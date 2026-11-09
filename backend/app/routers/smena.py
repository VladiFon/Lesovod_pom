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
Сайт: GET /api/smena (офис/мастер).

04.11.2026 (Влад): экран смены по профессиям —
  тракторист  — trelevka/naseleniyu/uhod/pochva/remont, без напарников;
  харвестерщик — harvester (делянка + м³, видит остаток по билету), remont;
  вальщик/лесоруб/лесовод — rubka_gp, rubka_uhoda, sanrubka, ochistka (по
    делянке), uhod, posadka, pochva (по участку культур), drugoe; напарники —
    только не-машинисты (трактористов/харвестерщиков отмечать нельзя).
Рубки ухода / очистка / санрубка копят га по выделу делянки (delyanka_item)
так же, как уход по участку: «сделано X из Y га, осталось Z».
Техника — справочник tehnika (app/routers/tehnika.py), за человеком можно
закрепить машину; в отчёте tehnika_id + расход топлива и заправка (л),
тип топлива (ДТ / АИ-92) берётся из машины. Сводка — GET /api/smena/toplivo."""
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
CREATE TABLE IF NOT EXISTS tehnika (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT NOT NULL,
    tip TEXT,
    nomer TEXT,
    toplivo TEXT,
    zakreplen_sotrudnik_id INTEGER REFERENCES sotrudniki(id),
    kommentariy TEXT,
    aktivna INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""

# Колонки, добавленные 04.11.2026 к уже созданной otchet_smeny.
NOVYE_KOLONKI = (
    ("tehnika_id", "INTEGER"),
    ("toplivo", "TEXT"),
    ("toplivo_rashod", "REAL"),
    ("zapravka", "REAL"),
    # рубка ухода по пробе экрана «Рубки ухода» (app/uhody_vypolnenie.py)
    ("uhody_proba_id", "INTEGER"),
)
TOPLIVO = ("ДТ", "АИ-92")
MAX_LITROV = 2000

VIDY = {
    "trelevka": {"title": "Трелёвка", "emoji": "🚜"},
    "naseleniyu": {"title": "Вывозка населению", "emoji": "🏠"},
    "uhod": {"title": "Уход за культурами", "emoji": "🌱", "meropriyatie": "Агротехнический уход"},
    "pochva": {"title": "Подготовка почвы", "emoji": "🪚", "meropriyatie": "Подготовка почвы"},
    "remont": {"title": "Ремонт", "emoji": "🔧"},
    # харвестерщик
    "harvester": {"title": "Заготовка харвестером", "emoji": "🌲"},
    # вальщик / лесоруб / лесовод
    "rubka_gp": {"title": "Рубка (валка)", "emoji": "🪓"},
    "rubka_uhoda": {"title": "Рубка ухода", "emoji": "✂️"},
    "sanrubka": {"title": "Санитарная рубка", "emoji": "🪵"},
    "ochistka": {"title": "Очистка мест рубок", "emoji": "🧹"},
    "posadka": {"title": "Посадка / дополнение", "emoji": "🌿"},
    "drugoe": {"title": "Другое", "emoji": "✍️"},
}
PO_UCHASTKU = ("uhod", "pochva", "posadka")
# Работы по делянке, где копятся га по выделу (сделано / осталось).
PO_ITEM_GA = ("rubka_uhoda", "sanrubka", "ochistka")
# Работы по делянке с кубами.
PO_DELYANKE = ("trelevka", "naseleniyu", "harvester", "rubka_gp") + PO_ITEM_GA
# Работы, которые можно вести и по выделу делянки, и по участку лесных
# культур (рубка ухода в культурах): если в отчёте пришёл участок — цикл
# копится по участку, иначе по выделу делянки.
UCHASTOK_ILI_DELYANKA = ("rubka_uhoda",)
CIKLY_UCHASTKA = PO_UCHASTKU + UCHASTOK_ILI_DELYANKA
# Запись в журнал участка при закрытии цикла для видов без своей «meropriyatie».
MEROPR_NA_UCHASTKE = {"rubka_uhoda": "Уход (рубки ухода)"}


def po_uchastku(vid, uchastok_id):
    """Отчёт копит га по участку лесных культур?"""
    return vid in PO_UCHASTKU or (vid in UCHASTOK_ILI_DELYANKA and bool(uchastok_id))
# Что видит какая профессия (телефон строит кнопки по этому списку).
VIDY_PROFESSII = {
    "traktorist": ["trelevka", "naseleniyu", "uhod", "pochva", "remont"],
    "harvester": ["harvester", "remont"],
    "brigada": ["rubka_gp", "rubka_uhoda", "sanrubka", "ochistka", "uhod", "posadka", "pochva", "drugoe"],
}


def vidy_professii():
    """Профессии и их кнопки: у издания «лесопункт» свой набор
    (вальщик / тракторист на вывозке / харвестерщик, app/izdanie.py)."""
    from app import izdanie
    prof = izdanie.opisanie()["professii"]
    if not prof:
        return VIDY_PROFESSII
    return {k: list(v["vidy"]) for k, v in prof.items()}


# Куда в отчёте кубы «заготовлено» (для остатка по делянке).
ZAGOTOVKA = ("harvester", "rubka_gp")
ZAKRYT_DOLYA = 0.98  # 98% площади — участок считаем пройденным (округления га)
MAX_CHASOV = 24


def ensure(conn):
    conn.executescript(SCHEMA)
    est = {r[1] for r in conn.execute("PRAGMA table_info(otchet_smeny)").fetchall()}
    for kol, tip in NOVYE_KOLONKI:
        if kol not in est:
            conn.execute(f"ALTER TABLE otchet_smeny ADD COLUMN {kol} {tip}")


def mashinist(dolzhnost):
    """Тракторист / харвестерщик / форвардер — их нельзя отмечать
    напарниками в отчёте бригады (они отчитываются сами за свою технику)."""
    d = (dolzhnost or "").lower()
    return any(x in d for x in ("трактор", "машинист", "харвест", "форвард"))


def _f(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


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
         f"WHERE deleted=0 AND lesokultury_uchastok_id IS NOT NULL AND vid IN ({','.join('?' * len(CIKLY_UCHASTKA))})")
    args = list(CIKLY_UCHASTKA)
    if uchastok_ids:
        q += f" AND lesokultury_uchastok_id IN ({','.join('?' * len(uchastok_ids))})"
        args += list(uchastok_ids)
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


def cikly_items(conn, item_ids=None):
    """То же, что cikly(), но по выделу делянки для рубок ухода / очистки /
    санрубки: {(delyanka_item_id, vid): {...}}."""
    ensure(conn)
    q = ("SELECT delyanka_item_id, vid, ga, zakryl_cikl, data FROM otchet_smeny "
         f"WHERE deleted=0 AND delyanka_item_id IS NOT NULL AND vid IN ({','.join('?' * len(PO_ITEM_GA))})")
    args = list(PO_ITEM_GA)
    if item_ids:
        q += f" AND delyanka_item_id IN ({','.join('?' * len(item_ids))})"
        args += list(item_ids)
    out = {}
    for iid, vid, ga, zakryl, data in conn.execute(q + " ORDER BY id", args).fetchall():
        x = out.setdefault((iid, vid), {"sdelano": 0.0, "otchetov": 0, "posledniy": None, "zakryto_raz": 0,
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
           for i, f, d in conn.execute("SELECT id, fio, dolzhnost FROM sotrudniki WHERE is_active=1 AND id<>?", (sid,))
           if not mashinist(d)]
    out.sort(key=lambda x: (-x["raz"], x["fio"] or ""))
    return out


def spravochnik(conn, sid, vse_kultury=False):
    """vse_kultury — телефон 0.11.2+: отдать и списанные / переведённые
    участки культур (с полем status), прячет их телефон по переключателю."""
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
    ci = cikly_items(conn)
    for iid, did, kv, vd, les, nazv, pl in conn.execute(
        """SELECT di.id, d.id, di.kvartal, di.vydel, di.lesoseka_nomer, d.nazvanie, di.ploshad
           FROM delyanka_item di JOIN delyanka d ON d.id = di.delyanka_id
           WHERE d.status = 'активна' ORDER BY d.nazvanie, di.poryadok, di.id""").fetchall():
        pl = _f(pl)
        x = {"item_id": iid, "delyanka_id": did, "kvartal": kv, "vydel": vd, "ploshad": pl,
             "label": _label_item(kv, vd, les, nazv), "nedavno": moi_items.get(iid)}
        for vid in PO_ITEM_GA:
            cy = ci.get((iid, vid))
            if cy and cy["otchetov"]:
                x[vid] = {"sdelano": _r(cy["sdelano"]), "ostatok": _ostatok(pl, cy["sdelano"]), "otchetov": cy["otchetov"],
                          "posledniy": cy["posledniy"]}
        delyanki.append(x)
    osv = osvoenie(conn, sorted({x["delyanka_id"] for x in delyanki}))
    for x in delyanki:
        if osv.get(x["delyanka_id"]):
            x["osvoenie"] = osv[x["delyanka_id"]]
    delyanki.sort(key=lambda x: (x["nedavno"] is None, "" if x["nedavno"] is None else _neg(x["nedavno"]), x["label"]))

    c = cikly(conn)
    statusy = dict(conn.execute("SELECT id, status FROM lesokultury_uchastok").fetchall())
    uchastki = []
    for uid, lesn, kv, vd, pl, por, god in conn.execute(
        """SELECT id, lesnichestvo, kvartal, vydel, ploshad, glavnaya_poroda, god_sozdaniya
           FROM lesokultury_uchastok WHERE ? OR COALESCE(status,'активен') NOT IN ('списан','переведён','переведен')
           ORDER BY lesnichestvo, CAST(kvartal AS INTEGER), kvartal, vydel""", (1 if vse_kultury else 0,)).fetchall():
        x = {"id": uid, "kvartal": kv, "vydel": vd, "ploshad": pl, "label": _label_uch(lesn, kv, vd, por, god),
             "nedavno": moi_uch.get(uid), "status": statusy.get(uid)}
        for vid in CIKLY_UCHASTKA:
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
    mashiny, moya = spisok_tehniki(conn, sid)
    from app import uhody_vypolnenie
    proby = uhody_vypolnenie.dlya_telefona(conn, sid)
    return {"vidy": VIDY, "vidy_professii": vidy_professii(), "delyanki": delyanki, "uchastki": uchastki, "proby": proby,
            "naparniki": naparniki(conn, sid), "poluchateli": poluchateli, "tehnika": tehnika,
            "mashiny": mashiny, "moya_mashina_id": moya, "toplivo_vidy": list(TOPLIVO)}


def spisok_tehniki(conn, sid):
    """Активная техника: своя (закреплённая) сверху, потом на которой
    человек чаще работал, потом остальная по названию."""
    ensure(conn)
    raz = {i: n for i, n in conn.execute(
        "SELECT tehnika_id, COUNT(*) FROM otchet_smeny WHERE deleted=0 AND sotrudnik_id=? AND tehnika_id IS NOT NULL "
        "GROUP BY tehnika_id", (sid,)).fetchall()}
    out, moya = [], None
    for tid, naz, tip, nom, top, zak, fio in conn.execute(
            """SELECT t.id, t.nazvanie, t.tip, t.nomer, t.toplivo, t.zakreplen_sotrudnik_id, s.fio
               FROM tehnika t LEFT JOIN sotrudniki s ON s.id = t.zakreplen_sotrudnik_id
               WHERE t.aktivna=1""").fetchall():
        if zak == sid and moya is None:
            moya = tid
        out.append({"id": tid, "nazvanie": naz, "tip": tip, "nomer": nom, "toplivo": top,
                    "zakreplen": fio, "moya": zak == sid, "raz": raz.get(tid, 0),
                    "label": naz + (f" · {nom}" if nom else "")})
    out.sort(key=lambda x: (not x["moya"], -x["raz"], x["nazvanie"] or ""))
    return out, moya


def osvoenie(conn, delyanka_ids):
    """Остаток по делянке для харвестерщика/вальщика: лимит по билету минус
    заготовленное. Наряды пишутся раз в месяц, поэтому «заготовлено» —
    большее из (наряд, ЕГАИС, сумма отчётов с телефона по этой делянке)."""
    if not delyanka_ids:
        return {}
    try:
        import raskhod_v2 as legacy_raskhod
        batch = legacy_raskhod.compute_osvoenie_batch(conn, delyanka_ids)
    except Exception:  # noqa: BLE001 — нет МДО/ЕГАИС: остаток просто не покажем
        batch = {}
    po_otchetam = {d: v or 0 for d, v in conn.execute(
        f"""SELECT di.delyanka_id, SUM(o.obyom) FROM otchet_smeny o JOIN delyanka_item di ON di.id = o.delyanka_item_id
            WHERE o.deleted=0 AND o.vid IN ({','.join('?' * len(ZAGOTOVKA))}) GROUP BY di.delyanka_id""",
        list(ZAGOTOVKA)).fetchall()}
    out = {}
    for d in delyanka_ids:
        b = batch.get(d) or {}
        limit = b.get("limit") or 0
        if limit <= 0:
            continue
        fakt = max(b.get("fakt") or 0, po_otchetam.get(d, 0))
        out[d] = {"limit": _r(limit), "fakt_naryad": _r(b.get("fakt_naryad")), "fakt_egais": _r(b.get("fakt_egais")),
                  "po_otchetam": _r(po_otchetam.get(d, 0)), "fakt": _r(fakt), "ostatok": _r(limit - fakt),
                  "ostatok_110": _r(limit * 1.1 - fakt), "pct": round(fakt / limit * 100, 1)}
    return out


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
    tehnika_id: Optional[int] = None
    toplivo_rashod: Optional[float] = None
    zapravka: Optional[float] = None
    kommentariy: Optional[str] = None
    uchastok_proyden: bool = False
    # Рубка ухода по пробе «Рубок ухода» (телефон 0.11.2+): место = проба,
    # га идут в «Выполнение» пробы.
    uhody_proba_id: Optional[int] = None
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
    for v, nazv in ((b.toplivo_rashod, "Расход топлива"), (b.zapravka, "Заправка")):
        if v is not None and not (0 <= v <= MAX_LITROV):
            raise HTTPException(400, f"{nazv} — от 0 до {MAX_LITROV} л")
    if b.tehnika_id and not conn.execute("SELECT 1 FROM tehnika WHERE id=?", (b.tehnika_id,)).fetchone():
        raise HTTPException(404, "Техника не найдена")
    uch = po_uchastku(b.vid, b.lesokultury_uchastok_id)
    po_probe = b.vid == "rubka_uhoda" and bool(b.uhody_proba_id)
    if po_probe:
        uch = False
        r = conn.execute("SELECT delyanka_id FROM uhody_proby WHERE id=?", (b.uhody_proba_id,)).fetchone()
        if not r:
            raise HTTPException(404, "Проба не найдена")
        if r[0]:
            raise HTTPException(400, "Это проба хвороста делянки, а не рубки ухода")
        if (b.ga is None or b.ga <= 0) and not b.uchastok_proyden:
            raise HTTPException(400, "Укажи, сколько га сделал")
    if b.vid in PO_DELYANKE and not uch and not po_probe:
        if not b.delyanka_item_id:
            raise HTTPException(400, "Выбери делянку")
        if not conn.execute("SELECT 1 FROM delyanka_item WHERE id=?", (b.delyanka_item_id,)).fetchone():
            raise HTTPException(404, "Делянка не найдена")
    if b.vid in ("harvester",) and (not b.obyom or b.obyom <= 0):
        raise HTTPException(400, "Укажи кубы")
    if b.vid in ("rubka_uhoda", "ochistka") and not uch and not po_probe and (b.ga is None or b.ga <= 0) and not b.uchastok_proyden:
        raise HTTPException(400, "Укажи, сколько га сделал")
    if b.vid == "sanrubka" and not ((b.ga or 0) > 0 or (b.obyom or 0) > 0 or b.uchastok_proyden):
        raise HTTPException(400, "Укажи га или кубы")
    if b.vid == "drugoe" and not (b.kommentariy or "").strip():
        raise HTTPException(400, "Напиши, что делал")
    if b.vid in ("trelevka", "naseleniyu"):
        if not b.obyom or b.obyom <= 0:
            raise HTTPException(400, "Укажи кубы")
        if b.reysov is not None and b.reysov < 0:
            raise HTTPException(400, "Рейсы — не меньше нуля")
        if b.vid == "naseleniyu" and not (b.poluchatel or "").strip():
            raise HTTPException(400, "Укажи, кому везли")
    if uch:
        if not b.lesokultury_uchastok_id:
            raise HTTPException(400, "Выбери участок")
        if not conn.execute("SELECT 1 FROM lesokultury_uchastok WHERE id=?", (b.lesokultury_uchastok_id,)).fetchone():
            raise HTTPException(404, "Участок не найден")
        if (b.ga is None or b.ga <= 0) and not b.uchastok_proyden:
            raise HTTPException(400, "Укажи, сколько га сделал")
    if b.vid == "remont":
        if not b.chasy:
            raise HTTPException(400, "Укажи, сколько часов был ремонт")
        if not (b.tehnika or b.tehnika_id or b.kommentariy or "").strip():
            raise HTTPException(400, "Напиши, что ремонтировали")
    return d


def sozdat(conn, sid, fio, b: SmenaIn, segodnya=None):
    ensure(conn)
    segodnya = segodnya or date.today()
    d = _proverit(conn, b, segodnya)
    po_probe = b.vid == "rubka_uhoda" and bool(b.uhody_proba_id)
    uch = po_uchastku(b.vid, b.lesokultury_uchastok_id) and not po_probe
    if b.client_id:
        est = conn.execute("SELECT id FROM otchet_smeny WHERE sotrudnik_id=? AND client_id=?", (sid, b.client_id)).fetchone()
        if est:  # повтор из очереди без сети — уже записан
            return {"id": est[0], "povtor": True, **_posle(conn, est[0])}
    nap = sorted({i for i in b.naparniki if i and i != sid})
    if nap:
        ok = {r[0] for r in conn.execute(
            f"SELECT id, dolzhnost FROM sotrudniki WHERE is_active=1 AND id IN ({','.join('?' * len(nap))})", nap).fetchall()
            if not mashinist(r[1])}
        nap = [i for i in nap if i in ok]
    teh_naz, toplivo = (b.tehnika or "").strip()[:120] or None, None
    if b.tehnika_id:
        t = conn.execute("SELECT nazvanie, nomer, toplivo FROM tehnika WHERE id=?", (b.tehnika_id,)).fetchone()
        teh_naz = t[0] + (f" {t[1]}" if t[1] else "")
        toplivo = t[2]
    cur = conn.execute(
        """INSERT INTO otchet_smeny (sotrudnik_id, data, vid, delyanka_item_id, lesokultury_uchastok_id, reysov, obyom, ga,
           chasy, poluchatel, tehnika, kommentariy, client_id, tehnika_id, toplivo, toplivo_rashod, zapravka, uhody_proba_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, d.isoformat(), b.vid, b.delyanka_item_id if (b.vid in PO_DELYANKE and not uch and not po_probe) else None,
         b.lesokultury_uchastok_id if uch else None, b.reysov, b.obyom, b.ga, b.chasy,
         (b.poluchatel or "").strip()[:120] or None, teh_naz,
         (b.kommentariy or "").strip()[:1000] or None, b.client_id, b.tehnika_id, toplivo,
         b.toplivo_rashod or None, b.zapravka or None, b.uhody_proba_id if po_probe else None))
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
    if po_probe:
        # учёт по пробе — в «Выполнении»; сделана вся площадь — проба закрывается сама
        from app import uhody_vypolnenie
        if uhody_vypolnenie.proverit_zakrytie(conn, b.uhody_proba_id):
            zakryt = {"meropriyatie_id": None, "tip": "Проба рубок ухода закрыта — площадь пройдена",
                      "sdelano": None, "ploshad": None}
    elif uch:
        zakryt = _zakryt_esli_proyden(conn, oid, b.lesokultury_uchastok_id, b.vid, d, sid, b.uchastok_proyden)
    elif b.vid in PO_ITEM_GA:
        zakryt = _zakryt_item(conn, oid, b.delyanka_item_id, b.vid, b.uchastok_proyden)
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
    tip_mer = VIDY[vid].get("meropriyatie") or MEROPR_NA_UCHASTKE.get(vid)
    if not tip_mer:  # посадка: тип записи в журнале выбирает мастер — только закрываем цикл
        conn.execute("UPDATE otchet_smeny SET zakryl_cikl=1 WHERE id=?", (oid,))
        conn.commit()
        return {"meropriyatie_id": None, "tip": VIDY[vid]["title"], "sdelano": _r(sdelano), "ploshad": pl}
    mid = legacy_db.add_lesokultury_meropriyatie(
        conn, uid, tip_mer, d.strftime("%d.%m.%Y"),
        primechaniya=f"По отчётам за смену с телефона: {sdelano:g} га" + (f" из {pl:g}" if pl else "")
                     + (f"; работали: {', '.join(fio)}" if fio else ""),
        dannye={"istochnik": "otchet_smeny", "ga": sdelano}, sotrudnik_id=sid)
    # Закрывающий отчёт входит в закрытый цикл; новый цикл — со следующего отчёта.
    conn.execute("UPDATE otchet_smeny SET zakryl_cikl=1, meropriyatie_id=? WHERE id=?", (mid, oid))
    conn.commit()
    # Кто делал — в журнал участка и «Журнал выполненных работ».
    ids = [r[0] for r in conn.execute(
        """SELECT DISTINCT x FROM (
             SELECT o.sotrudnik_id AS x FROM otchet_smeny o
              WHERE o.deleted=0 AND o.lesokultury_uchastok_id=? AND o.vid=?
                AND o.id > (SELECT COALESCE(MAX(id), 0) FROM otchet_smeny WHERE deleted=0 AND zakryl_cikl=1
                            AND lesokultury_uchastok_id=? AND vid=? AND id<>?)
             UNION
             SELECT u.sotrudnik_id FROM otchet_smeny_uchastnik u JOIN otchet_smeny o ON o.id=u.otchet_id
              WHERE o.deleted=0 AND o.lesokultury_uchastok_id=? AND o.vid=?
                AND o.id > (SELECT COALESCE(MAX(id), 0) FROM otchet_smeny WHERE deleted=0 AND zakryl_cikl=1
                            AND lesokultury_uchastok_id=? AND vid=? AND id<>?))""",
        (uid, vid, uid, vid, oid, uid, vid, uid, vid, oid)).fetchall()]
    try:
        legacy_db.set_meropriyatie_ispolniteli(conn, mid, ids)
    except Exception:  # noqa: BLE001 — журнал уже записан, исполнители — бонус
        pass
    return {"meropriyatie_id": mid, "tip": tip_mer, "sdelano": _r(sdelano), "ploshad": pl}


