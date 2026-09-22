# -*- coding: utf-8 -*-
"""Единая точка опроса статуса фоновых задач, поставленных любым другим
роутером (импорт МДО, генерация документов, парсинг ЕГАИС, пересчёт
таксации, пересчёт карты) — см. legacy/webext.py."""
from fastapi import APIRouter, Depends, HTTPException

from app import legacy_bridge  # noqa: F401
import webext

from app.database import get_conn

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}")
def get_task(task_id: str, conn=Depends(get_conn)):
    task = webext.get_task(conn, task_id)
    if task is None:
        raise HTTPException(404, "Задача не найдена")
    return task
