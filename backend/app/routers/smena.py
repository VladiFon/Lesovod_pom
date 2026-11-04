# -*- coding: utf-8 -*-
"""«Отчёт за смену» — понятный отчёт тракториста (и любого рабочего) с
телефона (просьба Влада 03.11.2026).

Виды работы (vid):
  trelevka    — трелёвка: делянка, рейсы, м³, часы;
  naseleniyu  — вывозка населению: делянка, кому, рейсы, м³, часы;
  uhod        — уход за лесными культурами: участок, сделано га, часы;
  pochva      — подготовка почвы: участок, сделано га, часы;
  remont      — ремонт техники: что чинили, часы.

Напарники: отчёт один на всех (объёмы не задваиваются), напарники
записываются в otchet_smeny_uchastnik — у каждого из них отчёт виден в
«Моих отчётах» и считается в его рейтинг. Список напарников в телефоне
отсортирован по тому, как часто человек с ними работал.

Остаток по участку (uhod / pochva): участок проходят не за один день и не
одним трактором — «цикл» = сумма га всех отчётов этого вида по участку с
последнего закрытия. Когда сумма дошла до площади участка (или человек
отметил «участок пройден»), цикл закрывается: отчёт помечается
zakryl_cikl=1, а в журнал участка лесокультур пишется мероприятие
(«Агротехнический уход» / «Подготовка почвы») — так уход попадает в
карточку участка и в «Огород уходов».

Трелёвка дублируется в старую таблицу trelevka (по одной строке на
участника, объём поровну), чтобы её видели экран «Трелёвка» и рейтинг.

Телефон: /api/bot/smena/* (только worker-login, identity из токена).
Сайт: GET /api/smena (офис/мастер)."""
import json
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import db/webext
import db as legacy_db
import webext

from app.auth import require_office_or_master, require_permission
from app.database import get_conn

router = APIRouter(prefix="/api/bot/smena", tags=["smena"])
web_router = APIRouter(prefix="/api/smena", tags=["smena"])

SCHEMA = """
CREATE TABLE IF NOT EXISTS otchet_smeny (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sotrudnik_id INTEGER NOT NULL REFERENCES sotrudniki(id),
    data TEXT NOT NULL,
    vid TEXT NOT NULL,
    delyanka_item_id INTEGER REFERENCES delyanka_item(id),
    lesokultury_uchastok_id INTEGER REFERENCES lesokultury_uchastok(id),
    reysov INTEGER,
    obyom REAL,
    ga REAL,
    chasy REAL,
    poluchatel TEXT,
    tehnika TEXT,
    kommentariy TEXT,
    zakryl_cikl INTEGER NOT NULL DEFAULT 0,
    meropriyatie_id INTEGER,
    client_id TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_otchet_smeny_data ON otchet_smeny(data);
CREATE INDEX IF NOT EXISTS idx_otchet_smeny_uch ON otchet_smeny(lesokultury_uchastok_id, vid);
CREATE UNIQUE INDEX IF NOT EXISTS idx_otchet_smeny_client ON otchet_smeny(sotrudnik_id, client_id);
CREATE TABLE IF NOT EXISTS otchet_smeny_uchastnik (
    otchet_id INTEGER NOT NULL REFERENCES otchet_smeny(id),
    sotrudnik_id INTEGER NOT NULL REFERENCES sotrudniki(id),
    trelevka_id INTEGER,
    PRIMARY KEY (otchet_id, sotrudnik_id)
);
"""

VIDY = {
    "trelevka": {"title": "Трелёвка", "emoji": "🚜"},
    "naseleniyu": {"title": "Вывозка населению", "emoji": "🏠"},
    "uhod": {"title": "Уход за культурами", "emoji": "🌱", "meropriyatie": "Агротехнический уход"},
    "pochva": {"title": "Подготовка почвы", "emoji": "🪚", "meropriyatie": "Подготовка почвы"},
    "remont": {"title": "Ремонт", "emoji": "🔧"},
}
PO_UCHASTKU = ("uhod", "pochva")
ZAKRYT_DOLYA = 0.98  # 98% площади — участок считаем пройденным (округления га)
MAX_CHASOV = 24


def ensure(conn):
    conn.executescript(SCHEMA)


