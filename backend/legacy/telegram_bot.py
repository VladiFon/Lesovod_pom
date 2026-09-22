# -*- coding: utf-8 -*-
"""
Telegram-бот "Цифровой помощник лесовода".

ВЕРСИЯ БЕЗ ИИ. В Беларуси нет надёжного доступа ни к Google Gemini, ни к
бесплатным моделям OpenRouter (то работает, то нет) — поэтому бот больше
НЕ пытается распознавать свободный текст. Вместо этого он ведёт рабочего
через пошаговый опрос (один вопрос — один ответ), а тип работы вообще не
нужно распознавать: он однозначно известен из того, какую кнопку меню
нажал рабочий.

Архитектура:
  - При первом запуске рабочий регистрируется: ФИО -> должность (кнопкой)
    -> лесничество (кнопкой). Должность хранится в lesorub_directory.dolzhnost
    и определяет, какое меню бот показывает дальше (get_menu_for_dolzhnost).
  - Отчёт о работе — это всегда пошаговый диалог: кнопка с типом работы ->
    "введи квартал" -> "введи выдел(а)" -> "фото или нет". Свободный текст
    одним сообщением для отчётов больше не разбирается.
  - Каждый отчёт уходит в буферную таблицу raw_reports (status='на
    проверке') — НЕ сразу в completed_works. Лесничий подтверждает его на
    экране "Журнал ИИ" в приложении (screens/ai_log/), после чего запись
    переносится в completed_works. Так как ввод теперь структурированный
    (не текст на разбор), это быстрая проверка, а не разбор ошибок ИИ.
  - Тракторист/харвестерщик видят кнопку "⚠️ Поломка": отчёт о поломке
    сразу рассылается всем зарегистрированным лесничим с inline-кнопкой
    "Добавить в служебные записки".
  - Голосовые сообщения не поддерживаются вообще (по требованию — раньше
    их пытался слушать Gemini, теперь такой возможности нет и не нужно).
  - Перед сохранением отчёта бот проверяет, не отправлял ли этот же
    рабочий точно такой же отчёт (кв/выд/тип работы) недавно, и если да —
    переспрашивает подтверждение (защита от случайного дубля, см.
    DEDUP_WINDOW_MINUTES/find_recent_duplicate_report). Кнопка "↩️
    Отменить последний отчёт" позволяет рабочему самому удалить свой
    последний отчёт, пока его ещё не проверил лесничий.

Идентификатор пользователя Telegram (from_user.id) хранится и проверяется
в уже существующей колонке viber_id таблицы lesorub_directory.

Запуск:
    pip install pyTelegramBotAPI
    python telegram_bot.py
"""
import re
import sqlite3
import os
import sys
import uuid
from datetime import datetime

# Бот работает как служба nssm (deploy/install_service.bat), без реальной
# консоли — Windows в этом случае отдаёт Python-процессу stdout/stderr в
# кодировке однобайтовой code page по умолчанию для системы (у нас —
# cp1251), а не UTF-8. Эмодзи (✅, 🌲 и т.п.) в cp1251 не существуют, поэтому
# print() с ними падал с UnicodeEncodeError прямо на строке успешного
# подключения к Telegram (if __name__ == "__main__" внизу файла) — бот
# фактически стартовал и получал bot.get_me(), но тут же падал на первом же
# print(), и nssm тут же перезапускал его заново (AppExit Default Restart) —
# отсюда бесконечный цикл рестартов, хотя сама логика бота была уже
# полностью рабочей. Принудительно переводим stdout/stderr на UTF-8 с
# errors="replace" (не крашиться даже если попадётся что-то совсем
# непечатаемое) до первого print() в файле — это чинит и эту точку, и любой
# другой print/лог с кириллицей или эмодзи, а не только эту одну строку.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import requests
import telebot
from telebot import types

import config
# get_remaining_volumes_for_bot — ЕДИНСТВЕННАЯ функция, которая ОСОЗНАННО НЕ
# переводится на HTTP в этом заходе (часть 3.4). Находка №1 аудита (часть
# 1/4 плана, Этап 4/Блок 3): эта же функция в raskhod_v2.py (которым
# пользуется веб) не делает сверку с ЕГАИС — если бы бот вызывал её через
# HTTP как есть (например, GET /api/raskhod/remaining), он тихо потерял бы
# защиту от переруба (см. докстринг _format_remaining_reply). Выбран
# вариант (б) из двух предложенных аудитом: бот по-прежнему вызывает
# raskhod.get_remaining_volumes_for_bot(conn, ...) напрямую, локальным
# sqlite-соединением (см. handle_balance_callback) — единственное
# оставшееся прямое обращение к БД в файле после этой правки. Вариант (а)
# (перенести ЕГАИС-сверку в raskhod_v2.py, чтобы веб тоже её получил) не
# выбран: это отдельная, более рискованная правка живой логики баланса,
# которой пользуется веб-интерфейс лесничих, и в объём части 3.4 она не
# входит — если понадобится когда-нибудь дать вебу ту же сверку, это
# отдельный заход, не связанный с переводом бота на HTTP.
from raskhod_v2 import get_remaining_volumes_grouped_for_bot as get_remaining_volumes_for_bot
from config import LCH_MAP
# get_vydel_card (часть 3.4) — прямой своп, не HTTP-обёртка через
# app/routers/bot.py: тот же SQL уже был доступен вебу через
# GET /api/taxation/vydel (app/routers/taxation.py), поэтому вместо нового
# роутер-эндпоинта process_taxation_step теперь просто ходит по этому уже
# существующему адресу (см. get_taxation_card() ниже) — заводить дубль в
# app/routers/bot.py не понадобилось.
# get_tasks_for_bot/complete_task_for_bot/get_active_delyanki_for_bot/
# get_last_raw_report_for_user/cancel_raw_report (часть 3.4, эта правка) —
# как и find_recent_duplicate_report/save_raw_report (3.2) и
# get_lesnichiy_telegram_ids/save_breakdown_report/
# add_sluzhebnaya_zametka_from_breakdown/list_active_sluzhebnye_zametki/
# complete_sluzhebnaya_zametka (3.3), сюда больше не импортируются — все
# теперь вызываются через HTTP (см. секцию get_active_delyanki()/
# get_worker_tasks()/complete_task()/get_last_report()/cancel_report()/
# get_taxation_card()/save_geo_note() ниже, app/routers/bot.py +
# существующий app/routers/taxation.py), а не напрямую из db.py по общему
# sqlite-соединению бота.
# migrate_schema — часть 3.5 (эта правка) рассмотрела и СОЗНАТЕЛЬНО
# ОСТАВИЛА вызов в run_bot() как есть (см. её докстринг ниже) — импорт
# остаётся, это не забытый хвост.
from db import migrate_schema

# ---------------------------------------------------------------- настройки ---
# Токен больше не хардкодится в исходнике (иначе он уезжает прямо в
# собранный .exe, откуда его видно через `strings`) — вводится лесничим на
# экране "Настройки" (screens/settings/) и хранится через config.py (QSettings).
TOKEN = config.get_telegram_bot_token()
if not TOKEN:
    raise RuntimeError(
        "Токен Telegram-бота не задан. Откройте приложение → Настройки → "
        "Telegram-бот, вставьте токен от @BotFather и сохраните."
    )
# Раньше BASE_DIR/DB_PATH считались через __file__ - в собранном .exe это
# указывало не туда (модуль упакован в архив PyInstaller), из-за чего бот
# писал/читал СВОЮ ОТДЕЛЬНУЮ базу вместо базы основного приложения, и не
# мог создать папку photos на запись. config.DB_PATH и config.APP_DIR уже
# правильно учитывают frozen-режим (sys._MEIPASS/sys.argv[0]) - используем их,
# чтобы бот и десктоп-приложение работали с ОДНОЙ и той же lesovod.db.
DB_PATH = config.DB_PATH
# Папка для локального хранения фото-отчётов (акты/делянки/поломки) —
# создаётся автоматически при первом запуске, если её ещё нет
PHOTOS_DIR = os.path.join(config.APP_DIR, "photos")
os.makedirs(PHOTOS_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN)

# ------------------------------------------------------- backend HTTP API ---
# Этап 4 доработки, Блок 3: функции бота переводятся с прямых запросов к
# sqlite (get_db()) на HTTP-вызовы к тому же backend'у, которым пользуется
# веб-фронтенд — app/routers/bot.py.
#   часть 3.1 (сделано): регистрация — GET/PUT /api/bot/workers/{telegram_id}.
#   часть 3.2 (эта правка): отчёты о работе — POST /api/bot/reports,
#     GET /api/bot/reports/duplicate.
#   часть 3.3 (сделано): поломки и служебные записки —
#     POST /api/bot/breakdowns, POST /api/bot/breakdowns/{id}/notes,
#     GET /api/bot/zametki, POST /api/bot/zametki/{id}/complete.
#   часть 3.4 (сделано): остатки/задачи/таксация/отмена отчёта —
#     GET /api/bot/delyanki, GET /api/bot/tasks,
#     POST /api/bot/tasks/{id}/complete, GET /api/bot/raw-reports/last,
#     DELETE /api/bot/raw-reports/{id}, плюс прямой своп таксации на уже
#     существующий GET /api/taxation/vydel.
#   часть 3.5 (эта правка, последняя в Блоке 3): гео-заметки —
#     POST /api/bot/geo-notes (см. save_geo_note() ниже, вызывается из
#     handle_message/handle_photo вместо старой _save_geo_note(cursor,
#     ...)). handle_location не трогает БД вообще (только кладёт координаты
#     в _pending_geo — оперативная память процесса, не таблица), поэтому
#     менять в ней было нечего — рассмотрена и оставлена как была.
#     run_bot()/вызов migrate_schema при старте — тоже рассмотрены и
#     СОЗНАТЕЛЬНО ОСТАВЛЕНЫ без изменений (см. докстринг run_bot()).
# Единственное оставшееся прямое обращение бота к БД после части 3.5 —
# get_remaining_volumes_for_bot в handle_balance_callback (см. комментарий
# у её импорта выше, решение части 3.4) — по-прежнему сознательное
# исключение, не забытый хвост.
API_BASE_URL = config.get_api_base_url().rstrip("/")
BOT_SERVICE_TOKEN = config.get_bot_service_token()

