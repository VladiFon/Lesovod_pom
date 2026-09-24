# Backend "Цифровой помощник лесовода" — что тут и куда

Это НОВЫЙ, параллельный слой поверх вашей бизнес-логики. `main.py` и
`screens/` вашего десктоп-приложения НЕ трогались вообще.

## Структура архива

```
backend/
├── requirements.txt
├── README.md                        # этот файл
├── legacy/
│   ├── delyanka.py                  # ВАША КОПИЯ — как есть, не менялась
│   ├── db.py                        # ВАША КОПИЯ — как есть, не менялась
│   ├── akt_generator.py             # ВАША КОПИЯ — как есть, не менялась
│   ├── listok_generator.py          # ВАША КОПИЯ — как есть, не менялась
│   ├── tehkarta_generator.py        # ВАША КОПИЯ — как есть, не менялась
│   ├── spravka_generator.py         # ИЗМЕНЁН — теперь заполняет официальный бланк
│   │                                 #   templates/spravka_shablon.docx (см. spravka_template_fill.py)
│   ├── spravka_template_fill.py     # НОВЫЙ — точечное заполнение ячеек spravka_shablon.docx
│   ├── osvidetelstvovanie_generator.py  # ИЗМЕНЁН — координаты ячеек под новый официальный
│   │                                 #   бланк akt_osvidetelstvovaniya_shablon.docx
│   ├── raskhod.py                   # ВАША КОПИЯ — как есть, не менялась (использует telegram_bot.py)
│   ├── raskhod_v2.py                 # НОВЫЙ — единый источник истины, см. "Второй этап" ниже
│   ├── secrets_store.py              # НОВЫЙ — секреты (Gemini/OpenRouter/Telegram), см. "Второй этап" ниже
│   ├── taksatsia_parser.py          # ВАША КОПИЯ — как есть, не менялась
│   ├── mdo_parser.py                # ВАША КОПИЯ — как есть, не менялась
│   ├── forest_map.py                # ВАША КОПИЯ — как есть, не менялась
│   ├── config.py                    # НОВЫЙ — headless-замена вашего QSettings-конфига
│   ├── webext.py                    # НОВЫЙ — таблицы documents/background_tasks
│   ├── lch_map.json                 # УЖЕ ЗАПОЛНЕН реальными значениями из вашего config.py
│   └── templates/                   # УЖЕ СОДЕРЖИТ реальные бланки и geojson из вашего проекта
│       ├── akt_expl_shablon.xlsx
│       ├── akt_zash_shablon.xlsx
│       ├── akt_osvidetelstvovaniya_shablon.docx  # официальный бланк акта
│       ├── spravka_shablon.docx     # НОВЫЙ — официальный бланк справки
│       ├── listok_shablon.xlsx
│       ├── raskhod_shablon.xlsx
│       ├── tehkarta_shablon.docx
│       ├── map_kvartala.geojson
│       ├── map_vydela.geojson
│       └── templates/proba_rubki_uhoda_template.docx
├── storage/
│   ├── documents/                   # сюда backend пишет сгенерированные файлы
│   └── uploads/                     # временные загрузки (МДО/таксация/ЕГАИС)
└── app/
    ├── __init__.py
    ├── main.py                      # точка входа FastAPI
    ├── legacy_bridge.py             # добавляет legacy/ в sys.path
    ├── database.py                  # подключение к SQLite + init схемы
    ├── paths.py                     # пути storage/
    ├── doc_tasks.py                 # общие хелперы генерации документов
    ├── aggregations.py              # НОВЫЙ — агрегация для spravka/osvidetelstvovanie
    └── routers/
        ├── __init__.py
        ├── delyanki.py
        ├── taxation.py
        ├── lesokultury.py
        ├── raskhod.py
        ├── inspection.py
        ├── map.py
        ├── documents.py
        ├── settings.py
        └── tasks.py
```

## ВАЖНО — два отступления от исходного ТЗ (нужно ваше решение)

1. **Таблица `documents`** просилась "в db.py". `db.py` — 2230 строк; вместо
   правки этого файла таблицы `documents`/`background_tasks` вынесены в
   отдельный **новый** модуль `legacy/webext.py` — та же БД, тот же
   `sqlite3.connect`, просто `CREATE TABLE IF NOT EXISTS`. Работает
   идентично. Если нужно физически в `db.py` — напишите, пришлю точечный
   patch на 2 места.
2. `legacy/config.py` — **новый** файл (в оригинале конфиг был на
   QSettings/PySide6, на сервере это не поднять). Экспортирует те же
   имена (`APP_DIR`, `RESOURCE_DIR`, `DB_PATH`, `LCH_MAP`), что и
   `delyanka.py`/`mdo_parser.py`/`forest_map.py` ожидают от `config`.

## Уже сделано в этой сборке (из lesovod_project_fixed_v5.zip)

- Реальные бланки (`akt_expl_shablon.xlsx`, `akt_zash_shablon.xlsx`,
  `listok_shablon.xlsx`, `raskhod_shablon.xlsx`, `tehkarta_shablon.docx`)
  и geojson-карты (`map_kvartala.geojson`, `map_vydela.geojson`) уже
  лежат в `legacy/templates/`.
