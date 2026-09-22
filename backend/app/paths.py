# -*- coding: utf-8 -*-
"""Пути хранения файлов backend-слоя."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.environ.get("LESOVOD_STORAGE_DIR") or (BACKEND_DIR / "storage"))
DOCUMENTS_DIR = STORAGE_DIR / "documents"
UPLOADS_DIR = STORAGE_DIR / "uploads"
# Пункт 1.4 TODO_DOMIGRACII.md — «Архивировать» физически переносит файл
# сюда (плюс статус документа меняется на 'архив', см. webext.py). Отдельная
# подпапка, а не просто пометка в БД, чтобы архив было видно и на диске —
# так же, как в исходном решении по продукту (перенос файла + статус).
DOCUMENTS_ARCHIVE_DIR = DOCUMENTS_DIR / "archive"

# Кэш PDF-конвертаций для предпросмотра .docx/.xlsx в браузере (TODO п.1.5)
# — держим отдельно от DOCUMENTS_DIR, чтобы не путать сгенерированные
# документы с производными файлами для предпросмотра.
PREVIEW_CACHE_DIR = STORAGE_DIR / "preview_cache"

DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
DOCUMENTS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