# Одна сессия на процесс бота — переиспользует TCP-соединение вместо
# нового на каждый запрос; заголовок Authorization выставляется один раз.
_api_session = requests.Session()
if BOT_SERVICE_TOKEN:
    _api_session.headers["Authorization"] = f"Bearer {BOT_SERVICE_TOKEN}"
_api_session.headers["Content-Type"] = "application/json"

# Бот и backend по плану развёртывания живут на одном сервере (localhost)
# — 10 секунд с большим запасом, но не бесконечность: если backend завис,
# лучше быстро сказать рабочему "сервер недоступен", чем заставить его
# ждать неопределённое время ответа Telegram.
API_TIMEOUT_SECONDS = 10


def _api_request(method, path, **kwargs):
    """Общая обёртка над requests для походов в backend API. НЕ перехватывает
    сетевые ошибки сама — поднимает requests.exceptions.RequestException,
    решение "что ответить пользователю при недоступном backend'е" остаётся
    за вызывающим кодом (см. _friendly_api_error_text)."""
    url = f"{API_BASE_URL}{path}"
    return _api_session.request(method, url, timeout=API_TIMEOUT_SECONDS, **kwargs)


def _friendly_api_error_text():
    """Единый текст, который рабочий видит, если backend недоступен/ответил
    ошибкой — вместо падения бота с необработанным исключением."""
    return (
        "Не получилось связаться с сервером. Попробуйте, пожалуйста, ещё "
        "раз через минуту — если не поможет, сообщите лесничему."
    )


