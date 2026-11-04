# -*- coding: utf-8 -*-
"""«Огород уходов» — игровой вид экрана «Лесокультуры» (просьба Влада
03.11.2026): где уход за культурами нужен, а где не надо — одним списком
на сезон, с планированием.

Нормы от Влада: агротехнических уходов 1-й год — 2, 2-й — 2, 3-й — 3;
плюс осветление. Год культур считается от года создания: в год посадки —
1-й год. Уходы считаются по журналу мероприятий участка за сезон
(«Агротехнический уход», «Химический уход» — всё с «уход» в названии,
кроме записей от проб рубок ухода). Осветление — запись журнала с
«осветл» (её же ставит проба рубок ухода с видом «Осветление»).

Ничего в обычных таблицах здесь не меняется: «✅ Сделано» — обычная
запись журнала (POST /api/lesokultury/uchastki/{id}/meropriyatiya),
«📅 В план» — обычная задача «Плана работ» (POST /api/work-plan/)."""
import re
from datetime import date

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401
import db as legacy_db

from app.auth import get_current_user
from app.database import get_conn

router = APIRouter(prefix="/api/uhody-igra", tags=["uhody-igra"])

# Агротехнических уходов за сезон по году культур (1-й год = год создания).
NORMY = {1: 2, 2: 2, 3: 3}
# Осветление: в какие годы культур ждём (если ещё не было ни одного).
OSVETLENIE_OT, OSVETLENIE_DO = 4, 10
SEZON_MESYACY = (5, 9)  # уходы ведутся май–сентябрь


def _god(s):
    m = re.search(r"(19|20)\d{2}", str(s or ""))
    return int(m.group(0)) if m else None


def _eto_uhod(tip, proba_id):
    t = (tip or "").lower()
    return "уход" in t and not proba_id and "рубк" not in t


def _eto_osvetlenie(tip):
    return "осветл" in (tip or "").lower()


def _label(u):
    por = u.get("glavnaya_poroda") or ""
    return f"кв.{u.get('kvartal') or '—'} выд.{u.get('vydel') or '—'}" + (f" · {por}" if por else "")


def po_umolchaniyu(segodnya):
    """В ноябре–декабре по умолчанию планируем следующий сезон."""
    return segodnya.year + 1 if segodnya.month >= 11 else segodnya.year


def sobrat(conn, sezon, segodnya=None):
    segodnya = segodnya or date.today()
    uchastki = legacy_db.get_lesokultury_uchastki(conn, include_spisannye=False)

    zhurnal = {}
    for uid, tip, data, proba_id in conn.execute(
        "SELECT uchastok_id, tip, data, proba_id FROM lesokultury_meropriyatiya"
    ).fetchall():
        zhurnal.setdefault(uid, []).append((tip, data, proba_id))

    plan = {}
    try:
        for uid, d, zad, fio, st in conn.execute(
            """SELECT wp.lesokultury_uchastok_id, wp.data, wp.zadacha, s.fio, wp.status
               FROM work_plan wp LEFT JOIN sotrudniki s ON s.id = wp.sotrudnik_id
               WHERE wp.lesokultury_uchastok_id IS NOT NULL AND substr(wp.data, 1, 4) = ?""",
            (str(sezon),),
        ).fetchall():
            plan.setdefault(uid, []).append({"data": d, "zadacha": zad, "kto": fio, "status": st})
    except Exception:  # noqa: BLE001 — старая база без work_plan
        pass

    out = []
    for u in uchastki:
        if (u.get("status") or "") == "списан":
            continue
        g = _god(u.get("god_sozdaniya"))
        if not g:
            continue
        god_kultur = sezon - g + 1
        if god_kultur < 1:
            continue
        zap = zhurnal.get(u["id"], [])
        uhody = [(t, d) for t, d, p in zap if _eto_uhod(t, p) and _god(d) == sezon]
        posledniy = max((d for t, d, p in zap if _eto_uhod(t, p) and d), default=None, key=lambda d: _sort_d(d))
        osv = [d for t, d, p in zap if _eto_osvetlenie(t)]
        norma = NORMY.get(god_kultur, 0) if (u.get("status") or "активен") != "переведён" else 0
        sdelano = len(uhody)
        pl = plan.get(u["id"], [])
        if norma and sdelano < norma:
            vid = "uhod"
        elif norma:
            vid = "uhod_ok"
        elif OSVETLENIE_OT <= god_kultur <= OSVETLENIE_DO and not osv:
            vid = "osvetlenie"
        else:
            vid = "pokoy"
        out.append({
            "id": u["id"],
            "label": _label(u),
            "lesnichestvo": u.get("lesnichestvo") or "",
            "ploshad": u.get("ploshad"),
            "god_sozdaniya": g,
            "god_kultur": god_kultur,
            "status": u.get("status") or "активен",
            "vid": vid,
            "norma": norma,
            "sdelano": sdelano,
            "dolg": max(norma - sdelano, 0),
            "posledniy_uhod": posledniy,
            "osvetlenie": max(osv, key=_sort_d) if osv else None,
            "plan": pl,
        })

    def klyuch(x):
        return (-x["dolg"], _sort_d(x["posledniy_uhod"]) if x["posledniy_uhod"] else "0", -(x["ploshad"] or 0))

    out.sort(key=klyuch)
    nado = sum(x["norma"] for x in out)
    sdel = sum(min(x["sdelano"], x["norma"]) for x in out)
    m1, m2 = SEZON_MESYACY
    return {
        "sezon": sezon,
        "po_umolchaniyu": po_umolchaniyu(segodnya),
        "idet_sezon": sezon == segodnya.year and m1 <= segodnya.month <= m2,
        "normy": {str(k): v for k, v in NORMY.items()},
        "osvetlenie": [OSVETLENIE_OT, OSVETLENIE_DO],
        "itogo": {
            "uhodov_nado": nado,
            "uhodov_sdelano": sdel,
            "uchastkov_uhod": sum(1 for x in out if x["vid"] == "uhod"),
            "ga_uhod": round(sum(x["ploshad"] or 0 for x in out if x["vid"] == "uhod"), 1),
            "uchastkov_osvetlenie": sum(1 for x in out if x["vid"] == "osvetlenie"),
            "ga_osvetlenie": round(sum(x["ploshad"] or 0 for x in out if x["vid"] == "osvetlenie"), 1),
            "v_plane": sum(1 for x in out if x["plan"]),
        },
        "uchastki": out,
    }


def _sort_d(d):
    """'12.07.2026' / '2026-07-12' → '2026-07-12' для сравнения."""
    s = str(d or "")
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return s[:10]


@router.get("")
def ogorod(sezon: int = 0, user=Depends(get_current_user), conn=Depends(get_conn)):
    sezon = sezon or po_umolchaniyu(date.today())
    res = sobrat(conn, sezon)
    try:
        res["sotrudniki"] = [
            {"id": r[0], "fio": r[1], "dolzhnost": r[2]}
            for r in conn.execute("SELECT id, fio, dolzhnost FROM sotrudniki WHERE is_active=1 ORDER BY fio").fetchall()
        ]
    except Exception:  # noqa: BLE001
        res["sotrudniki"] = []
    return res
