# -*- coding: utf-8 -*-
"""
Расширение схемы БД для backend-слоя: таблица `documents` (метаданные
любого сгенерированного файла — Акт/Листок/Техкарта/Справка/Акт
освидетельствования/экспорт Книги расхода/карта леса), таблица
`background_tasks` (статусы долгих фоновых операций, опрашиваемые через
GET /api/tasks/{task_id}), а с Этапа 2 плана переноса в веб — ещё и
`users`/`sessions` (многопользовательский режим: логин/сессии/роли) плюс
функции проверки прав has_permission().

Почему отдельным файлом, а не прямо дописано в db.py: db.py — 2230+ строк,
единый SQL-скрипт SCHEMA и ~60 функций уже работающего десктоп-приложения.
Ручной построчный перенос всего файла в чат (требование задания — присылать
ПОЛНОЕ содержимое каждого меняемого файла) создаёт неоправданный риск
опечатки при переписывании файла такого размера. Данный модуль решает ту же
задачу — новые таблицы, создаваемые "если их ещё нет" — но безопасным
способом: через CREATE TABLE IF NOT EXISTS на том же sqlite3-соединении, без
единой правки существующего db.py (кроме точечных ALTER TABLE в
migrate_schema() для updated_at/updated_by — см. комментарий там). Если
хотите, финальный SQL отсюда можно позже вручную перенести внутрь SCHEMA в
db.py — работать будет одинаково в обоих случаях (это обычные таблицы SQLite
на той же базе).
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta

DOCUMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type TEXT NOT NULL,
    delyanka_id INTEGER,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'готов',
    error_text TEXT,
    created_by TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_documents_delyanka_id ON documents(delyanka_id);
CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents(doc_type);
"""

TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS background_tasks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress TEXT,
    result_json TEXT,
    error_text TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""

# --------------------------------------------------------------------------- #
#   Этап 2: пользователи и сессии
# --------------------------------------------------------------------------- #
# Роли и их права см. в PERMISSIONS/has_permission() ниже. Три роли — ровно
# то, что просил план: admin (полный доступ, включая управление
# пользователями и настройками), lesovod (полный доступ к делянкам и
# документам), viewer (только просмотр/скачивание).
ROLES = ("admin", "lesovod", "viewer")

# Роль "bot" (Этап 4, Блок 3/часть 2) НАМЕРЕННО не входит в ROLES выше:
# ROLES — это только роли настоящих строк таблицы users (валидируются
# в create_user()/set_user_role(), и то же самое перечисление зашито в
# CHECK-ограничение колонки users.role в USERS_SCHEMA ниже). У бота нет
# ни логина, ни пароля, ни собственной строки в users — он один процесс
# на весь лесхоз, поэтому вместо строки в БД у него один статический
# токен из переменной окружения (config.get_bot_service_token()) и вот
# эта строка-константа, которую app/auth.py подставляет в синтетический
# dict пользователя при успешном сравнении токена. has_permission() ниже
# просто сравнивает user["role"] со списком в PERMISSIONS — ей всё равно,
# пришла ли роль из строки users или была собрана на лету, поэтому менять
# CHECK-ограничение/схему users не потребовалось.
BOT_ROLE = "bot"

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    fio TEXT,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'lesovod', 'viewer')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""

# Простые токен-сессии (не JWT): токен — случайная строка, живёт в БД со
# сроком действия. Проще для "сервер на локальной сети", не требует
# секретного ключа для подписи и позволяет мгновенно отозвать сессию
# (DELETE FROM sessions) — например, при увольнении сотрудника.
SESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
"""

SESSION_LIFETIME_DAYS = 14

# --------------------------------------------------------------------------- #
#   Мобильное приложение (Фаза 6 плана доработки): рабочие — отдельная
#   учётная система от users (админ/лесовод/viewer). У рабочего нет
#   Telegram — вход по логину+PIN. Токен-сессии устроены так же, как у
#   users/sessions выше (простой случайный токен в БД, не JWT — та же
#   причина: локальный сервер, мгновенный отзыв через DELETE), но
#   намеренно отдельная таблица sessions — рабочий не должен получать
#   права ролей admin/lesovod/viewer, у него свой набор прав (см.
#   PERMISSIONS["bot.access"] ниже — тот же контур, что и у Telegram-бота,
#   тот же роутер app/routers/bot.py).
#
#   Поля fio/dolzhnost/uchastok — то же самое, что просил "Фаза 1 —
#   Справочник сотрудников" плана доработки веб-версии; login/pin_hash
#   добавлены здесь же, а не отдельной таблицей, чтобы не создавать два
#   разных "рабочий" сразу — когда дойдёте до полноценного экрана
#   справочника в Settings.jsx, он будет работать с этой же таблицей.
SOTRUDNIKI_SCHEMA = """
CREATE TABLE IF NOT EXISTS sotrudniki (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT UNIQUE NOT NULL,
    pin_hash TEXT NOT NULL,
    fio TEXT NOT NULL,
    dolzhnost TEXT,
    uchastok TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""

WORKER_SESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS worker_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sotrudnik_id INTEGER NOT NULL REFERENCES sotrudniki(id),
    token TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_worker_sessions_token ON worker_sessions(token);
"""

# Минимальная версия "Фаза 4 — Планирование работы сотрудникам" из плана
# доработки веб-версии: сама таблица и функции чтения/отметки для
# мобильного приложения заведены уже сейчас (без них рабочему нечего
# показывать в "Моих задачах"), полноценный календарный экран постановки
# задач в веб-панели — по вашему решению, отдельным шагом позже. До того,
# как он появится, строки в work_plan можно заводить вручную через /docs
# (POST /api/auth/... появится там же, где остальные admin-эндпоинты).
WORK_PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,
    sotrudnik_id INTEGER NOT NULL REFERENCES sotrudniki(id),
    delyanka_item_id INTEGER REFERENCES delyanka_item(id),
    lesokultury_uchastok_id INTEGER REFERENCES lesokultury_uchastok(id),
    zadacha TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'активна',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_work_plan_sotrudnik ON work_plan(sotrudnik_id, status);
"""

# Отметка времени/присутствия (раздел 3.6 плана мобильного приложения):
# рабочий разово отмечает "Работаю"/"Не работаю"/"Больничный" на телефоне,
# с геометкой в момент отметки (не постоянное слежение — см. докстринг
# POST /api/bot/attendance в app/routers/bot.py). Таблица append-only —
# каждая отметка новой строкой, а не UPDATE поверх одной: так за мастером
# остаётся история за день (например, "работаю" утром, "не работаю" после
# обеда), а не только последнее состояние. "Текущий" статус сотрудника —
# это просто самая свежая строка (см. get_latest_attendance_mark).
# lat/lon нужны как GeoNoteIn в app/routers/bot.py, но НЕ обязательны в
# отличие от неё — если телефон не отдал координаты (нет разрешения, нет
# GPS в помещении), отметка всё равно должна сохраниться, просто без них.
ATTENDANCE_MARKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS attendance_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sotrudnik_id INTEGER NOT NULL REFERENCES sotrudniki(id),
    status TEXT NOT NULL CHECK (status IN ('работаю', 'не работаю', 'больничный')),
    lat REAL,
    lon REAL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_attendance_marks_sotrudnik ON attendance_marks(sotrudnik_id, created_at);
"""

# Заметки рабочего начальнику — односторонняя лента (рабочий -> мастер),
# НЕ переписка: у рабочего в мобильном приложении нет экрана "входящие",
# он может только отправить текст, мастер в веб-версии только читает и
# отмечает прочитанным. is_read — единственное поле, которое меняет мастер
# (PATCH /api/notes/{id}), сам текст/автор/время не редактируются никем.
WORKER_NOTES_SCHEMA = """
CREATE TABLE IF NOT EXISTS worker_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sotrudnik_id INTEGER NOT NULL REFERENCES sotrudniki(id),
    text TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    recipient_sotrudnik_id INTEGER REFERENCES sotrudniki(id)
);
CREATE INDEX IF NOT EXISTS idx_worker_notes_sotrudnik ON worker_notes(sotrudnik_id, created_at);
"""

# Трелёвка (тракторист): откуда/куда/объём, одной строкой на рейс.
# delyanka_item_id — NULL, если трактор работает не по конкретной делянке;
# ссылается на delyanka_item (там kvartal/vydel/ploshad), как и work_plan.
TRELEVKA_SCHEMA = """
CREATE TABLE IF NOT EXISTS trelevka (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sotrudnik_id INTEGER NOT NULL REFERENCES sotrudniki(id),
    delyanka_item_id INTEGER REFERENCES delyanka_item(id),
    otkuda TEXT NOT NULL,
    kuda TEXT NOT NULL,
    obyom REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_trelevka_sotrudnik ON trelevka(sotrudnik_id, created_at);
"""

# Табель ручного ввода (по просьбе пользователя, 24.09.2026): пока
# мобильное приложение есть только у начальства, рядовые рабочие в
# attendance_marks вообще не попадают (это append-only лента, которую
# рабочий сам отмечает в телефоне) — лесничему нечем заполнить табель на
# них руками. В отличие от attendance_marks (много отметок в день, без
# места/вида работы) tabel_zapis — ОДНА запись на сотрудника за день
# (UNIQUE), с местом работы (делянка ИЛИ участок лесных культур — тот же
# принцип, что и в work_plan) и видом работы (см. vidy_rabot) — лесничий
# сам расставляет, кто где что делал, и может поправить уже введённый
# день, а не плодить дубли.
VIDY_RABOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS vidy_rabot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""

TABEL_ZAPIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tabel_zapis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sotrudnik_id INTEGER NOT NULL REFERENCES sotrudniki(id),
    data TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('работал', 'не работал', 'больничный', 'отпуск', 'выходной')),
    delyanka_item_id INTEGER REFERENCES delyanka_item(id),
    lesokultury_uchastok_id INTEGER REFERENCES lesokultury_uchastok(id),
    vid_raboty_id INTEGER REFERENCES vidy_rabot(id),
    kommentariy TEXT NOT NULL DEFAULT '',
    entered_by TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(sotrudnik_id, data)
);
CREATE INDEX IF NOT EXISTS idx_tabel_zapis_data ON tabel_zapis(data);
"""

# Затравка частых видов работ — лесничий дополняет список сам прямо из
# формы ("+ новый вид работы"), см. get_or_create_vid_raboty.
_VIDY_RABOT_SEED = ("Заготовка", "Рубки ухода", "Вывозка", "Уход за лесными культурами",
                     "Лесовосстановление", "Охрана леса")


# Уведомления (колокольчик в веб-шапке и в мобильном приложении).
# recipient_sotrudnik_id NULL — общее (всем руководителям: мастер/помощник/
# лесничий и офисным логинам), иначе — адресное этому сотруднику.
# related_id — id связанной записи (поломки/заметки/пробы/трелёвки), смысл
# определяет event_type. ФЛАГА is_read В ЭТОЙ ТАБЛИЦЕ НЕТ намеренно:
# "прочитано" у каждого человека своё (см. notification_reads) — иначе
# общее уведомление гасло бы у всех, когда его прочитал один.
NOTIFICATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_sotrudnik_id INTEGER REFERENCES sotrudniki(id),
    event_type TEXT NOT NULL,
    text TEXT NOT NULL,
    related_id INTEGER,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_sotrudnik_id, created_at);