def get_worker(telegram_id):
    """GET /api/bot/workers/{telegram_id}. Возвращает dict с полями
    viber_id/fio/dolzhnost/lesnichestvo, или None, если рабочий ещё не
    регистрировался (backend отвечает 404) — тот же смысл, что раньше был
    у `user is None` после SELECT из lesorub_directory в send_welcome.
    Поднимает requests.exceptions.RequestException, если backend
    недоступен, — намеренно НЕ превращает сетевую проблему в "не
    зарегистрирован", чтобы не запускать регистрацию заново поверх уже
    существующего профиля из-за временного сбоя сети."""
    response = _api_request("GET", f"/api/bot/workers/{telegram_id}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def save_registration(telegram_id, fio, dolzhnost, lesnichestvo):
    """PUT /api/bot/workers/{telegram_id} — то же самое, что раньше делала
    _save_registration(cursor, ...) напрямую в sqlite (upsert по
    viber_id: UPDATE, если запись уже есть, иначе INSERT), теперь через
    backend, единой точкой правды для бота и веб-фронтенда."""
    response = _api_request(
        "PUT",
        f"/api/bot/workers/{telegram_id}",
        json={"fio": fio, "dolzhnost": dolzhnost, "lesnichestvo": lesnichestvo},
    )
    response.raise_for_status()
    return response.json()


def check_duplicate_report(telegram_id, kvartal, vydels, tip_raboty, window_minutes):
    """GET /api/bot/reports/duplicate — то же самое, что раньше делала
    find_recent_duplicate_report(conn, ...) из db.py, вызванная напрямую по
    общему sqlite-соединению бота (см. process_report_photo_step). Теперь
    сама SQL-логика живёт в db.py и вызывается backend'ом через
    app/routers/bot.py — здесь только HTTP-запрос. Возвращает dict с
    данными найденного отчёта (id/kvartal/vydels/tip_raboty/
    data_soobscheniya) или None, если дубля нет — тем же смыслом, что и
    раньше."""
    response = _api_request(
        "GET",
        "/api/bot/reports/duplicate",
        params={
            "telegram_id": telegram_id,
            "kvartal": kvartal,
            "vydels": ", ".join(vydels) if vydels else "",
            "tip_raboty": tip_raboty,
            "window_minutes": window_minutes,
        },
    )
    response.raise_for_status()
    return response.json()["duplicate"]


def create_raw_report(telegram_id, kvartal, vydels, tip_raboty, photo_path=None, opisanie=None):
    """POST /api/bot/reports — то же самое, что раньше делала
    save_raw_report(cursor, ...) (была определена прямо в этом файле,
    писала в raw_reports по общему sqlite-соединению бота и не коммитила
    сама — коммит делал вызывающий код). Теперь INSERT живёт в db.py
    (save_raw_report(conn, ...), вызывается backend'ом через
    app/routers/bot.py, коммитит сам) — здесь только HTTP-запрос. ФИО
    отдельно не передаём — backend сам берёт его из lesorub_directory по
    telegram_id (тот же профиль, что и GET /api/bot/workers/{telegram_id})."""
    response = _api_request(
        "POST",
        "/api/bot/reports",
        json={
            "telegram_id": telegram_id,
            "kvartal": kvartal,
            "vydels": vydels,
            "tip_raboty": tip_raboty,
            "photo_path": photo_path,
            "opisanie": opisanie,
        },
    )
    response.raise_for_status()
    return response.json()


def create_breakdown_report(telegram_id, detail_text, photo_path=None):
    """POST /api/bot/breakdowns — то же самое, что раньше делала
    process_breakdown_step напрямую: save_breakdown_report(cursor, ...) +
    get_lesnichiy_telegram_ids(conn) по общему sqlite-соединению бота.
    Оба результата теперь приходят одним HTTP-запросом (dict с ключами
    id/fio/dolzhnost/lesnichiy_telegram_ids) — ФИО/должность отдельно не
    передаём, backend сам берёт их из lesorub_directory по telegram_id,
    тем же принципом, что и create_raw_report()."""
    response = _api_request(
        "POST",
        "/api/bot/breakdowns",
        json={"telegram_id": telegram_id, "detail_text": detail_text, "photo_path": photo_path},
    )
    response.raise_for_status()
    return response.json()


def add_breakdown_to_notes(breakdown_id):
    """POST /api/bot/breakdowns/{id}/notes — то же самое, что раньше делала
    add_sluzhebnaya_zametka_from_breakdown(conn, ...), вызванная напрямую
    из handle_breakdown_add_callback. Возвращает id новой заметки, или
    None, если поломка не найдена или уже была обработана раньше (тем же
    смыслом, что и раньше)."""
    response = _api_request("POST", f"/api/bot/breakdowns/{breakdown_id}/notes")
    response.raise_for_status()
    return response.json()["zametka_id"]


def get_active_zametki():
    """GET /api/bot/zametki — то же самое, что раньше делала
    list_active_sluzhebnye_zametki(conn), вызванная напрямую из
    process_zametki_list. Возвращает список dict'ов (id/text/source/
    ispolnitel_fio/telegram_id/status/created_at)."""
    response = _api_request("GET", "/api/bot/zametki")
    response.raise_for_status()
    return response.json()


def complete_zametka(zametka_id):
    """POST /api/bot/zametki/{id}/complete — то же самое, что раньше
    делала complete_sluzhebnaya_zametka(conn, ...), вызванная напрямую из
    handle_zametka_done_callback. True — заметка была активна и теперь
    закрыта; False — уже была закрыта раньше или не найдена."""
    response = _api_request("POST", f"/api/bot/zametki/{zametka_id}/complete")
    response.raise_for_status()
    return response.json()["done"]


def get_active_delyanki(kvartal):
    """GET /api/bot/delyanki — то же самое, что раньше делала
    get_active_delyanki_for_bot(conn, kvartal) из db.py, вызванная
    напрямую из process_balance_step по общему sqlite-соединению бота.
    Возвращает список dict'ов {"vydel": ..., "lesoseka_nomer": ...}."""
    response = _api_request("GET", "/api/bot/delyanki", params={"kvartal": kvartal})
    response.raise_for_status()
    return response.json()


def get_worker_tasks(telegram_id):
    """GET /api/bot/tasks — то же самое, что раньше делала
    get_tasks_for_bot(conn, telegram_id) из db.py, вызванная напрямую из
    handle_message (кнопка '📋 Мои задачи'). Возвращает список dict'ов
    (id/opisanie/status/created_at)."""
    response = _api_request("GET", "/api/bot/tasks", params={"telegram_id": telegram_id})
    response.raise_for_status()
    return response.json()


def complete_task(task_id, telegram_id):
    """POST /api/bot/tasks/{id}/complete — то же самое, что раньше делала
    complete_task_for_bot(conn, ...), вызванная напрямую из
    handle_taskdone_callback. True — задача была активна и теперь закрыта;
    False — уже была закрыта раньше, не найдена или принадлежит другому
    telegram_id (та же проверка владения, что раньше была в WHERE
    telegram_id=? самого UPDATE — теперь внутри app/routers/bot.py)."""
    response = _api_request(
        "POST", f"/api/bot/tasks/{task_id}/complete", params={"telegram_id": telegram_id},
    )
    response.raise_for_status()
    return response.json()["done"]


def get_last_report(telegram_id):
    """GET /api/bot/raw-reports/last — то же самое, что раньше делала
    get_last_raw_report_for_user(conn, telegram_id) из db.py, вызванная
    напрямую из process_cancel_last_report. Возвращает dict
    (id/kvartal/vydels/tip_raboty/data_soobscheniya) или None, если
    отменять нечего (тем же смыслом, что и раньше)."""
    response = _api_request("GET", "/api/bot/raw-reports/last", params={"telegram_id": telegram_id})
    response.raise_for_status()
    return response.json()["report"]


def cancel_report(report_id, telegram_id):
    """DELETE /api/bot/raw-reports/{id} — то же самое, что раньше делала
    cancel_raw_report(conn, ...), вызванная напрямую из
    process_cancel_last_report_confirm_step. Возвращает dict
    {"cancelled": bool, "photo_path": str|None} — cancelled=False значит
    отчёт не найден, принадлежит другому telegram_id или уже проверен
    лесничим (тем же смыслом, что раньше был у возврата False)."""
    response = _api_request(
        "DELETE", f"/api/bot/raw-reports/{report_id}", params={"telegram_id": telegram_id},
    )
    response.raise_for_status()
    return response.json()


def get_taxation_card(kvartal, vydel):
    """GET /api/taxation/vydel — прямой своп на уже существующий
    эндпоинт (аудит, находка "низкий риск", часть 3a): раньше
    process_taxation_step вызывала get_vydel_card(conn, kvartal, vydel) из
    db.py напрямую; тот же SQL уже был доступен вебу через
    GET /api/taxation/vydel (app/routers/taxation.py) — отдельный новый
    эндпоинт в app/routers/bot.py заводить не понадобилось. Возвращает
    dict карточки, или None, если выдел не найден в таксации (backend
    отвечает 404, тем же смыслом, что раньше был у None из
    get_vydel_card)."""
    response = _api_request("GET", "/api/taxation/vydel", params={"kvartal": kvartal, "vydel": vydel})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def save_geo_note(telegram_id, coords, note_text, photo_path):
    """POST /api/bot/geo-notes — то же самое, что раньше делала
    _save_geo_note(cursor, ...) (была определена прямо в этом файле,
    писала в geo_notes по общему sqlite-соединению бота, без собственного
    commit — коммитил вызывающий код, handle_message/handle_photo).
    Теперь INSERT живёт в app/routers/bot.py (тот же принцип, что и
    upsert_worker() там же для регистрации — таблица однострочная,
    заводить под неё функцию в db.py не понадобилось), коммитит сам.
    coords — dict {"lat": ..., "lon": ...} из _pending_geo (см.
    handle_location)."""
    response = _api_request(
        "POST",
        "/api/bot/geo-notes",
        json={
            "telegram_id": telegram_id,
            "lat": coords["lat"],
            "lon": coords["lon"],
            "note_text": note_text or None,
            "photo_path": photo_path,
        },
    )
    response.raise_for_status()
    return response.json()["id"]


# --------------------------------------------------------------- кнопки меню ---
# Кнопка типа работы -> tip_raboty, который однозначно пишется в отчёт
# (см. ROLE_REPORT_BUTTON ниже) — тип работы больше не нужно распознавать,
# он известен из того, какую кнопку нажал рабочий.
BTN_OTHER_WORK = "📦 Другая работа"
BTN_BALANCE = "🌲 Остатки на делянке"
BTN_TAXATION = "📖 Таксационные характеристики"
BTN_GEO_NOTE = "📍 Добавить заметку на делянку"
BTN_TASKS = "📋 Мои задачи"
BTN_BREAKDOWN = "⚠️ Поломка"
BTN_ZAMETKI = "🗒 Служебные заметки"
BTN_CANCEL_LAST = "↩️ Отменить последний отчёт"
BTN_YES = "Да, отправить"
BTN_NO = "Нет, отменить"

# Отчёт с теми же кварталом/выделами/типом работы от того же рабочего в
# пределах этого окна считается вероятным дублем (двойное нажатие кнопки,
# повтор после сбоя связи и т.п.) — при отправке такого бот сначала
# переспрашивает подтверждение (см. process_report_photo_step), а не
# сохраняет отчёт молча второй раз.
DEDUP_WINDOW_MINUTES = 240

# Должность -> (текст кнопки основной работы, tip_raboty для этой кнопки).
# Порядок — как в исходном ТЗ: лесовод отчитывается по рубкам ухода,
# тракторист — по вывозке, харвестерщик и вальщик — по заготовке.
ROLE_REPORT_BUTTON = {
    config.DOLZHNOST_LESOVOD: ("🌲 Рубки ухода", "рубки ухода"),
    config.DOLZHNOST_TRAKTORIST: ("🚚 Вывозка", "вывозка"),
    config.DOLZHNOST_HARVESTER: ("🪓 Заготовка", "заготовка"),
    config.DOLZHNOST_VALSCHIK: ("🪓 Заготовка", "заготовка"),
}

# Текст кнопки -> tip_raboty, который в итоге попадёт в raw_reports.tip_raboty
# (см. handle_message: перехват кнопок отчёта). Собирается один раз при
# импорте модуля из ROLE_REPORT_BUTTON + BTN_OTHER_WORK.
REPORT_BUTTON_TIP = {btn_text: tip for btn_text, tip in ROLE_REPORT_BUTTON.values()}
REPORT_BUTTON_TIP[BTN_OTHER_WORK] = "другая работа"

# label ("Тракторист") -> ключ должности ("тракторист") — обратный словарь
# к config.DOLZHNOSTI, нужен при разборе ответа на кнопку выбора должности
# при регистрации (см. process_dolzhnost_step).
DOLZHNOST_LABEL_TO_KEY = {label: key for key, label in config.DOLZHNOSTI.items()}


def get_dolzhnost_menu():
    """Клавиатура выбора должности при регистрации (см. process_fio_step) —
    одна кнопка на каждую должность из config.DOLZHNOSTI, в заданном там
    порядке."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for label in config.DOLZHNOSTI.values():
        markup.add(types.KeyboardButton(label))
    return markup


def get_lesnichestvo_menu():
    """Клавиатура с названиями лесничеств (LCH_MAP, config.py) — показывается
    при регистрации, чтобы рабочий один раз выбрал своё лесничество кнопкой
    (вместо того чтобы бот пытался угадать его из текста каждого отчёта)."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for name in LCH_MAP:
        markup.add(types.KeyboardButton(name))
    return markup


def get_menu_for_dolzhnost(dolzhnost):
    """Возвращает постоянную клавиатуру (ReplyKeyboardMarkup) под конкретную
    должность рабочего:
      - лесовод/тракторист/харвестерщик/вальщик леса — кнопка своей основной
        работы + "Другая работа" + "Мои задачи"; у тракториста/харвестерщика
        дополнительно "⚠️ Поломка" (см. config.DOLZHNOSTI_S_POLOMKOY);
      - мастер леса/помощник лесничего/лесничий — остатки, таксация,
        геозаметка, другая работа, мои задачи; у лесничего дополнительно
        "Служебные заметки" (см. config.DOLZHNOSTI_MASTER_URODNYA).
    Если должность не распознана (не должна происходить после регистрации,
    но подстраховка на случай очень старой записи в базе) — возвращает
    минимальный набор без ролевых кнопок."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)

    if dolzhnost in ROLE_REPORT_BUTTON:
        btn_text, _tip = ROLE_REPORT_BUTTON[dolzhnost]
        markup.row(types.KeyboardButton(btn_text), types.KeyboardButton(BTN_OTHER_WORK))
        if dolzhnost in config.DOLZHNOSTI_S_POLOMKOY:
            markup.row(types.KeyboardButton(BTN_BREAKDOWN))
        markup.row(types.KeyboardButton(BTN_TASKS), types.KeyboardButton(BTN_CANCEL_LAST))
        return markup

    if dolzhnost in config.DOLZHNOSTI_MASTER_URODNYA:
        markup.row(types.KeyboardButton(BTN_BALANCE), types.KeyboardButton(BTN_TAXATION))
        markup.row(types.KeyboardButton(BTN_GEO_NOTE), types.KeyboardButton(BTN_OTHER_WORK))
        if dolzhnost == config.DOLZHNOST_LESNICHIY:
            markup.row(types.KeyboardButton(BTN_ZAMETKI))
        markup.row(types.KeyboardButton(BTN_TASKS))
        return markup

    markup.row(types.KeyboardButton(BTN_TASKS))
    return markup


# Промежуточное состояние приёма гео-заметки: telegram_id -> {"lat", "lon"} —
# рабочий прислал геометку (см. handle_location) и теперь бот ждёт от него
# следующее сообщение (текст/фото), чтобы привязать к этой точке как
# комментарий. Хранится в памяти процесса (не в БД) — короткоживущее
# состояние диалога, а не постоянные данные.
_pending_geo = {}


# ---------------------------------------------------------------- работа с БД ---
def get_db():
    """Открывает соединение с базой lesovod.db.
    Строки возвращаются как sqlite3.Row, что позволяет обращаться
    к полям по имени колонки (row['fio'])."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def download_photo(message):
    """Если в сообщении есть фото — скачивает его (в максимальном
    доступном разрешении) через bot.get_file()/bot.download_file() и
    сохраняет в папку photos под уникальным именем на основе timestamp
    и message_id. Возвращает путь к сохранённому файлу или None, если
    фото не было или скачать не удалось (сеть, ошибка API и т.п.) —
    в этом случае вызывающий код просто продолжает работу без фото.

    Этап 4, Блок 3/часть 3.2: НЕ переводится на HTTP и не меняется —
    это вызовы Telegram Bot API (bot.get_file/bot.download_file), а не
    обращение к нашему backend'у; сохранение файла на диск через open()
    так и остаётся локальной файловой операцией бота. В наш API
    (POST /api/bot/reports, см. create_raw_report() выше) передаётся уже
    готовый photo_path — то же самое, что раньше писала сюда
    save_raw_report(cursor, ...) напрямую в raw_reports.photo_path."""
    if not getattr(message, "photo", None):
        return None
    try:
        file_id = message.photo[-1].file_id  # последний элемент — самое высокое разрешение
        file_info = bot.get_file(file_id)
        file_bytes = bot.download_file(file_info.file_path)
        ext = os.path.splitext(file_info.file_path)[1] or ".jpg"
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{message.message_id}{ext}"
        photo_path = os.path.join(PHOTOS_DIR, filename)
        with open(photo_path, "wb") as f:
            f.write(file_bytes)
        return photo_path
    except Exception:
        return None


# ------------------------------------------------------------------ регистрация ---
@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    """/start и /help.
      - Новый пользователь -> запускаем регистрацию (ФИО -> должность ->
        лесничество).
      - Зарегистрированный, но с неполным профилем (обновление бота на
        уже работавшей базе, где ещё нет должности) -> доспрашиваем
        недостающее, не заставляя вводить ФИО заново.
      - Полностью зарегистрированный -> показываем меню под его должность.

    Этап 4, Блок 3/часть 3.1: SELECT из lesorub_directory заменён на
    get_worker() — HTTP-вызов к app/routers/bot.py вместо прямого
    sqlite3.connect."""
    telegram_id = str(message.from_user.id)
    try:
        user = get_worker(telegram_id)
    except requests.exceptions.RequestException:
        bot.send_message(message.chat.id, _friendly_api_error_text())
        return

    if user is None:
        _start_registration(message)
        return

    if not user["dolzhnost"]:
        msg = bot.send_message(
            message.chat.id,
            f"С возвращением, {user['fio']}! Бот обновился — нужно один раз "
            "уточнить твою должность.",
            reply_markup=get_dolzhnost_menu(),
        )
        bot.register_next_step_handler(msg, process_dolzhnost_step, user["fio"])
        return

    if not user["lesnichestvo"]:
        msg = bot.send_message(
            message.chat.id,
            f"С возвращением, {user['fio']}! Уточни своё лесничество:",
            reply_markup=get_lesnichestvo_menu(),
        )
        bot.register_next_step_handler(msg, process_lesnichestvo_step, user["fio"], user["dolzhnost"])
        return

    bot.send_message(
        message.chat.id,
        f"С возвращением, {user['fio']}! Пользуйся кнопками ниже.",
        reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
    )


def _start_registration(message):
    msg = bot.send_message(
        message.chat.id,
        "Привет! Я цифровой помощник лесовода 🌲\n"
        "Давай зарегистрируемся. Напиши свои фамилию, имя и отчество "
        "(например: Иванов Андрей Петрович):",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(msg, process_fio_step)


def process_fio_step(message):
    fio = (message.text or "").strip()
    if len(fio.split()) < 2:
        msg = bot.reply_to(
            message,
            "Похоже, это не ФИО. Напиши, пожалуйста, минимум фамилию и имя "
            "(например: Иванов Андрей Петрович):",
        )
        bot.register_next_step_handler(msg, process_fio_step)
        return
    msg = bot.reply_to(message, "Отлично! Теперь выбери свою должность:", reply_markup=get_dolzhnost_menu())
    bot.register_next_step_handler(msg, process_dolzhnost_step, fio)


def process_dolzhnost_step(message, fio):
    label = (message.text or "").strip()
    dolzhnost = DOLZHNOST_LABEL_TO_KEY.get(label)
    if not dolzhnost:
        msg = bot.reply_to(
            message,
            "Пожалуйста, выбери должность кнопкой на клавиатуре ниже.",
            reply_markup=get_dolzhnost_menu(),
        )
        bot.register_next_step_handler(msg, process_dolzhnost_step, fio)
        return
    msg = bot.reply_to(message, "Теперь выбери своё лесничество:", reply_markup=get_lesnichestvo_menu())
    bot.register_next_step_handler(msg, process_lesnichestvo_step, fio, dolzhnost)


def process_lesnichestvo_step(message, fio, dolzhnost):
    lesnichestvo = (message.text or "").strip()
    if lesnichestvo not in LCH_MAP:
        msg = bot.reply_to(
            message,
            "Пожалуйста, выбери лесничество кнопкой на клавиатуре ниже.",
            reply_markup=get_lesnichestvo_menu(),
        )
        bot.register_next_step_handler(msg, process_lesnichestvo_step, fio, dolzhnost)
        return

    telegram_id = str(message.from_user.id)
    try:
        save_registration(telegram_id, fio, dolzhnost, lesnichestvo)
    except requests.exceptions.RequestException:
        bot.send_message(message.chat.id, _friendly_api_error_text())
        return

    bot.send_message(
        message.chat.id,
        f"Приятно познакомиться, {fio}!\n"
        f"Должность: {config.DOLZHNOSTI[dolzhnost]}\n"
        f"Лесничество: {lesnichestvo}\n\n"
        "Теперь можно пользоваться кнопками ниже.",
        reply_markup=get_menu_for_dolzhnost(dolzhnost),
    )


def _require_registered_user(telegram_id):
    """Общая проверка регистрации — используется и в handle_message, и в
    step-хендлерах (process_balance_step, process_taxation_step,
    process_report_*_step, process_breakdown_step), куда управление
    приходит через bot.register_next_step_handler в обход основного
    handle_message, поэтому проверку нужно повторить.

    Возвращает (user, None) при успехе или (None, текст_ошибки), если
    пользователя нужно остановить и отправить на /start.

    Этап 4, Блок 3/часть 3.1: сама проверка переведена на get_worker()
    (HTTP вместо прямого SELECT).
    Этап 4, Блок 3/часть 3.5: параметр `cursor` убран из сигнатуры —
    подчасти 3.2-3.4 уже вызывали функцию как `_require_registered_user
    (None, telegram_id)` (сам параметр не использовался с части 3.1), а
    часть 3.5 перевела последние вызовы, передававшие реальный `cursor`
    (handle_message), на тот же принцип. Все вызовы в файле обновлены
    одним заходом вместе с этой правкой — если найдёте где-то ещё
    двухаргументный вызов, это забытое место, а не альтернативная
    сигнатура."""
    try:
        user = get_worker(telegram_id)
    except requests.exceptions.RequestException:
        return None, _friendly_api_error_text()
    if user is None or not user["dolzhnost"] or not user["lesnichestvo"]:
        return None, "Похоже, регистрация не завершена. Напиши /start, чтобы продолжить."
    return user, None


# ------------------------------------------------------------- отчёт о работе ---
def process_report_kvartal_step(message, tip_raboty):
    """Шаг 1 пошагового отчёта: номер квартала. Принимаем только строку из
    одних цифр — никакого разбора свободного текста, чтобы не промахнуться
    с номером.

    Этап 4, Блок 3/часть 3.2: раньше здесь открывалось sqlite-соединение
    (get_db()) только ради cursor для _require_registered_user — сама
    проверка регистрации уже с части 3.1 ходит в backend по HTTP и cursor
    не использует (параметр в сигнатуре оставлен для мест, ещё не
    переведённых на 3.2, см. докстринг _require_registered_user), так что
    открывать локальное соединение здесь больше незачем."""
    telegram_id = str(message.from_user.id)
    user, error = _require_registered_user(telegram_id)
    if error:
        bot.reply_to(message, error)
        return

    kvartal = (message.text or "").strip()
    if not kvartal.isdigit():
        msg = bot.reply_to(
            message,
            "Номер квартала должен быть числом. Введи, например: 139",
        )
        bot.register_next_step_handler(msg, process_report_kvartal_step, tip_raboty)
        return

    msg = bot.reply_to(
        message,
        "Введи номер(а) выдела через запятую (например: 15 или 1,2,3):",
    )
    bot.register_next_step_handler(msg, process_report_vydel_step, tip_raboty, kvartal)


def process_report_vydel_step(message, tip_raboty, kvartal):
    """Шаг 2: список номеров выделов, через запятую или пробел. Каждый
    элемент должен быть числом — если хоть один не число, переспрашиваем
    целиком (не пытаемся угадать, что имел в виду рабочий)."""
    raw = (message.text or "").strip()
    parts = [p for p in re.split(r"[,\s]+", raw) if p]
    if not parts or not all(p.isdigit() for p in parts):
        msg = bot.reply_to(
            message,
            "Не понял номера выделов. Введи только числа через запятую, "
            "например: 15 или 1,2,3",
        )
        bot.register_next_step_handler(msg, process_report_vydel_step, tip_raboty, kvartal)
        return

    msg = bot.reply_to(
        message,
        "Прикрепи фото (например, страницу тетрадки), либо напиши «нет», "
        "если фото не будет:",
    )
    bot.register_next_step_handler(msg, process_report_photo_step, tip_raboty, kvartal, parts)


def process_report_photo_step(message, tip_raboty, kvartal, vydels):
    """Шаг 3 (последний): фото или текстовый комментарий/«нет». Перед
    сохранением проверяем, не отправлял ли этот же рабочий точно такой же
    отчёт (кв/выд/тип работы) совсем недавно (см. DEDUP_WINDOW_MINUTES) —
    если да, переспрашиваем подтверждение (process_report_confirm_duplicate),
    вместо того чтобы молча создать дубль. Иначе отчёт сразу уходит в
    raw_reports на проверку лесничему — см. докстринг модуля.

    Этап 4, Блок 3/часть 3.2: проверка дубля и сохранение отчёта переведены
    с прямых обращений к db.py по общему sqlite-соединению
    (find_recent_duplicate_report/save_raw_report) на HTTP-вызовы
    (check_duplicate_report()/create_raw_report() выше) — локальное
    соединение (get_db()) здесь больше не открывается."""
    telegram_id = str(message.from_user.id)
    user, error = _require_registered_user(telegram_id)
    if error:
        bot.reply_to(message, error)
        return

    photo_path = download_photo(message)
    opisanie = None
    if not photo_path:
        text = (message.text or "").strip()
        if text and text.lower() not in ("нет", "-", "нету"):
            opisanie = text

    try:
        duplicate = check_duplicate_report(
            telegram_id, kvartal, vydels, tip_raboty, DEDUP_WINDOW_MINUTES,
        )
    except requests.exceptions.RequestException:
        bot.reply_to(message, _friendly_api_error_text())
        return

    if duplicate is not None:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.row(types.KeyboardButton(BTN_YES), types.KeyboardButton(BTN_NO))
        msg = bot.reply_to(
            message,
            f"⚠️ Похоже, ты уже отправлял такой же отчёт сегодня в "
            f"{duplicate['data_soobscheniya'].split()[-1]} (кв {kvartal}, "
            f"выд {', '.join(vydels)}, работа: {tip_raboty}) — он ещё "
            "не проверен лесничим. Отправить ещё один такой же?",
            reply_markup=markup,
        )
        bot.register_next_step_handler(
            msg, process_report_confirm_duplicate_step, tip_raboty, kvartal, vydels, photo_path, opisanie,
        )
        return

    try:
        create_raw_report(telegram_id, kvartal, vydels, tip_raboty, photo_path, opisanie)
    except requests.exceptions.RequestException:
        bot.reply_to(message, _friendly_api_error_text())
        return

    vydels_display = ", ".join(vydels)
    bot.reply_to(
        message,
        f"✅ Принято: кв {kvartal}, выд {vydels_display}, работа: {tip_raboty}.\n"
        "Отчёт передан лесничему на проверку.",
        reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
    )


def process_other_work_photo_step(message):
    """Упрощённый (однoшаговый) вариант process_report_photo_step для кнопки
    «📦 Другая работа»: без квартала/выдела — сразу фото или текстовый
    комментарий/«нет». Отчёт уходит в raw_reports с kvartal=None,
    vydels=None и tip_raboty='другая работа' (см. REPORT_BUTTON_TIP).
    Проверку на дубли (check_duplicate_report) здесь не делаем — без
    квартала/выдела сравнивать "тот же отчёт" не с чем.

    Этап 4, Блок 3/часть 3.2: сохранение отчёта переведено на HTTP
    (create_raw_report() выше) — локальное sqlite-соединение здесь больше
    не открывается."""
    telegram_id = str(message.from_user.id)
    user, error = _require_registered_user(telegram_id)
    if error:
        bot.reply_to(message, error)
        return

    photo_path = download_photo(message)
    opisanie = None
    if not photo_path:
        text = (message.text or "").strip()
        if text and text.lower() not in ("нет", "-", "нету"):
            opisanie = text

    try:
        create_raw_report(
            telegram_id, None, None, REPORT_BUTTON_TIP[BTN_OTHER_WORK], photo_path, opisanie,
        )
    except requests.exceptions.RequestException:
        bot.reply_to(message, _friendly_api_error_text())
        return

    bot.reply_to(
        message,
        "✅ Принято: другая работа.\nОтчёт передан лесничему на проверку.",
        reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
    )


def process_report_confirm_duplicate_step(message, tip_raboty, kvartal, vydels, photo_path, opisanie):
    """Ответ на переспрос про вероятный дубль (см. process_report_photo_step).
    'Да, отправить' — сохраняем отчёт как обычно; любой другой ответ —
    считаем отменой и ничего не пишем в raw_reports.

    Этап 4, Блок 3/часть 3.2: сохранение отчёта переведено на HTTP
    (create_raw_report() выше) — локальное sqlite-соединение здесь больше
    не открывается."""
    telegram_id = str(message.from_user.id)
    text = (message.text or "").strip()

    user, error = _require_registered_user(telegram_id)
    if error:
        bot.reply_to(message, error)
        return

    if text != BTN_YES:
        bot.reply_to(
            message,
            "Отменено, повторный отчёт не сохранён.",
            reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
        )
        return

    try:
        create_raw_report(telegram_id, kvartal, vydels, tip_raboty, photo_path, opisanie)
    except requests.exceptions.RequestException:
        bot.reply_to(message, _friendly_api_error_text())
        return

    vydels_display = ", ".join(vydels)
    bot.reply_to(
        message,
        f"✅ Принято: кв {kvartal}, выд {vydels_display}, работа: {tip_raboty}.\n"
        "Отчёт передан лесничему на проверку.",
        reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
    )


# ------------------------------------------------------------------- поломки ---
def process_breakdown_step(message):
    """Единственный шаг отчёта о поломке: свободный текст с описанием, что
    сломалось (не парсится — просто пересылается лесничему как есть,
    опционально с фото).

    Этап 4, Блок 3/часть 3.3: save_breakdown_report + get_lesnichiy_
    telegram_ids переведены с прямых обращений к db.py по общему
    sqlite-соединению на один HTTP-вызов (create_breakdown_report() выше)
    — локальное соединение (get_db()) здесь больше не открывается."""
    telegram_id = str(message.from_user.id)
    user, error = _require_registered_user(telegram_id)
    if error:
        bot.reply_to(message, error)
        return

    detail_text = (message.text or message.caption or "").strip()
    if not detail_text:
        msg = bot.reply_to(
            message,
            "Опиши текстом, что именно сломалось (например: 'потёк гидроцилиндр стрелы'):",
        )
        bot.register_next_step_handler(msg, process_breakdown_step)
        return

    photo_path = download_photo(message)
    try:
        result = create_breakdown_report(telegram_id, detail_text, photo_path)
    except requests.exceptions.RequestException:
        bot.reply_to(message, _friendly_api_error_text())
        return

    breakdown_id = result["id"]
    lesnichiy_ids = result["lesnichiy_telegram_ids"]

    bot.reply_to(
        message,
        "⚠️ Отчёт о поломке отправлен лесничему.",
        reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
    )

    if not lesnichiy_ids:
        return

    notify_text = (
        f"⚠️ ПОЛОМКА\n"
        f"{config.DOLZHNOSTI.get(user['dolzhnost'], user['dolzhnost'])}: {user['fio']}\n"
        f"Что сломалось: {detail_text}"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "➕ Добавить в служебные записки", callback_data=f"breakdown_add_{breakdown_id}"
        )
    )
    for chat_id in lesnichiy_ids:
        try:
            if photo_path:
                with open(photo_path, "rb") as f:
                    bot.send_photo(chat_id, f, caption=notify_text, reply_markup=markup)
            else:
                bot.send_message(chat_id, notify_text, reply_markup=markup)
        except Exception as e:
            # Например, лесничий ни разу не писал боту (Telegram не даёт
            # написать первым) — не роняем рассылку остальным из-за одного.
            print(f"❌ Не удалось уведомить лесничего {chat_id} о поломке: {e}")


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("breakdown_add_"))
def handle_breakdown_add_callback(call):
    """Лесничий нажал '➕ Добавить в служебные записки' под уведомлением о
    поломке — переносит её в sluzhebnye_zametki и редактирует исходное
    сообщение, чтобы кнопку нельзя было нажать дважды.

    Этап 4, Блок 3/часть 3.3: add_sluzhebnaya_zametka_from_breakdown
    переведена на HTTP (add_breakdown_to_notes() выше) — локальное
    sqlite-соединение здесь больше не открывается. На сетевую ошибку —
    не падение бота, а понятный текст лесничему через answer_callback_query
    (тот же принцип _friendly_api_error_text, что и в остальных
    обработчиках, но короче — Telegram ограничивает текст ответа на
    callback примерно 200 символами)."""
    id_part = call.data[len("breakdown_add_"):]
    try:
        breakdown_id = int(id_part)
    except ValueError:
        bot.answer_callback_query(call.id, "Не удалось разобрать поломку.")
        return

    try:
        zametka_id = add_breakdown_to_notes(breakdown_id)
    except requests.exceptions.RequestException:
        bot.answer_callback_query(call.id, "Сервер недоступен, попробуйте позже.")
        return

    if zametka_id is None:
        bot.answer_callback_query(call.id, "Эта поломка уже добавлена в записки.")
        return

    bot.answer_callback_query(call.id, "✅ Добавлено в служебные записки")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass


