# -*- coding: utf-8 -*-
"""Общие хелперы для фоновой генерации документов, используемые всеми
роутерами: (a) генерация делается вызовом существующей функции
(delyanka.py/*_generator.py/raskhod.py/forest_map.py), (b) результат
сохраняется в /backend/storage/documents/<task_id>/..., (c) метаданные
пишутся в таблицу documents (webext.py)."""
from pathlib import Path

from app.paths import DOCUMENTS_DIR
import webext


def new_task_dir(task_id: str) -> Path:
    d = DOCUMENTS_DIR / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def register_document(conn, doc_type, delyanka_id, path, created_by=None, status="готов", error_text=None):
    path = str(path)
    file_name = Path(path).name
    return webext.add_document(
        conn, doc_type, delyanka_id, file_name, path,
        status=status, error_text=error_text, created_by=created_by,
    )