"""

# Кто что прочитал: одна строка = "этот читатель прочитал это уведомление".
# Читатель — либо рабочий-руководитель (reader_type='sotrudnik',
# reader_id = sotrudniki.id), либо офисный логин (reader_type='user',
# reader_id = users.id): это разные таблицы с независимой нумерацией, поэтому
# id без типа был бы неоднозначен.
NOTIFICATION_READS_SCHEMA = """
CREATE TABLE IF NOT EXISTS notification_reads (
    notification_id INTEGER NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
    reader_type TEXT NOT NULL CHECK (reader_type IN ('user', 'sotrudnik')),
    reader_id INTEGER NOT NULL,
    read_at TEXT DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (notification_id, reader_type, reader_id)
);
"""


def ensure_webext_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DOCUMENTS_SCHEMA)
    conn.executescript(TASKS_SCHEMA)
    conn.executescript(USERS_SCHEMA)
    conn.executescript(SESSIONS_SCHEMA)
    conn.executescript(SOTRUDNIKI_SCHEMA)
    conn.executescript(WORKER_SESSIONS_SCHEMA)
    conn.executescript(WORK_PLAN_SCHEMA)
    conn.executescript(ATTENDANCE_MARKS_SCHEMA)
    conn.executescript(WORKER_NOTES_SCHEMA)
    conn.executescript(TRELEVKA_SCHEMA)
    conn.executescript(NOTIFICATIONS_SCHEMA)
    conn.executescript(NOTIFICATION_READS_SCHEMA)
    conn.executescript(VIDY_RABOT_SCHEMA)
    conn.executescript(TABEL_ZAPIS_SCHEMA)
    conn.executemany(
        "INSERT OR IGNORE INTO vidy_rabot (nazvanie) VALUES (?)",
        [(n,) for n in _VIDY_RABOT_SEED],
    )
    conn.commit()

    # recipient_sotrudnik_id в worker_notes — адресат заметки (NULL = общая,
    # видна всем руководителям), для баз, созданных до этого добавления.
    existing_wn_cols = {row[1] for row in conn.execute("PRAGMA table_info(worker_notes)").fetchall()}
    if "recipient_sotrudnik_id" not in existing_wn_cols:
        conn.execute(
            "ALTER TABLE worker_notes ADD COLUMN recipient_sotrudnik_id INTEGER "
            "REFERENCES sotrudniki(id)"
        )

    # documents создаётся выше в этой же функции (или уже существует из
    # более старой версии backend'а) — добавляем updated_at/updated_by тем
    # же безопасным способом ALTER TABLE ... IF NOT EXISTS, что и в
    # db.py:migrate_schema() для остальных ключевых таблиц.
    existing_doc_cols = {row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "updated_at" not in existing_doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN updated_at TEXT")

    # lesokultury_uchastok_id в work_plan — задачу теперь можно привязать
    # либо к делянке (delyanka_item_id, как раньше), либо к участку лесных
    # культур (взаимоисключающе — см. create_work_plan_item/
    # update_work_plan_item ниже), для баз, созданных до этого добавления.
    existing_wp_cols = {row[1] for row in conn.execute("PRAGMA table_info(work_plan)").fetchall()}
    if existing_wp_cols and "lesokultury_uchastok_id" not in existing_wp_cols:
        conn.execute(
            "ALTER TABLE work_plan ADD COLUMN lesokultury_uchastok_id INTEGER "
            "REFERENCES lesokultury_uchastok(id)"
        )
    if "updated_by" not in existing_doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN updated_by TEXT")
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_documents_updated_at
            AFTER UPDATE ON documents
            FOR EACH ROW
            BEGIN
                UPDATE documents SET updated_at = datetime('now', 'localtime')
                WHERE id = NEW.id;
            END"""
    )
    conn.commit()
    ensure_bootstrap_admin(conn)


