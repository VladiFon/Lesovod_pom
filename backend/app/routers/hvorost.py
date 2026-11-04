# -*- coding: utf-8 -*-
"""Хворост делянки (legacy/hvorost.py): откуда брать «разрешено» по
хворосту для лимитов и акта, и какие пробы «хворост делянки» к ней
привязаны. Карточка делянки и Инспекция — блок «🔥 Хворост»."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401
import delyanka
import hvorost
import raskhod_v2

from app.auth import get_current_user, require_permission
from app.database import get_conn

router = APIRouter(prefix="/api/hvorost", tags=["hvorost"])


def _r(x):
    return round(x or 0.0, 2)


def svodka(conn, delyanka_id):
    d, items = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    hvorost.ensure(conn)
    ist = hvorost.istochniki(conn, [delyanka_id]).get(delyanka_id, "net")
    mdo = sum(sum(hvorost.mdo_po_item(it).values()) for it in items)
    proby = hvorost.proby_delyanok(conn, [delyanka_id]).get(delyanka_id, [])
    po_probe = 0.0
    for it in items:
        p = hvorost._proba_dlya_item(proby, it)
        pl = hvorost._f(it.get("ploshad")) or 0
        if p:
            po_probe += p["zapas_na_1ga"] * pl
    bal = raskhod_v2.compute_balance_batch(conn, items) if items else {}
    fakt = limit = 0.0
    for b in bal.values():
        for s in b.values():
            h = s.get("HVOROST") or {}
            fakt += h.get("fakt") or 0
            limit += h.get("limit") or 0
    return {
        "delyanka_id": delyanka_id, "istochnik": ist,
        "mdo": _r(mdo), "po_probe": _r(po_probe) if proby else None,
        "proby": [{"id": p["id"], "kvartal": p["kvartal"], "vydel": p["vydel"], "data_zamera": p["data_zamera"],
                   "zapas_na_1ga": p["zapas_na_1ga"]} for p in proby],
        "limit": _r(limit) if ist != "net" else None, "fakt": _r(fakt),
        "ostatok": _r(limit - fakt) if ist != "net" else None,
    }


@router.get("/delyanka/{delyanka_id}")
def get_hvorost(delyanka_id: int, user=Depends(get_current_user), conn=Depends(get_conn)):
    return svodka(conn, delyanka_id)


class IstochnikIn(BaseModel):
    istochnik: str


@router.put("/delyanka/{delyanka_id}")
def put_hvorost(delyanka_id: int, body: IstochnikIn, user=Depends(require_permission("inspection.edit")),
                conn=Depends(get_conn)):
    if not conn.execute("SELECT 1 FROM delyanka WHERE id=?", (delyanka_id,)).fetchone():
        raise HTTPException(404, "Делянка не найдена")
    try:
        hvorost.set_istochnik(conn, delyanka_id, body.istochnik)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return svodka(conn, delyanka_id)


@router.get("/delyanki")
def delyanki_dlya_vybora(user=Depends(get_current_user), conn=Depends(get_conn)):
    """Делянки для привязки пробы «хворост делянки»: не архивные, с кв/выд."""
    out = []
    for did, nazv, status in conn.execute(
            "SELECT id, nazvanie, status FROM delyanka WHERE COALESCE(status,'') <> 'архив' ORDER BY id DESC").fetchall():
        kv_vyd = conn.execute(
            "SELECT GROUP_CONCAT('кв.' || COALESCE(kvartal,'?') || ' выд.' || COALESCE(vydel,'?'), '; ') "
            "FROM delyanka_item WHERE delyanka_id=?", (did,)).fetchone()[0]
        out.append({"id": did, "nazvanie": nazv, "status": status, "kv_vyd": kv_vyd or ""})
    return out
