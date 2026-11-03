# -*- coding: utf-8 -*-
"""Игровой режим в телефоне (03.11.2026): одна ручка для рабочего —
своя карточка героя (geroi), рейтинг за неделю/месяц (reyting) с
соперником впереди и догоняющим, активные челленджи команды
(chellendzhi). Включается в настройках телефона; сервер отдаёт данные
всегда, режим — только вид. Только чтение (кроме фиксации итогов
челленджей, как на сайте)."""
from fastapi import APIRouter, Depends, HTTPException

from app import legacy_bridge  # noqa: F401
from app.auth import require_permission
from app.database import get_conn

router = APIRouter(prefix="/api/bot/igra", tags=["igra-bot"])


def _korotko(r):
    return {"sotrudnik_id": r["sotrudnik_id"], "fio": r["fio"], "mesto": r["mesto"], "ochki": r["ochki"],
            "znachki": [z["z"] for z in r.get("znachki", [])]}


def sobrat(conn, sid, period="mesyac"):
    from app.routers import chellendzhi, geroi, reyting
    rf = conn.row_factory
    g = next((x for x in geroi.sobrat(conn)["geroi"] if x["id"] == sid), None)
    conn.row_factory = rf
    r = reyting.sobrat(conn, period if period in reyting.PERIODY else "mesyac")
    conn.row_factory = rf
    ya = next((x for x in r["reyting"] if x["sotrudnik_id"] == sid), None)
    try:
        c = chellendzhi.sobrat(conn)
        ch = [{"nazvanie": x["nazvanie"], "emoji": x.get("emoji"), "pct": x.get("pct", 0), "status": x.get("status"),
               "temp": x.get("temp"), "fakt": x.get("fakt"), "cel": x.get("cel"), "ed": x.get("ed"), "do": x.get("do"),
               "priz": x.get("priz")} for x in c["aktivnye"] if x.get("status") != "oshibka"]
        zvaniya = [z["priz"] for z in c["zvaniya"]][:5]
    except Exception:  # noqa: BLE001
        ch, zvaniya = [], []
    conn.row_factory = rf
    return {
        "geroy": g,
        "reyting": {
            "period": r["period"], "periody": r["periody"], "ot": r["ot"], "do": r["do"],
            "top": [_korotko(x) for x in r["reyting"][:10]],
            "ya": {**_korotko(ya), "sopernik": ya.get("sopernik"), "dogonyaet": ya.get("dogonyaet"),
                   "sdvig": ya.get("sdvig"), "ochki_po": ya.get("ochki_po")} if ya else None,
            "v_igre": len(r["reyting"]),
            "zvenya": [{"nazvanie": z["nazvanie"], "emoji": z["emoji"], "srednee": z["srednee"]} for z in r["zvenya"][:5]],
        },
        "chellendzhi": ch,
        "zvaniya_komandy": zvaniya,
    }


@router.get("/moy")
def moy(period: str = "mesyac", conn=Depends(get_conn), user=Depends(require_permission("bot.access"))):
    if user.get("role") != "worker" or not user.get("sotrudnik_id"):
        raise HTTPException(403, "Доступно только учётным записям рабочих (worker-login)")
    return sobrat(conn, user["sotrudnik_id"], period)
