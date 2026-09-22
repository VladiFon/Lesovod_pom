# -*- coding: utf-8 -*-
"""
Подключение к SQLite: та же база, с которой работают db.py/delyanka.py/
raskhod.py и т.д. (обычный sqlite3.connect, без ORM — как в исходном
проекте). Путь к базе берётся из legacy/config.py (DB_PATH, переопределяется
переменной окружения LESOVOD_DB_PATH).

Каждый HTTP-запрос получает своё соединение через Depends(get_conn) —
sqlite3-соединение не потокобезопасно для совместного использования между
запросами, поэтому не переиспользуется глобально. Фоновые задачи
(BackgroundTasks) открывают своё отдельное соединение тем же способом
(см. app/routers/*.py).
"""
import sqlite3

from app import legacy_bridge  # noqa: F401 — обязателен до import config/db
import config as legacy_config
import db as legacy_db
import webext

DB_PATH = legacy_config.DB_PATH


def get_connection() -> sqlite3.Connection:
    """Открывает новое соединение с прикладными PRAGMA — используется и в
    Depends(), и напрямую в фоновых задачах.

    Этап 2 плана переноса в веб (многопользовательский режим):
    - journal_mode=WAL — читатели и писатель больше не блокируют друг друга
      (в отличие от режима по умолчанию DELETE/rollback-journal), что и
      снимает большую часть конфликтов, когда несколько человек одновременно
      открыли браузер. Устанавливается один раз на файл базы (не нужно
      выставлять на каждом соединении заново — PRAGMA journal_mode
      сохраняется в самом файле БД), но безопасно выполнять на каждом
      подключении: если WAL уже включён, команда — no-op.
    - busy_timeout — вместо мгновенного "database is locked" при редкой
      одновременной записи двух пользователей соединение будет ждать до
      5 секунд, пока освободится блокировка, прежде чем вернуть ошибку.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    """Вызывается один раз при старте приложения (main.py, startup-событие):
    применяет схему db.py (все 30 таблиц десктоп-приложения) и добавляет
    расширение backend'а (documents/background_tasks, см. webext.py)."""
    conn = get_connection()
    try:
        legacy_db.migrate_schema(conn)
        webext.ensure_webext_schema(conn)
    finally:
        conn.close()


def get_conn():
    """FastAPI-зависимость: Depends(get_conn)."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
