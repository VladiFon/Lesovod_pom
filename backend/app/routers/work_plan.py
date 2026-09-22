# -*- coding: utf-8 -*-
"""Роутер экрана "План работ" (Фаза 4 плана доработки веб-версии) —
недостающая веб-половина уже существующей мобильной функции: таблица
work_plan и мобильные эндпоинты (GET/POST .../complete в
app/routers/bot.py, только "свои" задачи рабочего) были заведены заранее
(см. legacy/webext.py:WORK_PLAN_SCHEMA), не хватало только
администраторского взгляда — список ВСЕХ задач сразу и полноценный
CRUD, а не только создание вручную через /docs.

Права — то же "work_plan.edit" (admin/lesovod), что уже используется для
POST /api/bot/work-plan (см. legacy/webext.py:PERMISSIONS) — одно право
на весь экран, просмотр отдельного "view" не заводим (задачи рабочих не
видны viewer-ролям, как и наряды/расход).

Мобильные эндпоинты (app/routers/bot.py: GET/POST .../work-plan) НЕ
трогаются и не дублируются здесь — они рассчитаны на другую identity
(рабочий видит только свои активные задачи по токену), а не на
администраторский список. create_work_plan_item/get_work_plan_for_sotrudnik/
complete_work_plan_item в legacy/webext.py тоже не меняются, этот роутер
использует отдельные новые функции (list_work_plan/get_work_plan_item/
update_work_plan_item/delete_work_plan_item), написанные специально под
"взгляд администратора" (сразу с ФИО сотрудника и кварталом/выделом
делянки в ответе, без ручного джойна на фронте)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import webext
import webext

from app.auth import require_permission
from app.database import get_conn

router = APIRouter(prefix="/api/work-plan", tags=["work_plan"])


@router.get("/")
def list_work_plan(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sotrudnik_id: Optional[int] = None,
    user=Depends(require_permission("work_plan.edit")),
    conn=Depends(get_conn),
) -> list[dict]:
    return webext.list_work_plan(conn, date_from=date_from, date_to=date_to, sotrudnik_id=sotrudnik_id)


@router.get("/sotrudniki")
def list_sotrudniki_for_picker(
    user=Depends(require_permission("work_plan.edit")), conn=Depends(get_conn)
) -> list[dict]:
    """Тот же принцип, что и GET /api/uhody/sotrudniki — лёгкий список для
    выбора исполнителя без прав users.manage (см. докстринг там же)."""
    return [s for s in webext.list_sotrudniki(conn) if s["is_active"]]


@router.get("/lesokultury-uchastki")
def list_lesokultury_uchastki_for_picker(
    search: Optional[str] = None,
    user=Depends(require_permission("work_plan.edit")), conn=Depends(get_conn)
) -> list[dict]:
    """Лёгкий список активных участков лесных культур — для переключателя
    "Делянка / Лесные культуры" в форме постановки задачи."""
    import db as legacy_db  # локальный импорт, как в остальных роутерах — после legacy_bridge
    return legacy_db.get_lesokultury_uchastki(conn, include_spisannye=False, search=search)


class WorkPlanCreateIn(BaseModel):
    sotrudnik_id: int
    data: str  # "ГГГГ-ММ-ДД"
    zadacha: str
    delyanka_item_id: Optional[int] = None
    lesokultury_uchastok_id: Optional[int] = None


@router.post("/")
def create_work_plan(
    body: WorkPlanCreateIn,
    user=Depends(require_permission("work_plan.edit")),
    conn=Depends(get_conn),
) -> dict:
    try:
        work_plan_id = webext.create_work_plan_item(
            conn, body.sotrudnik_id, body.data, body.zadacha, body.delyanka_item_id,
            lesokultury_uchastok_id=body.lesokultury_uchastok_id,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return webext.get_work_plan_item(conn, work_plan_id)


class WorkPlanUpdateIn(BaseModel):
    data: Optional[str] = None
    zadacha: Optional[str] = None
    sotrudnik_id: Optional[int] = None
    delyanka_item_id: Optional[int] = -1  # -1 = не менять, см. update_work_plan_item
    lesokultury_uchastok_id: Optional[int] = -1  # -1 = не менять, см. update_work_plan_item
    status: Optional[str] = None


@router.patch("/{work_plan_id}")
def update_work_plan(
    work_plan_id: int,
    body: WorkPlanUpdateIn,
    user=Depends(require_permission("work_plan.edit")),
    conn=Depends(get_conn),
) -> dict:
    if webext.get_work_plan_item(conn, work_plan_id) is None:
        raise HTTPException(404, "Задача не найдена")
    try:
        webext.update_work_plan_item(
            conn, work_plan_id,
            data=body.data, zadacha=body.zadacha, sotrudnik_id=body.sotrudnik_id,
            delyanka_item_id=body.delyanka_item_id,
            lesokultury_uchastok_id=body.lesokultury_uchastok_id,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return webext.get_work_plan_item(conn, work_plan_id)


@router.delete("/{work_plan_id}")
def delete_work_plan(
    work_plan_id: int,
    user=Depends(require_permission("work_plan.edit")),
    conn=Depends(get_conn),
) -> dict:
    if webext.get_work_plan_item(conn, work_plan_id) is None:
        raise HTTPException(404, "Задача не найдена")
    webext.delete_work_plan_item(conn, work_plan_id)
    return {"ok": True, "id": work_plan_id}
