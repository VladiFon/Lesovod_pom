# -*- coding: utf-8 -*-
"""Роутер "Таксация" (screens/taxation/) — оборачивает db.build_db/
db.get_vydel_card, без изменения их внутренней логики."""
import shutil
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from app import legacy_bridge  # noqa: F401
import config as legacy_config
import db as legacy_db

from app.database import get_conn
from app.paths import UPLOADS_DIR
import webext

router = APIRouter(prefix="/api/taxation", tags=["taxation"])


def _run_build_db(task_id: str, docx_paths: List[str], reset: bool):
    import sqlite3
    conn = sqlite3.connect(legacy_config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        webext.set_task_running(conn, task_id)
    finally:
        conn.close()

    try:
        # build_db открывает СВОЁ собственное соединение на db_path и не
        # закрывает его сама (см. db.py: возвращает conn для интерактивного
        # использования в __main__) — закрываем сами после использования.
        result_conn = legacy_db.build_db(docx_paths, db_path=legacy_config.DB_PATH, reset=reset)
        result_conn.close()
        status_conn = sqlite3.connect(legacy_config.DB_PATH)
        try:
            webext.set_task_done(status_conn, task_id, result={"docx_files": [p for p in docx_paths]})
        finally:
            status_conn.close()
    except Exception as e:  # noqa: BLE001
        status_conn = sqlite3.connect(legacy_config.DB_PATH)
        try:
            webext.set_task_error(status_conn, task_id, str(e))
        finally:
            status_conn.close()
    finally:
        for p in docx_paths:
            import os
            if os.path.exists(p):
                os.remove(p)


@router.post("/build")
def build_taxation_db(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    reset: bool = True,
    conn=Depends(get_conn),
):
    """Загружает одно или несколько таксационных описаний (.docx) и
    перестраивает справочник lesnichestvo/kvartal/vydel/sostav в фоне
    (может быть долгим на больших выгрузках)."""
    saved_paths = []
    for f in files:
        dest = UPLOADS_DIR / f"taksatsia_{uuid4().hex}_{f.filename}"
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved_paths.append(str(dest))

    task_id = webext.create_task(conn, "build_taxation_db")
    background_tasks.add_task(_run_build_db, task_id, saved_paths, reset)
    return {"task_id": task_id}


@router.get("/lesnichestva")
def list_lesnichestva(conn=Depends(get_conn)):
    """Список лесничеств, ORDER BY name — тот же запрос, что был в
    load_lesnichestva() (screens/taxation/screen_data.py, раньше жил прямо
    в экране, отдельного backend-эндпоинта под него не было)."""
    try:
        rows = conn.execute("SELECT name FROM lesnichestvo ORDER BY name").fetchall()
    except Exception:  # noqa: BLE001 — таблицы ещё нет, пока не загружена таксация
        return []
    return [r[0] for r in rows if r and r[0]]


@router.get("/vydel")
def get_vydel(kvartal: str, vydel: str, lesnichestvo: Optional[str] = None, conn=Depends(get_conn)):
    card = legacy_db.get_vydel_card(conn, kvartal, vydel, lesnichestvo_name=lesnichestvo)
    if card is None:
        raise HTTPException(404, "Выдел не найден в таксации")
    return card