# --------------------------------------------------------------------------- #
#   ДОКУМЕНТЫ (documents)
# --------------------------------------------------------------------------- #
def add_document(conn, doc_type, delyanka_id, file_name, file_path,
                  status="готов", error_text=None, created_by=None):
    cur = conn.execute(
        """INSERT INTO documents (doc_type, delyanka_id, file_name, file_path,
                                   status, error_text, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (doc_type, delyanka_id, file_name, file_path, status, error_text, created_by),
    )
    conn.commit()
    return cur.lastrowid


def update_document_status(conn, document_id, status, error_text=None):
    conn.execute(
        "UPDATE documents SET status=?, error_text=? WHERE id=?",
        (status, error_text, document_id),
    )
    conn.commit()


def get_document(conn, document_id):
    row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).description]
    return dict(zip(cols, row))


def list_documents(conn, delyanka_id=None, doc_type=None, status=None,
                    created_by=None, date_from=None, date_to=None):
    """date_from/date_to — строки 'YYYY-MM-DD' (включительно), сравниваются
    с датой created_at (без времени) — этого достаточно для фильтра
    "за период" на экране документов (Этап 5 плана переноса)."""
    sql = "SELECT * FROM documents WHERE 1=1"
    params = []
    if delyanka_id is not None:
        sql += " AND delyanka_id=?"
        params.append(delyanka_id)
    if doc_type:
        sql += " AND doc_type=?"
        params.append(doc_type)
    if status:
        sql += " AND status=?"
        params.append(status)
    if created_by:
        sql += " AND created_by=?"
        params.append(created_by)
    if date_from:
        sql += " AND date(created_at) >= date(?)"
        params.append(date_from)
    if date_to:
        sql += " AND date(created_at) <= date(?)"
        params.append(date_to)
    sql += " ORDER BY id DESC"
    rows = conn.execute(sql, params).fetchall()
    cols = [d[0] for d in conn.execute(sql, params).description]
    return [dict(zip(cols, r)) for r in rows]


def list_document_authors(conn):
    """Список различных created_by, уже встречавшихся в documents —
    для выпадающего фильтра "Автор" на экране документов, без отдельного
    похода в таблицу users (created_by хранит логин/ФИО как строку на
    момент генерации, это не всегда совпадает с текущим users.id)."""
    rows = conn.execute(
        "SELECT DISTINCT created_by FROM documents "
        "WHERE created_by IS NOT NULL AND created_by != '' ORDER BY created_by"
    ).fetchall()
    return [r[0] for r in rows]


def bulk_delete_documents(conn, document_ids):
    """Удаляет несколько документов разом. Возвращает список
    {"id", "ok", "file_path"|"error"} — по одному на каждый переданный id,
    чтобы роутер мог удалить файлы с диска и сообщить пользователю, какие
    именно записи не найдены (уже удалены кем-то другим и т.п.)."""
    results = []
    for document_id in document_ids:
        row = conn.execute(
            "SELECT file_path FROM documents WHERE id=?", (document_id,)
        ).fetchone()
        if not row:
            results.append({"id": document_id, "ok": False, "error": "не найден"})
            continue
        conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
        results.append({"id": document_id, "ok": True, "file_path": row[0]})
    conn.commit()
    return results


def delete_document(conn, document_id):
    """Удаляет запись метаданных документа и возвращает file_path (или None,
    если записи не было) — сам файл на диске удаляет вызывающий код
    (роутер), эта функция трогает только БД."""
    row = conn.execute("SELECT file_path FROM documents WHERE id=?", (document_id,)).fetchone()
    if not row:
        return None
    conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
    conn.commit()
    return row[0]


# --------------------------------------------------------------------------- #
#   Пункт 1.4 TODO_DOMIGRACII.md — «Архивировать» в панели документов.
#   Решение по продукту: архивация = статус документа становится 'архив'
#   (уже был готовый пресет под него в StatusBadge.jsx) + физический перенос
#   файла в DOCUMENTS_ARCHIVE_DIR. И то и другое — как и обычное удаление,
#   эти функции трогают только БД и отдают старый file_path, сам перенос/
#   создание директории делает роутер (там же лежат paths.py-константы).
#   Архивировать можно только уже готовый документ (status='готов') —
#   у документов "в процессе"/"с ошибкой" часто нет стабильного файла на
#   диске. Восстановление возвращает status='готов', то есть архив по
#   смыслу — не отдельный терминальный статус жизненного цикла, а временная
#   "полка" поверх уже готового документа.
# --------------------------------------------------------------------------- #
def archive_document(conn, document_id, new_file_path):
    """Переводит документ в статус 'архив' и переключает file_path на новое
    расположение. Возвращает {"old_path", "status"} или None, если документа
    нет; status — тот, что был ДО архивации (роутер решает, разрешать ли
    архивацию исходя из него)."""
    row = conn.execute(
        "SELECT file_path, status FROM documents WHERE id=?", (document_id,)
    ).fetchone()
    if not row:
        return None
    old_path, status = row
    conn.execute(
        "UPDATE documents SET status='архив', file_path=? WHERE id=?",
        (new_file_path, document_id),
    )
    conn.commit()
    return {"old_path": old_path, "status": status}


def unarchive_document(conn, document_id, new_file_path):
    """Обратная операция: статус 'архив' -> 'готов', file_path -> обратно в
    DOCUMENTS_DIR. Возвращает {"old_path", "status"} или None."""
    row = conn.execute(
        "SELECT file_path, status FROM documents WHERE id=?", (document_id,)
    ).fetchone()
    if not row:
        return None
    old_path, status = row
    conn.execute(
        "UPDATE documents SET status='готов', file_path=? WHERE id=?",
        (new_file_path, document_id),
    )
    conn.commit()
    return {"old_path": old_path, "status": status}


# --------------------------------------------------------------------------- #
#   ФОНОВЫЕ ЗАДАЧИ (background_tasks) — опрос через GET /api/tasks/{id}
# --------------------------------------------------------------------------- #
def create_task(conn, kind):
    task_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO background_tasks (id, kind, status) VALUES (?, ?, 'pending')",
        (task_id, kind),
    )
    conn.commit()
    return task_id


def set_task_running(conn, task_id, progress=None):
    conn.execute(
        "UPDATE background_tasks SET status='running', progress=?, "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (progress, task_id),
    )
    conn.commit()


def set_task_needs_input(conn, task_id, status, payload=None):
    """Переводит задачу в статус ожидания ответа пользователя вместо
    'running' — например, 'needs_vydel_choice' (см. app/routers/delyanki.py,
    Блок C.2 плана доработки: диалог выбора главного выдела при составной
    записи в МДО). payload кладётся в result_json ТЕМ ЖЕ способом, что и в
    set_task_done — фронт (pollTask) читает task.result, чтобы показать
    диалог/модалку. Статус НЕ 'done' и не 'error', поэтому опрос
    продолжается, пока кто-нибудь не ответит (см. соответствующий
    POST .../resolve-... эндпоинт, который переводит задачу обратно в
    'running' и отпускает фоновый поток)."""
    conn.execute(
        "UPDATE background_tasks SET status=?, result_json=?, "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (status, json.dumps(payload if payload is not None else {}, ensure_ascii=False), task_id),
    )
    conn.commit()


def set_task_done(conn, task_id, result=None):
    conn.execute(
        "UPDATE background_tasks SET status='done', result_json=?, "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (json.dumps(result if result is not None else {}, ensure_ascii=False), task_id),
    )
    conn.commit()


def set_task_error(conn, task_id, error_text):
    conn.execute(
        "UPDATE background_tasks SET status='error', error_text=?, "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (str(error_text), task_id),
    )
    conn.commit()


def get_task(conn, task_id):
    row = conn.execute(
        "SELECT id, kind, status, progress, result_json, error_text, created_at, updated_at "
        "FROM background_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    if not row:
        return None
    (tid, kind, status, progress, result_json, error_text, created_at, updated_at) = row
    try:
        result = json.loads(result_json) if result_json else None
    except (TypeError, ValueError):
        result = None
    return {
        "id": tid, "kind": kind, "status": status, "progress": progress,
        "result": result, "error_text": error_text,
        "created_at": created_at, "updated_at": updated_at,
    }


# --------------------------------------------------------------------------- #
#   ПАРОЛИ (PBKDF2 — без внешних зависимостей: passlib/bcrypt не входят в
#   requirements.txt backend'а, а stdlib hashlib этого достаточно для
#   "сервер в локальной сети конторы", см. README.md об уровне защиты)
# --------------------------------------------------------------------------- #
_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        iterations_s, salt_hex, digest_hex = stored_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_s))
    return hmac.compare_digest(actual, expected)


# --------------------------------------------------------------------------- #
#   ПОЛЬЗОВАТЕЛИ (users)
# --------------------------------------------------------------------------- #
def create_user(conn, login, password, fio="", role="viewer"):
    if role not in ROLES:
        raise ValueError(f"Недопустимая роль: {role!r}, ожидается одна из {ROLES}")
    cur = conn.execute(
        "INSERT INTO users (login, password_hash, fio, role) VALUES (?, ?, ?, ?)",
        (login, hash_password(password), fio, role),
    )
    conn.commit()
    return cur.lastrowid


def list_users(conn):
    rows = conn.execute(
        "SELECT id, login, fio, role, is_active, created_at FROM users ORDER BY id"
    ).fetchall()
    cols = ["id", "login", "fio", "role", "is_active", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def get_user_by_id(conn, user_id):
    row = conn.execute(
        "SELECT id, login, fio, role, is_active, created_at FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if not row:
        return None
    cols = ["id", "login", "fio", "role", "is_active", "created_at"]
    return dict(zip(cols, row))


def get_user_by_login(conn, login):
    """С password_hash — только для внутренней проверки пароля
    (authenticate_user); наружу (в API-ответы) не отдавать."""
    row = conn.execute("SELECT * FROM users WHERE login=?", (login,)).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM users WHERE login=?", (login,)).description]
    return dict(zip(cols, row))


def set_user_role(conn, user_id, role):
    if role not in ROLES:
        raise ValueError(f"Недопустимая роль: {role!r}, ожидается одна из {ROLES}")
    conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    conn.commit()


def set_user_password(conn, user_id, password: str) -> None:
    """Смена пароля существующего пользователя (Блок 1 плана доработки,
    п.6 — прежде всего для смены пароля начального admin/admin после
    первого запуска). Все существующие сессии пользователя отзываются,
    чтобы старый пароль/токен не продолжали действовать где-то ещё."""
    if not password:
        raise ValueError("Пароль не может быть пустым")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user_id))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.commit()


def set_user_active(conn, user_id, is_active: bool):
    conn.execute("UPDATE users SET is_active=? WHERE id=?", (1 if is_active else 0, user_id))
    conn.commit()
    if not is_active:
        # Деактивация должна немедленно обрывать уже открытые сессии — иначе
        # уволенный/заблокированный сотрудник остаётся залогинен до истечения
        # токена (до SESSION_LIFETIME_DAYS дней).
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.commit()


def ensure_bootstrap_admin(conn) -> None:
    """Если в базе ещё нет ни одного пользователя (первый запуск после
    появления таблицы users) — создаёт admin/admin, чтобы было чем
    залогиниться в первый раз, и громко предупреждает в консоли сменить
    пароль. Вызывается из ensure_webext_schema() при каждом старте
    приложения — безопасно, т.к. срабатывает только при count == 0."""
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        create_user(conn, login="admin", password="admin", fio="Администратор", role="admin")
        print("=" * 78)
        print("ВНИМАНИЕ: в базе не было пользователей — создан admin/admin.")
        print("Смените пароль (POST /api/auth/users или /docs) до открытия")
        print("доступа за пределами вашего компьютера.")
        print("=" * 78)


# --------------------------------------------------------------------------- #
#   СЕССИИ (sessions) — простые токены, а не JWT (см. комментарий у
#   SESSIONS_SCHEMA)
# --------------------------------------------------------------------------- #
def authenticate_user(conn, login, password):
    """Возвращает запись пользователя (без password_hash) при верном логине/
    пароле и активном аккаунте, иначе None — единой причины специально не
    даёт (не подсказывать, что именно неверно: логин или пароль)."""
    user = get_user_by_login(conn, login)
    if not user or not user["is_active"]:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


def create_session(conn, user_id, lifetime_days=SESSION_LIFETIME_DAYS):
    token = secrets.token_hex(32)
    expires_at = (datetime.now() + timedelta(days=lifetime_days)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at),
    )
    conn.commit()
    return token, expires_at


def get_user_by_token(conn, token):
    """Для Depends(get_current_user) в app/auth.py: валидная незакончившаяся
    сессия + активный пользователь, иначе None."""
    row = conn.execute(
        """SELECT users.id, users.login, users.fio, users.role, users.is_active,
                  sessions.expires_at
           FROM sessions JOIN users ON users.id = sessions.user_id
           WHERE sessions.token = ?""",
        (token,),
    ).fetchone()
    if not row:
        return None
    cols = ["id", "login", "fio", "role", "is_active", "expires_at"]
    user = dict(zip(cols, row))
    if not user["is_active"]:
        return None
    if user["expires_at"] < datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        return None
    return user


def delete_session(conn, token):
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()


def hash_pin(pin: str) -> str:
    """PIN — короткий цифровой код (не полноценный пароль, рабочие вводят
    его на телефоне в лесу без клавиатуры), но хранится тем же PBKDF2, что
    и обычные пароли — переиспользуем hash_password/verify_password
    построчно, отдельная пара функций не нужна."""
    return hash_password(pin)


def verify_pin(pin: str, stored_hash: str) -> bool:
    return verify_password(pin, stored_hash)


# --------------------------------------------------------------------------- #
#   РАБОЧИЕ (sotrudniki) — мобильное приложение, Фаза 6 плана доработки
# --------------------------------------------------------------------------- #
def create_sotrudnik(conn, login, pin, fio, dolzhnost="", uchastok=""):
    """Создаёт учётку рабочего (админ делает это через /docs или будущий
    экран Settings). Синхронно заводит/обновляет ту же запись в
    lesorub_directory под синтетическим viber_id вида "app:<id>" — это
    сохраняет ВЕСЬ существующий код app/routers/bot.py (list_tasks,
    create_report, create_geo_note и т.д.) рабочим без единой правки:
    для него рабочий из приложения ничем не отличается от рабочего,
    который где-то раньше написал боту в Telegram."""
    if conn.execute("SELECT 1 FROM sotrudniki WHERE login=?", (login,)).fetchone():
        raise ValueError(f"Логин {login!r} уже занят")
    cur = conn.execute(
        "INSERT INTO sotrudniki (login, pin_hash, fio, dolzhnost, uchastok) "
        "VALUES (?, ?, ?, ?, ?)",
        (login, hash_pin(pin), fio, dolzhnost, uchastok),
    )
    sotrudnik_id = cur.lastrowid
    app_identity = f"app:{sotrudnik_id}"
    conn.execute(
        "INSERT INTO lesorub_directory (viber_id, fio, dolzhnost, lesnichestvo) "
        "VALUES (?, ?, ?, ?)",
        (app_identity, fio, dolzhnost, uchastok),
    )
    conn.commit()
    return sotrudnik_id


def list_sotrudniki(conn):
    rows = conn.execute(
        "SELECT id, login, fio, dolzhnost, uchastok, is_active, created_at "
        "FROM sotrudniki ORDER BY id"
    ).fetchall()
    cols = ["id", "login", "fio", "dolzhnost", "uchastok", "is_active", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def set_sotrudnik_active(conn, sotrudnik_id, is_active: bool):
    conn.execute("UPDATE sotrudniki SET is_active=? WHERE id=?", (1 if is_active else 0, sotrudnik_id))
    conn.commit()
    if not is_active:
        conn.execute("DELETE FROM worker_sessions WHERE sotrudnik_id=?", (sotrudnik_id,))
        conn.commit()


def authenticate_sotrudnik(conn, login, pin):
    row = conn.execute(
        "SELECT id, login, pin_hash, fio, dolzhnost, uchastok, is_active "
        "FROM sotrudniki WHERE login=?", (login,),
    ).fetchone()
    if not row:
        return None
    cols = ["id", "login", "pin_hash", "fio", "dolzhnost", "uchastok", "is_active"]
    worker = dict(zip(cols, row))
    if not worker["is_active"]:
        return None
    if not verify_pin(pin, worker["pin_hash"]):
        return None
    del worker["pin_hash"]
    return worker


def create_worker_session(conn, sotrudnik_id, lifetime_days=SESSION_LIFETIME_DAYS):
    token = secrets.token_hex(32)
    expires_at = (datetime.now() + timedelta(days=lifetime_days)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO worker_sessions (sotrudnik_id, token, expires_at) VALUES (?, ?, ?)",
        (sotrudnik_id, token, expires_at),
    )
    conn.commit()
    return token, expires_at


def get_worker_by_token(conn, token):
    """Для app/auth.py — тот же принцип, что get_user_by_token() выше,
    только по worker_sessions/sotrudniki. Возвращённый dict дополнительно
    несёт app_identity — синтетический viber_id (см. create_sotrudnik),
    его роутеры app/routers/bot.py используют вместо telegram_id, который
    в мобильном приложении взять неоткуда."""
    row = conn.execute(
        """SELECT sotrudniki.id, sotrudniki.login, sotrudniki.fio, sotrudniki.dolzhnost,
                  sotrudniki.uchastok, sotrudniki.is_active, worker_sessions.expires_at
           FROM worker_sessions JOIN sotrudniki ON sotrudniki.id = worker_sessions.sotrudnik_id
           WHERE worker_sessions.token = ?""",
        (token,),
    ).fetchone()
    if not row:
        return None
    cols = ["id", "login", "fio", "dolzhnost", "uchastok", "is_active", "expires_at"]
    worker = dict(zip(cols, row))
    if not worker["is_active"]:
        return None
    if worker["expires_at"] < datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        return None
    worker["app_identity"] = f"app:{worker['id']}"
    return worker


def delete_worker_session(conn, token):
    conn.execute("DELETE FROM worker_sessions WHERE token=?", (token,))
    conn.commit()


# --------------------------------------------------------------------------- #
#   Задачи рабочего (work_plan) — минимальная версия Фазы 4 плана
#   доработки, только чтение/отметка для мобильного приложения. Постановка
#   задачи (INSERT) — временно вручную через /docs, полноценный экран
#   планирования в вебе — отдельным шагом, см. докстринг WORK_PLAN_SCHEMA.
# --------------------------------------------------------------------------- #
def create_work_plan_item(conn, sotrudnik_id, data, zadacha, delyanka_item_id=None,
                           lesokultury_uchastok_id=None):
    """Постановка задачи рабочему — временная замена экрана 'План работ'
    (см. комментарий у PERMISSIONS["work_plan.edit"]): вызывается либо
    вручную через /docs (POST /api/bot/work-plan), либо позже — из
    будущего календарного экрана в вебе, без изменений здесь.

    Задача привязывается МЕСТОМ работы либо к делянке (delyanka_item_id),
    либо к участку лесных культур (lesokultury_uchastok_id) — не к обоим
    сразу (переключатель "Делянка / Лесные культуры" на фронте); задача
    без привязки к месту (оба None) тоже допустима."""
    if not conn.execute("SELECT 1 FROM sotrudniki WHERE id=? AND is_active=1", (sotrudnik_id,)).fetchone():
        raise ValueError(f"Рабочий id={sotrudnik_id} не найден или отключён")
    if delyanka_item_id and lesokultury_uchastok_id:
        raise ValueError("Задачу нельзя привязать одновременно к делянке и к участку лесных культур")
    cur = conn.execute(
        "INSERT INTO work_plan (data, sotrudnik_id, delyanka_item_id, lesokultury_uchastok_id, zadacha) "
        "VALUES (?, ?, ?, ?, ?)",
        (data, sotrudnik_id, delyanka_item_id, lesokultury_uchastok_id, zadacha),
    )
    conn.commit()
    return cur.lastrowid


def get_work_plan_for_sotrudnik(conn, sotrudnik_id):
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT work_plan.id, work_plan.data, work_plan.zadacha, work_plan.status,
                  work_plan.created_at, delyanka_item.kvartal, delyanka_item.vydel,
                  delyanka_item.lesnichestvo
           FROM work_plan
           LEFT JOIN delyanka_item ON delyanka_item.id = work_plan.delyanka_item_id
           WHERE work_plan.sotrudnik_id = ? AND work_plan.status = 'активна'
           ORDER BY work_plan.data""",
        (sotrudnik_id,),
    ).fetchall()
    return rows