# ---------------------------------------------------------- служебные заметки ---
def _format_zametka_button_label(zametka):
    text = zametka["text"] or ""
    return (text[:35] + "…") if len(text) > 35 else text


def process_zametki_list(message):
    """Кнопка 'Служебные заметки' (только у лесничего) — список активных
    заметок с inline-кнопкой '✅ выполнено' под каждой.

    Этап 4, Блок 3/часть 3.3: list_active_sluzhebnye_zametki переведена на
    HTTP (get_active_zametki() выше) — локальное sqlite-соединение здесь
    больше не открывается."""
    try:
        zametki = get_active_zametki()
    except requests.exceptions.RequestException:
        bot.reply_to(message, _friendly_api_error_text())
        return

    if not zametki:
        bot.reply_to(message, "Активных служебных заметок нет 👍")
        return

    markup = types.InlineKeyboardMarkup()
    lines = ["🗒 Служебные заметки:"]
    for i, z in enumerate(zametki, start=1):
        lines.append(f"{i}. {z['text']}")
        markup.add(
            types.InlineKeyboardButton(
                f"✅ {_format_zametka_button_label(z)}", callback_data=f"zametka_done_{z['id']}"
            )
        )
    bot.reply_to(message, "\n".join(lines), reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("zametka_done_"))
