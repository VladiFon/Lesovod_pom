# -*- coding: utf-8 -*-
"""
Хранилище секретов backend-слоя — замена QSettings из вашего config.py
(см. AUDIT.md, п.4 "Общие замечания": "ключи которых сейчас хранятся в
QSettings (config.py) и должны переехать в серверное хранилище
секретов").

Что здесь: ключ Gemini API, ключ OpenRouter API (ai_vision.py),
токен Telegram-бота (telegram_bot.py) — те же три секрета, что в вашем
config.py, только вместо QSettings — файл `APP_DIR/secrets.json`
с правами доступа 0o600 (чтение/запись только владельцу процесса).

mask_api_key() — БЕЗ ИЗМЕНЕНИЙ, дословно перенесена логика из вашего
config.py (чистая функция форматирования строки, без QSettings), чтобы
маскировка в UI выглядела так же, как в десктоп-версии.

ВАЖНО для продакшена: файл на диске хранит секреты ОТКРЫТЫМ ТЕКСТОМ
(права 0o600 — это базовая защита на уровне ОС, не шифрование). Для
реального продакшена замените этот модуль на настоящий секрет-менеджер
(HashiCorp Vault, AWS/GCP Secrets Manager, Docker/Kubernetes secrets и
т.п.) — интерфейс (эти же 9 функций) можно оставить прежним, поменяв
только реализацию _load()/_save() ниже.
"""
import json
import os
import stat
from pathlib import Path

import config as legacy_config

_SECRETS_PATH = Path(legacy_config.APP_DIR) / "secrets.json"

# Те же имена переменных окружения, что и в вашем config.py — чтобы
# ai_vision.py/telegram_bot.py (если будут запускаться в том же
# процессе/окружении, что и backend) продолжали находить ключи там же,
# где они их всегда искали.
GEMINI_ENV_VAR_NAME = "GEMINI_API_KEY"
OPENROUTER_ENV_VAR_NAME = "OPENROUTER_API_KEY"
TELEGRAM_TOKEN_ENV_VAR_NAME = "TELEGRAM_BOT_TOKEN"

_GEMINI_KEY = "gemini_api_key"
_OPENROUTER_KEY = "openrouter_api_key"
_TELEGRAM_TOKEN_KEY = "telegram_bot_token"


def _load() -> dict:
    if not _SECRETS_PATH.exists():
        return {}
    try:
        with open(_SECRETS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    with open(_SECRETS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(_SECRETS_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        pass  # Windows/некоторые ФС не поддерживают chmod — не критично


def _get(key: str) -> str | None:
    value = (_load().get(key) or "").strip()
    return value or None


def _set(key: str, value: str, env_var_name: str) -> None:
    data = _load()
    data[key] = (value or "").strip()
    _save(data)
    os.environ[env_var_name] = data[key]


def _clear(key: str, env_var_name: str) -> None:
    data = _load()
    data.pop(key, None)
    _save(data)
    os.environ.pop(env_var_name, None)


# --------------------------------------------------------------------------- #
#   Gemini API key
# --------------------------------------------------------------------------- #
def get_gemini_api_key() -> str | None:
    return _get(_GEMINI_KEY)


def set_gemini_api_key(key: str) -> None:
    _set(_GEMINI_KEY, key, GEMINI_ENV_VAR_NAME)


def clear_gemini_api_key() -> None:
    _clear(_GEMINI_KEY, GEMINI_ENV_VAR_NAME)


# --------------------------------------------------------------------------- #
#   OpenRouter API key
# --------------------------------------------------------------------------- #
def get_openrouter_api_key() -> str | None:
    return _get(_OPENROUTER_KEY)


def set_openrouter_api_key(key: str) -> None:
    _set(_OPENROUTER_KEY, key, OPENROUTER_ENV_VAR_NAME)


def clear_openrouter_api_key() -> None:
    _clear(_OPENROUTER_KEY, OPENROUTER_ENV_VAR_NAME)


# --------------------------------------------------------------------------- #
#   Telegram bot token
# --------------------------------------------------------------------------- #
def get_telegram_bot_token() -> str | None:
    return _get(_TELEGRAM_TOKEN_KEY)


def set_telegram_bot_token(token: str) -> None:
    _set(_TELEGRAM_TOKEN_KEY, token, TELEGRAM_TOKEN_ENV_VAR_NAME)


def clear_telegram_bot_token() -> None:
    _clear(_TELEGRAM_TOKEN_KEY, TELEGRAM_TOKEN_ENV_VAR_NAME)


def apply_saved_secrets_to_env() -> None:
    """Вызывается один раз при старте backend'а (main.py): кладёт уже
    сохранённые секреты в os.environ для этого процесса — тем же
    поведением, что и config.apply_saved_api_key_to_env() в десктопе
    (если переменная окружения ОС уже задана явно — не перезаписываем)."""
    if not os.environ.get(GEMINI_ENV_VAR_NAME):
        key = get_gemini_api_key()
        if key:
            os.environ[GEMINI_ENV_VAR_NAME] = key
    if not os.environ.get(OPENROUTER_ENV_VAR_NAME):
        key = get_openrouter_api_key()
        if key:
            os.environ[OPENROUTER_ENV_VAR_NAME] = key
    if not os.environ.get(TELEGRAM_TOKEN_ENV_VAR_NAME):
        token = get_telegram_bot_token()
        if token:
            os.environ[TELEGRAM_TOKEN_ENV_VAR_NAME] = token


def mask_api_key(key: str) -> str:
    """Дословно перенесено из вашего config.py (чистая функция форматирования,
    без QSettings) — маскированное представление ключа для интерфейса,
    например "AQ.Ab8R••••••••Bazsg", чтобы после сохранения ключ не
    светился на экране целиком открытым текстом."""
    key = (key or "").strip()
    if len(key) <= 10:
        return "•" * len(key)
    return f"{key[:6]}{'•' * 8}{key[-4:]}"
