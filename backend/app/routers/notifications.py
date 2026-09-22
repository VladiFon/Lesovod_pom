# -*- coding: utf-8 -*-
"""Роутер "Уведомления" (колокольчик) — GET/PATCH /api/notifications поверх
notifications/notification_reads (см. legacy/webext.py). Создаются записи не
здесь, а в местах событий: POST /api/bot/breakdowns, /trelevka, /notes
(app/routers/bot.py) и POST /api/uhody/proby (app/routers/uhody.py) —
через webext.notify().

Права — require_office_or_master (app/auth.py), как у присутствия/заметок.
Видимость — как у заметок: общие (recipient NULL) плюс адресованные лично
читающему (по user["sotrudnik_id"] из токена); офисные логины видят только
общие. "Прочитано" — у каждого читателя своё (notification_reads), а не
один флаг на всех."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import webext
import webext

from app.auth import require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _reader(user: dict) -> tuple[str, int]:
    """Кто читает: рабочий-руководитель — по sotrudniki.id, офисный
    логин — по users.id (разные таблицы, поэтому пара тип+id)."""
    if user.get("role") == "worker":
        return "sotrudnik", user["sotrudnik_id"]
    return "user", user["id"]


@router.get("/")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> list[dict]:
    """Самые новые сверху; is_read — для ЭТОГО читателя."""
    reader_type, reader_id = _reader(user)
    return webext.list_notifications(
        conn, reader_type, reader_id, user.get("sotrudnik_id"), unread_only, limit,
    )


@router.get("/unread-count")
def unread_count(user=Depends(require_office_or_master), conn=Depends(get_conn)) -> dict:
    """Для точки на колокольчике — точное число, а не «есть ли непрочитанное
    среди последних N из списка»."""
    reader_type, reader_id = _reader(user)
    return {"unread": webext.count_unread_notifications(conn, reader_type, reader_id, user.get("sotrudnik_id"))}


class SetNotificationReadIn(BaseModel):
    is_read: bool = True


@router.patch("/{notification_id}")
def set_notification_read(
    notification_id: int,
    body: SetNotificationReadIn,
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> dict:
    """Отметка прочитанным — только для вошедшего; у остальных то же
    уведомление остаётся непрочитанным. Чужое адресное — 404."""
    reader_type, reader_id = _reader(user)
    ok = webext.set_notification_read(
        conn, notification_id, reader_type, reader_id, body.is_read, user.get("sotrudnik_id"),
    )
    if not ok:
        raise HTTPException(404, "Уведомление не найдено")
    return {"ok": True}


@router.post("/read-all")
def read_all(user=Depends(require_office_or_master), conn=Depends(get_conn)) -> dict:
    """«Прочитать всё» — тоже только для вошедшего."""
    reader_type, reader_id = _reader(user)
    return {"marked": webext.mark_all_notifications_read(conn, reader_type, reader_id, user.get("sotrudnik_id"))}
