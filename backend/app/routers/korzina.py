# -*- coding: utf-8 -*-
"""Корзина удалённых делянок и участков лесокультур (30 дней) и список
автокопий базы — см. app/korzina.py."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app import korzina
from app.auth import require_permission
from app.database import get_conn

router = APIRouter(prefix="/api/korzina", tags=["korzina"])


@router.get("/")
def list_korzina(user=Depends(require_permission("korzina.view")), conn=Depends(get_conn)):
    return {"items": korzina.spisok(conn), "dnei": korzina.KORZINA_DNEI}


@router.post("/{korzina_id}/restore")
def restore(korzina_id: int, user=Depends(require_permission("korzina.view")), conn=Depends(get_conn)):
    try:
        return {"ok": True, **korzina.vosstanovit(conn, korzina_id)}
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.delete("/{korzina_id}")
def purge(korzina_id: int, user=Depends(require_permission("korzina.purge")), conn=Depends(get_conn)):
    korzina.udalit_navsegda(conn, korzina_id)
    return {"ok": True}


@router.get("/backups")
def list_backups(user=Depends(require_permission("backups.manage"))):
    return {"items": korzina.spisok_kopiy(), "hranit": korzina.BACKUPS_HRANIT}


@router.post("/backups")
def make_backup(user=Depends(require_permission("backups.manage")), conn=Depends(get_conn)):
    p = korzina.avtokopiya(conn, "vruchnuyu")
    if p is None:
        raise HTTPException(500, "Не удалось сделать копию базы")
    return {"ok": True, "file": p.name}


@router.get("/backups/{name}")
def download_backup(name: str, user=Depends(require_permission("backups.manage"))):
    try:
        p = korzina.put_kopii(name)
    except FileNotFoundError:
        raise HTTPException(404, "Копия не найдена")
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")
