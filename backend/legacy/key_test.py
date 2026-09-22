# -*- coding: utf-8 -*-
"""
Проверка ключей/токенов из экрана «Настройки» — Блок 5 доработки, п.1.1
(«Проверка ключей/токенов в настройках»).

Раньше (см. Settings.jsx, докстринг «Сознательно упрощено», п.1) кнопки
«Проверить ключ»/«Проверить токен» были заглушками — самого запроса к
внешнему сервису не было ни на фронтенде (нельзя слать секрет прямо из
браузера на сторонний сервис), ни на backend'е (эндпоинта не было).
Этот модуль — та недостающая часть: три лёгких HTTP-запроса, каждый
специально выбран так, чтобы НЕ тратить платные кредиты/квоты и не
иметь побочных эффектов:

    test_openrouter_key(key)
        GET https://openrouter.ai/api/v1/key — сведения об аккаунте,
        привязанном к ключу (лимиты/остаток). Тот же эндпоинт и та же
        идея, что была в ai_vision.test_api_key() десктоп-версии
        (см. её докстринг: "не тратит кредиты").
    test_gemini_key(key)
        GET https://generativelanguage.googleapis.com/v1beta/models —
        список доступных моделей. Стандартный лёгкий способ проверить
        ключ Google Generative Language API без единого вызова
        generateContent (и, соответственно, без расхода квоты).
    test_telegram_bot_token(token)
        GET https://api.telegram.org/bot<token>/getMe — Telegram
        подтверждает валидность токена и возвращает username бота;
        никаких сообщений не отправляется.

Реализовано через urllib (без requests) — тот же приём, что уже был в
ai_vision.py десктоп-версии, чтобы не добавлять новую обязательную
зависимость.

Каждая функция возвращает (ok: bool, message: str) — тот же контракт,
что mdo_parser.check_soffice(), чтобы роутер settings.py мог обрабатывать
результат единообразно для секретов и для LibreOffice.
"""
import json
import ssl
import urllib.error
import urllib.request

import certifi

_TIMEOUT = 15

# urllib по умолчанию не всегда корректно подхватывает доверенные
# сертификаты в venv на Windows (в отличие от requests, который использует
# собственный бандл сертификатов certifi) — из-за этого проверка токенов
# может падать с "self-signed certificate in certificate chain", даже
# когда тот же самый запрос через requests/certifi проходит нормально.
# Явно указываем urllib использовать тот же бандл certifi, что и requests.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _get_json(url: str, headers: dict) -> tuple[bool, dict | str]:
    """Общий GET-запрос: (True, распарсенный JSON) либо (False, текст
    ошибки, уже готовый к показу пользователю)."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CONTEXT) as resp:
            raw = resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        detail = _extract_error_message(body)
        if e.code in (401, 403):
            return False, f"Ключ отклонён сервисом (код {e.code}): {detail}"
        return False, f"Сервис вернул ошибку (код {e.code}): {detail}"
    except urllib.error.URLError as e:
        return False, f"Не удалось подключиться: {e.reason}"
    except TimeoutError:
        return False, "Сервис не ответил за 15 секунд."

    try:
        return True, json.loads(raw)
    except json.JSONDecodeError:
        return False, "Сервис вернул ответ, который не удалось разобрать."


def _extract_error_message(body: str) -> str:
    """Большинство API (OpenRouter, Google, Telegram) при ошибке отдают
    JSON вида {"error": {"message": ...}} или {"description": ...} —
    достаём человекочитаемый текст, если получится, иначе отдаём тело
    как есть (обрезая, чтобы не заваливать интерфейс)."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return (body or "нет описания ошибки").strip()[:300]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
        if data.get("description"):
            return str(data["description"])
    return (body or "нет описания ошибки").strip()[:300]


def test_openrouter_key(key: str) -> tuple[bool, str]:
    """GET /api/v1/key — не тратит кредиты (см. докстринг модуля)."""
    key = (key or "").strip()
    if not key:
        return False, "Ключ не задан."
    ok, result = _get_json(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {key}"},
    )
    if not ok:
        return False, result  # type: ignore[return-value]
    data = result.get("data") if isinstance(result, dict) else None
    label = (data or {}).get("label") or "без метки"
    limit = (data or {}).get("limit")
    limit_text = f", лимит: {limit}" if limit is not None else ""
    return True, f"Ключ действителен. Аккаунт: {label}{limit_text}."


def test_gemini_key(key: str) -> tuple[bool, str]:
    """GET /v1beta/models — не расходует квоту генерации (см. докстринг
    модуля)."""
    key = (key or "").strip()
    if not key:
        return False, "Ключ не задан."
    ok, result = _get_json(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
        headers={},
    )
    if not ok:
        return False, result  # type: ignore[return-value]
    models = result.get("models") if isinstance(result, dict) else None
    count = len(models) if isinstance(models, list) else 0
    return True, f"Ключ действителен. Доступно моделей: {count}."


def test_telegram_bot_token(token: str) -> tuple[bool, str]:
    """GET /bot<token>/getMe — подтверждает токен, ничего не отправляет."""
    token = (token or "").strip()
    if not token:
        return False, "Токен не задан."
    ok, result = _get_json(f"https://api.telegram.org/bot{token}/getMe", headers={})
    if not ok:
        return False, result  # type: ignore[return-value]
    if not isinstance(result, dict) or not result.get("ok"):
        detail = result.get("description") if isinstance(result, dict) else None
        return False, detail or "Telegram не подтвердил токен."
    info = result.get("result") or {}
    username = info.get("username")
    name = f"@{username}" if username else info.get("first_name", "бот")
    return True, f"Токен действителен. Бот: {name}."
