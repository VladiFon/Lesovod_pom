# -*- coding: utf-8 -*-
"""
FastAPI-зависимости для авторизации — тонкая обвязка над функциями
users/sessions/has_permission() из legacy/webext.py (Этап 2 плана переноса
в веб). Роутеры подключают их так:

    from app.auth import get_current_user, require_permission

    @router.delete("/{document_id}")
    def delete_document(document_id: int, conn=Depends(get_conn),
                         user=Depends(require_permission("documents.delete"))):
        ...

Токен передаётся заголовком `Authorization: Bearer <token>` (обычный
Bearer-токен, не JWT — сам токен непрозрачный, проверяется по таблице
sessions на каждый запрос).

Важно: на этом этапе (2) существующие роутеры из Этапа 1 НЕ переведены на
обязательную авторизацию — этим планово занимается Этап 4 (переписывание
экранов), когда во фронтенде появится экран логина и токен будет из чего
брать. Здесь — готовый и протестированный через /docs механизм: эндпоинты
/api/auth/* (app/routers/auth.py) уже требуют реальный логин/пароль и
реальные права.

Сервисный токен Telegram-бота (LESOVOD_BOT_SERVICE_TOKEN) удалён вместе
с ботом 28.09.2026; остался только статический токен QGIS-моста ниже.
"""
import os
import hmac
from typing import Optional

from fastapi import Depends, HTTPException, Header

from app import legacy_bridge  # noqa: F401 — обязателен до import webext
import config
import webext

from app.database import get_conn


def _map_import_user_from_token(token: str) -> Optional[dict]:
    """Служебный пользователь для QGIS-моста
    ("Лесовод-мост") — отдельный статический токен
    (config.get_map_import_service_token()), отдельная синтетическая роль
    "map_import" (см. webext.PERMISSIONS["map.import"]). Заведена
    16.09.2026 вместе с самой авторизацией POST /api/map/import-layer и
    DELETE /api/map/import-layers/{batch_id} — до этого эти два эндпоинта
    вообще не проверяли токен (см. докстринг get_map_import_service_token
    в legacy/config.py — почему это стало проблемой именно в этот день)."""
    service_token = config.get_map_import_service_token()
    if not service_token or not token:
        return None
    if not hmac.compare_digest(token, service_token):
        return None
    return {
        "id": None,
        "login": "qgis_bridge",
        "fio": "QGIS-мост (служебная учётная запись)",
        "role": "map_import",
        "is_active": 1,
    }


def get_current_user_optional(
    authorization: Optional[str] = Header(default=None),
    conn=Depends(get_conn),
):
    """Возвращает dict пользователя, если передан валидный Bearer-токен,
    иначе None (не кидает 401) — для эндпоинтов, где авторизация опциональна
    (например, чтобы response включал "кто сейчас смотрит", не требуя
    логина). Сначала пробует токен QGIS-моста (сравнение со строкой из
    переменной окружения, без похода в БД); если не совпал — обычная проверка
    через таблицу sessions, как и раньше."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer "):].strip()
    if not token:
        return None
    map_import_user = _map_import_user_from_token(token)
    if map_import_user is not None:
        return map_import_user
    office_user = webext.get_user_by_token(conn, token)
    if office_user is not None:
        return office_user
    # Мобильное приложение (Фаза 6 плана доработки): токен рабочего из
    # worker_sessions/sotrudniki — отдельная учётная система от
    # users/sessions (office_user выше), поэтому проверяется отдельным
    # запросом, только если первые два варианта не подошли. role="worker"
    # даёт доступ ровно к тому, что перечислено в
    # webext.PERMISSIONS["bot.access"] — то есть только к
    # app/routers/bot.py, как и предполагает Фаза 6.
    worker = webext.get_worker_by_token(conn, token)
    if worker is not None:
        return {
            "id": None,
            "login": worker["login"],
            "fio": worker["fio"],
            "role": "worker",
            "is_active": worker["is_active"],
            "app_identity": worker["app_identity"],
            "sotrudnik_id": worker["id"],
        }
    return None


def get_current_user(user=Depends(get_current_user_optional)):
    """Требует валидный токен — 401, если его нет или он просрочен/отозван."""
    if user is None:
        raise HTTPException(401, "Требуется авторизация (Authorization: Bearer <token>)")
    return user


def require_permission(action: str):
    """Фабрика зависимостей: Depends(require_permission("documents.delete")).
    401, если не залогинен; 403, если залогинен, но роль не даёт прав на
    action (список действий — webext.PERMISSIONS)."""

    def _dependency(user=Depends(get_current_user)):
        if not webext.has_permission(user, action):
            raise HTTPException(403, f"Недостаточно прав для действия «{action}»")
        return user

    return _dependency


OFFICE_ROLES = ("admin", "lesovod", "viewer")
# Офисные роли, которым можно ЗАПИСЫВАТЬ (viewer — только смотреть, как и
# у остальных прав в webext.PERMISSIONS).
OFFICE_WRITE_ROLES = ("admin", "lesovod")


def _office_or_master(office_roles):
    """Фабрика зависимости: офисные роли из office_roles ИЛИ рабочий
    (role="worker") с руководящей должностью из
    config.DOLZHNOSTI_MASTER_URODNYA (мастер леса, помощник лесничего,
    лесничий — они же работают в мобильном приложении). Остальным —
    рабочим других должностей, боту, QGIS-мосту — 403.
    Должность берём из sotrudniki по user["sotrudnik_id"] на каждый
    запрос, а не из токена: смена должности вступает в силу сразу."""

    def _dependency(user=Depends(get_current_user), conn=Depends(get_conn)):
        role = user.get("role")
        if role in office_roles:
            return user
        if role == "worker":
            row = conn.execute(
                "SELECT dolzhnost FROM sotrudniki WHERE id = ? AND is_active = 1",
                (user["sotrudnik_id"],),
            ).fetchone()
            # В константе значения строчные (формат Telegram-бота), а в
            # sotrudniki.dolzhnost — названия из мобильного Dolzhnost-Literal
            # с заглавной ("Мастер леса"): точное сравнение не сработало бы
            # никогда, поэтому сравниваем без учёта регистра.
            if row and (row[0] or "").strip().casefold() in config.DOLZHNOSTI_MASTER_URODNYA:
                return user
        raise HTTPException(403, "Недостаточно прав: раздел доступен только руководителям")

    return _dependency


# Чтение веб-разделов с данными рабочих (присутствие, заметки, трелёвка,
# уведомления): admin/lesovod/viewer + рабочие-руководители.
require_office_or_master = _office_or_master(OFFICE_ROLES)
# Запись (например, инвентаризация/перевод лесных культур из поля): то же,
# но без viewer.
require_office_writer_or_master = _office_or_master(OFFICE_WRITE_ROLES)


def map_reader(user=Depends(get_current_user_optional)):
    """Геометрия лесничеств, импортированные слои и склады — только для вошедших
    (рабочий в приложении, сотрудник на сайте, QGIS-мост со служебным токеном).
    До 28.09.2026 эти адреса были открыты всем. LESOVOD_MAP_PUBLIC=1 временно
    возвращает старое поведение — если приложение ещё не обновлено до 0.4.1."""
    if user is None and os.environ.get("LESOVOD_MAP_PUBLIC", "").strip() not in ("1", "true", "yes"):
        raise HTTPException(401, "Требуется авторизация (Authorization: Bearer <token>)")
    return user