def handle_zametka_done_callback(call):
    """Этап 4, Блок 3/часть 3.3: complete_sluzhebnaya_zametka переведена на
    HTTP (complete_zametka() выше) — локальное sqlite-соединение здесь
    больше не открывается."""
    id_part = call.data[len("zametka_done_"):]
    try:
        zametka_id = int(id_part)
    except ValueError:
        bot.answer_callback_query(call.id, "Не удалось разобрать заметку.")
        return

    try:
        done = complete_zametka(zametka_id)
    except requests.exceptions.RequestException:
        bot.answer_callback_query(call.id, "Сервер недоступен, попробуйте позже.")
        return

    if not done:
        bot.answer_callback_query(call.id, "Заметка уже закрыта или не найдена.")
        return

    bot.answer_callback_query(call.id, "Отмечено выполненным ✅")
    reply_markup = call.message.reply_markup
    if reply_markup and reply_markup.keyboard:
        new_rows = [[b for b in row if b.callback_data != call.data] for row in reply_markup.keyboard]
        new_rows = [row for row in new_rows if row]
        new_markup = types.InlineKeyboardMarkup()
        for row in new_rows:
            new_markup.row(*row)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=new_markup)
        except Exception:
            pass


# ---------------------------------------------------- отмена последнего отчёта ---
def process_cancel_last_report(message):
    """Кнопка '↩️ Отменить последний отчёт' — удаляет последний отчёт этого
    рабочего, если он ещё не проверен лесничим (status='на проверке' в
    raw_reports). Если лесничий уже успел его подтвердить (перенёс в
    completed_works) — отменить нельзя, отчёт уже не в raw_reports.

    Этап 4, Блок 3/часть 3.4: раньше здесь открывалось sqlite-соединение
    (get_db()) ради cursor для _require_registered_user и ради conn для
    get_last_raw_report_for_user — обе операции теперь ходят в backend по
    HTTP (get_worker() внутри _require_registered_user с части 3.1,
    get_last_report() ниже), открывать локальное соединение больше
    незачем."""
    telegram_id = str(message.from_user.id)
    user, error = _require_registered_user(telegram_id)
    if error:
        bot.reply_to(message, error)
        return

    try:
        last_report = get_last_report(telegram_id)
    except requests.exceptions.RequestException:
        bot.reply_to(message, _friendly_api_error_text())
        return

    if last_report is None:
        bot.reply_to(
            message,
            "Отменять нечего: либо ты ещё не отправлял отчётов, либо "
            "последний уже проверен лесничим.",
            reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
        )
        return

    vydels_display = last_report["vydels"] or "—"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row(types.KeyboardButton(BTN_YES), types.KeyboardButton(BTN_NO))
    msg = bot.reply_to(
        message,
        f"Отменить этот отчёт?\nкв {last_report['kvartal']}, выд "
        f"{vydels_display}, работа: {last_report['tip_raboty']}, "
        f"отправлен {last_report['data_soobscheniya']}.",
        reply_markup=markup,
    )
    bot.register_next_step_handler(msg, process_cancel_last_report_confirm_step, last_report["id"])


