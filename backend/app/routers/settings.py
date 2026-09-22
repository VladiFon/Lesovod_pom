# -*- coding: utf-8 -*-
"""Роутер "Настройки" (screens/settings/) — данные лесничего (app_login) и
план заготовки через db.py, плюс секреты (ключ Gemini/OpenRouter, токен
Telegram-бота) через legacy/secrets_store.py (см. AUDIT.md, п.4: секреты
переехали из QSettings в серверное хранилище — см. docstring
secrets_store.py). Секреты НИКОГДА не возвращаются в открытом виде —
только маскированная форма (mask_api_key), как и в десктоп-версии."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401
import config as legacy_config
import db as legacy_db
import key_test as legacy_key_test
import mdo_parser as legacy_mdo_parser
import secrets_store

from app.database import get_conn

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/lesnichiy")
def get_lesnichiy(conn=Depends(get_conn)):
    return legacy_db.get_app_login(conn)


class LesnichiyIn(BaseModel):
    fio: str
    dolzhnost: str = ""
    lesnichestvo: str = ""


@router.post("/lesnichiy")
def set_lesnichiy(body: LesnichiyIn, conn=Depends(get_conn)):
    legacy_db.set_app_login(conn, body.fio, dolzhnost=body.dolzhnost, lesnichestvo=body.lesnichestvo)
    return {"ok": True}


@router.get("/lesnichestva")
def list_lesnichestva():
    """Названия лесничеств из LCH_MAP (legacy/config.py + legacy/lch_map.json)."""
    return list(legacy_config.LCH_MAP.keys())


@router.get("/harvest-plan")
def get_harvest_plan(periods: Optional[str] = None, conn=Depends(get_conn)):
    """periods — необязательный список 'YYYY-MM' через запятую."""
    period_list = periods.split(",") if periods else None
    return legacy_db.get_harvest_plan(conn, periods=period_list)


class HarvestPlanIn(BaseModel):
    period: str
    plan_obyom: float


@router.post("/harvest-plan")
def set_harvest_plan(body: HarvestPlanIn, conn=Depends(get_conn)):
    legacy_db.set_harvest_plan(conn, body.period, body.plan_obyom)
    return {"ok": True}


# --------------------------------------------------------------------------- #
#   Секреты (ключ Gemini/OpenRouter, токен Telegram-бота)
#   Ни один эндпоинт не возвращает секрет в открытом виде.
# --------------------------------------------------------------------------- #
@router.get("/secrets")
def get_secrets_status():
    """Только МАСКИРОВАННЫЙ статус — null, если секрет не задан."""
    gemini = secrets_store.get_gemini_api_key()
    openrouter = secrets_store.get_openrouter_api_key()
    telegram = secrets_store.get_telegram_bot_token()
    return {
        "gemini_api_key": secrets_store.mask_api_key(gemini) if gemini else None,
        "openrouter_api_key": secrets_store.mask_api_key(openrouter) if openrouter else None,
        "telegram_bot_token": secrets_store.mask_api_key(telegram) if telegram else None,
    }


class SecretIn(BaseModel):
    value: str


_SECRET_SETTERS = {
    "gemini": secrets_store.set_gemini_api_key,
    "openrouter": secrets_store.set_openrouter_api_key,
    "telegram": secrets_store.set_telegram_bot_token,
}
_SECRET_CLEARERS = {
    "gemini": secrets_store.clear_gemini_api_key,
    "openrouter": secrets_store.clear_openrouter_api_key,
    "telegram": secrets_store.clear_telegram_bot_token,
}


@router.post("/secrets/{name}")
def set_secret(name: str, body: SecretIn):
    if name not in _SECRET_SETTERS:
        raise HTTPException(404, "Неизвестный секрет: %s (ожидается gemini/openrouter/telegram)" % name)
    if not body.value.strip():
        raise HTTPException(422, "Значение не может быть пустым — используйте DELETE для очистки")
    _SECRET_SETTERS[name](body.value)
    return {"ok": True}


@router.delete("/secrets/{name}")
def clear_secret(name: str):
    if name not in _SECRET_CLEARERS:
        raise HTTPException(404, "Неизвестный секрет: %s (ожидается gemini/openrouter/telegram)" % name)
    _SECRET_CLEARERS[name]()
    return {"ok": True}


# --------------------------------------------------------------------------- #
#   Проверка ключа/токена (Блок 5 доработки, п.1.1) — реальный лёгкий запрос
#   к сервису (см. legacy/key_test.py: не тратит кредиты/квоту, ничего не
#   отправляет). Раньше кнопки "Проверить" в Settings.jsx были заглушкой —
#   этого эндпоинта не было (см. докстринг Settings.jsx, "Сознательно
#   упрощено", п.1).
# --------------------------------------------------------------------------- #
_SECRET_GETTERS = {
    "gemini": secrets_store.get_gemini_api_key,
    "openrouter": secrets_store.get_openrouter_api_key,
    "telegram": secrets_store.get_telegram_bot_token,
}
_SECRET_TESTERS = {
    "gemini": legacy_key_test.test_gemini_key,
    "openrouter": legacy_key_test.test_openrouter_key,
    "telegram": legacy_key_test.test_telegram_bot_token,
}


class SecretTestIn(BaseModel):
    value: Optional[str] = None


@router.post("/secrets/{name}/test")
def test_secret(name: str, body: Optional[SecretTestIn] = None):
    """Проверяет ключ/токен настоящим запросом к сервису, без сохранения.

    Если body.value передан (пользователь ещё не нажал "Сохранить") —
    проверяем именно его, ничего не записывая на диск — так же, как
    /libreoffice-path/test позволяет проверить путь ДО сохранения.
    Если body/value не переданы — проверяем уже сохранённый на сервере
    секрет."""
    if name not in _SECRET_TESTERS:
        raise HTTPException(404, "Неизвестный секрет: %s (ожидается gemini/openrouter/telegram)" % name)

    value = body.value.strip() if (body and body.value and body.value.strip()) else None
    if value is None:
        value = _SECRET_GETTERS[name]()
        if not value:
            raise HTTPException(
                422,
                "Значение не задано — сначала сохраните ключ/токен или введите его для проверки",
            )

    ok, message = _SECRET_TESTERS[name](value)
    return {"ok": ok, "message": message}


# --------------------------------------------------------------------------- #
#   Путь к LibreOffice (soffice) — используется mdo_parser.py для конвертации
#   .rtf -> .docx при разборе МДО. Логика поиска/хранения пути (реестр
#   Windows, LibreOfficePortable, ручной путь из soffice_path.txt) уже была
#   в legacy/mdo_parser.py (десктопная версия, экран "Настройки" → раздел
#   "LibreOffice") — здесь только HTTP-обёртка над теми же функциями,
#   внутренняя логика не тронута (Блок 5, PLAN_DORABOTKI, п. "путь к
#   LibreOffice как настройка").
# --------------------------------------------------------------------------- #
@router.get("/libreoffice-path")
def get_libreoffice_path():
    """Статус LibreOffice для экрана Настройки: вручную заданный путь (если
    есть), путь, найденный автопоиском (реестр/стандартные места/PATH), и
    итоговый путь, который реально будет использован (ручной приоритетнее
    автопоиска — та же логика, что в mdo_parser._find_soffice)."""
    configured = legacy_mdo_parser.get_configured_soffice_path()
    auto_found = legacy_mdo_parser.find_soffice()
    effective = configured or auto_found
    return {
        "configured_path": configured,
        "auto_found_path": auto_found,
        "effective_path": effective,
        "is_manual": configured is not None,
    }


class LibreOfficePathIn(BaseModel):
    path: str


@router.post("/libreoffice-path")
def set_libreoffice_path(body: LibreOfficePathIn):
    """Сохраняет путь к soffice.exe/soffice, указанный вручную, и сразу
    проверяет, что по нему реально можно запустить LibreOffice (кнопка
    "Сохранить и проверить" на фронте) — используем check_soffice из
    mdo_parser.py, ту же функцию, что уже была в десктопной версии."""
    path = body.path.strip()
    if not path:
        raise HTTPException(422, "Путь не может быть пустым — используйте DELETE для сброса на автопоиск")
    ok, message = legacy_mdo_parser.check_soffice(path)
    legacy_mdo_parser.set_configured_soffice_path(path)
    return {"ok": ok, "message": message, "path": path}


@router.delete("/libreoffice-path")
def clear_libreoffice_path():
    """Сбрасывает вручную заданный путь — снова используется автопоиск."""
    legacy_mdo_parser.clear_configured_soffice_path()
    return {"ok": True}


@router.post("/libreoffice-path/test")
def test_libreoffice_path(body: Optional[LibreOfficePathIn] = None):
    """Проверяет LibreOffice без сохранения — если path не передан, тестирует
    уже сохранённый/автонайденный путь (тот же порядок приоритета, что при
    реальной конвертации в mdo_parser.rtf_to_docx)."""
    path = body.path.strip() if body and body.path.strip() else None
    ok, message = legacy_mdo_parser.check_soffice(path)
    return {"ok": ok, "message": message}
