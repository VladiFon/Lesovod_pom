# -*- coding: utf-8 -*-
"""Проекты лесных культур — API (логика в app/lk_proekt.py).

* GET    /api/lk-proekty                    — список (?god=, ?status=)
* POST   /api/lk-proekty/import/preview     — разбор Word-файлов АРМ ЛВ, В БАЗУ НЕ ПИШЕТ
* POST   /api/lk-proekty/import/apply       — то же + запись (propustit, delyanki — JSON)
* GET    /api/lk-proekty/potrebnost         — сколько посадочного материала на сезон
* GET    /api/lk-proekty/{id}               — проект целиком + проверки и допуски техприёмки
* PUT    /api/lk-proekty/{id}               — статус / делянка / примечание
* DELETE /api/lk-proekty/{id}
* GET    /api/lk-proekty/{id}/plan          — картинка плана участка
* GET    /api/lk-proekty/{id}/fail          — исходный файл из АРМ (перепечатать)
"""
import json
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Form
from fastapi.responses import Response
from pydantic import BaseModel

from app import lk_proekt as lp
from app.auth import get_current_user, require_permission
from app.database import get_conn

router = APIRouter(prefix="/api/lk-proekty", tags=["lk-proekty"])
PRAVO = "lesokultury.edit"
MAKS = 30 * 1024 * 1024


@router.get("")
def spisok(god: Optional[int] = None, status: Optional[str] = None, conn=Depends(get_conn),
           _u=Depends(get_current_user)):
    return lp.spisok(conn, god=god, status=status)


async def _faily(files: List[UploadFile]):
    out = []
    for f in files:
        data = await f.read()
        if len(data) > MAKS:
            raise HTTPException(400, f"{f.filename}: файл больше 30 МБ")
        out.append((f.filename or "proekt.doc", data))
    if not out:
        raise HTTPException(400, "Нет файлов")
    return out


@router.post("/import/preview")
async def import_preview(files: List[UploadFile] = File(...), conn=Depends(get_conn),
                         _u=Depends(require_permission(PRAVO))):
    return lp.publichnyy_plan(lp.plan_importa(conn, await _faily(files)))


@router.post("/import/apply")
async def import_apply(files: List[UploadFile] = File(...), propustit: Optional[str] = Form(None),
                       delyanki: Optional[str] = Form(None), conn=Depends(get_conn),
                       _u=Depends(require_permission(PRAVO))):
    try:
        prop = json.loads(propustit) if propustit else []
        dely = json.loads(delyanki) if delyanki else {}
    except ValueError:
        raise HTTPException(400, "propustit/delyanki: ожидается JSON")
    plan = lp.plan_importa(conn, await _faily(files))
    return lp.primenit(conn, plan, prop, dely)


@router.get("/potrebnost")
def potrebnost(god: Optional[int] = None, sezon: Optional[str] = None, conn=Depends(get_conn),
               _u=Depends(get_current_user)):
    return lp.potrebnost(conn, god=god, sezon=sezon)


@router.get("/{pid}")
def odin(pid: int, conn=Depends(get_conn), _u=Depends(get_current_user)):
    x = lp.odin(conn, pid)
    if not x:
        raise HTTPException(404, "Проект не найден")
    return x


class PravkaIn(BaseModel):
    status: Optional[str] = None
    delyanka_id: Optional[int] = None
    sbros_delyanki: bool = False
    primechanie: Optional[str] = None


@router.put("/{pid}")
def pravka(pid: int, body: PravkaIn, conn=Depends(get_conn), _u=Depends(require_permission(PRAVO))):
    if not lp.odin(conn, pid):
        raise HTTPException(404, "Проект не найден")
    dely = None if body.sbros_delyanki else (body.delyanka_id if body.delyanka_id else ...)
    try:
        return lp.obnovit(conn, pid, status=body.status, delyanka_id=dely, primechanie=body.primechanie)
    except lp.ProektError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/{pid}")
def udalit(pid: int, conn=Depends(get_conn), _u=Depends(require_permission(PRAVO))):
    lp.udalit(conn, pid)
    return {"ok": True}


@router.get("/{pid}/plan")
def plan(pid: int, conn=Depends(get_conn), _u=Depends(get_current_user)):
    x = lp.plan_kartinka(conn, pid)
    if not x:
        raise HTTPException(404, "Плана нет")
    ext = x[1].lower()
    tip = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp"}.get(ext, "application/octet-stream")
    return Response(content=x[0], media_type=tip)


@router.get("/{pid}/fail")
def fail(pid: int, conn=Depends(get_conn), _u=Depends(get_current_user)):
    x = lp.ishodnyy_fail(conn, pid)
    if not x:
        raise HTTPException(404, "Исходного файла нет")
    data, imya = x
    tip = "application/msword" if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(content=data, media_type=tip,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(imya)}"})
