# -*- coding: utf-8 -*-
"""«🔥 Челленджи» — общие цели на всю команду (этап 5 по плану Влада
03.11.2026: «Ноябрь без просрочек», «Вывезти 500 м³ до конца месяца» —
одна общая шкала, в конце звание).

Челлендж = вид цели + число + срок (от–до) + приз-звание. Факт считается из
того, что уже есть в базе, теми же функциями, что остальные экраны:
  kuby       — м³ по нарядам (raskhod_naryad / raskhod_pozitsiya);
  vyvozka    — м³ расхода ЕГАИС (svodka_raskhod.egais_svodka);
  akty       — актов освидетельствования (по дате акта);
  chelodni   — человеко-дней «работал» по табелю;
  uhody      — мероприятий лесокультур (по дате мероприятия);
  zadachi    — выполненных задач «Плана работ»;
  bez_prosr  — «без просрочек»: ни один срок (заготовки, вывозки, акта),
               выпавший на период, не просрочен — по «Пути делянки».
Итог фиксируется в таблице при первом открытии после конца срока, чтобы
победа не «уплывала» от поздних правок. Пишет только свою таблицу."""
import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401
from app.auth import get_current_user, require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/chellendzhi", tags=["chellendzhi"])

SCHEMA = """
CREATE TABLE IF NOT EXISTS komanda_chellendzh (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT NOT NULL,
    emoji TEXT,
    tip TEXT NOT NULL,
    cel REAL NOT NULL DEFAULT 0,
    ot TEXT NOT NULL,
    do TEXT NOT NULL,
    priz TEXT,
    sozdal TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    itog_json TEXT,
    deleted INTEGER NOT NULL DEFAULT 0
);
"""

TIPY = {
    "kuby": {"title": "Нарубить по нарядам, м³", "ed": "м³", "emoji": "🪓", "imya": "Нарубить {cel} м³"},
    "vyvozka": {"title": "Вывезти по ЕГАИС, м³", "ed": "м³", "emoji": "🚛", "imya": "Вывезти {cel} м³"},
    "akty": {"title": "Составить актов освидетельствования", "ed": "акт.", "emoji": "📜", "imya": "Актов: {cel}"},
    "chelodni": {"title": "Отработать человеко-дней", "ed": "чел.-дн.", "emoji": "🧑‍🌾", "imya": "{cel} человеко-дней в лесу"},
    "uhody": {"title": "Мероприятий лесокультур (уходы и др.)", "ed": "мер.", "emoji": "🌱", "imya": "Уходов и мероприятий: {cel}"},
    "zadachi": {"title": "Выполнить задач плана", "ed": "задач", "emoji": "✅", "imya": "Задач плана: {cel}"},
    "bez_prosr": {"title": "Без просрочек: ни одного сорванного срока", "ed": "сорв.", "emoji": "🛡", "imya": "Без просрочек"},
}
MESYACY = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
           "ноябрь", "декабрь"]


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


def _rab(ot, do):
    return sum(1 for k in range((do - ot).days + 1) if (ot + timedelta(days=k)).weekday() < 5) if do >= ot else 0


def _konec_mesyaca(d):
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)


# ---------- факт по видам цели: (факт, вклад [{kto, znach}], подробности) ----------

def _f_kuby(conn, ot, do):
    from app.routers import reyting
    cur, _ = reyting.poschitat(conn, ot, do)
    vsego = 0.0
    for did, data, v in conn.execute(
        """SELECT n.delyanka_id, n.data, COALESCE(SUM(p.obyom), 0)
           FROM raskhod_naryad n LEFT JOIN raskhod_pozitsiya p ON p.naryad_id = n.id GROUP BY n.id""").fetchall():
        dt = _d(data)
        if dt and ot <= dt <= do:
            vsego += v or 0
    fio = dict(conn.execute("SELECT id, fio FROM sotrudniki").fetchall())
    vklad = [{"kto": fio.get(s, "—"), "znach": x["kuby"]} for s, x in cur.items() if x["kuby"] > 0]
    return vsego, vklad, None


