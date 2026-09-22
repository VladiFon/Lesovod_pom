# -*- coding: utf-8 -*-
"""
Headless-замена config.py для backend-слоя.

В десктоп-приложении config.py хранил настройки через QSettings (PySide6)
и требует запущенного Qt-окружения — на сервере это не работает и не
нужно. Этот файл — НОВЫЙ, специально написанный для FastAPI-бэкенда,
экспортирует ТЕ ЖЕ имена, которые импортируют существующие модули
(delyanka.py, mdo_parser.py, forest_map.py):

    delyanka.py:    from config import RESOURCE_DIR
    forest_map.py:  from config import LCH_MAP, RESOURCE_DIR
    mdo_parser.py:  import config      (использует config.APP_DIR)

Внутренняя логика delyanka.py/mdo_parser.py/forest_map.py НЕ менялась —
меняется только источник настроек (переменные окружения + JSON-файл
вместо QSettings).

Ничего не меняет в оригинальном config.py десктоп-приложения — тот файл
остаётся как есть для main.py/screens/.

Этап 4 доработки (Блок 3, часть 2 — авторизация телеграм-бота) добавил
два токена, тоже через переменные окружения (см. находку №2 аудита
Блока 3 — в этом headless config.py токен-функций из десктопной версии
не было вообще, `telegram_bot.py` падал бы при импорте):

    get_telegram_bot_token()
        — токен самого бота у @BotFather (`telebot.TeleBot(TOKEN)`).
          В десктоп-версии хранился через QSettings; здесь — переменная
          окружения LESOVOD_TELEGRAM_BOT_TOKEN (см. deploy/.env.example).
    get_bot_service_token()
        — ДРУГОЙ токен: которым сам процесс бота представляется этому
          backend'у (Authorization: Bearer ...), чтобы HTTP-эндпоинты
          под require_permission(...) видели его как служебную роль
          "bot" (app/auth.py, webext.PERMISSIONS). Переменная окружения
          LESOVOD_BOT_SERVICE_TOKEN. Не путать с токеном выше — тот
          нужен для разговора бота с Telegram, этот — для разговора
          бота с нашим же backend'ом.
"""
import json
import os
from pathlib import Path

# Папка приложения на сервере: сюда пишутся lesovod.db (если не переопределён
# отдельно), lch_map.json, soffice_path.txt (см. mdo_parser.py) и т.п.
# По умолчанию — рядом с этим файлом; переопределяется LESOVOD_APP_DIR.
APP_DIR = os.environ.get("LESOVOD_APP_DIR") or str(Path(__file__).resolve().parent)
Path(APP_DIR).mkdir(parents=True, exist_ok=True)

# Папка с шаблонами документов (*.xlsx/*.docx бланки) и geojson-картами
# (map_kvartala.geojson/map_vydela.geojson).
# ВАЖНО: скопируйте сюда все бланки из старого приложения (RESOURCE_DIR
# десктоп-версии) — без них генераторы документов будут падать с
# FileNotFoundError (см. akt_generator.AKT_EXPL_TEMPLATE,
# listok_generator.LISTOK_TEMPLATE, tehkarta_generator.TEHKARTA_TEMPLATE,
# raskhod.RASKHOD_TEMPLATE и geojson-файлы для forest_map.py).
# Переопределяется LESOVOD_RESOURCE_DIR.
RESOURCE_DIR = os.environ.get("LESOVOD_RESOURCE_DIR") or str(Path(APP_DIR) / "templates")
Path(RESOURCE_DIR).mkdir(parents=True, exist_ok=True)

# Путь к базе SQLite, которую использует backend (db.py/delyanka.py/raskhod.py
# и т.д. работают с обычным sqlite3.connect(DB_PATH)).
# Переопределяется LESOVOD_DB_PATH — например, чтобы указать на ту же базу,
# которой пользуется десктоп-приложение.
DB_PATH = os.environ.get("LESOVOD_DB_PATH") or str(Path(APP_DIR) / "lesovod.db")