def _d(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _r(v):
    return round(v, 2) if v is not None else None


# ---------------------------------------------------------------- остатки ---

def cikly(conn, uchastok_ids=None):
    """{(uchastok_id, vid): {"sdelano": га в открытом цикле, "otchetov": n,
    "posledniy": дата, "zakryto_raz": n, "zakryt": дата последнего закрытия}}"""
    ensure(conn)
    q = ("SELECT lesokultury_uchastok_id, vid, ga, zakryl_cikl, data FROM otchet_smeny "
         "WHERE deleted=0 AND lesokultury_uchastok_id IS NOT NULL AND vid IN ('uhod','pochva')")
    args = []
    if uchastok_ids:
        q += f" AND lesokultury_uchastok_id IN ({','.join('?' * len(uchastok_ids))})"
        args = list(uchastok_ids)
    out = {}
    # По порядку ввода: закрытие цикла — событие в момент отправки отчёта.
    for uid, vid, ga, zakryl, data in conn.execute(q + " ORDER BY id", args).fetchall():
        x = out.setdefault((uid, vid), {"sdelano": 0.0, "otchetov": 0, "posledniy": None, "zakryto_raz": 0,
                                        "zakryt": None})
        if zakryl:
            x.update(sdelano=0.0, otchetov=0, zakryto_raz=x["zakryto_raz"] + 1, zakryt=data)
        else:
            x["sdelano"] += ga or 0
            x["otchetov"] += 1
            x["posledniy"] = data
    return out


def _ostatok(ploshad, sdelano):
    if not ploshad:
        return None
    return round(max(ploshad - sdelano, 0), 2)


# ---------------------------------------------------------------- справочник ---

def _label_item(kv, vd, les, nazv):
    s = f"кв.{kv or '—'} выд.{vd or '—'}"
    if les:
        s += f" · л.{les}"
    return s + (f" — {nazv}" if nazv else "")


def _label_uch(lesn, kv, vd, poroda, god):
    s = f"кв.{kv or '—'} выд.{vd or '—'}"
    extra = ", ".join(x for x in (poroda, str(god) if god else None) if x)
    return s + (f" · {extra}" if extra else "") + (f" · {lesn}" if lesn else "")


def naparniki(conn, sid):
    """Все активные сотрудники кроме себя: сначала частые напарники (по
    отчётам смены — вес 3, по табелю: в один день на одном месте — вес 1)."""
    ensure(conn)
    raz = {}
    for (oid,) in conn.execute(
        """SELECT o.id FROM otchet_smeny o WHERE o.deleted=0 AND (o.sotrudnik_id=?
           OR o.id IN (SELECT otchet_id FROM otchet_smeny_uchastnik WHERE sotrudnik_id=?))""", (sid, sid)).fetchall():
        for (other,) in conn.execute(
            "SELECT sotrudnik_id FROM otchet_smeny_uchastnik WHERE otchet_id=? UNION "
            "SELECT sotrudnik_id FROM otchet_smeny WHERE id=?", (oid, oid)).fetchall():
            if other != sid:
                raz[other] = raz.get(other, 0) + 3
    ot = (date.today() - timedelta(days=120)).isoformat()
    for other, n in conn.execute(
        """SELECT b.sotrudnik_id, COUNT(*) FROM tabel_zapis a JOIN tabel_zapis b
             ON a.data = b.data AND a.sotrudnik_id <> b.sotrudnik_id
            AND ((a.delyanka_item_id IS NOT NULL AND a.delyanka_item_id = b.delyanka_item_id)
              OR (a.lesokultury_uchastok_id IS NOT NULL AND a.lesokultury_uchastok_id = b.lesokultury_uchastok_id))
           WHERE a.sotrudnik_id = ? AND a.status='работал' AND b.status='работал' AND a.data >= ?
           GROUP BY b.sotrudnik_id""", (sid, ot)).fetchall():
        raz[other] = raz.get(other, 0) + n
    out = [{"id": i, "fio": f, "dolzhnost": d, "raz": raz.get(i, 0)}
           for i, f, d in conn.execute("SELECT id, fio, dolzhnost FROM sotrudniki WHERE is_active=1 AND id<>?", (sid,))]
    out.sort(key=lambda x: (-x["raz"], x["fio"] or ""))
    return out


def spravochnik(conn, sid):
    ensure(conn)
    moi_items, moi_uch = {}, {}
    for iid, uid, data in conn.execute(
        """SELECT delyanka_item_id, lesokultury_uchastok_id, MAX(data) FROM otchet_smeny
           WHERE deleted=0 AND (sotrudnik_id=? OR id IN (SELECT otchet_id FROM otchet_smeny_uchastnik WHERE sotrudnik_id=?))
           GROUP BY delyanka_item_id, lesokultury_uchastok_id""", (sid, sid)).fetchall():
        if iid:
            moi_items[iid] = data
        if uid:
            moi_uch[uid] = data
    delyanki = []
    for iid, did, kv, vd, les, nazv in conn.execute(
        """SELECT di.id, d.id, di.kvartal, di.vydel, di.lesoseka_nomer, d.nazvanie
           FROM delyanka_item di JOIN delyanka d ON d.id = di.delyanka_id
           WHERE d.status = 'активна' ORDER BY d.nazvanie, di.poryadok, di.id""").fetchall():
        delyanki.append({"item_id": iid, "delyanka_id": did, "kvartal": kv, "vydel": vd,
                         "label": _label_item(kv, vd, les, nazv), "nedavno": moi_items.get(iid)})
    delyanki.sort(key=lambda x: (x["nedavno"] is None, "" if x["nedavno"] is None else _neg(x["nedavno"]), x["label"]))

    c = cikly(conn)
    uchastki = []
    for uid, lesn, kv, vd, pl, por, god in conn.execute(
        """SELECT id, lesnichestvo, kvartal, vydel, ploshad, glavnaya_poroda, god_sozdaniya
           FROM lesokultury_uchastok WHERE COALESCE(status,'активен') NOT IN ('списан','переведён','переведен')
           ORDER BY lesnichestvo, CAST(kvartal AS INTEGER), kvartal, vydel""").fetchall():
        x = {"id": uid, "kvartal": kv, "vydel": vd, "ploshad": pl, "label": _label_uch(lesn, kv, vd, por, god),
             "nedavno": moi_uch.get(uid)}
        for vid in PO_UCHASTKU:
            cy = c.get((uid, vid))
            if cy and cy["otchetov"]:
                x[vid] = {"sdelano": _r(cy["sdelano"]), "ostatok": _ostatok(pl, cy["sdelano"]), "otchetov": cy["otchetov"],
                          "posledniy": cy["posledniy"]}
        uchastki.append(x)
    uchastki.sort(key=lambda x: (not (x.get("uhod") or x.get("pochva")), x["nedavno"] is None,
                                 "" if x["nedavno"] is None else _neg(x["nedavno"])))
    poluchateli = [r[0] for r in conn.execute(
        "SELECT poluchatel FROM otchet_smeny WHERE deleted=0 AND poluchatel IS NOT NULL AND poluchatel<>'' "
        "GROUP BY poluchatel ORDER BY MAX(id) DESC LIMIT 15").fetchall()]
    tehnika = [r[0] for r in conn.execute(
        "SELECT tehnika FROM otchet_smeny WHERE deleted=0 AND sotrudnik_id=? AND tehnika IS NOT NULL AND tehnika<>'' "
        "GROUP BY tehnika ORDER BY MAX(id) DESC LIMIT 10", (sid,)).fetchall()]
    return {"vidy": VIDY, "delyanki": delyanki, "uchastki": uchastki, "naparniki": naparniki(conn, sid),
            "poluchateli": poluchateli, "tehnika": tehnika}


def _neg(s):
    """Строка-дата для сортировки «свежие сверху» внутри возрастающей сортировки."""
    return "".join(chr(255 - ord(ch)) for ch in s)


# ---------------------------------------------------------------- запись ---

class SmenaIn(BaseModel):
    vid: str
    data: Optional[str] = None
    delyanka_item_id: Optional[int] = None
    lesokultury_uchastok_id: Optional[int] = None
    reysov: Optional[int] = None
    obyom: Optional[float] = None
    ga: Optional[float] = None
    chasy: Optional[float] = None
    poluchatel: Optional[str] = None
    tehnika: Optional[str] = None
    kommentariy: Optional[str] = None
    uchastok_proyden: bool = False
    naparniki: List[int] = []
    client_id: Optional[str] = None


def _proverit(conn, b: SmenaIn, segodnya):
    if b.vid not in VIDY:
        raise HTTPException(400, "Неизвестный вид работы")
    d = _d(b.data) if b.data else segodnya
    if not d:
        raise HTTPException(400, "Дата в формате ГГГГ-ММ-ДД")
    if d > segodnya:
        raise HTTPException(400, "Нельзя отчитаться за будущий день")
    if (segodnya - d).days > 14:
        raise HTTPException(400, "Отчёт можно внести не позже чем за 2 недели — старше вносит мастер")
    if b.chasy is not None and not (0 <= b.chasy <= MAX_CHASOV):
        raise HTTPException(400, "Часы — от 0 до 24")
    if b.vid in ("trelevka", "naseleniyu"):
        if not b.delyanka_item_id:
            raise HTTPException(400, "Выбери делянку")
        if not b.obyom or b.obyom <= 0:
            raise HTTPException(400, "Укажи кубы")
        if b.reysov is not None and b.reysov < 0:
            raise HTTPException(400, "Рейсы — не меньше нуля")
        if b.vid == "naseleniyu" and not (b.poluchatel or "").strip():
            raise HTTPException(400, "Укажи, кому везли")
        if not conn.execute("SELECT 1 FROM delyanka_item WHERE id=?", (b.delyanka_item_id,)).fetchone():
            raise HTTPException(404, "Делянка не найдена")
    if b.vid in PO_UCHASTKU:
        if not b.lesokultury_uchastok_id:
            raise HTTPException(400, "Выбери участок")
        if not conn.execute("SELECT 1 FROM lesokultury_uchastok WHERE id=?", (b.lesokultury_uchastok_id,)).fetchone():
            raise HTTPException(404, "Участок не найден")
        if (b.ga is None or b.ga <= 0) and not b.uchastok_proyden:
            raise HTTPException(400, "Укажи, сколько га сделал")
    if b.vid == "remont":
        if not b.chasy:
            raise HTTPException(400, "Укажи, сколько часов был ремонт")
        if not (b.tehnika or b.kommentariy or "").strip():
            raise HTTPException(400, "Напиши, что ремонтировали")
    return d


def sozdat(conn, sid, fio, b: SmenaIn, segodnya=None):
    ensure(conn)
    segodnya = segodnya or date.today()
    d = _proverit(conn, b, segodnya)
    if b.client_id:
        est = conn.execute("SELECT id FROM otchet_smeny WHERE sotrudnik_id=? AND client_id=?", (sid, b.client_id)).fetchone()
        if est:  # повтор из очереди без сети — уже записан
            return {"id": est[0], "povtor": True, **_posle(conn, est[0])}
    nap = sorted({i for i in b.naparniki if i and i != sid})
    if nap:
        ok = {r[0] for r in conn.execute(
            f"SELECT id FROM sotrudniki WHERE is_active=1 AND id IN ({','.join('?' * len(nap))})", nap).fetchall()}
        nap = [i for i in nap if i in ok]
    cur = conn.execute(
        """INSERT INTO otchet_smeny (sotrudnik_id, data, vid, delyanka_item_id, lesokultury_uchastok_id, reysov, obyom, ga,
           chasy, poluchatel, tehnika, kommentariy, client_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, d.isoformat(), b.vid, b.delyanka_item_id if b.vid in ("trelevka", "naseleniyu") else None,
         b.lesokultury_uchastok_id if b.vid in PO_UCHASTKU else None, b.reysov, b.obyom, b.ga, b.chasy,
         (b.poluchatel or "").strip()[:120] or None, (b.tehnika or "").strip()[:120] or None,
         (b.kommentariy or "").strip()[:1000] or None, b.client_id))
    oid = cur.lastrowid
    uchastniki = [sid] + nap
    trel_ids = {}
    if b.vid == "trelevka":
        # Совместимость: экран «Трелёвка» и рейтинг читают таблицу trelevka.
        item = conn.execute("SELECT kvartal, vydel FROM delyanka_item WHERE id=?", (b.delyanka_item_id,)).fetchone()
        otkuda = f"кв.{item[0]} выд.{item[1]}" if item else "делянка"
        dolya = b.obyom / len(uchastniki)
        for u in uchastniki:
            c2 = conn.execute(
                "INSERT INTO trelevka (sotrudnik_id, delyanka_item_id, otkuda, kuda, obyom, created_at) VALUES (?,?,?,?,?,?)",
                (u, b.delyanka_item_id, otkuda, "верхний склад", round(dolya, 3), f"{d.isoformat()} 12:00:00"))
            trel_ids[u] = c2.lastrowid
    for u in nap:
        conn.execute("INSERT OR IGNORE INTO otchet_smeny_uchastnik (otchet_id, sotrudnik_id, trelevka_id) VALUES (?,?,?)",
                     (oid, u, trel_ids.get(u)))
    if trel_ids.get(sid):
        conn.execute("INSERT OR IGNORE INTO otchet_smeny_uchastnik (otchet_id, sotrudnik_id, trelevka_id) VALUES (?,?,?)",
                     (oid, sid, trel_ids[sid]))
    conn.commit()

    zakryt = None
    if b.vid in PO_UCHASTKU:
        zakryt = _zakryt_esli_proyden(conn, oid, b.lesokultury_uchastok_id, b.vid, d, sid, b.uchastok_proyden)
    _uvedomit(conn, oid, fio, b, nap)
    return {"id": oid, **_posle(conn, oid), "zakryt_cikl": zakryt}


def _zakryt_esli_proyden(conn, oid, uid, vid, d, sid, rukami):
    pl = conn.execute("SELECT ploshad FROM lesokultury_uchastok WHERE id=?", (uid,)).fetchone()
    pl = pl[0] if pl else None
    cy = cikly(conn, [uid]).get((uid, vid)) or {"sdelano": 0.0}
    if not (rukami or (pl and cy["sdelano"] >= pl * ZAKRYT_DOLYA)):
        return None
    fio = [r[0] for r in conn.execute(
        """SELECT DISTINCT s.fio FROM otchet_smeny o JOIN sotrudniki s ON s.id = o.sotrudnik_id
           WHERE o.deleted=0 AND o.lesokultury_uchastok_id=? AND o.vid=? AND o.zakryl_cikl=0
             AND o.id > (SELECT COALESCE(MAX(id), 0) FROM otchet_smeny WHERE deleted=0 AND zakryl_cikl=1
                         AND lesokultury_uchastok_id=? AND vid=?)""", (uid, vid, uid, vid)).fetchall()]
    sdelano = cy["sdelano"]
    mid = legacy_db.add_lesokultury_meropriyatie(
        conn, uid, VIDY[vid]["meropriyatie"], d.strftime("%d.%m.%Y"),
        primechaniya=f"По отчётам за смену с телефона: {sdelano:g} га" + (f" из {pl:g}" if pl else "")
                     + (f"; работали: {', '.join(fio)}" if fio else ""),
        dannye={"istochnik": "otchet_smeny", "ga": sdelano}, sotrudnik_id=sid)
    # Закрывающий отчёт входит в закрытый цикл; новый цикл — со следующего отчёта.
    conn.execute("UPDATE otchet_smeny SET zakryl_cikl=1, meropriyatie_id=? WHERE id=?", (mid, oid))
    conn.commit()
    return {"meropriyatie_id": mid, "tip": VIDY[vid]["meropriyatie"], "sdelano": _r(sdelano), "ploshad": pl}


def _posle(conn, oid):
    """Что показать человеку после отправки: остаток по участку."""
    r = conn.execute("SELECT lesokultury_uchastok_id, vid FROM otchet_smeny WHERE id=?", (oid,)).fetchone()
    if not r or not r[0] or r[1] not in PO_UCHASTKU:
        return {}
    pl = conn.execute("SELECT ploshad FROM lesokultury_uchastok WHERE id=?", (r[0],)).fetchone()
    cy = cikly(conn, [r[0]]).get((r[0], r[1])) or {"sdelano": 0.0}
    return {"ostatok": _ostatok(pl[0] if pl else None, cy["sdelano"]), "sdelano_v_cikle": _r(cy["sdelano"]),
            "ploshad": pl[0] if pl else None}


def _uvedomit(conn, oid, fio, b, nap):
    v = VIDY[b.vid]
    chto = []
    if b.obyom:
        chto.append(f"{b.obyom:g} м³")
    if b.reysov:
        chto.append(f"{b.reysov} рейс.")
    if b.ga:
        chto.append(f"{b.ga:g} га")
    if b.chasy:
        chto.append(f"{b.chasy:g} ч")
    s = f"{v['emoji']} {v['title']}: {fio}" + (f" (+{len(nap)} напарн.)" if nap else "") + (" — " + ", ".join(chto) if chto else "")
    try:
        webext.notify(conn, "smena", s, related_id=oid)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- списки ---

def _stroki(conn, where, args, limit=300):
    ensure(conn)
    rows = conn.execute(
        f"""SELECT o.id, o.sotrudnik_id, s.fio, o.data, o.vid, o.delyanka_item_id, di.kvartal, di.vydel, di.lesoseka_nomer,
                   d.nazvanie, o.lesokultury_uchastok_id, lu.kvartal, lu.vydel, lu.lesnichestvo, lu.ploshad, o.reysov,
                   o.obyom, o.ga, o.chasy, o.poluchatel, o.tehnika, o.kommentariy, o.zakryl_cikl, o.created_at
            FROM otchet_smeny o
            JOIN sotrudniki s ON s.id = o.sotrudnik_id
            LEFT JOIN delyanka_item di ON di.id = o.delyanka_item_id
            LEFT JOIN delyanka d ON d.id = di.delyanka_id
            LEFT JOIN lesokultury_uchastok lu ON lu.id = o.lesokultury_uchastok_id
            WHERE o.deleted=0 AND {where} ORDER BY o.data DESC, o.id DESC LIMIT {int(limit)}""", args).fetchall()
    ids = [r[0] for r in rows]
    nap = {}
    if ids:
        for oid, sid, f in conn.execute(
                f"""SELECT u.otchet_id, u.sotrudnik_id, s.fio FROM otchet_smeny_uchastnik u JOIN sotrudniki s ON s.id=u.sotrudnik_id
                    WHERE u.otchet_id IN ({','.join('?' * len(ids))})""", ids).fetchall():
            nap.setdefault(oid, []).append({"id": sid, "fio": f})
    out = []
    for r in rows:
        mesto = None
        if r[5]:
            mesto = _label_item(r[6], r[7], r[8], r[9])
        elif r[10]:
            mesto = _label_uch(r[13], r[11], r[12], None, None)
        out.append({
            "id": r[0], "sotrudnik_id": r[1], "fio": r[2], "data": r[3], "vid": r[4], "vid_title": VIDY.get(r[4], {}).get("title", r[4]),
            "emoji": VIDY.get(r[4], {}).get("emoji", "•"), "delyanka_item_id": r[5], "lesokultury_uchastok_id": r[10],
            "mesto": mesto, "ploshad_uchastka": r[14], "reysov": r[15], "obyom": r[16], "ga": r[17], "chasy": r[18],
            "poluchatel": r[19], "tehnika": r[20], "kommentariy": r[21], "zakryl_cikl": bool(r[22]), "created_at": r[23],
            "naparniki": [n for n in nap.get(r[0], []) if n["id"] != r[1]],
        })
    return out


def moi(conn, sid, dney=14, segodnya=None):
    segodnya = segodnya or date.today()
    ot = (segodnya - timedelta(days=dney)).isoformat()
    rows = _stroki(conn, "o.data >= ? AND (o.sotrudnik_id=? OR o.id IN (SELECT otchet_id FROM otchet_smeny_uchastnik "
                         "WHERE sotrudnik_id=?))", (ot, sid, sid))
    for r in rows:
        r["moy"] = r["sotrudnik_id"] == sid
        r["mozhno_udalit"] = r["moy"] and r["data"] >= (segodnya - timedelta(days=1)).isoformat()
    sevodnya = [r for r in rows if r["data"] == segodnya.isoformat()]
    itog = {
        "chasy": round(sum(r["chasy"] or 0 for r in sevodnya), 1),
        "obyom": round(sum(r["obyom"] or 0 for r in sevodnya if r["vid"] in ("trelevka", "naseleniyu")), 2),
        "reysov": sum(r["reysov"] or 0 for r in sevodnya),
        "ga": round(sum(r["ga"] or 0 for r in sevodnya), 2),
        "otchetov": len(sevodnya),
    }
    return {"otchety": rows, "segodnya": itog}


# ---------------------------------------------------------------- роуты ---

def _worker(user):
    if user.get("role") != "worker" or not user.get("sotrudnik_id"):
        raise HTTPException(403, "Доступно только учётным записям рабочих (worker-login)")


@router.get("/spravochnik")
def get_spravochnik(conn=Depends(get_conn), user=Depends(require_permission("bot.access"))):
    _worker(user)
    return spravochnik(conn, user["sotrudnik_id"])


@router.post("")
def post_smena(body: SmenaIn, conn=Depends(get_conn), user=Depends(require_permission("bot.access"))):
    _worker(user)
    return sozdat(conn, user["sotrudnik_id"], user.get("fio") or "", body)


@router.get("/moi")
def get_moi(dney: int = 14, conn=Depends(get_conn), user=Depends(require_permission("bot.access"))):
    _worker(user)
    return moi(conn, user["sotrudnik_id"], max(1, min(dney, 60)))


@router.delete("/{oid}")
def delete_smena(oid: int, conn=Depends(get_conn), user=Depends(require_permission("bot.access"))):
    """Удалить свой отчёт — только автор и только за сегодня/вчера (ошибся
    при вводе). Закрытый цикл участка не откатывается — это делает мастер."""
    _worker(user)
    ensure(conn)
    r = conn.execute("SELECT sotrudnik_id, data, zakryl_cikl FROM otchet_smeny WHERE id=? AND deleted=0", (oid,)).fetchone()
    if not r or r[0] != user["sotrudnik_id"]:
        raise HTTPException(404, "Отчёт не найден")
    if r[1] < (date.today() - timedelta(days=1)).isoformat():
        raise HTTPException(400, "Удалить можно только отчёт за сегодня или вчера — старше правит мастер")
    if r[2]:
        raise HTTPException(400, "Этим отчётом участок закрыт — удалить его может мастер")
    _udalit(conn, oid)
    return {"ok": True}


def _udalit(conn, oid):
    for (tid,) in conn.execute("SELECT trelevka_id FROM otchet_smeny_uchastnik WHERE otchet_id=? AND trelevka_id IS NOT NULL",
                               (oid,)).fetchall():
        conn.execute("DELETE FROM trelevka WHERE id=?", (tid,))
    conn.execute("UPDATE otchet_smeny SET deleted=1 WHERE id=?", (oid,))
    conn.commit()


@web_router.get("")
def web_list(date_from: Optional[str] = None, date_to: Optional[str] = None, vid: Optional[str] = None,
             sotrudnik_id: Optional[int] = None, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    ensure(conn)
    where, args = ["1=1"], []
    if date_from:
        where.append("o.data >= ?")
        args.append(date_from)
    if date_to:
        where.append("o.data <= ?")
        args.append(date_to)
    if vid:
        where.append("o.vid = ?")
        args.append(vid)
    if sotrudnik_id:
        where.append("(o.sotrudnik_id = ? OR o.id IN (SELECT otchet_id FROM otchet_smeny_uchastnik WHERE sotrudnik_id = ?))")
        args += [sotrudnik_id, sotrudnik_id]
    rows = _stroki(conn, " AND ".join(where), args, limit=1000)
    # Открытые циклы по участкам — «что недоделано».
    c = cikly(conn)
    otkrytye = []
    if c:
        uids = sorted({u for (u, _v), x in c.items() if x["otchetov"]})
        info = {}
        if uids:
            for uid, lesn, kv, vd, pl in conn.execute(
                    f"SELECT id, lesnichestvo, kvartal, vydel, ploshad FROM lesokultury_uchastok WHERE id IN ({','.join('?' * len(uids))})",
                    uids).fetchall():
                info[uid] = (_label_uch(lesn, kv, vd, None, None), pl)
        for (uid, v), x in c.items():
            if x["otchetov"] and uid in info:
                otkrytye.append({"uchastok_id": uid, "mesto": info[uid][0], "vid": v, "vid_title": VIDY[v]["title"],
                                 "sdelano": _r(x["sdelano"]), "ploshad": info[uid][1],
                                 "ostatok": _ostatok(info[uid][1], x["sdelano"]), "posledniy": x["posledniy"]})
    return {"otchety": rows, "otkrytye": sorted(otkrytye, key=lambda x: x["posledniy"] or "", reverse=True), "vidy": VIDY}


@web_router.delete("/{oid}")
def web_delete(oid: int, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    """Мастер удаляет ошибочный отчёт. Если им был закрыт участок — удаляется
    и созданная запись в журнале лесокультур."""
    ensure(conn)
    r = conn.execute("SELECT meropriyatie_id FROM otchet_smeny WHERE id=? AND deleted=0", (oid,)).fetchone()
    if not r:
        raise HTTPException(404, "Отчёт не найден")
    if r[0]:
        conn.execute("DELETE FROM lesokultury_meropriyatiya WHERE id=?", (r[0],))
    _udalit(conn, oid)
    return {"ok": True}
