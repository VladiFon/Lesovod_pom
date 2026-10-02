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


# Без слеша тоже: мобильное приложение ходит на /api/…без "/" на конце, а
# автоматический 307-редирект FastAPI за прокси уводил на http:// — Android
# такой редирект блокирует и показывал «Нет соединения с интернетом».
@router.get("", include_in_schema=False)
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


class NoteReplyIn(BaseModel):
    text: str


@router.post("/{note_id}/reply")
def reply_to_note(
    note_id: int,
    body: NoteReplyIn,
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> dict:
    """Ответить рабочему на заметку — ответ увидит автор в «Моих заметках»
    приложения и получит уведомление."""
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Пустой ответ")
    kto = user.get("fio") or user.get("login") or ""
    if not webext.otvetit_na_zametku(conn, note_id, text, kto):
        raise HTTPException(404, "Заметка не найдена")
    return {"ok": True}


@router.get("/metki")
def list_metki(
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> list[dict]:
    """Метки рабочих с карты приложения (ветровал, склад, дорога…) — на
    сайте, чтобы из метки можно было поставить задачу."""
    from app import map_features

    cats = {c["code"]: c["label"] for c in map_features.GEO_NOTE_CATEGORIES}
    notes = map_features.list_geo_notes(conn)
    for n in notes:
        n["kategoriya_label"] = cats.get(n["kategoriya"], n["kategoriya"])
    return notes