def complete_work_plan_item(conn, work_plan_id, sotrudnik_id):
    cur = conn.execute(
        "UPDATE work_plan SET status='выполнена' WHERE id=? AND sotrudnik_id=? AND status='активна'",
        (work_plan_id, sotrudnik_id),
    )
    conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
#   Отметка времени/присутствия (work_plan-раздел плана мобильного
#   приложения, п.3.6) — append-only лог, см. докстринг ATTENDANCE_MARKS_SCHEMA.
# --------------------------------------------------------------------------- #
def create_attendance_mark(conn, sotrudnik_id, status, lat=None, lon=None):
    if not conn.execute("SELECT 1 FROM sotrudniki WHERE id=? AND is_active=1", (sotrudnik_id,)).fetchone():
        raise ValueError(f"Рабочий id={sotrudnik_id} не найден или отключён")
    cur = conn.execute(
        "INSERT INTO attendance_marks (sotrudnik_id, status, lat, lon) VALUES (?, ?, ?, ?)",
        (sotrudnik_id, status, lat, lon),
    )
    conn.commit()
    return cur.lastrowid


def get_latest_attendance_mark(conn, sotrudnik_id):
    """Самая свежая отметка сотрудника — не обязательно за сегодня: если
    рабочий последний раз отмечался вчера и с тех пор молчит, мобильному
    приложению и будущему экрану "Мастер видит сводку" полезнее честно
    показать именно её (с датой), а не тихо притвориться, что отметок
    вообще не было."""
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT id, status, lat, lon, created_at FROM attendance_marks "
        "WHERE sotrudnik_id=? ORDER BY id DESC LIMIT 1",
        (sotrudnik_id,),
    ).fetchone()