def _zakryt_item(conn, oid, iid, vid, rukami):
    pl = conn.execute("SELECT ploshad FROM delyanka_item WHERE id=?", (iid,)).fetchone()
    pl = _f(pl[0]) if pl else None
    cy = cikly_items(conn, [iid]).get((iid, vid)) or {"sdelano": 0.0}
    if not (rukami or (pl and cy["sdelano"] >= pl * ZAKRYT_DOLYA)):
        return None
    conn.execute("UPDATE otchet_smeny SET zakryl_cikl=1 WHERE id=?", (oid,))
    conn.commit()
    return {"meropriyatie_id": None, "tip": VIDY[vid]["title"], "sdelano": _r(cy["sdelano"]), "ploshad": pl}


def _posle(conn, oid):
    """Что показать человеку после отправки: остаток по участку / выделу."""
    r = conn.execute("SELECT lesokultury_uchastok_id, vid, delyanka_item_id, uhody_proba_id FROM otchet_smeny WHERE id=?",
                     (oid,)).fetchone()
    if r and r[3]:
        from app import uhody_vypolnenie
        sv = uhody_vypolnenie.svodka(conn, r[3]) or {}
        return {"ostatok": sv.get("ostatok_ga"), "sdelano_v_cikle": sv.get("sdelano_ga"), "ploshad": sv.get("ploshad"),
                "kubov": sv.get("kubov")}
    if r and r[2] and r[1] in PO_ITEM_GA:
        pl = conn.execute("SELECT ploshad FROM delyanka_item WHERE id=?", (r[2],)).fetchone()
        pl = _f(pl[0]) if pl else None
        cy = cikly_items(conn, [r[2]]).get((r[2], r[1])) or {"sdelano": 0.0}
        return {"ostatok": _ostatok(pl, cy["sdelano"]), "sdelano_v_cikle": _r(cy["sdelano"]), "ploshad": pl}
    if not r or not r[0] or r[1] not in CIKLY_UCHASTKA:
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
    if b.zapravka:
        chto.append(f"⛽ заправка {b.zapravka:g} л")
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
                   o.obyom, o.ga, o.chasy, o.poluchatel, o.tehnika, o.kommentariy, o.zakryl_cikl, o.created_at,
                   o.tehnika_id, o.toplivo, o.toplivo_rashod, o.zapravka, o.uhody_proba_id, up.kvartal, up.vydel,
                   di.delyanka_id
            FROM otchet_smeny o
            LEFT JOIN uhody_proby up ON up.id = o.uhody_proba_id
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
        elif r[28]:
            mesto = f"проба №{r[28]} · кв.{r[29] or '—'} выд.{r[30] or '—'}"
        out.append({
            "id": r[0], "sotrudnik_id": r[1], "fio": r[2], "data": r[3], "vid": r[4], "vid_title": VIDY.get(r[4], {}).get("title", r[4]),
            "emoji": VIDY.get(r[4], {}).get("emoji", "•"), "delyanka_item_id": r[5], "lesokultury_uchastok_id": r[10],
            "mesto": mesto, "ploshad_uchastka": r[14], "reysov": r[15], "obyom": r[16], "ga": r[17], "chasy": r[18],
            "poluchatel": r[19], "tehnika": r[20], "kommentariy": r[21], "zakryl_cikl": bool(r[22]), "created_at": r[23],
            "naparniki": [n for n in nap.get(r[0], []) if n["id"] != r[1]],
            "tehnika_id": r[24], "toplivo": r[25], "toplivo_rashod": r[26], "zapravka": r[27],
            "uhody_proba_id": r[28], "delyanka_id": r[31],
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
        "obyom": round(sum(r["obyom"] or 0 for r in sevodnya if r["vid"] in PO_DELYANKE), 2),
        "toplivo_rashod": round(sum(r["toplivo_rashod"] or 0 for r in sevodnya), 1),
        "zapravka": round(sum(r["zapravka"] or 0 for r in sevodnya), 1),
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
def get_spravochnik(vse: bool = False, conn=Depends(get_conn), user=Depends(require_permission("bot.access"))):
    _worker(user)
    return spravochnik(conn, user["sotrudnik_id"], vse_kultury=vse)


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
    ci = cikly_items(conn)
    iids = sorted({i for (i, _v), x in ci.items() if x["otchetov"]})
    if iids:
        info = {r[0]: (_label_item(r[1], r[2], r[3], r[4]), _f(r[5])) for r in conn.execute(
            f"""SELECT di.id, di.kvartal, di.vydel, di.lesoseka_nomer, d.nazvanie, di.ploshad FROM delyanka_item di
                JOIN delyanka d ON d.id = di.delyanka_id WHERE di.id IN ({','.join('?' * len(iids))})""", iids).fetchall()}
        for (iid, v), x in ci.items():
            if x["otchetov"] and iid in info:
                otkrytye.append({"delyanka_item_id": iid, "mesto": info[iid][0], "vid": v, "vid_title": VIDY[v]["title"],
                                 "sdelano": _r(x["sdelano"]), "ploshad": info[iid][1],
                                 "ostatok": _ostatok(info[iid][1], x["sdelano"]), "posledniy": x["posledniy"]})
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


# ---------------------------------------------------------------- топливо ---

def svodka_topliva(conn, ot, do):
    """Кто сколько заправил и сжёг (по людям и по машинам), раздельно ДТ и
    АИ-92, + «в баке примерно» по машине: все заправки минус весь расход
    с начала учёта. Расход на час и на м³ — чтобы сразу видеть, у кого
    странно много."""
    ensure(conn)
    pusto = lambda: {t: {"rashod": 0.0, "zapravka": 0.0} for t in TOPLIVO + ("—",)}  # noqa: E731
    lyudi, mashiny = {}, {}
    for sid, fio, tid, teh, top, ras, zap, chasy, obyom in conn.execute(
            """SELECT o.sotrudnik_id, s.fio, o.tehnika_id, o.tehnika, o.toplivo, o.toplivo_rashod, o.zapravka, o.chasy, o.obyom
               FROM otchet_smeny o JOIN sotrudniki s ON s.id = o.sotrudnik_id
               WHERE o.deleted=0 AND o.data >= ? AND o.data <= ?
                 AND (COALESCE(o.toplivo_rashod,0) > 0 OR COALESCE(o.zapravka,0) > 0)""", (ot, do)).fetchall():
        t = top if top in TOPLIVO else "—"
        p = lyudi.setdefault(sid, {"sotrudnik_id": sid, "fio": fio, "po_toplivu": pusto(), "chasy": 0.0, "obyom": 0.0,
                                   "smen": 0})
        key = tid or f"txt:{teh or '—'}"
        m = mashiny.setdefault(key, {"tehnika_id": tid, "nazvanie": teh or "техника не указана", "toplivo": top,
                                     "po_toplivu": pusto(), "chasy": 0.0, "obyom": 0.0, "kto": set()})
        for x in (p, m):
            x["po_toplivu"][t]["rashod"] += ras or 0
            x["po_toplivu"][t]["zapravka"] += zap or 0
            x["chasy"] += chasy or 0
            x["obyom"] += obyom or 0
        p["smen"] += 1
        m["kto"].add(fio)
    # Остаток в баке — по всей истории машины, не только за период.
    bak = {tid: (z or 0) - (r or 0) for tid, z, r in conn.execute(
        "SELECT tehnika_id, SUM(zapravka), SUM(toplivo_rashod) FROM otchet_smeny WHERE deleted=0 AND tehnika_id IS NOT NULL "
        "GROUP BY tehnika_id").fetchall()}
    zakrep = {tid: fio for tid, fio in conn.execute(
        "SELECT t.id, s.fio FROM tehnika t LEFT JOIN sotrudniki s ON s.id=t.zakreplen_sotrudnik_id").fetchall()}

    def itog(x):
        ras = sum(v["rashod"] for v in x["po_toplivu"].values())
        x["po_toplivu"] = {k: {"rashod": round(v["rashod"], 1), "zapravka": round(v["zapravka"], 1)}
                           for k, v in x["po_toplivu"].items() if v["rashod"] or v["zapravka"]}
        x["l_na_chas"] = round(ras / x["chasy"], 1) if x["chasy"] else None
        x["l_na_m3"] = round(ras / x["obyom"], 2) if x["obyom"] else None
        x["chasy"] = round(x["chasy"], 1)
        x["obyom"] = round(x["obyom"], 2)
        return x

    lyudi_out = sorted((itog(x) for x in lyudi.values()), key=lambda x: x["fio"] or "")
    mashiny_out = []
    for x in mashiny.values():
        x = itog(x)
        x["kto"] = sorted(x["kto"])
        x["zakreplen"] = zakrep.get(x["tehnika_id"])
        x["v_bake_primerno"] = round(bak[x["tehnika_id"]], 1) if x["tehnika_id"] in bak else None
        mashiny_out.append(x)
    mashiny_out.sort(key=lambda x: x["nazvanie"] or "")
    vsego = {t: {"rashod": round(sum(x["po_toplivu"].get(t, {}).get("rashod", 0) for x in lyudi_out), 1),
                 "zapravka": round(sum(x["po_toplivu"].get(t, {}).get("zapravka", 0) for x in lyudi_out), 1)}
             for t in TOPLIVO + ("—",)}
    vsego = {k: v for k, v in vsego.items() if v["rashod"] or v["zapravka"]}
    return {"ot": ot, "do": do, "lyudi": lyudi_out, "mashiny": mashiny_out, "vsego": vsego}


@web_router.get("/toplivo")
def web_toplivo(date_from: Optional[str] = None, date_to: Optional[str] = None,
                user=Depends(require_office_or_master), conn=Depends(get_conn)):
    segodnya = date.today()
    ot = (_d(date_from) or segodnya.replace(day=1)).isoformat()
    do = (_d(date_to) or segodnya).isoformat()
    return svodka_topliva(conn, ot, do)
