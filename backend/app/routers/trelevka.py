# -*- coding: utf-8 -*-
"""Роутер "Трелёвка" (веб, взгляд мастера/лесничего) — GET /api/trelevka
поверх таблицы trelevka (см. legacy/webext.py:TRELEVKA_SCHEMA). Создаёт
записи только тракторист из мобильного приложения (POST /api/bot/trelevka,
app/routers/bot.py), здесь — только чтение.

Права — require_office_or_master (app/auth.py), как у присутствия и
заметок: admin/lesovod/viewer либо рабочий с руководящей должностью."""
from typing import Optional

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401 — обязателен до import webext
import webext

from app.auth import require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/trelevka", tags=["trelevka"])


@router.get("/")
def list_trelevka(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sotrudnik_id: Optional[int] = None,
    delyanka_item_id: Optional[int] = None,
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> list[dict]:
    """date_from/date_to — "ГГГГ-ММ-ДД", включительно."""
    return webext.list_trelevka(
        conn, date_from=date_from, date_to=date_to,
        sotrudnik_id=sotrudnik_id, delyanka_item_id=delyanka_item_id,
    )
