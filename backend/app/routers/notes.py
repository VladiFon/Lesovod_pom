# -*- coding: utf-8 -*-
"""Роутер "Заметки рабочего начальнику" (веб, взгляд мастера/лесничего) —
GET/PATCH /api/notes поверх worker_notes (см. legacy/webext.py:
WORKER_NOTES_SCHEMA). Односторонняя лента, не переписка: создаёт только
рабочий (POST /api/bot/notes, app/routers/bot.py), здесь — только чтение
и отметка прочитанным, ответа обратно рабочему не предусмотрено.

Права — require_office_or_master (app/auth.py), как и в
app/routers/attendance.py: admin/lesovod либо рабочий с руководящей
должностью (config.DOLZHNOSTI_MASTER_URODNYA); остальным — 403, личные
заметки рабочих не должны читать коллеги.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import webext
import webext

from app.auth import require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("/")
def list_notes(
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> list[dict]:
    """Лента заметок — непрочитанные и самые новые наверху (см.
    webext.list_worker_notes), с ФИО/должностью сотрудника уже
    приджойненными. Общие заметки (без получателя) видят все с доступом к
    разделу; адресные — только сам получатель (по user["sotrudnik_id"] из
    токена; офисным логинам, у которых его нет, — только общие)."""
    return webext.list_worker_notes(conn, user.get("sotrudnik_id"))


class SetNoteReadIn(BaseModel):
    is_read: bool = True


@router.patch("/{note_id}")
def set_note_read(
    note_id: int,
    body: SetNoteReadIn,
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> dict:
    ok = webext.set_worker_note_read(conn, note_id, body.is_read, user.get("sotrudnik_id"))
    if not ok:
        raise HTTPException(404, "Заметка не найдена")
    return {"ok": True}