def list_attendance_marks(conn, date_from=None, date_to=None, sotrudnik_id=None):
    """Веб-экран для мастера/лесничего ("кто сегодня работал") — с ФИО/
    должностью/участком сотрудника уже приджойненными, тот же принцип,
    что list_work_plan() выше. date_from/date_to — "ГГГГ-ММ-ДД",
    включительно, сравниваются с датой отметки (created_at хранит ещё и
    время, поэтому date(...), а не прямое сравнение строк, как у
    work_plan.data, где времени в поле нет)."""
    conn.row_factory = sqlite3.Row
    q = """
        SELECT attendance_marks.id, attendance_marks.status, attendance_marks.lat,
               attendance_marks.lon, attendance_marks.created_at, attendance_marks.sotrudnik_id,
               sotrudniki.fio AS sotrudnik_fio, sotrudniki.dolzhnost AS sotrudnik_dolzhnost,
               sotrudniki.uchastok AS sotrudnik_uchastok
        FROM attendance_marks
        JOIN sotrudniki ON sotrudniki.id = attendance_marks.sotrudnik_id
        WHERE 1=1
    """
    params = []
    if date_from:
        q += " AND date(attendance_marks.created_at) >= ?"
        params.append(date_from)
    if date_to:
        q += " AND date(attendance_marks.created_at) <= ?"
        params.append(date_to)
    if sotrudnik_id:
        q += " AND attendance_marks.sotrudnik_id = ?"
        params.append(sotrudnik_id)
    q += " ORDER BY attendance_marks.created_at DESC"
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
#   Заметки рабочего начальнику — односторонняя лента, см. докстринг
#   WORKER_NOTES_SCHEMA выше. Рабочий (мобильное приложение) только
#   создаёт, мастер/лесничий (веб) только читает и отмечает прочитанным —
#   ответа "в обратную сторону" (от мастера рабочему) не предусмотрено.
# --------------------------------------------------------------------------- #
def list_recipients(conn):
    """Кому рабочий может адресовать заметку: активные сотрудники с
    руководящей должностью (config.DOLZHNOSTI_MASTER_URODNYA). Сравнение
    без учёта регистра и в Python, а не в SQL: значения в константе
    строчные, в sotrudniki — с заглавной ("Мастер леса"), а lower() в
    SQLite не понимает кириллицу."""
    import config  # локально: webext не зависит от config на верхнем уровне
    rows = conn.execute(
        "SELECT id, fio, dolzhnost FROM sotrudniki WHERE is_active = 1 ORDER BY fio"
    ).fetchall()
    return [
        {"id": r[0], "fio": r[1], "dolzhnost": r[2]}
        for r in rows
        if (r[2] or "").strip().casefold() in config.DOLZHNOSTI_MASTER_URODNYA
    ]


def create_worker_note(conn, sotrudnik_id, text, recipient_sotrudnik_id=None):
    if not conn.execute("SELECT 1 FROM sotrudniki WHERE id=? AND is_active=1", (sotrudnik_id,)).fetchone():
        raise ValueError(f"Рабочий id={sotrudnik_id} не найден или отключён")
    text = (text or "").strip()
    if not text:
        raise ValueError("Текст заметки не может быть пустым")
    # Адресат должен быть из списка GET /api/bot/recipients — иначе заметка
    # окажется невидимой никому (раздел заметок открыт только руководителям).
    if recipient_sotrudnik_id is not None and recipient_sotrudnik_id not in {
        r["id"] for r in list_recipients(conn)
    }:
        raise ValueError("Получатель не найден среди мастеров/помощников/лесничих")
    cur = conn.execute(
        "INSERT INTO worker_notes (sotrudnik_id, text, recipient_sotrudnik_id) VALUES (?, ?, ?)",
        (sotrudnik_id, text, recipient_sotrudnik_id),
    )
    conn.commit()
    return cur.lastrowid


# Заметка видна читающему, если она общая (recipient NULL) или адресована
# именно ему. У офисных логинов (users) sotrudnik_id нет — им только общие.
_NOTE_VISIBLE_SQL = "(worker_notes.recipient_sotrudnik_id IS NULL OR worker_notes.recipient_sotrudnik_id = ?)"