def _f_vyvozka(conn, ot, do):
    from app import svodka_raskhod
    vsego, kto = 0.0, {}
    for r in svodka_raskhod.egais_svodka(conn, "raskhod")["rows"]:
        dt = _d(r.get("data_iso"))
        if dt and ot <= dt <= do:
            vsego += r["obyom"] or 0
            k = r.get("sotrudnik") or "—"
            kto[k] = kto.get(k, 0.0) + (r["obyom"] or 0)
    return vsego, [{"kto": k, "znach": v} for k, v in kto.items()], None


def _f_akty(conn, ot, do):
    names = dict(conn.execute("SELECT id, nazvanie FROM delyanka").fetchall())
    akty = []
    for did, ad in conn.execute("SELECT delyanka_id, act_date FROM osvidetelstvovanie_acts").fetchall():
        dt = _d(ad)
        if dt and ot <= dt <= do:
            akty.append(names.get(did, f"#{did}"))
    return len(akty), [], {"spisok": akty[:10]}


def _f_chelodni(conn, ot, do):
    fio = dict(conn.execute("SELECT id, fio FROM sotrudniki").fetchall())
    vklad, vsego = [], 0
    for sid, n in conn.execute(
            "SELECT sotrudnik_id, COUNT(*) FROM tabel_zapis WHERE status='работал' AND data >= ? AND data <= ? "
            "GROUP BY sotrudnik_id", (ot.isoformat(), do.isoformat())).fetchall():
        vsego += n
        vklad.append({"kto": fio.get(sid, "—"), "znach": n})
    return vsego, vklad, None


def _f_uhody(conn, ot, do):
    n = 0
    for (data,) in conn.execute("SELECT data FROM lesokultury_meropriyatiya").fetchall():
        dt = _d(data)
        if dt and ot <= dt <= do:
            n += 1
    return n, [], None


def _f_zadachi(conn, ot, do):
    fio = dict(conn.execute("SELECT id, fio FROM sotrudniki").fetchall())
    vklad, vsego = [], 0
    for sid, n in conn.execute(
            "SELECT sotrudnik_id, COUNT(*) FROM work_plan WHERE status='выполнена' AND data >= ? AND data <= ? "
            "GROUP BY sotrudnik_id", (ot.isoformat(), do.isoformat())).fetchall():
        vsego += n
        vklad.append({"kto": fio.get(sid, "—"), "znach": n})
    return vsego, vklad, None


def _f_bez_prosr(conn, ot, do, segodnya):
    """Сорванные сроки: непройденная станция «Пути делянки», срок которой
    выпал на [ot, do] и уже прошёл. Плюс — сколько сроков впереди."""
    from app.routers import put_delyanki
    p = put_delyanki.sobrat(conn, segodnya)
    nazv = {k: t for k, _e, t in put_delyanki.STANCII}
    sorvano, vperedi = [], []
    for x in p["v_puti"]:
        for k, s in x["stancii"].items():
            sr = s.get("srok")
            if s["done"] or not sr:
                continue
            dt = _d(sr["data"])
            if not dt or not (ot <= dt <= do):
                continue
            (sorvano if dt < segodnya else vperedi).append(
                {"delyanka": x["nazvanie"], "chto": nazv[k], "data": sr["data"]})
    vperedi.sort(key=lambda v: _d(v["data"]))
    return len(sorvano), [], {"sorvano": sorvano[:10], "vperedi": vperedi[:6]}


def fakt(conn, tip, ot, do, segodnya):
    fn = {"kuby": _f_kuby, "vyvozka": _f_vyvozka, "akty": _f_akty, "chelodni": _f_chelodni,
          "uhody": _f_uhody, "zadachi": _f_zadachi}.get(tip)
    if tip == "bez_prosr":
        return _f_bez_prosr(conn, ot, do, segodnya)
    if not fn:
        raise HTTPException(400, "Неизвестный вид цели")
    return fn(conn, ot, do)


