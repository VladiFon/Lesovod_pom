# -*- coding: utf-8 -*-
"""
Делает /backend/legacy доступной для импорта как обычный путь модулей —
чтобы роутеры могли писать `import delyanka`, `import db`, `import
akt_generator` и т.д., как это делает существующий код (например,
delyanka.py сам пишет `from db import get_vydel_card`).

Импортировать этот модуль ДО первого `import delyanka`/`import db`/...
в любом файле, где они нужны:

    from app import legacy_bridge  # noqa: F401 — только ради sys.path
    import delyanka
    import db

Сами файлы в /backend/legacy (delyanka.py, db.py, akt_generator.py и
т.д.) — это НЕИЗМЕНЁННЫЕ копии исходных модулей проекта (кроме config.py,
который в /backend/legacy — новый, headless, см. legacy/config.py), плюс
webext.py — новый модуль расширения схемы БД (таблицы documents/
background_tasks).
"""
import sys
from pathlib import Path

LEGACY_DIR = Path(__file__).resolve().parent.parent / "legacy"

_legacy_path = str(LEGACY_DIR)
if _legacy_path not in sys.path:
    sys.path.insert(0, _legacy_path)
