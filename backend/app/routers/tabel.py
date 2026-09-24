# -*- coding: utf-8 -*-
"""Роутер "Табель — ручной ввод" (по просьбе пользователя, 24.09.2026).

Пока мобильное приложение есть только у начальства, рядовые рабочие
(лесорубы, вальщики, трактористы — они уже есть в справочнике
"Сотрудники") сами в attendance_marks не попадают — append-only лента
заполняется только тем, кто отметился в телефоне. Этот экран даёт
лесничему заполнить табель на них руками: не только "работал/не работал",
но и где работал (делянка или участок лесных культур) и что делал (вид
работы), одной строкой на сотрудника за день.

Отдельная таблица tabel_zapis (см. legacy/webext.py:TABEL_ZAPIS_SCHEMA),
не attendance_marks — разный смысл записи (одна ИТОГОВАЯ запись дня,
которую можно поправить, а не лог отметок) и разные поля (место/вид
работы/комментарий, которых в мобильной ленте физически нет).

Права: require_office_or_master (app/auth.py) — admin/lesovod либо
рабочий (обычный PIN-вход мобильного приложения) с руководящей
должностью (config.DOLZHNOSTI_MASTER_URODNYA: мастер леса/помощник
лесничего/лесничий), тот же принцип, что у attendance/trelevka/notes.
(Раньше здесь стоял require_permission("tabel.edit"), а PERMISSIONS
даёт это действие только admin/lesovod — рабочие с role="worker" не
проходили вообще, независимо от должности; это не совпадало с тем, что
экран как раз для них и делался, поэтому переведено на
require_office_or_master, как и у остальных мобильных экранов
руководителей.)"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import webext
import webext

from app.auth import require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/tabel", tags=["tabel"])


@router.get("/vidy-rabot")
def list_vidy_rabot(user=Depends(require_office_or_master), conn=Depends(get_conn)) -> list[dict]:
    return webext.list_vidy_rabot(conn)


class VidRabotyCreateIn(BaseModel):
    nazvanie: str


@router.post("/vidy-rabot")
def create_vid_raboty(
    body: VidRabotyCreateIn,
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> dict:
    """Возвращает существующий вид работы, если название уже есть в
    справочнике (не плодит дубли при повторном вводе того же названия
    разными пользователями) — см. webext.get_or_create_vid_raboty."""
    try:
        vid_raboty_id = webext.get_or_create_vid_raboty(conn, body.nazvanie)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": vid_raboty_id, "nazvanie": body.nazvanie.strip()}


@router.get("/lesokultury-uchastki")
def list_lesokultury_uchastki_for_picker(
    search: Optional[str] = None,
    user=Depends(require_office_or_master), conn=Depends(get_conn),
) -> list[dict]:
    """Тот же принцип и источник, что GET /api/work-plan/lesokultury-uchastki
    (см. докстринг там же) — не переиспользуем тот эндпоинт напрямую,
    чтобы права экрана "Табель" не были завязаны на право экрана "План
    работ" (даже если сейчас у них один и тот же круг ролей)."""
    import db as legacy_db  # локальный импорт, как в остальных роутерах — после legacy_bridge
    return legacy_db.get_lesokultury_uchastki(conn, include_spisannye=False, search=search)


@router.get("/day")
def get_tabel_day(
    data: str,
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> list[dict]:
    """Табель на один день — строка на КАЖДОГО активного сотрудника (не
    только уже заполненных), см. webext.get_tabel_day. data — "ГГГГ-ММ-ДД"."""
    return webext.get_tabel_day(conn, data)


class TabelEntryIn(BaseModel):
    sotrudnik_id: int
    status: str  # работал | не работал | больничный | отпуск | выходной
    delyanka_item_id: Optional[int] = None
    lesokultury_uchastok_id: Optional[int] = None
    vid_raboty_id: Optional[int] = None
    kommentariy: str = ""


class TabelDaySaveIn(BaseModel):
    data: str
    entries: list[TabelEntryIn]


@router.post("/day")
def save_tabel_day(
    body: TabelDaySaveIn,
    user=Depends(require_office_or_master),
    conn=Depends(get_conn),
) -> list[dict]:
    """Пакетное сохранение табеля на один день — см. webext.save_tabel_day
    (UPSERT: повторное сохранение того же дня исправляет уже введённые
    записи, а не плодит дубли)."""
    try:
        webext.save_tabel_day(
            conn, body.data, [e.dict() for e in body.entries], entered_by=user["login"],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return webext.get_tabel_day(conn, body.data)