def _schitat(conn, row, segodnya):
    cid, naz, em, tip, cel, ot_s, do_s, priz, sozdal, created, itog_json = row
    ot, do = _d(ot_s), _d(do_s)
    t = TIPY.get(tip, {"title": tip, "ed": "", "emoji": "🎯"})
    base = {"id": cid, "nazvanie": naz, "emoji": em or t["emoji"], "tip": tip, "tip_title": t["title"], "ed": t["ed"],
            "cel": cel, "ot": ot_s, "do": do_s, "priz": priz, "sozdal": sozdal}
    if itog_json:
        return {**base, **json.loads(itog_json), "zafiksirovan": True}
    do_fakt = min(do, segodnya)
    if segodnya < ot:
        return {**base, "status": "skoro", "fakt": 0, "pct": 0, "dney_do_starta": (ot - segodnya).days, "vklad": []}
    # «Без просрочек» смотрит сроки всего периода (и впереди), остальные — факт по сегодня.
    f, vklad, podr = fakt(conn, tip, ot, do if tip == "bez_prosr" else do_fakt, segodnya)
    vsego_rab = max(_rab(ot, do), 1)
    proshlo_rab = _rab(ot, do_fakt)
    ostalos_rab = _rab(segodnya + timedelta(days=1), do) if do > segodnya else 0
    zakonchen = segodnya > do
    out = {**base, "fakt": round(f, 1), "podrobno": podr,
           "vklad": sorted(({"kto": v["kto"], "znach": round(v["znach"], 1)} for v in vklad), key=lambda v: -v["znach"])[:6],
           "dney_ostalos": max((do - segodnya).days, 0), "rab_ostalos": ostalos_rab}
    if tip == "bez_prosr":
        dni = (do - ot).days + 1
        proshlo = min((segodnya - ot).days + 1, dni)
        out["pct"] = round(proshlo / dni * 100) if f == 0 else 0
        out["status"] = "proval" if f > 0 else ("pobeda" if zakonchen else "idet")
        out["temp"] = "Пока ни одного сорванного срока 💪" if f == 0 else f"Сорвано сроков: {int(f)} — челлендж провален"
    else:
        out["pct"] = round(f / cel * 100) if cel else 0
        ozhid = cel * proshlo_rab / vsego_rab
        v_den = f / proshlo_rab if proshlo_rab else 0
        prognoz = f + v_den * ostalos_rab
        out["prognoz"] = round(prognoz, 1)
        out["nado_v_den"] = round((cel - f) / ostalos_rab, 1) if ostalos_rab and f < cel else 0
        if f >= cel:
            out["status"] = "pobeda"
            out["temp"] = "Цель взята! 🎉"
        elif zakonchen:
            out["status"] = "proval"
            out["temp"] = f"Не дотянули {round(cel - f, 1):g} {t['ed']}"
        else:
            out["status"] = "idet"
            if proshlo_rab == 0:
                out["temp"] = "Старт! Первый рабочий день впереди"
            elif f >= ozhid:
                out["temp"] = f"Идём с опережением: +{round(f - ozhid, 1):g} {t['ed']} к графику"
            else:
                out["temp"] = f"Отстаём от графика на {round(ozhid - f, 1):g} {t['ed']}"
            out["ozhid"] = round(ozhid, 1)
    if zakonchen:
        itog = {k: out[k] for k in ("fakt", "pct", "status", "temp", "vklad", "podrobno")}
        itog["zafiksirovan_at"] = segodnya.isoformat()
        conn.execute("UPDATE komanda_chellendzh SET itog_json=? WHERE id=?", (json.dumps(itog, ensure_ascii=False), cid))
        conn.commit()
        out["zafiksirovan"] = True
    return out


def _shablony(conn, segodnya):
    """Готовые цели на остаток месяца: число — от прошлого месяца +10%."""
    nach = segodnya.replace(day=1)
    konec = _konec_mesyaca(segodnya)
    p_do = nach - timedelta(days=1)
    p_ot = p_do.replace(day=1)
    mes = MESYACY[segodnya.month - 1]
    out = [{"tip": "bez_prosr", "nazvanie": f"{mes.capitalize()} без просрочек", "emoji": "🛡", "cel": 0,
            "ot": nach.isoformat(), "do": konec.isoformat(), "priz": "🛡 Команда без единой просрочки"}]
    for tip, priz in (("vyvozka", "🚛 Короли вывозки"), ("kuby", "🪓 Лесорубы месяца"), ("akty", "📜 Гроза актов")):
        try:
            f, _v, _p = fakt(conn, tip, p_ot, p_do, segodnya)
        except Exception:  # noqa: BLE001
            f = 0
        if tip == "akty":
            cel = max(int(f) + 1, 3)
        else:
            cel = max(round(f * 1.1 / 10) * 10, 50)
        out.append({"tip": tip, "nazvanie": TIPY[tip]["imya"].format(cel=f"{cel:g}") + f" за {mes}", "emoji": TIPY[tip]["emoji"],
                    "cel": cel, "ot": nach.isoformat(), "do": konec.isoformat(), "priz": priz,
                    "podskazka": f"в прошлом месяце {round(f, 1):g} {TIPY[tip]['ed']}"})
    return out


