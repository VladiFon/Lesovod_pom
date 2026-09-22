# -*- coding: utf-8 -*-
"""Роутер "Архив документов" (screens/archive/) — оборачивает
db.add_archive_document/search_archive_documents (SQL-поиск по
title/tags/doc_type) без изменения логики.

До Этапа 11 этот backend не существовал вовсе (в отличие от остальных
экранов, где роутер уже был готов в lesovod_backend_stage2.zip) —
добавлен здесь заново по мотивам screens/archive/screen_logic.py.

Файлы — обычные ручные загрузки лесничего (сканы приказов и т.п.), а не
результат генерации, поэтому хранятся не в app.paths.DOCUMENTS_DIR
(там — задачи генерации по task_id), а в отдельной app.paths.UPLOADS_DIR/
archive/ — эта директория была зарезервирована в app/paths.py именно под
такие случаи, но до сих пор ни один роутер её не использовал."""
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app import legacy_bridge  # noqa: F401
import db as legacy_db

from app.database import get_conn
from app.paths import UPLOADS_DIR

router = APIRouter(prefix="/api/archive", tags=["archive"])

ARCHIVE_DIR = UPLOADS_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

# 1:1 из screens/archive/screen_ui.py — DOC_TYPES.
DOC_TYPES = ["Приказы", "Списки делянок", "Прочее"]


@router.get("/doc-types")
def list_doc_types():
    return DOC_TYPES


@router.get("/documents")
def search_documents(query: str = "", doc_type: str = "", conn=Depends(get_conn)):
    return legacy_db.search_archive_documents(conn, query=query, doc_type=doc_type)


@router.post("/documents")
def add_document(
    title: str,
    doc_type: str = "",
    doc_date: str = "",
    tags: str = "",
    file: UploadFile = File(...),
    conn=Depends(get_conn),
):
    """title/doc_type/doc_date/tags вводятся лесничим вручную (см. докстринг
    screen_logic.py — Этап F desktop-версии убрал автозаполнение через
    Gemini/OpenRouter, полностью ручной ввод)."""
    ext = Path(file.filename or "").suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = ARCHIVE_DIR / stored_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    doc_id = legacy_db.add_archive_document(conn, title, doc_type, doc_date, tags, str(dest))
    return {"id": doc_id}


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, conn=Depends(get_conn)):
    rows = legacy_db.search_archive_documents(conn)
    doc = next((d for d in rows if d["id"] == document_id), None)
    if doc is None or not doc.get("file_path") or not os.path.exists(doc["file_path"]):
        raise HTTPException(404, "Файл не найден")
    return FileResponse(doc["file_path"], filename=os.path.basename(doc["file_path"]))


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, conn=Depends(get_conn)):
    rows = legacy_db.search_archive_documents(conn)
    doc = next((d for d in rows if d["id"] == document_id), None)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    conn.execute("DELETE FROM archive_documents WHERE id = ?", (document_id,))
    conn.commit()
    if doc.get("file_path") and os.path.exists(doc["file_path"]):
        os.remove(doc["file_path"])
    return {"ok": True}