def process_cancel_last_report_confirm_step(message, report_id):
    """Этап 4, Блок 3/часть 3.4: та же причина, что и в
    process_cancel_last_report — регистрация проверяется по HTTP,
    cancel_raw_report(conn, ...) заменена на cancel_report() (HTTP DELETE),
    локальное sqlite-соединение больше не открывается."""
    telegram_id = str(message.from_user.id)
    text = (message.text or "").strip()

    user, error = _require_registered_user(telegram_id)
    if error:
        bot.reply_to(message, error)
        return

    if text != BTN_YES:
        bot.reply_to(
            message, "Хорошо, отчёт оставлен как есть.",
            reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
        )
        return

    try:
        result = cancel_report(report_id, telegram_id)
    except requests.exceptions.RequestException:
        bot.reply_to(message, _friendly_api_error_text())
        return

    if not result["cancelled"]:
        bot.reply_to(
            message,
            "Не удалось отменить: отчёт уже проверен лесничим или не найден.",
            reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
        )
        return

    photo_path = result["photo_path"]
    if photo_path:
        try:
            os.remove(photo_path)
        except OSError:
            pass

    bot.reply_to(
        message, "↩️ Отчёт отменён.",
        reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
    )


# -------------------------------------------------------------- запрос остатка ---
def _format_vydel_display(vydel):
    """Приводит vydel к строке для показа пользователю: список ['17', '33']
    -> '17, 33', одиночное значение отображается как есть."""
    if isinstance(vydel, (list, tuple, set)):
        return ", ".join(str(v) for v in vydel)
    return str(vydel)


def _format_remaining_reply(kvartal, vydel, result):
    """Формирует текстовый ответ на запрос остатка лимита.

    Раньше показывал только остаток по наряду (result["remaining"]). Теперь
    источники разведены явно и подписаны, чтобы мастер не путал, откуда
    какая цифра, и понимал, сколько РЕАЛЬНО можно ещё заготовить:

        📋 Наряд   — то, что сам мастер (или офис с его слов) внёс в
                      приложение через наряды. Может отставать от жизни,
                      если наряд ещё не занесён.
        🛰 ЕГАИС    — последний импортированный в приложение снапшот
                      выгрузки ЕГАИС (см. save_egais_snapshot в raskhod.py).
                      Не всегда есть - если файл ЕГАИС ни разу не
                      загружали в приложении, будет "нет данных".
        ➡️ Можно ещё — главная цифра, ради которой мастер вообще спрашивает
                      остаток. Считается от БОЛЬШЕГО из двух факторов (см.
                      ostatok_safe в get_remaining_volumes_for_bot) - если
                      ЕГАИС показывает больше, чем наряд, остаток от одного
                      только наряда был бы завышен и мог привести к
                      перерубу на бумаге, даже если по факту всё верно.
    """
    from raskhod_v2 import _poroda_label  # локальный импорт, чтобы не тянуть его наверх файла без нужды

    lines = [f"🌲 Баланс по кв {kvartal} выд {_format_vydel_display(vydel)}"]
    grouped = result.get("grouped") or {}

    GROUP_LABELS = {"delovaya": "деловая", "drova": "дрова"}

    any_row = False
    for poroda in sorted(grouped):
        label = _poroda_label(poroda)
        poroda_lines = []

        for group in ("delovaya", "drova"):
            vals = grouped[poroda].get(group) or {}
            limit = vals.get("limit") or 0.0
            fakt_naryad = vals.get("fakt_naryad") or 0.0
            fakt_egais = vals.get("fakt_egais")
            ostatok_safe = vals.get("ostatok_safe")

            if not limit and not fakt_naryad and not fakt_egais:
                continue  # совсем нечего показывать по этой группе

            group_label = GROUP_LABELS[group]
            if not limit and (fakt_egais or fakt_naryad):
                # Порода/группа заготавливается (наряд или ЕГАИС это
                # показывают), а лимита на неё в МДО этой делянки нет
                # вообще — либо порода вне разрешённого перечня, либо
                # где-то перепутали делянку. Не должно теряться молча.
                poroda_lines.append(f"⚠️ {group_label}: лимита НЕТ в МДО этой делянки, но заготовка идёт!")

            poroda_lines.append(f"  {group_label} — лимит: {limit:g} м³")
            poroda_lines.append(f"    📋 Наряд: {fakt_naryad:g} м³")
            if fakt_egais is None:
                poroda_lines.append("    🛰 ЕГАИС: нет данных")
            else:
                egais_line = f"    🛰 ЕГАИС: {fakt_egais:g} м³"
                if abs(fakt_egais - fakt_naryad) > 0.1:
                    razn = fakt_egais - fakt_naryad
                    znak = "больше" if razn > 0 else "меньше"
                    egais_line += f" ⚠️ {znak} наряда на {abs(razn):g} м³"
                poroda_lines.append(egais_line)

            if ostatok_safe is not None:
                if ostatok_safe <= 0:
                    poroda_lines.append("    ➡️ Можно ещё: 0 м³ — лимит исчерпан")
                else:
                    poroda_lines.append(f"    ➡️ Можно ещё: {ostatok_safe:g} м³")
                fakt_effektivny = max(fakt_naryad, fakt_egais) if fakt_egais is not None else fakt_naryad
                if limit and fakt_effektivny > limit * 1.1:
                    poroda_lines.append("    ❗ Превышен лимит+10% — нужна объяснительная")

        if poroda_lines:
            lines.append(f"\n{label}")
            lines.extend(poroda_lines)
            any_row = True

    if not any_row:
        lines.append("Лимитов/остатков по данной делянке не найдено.")

    last_update = result.get("last_update")
    egais_imported_at = result.get("egais_imported_at")
    lines.append("")
    if last_update:
        line = f"🕒 Наряды актуальны на: {last_update.strftime('%d.%m.%Y %H:%M')}"
        if (datetime.now() - last_update).days > 7:
            line += " ⚠️ давно не обновлялись!"
        lines.append(line)
    else:
        lines.append("🕒 Наряды: ещё ни одного не внесено")

    if egais_imported_at:
        lines.append(f"🕒 ЕГАИС загружен в приложение: {egais_imported_at.strftime('%d.%m.%Y %H:%M')}")
    else:
        lines.append("🕒 ЕГАИС: файл ни разу не загружали в приложение — сверка недоступна")

    return "\n".join(lines)


def process_balance_step(message):
    """Второй шаг диалога 'Остатки на делянке' — рабочий вводит ТОЛЬКО
    номер квартала (текстом), а конкретный выдел/лесосека выбирается
    дальше нажатием inline-кнопки (см. handle_balance_callback).

    Этап 4, Блок 3/часть 3.4: регистрация проверяется по HTTP,
    get_active_delyanki_for_bot(conn, ...) заменена на get_active_delyanki()
    (HTTP GET /api/bot/delyanki) — локальное sqlite-соединение здесь
    больше не открывается. Список делянок теперь приходит как список
    JSON-словарей (не sqlite3.Row), поэтому lesoseka читается через
    row.get(...) вместо row["..."] с проверкой "in row.keys()"."""
    telegram_id = str(message.from_user.id)
    text = (message.text or "").strip()

    user, error = _require_registered_user(telegram_id)
    if error:
        bot.reply_to(message, error)
        return

    if not text.isdigit():
        bot.reply_to(
            message,
            "Не понял номер квартала. Напиши, пожалуйста, только число, например: 139.",
        )
        return
    kvartal = text

    try:
        delyanki = get_active_delyanki(kvartal)
    except requests.exceptions.RequestException:
        bot.reply_to(message, _friendly_api_error_text())
        return

    if not delyanki:
        bot.reply_to(message, f"В квартале {kvartal} нет активных делянок.")
        return

    markup = types.InlineKeyboardMarkup()
    for row in delyanki:
        vydel = row["vydel"]
        lesoseka = row.get("lesoseka_nomer")
        label = f"Выд. {vydel} (Лесосека {lesoseka})" if lesoseka else f"Выд. {vydel}"
        markup.add(
            types.InlineKeyboardButton(
                label, callback_data=_build_balance_callback_data(kvartal, vydel, lesoseka)
            )
        )

    bot.reply_to(message, f"Выбери делянку в квартале {kvartal}:", reply_markup=markup)