# LCH_MAP: {"название лесничества": "номер лесничества (num_lch)"} — тот же
# справочник, что был python-словарём прямо в исходном config.py; здесь
# читается из lch_map.json, чтобы не хардкодить его в коде backend'а.
# Скопируйте содержимое LCH_MAP из оригинального config.py в этот JSON-файл
# (APP_DIR/lch_map.json), например:
#   {"Болбасовское": "1", "Аслановичское": "2"}
# Если файла нет — LCH_MAP пуст, карта леса (forest_map.py) будет
# недоступна, пока файл не создан.
_LCH_MAP_PATH = Path(APP_DIR) / "lch_map.json"
if _LCH_MAP_PATH.exists():
    with open(_LCH_MAP_PATH, encoding="utf-8") as _f:
        LCH_MAP = json.load(_f)
else:
    LCH_MAP = {}


# ============================================================================
#   Этап 4 доработки, Блок 3/часть 2 — токены телеграм-бота (см. докстринг
#   модуля выше). Оба — простые переменные окружения, а не файл/QSettings:
#   бот на сервере — процесс, который стартует через тот же deploy/run_server-
#   like сценарий (Блок 4), где .env уже парсится построчно в окружение —
#   ничего нового изобретать не пришлось.
# ============================================================================
def get_telegram_bot_token() -> str | None:
    """Токен бота у @BotFather. None, если LESOVOD_TELEGRAM_BOT_TOKEN не
    задана — вызывающий код (telegram_bot.py) должен сам решить, что
    делать (сейчас — падать с понятным RuntimeError, см. его исходник)."""
    return os.environ.get("LESOVOD_TELEGRAM_BOT_TOKEN") or None


def get_bot_service_token() -> str | None:
    """Токен, которым процесс бота авторизуется перед этим backend'ом
    (Authorization: Bearer <токен>) — см. app/auth.py:get_current_user_optional.
    None, если LESOVOD_BOT_SERVICE_TOKEN не задана — в этом случае служебная
    роль "bot" в принципе недостижима ни для какого запроса (безопасно по
    умолчанию: сравнение с None никогда не проходит, а не "сравнение с
    пустой строкой", которое мог бы случайно пройти запрос без заголовка)."""
    return os.environ.get("LESOVOD_BOT_SERVICE_TOKEN") or None


def get_map_import_service_token() -> str | None:
    """Токен для QGIS-моста ("Лесовод-мост" — отдельный плагин, публикует
    контуры лесосек из ГИСлесхоз в Лесовод, см. POST /api/map/import-layer
    и DELETE /api/map/import-layers/{batch_id}). Раньше эти два эндпоинта
    были вообще без авторизации — пока сервер был виден только внутри
    локальной сети, это было терпимо, но после публикации через Cloudflare
    Tunnel (16.09.2026) сервер стал виден из интернета целиком, и открытая
    ручка приёма произвольных файлов на карту стала реальной дырой, не
    гипотетической.

    Сознательно ОТДЕЛЬНЫЙ токен от get_bot_service_token(), а не
    переиспользование одного и того же — QGIS-плагин и Telegram-бот это
    разные доверенные клиенты с разным временем жизни (бот работает
    постоянно, плагин публикует по кнопке раз в какое-то время); одним
    токеном на двоих нельзя было бы отозвать доступ одному, не сломав
    другого. Тот же принцип "безопасно по умолчанию", что и в
    get_bot_service_token() — None, если переменная окружения не задана,
    роль "map_import" в этом случае недостижима."""
    return os.environ.get("LESOVOD_MAP_IMPORT_SERVICE_TOKEN") or None


