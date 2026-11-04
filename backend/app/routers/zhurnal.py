# -*- coding: utf-8 -*-
"""GET /api/zhurnal-rabot — единый журнал работ (app/zhurnal_rabot.py)."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app import zhurnal_rabot as zr
from app.auth import require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/zhurnal-rabot", tags=["zhurnal-rabot"])


@router.get("")
def zhurnal(ot: Optional[str] = None, do: Optional[str] = None, q: Optional[str] = None,
            istochniki: Optional[str] = None, s: Optional[int] = None,
            kv: Optional[str] = None, vyd: Optional[str] = None,
            limit: int = Query(400, ge=1, le=5000),
            user=Depends(require_office_or_master), conn=Depends(get_conn)):
    do = do or date.today().isoformat()
    ot = ot or (date.fromisoformat(do) - timedelta(days=30)).isoformat()
    ist = [x for x in (istochniki or "").split(",") if x in zr.ISTOCHNIKI] or None
    vse = zr.sobrat(conn, ot, do, ist)
    stroki = zr.filtr(vse, q=q, sotrudnik_id=s, kvartal=kv, vydel=vyd)
    po_ist = {}
    for x in stroki:
        po_ist[x["istochnik"]] = po_ist.get(x["istochnik"], 0) + 1
    lyudey = {p["id"] or p["fio"] for x in stroki for p in x["lyudi"]}
    return {"ot": ot, "do": do, "vsego": len(stroki), "po_istochnikam": po_ist, "lyudey": len(lyudey),
            "istochniki": zr.ISTOCHNIKI, "stroki": stroki[:limit], "obrezano": len(stroki) > limit}
