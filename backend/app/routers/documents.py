# -*- coding: utf-8 -*-
"""Роутер "Документы" — единая точка просмотра/скачивания/удаления всех
файлов, сгенерированных остальными роутерами (таблица documents, см.
legacy/webext.py).

Этап 5 плана переноса, часть 1 (backend): фильтры по автору/периоду,
размер файла в списке, массовое скачивание zip и массовое удаление —
для глобального экрана "Документы" (frontend/src/pages/Documents.jsx,
часть 2)."""
import io
import os
import shutil
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401
import webext
import mdo_parser as legacy_mdo_parser

from app.database import get_conn
from app.auth import require_permission
from app.paths import DOCUMENTS_DIR, DOCUMENTS_ARCHIVE_DIR, PREVIEW_CACHE_DIR

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Документ считается доступным для скачивания и в готовом, и в
# заархивированном состоянии (пункт 1.4 TODO_DOMIGRACII.md) — архивация не
# должна прятать файл от того, кто уже знает, где его искать.
DOWNLOADABLE_STATUSES = {"готов", "архив"}


def _with_file_size(doc: dict) -> dict:
    """Добавляет file_size (байт) в ответ, читая размер с диска — отдельной
    колонки под это в схеме нет и не нужна, размер всегда актуален и на
    списке из десятков строк os.path.getsize достаточно быстр."""
    path = doc.get("file_path")
    doc["file_size"] = os.path.getsize(path) if path and os.path.exists(path) else None
    return doc


@router.get("/")
def list_documents(
    delyanka_id: Optional[int] = None,
    doc_type: Optional[str] = None,
    status: Optional[str] = None,
    created_by: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    conn=Depends(get_conn),
):
    docs = webext.list_documents(
        conn, delyanka_id=delyanka_id, doc_type=doc_type, status=status,
        created_by=created_by, date_from=date_from, date_to=date_to,
    )
    return [_with_file_size(d) for d in docs]


@router.get("/authors")
def list_document_authors(conn=Depends(get_conn)):
    """Для выпадающего фильтра "Автор" на экране документов."""
    return webext.list_document_authors(conn)