def list_worker_notes(conn, viewer_sotrudnik_id=None):
    """Лента для мастера/лесничего — непрочитанные и самые новые наверху
    (is_read ASC сначала выносит 0/непрочитанные впереди 1/прочитанных,
    внутри каждой группы — свежие сначала). Чужие адресные заметки не
    отдаются: viewer_sotrudnik_id — id читающего (None у офисных логинов;
    сравнение с NULL в SQL даёт не-истину, так что им остаются общие)."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"""
        SELECT worker_notes.id, worker_notes.text, worker_notes.is_read,
               worker_notes.created_at, worker_notes.sotrudnik_id,
               worker_notes.recipient_sotrudnik_id,
               sotrudniki.fio AS sotrudnik_fio, sotrudniki.dolzhnost AS sotrudnik_dolzhnost
        FROM worker_notes
        JOIN sotrudniki ON sotrudniki.id = worker_notes.sotrudnik_id
        WHERE {_NOTE_VISIBLE_SQL}
        ORDER BY worker_notes.is_read ASC, worker_notes.created_at DESC
        """,
        (viewer_sotrudnik_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_worker_notes_mine(conn, sotrudnik_id):
    """Лента "Мои заметки" для самого рабочего (мобильное приложение,
    GET /api/bot/notes/mine) — все его собственные заметки, общие и
    адресные вперемешку, по дате (свежие сначала). В отличие от
    list_worker_notes() выше (лента читающего мастера/лесничего, с
    видимостью по recipient_sotrudnik_id и сортировкой по is_read), здесь
    автор и так уже знает, что сам отправлял, поэтому фильтр — просто по
    sotrudnik_id, без ограничения по видимости. recipient_fio — для
    адресных заметок (кому отправлено), NULL у общих."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT worker_notes.id, worker_notes.text, worker_notes.is_read,
               worker_notes.created_at, worker_notes.recipient_sotrudnik_id,
               recipient.fio AS recipient_fio
        FROM worker_notes
        LEFT JOIN sotrudniki AS recipient ON recipient.id = worker_notes.recipient_sotrudnik_id
        WHERE worker_notes.sotrudnik_id = ?
        ORDER BY worker_notes.created_at DESC
        """,
        (sotrudnik_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def create_trelevka(conn, sotrudnik_id, otkuda, kuda, obyom, delyanka_item_id=None):
    if not conn.execute("SELECT 1 FROM sotrudniki WHERE id=? AND is_active=1", (sotrudnik_id,)).fetchone():
        raise ValueError(f"Рабочий id={sotrudnik_id} не найден или отключён")
    if delyanka_item_id is not None and not conn.execute(
        "SELECT 1 FROM delyanka_item WHERE id=?", (delyanka_item_id,)
    ).fetchone():
        raise LookupError(f"Делянка id={delyanka_item_id} не найдена")
    otkuda, kuda = (otkuda or "").strip(), (kuda or "").strip()
    if not otkuda or not kuda:
        raise ValueError("Нужно указать, откуда и куда")
    if not obyom or obyom <= 0:
        raise ValueError("Объём должен быть больше нуля")
    cur = conn.execute(
        "INSERT INTO trelevka (sotrudnik_id, delyanka_item_id, otkuda, kuda, obyom) VALUES (?, ?, ?, ?, ?)",
        (sotrudnik_id, delyanka_item_id, otkuda, kuda, obyom),
    )
    conn.commit()
    return cur.lastrowid


def list_trelevka(conn, date_from=None, date_to=None, sotrudnik_id=None, delyanka_item_id=None):
    """Веб-список трелёвки для мастера — с ФИО сотрудника и кварталом/
    выделом делянки уже в ответе; фильтры как у list_attendance_marks
    (date_from/date_to — "ГГГГ-ММ-ДД", включительно)."""
    conn.row_factory = sqlite3.Row
    q = """
        SELECT trelevka.id, trelevka.sotrudnik_id, trelevka.delyanka_item_id,
               trelevka.otkuda, trelevka.kuda, trelevka.obyom, trelevka.created_at,
               sotrudniki.fio AS sotrudnik_fio, sotrudniki.dolzhnost AS sotrudnik_dolzhnost,
               delyanka_item.kvartal, delyanka_item.vydel, delyanka_item.lesoseka_nomer
        FROM trelevka
        JOIN sotrudniki ON sotrudniki.id = trelevka.sotrudnik_id
        LEFT JOIN delyanka_item ON delyanka_item.id = trelevka.delyanka_item_id
        WHERE 1=1
    """
    params = []
    if date_from:
        q += " AND date(trelevka.created_at) >= ?"
        params.append(date_from)
    if date_to:
        q += " AND date(trelevka.created_at) <= ?"
        params.append(date_to)
    if sotrudnik_id:
        q += " AND trelevka.sotrudnik_id = ?"
        params.append(sotrudnik_id)
    if delyanka_item_id:
        q += " AND trelevka.delyanka_item_id = ?"
        params.append(delyanka_item_id)
    q += " ORDER BY trelevka.created_at DESC, trelevka.id DESC"
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def set_worker_note_read(conn, note_id, is_read: bool, viewer_sotrudnik_id=None):
    """Отметка прочитанной — только для заметок, видимых читающему (чужую
    адресную заметку нельзя ни увидеть, ни отметить: для неё rowcount 0,
    как для несуществующей)."""
    cur = conn.execute(
        f"UPDATE worker_notes SET is_read=? WHERE id=? AND {_NOTE_VISIBLE_SQL.replace('worker_notes.', '')}",
        (1 if is_read else 0, note_id, viewer_sotrudnik_id),
    )
    conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
#   Уведомления — см. NOTIFICATIONS_SCHEMA / NOTIFICATION_READS_SCHEMA выше.
# --------------------------------------------------------------------------- #
def notify(conn, event_type, text, related_id=None, recipient_sotrudnik_id=None):
    """Создаёт уведомление. "Best effort": основное действие (поломка, проба,
    трелёвка, заметка) к этому моменту уже сохранено и закоммичено, поэтому
    сбой уведомления не должен превращать успешный запрос в 500 — он только
    печатается в лог. Возвращает id или None."""
    try:
        cur = conn.execute(
            "INSERT INTO notifications (recipient_sotrudnik_id, event_type, text, related_id) "
            "VALUES (?, ?, ?, ?)",
            (recipient_sotrudnik_id, event_type, (text or "")[:300], related_id),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Не удалось создать уведомление {event_type!r}: {exc}")
        return None


# Видно читающему, если общее или адресовано ему (у офисных логинов
# sotrudnik_id нет — сравнение с NULL не истинно, остаются только общие).
_NOTIF_VISIBLE = "(n.recipient_sotrudnik_id IS NULL OR n.recipient_sotrudnik_id = :sid)"


def list_notifications(conn, reader_type, reader_id, viewer_sotrudnik_id=None, unread_only=False, limit=50):
    conn.row_factory = sqlite3.Row
    q = f"""
        SELECT n.id, n.recipient_sotrudnik_id, n.event_type, n.text, n.related_id, n.created_at,
               (r.notification_id IS NOT NULL) AS is_read
        FROM notifications n
        LEFT JOIN notification_reads r
               ON r.notification_id = n.id AND r.reader_type = :rt AND r.reader_id = :rid
        WHERE {_NOTIF_VISIBLE}
    """
    if unread_only:
        q += " AND r.notification_id IS NULL"
    q += " ORDER BY n.created_at DESC, n.id DESC LIMIT :lim"
    rows = conn.execute(q, {"sid": viewer_sotrudnik_id, "rt": reader_type, "rid": reader_id, "lim": limit}).fetchall()
    return [{**dict(r), "is_read": bool(r["is_read"])} for r in rows]


def count_unread_notifications(conn, reader_type, reader_id, viewer_sotrudnik_id=None):
    return conn.execute(
        f"""
        SELECT COUNT(*) FROM notifications n
        LEFT JOIN notification_reads r
               ON r.notification_id = n.id AND r.reader_type = :rt AND r.reader_id = :rid
        WHERE {_NOTIF_VISIBLE} AND r.notification_id IS NULL
        """,
        {"sid": viewer_sotrudnik_id, "rt": reader_type, "rid": reader_id},
    ).fetchone()[0]


def set_notification_read(conn, notification_id, reader_type, reader_id, is_read, viewer_sotrudnik_id=None):
    """Отметка ТОЛЬКО для этого читателя. False — уведомления нет или оно
    не видно читающему (чужое адресное неотличимо от несуществующего)."""
    visible = conn.execute(
        f"SELECT 1 FROM notifications n WHERE n.id = :nid AND {_NOTIF_VISIBLE}",
        {"nid": notification_id, "sid": viewer_sotrudnik_id},
    ).fetchone()
    if not visible:
        return False
    if is_read:
        conn.execute(
            "INSERT OR IGNORE INTO notification_reads (notification_id, reader_type, reader_id) VALUES (?, ?, ?)",
            (notification_id, reader_type, reader_id),
        )
    else:
        conn.execute(
            "DELETE FROM notification_reads WHERE notification_id=? AND reader_type=? AND reader_id=?",
            (notification_id, reader_type, reader_id),
        )
    conn.commit()
    return True


def mark_all_notifications_read(conn, reader_type, reader_id, viewer_sotrudnik_id=None):
    cur = conn.execute(
        f"""
        INSERT OR IGNORE INTO notification_reads (notification_id, reader_type, reader_id)
        SELECT n.id, :rt, :rid FROM notifications n WHERE {_NOTIF_VISIBLE}
        """,
        {"sid": viewer_sotrudnik_id, "rt": reader_type, "rid": reader_id},
    )
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------- #
#   Фаза 4 плана доработки — веб-экран "План работ" (постановка задач
#   admin/лесоводом). В отличие от create_work_plan_item/
#   get_work_plan_for_sotrudnik/complete_work_plan_item выше (написаны для
#   мобильного приложения — рабочий видит только СВОИ активные задачи),
#   этим функциям нужен взгляд администратора: все задачи сразу, с ФИО
#   сотрудника и кварталом/выделом делянки уже в ответе (не заставлять
#   фронтенд джойнить самому), и полноценный CRUD, а не только
#   создание+отметка выполнено.
# --------------------------------------------------------------------------- #
def list_work_plan(conn, date_from=None, date_to=None, sotrudnik_id=None):
    """Список задач для веб-экрана "План работ" — с ФИО/должностью
    сотрудника и кварталом/выделом делянки уже приджойненными.
    date_from/date_to — включительно, фильтр по work_plan.data (строка
    "ГГГГ-ММ-ДД", сравнение строк работает корректно для этого формата)."""
    conn.row_factory = sqlite3.Row
    q = """
        SELECT work_plan.id, work_plan.data, work_plan.zadacha, work_plan.status,
               work_plan.created_at, work_plan.sotrudnik_id, work_plan.delyanka_item_id,
               work_plan.lesokultury_uchastok_id,
               sotrudniki.fio AS sotrudnik_fio, sotrudniki.dolzhnost AS sotrudnik_dolzhnost,
               delyanka_item.kvartal, delyanka_item.vydel, delyanka_item.lesnichestvo,
               lku.kvartal AS lku_kvartal, lku.vydel AS lku_vydel,
               lku.lesnichestvo AS lku_lesnichestvo, lku.glavnaya_poroda AS lku_glavnaya_poroda
        FROM work_plan
        JOIN sotrudniki ON sotrudniki.id = work_plan.sotrudnik_id
        LEFT JOIN delyanka_item ON delyanka_item.id = work_plan.delyanka_item_id
        LEFT JOIN lesokultury_uchastok lku ON lku.id = work_plan.lesokultury_uchastok_id
        WHERE 1=1
    """
    params = []
    if date_from:
        q += " AND work_plan.data >= ?"
        params.append(date_from)
    if date_to:
        q += " AND work_plan.data <= ?"
        params.append(date_to)
    if sotrudnik_id:
        q += " AND work_plan.sotrudnik_id = ?"
        params.append(sotrudnik_id)
    q += " ORDER BY work_plan.data, sotrudniki.fio"
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def get_work_plan_item(conn, work_plan_id):
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT work_plan.id, work_plan.data, work_plan.zadacha, work_plan.status,
               work_plan.created_at, work_plan.sotrudnik_id, work_plan.delyanka_item_id,
               work_plan.lesokultury_uchastok_id,
               sotrudniki.fio AS sotrudnik_fio, sotrudniki.dolzhnost AS sotrudnik_dolzhnost,
               delyanka_item.kvartal, delyanka_item.vydel, delyanka_item.lesnichestvo,
               lku.kvartal AS lku_kvartal, lku.vydel AS lku_vydel,
               lku.lesnichestvo AS lku_lesnichestvo, lku.glavnaya_poroda AS lku_glavnaya_poroda
        FROM work_plan
        JOIN sotrudniki ON sotrudniki.id = work_plan.sotrudnik_id
        LEFT JOIN delyanka_item ON delyanka_item.id = work_plan.delyanka_item_id
        LEFT JOIN lesokultury_uchastok lku ON lku.id = work_plan.lesokultury_uchastok_id
        WHERE work_plan.id = ?
        """,
        (work_plan_id,),
    ).fetchone()
    return dict(row) if row else None