# ============================================================================
#   Должности рабочих (lesorub_directory.dolzhnost) — используются
#   telegram_bot.py для регистрации и построения меню под роль
#   (get_dolzhnost_menu/get_menu_for_dolzhnost/ROLE_REPORT_BUTTON).
#
#   ВНИМАНИЕ (реконструкция): в этом headless config.py эти константы
#   отсутствовали вовсе (в отличие от APP_DIR/RESOURCE_DIR/LCH_MAP выше,
#   которые докстринг файла явно обещал перенести) — из-за этого
#   telegram_bot.py падал при импорте с AttributeError. Оригинальный
#   десктопный config.py, где эти значения были определены исходно, в
#   этот экспорт не входит, поэтому ключи ниже восстановлены по текстам
#   комментариев в самом telegram_bot.py (там, где он описывает бизнес-
#   логику по ролям) и по единственному месту в этом экспорте, где
#   значение должности захардкожено буквально — db.py:1639
#   (`dolzhnost='лесничий'`), что и подтверждает регистр/написание для
#   лесничего. Остальные ключи (лесовод/тракторист/харвестерщик/
#   вальщик/мастер леса/помощник лесничего) НИГДЕ БОЛЬШЕ в экспорте не
#   встречаются буквально — т.е. это правдоподобная, но не подтверждённая
#   напрямую реконструкция. Если в базе lesorub_directory.dolzhnost уже
#   есть зарегистрированные рабочие с другим написанием этих слов —
#   они попадут в ветку "должность не распознана" в get_menu_for_dolzhnost
#   молча (без ошибки/краша), поэтому Владу стоит сверить эти значения с
#   `SELECT DISTINCT dolzhnost FROM lesorub_directory;` на живой базе
#   перед тем как полагаться на них для уже зарегистрированных рабочих.
# ============================================================================
DOLZHNOST_LESOVOD = "лесовод"
DOLZHNOST_TRAKTORIST = "тракторист"
DOLZHNOST_HARVESTER = "харвестерщик"
DOLZHNOST_VALSCHIK = "вальщик"
DOLZHNOST_MASTER_LESA = "мастер леса"
DOLZHNOST_POMOSHNIK_LESNICHEGO = "помощник лесничего"
DOLZHNOST_LESNICHIY = "лесничий"  # подтверждено буквально в db.py:1639

# key -> подпись на кнопке при регистрации (см. get_dolzhnost_menu) —
# порядок словаря определяет порядок кнопок.
DOLZHNOSTI = {
    DOLZHNOST_LESOVOD: "Лесовод",
    DOLZHNOST_TRAKTORIST: "Тракторист",
    DOLZHNOST_HARVESTER: "Харвестерщик",
    DOLZHNOST_VALSCHIK: "Вальщик",
    DOLZHNOST_MASTER_LESA: "Мастер леса",
    DOLZHNOST_POMOSHNIK_LESNICHEGO: "Помощник лесничего",
    DOLZHNOST_LESNICHIY: "Лесничий",
}

# Должности, у которых в меню дополнительно есть кнопка "⚠️ Поломка"
# (см. get_menu_for_dolzhnost) — трактористы и харвестерщики (техника),
# не вальщик (ручной инструмент).
DOLZHNOSTI_S_POLOMKOY = {DOLZHNOST_TRAKTORIST, DOLZHNOST_HARVESTER}

# Должности с "руководящим" меню (остатки/таксация/геозаметка вместо
# кнопки отчёта по своей работе) — мастер леса, помощник лесничего,
# лесничий; у лесничего дополнительно "Служебные заметки".
DOLZHNOSTI_MASTER_URODNYA = {
    DOLZHNOST_MASTER_LESA,
    DOLZHNOST_POMOSHNIK_LESNICHEGO,
    DOLZHNOST_LESNICHIY,
}


def get_api_base_url() -> str:
    """Базовый URL backend'а (FastAPI/uvicorn), к которому обращается бот
    (telegram_bot.py:API_BASE_URL) через requests.Session — например,
    "http://localhost:8000". Бот и backend — два отдельных процесса на
    одной машине (см. deploy/run_bot.bat и deploy/run_server.bat), бот
    всегда ходит на локальный uvicorn, не наружу через Caddy.

    Переопределяется целиком через LESOVOD_API_BASE_URL (если backend
    слушает не на localhost — например, отдельная машина/контейнер).
    По умолчанию собирается из LESOVOD_PORT (тот же порт, что слушает
    run_server.bat/uvicorn, см. .env.example) — так оба .env-значения не
    расходятся между собой без явной необходимости."""
    explicit = os.environ.get("LESOVOD_API_BASE_URL")
    if explicit:
        return explicit
    port = os.environ.get("LESOVOD_PORT") or "8000"
    return f"http://localhost:{port}"
