# -*- coding: utf-8 -*-
"""Роутер "Рабочий календарь" (screens/calendar/) — оборачивает
legacy/calendar_tasks.py (чистый Python, без Qt — специально написан так,
чтобы им мог пользоваться и бейдж уведомлений в шапке, см. докстринг
calendar_tasks.count_needs_attention) без изменения логики.

До Этапа 12 модуль calendar_tasks.py не входил в
lesovod_backend_stage2.zip вовсе (ни как router, ни как legacy-файл) —
скопирован сюда из lesovod_project_fixed_v5.zip как есть. Таблицы
calendar_tasks/calendar_completions уже были в схеме db.py (см.
CREATE TABLE calendar_tasks) — сам модуль просто не был подключён ни к
одному роутеру."""
from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401
import calendar_tasks as ct

from app.database import get_conn

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _serialize(task: dict) -> dict:
    """compute_status() кладёт в задачу due_date как объект date — FastAPI
    не умеет сериализовать его в JSON без явного приведения к строке."""
    out = dict(task)
    if isinstance(out.get("due_date"), date):
        out["due_date"] = out["due_date"].isoformat()
    return out


@router.get("/tasks")
def list_tasks(include_inactive: bool = False, conn=Depends(get_conn)):
    return [_serialize(t) for t in ct.list_tasks(conn, include_inactive=include_inactive)]


@router.get("/tasks/{task_id}")
def get_task(task_id: int, conn=Depends(get_conn)):
    task = ct.get_task(conn, task_id)
    if task is None:
        raise HTTPException(404, "Задача не найдена")
    return task


class TaskIn(BaseModel):
    title: str
    description: str = ""
    category: str = ""
    recurrence: str = "once"
    recurrence_config: Dict[str, Any] = {}


@router.post("/tasks")
def create_task(body: TaskIn, conn=Depends(get_conn)):
    task_id = ct.create_task(conn, body.title, body.description, body.category, body.recurrence, body.recurrence_config)
    return {"id": task_id}


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskIn, conn=Depends(get_conn)):
    if ct.get_task(conn, task_id) is None:
        raise HTTPException(404, "Задача не найдена")
    ct.update_task(conn, task_id, body.title, body.description, body.category, body.recurrence, body.recurrence_config)
    return {"ok": True}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, conn=Depends(get_conn)):
    if ct.get_task(conn, task_id) is None:
        raise HTTPException(404, "Задача не найдена")
    ct.delete_task(conn, task_id)
    return {"ok": True}


@router.post("/tasks/{task_id}/active")
def set_task_active(task_id: int, active: bool, conn=Depends(get_conn)):
    ct.set_task_active(conn, task_id, active)
    return {"ok": True}


class CompleteIn(BaseModel):
    period_key: str
    note: str = ""


@router.post("/tasks/{task_id}/complete")
def mark_done(task_id: int, body: CompleteIn, conn=Depends(get_conn)):
    ct.mark_done(conn, task_id, body.period_key, body.note)
    return {"ok": True}


@router.delete("/tasks/{task_id}/complete/{period_key}")
def unmark_done(task_id: int, period_key: str, conn=Depends(get_conn)):
    ct.unmark_done(conn, task_id, period_key)
    return {"ok": True}


@router.get("/needs-attention-count")
def needs_attention_count(conn=Depends(get_conn)):
    return {"count": ct.count_needs_attention(conn)}