def update_work_plan_item(conn, work_plan_id, data=None, zadacha=None, delyanka_item_id=-1,
                           lesokultury_uchastok_id=-1, sotrudnik_id=None, status=None):
    """Частичное обновление — None (кроме delyanka_item_id/
    lesokultury_uchastok_id) значит "не менять это поле".
    delyanka_item_id и lesokultury_uchastok_id — особый случай: -1 (не
    путать с None!) значит "не менять", None — это допустимое ЦЕЛЕВОЕ
    значение (отвязать задачу от делянки/участка), поэтому его нельзя
    использовать как маркер "поле не передано".

    Задача привязывается местом работы только к ОДНОМУ источнику —
    если явно задаётся delyanka_item_id (не -1 и не None), существующая
    привязка к участку лесных культур снимается, и наоборот."""
    if sotrudnik_id is not None and not conn.execute(
        "SELECT 1 FROM sotrudniki WHERE id=? AND is_active=1", (sotrudnik_id,)
    ).fetchone():
        raise ValueError(f"Рабочий id={sotrudnik_id} не найден или отключён")
    if delyanka_item_id not in (-1, None) and lesokultury_uchastok_id not in (-1, None):
        raise ValueError("Задачу нельзя привязать одновременно к делянке и к участку лесных культур")

    fields, params = [], []
    if data is not None:
        fields.append("data=?"); params.append(data)
    if zadacha is not None:
        fields.append("zadacha=?"); params.append(zadacha)
    if delyanka_item_id != -1:
        fields.append("delyanka_item_id=?"); params.append(delyanka_item_id)
        if delyanka_item_id is not None:
            fields.append("lesokultury_uchastok_id=?"); params.append(None)
    if lesokultury_uchastok_id != -1:
        fields.append("lesokultury_uchastok_id=?"); params.append(lesokultury_uchastok_id)
        if lesokultury_uchastok_id is not None:
            fields.append("delyanka_item_id=?"); params.append(None)
    if sotrudnik_id is not None:
        fields.append("sotrudnik_id=?"); params.append(sotrudnik_id)
    if status is not None:
        fields.append("status=?"); params.append(status)
    if not fields:
        return
    params.append(work_plan_id)
    conn.execute(f"UPDATE work_plan SET {', '.join(fields)} WHERE id=?", params)
    conn.commit()


def delete_work_plan_item(conn, work_plan_id):
    conn.execute("DELETE FROM work_plan WHERE id=?", (work_plan_id,))
    conn.commit()


# --------------------------------------------------------------------------- #
#   Табель ручного ввода (tabel_zapis/vidy_rabot) — см. докстринг
#   TABEL_ZAPIS_SCHEMA. Экран "Табель — ручной ввод" в веб-панели.
# --------------------------------------------------------------------------- #
def list_vidy_rabot(conn):
    rows = conn.execute("SELECT id, nazvanie FROM vidy_rabot ORDER BY nazvanie").fetchall()
    return [{"id": r[0], "nazvanie": r[1]} for r in rows]