- `legacy/lch_map.json` уже заполнен реальными номерами лесничеств из
  вашего `config.py`.
- `STANDARD_CHECKLIST_ITEMS` в `app/routers/inspection.py` — реальный
  список из `screens/inspection/screen.py`.
- `lesovod.db` из архива весит 0 байт (пустая заготовка) — НЕ
  переносился. Backend сам создаст свою `legacy/lesovod.db` при первом
  запуске (`init_db()` в `main.py`).

## Второй этап — доведены до ума 2 пункта из AUDIT.md

### 1. Дублирование raskhod.py ↔ screens/raskhod/ — решено

Аудит явно указывал: "стоит явно проверить, какой из двух источников
считать единственно верным... вероятно, версия в screens/raskhod/".
Проверено и решено:

- `legacy/raskhod_v2.py` — НОВЫЙ файл, точная построчная выгрузка (через
  `sed` по диапазону строк, без единого ручного изменения символа) чистой
  логики из вашего `screens/raskhod/balance.py` + `egais.py` + `export.py`
  (у всех трёх — общая продублированная шапка с мёртвыми
  `PySide6`/`from screens.plots import PlotsScreen` импортами, которые НЕ
  используются ни в одной функции — проверено `grep`; их отсутствие не
  меняет поведение). Проверено импортом и полным end-to-end прогоном
  (лимиты/наряды/баланс/Справка/Акт освидетельствования).
- `app/routers/raskhod.py` и `app/routers/inspection.py` переключены на
  `raskhod_v2` — теперь используют настоящий `compute_balance` (с полями
  `limit_110`/`ostatok_110`, которых не было в старом корневом
  `raskhod.py`) и настоящие `compute_sortiment_totals_multi`/
  `compute_sortiment_limit_fakt_totals` вместо приблизительной
  реализации, которая раньше была в `app/aggregations.py`
  (файл оставлен для истории, помечен как устаревший, больше не
  используется).
- Старый `legacy/raskhod.py` (корневой) **не удалён и не менялся** —
  `telegram_bot.py` продолжает импортировать функции из него. Веб-backend
  и бот временно используют два модуля с почти идентичной логикой.
  **Рекомендация на будущее:** при следующем изменении бизнес-логики
  расхода леса вносите правку в `raskhod_v2.py` и переносите её отдельно
  в `raskhod.py` для бота (или, лучше, переведите `telegram_bot.py` на
  `raskhod_v2` тоже — тогда останется единственный файл).

### 2. Секреты — вынесены из QSettings

- `legacy/secrets_store.py` — НОВЫЙ модуль. Хранит ключ Gemini API, ключ
  OpenRouter API и токен Telegram-бота в `legacy/secrets.json` с правами
  доступа `0o600` (только владелец процесса), вместо `QSettings`.
  `mask_api_key()` перенесена дословно из вашего `config.py` — маскировка
  в API выглядит так же, как в десктоп-версии (проверено: тот же формат
  `AQ.Ab8••••••••azsg`).
- Новые эндпоинты в `app/routers/settings.py`:
  `GET /api/settings/secrets` (только маскированный статус, `null` если не
  задан), `POST /api/settings/secrets/{gemini|openrouter|telegram}`,
  `DELETE /api/settings/secrets/{gemini|openrouter|telegram}`. Ни один
  эндпоинт никогда не возвращает секрет в открытом виде.
- При старте (`main.py`) секреты подгружаются в `os.environ` процесса —
  то же поведение, что `config.apply_saved_api_key_to_env()` в десктопе.
- **Важно для продакшена:** файл `secrets.json` хранит значения ОТКРЫТЫМ
  ТЕКСТОМ, права `0o600` — это базовая защита ОС, не шифрование. Для
  реального продакшена замените `_load()`/`_save()` в `secrets_store.py`
  на настоящий секрет-менеджер (Vault/AWS Secrets Manager/K8s Secrets) —
  остальной интерфейс (9 функций) можно не менять.

## Осталось сделать руками

1. Если у вас есть РЕАЛЬНАЯ заполненная база (не пустышка из архива) —
   задайте переменную окружения `LESOVOD_DB_PATH` с путём к ней перед
   запуском (см. команды ниже), иначе backend создаст пустую.

2. `forest_map.py` требует `geopandas`/`shapely`/`pyproj`/`fiona`/`folium`/
   `pandas` (см. `requirements.txt` — раскомментируйте нужные строки и
   поставьте, если будете использовать `/api/map/*`).

3. Ещё не тронутые пункты AUDIT.md (для следующего этапа, если понадобится):
   - `screens/calendar/screen.py` и весь `screens/ai_log/` держат SQL
     прямо в Qt-классах — их логику нужно сначала вынести в `db.py`/
     сервисный модуль, только потом оборачивать роутером.
   - В схеме БД почти нет `FK`/`ON DELETE CASCADE`/`NOT NULL` — целостность
     сейчас держится на дисциплине кода приложения, а не на самой БД.
   - Файловые артефакты (документы/фото/сканы) хранятся как пути на диске
     — для реального продакшена стоит объектное хранилище (S3-совместимое)
     вместо локальной ФС.

## Запуск — см. отдельный список команд в чате
