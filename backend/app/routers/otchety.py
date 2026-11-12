"""Экран «Отчёты» (разбор сайта 09.11.2026, шаг 2): сводка за месяц для
начальства — app/svodka_nachalstvu.py."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app import legacy_bridge  # noqa: F401 — обязателен до legacy-импортов
from app.auth import require_office_or_master
from app.database import get_conn
from app import svodka_nachalstvu

router = APIRouter(prefix="/api/otchety", tags=["otchety"])


@router.get("/svodka")
def get_svodka(ym: Optional[str] = None, user=Depends(require_office_or_master), conn=Depends(get_conn)) -> dict:
    import datetime
    try:
        return svodka_nachalstvu.svodka(conn, ym or datetime.date.today().strftime("%Y-%m"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/itogi")
def get_itogi(god: Optional[int] = None, user=Depends(require_office_or_master), conn=Depends(get_conn)) -> dict:
    """Итоги сезона: год целиком и сравнение с прошлым."""
    import datetime
    try:
        return svodka_nachalstvu.itogi(conn, god or datetime.date.today().year)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