def sobrat(conn, segodnya=None):
    ensure(conn)
    segodnya = segodnya or date.today()
    rows = conn.execute(
        "SELECT id, nazvanie, emoji, tip, cel, ot, do, priz, sozdal, created_at, itog_json FROM komanda_chellendzh "
        "WHERE deleted=0 ORDER BY do DESC, id DESC").fetchall()
    aktivnye, proshlye = [], []
    for r in rows:
        try:
            x = _schitat(conn, r, segodnya)
        except Exception as e:  # noqa: BLE001
            x = {"id": r[0], "nazvanie": r[1], "status": "oshibka", "oshibka": str(e)[:200], "vklad": []}
        (proshlye if x.get("status") in ("pobeda", "proval") and _d(r[6]) < segodnya else aktivnye).append(x)
    poryadok = {"idet": 0, "pobeda": 1, "skoro": 2}
    aktivnye.sort(key=lambda x: (poryadok.get(x.get("status"), 3), x.get("do") or ""))
    return {
        "segodnya": segodnya.isoformat(), "tipy": TIPY,
        "aktivnye": aktivnye, "proshlye": proshlye[:20],
        "zvaniya": [{"priz": x.get("priz"), "nazvanie": x["nazvanie"], "do": x.get("do"), "emoji": x.get("emoji")}
                    for x in proshlye if x.get("status") == "pobeda" and x.get("priz")],
        "pobed": sum(1 for x in proshlye if x.get("status") == "pobeda"),
        "provalov": sum(1 for x in proshlye if x.get("status") == "proval"),
        # Готовые цели — кроме тех, что уже запущены на этот же срок.
        "shablony": [s for s in _shablony(conn, segodnya)
                     if not any(r[3] == s["tip"] and r[5] == s["ot"] and r[6] == s["do"] for r in rows)],
    }


class ChellendzhIn(BaseModel):
    nazvanie: str
    emoji: Optional[str] = None
    tip: str
    cel: float = 0
    ot: str
    do: str
    priz: Optional[str] = None


@router.get("")
def spisok(user=Depends(get_current_user), conn=Depends(get_conn)):
    return sobrat(conn)


@router.post("")
def sozdat(body: ChellendzhIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    ensure(conn)
    if body.tip not in TIPY:
        raise HTTPException(400, "Неизвестный вид цели")
    ot, do = _d(body.ot), _d(body.do)
    if not ot or not do or do < ot:
        raise HTTPException(400, "Проверь даты: «по» не раньше «с»")
    if body.tip != "bez_prosr" and body.cel <= 0:
        raise HTTPException(400, "Цель должна быть больше нуля")
    naz = (body.nazvanie or "").strip() or TIPY[body.tip]["title"]
    cur = conn.execute(
        "INSERT INTO komanda_chellendzh (nazvanie, emoji, tip, cel, ot, do, priz, sozdal) VALUES (?,?,?,?,?,?,?,?)",
        (naz[:120], (body.emoji or TIPY[body.tip]["emoji"])[:8], body.tip, body.cel if body.tip != "bez_prosr" else 0,
         ot.isoformat(), do.isoformat(), (body.priz or "").strip()[:80] or None, user.get("login")))
    conn.commit()
    return {"id": cur.lastrowid}


@router.delete("/{cid}")
def udalit(cid: int, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    ensure(conn)
    cur = conn.execute("UPDATE komanda_chellendzh SET deleted=1 WHERE id=?", (cid,))
    if not cur.rowcount:
        raise HTTPException(404, "Челлендж не найден")
    conn.commit()
    return {"ok": True}