# Хранилище пар (kvartal, vydel, lesoseka), для которых прямой формат
# callback_data вида 'bal_{kvartal}_{vydel}_{lesoseka}' превысил бы лимит
# Telegram в 64 байта — в этом случае в кнопку кладётся короткий ключ
# 'balid_{short_id}', а сама пара живёт в памяти процесса (см.
# _build_balance_callback_data / handle_balance_callback). Это только
# страховка на крайний случай — в норме используется прямой формат.
_pending_balance_choices = {}


def _build_balance_callback_data(kvartal, vydel, lesoseka):
    """Формирует callback_data для inline-кнопки выбора делянки. Пытается
    использовать прямой человекочитаемый формат 'bal_{kvartal}_{vydel}_
    {lesoseka}' (удобно отлаживать логами апдейтов), но если он не
    укладывается в лимит Telegram на callback_data (64 байта — например,
    из-за необычно длинного номера лесосеки), откатывается на короткий
    сгенерированный ключ."""
    lesoseka_part = lesoseka if lesoseka else "-"
    direct = f"bal_{kvartal}_{vydel}_{lesoseka_part}"
    if len(direct.encode("utf-8")) <= 64:
        return direct

    short_id = uuid.uuid4().hex[:12]
    _pending_balance_choices[short_id] = (kvartal, vydel, lesoseka)
    return f"balid_{short_id}"


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith(("bal_", "balid_")))
def handle_balance_callback(call):
    """Обрабатывает нажатие inline-кнопки выбора делянки (см.
    process_balance_step): достаёт квартал/выдел/лесосеку из
    callback_data (либо из _pending_balance_choices для короткого
    формата 'balid_...') и отвечает остатком через
    get_remaining_volumes_for_bot/_format_remaining_reply.

    Этап 4, Блок 3/часть 3.4: в отличие от остальных функций этой
    подчасти, ЗДЕСЬ get_db() СОЗНАТЕЛЬНО ОСТАВЛЕН — get_remaining_volumes_
    for_bot не переводится на HTTP в этом заходе (см. подробное
    объяснение решения (б) у импорта `from raskhod import
    get_remaining_volumes_for_bot` в начале файла). Это единственное
    оставшееся прямое обращение бота к БД в файле после части 3.4."""
    bot.answer_callback_query(call.id)

    if call.data.startswith("balid_"):
        short_id = call.data[len("balid_"):]
        choice = _pending_balance_choices.pop(short_id, None)
        if choice is None:
            bot.send_message(call.message.chat.id, "Эта кнопка уже устарела, запроси остаток заново.")
            return
        kvartal, vydel, lesoseka = choice
    else:
        parts = call.data.split("_", 3)
        if len(parts) != 4:
            bot.send_message(call.message.chat.id, "Не удалось разобрать выбор делянки.")
            return
        _, kvartal, vydel, lesoseka_part = parts
        lesoseka = None if lesoseka_part == "-" else lesoseka_part

    conn = get_db()
    try:
        result = get_remaining_volumes_for_bot(conn, kvartal, vydel, lesoseka)
        if not result["found"]:
            bot.send_message(
                call.message.chat.id,
                f"Делянка кв {kvartal} выд {_format_vydel_display(vydel)} не найдена в базе.",
            )
            return
        bot.send_message(call.message.chat.id, _format_remaining_reply(kvartal, vydel, result))
    finally:
        conn.close()


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("taskdone_"))
def handle_taskdone_callback(call):
    """Обрабатывает нажатие inline-кнопки '✅ <задача>' под списком задач
    (см. BTN_TASKS в handle_message): отмечает задачу выполненной через
    complete_task_for_bot и убирает соответствующую кнопку из клавиатуры,
    чтобы не дать закрыть одну и ту же задачу дважды.

    Этап 4, Блок 3/часть 3.4: complete_task_for_bot(conn, ...) заменена на
    complete_task() (HTTP POST /api/bot/tasks/{id}/complete) — локальное
    sqlite-соединение здесь больше не открывается."""
    telegram_id = str(call.from_user.id)
    task_id_part = call.data[len("taskdone_"):]
    try:
        task_id = int(task_id_part)
    except ValueError:
        bot.answer_callback_query(call.id, "Не удалось разобрать задачу.")
        return

    try:
        done = complete_task(task_id, telegram_id)
    except requests.exceptions.RequestException:
        # answer_callback_query ограничен Telegram ~200 символами — текст
        # короче, чем _friendly_api_error_text() (тот же приём для
        # callback'ов, что уже применён в части 3.3).
        bot.answer_callback_query(call.id, "Не получилось связаться с сервером, попробуй ещё раз.")
        return

    if not done:
        bot.answer_callback_query(call.id, "Задача уже закрыта или не найдена.")
        return

    bot.answer_callback_query(call.id, "Отмечено как выполнено ✅")

    reply_markup = call.message.reply_markup
    if reply_markup and reply_markup.keyboard:
        new_rows = [
            [btn for btn in row if btn.callback_data != call.data]
            for row in reply_markup.keyboard
        ]
        new_rows = [row for row in new_rows if row]
        new_markup = types.InlineKeyboardMarkup()
        for row in new_rows:
            new_markup.row(*row)
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id, call.message.message_id, reply_markup=new_markup
            )
        except Exception:
            pass


# --------------------------------------------------------------------- таксация ---
def _format_taxation_reply(kvartal, vydel, card):
    """Формирует текстовый ответ с характеристикой выдела (таксационное
    описание). card — то, что вернула get_vydel_card."""
    field_labels = [
        ("kategoriya_lesov", "Категория лесов"),
        ("poroda", "Порода"),
        ("formula_sostava", "Состав"),
        ("vozrast", "Возраст"),
        ("bonitet", "Бонитет"),
        ("polnota", "Полнота"),
        ("zapas", "Запас, м3/га"),
        ("ploshad", "Площадь, га"),
        ("tip_lesa", "Тип леса"),
    ]
    lines = [f"📖 Таксационная карточка: кв {kvartal} выд {vydel}"]

    keys = card.keys() if hasattr(card, "keys") else card
    found_any = False
    for key, label in field_labels:
        if key in keys and card[key] not in (None, ""):
            lines.append(f"{label}: {card[key]}")
            found_any = True

    if not found_any:
        for key in keys:
            if card[key] not in (None, ""):
                lines.append(f"{key}: {card[key]}")

    return "\n".join(lines)


def process_taxation_step(message):
    """Второй шаг диалога 'Таксационные характеристики' — рабочий вводит
    квартал и выдел ОДНИМ сообщением через пробел (например: '139 15') —
    это единственный ввод в боте, где два значения ожидаются в одной
    строке, т.к. привязан к формату уже существующей карточки в базе.

    Этап 4, Блок 3/часть 3.4: регистрация проверяется по HTTP,
    get_vydel_card(conn, ...) заменена на get_taxation_card() — прямой
    своп на уже существующий GET /api/taxation/vydel (см. её докстринг) —
    локальное sqlite-соединение здесь больше не открывается."""
    telegram_id = str(message.from_user.id)
    text = (message.text or "").strip()

    user, error = _require_registered_user(telegram_id)
    if error:
        bot.reply_to(message, error)
        return

    numbers = re.findall(r"\d+", text)
    if len(numbers) < 2:
        bot.reply_to(
            message,
            "Не понял номер квартала и выдела. Напиши два числа через "
            "пробел, например: '139 15'.",
        )
        return
    kvartal, vydel = numbers[0], numbers[1]

    try:
        card = get_taxation_card(kvartal, vydel)
    except requests.exceptions.RequestException:
        bot.reply_to(message, _friendly_api_error_text())
        return

    if not card:
        bot.reply_to(
            message,
            f"Таксационная карточка для кв {kvartal} выд {vydel} не найдена в базе.",
        )
        return

    bot.reply_to(message, _format_taxation_reply(kvartal, vydel, card))


def _format_tasks_reply(tasks):
    """Формирует текстовый список задач для кнопки 'Мои задачи'."""
    if not tasks:
        return "На сегодня новых задач нет 👍"

    lines = ["📋 Твои задачи:"]
    for i, task in enumerate(tasks, start=1):
        opisanie = task["opisanie"] if task["opisanie"] else "(без описания)"
        created_at = task["created_at"] if "created_at" in task.keys() else None
        line = f"{i}. {opisanie}"
        if created_at:
            line += f" (от {created_at})"
        lines.append(line)

    return "\n".join(lines)


@bot.message_handler(content_types=["location"])
def handle_location(message):
    """Рабочий прислал геометку через скрепку Telegram ('Локация') — бот
    запоминает координаты в _pending_geo и ждёт следующее сообщение
    (текст/фото) как комментарий к этой точке (кнопка "📍 Добавить заметку
    на делянку" просто подсказывает мастеру/лесничему это сделать, сама
    геометка всё равно отправляется через скрепку — Telegram Bot API не
    даёт запросить локацию нажатием обычной кнопки).

    Этап 4, Блок 3/часть 3.5: рассмотрена и оставлена без изменений — эта
    функция не обращается к БД вообще, только кладёт координаты в
    _pending_geo (память процесса бота, не таблица); сохранение самой
    заметки происходит позже, в handle_message/handle_photo, когда придёт
    комментарий (см. save_geo_note() выше)."""
    telegram_id = str(message.from_user.id)
    lat = message.location.latitude
    lon = message.location.longitude
    _pending_geo[telegram_id] = {"lat": lat, "lon": lon}
    bot.send_message(
        message.chat.id,
        "📍 Геометка получена! Теперь отправь фото или напиши текстом комментарий к этой точке.",
    )


