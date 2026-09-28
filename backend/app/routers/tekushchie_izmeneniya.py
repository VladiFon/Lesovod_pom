# -*- coding: utf-8 -*-
"""Роутер «Текущие изменения» — ведомости по приказу Минлесхоза №130
(см. app/tekushchie_izmeneniya.py). Пока прил. 4, 7, 14 из «Лесных культур»."""
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app import tekushchie_izmeneniya as ti
from app.auth import get_current_user
from app.database import get_conn

router = APIRouter(prefix="/api/tekushchie-izmeneniya", tags=["tekushchie-izmeneniya"])

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _check_god(god: int) -> None:
    if not 2000 <= god <= 2100:
        raise HTTPException(400, "Год — четыре цифры, например 2026")


@router.get("/lesokultury")
def preview_lesokultury(
    god: int,
    lesnichestvo: str = "",
    conn=Depends(get_conn), _user=Depends(get_current_user),
):
    """Строки прил. 4, 7, 14 за год и замечания (чего не хватает в данных)."""
    _check_god(god)
    data = ti.build(conn, god, lesnichestvo.strip())
    return {
        "god": god,
        "prilozheniya": [
            {"nomer": n, "title": ti.TITLES[n], "columns": ti.COLUMNS[n], **data[n]}
            for n in (4, 7, 14)
        ],
    }


@router.post("/lesokultury/docx")
async def docx_lesokultury(
    god: int = Form(...),
    lesnichestvo: str = Form(""),
    data_zapolneniya: str = Form(""),
    shablon: Optional[UploadFile] = File(None),
    conn=Depends(get_conn), _user=Depends(get_current_user),
):
    """Word по шаблону ведомостей: заполняются таблицы прил. 4, 7, 14, в шапках
    меняются год и дата заполнения. shablon — свой «Таблицы … ЗАПОЛНЯТЬ
    ЗДЕСЬ.docx» (если не прислан — встроенный)."""
    _check_god(god)
    template = await shablon.read() if shablon is not None else None
    data = ti.build(conn, god, lesnichestvo.strip())
    try:
        content = ti.make_docx(data, god, template or None, data_zapolneniya.strip() or None)
    except ti.TIError as exc:
        raise HTTPException(400, str(exc))
    name = f"Текущие изменения {god}" + (f" {lesnichestvo.strip()}" if lesnichestvo.strip() else "") + ".docx"
    return Response(
        content,
        media_type=DOCX_TYPE,
        headers={"Content-Disposition": f"attachment; filename=\"tekushchie_izmeneniya_{god}.docx\"; "
                                        f"filename*=UTF-8''{quote(name)}"},
    )