@router.get("/{document_id}")
def get_document(document_id: int, conn=Depends(get_conn)):
    doc = webext.get_document(conn, document_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    return doc


@router.get("/{document_id}/download")
def download_document(document_id: int, conn=Depends(get_conn)):
    doc = webext.get_document(conn, document_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    if doc["status"] not in DOWNLOADABLE_STATUSES or not doc["file_path"] or not os.path.exists(doc["file_path"]):
        raise HTTPException(409, "Файл документа недоступен (статус: %s)" % doc["status"])
    return FileResponse(doc["file_path"], filename=doc["file_name"])


@router.get("/{document_id}/preview")
def preview_document(document_id: int, conn=Depends(get_conn)):
    """Полноценный предпросмотр .docx/.xlsx в браузере (TODO п.1.5): по
    запросу конвертирует файл документа в PDF через LibreOffice headless
    (mdo_parser.convert_to_pdf — та же функция уже используется для
    rtf→docx при разборе МДО) и отдаёт PDF, который браузер показывает
    сам, без плагинов.

    Результат кэшируется в app.paths.PREVIEW_CACHE_DIR по document_id —
    повторные открытия одного документа не гоняют LibreOffice заново,
    только когда исходный файл на диске новее уже закэшированного PDF
    (на случай перегенерации документа с тем же id).

    Как и скачивание, доступен и для готовых, и для заархивированных
    документов (пункт 1.4) — архивация не должна прятать содержимое от
    предпросмотра."""
    doc = webext.get_document(conn, document_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    if doc["status"] not in DOWNLOADABLE_STATUSES or not doc["file_path"] or not os.path.exists(doc["file_path"]):
        raise HTTPException(409, "Файл документа недоступен (статус: %s)" % doc["status"])

    source_path = doc["file_path"]
    ext = Path(source_path).suffix.lower()
    if ext == ".pdf":
        return FileResponse(source_path, media_type="application/pdf",
                             filename=Path(source_path).name,
                             headers={"Content-Disposition": "inline"})
    if ext not in legacy_mdo_parser.PDF_CONVERTIBLE_EXTENSIONS:
        raise HTTPException(415, f"Предпросмотр для формата {ext or '(без расширения)'} не поддерживается")

    cached_pdf = PREVIEW_CACHE_DIR / f"{document_id}.pdf"
    needs_conversion = (
        not cached_pdf.exists()
        or os.path.getmtime(source_path) > os.path.getmtime(cached_pdf)
    )
    if needs_conversion:
        try:
            converted = legacy_mdo_parser.convert_to_pdf(source_path, str(PREVIEW_CACHE_DIR))
        except legacy_mdo_parser.SofficeNotFoundError as e:
            raise HTTPException(503, str(e))
        except (RuntimeError, ValueError) as e:
            raise HTTPException(500, f"Не удалось подготовить предпросмотр: {e}")
        # convert_to_pdf называет файл по исходному имени (stem source_path),
        # а кэш мы держим по document_id — переименовываем/перекладываем,
        # если конвертер положил файл под другим именем.
        converted_path = Path(converted)
        if converted_path != cached_pdf:
            if cached_pdf.exists():
                cached_pdf.unlink()
            converted_path.replace(cached_pdf)

    return FileResponse(str(cached_pdf), media_type="application/pdf",
                         filename=Path(doc["file_name"]).stem + ".pdf",
                         headers={"Content-Disposition": "inline"})


def _archive_target_path(doc: dict) -> str:
    """Имя файла в архиве с префиксом id документа — чтобы не столкнуться с
    одноимённым файлом другого документа (bulk-zip и обычный список от
    коллизий не страдают, а вот одна общая папка archive/ — вполне может)."""
    return os.path.join(DOCUMENTS_ARCHIVE_DIR, f"{doc['id']}_{doc['file_name']}")


@router.post("/{document_id}/archive")
def archive_document(document_id: int, user=Depends(require_permission("documents.archive")),
                      conn=Depends(get_conn)):
    """Пункт 1.4 TODO_DOMIGRACII.md: статус -> 'архив' + перенос файла в
    DOCUMENTS_ARCHIVE_DIR. Разрешено только для уже готовых документов."""
    doc = webext.get_document(conn, document_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    if doc["status"] != "готов":
        raise HTTPException(409, "Архивировать можно только готовый документ (статус: %s)" % doc["status"])
    new_path = _archive_target_path(doc)
    result = webext.archive_document(conn, document_id, new_path)
    if doc["file_path"] and os.path.exists(doc["file_path"]):
        os.makedirs(DOCUMENTS_ARCHIVE_DIR, exist_ok=True)
        shutil.move(doc["file_path"], new_path)
    return {"ok": True, **result}


@router.post("/{document_id}/unarchive")
def unarchive_document(document_id: int, user=Depends(require_permission("documents.archive")),
                        conn=Depends(get_conn)):
    """Обратная операция: статус 'архив' -> 'готов', файл — обратно в
    DOCUMENTS_DIR."""
    doc = webext.get_document(conn, document_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    if doc["status"] != "архив":
        raise HTTPException(409, "Документ не находится в архиве (статус: %s)" % doc["status"])
    new_path = os.path.join(DOCUMENTS_DIR, doc["file_name"])
    result = webext.unarchive_document(conn, document_id, new_path)
    if doc["file_path"] and os.path.exists(doc["file_path"]):
        shutil.move(doc["file_path"], new_path)
    return {"ok": True, **result}


@router.delete("/{document_id}")
def delete_document(document_id: int, user=Depends(require_permission("documents.delete")),
                     conn=Depends(get_conn)):
    file_path = webext.delete_document(conn, document_id)
    if file_path is None:
        raise HTTPException(404, "Документ не найден")
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
    return {"ok": True}


class BulkIdsRequest(BaseModel):
    ids: List[int]


@router.post("/bulk-delete")
def bulk_delete_documents(payload: BulkIdsRequest,
                           user=Depends(require_permission("documents.delete")),
                           conn=Depends(get_conn)):
    """Панель массовых действий экрана "Документы" → "Удалить" (с
    подтверждением на фронте). Возвращает результат по каждому id, чтобы
    показать, если что-то не удалилось (уже удалено кем-то другим и т.п.)."""
    if not payload.ids:
        raise HTTPException(400, "Список id пуст")
    results = webext.bulk_delete_documents(conn, payload.ids)
    for r in results:
        if r["ok"] and r.get("file_path") and os.path.exists(r["file_path"]):
            os.remove(r["file_path"])
            del r["file_path"]
    return {"results": results}


@router.post("/bulk-archive")
def bulk_archive_documents(payload: BulkIdsRequest,
                            user=Depends(require_permission("documents.archive")),
                            conn=Depends(get_conn)):
    """Панель массовых действий → «Архивировать». Документы, которые нельзя
    архивировать (уже в архиве, в процессе, с ошибкой, не найдены) —
    пропускаются молча, как и в bulk-zip; итог по каждому id возвращается,
    чтобы фронт мог сообщить, если что-то не заархивировалось."""
    if not payload.ids:
        raise HTTPException(400, "Список id пуст")
    os.makedirs(DOCUMENTS_ARCHIVE_DIR, exist_ok=True)
    results = []
    for document_id in payload.ids:
        doc = webext.get_document(conn, document_id)
        if doc is None:
            results.append({"id": document_id, "ok": False, "error": "не найден"})
            continue
        if doc["status"] != "готов":
            results.append({"id": document_id, "ok": False, "error": "статус: %s" % doc["status"]})
            continue
        new_path = _archive_target_path(doc)
        webext.archive_document(conn, document_id, new_path)
        if doc["file_path"] and os.path.exists(doc["file_path"]):
            shutil.move(doc["file_path"], new_path)
        results.append({"id": document_id, "ok": True})
    return {"results": results}


@router.post("/bulk-zip")
def bulk_download_zip(payload: BulkIdsRequest, conn=Depends(get_conn)):
    """Панель массовых действий → "Скачать выбранное (.zip)". Документы без
    готового файла на диске (в процессе/ошибка) пропускаются молча — в
    архив попадают только реально скачиваемые файлы (включая уже
    заархивированные, пункт 1.4); фронт сам решает, предупреждать ли
    пользователя, у него есть статус каждой строки."""
    buffer = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for document_id in payload.ids:
            doc = webext.get_document(conn, document_id)
            if not doc or doc["status"] not in DOWNLOADABLE_STATUSES or not doc["file_path"]:
                continue
            if not os.path.exists(doc["file_path"]):
                continue
            zf.write(doc["file_path"], arcname=doc["file_name"])
            added += 1
    if added == 0:
        raise HTTPException(409, "Ни один из выбранных документов не готов к скачиванию")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="documents.zip"'},
    )