# ---------------------------------------------------------------- обработчики ---
@bot.message_handler(content_types=["text"])
def handle_message(message):
    telegram_id = str(message.from_user.id)
    text = message.text.strip()

    # --- Привязка комментария к ожидающей гео-метке (см. handle_location).
    # Этап 4, Блок 3/часть 3.5: _save_geo_note(cursor, ...) заменена на
    # save_geo_note() (HTTP POST /api/bot/geo-notes) — локальное
    # sqlite-соединение здесь больше не открывается. ---
    if telegram_id in _pending_geo:
        coords = _pending_geo.pop(telegram_id)
        try:
            save_geo_note(telegram_id, coords, text, None)
        except requests.exceptions.RequestException:
            bot.reply_to(message, _friendly_api_error_text())
            return
        bot.reply_to(message, "📍 Заметка успешно сохранена на карте!")
        return

    # --- "Другая работа" — отдельная, укороченная ветка: без квартала/
    # выдела, сразу запрашиваем фото. Проверяется ДО общей ветки
    # REPORT_BUTTON_TIP ниже, иначе "Другая работа" тоже попала бы в
    # трёхшаговый опрос (квартал → выдел → фото) наравне с обычными
    # видами работ ---
    if text == BTN_OTHER_WORK:
        # Этап 4, Блок 3/часть 3.5: локальное sqlite-соединение (get_db())
        # здесь больше не открывается — _require_registered_user уже с
        # части 3.1 не использует переданный cursor.
        user, error = _require_registered_user(telegram_id)
        if error:
            bot.reply_to(message, error)
            return
        msg = bot.reply_to(message, "Пришлите фото")
        bot.register_next_step_handler(msg, process_other_work_photo_step)
        return

    # --- Перехват кнопок с типом работы (своя работа роли или "Другая
    # работа") — запускает пошаговый опрос, см. process_report_kvartal_step.
    # Работает для ЛЮБОГО пользователя с этой кнопкой на клавиатуре,
    # независимо от роли, т.к. текст кнопки уникально определяет tip_raboty ---
    if text in REPORT_BUTTON_TIP:
        # Этап 4, Блок 3/часть 3.5: как и в блоке BTN_OTHER_WORK выше —
        # get_db() здесь больше не открывается.
        user, error = _require_registered_user(telegram_id)
        if error:
            bot.reply_to(message, error)
            return
        msg = bot.reply_to(message, "Введи номер квартала (только число):")
        bot.register_next_step_handler(msg, process_report_kvartal_step, REPORT_BUTTON_TIP[text])
        return

    if text == BTN_BREAKDOWN:
        # Этап 4, Блок 3/часть 3.5: как и выше — get_db() больше не открывается.
        user, error = _require_registered_user(telegram_id)
        if error:
            bot.reply_to(message, error)
            return
        msg = bot.reply_to(message, "Что сломалось? Опиши коротко, какая деталь/узел:")
        bot.register_next_step_handler(msg, process_breakdown_step)
        return

    if text == BTN_BALANCE:
        msg = bot.reply_to(message, "Введи номер квартала (только число):")
        bot.register_next_step_handler(msg, process_balance_step)
        return

    if text == BTN_TAXATION:
        msg = bot.reply_to(message, "Напиши номер квартала и выдела через пробел, например: '139 15'")
        bot.register_next_step_handler(msg, process_taxation_step)
        return

    if text == BTN_GEO_NOTE:
        bot.reply_to(
            message,
            "Пришли геометку через скрепку (📎 → Локация), а следующим "
            "сообщением — фото или комментарий к ней.",
        )
        return

    if text == BTN_ZAMETKI:
        process_zametki_list(message)
        return

    if text == BTN_CANCEL_LAST:
        process_cancel_last_report(message)
        return

    if text == BTN_TASKS:
        # Этап 4, Блок 3/часть 3.4: регистрация проверяется по HTTP,
        # get_tasks_for_bot(conn, ...) заменена на get_worker_tasks() (HTTP
        # GET /api/bot/tasks) — локальное sqlite-соединение здесь больше
        # не открывается.
        user, error = _require_registered_user(telegram_id)
        if error:
            bot.reply_to(message, error)
            return
        try:
            tasks = get_worker_tasks(telegram_id)
        except requests.exceptions.RequestException:
            bot.reply_to(message, _friendly_api_error_text())
            return
        if not tasks:
            bot.reply_to(message, "На сегодня новых задач нет 👍")
            return

        reply_text = _format_tasks_reply(tasks)
        markup = types.InlineKeyboardMarkup()
        for task in tasks:
            opisanie = task["opisanie"] if task["opisanie"] else "(без описания)"
            markup.add(
                types.InlineKeyboardButton(
                    text=f"✅ {opisanie[:25]}...",
                    callback_data=f"taskdone_{task['id']}",
                )
            )
        bot.reply_to(message, reply_text, reply_markup=markup)
        return

    # --- ни одна кнопка не совпала: проверяем регистрацию (/start её
    # запускает) и, если пользователь уже зарегистрирован, просто
    # напоминаем пользоваться кнопками — свободный текст больше не
    # разбирается как отчёт.
    # Этап 4, Блок 3/часть 3.5: как и во всех блоках выше — get_db() здесь
    # больше не открывается. ---
    user, error = _require_registered_user(telegram_id)

    if error:
        bot.reply_to(message, "Привет! Напиши /start, чтобы зарегистрироваться.")
        return

    bot.reply_to(
        message,
        "Пользуйся, пожалуйста, кнопками на клавиатуре ниже — так отчёт "
        "точно не потеряется и не будет разобран неправильно.",
        reply_markup=get_menu_for_dolzhnost(user["dolzhnost"]),
    )


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    """Фото вне пошагового опроса (message_handler для content_types
    'photo' не перехватывается register_next_step_handler автоматически
    для чисто текстовых шагов — но process_report_photo_step и
    process_breakdown_step регистрируются без ограничения content_types,
    поэтому реально сюда попадают только фото, присланные ВНЕ этих
    диалогов). Единственный сценарий, который стоит поддержать отдельно —
    фото как комментарий к геометке.

    Этап 4, Блок 3/часть 3.5: _save_geo_note(cursor, ...) заменена на
    save_geo_note() (HTTP POST /api/bot/geo-notes), как и в
    handle_message — локальное sqlite-соединение здесь больше не
    открывается. download_photo() не меняется (см. её докстринг) — это
    вызов Telegram Bot API и локальная запись файла на диск бота, а не
    обращение к нашему backend'у; в save_geo_note() уходит уже готовый
    photo_path."""
    telegram_id = str(message.from_user.id)

    if telegram_id in _pending_geo:
        coords = _pending_geo.pop(telegram_id)
        caption = (message.caption or "").strip()
        photo_path = download_photo(message)
        try:
            save_geo_note(telegram_id, coords, caption, photo_path)
        except requests.exceptions.RequestException:
            bot.reply_to(message, _friendly_api_error_text())
            return
        bot.reply_to(message, "📍 Заметка успешно сохранена на карте!")
        return

    bot.reply_to(
        message,
        "Чтобы прикрепить фото к отчёту, сначала нажми кнопку нужного типа "
        "работы и дойди до шага «пришли фото» — так оно точно попадёт "
        "в нужный отчёт.",
    )


# ---------------------------------------------------------------- запуск ---
def run_bot() -> None:
    """Точка запуска бота, которую использует TelegramBotWorker.run()
    (main.py) — миграция схемы БД + бесконечный поллинг.

    Этап 4, Блок 3/часть 3.5: рассмотрена и СОЗНАТЕЛЬНО ОСТАВЛЕНА без
    изменений. После частей 3.1-3.5 backend (app/main.py, startup-событие)
    и так уже вызывает migrate_schema сам при своём собственном запуске
    (app/database.py) — казалось бы, дублирующий вызов здесь можно убрать.
    Не убран по двум причинам:
      1. handle_balance_callback (часть 3.4, сознательное исключение —
         см. её докстринг) по-прежнему открывает СВОЁ собственное
         sqlite-соединение через get_db() к тому же DB_PATH — бот не
         может полагаться исключительно на то, что backend когда-нибудь
         успел стартовать первым и создать схему, если оба процесса
         запускаются независимо (например, порядок автозапуска служб
         Windows, Блок 4, не гарантирован сам по себе без явной
         настройки зависимостей служб).
      2. migrate_schema идемпотентна (CREATE TABLE IF NOT EXISTS +
         добавление недостающих колонок, см. db.py) — повторный вызов
         подряд из двух процессов ничего не портит и не теряет данные,
         только читает PRAGMA table_info и, возможно, делает несколько
         ALTER TABLE на уже добавленные колонки (no-op). Цена вызова на
         каждый старт бота (не на каждое сообщение) пренебрежимо мала.
    Если часть 3.4 будет пересмотрена и get_remaining_volumes_for_bot
    тоже переедет на HTTP (вариант "а", не выбранный там) — тогда у бота
    не останется ни одного прямого обращения к БД, и этот вызов можно
    будет убрать вместе с DB_PATH/get_db()/import sqlite3 одним заходом."""
    _migration_conn = sqlite3.connect(DB_PATH)
    migrate_schema(_migration_conn)
    _migration_conn.close()
    bot.infinity_polling()


if __name__ == "__main__":
    bot_info = bot.get_me()
    print(f"✅ УРА! Пропуск сработал! Бот @{bot_info.username} успешно подключен к матрице Telegram!")
    print("Ожидаю отчеты от лесорубов...")
    run_bot()
