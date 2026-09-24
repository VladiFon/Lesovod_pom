# -*- coding: utf-8 -*-
"""Роутер "Учёт времени/присутствия" (веб, взгляд мастера/лесничего) —
GET /api/attendance поверх уже готовой таблицы attendance_marks (см.
legacy/webext.py:ATTENDANCE_MARKS_SCHEMA) и мобильных эндпоинтов
POST/GET /api/bot/attendance[/latest] в app/routers/bot.py — те не
трогались и не дублируются здесь, у них другая identity (рабочий видит
по своему токену только свою последнюю отметку, а не сводку по всем).

Права: require_office_or_master (app/auth.py) — admin/lesovod либо
рабочий с руководящей должностью (config.DOLZHNOSTI_MASTER_URODNYA).
Эндпоинт отдаёт координаты живых людей, поэтому остальным рабочим, боту
и viewer — 403. GET-эндпоинты остального приложения исторически логин не
проверяют — это отдельный, более широкий вопрос, здесь не решается.
"""
from typing import Optional

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401 — обязателен до import webext
import webext

from app.auth import require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


@router.get("/")
def list_attendance(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sotrudnik_id: Optional[int] = None,
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> list[dict]:
    """Сводка "кто сегодня работал" — с ФИО/должностью/участком сотрудника
    уже приджойненными (см. webext.list_attendance_marks). date_from/
    date_to — "ГГГГ-ММ-ДД", включительно."""
    return webext.list_attendance_marks(conn, date_from=date_from, date_to=date_to, sotrudnik_id=sotrudnik_id)


@router.get("/tabel")
def list_tabel_for_grid(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> list[dict]:
    """Записи табеля ручного ввода (см. app/routers/tabel.py) за период —
    для слияния в ту же месячную сетку "Присутствие" на фронте
    (Attendance.jsx запрашивает и это, и "/" выше, и сводит вместе)."""
    return webext.list_tabel_zapisi(conn, date_from=date_from, date_to=date_to)