def get_or_create_vid_raboty(conn, nazvanie):
    """Возвращает id вида работы, заводя новую строку в справочнике, если
    такого названия ещё нет — форма табеля даёт лесничему "+ новый вид
    работы" прямо на месте, без отдельного экрана-справочника."""
    nazvanie = (nazvanie or "").strip()
    if not nazvanie:
        raise ValueError("Название вида работы не может быть пустым")
    row = conn.execute("SELECT id FROM vidy_rabot WHERE nazvanie=?", (nazvanie,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute("INSERT INTO vidy_rabot (nazvanie) VALUES (?)", (nazvanie,))
    conn.commit()
    return cur.lastrowid


def _tabel_mobile_status_by_sotrudnik(conn, data):
    """Итоговый статус мобильной отметки (attendance_marks) на дату — тот
    же приоритет, что и Attendance.jsx dayKind (больничный > работаю > не
    работаю) — только чтобы форма табеля показала "уже отметился в
    приложении" рядом с сотрудником, лесничему решать самому."""
    rows = conn.execute(
        "SELECT sotrudnik_id, status FROM attendance_marks WHERE substr(created_at, 1, 10) = ?",
        (data,),
    ).fetchall()
    by_sotrudnik = {}
    for sotrudnik_id, status in rows:
        by_sotrudnik.setdefault(sotrudnik_id, set()).add(status)
    result = {}
    for sotrudnik_id, statuses in by_sotrudnik.items():
        if "больничный" in statuses:
            result[sotrudnik_id] = "больничный"
        elif "работаю" in statuses:
            result[sotrudnik_id] = "работаю"
        else:
            result[sotrudnik_id] = "не работаю"
    return result


def get_tabel_day(conn, data):
    """Табель ручного ввода на ОДИН день — строка на КАЖДОГО активного
    сотрудника (не только тех, у кого уже есть запись за этот день, в
    отличие от attendance_marks-based Attendance.jsx, где виден только тот,
    кто сам отметился), с уже приджойненной записью (если лесничий её уже
    вносил) и итогом мобильной отметки за этот день для подсказки
    "уже отметился"."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT sotrudniki.id AS sotrudnik_id, sotrudniki.fio, sotrudniki.dolzhnost,
               tz.id AS zapis_id, tz.status, tz.kommentariy, tz.entered_by, tz.updated_at,
               tz.delyanka_item_id, delyanka_item.kvartal AS d_kvartal, delyanka_item.vydel AS d_vydel,
               tz.lesokultury_uchastok_id, lku.kvartal AS lku_kvartal, lku.vydel AS lku_vydel,
               lku.glavnaya_poroda AS lku_glavnaya_poroda,
               tz.vid_raboty_id, vidy_rabot.nazvanie AS vid_raboty_nazvanie
        FROM sotrudniki
        LEFT JOIN tabel_zapis tz ON tz.sotrudnik_id = sotrudniki.id AND tz.data = ?
        LEFT JOIN delyanka_item ON delyanka_item.id = tz.delyanka_item_id
        LEFT JOIN lesokultury_uchastok lku ON lku.id = tz.lesokultury_uchastok_id
        LEFT JOIN vidy_rabot ON vidy_rabot.id = tz.vid_raboty_id
        WHERE sotrudniki.is_active = 1
        ORDER BY sotrudniki.fio
        """,
        (data,),
    ).fetchall()
    result = [dict(r) for r in rows]
    mobile_status = _tabel_mobile_status_by_sotrudnik(conn, data)
    for r in result:
        r["mobile_status"] = mobile_status.get(r["sotrudnik_id"])
    return result


def save_tabel_day(conn, data, entries, entered_by):
    """Пакетное сохранение табеля на один день. entries — список dict:
    sotrudnik_id, status, delyanka_item_id, lesokultury_uchastok_id,
    vid_raboty_id, kommentariy. UPSERT по UNIQUE(sotrudnik_id, data) — одна
    запись на сотрудника за день, повторное сохранение того же дня
    исправляет её, а не плодит дубли (лесничий может открыть уже
    заполненный день и что-то поправить)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for e in entries:
        if e.get("delyanka_item_id") and e.get("lesokultury_uchastok_id"):
            raise ValueError(
                "Запись табеля нельзя привязать одновременно к делянке и к участку лесных культур"
            )
        if not conn.execute(
            "SELECT 1 FROM sotrudniki WHERE id=? AND is_active=1", (e["sotrudnik_id"],)
        ).fetchone():
            raise ValueError(f"Сотрудник id={e['sotrudnik_id']} не найден или отключён")
        conn.execute(
            """
            INSERT INTO tabel_zapis
                (sotrudnik_id, data, status, delyanka_item_id, lesokultury_uchastok_id,
                 vid_raboty_id, kommentariy, entered_by, created_at, updated_at)
            VALUES (:sotrudnik_id, :data, :status, :delyanka_item_id, :lesokultury_uchastok_id,
                    :vid_raboty_id, :kommentariy, :entered_by, :now, :now)
            ON CONFLICT(sotrudnik_id, data) DO UPDATE SET
                status=excluded.status,
                delyanka_item_id=excluded.delyanka_item_id,
                lesokultury_uchastok_id=excluded.lesokultury_uchastok_id,
                vid_raboty_id=excluded.vid_raboty_id,
                kommentariy=excluded.kommentariy,
                entered_by=excluded.entered_by,
                updated_at=excluded.updated_at
            """,
            {
                "sotrudnik_id": e["sotrudnik_id"], "data": data, "status": e["status"],
                "delyanka_item_id": e.get("delyanka_item_id"),
                "lesokultury_uchastok_id": e.get("lesokultury_uchastok_id"),
                "vid_raboty_id": e.get("vid_raboty_id"),
                "kommentariy": e.get("kommentariy") or "",
                "entered_by": entered_by, "now": now,
            },
        )
    conn.commit()


def list_tabel_zapisi(conn, date_from=None, date_to=None):
    """Записи табеля ручного ввода за период — для слияния в месячную
    сетку "Присутствие" (см. app/routers/attendance.py: GET .../tabel)."""
    conn.row_factory = sqlite3.Row
    q = """
        SELECT tz.id, tz.sotrudnik_id, tz.data, tz.status, tz.kommentariy, tz.entered_by,
               sotrudniki.fio AS sotrudnik_fio, sotrudniki.dolzhnost AS sotrudnik_dolzhnost,
               tz.delyanka_item_id, delyanka_item.kvartal AS d_kvartal, delyanka_item.vydel AS d_vydel,
               tz.lesokultury_uchastok_id, lku.kvartal AS lku_kvartal, lku.vydel AS lku_vydel,
               lku.glavnaya_poroda AS lku_glavnaya_poroda,
               tz.vid_raboty_id, vidy_rabot.nazvanie AS vid_raboty_nazvanie
        FROM tabel_zapis tz
        JOIN sotrudniki ON sotrudniki.id = tz.sotrudnik_id
        LEFT JOIN delyanka_item ON delyanka_item.id = tz.delyanka_item_id
        LEFT JOIN lesokultury_uchastok lku ON lku.id = tz.lesokultury_uchastok_id
        LEFT JOIN vidy_rabot ON vidy_rabot.id = tz.vid_raboty_id
        WHERE 1=1
    """
    params = []
    if date_from:
        q += " AND tz.data >= ?"
        params.append(date_from)
    if date_to:
        q += " AND tz.data <= ?"
        params.append(date_to)
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def purge_expired_sessions(conn):
    """Необязательная уборка — можно дёргать периодически (например, из
    background-задачи по расписанию), просроченные сессии и так не проходят
    get_user_by_token()."""
    conn.execute("DELETE FROM sessions WHERE expires_at < datetime('now', 'localtime')")
    conn.commit()


# --------------------------------------------------------------------------- #
#   ПРАВА (has_permission) — используется в роутерах FastAPI (Этап 1) через
#   Depends(require_permission(...)) из app/auth.py. Список действий будет
#   расти по мере того, как экраны (Этап 4) переводятся на реальную
#   авторизацию — добавляйте новые ключи сюда, а не разбрасывайте проверки
#   ролей по роутерам напрямую.
# --------------------------------------------------------------------------- #
PERMISSIONS = {
    "delyanka.view": ("admin", "lesovod", "viewer"),
    "delyanka.edit": ("admin", "lesovod"),
    "delyanka.delete": ("admin", "lesovod"),
    # Постановка задачи рабочему (work_plan) — тот же круг ролей, что и
    # редактирование делянки (лесничий/админ), временная замена
    # полноценного экрана "План работ" (Фаза 4 плана доработки), см.
    # webext.WORK_PLAN_SCHEMA.
    "work_plan.edit": ("admin", "lesovod"),
    # Табель ручного ввода (просьба пользователя, 24.09.2026) — тот же круг
    # ролей, что и у "Плана работ" (лесничий/админ): расставляет, кто где
    # что делал, задним числом, пока рядовые рабочие не завели мобильное
    # приложение и не попадают в attendance_marks сами.
    "tabel.edit": ("admin", "lesovod"),
    "documents.view": ("admin", "lesovod", "viewer"),
    "documents.generate": ("admin", "lesovod"),
    "documents.delete": ("admin", "lesovod"),
    # Пункт 1.4 TODO_DOMIGRACII.md — те же роли, что и на удаление: архивация
    # тоже необратимо трогает файл на диске (переносит его), а не просто
    # публичный просмотр.
    "documents.archive": ("admin", "lesovod"),
    "taxation.edit": ("admin", "lesovod"),
    "lesokultury.edit": ("admin", "lesovod"),
    "raskhod.edit": ("admin", "lesovod"),
    "inspection.edit": ("admin", "lesovod"),
    # C.3 плана — экран "Рубки ухода" (независимые пробы). Те же роли, что
    # и у остальных прикладных экранов (raskhod/taxation/inspection): вести
    # и считать пробы может admin/lesovod, viewer — только смотреть (GET-
    # эндпоинты в app/routers/uhody.py открыты без require_permission, как
    # и list_inspection/get_balance у остальных роутеров этого же уровня).
    "uhody.edit": ("admin", "lesovod"),
    # Рабочий из мобильного приложения может СОЗДАВАТЬ пробу (POST
    # /uhody/proby — тот же расчёт, что и у офиса), но не править/удалять/
    # отмечать выполненной (PATCH/DELETE/complete остаются на uhody.edit).
    # Отдельное узкое право, а не переиспользование uhody.edit — по
    # образцу map.import ниже.
    "uhody.submit": ("admin", "lesovod", "worker"),
    # Трелёвка (POST /api/bot/trelevka) — на всю роль worker, без
    # сужения по должности: должность на сервере не проверяется (как и
    # кнопка "Поломка" у бота — ограничена только на клиенте).
    "trelevka.submit": ("worker",),
    "map.view": ("admin", "lesovod", "viewer"),    "settings.edit": ("admin",),
    "users.manage": ("admin",),
    # Этап 4, Блок 3/часть 2 — единая точка входа для всех будущих
    # bot.py-эндпоинтов (Блок 3/часть 3b: регистрация рабочих, приём
    # отчётов, задачи, служебные записки, гео-заметки). Роль "bot" не
    # хранится в таблице users (не проходит через create_user()/ROLES —
    # см. app/auth.py:get_current_user_optional) — это синтетический
    # пользователь, которого backend распознаёт по отдельному статическому
    # токену (config.get_bot_service_token()), а не по сессии. admin тоже
    # допущен — чтобы эндпоинты бота можно было дёрнуть руками из /docs
    # при отладке, не поднимая сам бот.
    # "worker" добавлена здесь (Фаза 6 плана доработки, пункт 4 — "рабочие
    # аккаунты не должны получать 403 на /api/bot/*"): рабочий из
    # мобильного приложения пользуется ТЕМ ЖЕ роутером app/routers/bot.py,
    # что и Telegram-бот (тот же смысл действий — отчёты/задачи/гео-заметки
    # "полевого агента"), просто входит своим личным токеном
    # (worker_sessions) вместо общего сервисного токена бота. app/auth.py
    # различает "bot" (весь процесс бота, один токен на всех) и "worker"
    # (staff person, свой токен на каждого) — оба допущены сюда, но с
    # разным способом определить, "чьи" данные читать (см. app_identity
    # в get_worker_by_token() выше и комментарии в bot.py).
    "bot.access": ("admin", "bot", "worker"),
    # QGIS-мост (16.09.2026) — POST /api/map/import-layer и
    # DELETE /api/map/import-layers/{batch_id} раньше не проверяли права
    # вообще (см. подробности в legacy/config.py:get_map_import_service_
    # token). "map_import" — синтетическая роль по образцу "bot" выше,
    # только со своим отдельным токеном (не переиспользует токен бота).
    "map.import": ("admin", "map_import"),
}


def has_permission(user, action: str) -> bool:
    """user — dict с ключом 'role' (как возвращают get_user_by_token()/
    authenticate_user()) либо None (неаутентифицированный запрос — всегда
    False). action — ключ из PERMISSIONS; неизвестное действие — это ошибка
    в вызывающем коде, а не "запретить по умолчанию", поэтому кидаем
    исключение, а не тихо возвращаем False."""
    if action not in PERMISSIONS:
        raise ValueError(f"Неизвестное действие для проверки прав: {action!r}")
    if not user:
        return False
    return user.get("role") in PERMISSIONS[action]


# --------------------------------------------------------------------------- #
#   updated_by для таблиц из db.py:migrate_schema() (delyanka, delyanka_item,
#   lesokultury_uchastok, raskhod_naryad) и documents (эта таблица, выше).
#   updated_at эти таблицы проставляют себе сами через AFTER UPDATE-триггер —
#   updated_by триггером не поставить (в SQL нет "текущего пользователя HTTP-
#   запроса"), поэтому роутер вызывает это явно после обновления записи,
#   когда пользователь известен (Depends(get_current_user)).
# --------------------------------------------------------------------------- #
_TOUCHABLE_TABLES = ("delyanka", "delyanka_item", "lesokultury_uchastok", "raskhod_naryad", "documents")


def touch_updated_by(conn, table: str, record_id: int, user_login: str) -> None:
    if table not in _TOUCHABLE_TABLES:
        raise ValueError(f"Таблица {table!r} не поддерживает updated_by (нет такой колонки)")
    conn.execute(f"UPDATE {table} SET updated_by=? WHERE id=?", (user_login, record_id))
    conn.commit()
