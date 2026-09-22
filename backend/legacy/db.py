# -*- coding: utf-8 -*-
"""
Создаёт локальную базу SQLite и загружает в неё данные из таксационного описания.
Схема:
  lesnichestvo(id, name)
  kvartal(id, lesnichestvo_id, nomer)
  vydel(id, kvartal_id, nomer, ploshad, kategoriya_lesov, podkategoriya_lesov,
        kl_tovarnosti, tip_lesa, tlu, bonitet, polnota, zapas_na_ga_raw,
        osobaya_zemlya, is_forested, lesnye_kultury,
        podlesok, podrost, tselevaya_poroda, ptg, povrezhdenie, primechaniya)
  sostav(id, vydel_id, poroda, dolya, vozrast, vysota, diametr, poryadok)
"""
import sqlite3
import json
import re
from datetime import datetime
from taksatsia_parser import extract_lines, parse, to_rows, Record
SCHEMA = """
CREATE TABLE IF NOT EXISTS lesnichestvo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS kvartal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesnichestvo_id INTEGER NOT NULL REFERENCES lesnichestvo(id),
    nomer INTEGER NOT NULL,
    UNIQUE(lesnichestvo_id, nomer)
);
CREATE TABLE IF NOT EXISTS vydel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kvartal_id INTEGER NOT NULL REFERENCES kvartal(id),
    nomer TEXT NOT NULL,
    ploshad TEXT,
    kategoriya_lesov TEXT,
    podkategoriya_lesov TEXT,
    kl_tovarnosti TEXT,
    tip_lesa TEXT,
    tlu TEXT,
    bonitet TEXT,
    polnota TEXT,
    zapas_na_ga TEXT,
    osobaya_zemlya TEXT,
    is_forested INTEGER,
    lesnye_kultury INTEGER,
    podlesok TEXT,
    podrost TEXT,
    tselevaya_poroda TEXT,
    ptg TEXT,
    povrezhdenie TEXT,
    primechaniya TEXT,
    -- === НИЖЕ: колонки, добавленные под парсер v2 (taksatsia_parser.Record) ===
    tip_obekta TEXT,          -- тип_объекта: 'Лес' / категория нелесных земель / метка типа культур
    sostav_formula TEXT,      -- состав: склеенная формула главного яруса, напр. '6Е4С'
    yarus INTEGER,            -- ярус выдела (1 обычный; 4 несомкн.культуры; спецкоды 6/9/13 и т.п.)
    vozrast_let REAL,
    vysota_m REAL,
    diametr_sm REAL,
    klass_vozrasta REAL,      -- класс_возраста (стр. A, поле 'Кл')
    gruppa_vozrasta REAL,     -- группа_возраста (стр. B, поле 'Гр')
    tip_tlu TEXT,             -- тип_тлу: 'tip_lesa + tlu' одной строкой
    prizhivaemost_pct REAL,   -- приживаемость_pct — для яруса=4 (несомкн.культуры) вместо polnota
    g_a REAL,
    g_b REAL,
    zapas_na_vydele REAL,     -- запас_на_выделе (суммарный, стр. B), в отличие от zapas_na_ga
    po_a REAL, t_a REAL, suh_a REAL, zah_a REAL,
    po_b REAL, t_b REAL, suh_b REAL, zah_b REAL,
    dop_yarusy_json TEXT,     -- JSON-список доп. ярусов (подрост/сухостой/сохран.ярус), структурно
    zametki TEXT,             -- ВСЕ свободнотекстовые заметки склеены через ' | ' (полный аудит-след)
    flag_proverki TEXT,       -- флаг_проверки — что парсер v2 просит перепроверить вручную
    syraya_stroka_a TEXT,     -- сырая_строка_A — для сверки с оригиналом
    syraya_stroka_b TEXT,     -- сырая_строка_B
    UNIQUE(kvartal_id, nomer)
);
CREATE TABLE IF NOT EXISTS sostav (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vydel_id INTEGER NOT NULL REFERENCES vydel(id),
    poryadok INTEGER,
    yarus TEXT,
    poroda TEXT,
    dolya INTEGER,
    vozrast TEXT,
    vysota TEXT,
    diametr TEXT
);
CREATE INDEX IF NOT EXISTS idx_vydel_lookup ON vydel(kvartal_id, nomer);
CREATE TABLE IF NOT EXISTS delyanka (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT,
    data_akta TEXT,
    prichiny TEXT,
    vrediteli TEXT,
    meropriyatiya TEXT,
    sroki_rubki TEXT,
    polnota_zhivyh TEXT,
    preduprezhdenie TEXT,
    krasnaya_kniga_meropriyatiya TEXT,
    predsedatel_dolzhnost TEXT,
    predsedatel_fio TEXT,
    chleny_json TEXT,
    listok_obnaruzhil_data TEXT,
    listok_obnaruzhil_dolzhnost TEXT,
    listok_obnaruzhil_fio TEXT,
    listok_proveril_data TEXT,
    listok_proveril_dolzhnost TEXT,
    listok_proveril_fio TEXT,
    listok_namechaemoe_meropriyatie TEXT,
    listok_reshenie_data TEXT,
    listok_reshenie_dolzhnost TEXT,
    listok_reshenie_fio TEXT,
    listok_zaklyuchenie_text TEXT,
    nomer_lesorubochnogo_bileta TEXT,
    data_lesorubochnogo_bileta TEXT,
    data_tehkarty TEXT,
    god_tehkarty TEXT,
    sostavil_dolzhnost TEXT,
    sostavil_fio TEXT,
    utverdil_dolzhnost TEXT,
    utverdil_fio TEXT,
    podrost_ploshad TEXT,
    podrost_tys_sht TEXT,
    gotovnost_komissiya_json TEXT,
    data_gotovnosti TEXT,
    master_lesa_fio TEXT,
    brigadir_fio TEXT,
    status TEXT DEFAULT 'черновик',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS komissiya_preset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT UNIQUE NOT NULL,
    predsedatel_dolzhnost TEXT,
    predsedatel_fio TEXT,
    chleny_json TEXT,
    obnaruzhil_dolzhnost TEXT,
    obnaruzhil_fio TEXT,
    proveril_dolzhnost TEXT,
    proveril_fio TEXT,
    reshenie_dolzhnost TEXT,
    reshenie_fio TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS listok_komissiya_preset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT UNIQUE NOT NULL,
    obnaruzhil_dolzhnost TEXT,
    obnaruzhil_fio TEXT,
    proveril_dolzhnost TEXT,
    proveril_fio TEXT,
    reshenie_dolzhnost TEXT,
    reshenie_fio TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS tehkarta_komissiya_preset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT UNIQUE NOT NULL,
    sostavil_dolzhnost TEXT,
    sostavil_fio TEXT,
    utverdil_dolzhnost TEXT,
    utverdil_fio TEXT,
    master_lesa_fio TEXT,
    brigadir_fio TEXT,
    tehkarta_chleny_json TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS delyanka_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delyanka_id INTEGER NOT NULL REFERENCES delyanka(id),
    poryadok INTEGER,
    lesxoz TEXT,
    lesnichestvo TEXT,
    kvartal TEXT,
    vydel TEXT,
    lesoseka_nomer TEXT,
    kategoriya_lesov TEXT,
    ploshad TEXT,
    zapas_na_ga TEXT,
    vyrubaemyy_zapas TEXT,
    proishozhdenie TEXT,
    sostav TEXT,
    vozrast TEXT,
    polnota TEXT,
    tip_lesa TEXT,
    bonitet TEXT,
    krasnaya_kniga TEXT DEFAULT '-',
    mdo_source_file TEXT,
    mdo_raw_json TEXT,
    abris_image_path TEXT,
    abris_coords_json TEXT,
    ispolnitel_fio TEXT,
    ispolnitel_viber_id TEXT,
    status_rabot TEXT DEFAULT 'ожидает',
    data_vypolneniya TEXT
);
-- Этап 3 плана оптимизации: get_delyanka_items_batch()/get_delyanka_items()
-- фильтруют именно по delyanka_id — без индекса это полный скан таблицы.
CREATE INDEX IF NOT EXISTS idx_delyanka_item_delyanka_id ON delyanka_item(delyanka_id);
-- Справочник работников (лесорубов) для интеграции с Viber/Telegram-ботом
CREATE TABLE IF NOT EXISTS lesorub_directory (
    viber_id TEXT PRIMARY KEY,
    fio TEXT NOT NULL,
    dolzhnost TEXT,
    -- лесничество рабочего, выбранное один раз при регистрации кнопкой
    -- (см. LCH_MAP в app.py) — больше не извлекается из текста отчёта
    lesnichestvo TEXT
);
-- Буфер входящих заявок из Telegram-бота: сюда попадают отчёты, которые
-- не удалось однозначно сопоставить с плановой delyanka_item (неплановые
-- виды работ вроде рубок ухода, свободный текст, нераспознанные номера,
-- фото без подписи и т.п.). Лесничий разбирает их вручную.
CREATE TABLE IF NOT EXISTS raw_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ispolnitel_viber_id TEXT,
    ispolnitel_fio TEXT,
    kvartal TEXT,
    vydels TEXT,
    raw_text TEXT,
    data_soobscheniya TEXT,
    status TEXT DEFAULT 'на проверке',
    photo_path TEXT,
    -- доп. детали (кол-во рейсов, объём, примечания), вписанные рабочим
    -- на шаге "фото/комментарий" пошагового опроса бота (telegram_bot.py),
    -- либо лесничим вручную при разборе
    opisanie TEXT,
    -- тип работы — теперь определяется однозначно самой кнопкой меню,
    -- которую нажал рабочий (telegram_bot.py: REPORT_BUTTON_TIP), а не
    -- угадывается ИИ, поэтому приходит уже готовым и просто отображается
    -- при разборе на экране "Журнал ИИ" (screens/ai_log/)
    tip_raboty TEXT
);
-- Независимая база выполненных работ из Telegram-бота: сюда попадает
-- ЛЮБАЯ работа (посадка, осветление, рубка и т.д.), которую боту удалось
-- разобрать (номер квартала, выдела и тип работы) — без привязки
-- к плановой delyanka_item.
CREATE TABLE IF NOT EXISTS completed_works (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_vypolneniya TEXT,
    ispolnitel_fio TEXT,
    kvartal TEXT,
    vydel TEXT,
    tip_raboty TEXT,
    photo_path TEXT,
    lesnichestvo TEXT,
    -- доп. детали (кол-во рейсов, объём, примечания) — см. raw_reports.opisanie
    opisanie TEXT,
    -- должность исполнителя на момент одобрения записи (screens/ai_log/
    -- screen_completed.py: approve_and_transfer) — берётся из
    -- lesorub_directory.dolzhnost по ФИО и сохраняется отдельной колонкой,
    -- чтобы фильтр по должности на вкладке "Выполненные" не требовал JOIN
    dolzhnost TEXT
);
CREATE TABLE IF NOT EXISTS raskhod_naryad (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delyanka_id INTEGER NOT NULL REFERENCES delyanka(id),
    item_id INTEGER NOT NULL REFERENCES delyanka_item(id),
    data TEXT,
    nomer_naryada TEXT,
    ploshad TEXT,
    primechanie TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Этап 3 плана оптимизации: compute_balance()/compute_balance_batch()
-- фильтруют/джойнят именно по item_id — без индекса это полный скан.
CREATE INDEX IF NOT EXISTS idx_raskhod_naryad_item_id ON raskhod_naryad(item_id);

CREATE TABLE IF NOT EXISTS raskhod_pozitsiya (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    naryad_id INTEGER NOT NULL REFERENCES raskhod_naryad(id),
    poroda TEXT,
    sortiment TEXT,
    obyom REAL
);
-- Этап 3 плана оптимизации: JOIN raskhod_pozitsiya.naryad_id = raskhod_naryad.id
-- в compute_balance()/compute_balance_batch() — без индекса на каждый наряд
-- полный скан raskhod_pozitsiya.
CREATE INDEX IF NOT EXISTS idx_raskhod_pozitsiya_naryad_id ON raskhod_pozitsiya(naryad_id);
-- Задачи, назначаемые рабочему (кнопка 'Мои задачи' в Telegram-боте).
-- telegram_id — тот же идентификатор, что хранится в lesorub_directory.viber_id.
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    telegram_id TEXT,
    opisanie TEXT,
    status TEXT DEFAULT 'активна',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Гео-заметки: точки на местности, присланные рабочим через геометку в
-- Telegram-боте (см. handle_location/_pending_geo/_save_geo_note), с
-- необязательным текстовым комментарием и/или фото — выводятся отдельным
-- слоем на Живую карту (generate_forest_map в app.py).
CREATE TABLE IF NOT EXISTS geo_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id TEXT,
    lat REAL,
    lon REAL,
    note_text TEXT,
    photo_path TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Самостоятельный слой карты, загруженный импортом из QGIS (GeoJSON/
-- Shapefile) или экспорта "Лесной страж" (см. legacy/map_import.py,
-- app/routers/map.py: /api/map/import-layer) — рисуется на Живой карте
-- ОТДЕЛЬНЫМ слоем поверх кварталов/выделов и НЕ создаёт делянки (в
-- отличие от старого поведения /api/delyanki/import-geo). batch_id
-- группирует все объекты одной загрузки одного файла — по нему слой
-- убирается с карты целиком одним действием.
CREATE TABLE IF NOT EXISTS imported_map_layer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    layer_name TEXT,
    lesnichestvo TEXT,
    kvartal TEXT,
    vydel TEXT,
    nazvanie TEXT,
    properties_json TEXT,
    geom_geojson TEXT NOT NULL,
    source_format TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Склады (места хранения/отгрузки древесины) — точки на Живой карте,
-- добавляются и удаляются вручную по координатам (см. legacy/sklad.py,
-- app/routers/map.py: /api/map/sklady). Не привязаны к лесничеству —
-- показываются на карте все сразу, независимо от того, какое
-- лесничество сейчас выбрано (склад — не часть таксации/делянок, а
-- инфраструктура, которая может обслуживать несколько лесничеств).
CREATE TABLE IF NOT EXISTS sklad (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    comment TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Независимые пробы рубок ухода (экран "Рубки ухода" / OsvetlenieScreen).
-- Полностью отвязаны от delyanka/delyanka_item — участок описывается
-- только своими кварталом/выделом (как обычный текст, а не FK), поэтому
-- пробу можно создать и без делянки главного пользования. kvartal/vydel/
-- ploshad_vydela/ploshad_proby/data_zamera вынесены отдельными колонками
-- для быстрого отображения в списке слева (см. list_uhody_proby); весь
-- остальной набор полей ведомости (лесничество, состав, полнота, вид/
-- способ рубки, комиссия, строки таблицы перечёта, итоги расчёта) хранится
-- одним JSON-словарём в data_json, чтобы не пересоздавать таблицу при
-- каждом добавлении нового поля ведомости.
CREATE TABLE IF NOT EXISTS uhody_proby (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kvartal TEXT,
    vydel TEXT,
    ploshad_vydela REAL,
    ploshad_proby REAL,
    data_zamera TEXT,
    data_json TEXT,
    completed_at TEXT,
    ispolniteli_json TEXT DEFAULT '[]',
    lesokultury_uchastok_ids_json TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Пресеты комиссии экрана "Рубки ухода" (C.3 плана) — отдельная сущность
-- от komissiya_preset/listok_komissiya_preset/tehkarta_komissiya_preset:
-- ведомость перечёта укладок хвороста хранит троих перечётчиков + одного
-- проверяющего (должность+ФИО), а не председателя/членов комиссии, поэтому
-- переиспользование чужой таблицы пресетов смешало бы разные по смыслу
-- формы. В отличие от osvidetelstvovanie_komissiya_preset (UPSERT по
-- nazvanie) здесь пресеты адресуются integer id — так проще для
-- GET/POST/DELETE /api/uhody/komissiya-presets (см. app/routers/uhody.py).
CREATE TABLE IF NOT EXISTS osvetlenie_komissiya_preset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT UNIQUE NOT NULL,
    perechetchik_1 TEXT,
    perechetchik_2 TEXT,
    perechetchik_3 TEXT,
    proveril_doljnost TEXT,
    proveril_fio TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Текущая погодная сводка для дашборда/оценки пожарной опасности.
-- Одна актуальная строка (id=1) — не история, а "текущий снимок",
-- обновляемый вручную или интеграцией с внешним API погоды.
CREATE TABLE IF NOT EXISTS weather_current (
    id INTEGER PRIMARY KEY,
    temperature REAL,
    humidity INTEGER,
    wind_speed REAL,
    wind_dir TEXT,
    fire_danger_class INTEGER,
    fire_danger_text TEXT,
    updated_at TEXT
);
-- Служебные заметки лесничего (экран "Журнал ИИ" / Telegram-бот, кнопка
-- "Служебные заметки" у должности лесничий). Заметка либо создаётся
-- вручную лесничим (source='вручную'), либо автоматически из принятой
-- поломки техники (source='поломка', см. breakdown_reports ниже —
-- callback-кнопка "Добавить в служебные записки" в telegram_bot.py).
-- Выполненные заметки не удаляются, а помечаются status='выполнена' и
-- просто пропадают из активного списка в боте/на экране.
CREATE TABLE IF NOT EXISTS sluzhebnye_zametki (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    source TEXT DEFAULT 'вручную',
    ispolnitel_fio TEXT,
    telegram_id TEXT,
    status TEXT DEFAULT 'активна',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Отчёты о поломке техники от тракториста/харвестерщика (кнопка
-- "⚠️ Поломка" в telegram_bot.py). При отправке бот сразу рассылает
-- этот отчёт всем пользователям с dolzhnost='лесничий' из
-- lesorub_directory вместе с inline-кнопкой "Добавить в служебные
-- записки" (callback breakdown_add_<id>) — по нажатию создаётся строка
-- в sluzhebnye_zametki (source='поломка') и сюда пишется её id.
CREATE TABLE IF NOT EXISTS breakdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id TEXT,
    fio TEXT,
    dolzhnost TEXT,
    detail_text TEXT,
    photo_path TEXT,
    status TEXT DEFAULT 'новое',
    zametka_id INTEGER REFERENCES sluzhebnye_zametki(id),
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Рабочий календарь (экран "Рабочий календарь") — задачи лесничего,
-- которые легко потерять в рутине: разовые ("подать заявку на..." к
-- конкретной дате) и повторяющиеся с разной периодичностью (раз в месяц/
-- квартал/полгода/год, либо "сезонные" — привязанные к диапазону дат
-- внутри года, например период лесопосадки). recurrence — тип
-- периодичности ('once'/'monthly'/'quarterly'/'semiannual'/'annual'/
-- 'seasonal'), recurrence_config_json — параметры под конкретный тип (см.
-- calendar_tasks.py: RECURRENCE_*). Сама таблица хранит только ШАБЛОН
-- задачи, не список всех прошлых/будущих дат выполнения — конкретная
-- "текущая" дата выполнения вычисляется на лету (calendar_tasks.compute_status),
-- а факт выполнения конкретного периода — в calendar_completions ниже.
CREATE TABLE IF NOT EXISTS calendar_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    recurrence TEXT NOT NULL DEFAULT 'once',
    recurrence_config_json TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Факт выполнения ОДНОГО периода задачи calendar_tasks. period_key —
-- дата-строка (YYYY-MM-DD) того конкретного срока, который был закрыт —
-- для разовой задачи это единственная её дата, для повторяющейся — дата
-- очередного наступившего срока (см. calendar_tasks.compute_status). Как
-- только наступает следующий период с ДРУГИМ period_key, задача снова
-- считается невыполненной — отметки не нужно и нельзя "погасить" заранее
-- на будущее.
CREATE TABLE IF NOT EXISTS calendar_completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES calendar_tasks(id),
    period_key TEXT NOT NULL,
    note TEXT,
    completed_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(task_id, period_key)
);
-- Экран "Архив документов" (screens/archive/) — этап F: ручной архиватор
-- без ИИ-распознавания. Один документ = один файл (скан/фото/PDF) +
-- вручную заполненные название/тип/дата/теги.
CREATE TABLE IF NOT EXISTS archive_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    doc_type TEXT,
    doc_date TEXT,
    tags TEXT,
    file_path TEXT,
    added_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Этап B плана доработок: план заготовки на месяц вводится ЛЕСНИЧИМ вручную
-- (столбики "план" на графике "Обзор заготовки" дашборда) — реального
-- источника плана по месяцам в БД нет, а delyanka_item.obyom (как
-- предполагалось раньше) физически не существует как колонка.
-- period — 'YYYY-MM'. Рабочее допущение (открытый вопрос плана): план
-- задаётся по хозяйству в целом, а не по делянкам/породам отдельно.
CREATE TABLE IF NOT EXISTS harvest_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period TEXT UNIQUE NOT NULL,
    plan_obyom REAL NOT NULL,
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Экран авторизации при входе (без пароля — просто фиксирует, что ФИО/
-- должность/лесничество уже один раз указаны, и это не нужно спрашивать
-- заново при каждом следующем запуске). Специально таблица В САМОЙ БД
-- (а не только в QSettings, где эти же поля дублируются для
-- автоподстановки в документы, см. config.get_lesnichiy_data()) — чтобы
-- сброс на "нового человека за этим компьютером" делался одной понятной
-- командой (DELETE FROM app_login;) прямо в lesovod.db, а не поиском по
-- реестру Windows/файлам конфигурации QSettings.
CREATE TABLE IF NOT EXISTS app_login (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    fio TEXT NOT NULL,
    dolzhnost TEXT,
    lesnichestvo TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- ==========================================================================
--   ЭКРАН "АКТЫ ОСВИДЕТЕЛЬСТВОВАНИЯ"
-- ==========================================================================
-- Комиссия для акта освидетельствования лесосеки — отдельный пресет (не
-- переиспользуем komissiya_preset "Акта обследования расстроенных лесных
-- насаждений": это семантически другой документ и другая комиссия, пусть
-- даже структура полей совпадает — смешение привело бы к тому, что смена
-- состава для одного акта тихо ломала бы другой).
-- С правки "пресет вводимых данных акта" (по просьбе пользователя: не
-- перепечатывать одну и ту же организационную информацию для каждого
-- акта) пресет расширен помимо состава комиссии — сохраняет ВСЕ поля
-- акта, которые обычно не меняются от делянки к делянке (область/район,
-- представитель лесхоза/лесопользователя, способ рубки/учёта/очистки,
-- руководитель). Поля, которые меняются при каждом осмотре (дата акта,
-- номер документа о полномочиях, измеренная площадь/подрост, нарушения,
-- заявления, заключение), в пресет не входят — их и так нужно вводить
-- заново на каждую делянку.
CREATE TABLE IF NOT EXISTS osvidetelstvovanie_komissiya_preset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT UNIQUE NOT NULL,
    predsedatel_dolzhnost TEXT,
    predsedatel_fio TEXT,
    chleny_json TEXT,
    oblast_rayon TEXT,
    predstavitel_lesxoza_dolzhnost TEXT,
    predstavitel_lesxoza_fio TEXT,
    lesopolz_organizatsiya TEXT,
    lesopolz_dolzhnost TEXT,
    lesopolz_fio TEXT,
    sign_lesopolz_dolzhnost TEXT,
    sign_lesopolz_fio TEXT,
    vid_osvidetelstvovaniya TEXT,
    sposob_rubki TEXT,
    sposob_ucheta TEXT,
    sposob_ochistki TEXT,
    rukovoditel_dolzhnost TEXT,
    rukovoditel_fio TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Чек-лист подготовки делянки к освидетельствованию ("были какие-нибудь
-- пометки для их выполнения" из плана доработок) — по делянке заводится
-- набор пунктов: часть — из готового типового списка
-- (STANDARD_CHECKLIST_ITEMS в screens/inspection/screen.py), часть может
-- добавить сам лесничий вручную (is_custom=1).
CREATE TABLE IF NOT EXISTS osvidetelstvovanie_checklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delyanka_id INTEGER NOT NULL REFERENCES delyanka(id),
    text TEXT NOT NULL,
    is_done INTEGER DEFAULT 0,
    is_custom INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- История сгенерированных актов освидетельствования по делянке. data_json
-- хранит СНИМОК всех вручную введённых при генерации полей (недоруб,
-- нарушения, сохранность подроста, представитель лесопользователя,
-- заявления и т.п.) — то, чего физически нет больше нигде в БД, потому
-- что это результат осмотра лесничим на месте, а не что-то вычислимое из
-- нарядов/МДО. file_path — путь к сгенерированному .docx на момент
-- создания (для повторного открытия; сам файл может быть позже перемещён
-- пользователем — это не считается ошибкой).
CREATE TABLE IF NOT EXISTS osvidetelstvovanie_acts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delyanka_id INTEGER NOT NULL REFERENCES delyanka(id),
    act_date TEXT,
    data_json TEXT,
    file_path TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- ==========================================================================
--   ЭКРАН "ЛЕСНЫЕ КУЛЬТУРЫ"
-- ==========================================================================
-- "Книга учёта лесных культур" в цифровом виде — ПОЛНОСТЬЮ независимый
-- список (НЕ выводится фильтром по таксации/vydel — по итогам обсуждения:
-- таксация обновляется нечасто и "стареет", а участки культур нужно
-- заводить и вести самим лесничим, как и делянки). Один участок культур
-- МОЖЕТ (необязательно) быть привязан к делянке, на месте которой он
-- заложен — просто для истории "тут рубили — тут посадили", без какой-либо
-- обязательной связи данных лимитов/баланса.
--
-- Модель мероприятий по факту сложнее, чем "инвентаризация на 1/3 год" —
-- см. ТКП "Правила лесовосстановления и лесоразведения" (пост. Минлесхоза
-- №13 от 03.08.2022, на основе Положения №80 от 19.12.2016): техническая
-- приёмка сразу после посадки, инвентаризация 1-го и 3-го года (полная, с
-- пробными площадями), агротехнический/химический уход (обычно
-- заканчивается на 2–4-й год — НЕ жёсткая цифра, "в зависимости от
-- состояния участка"), и ОТДЕЛЬНАЯ инвентаризация "с целью перевода в
-- покрытые лесом земли" — по факту достижения норматива (кол-во деревьев
-- главной породы на 1 га), а не по календарной дате. Поэтому — гибкий
-- журнал мероприятий (lesokultury_meropriyatiya) со свободным tip, а не
-- жёстко зашитые даты.
CREATE TABLE IF NOT EXISTS lesokultury_uchastok (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesnichestvo TEXT,
    kvartal TEXT,
    vydel TEXT,
    delyanka_id INTEGER REFERENCES delyanka(id),
    ploshad REAL,
    kategoriya_ploshadi TEXT,
    tlu TEXT,
    god_sozdaniya TEXT,
    metod_sozdaniya TEXT,
    glavnaya_poroda TEXT,
    sostav_formula TEXT,
    gustota_posadki REAL,
    normativ_perevoda REAL,
    status TEXT DEFAULT 'активен',
    primechaniya TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
-- Журнал мероприятий по участку лесных культур — техническая приёмка,
-- инвентаризация (1-й/3-й год/на перевод/внеплановая), агротехнический/
-- химический уход, дополнение, перевод в покрытые лесом земли, списание.
-- kolichestvo_na_ga и sostav_fakt заполняются для инвентаризаций (для
-- сравнения с lesokultury_uchastok.normativ_perevoda).
CREATE TABLE IF NOT EXISTS lesokultury_meropriyatiya (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uchastok_id INTEGER NOT NULL REFERENCES lesokultury_uchastok(id),
    tip TEXT NOT NULL,
    data TEXT,
    prizhivaemost_pct REAL,
    kolichestvo_na_ga REAL,
    sostav_fakt TEXT,
    primechaniya TEXT,
    proba_id INTEGER REFERENCES uhody_proby(id),
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- Снапшот последней загруженной в приложении выгрузки ЕГАИС ("Реестр
-- движения по складам", см. screens/raskhod/egais.py) - сохраняется при
-- каждом импорте в десктоп-приложении (screens/raskhod/screen.py
-- import_egais_file), чтобы этими же цифрами мог пользоваться отдельный
-- процесс Telegram-бота (telegram_bot.py), у которого нет доступа к
-- памяти запущенного окна десктоп-приложения. При каждом новом импорте
-- таблица полностью перезаписывается (см. save_egais_snapshot в
-- raskhod.py) - это именно СНАПШОТ последней выгрузки, а не история.
--
-- delovaya_obyom/drova_obyom - уже готовые итоговые суммы по породе (не
-- разбивка по КР/СР/МЛ - у ЕГАИС для деловой другая ось классификации,
-- сортность, а не размер - см. docstring _build_poroda_groups в screen.py),
-- ровно то же самое, что показывает колонка "Факт (ЕГАИС)" в десктопе.
CREATE TABLE IF NOT EXISTS egais_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imported_at TEXT NOT NULL,
    kvartal TEXT NOT NULL,
    vydel TEXT NOT NULL,
    poroda TEXT NOT NULL,
    delovaya_obyom REAL NOT NULL DEFAULT 0,
    drova_obyom REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_egais_snapshot_kv ON egais_snapshot(kvartal, vydel);

-- Полный ("лосслесс") снапшот той же выгрузки ЕГАИС, что и egais_snapshot
-- выше, но без потери детализации. egais_snapshot хранит только суммы
-- (delovaya_obyom/drova_obyom одним числом на породу) - этого достаточно
-- Telegram-боту (get_remaining_volumes_for_bot в raskhod.py), но НЕ
-- достаточно десктоп-экрану "Расход", которому нужна структура
-- porody[порода][сортимент]=объём (с реальными кодами сорта ЕГАИС, не
-- только "деловая"/"дрова") и список корректировок остатков (см.
-- docstring parse_egais_reestr в screens/raskhod/egais.py) - именно её
-- desktop-экран показывает пользователю и теряет при закрытии окна, если
-- хранить только агрегат. Одна строка = одна делянка (kvartal, vydel) за
-- ПОСЛЕДНИЙ импорт (снапшот, не история, как и у egais_snapshot) -
-- porody_json/korrektirovki_json хранят raw-структуру parse_egais_reestr()
-- как есть, сериализованную в JSON.
CREATE TABLE IF NOT EXISTS egais_snapshot_detail (
    kvartal TEXT NOT NULL,
    vydel TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    nazvanie_sklada TEXT NOT NULL DEFAULT '',
    porody_json TEXT NOT NULL DEFAULT '{}',
    korrektirovki_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (kvartal, vydel)
);

-- ------------------------------------------------------------------- --
--   Экран "Расход → ЕГАИС" — очереди на ручной разбор при импорте.
--   В отличие от egais_snapshot/egais_snapshot_detail выше (снимок ПОСЛЕДНЕЙ
--   выгрузки, полностью перезаписывается), эти три таблицы - ИСТОРИЯ:
--   копятся между импортами, у каждой строки свой статус разбора, чтобы
--   один и тот же вопрос не "всплывал" заново при каждом повторном
--   импорте того же периода. Наполняются в save_egais_snapshot()
--   (raskhod_v2.py), UNIQUE-ограничения там же используются как
--   "не создавать дубль, если этот вопрос уже был показан раньше".
-- ------------------------------------------------------------------- --

-- 1) Корректировки остатков ЕГАИС (doc_type = "Корректировка остатков") -
-- уже и так не приплюсовываются к объёму делянки при парсинге (см.
-- _parse_egais_reestr_impl), эта таблица только даёт им статус разбора,
-- чтобы лесничий видел, откуда взялась корректировка, и отметил её
-- просмотренной/проигнорированной.
CREATE TABLE IF NOT EXISTS egais_korrektirovka_review (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kvartal TEXT NOT NULL,
    vydel TEXT NOT NULL,
    poroda TEXT NOT NULL DEFAULT '',
    obyom REAL NOT NULL DEFAULT 0,
    data_dok TEXT NOT NULL DEFAULT '',
    nomer_dokumenta TEXT NOT NULL DEFAULT '',
    sklad TEXT NOT NULL DEFAULT '',
    sotrudnik TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',  -- new | resolved | ignored
    resolved_by TEXT,
    resolved_at TEXT,
    UNIQUE(kvartal, vydel, nomer_dokumenta, poroda, data_dok)
);
CREATE INDEX IF NOT EXISTS idx_egais_korrektirovka_review_status
    ON egais_korrektirovka_review(status);

-- 2) Строки ЕГАИС (любой тип - приход/расход/корректировка) с
-- квартал+выдел, которых нет ни в одной delyanka_item на момент импорта -
-- см. _find_unmatched_delyanki в raskhod_v2.py. last_seen_at обновляется
-- при каждом повторном импорте, пока запись не привязана/не
-- проигнорирована - это НЕ снимок, "new" может снова стать актуальной
-- проблемой в следующем месяце, если её не разобрали.
CREATE TABLE IF NOT EXISTS egais_unmatched_delyanka (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kvartal TEXT NOT NULL,
    vydel TEXT NOT NULL,
    nazvanie_sklada TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',  -- new | linked | ignored
    linked_delyanka_id INTEGER REFERENCES delyanka(id),
    resolved_by TEXT,
    resolved_at TEXT,
    UNIQUE(kvartal, vydel)
);
CREATE INDEX IF NOT EXISTS idx_egais_unmatched_delyanka_status
    ON egais_unmatched_delyanka(status);

-- 3) "Приход" на склад ФЛС (верхний склад на делянке) без явной пары
-- "Расход при внутреннем перемещении" на ПЛС того же документа - редкий,
-- но легальный случай полной цепочки складов (см. переписку с Владом,
-- 2026-09-03): Приход-ФЛС → Расход-ФЛС → Приход-ПЛС (тот же объём) →
-- Расход-ПЛС потребителю. Такие строки НЕ прибавляются автоматически к
-- объёму делянки при парсинге (см. _parse_egais_reestr_impl) - лесничий
-- сам решает на экране, отдельная это заготовка или уже учтённое
-- продолжение цепочки, которую позже (в этом же файле или в следующем
-- месяце) подхватит соответствующий приход на ПЛС.
CREATE TABLE IF NOT EXISTS egais_fls_prihod_review (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kvartal TEXT NOT NULL,
    vydel TEXT NOT NULL,
    poroda TEXT NOT NULL DEFAULT '',
    sortiment TEXT NOT NULL DEFAULT '',
    obyom REAL NOT NULL DEFAULT 0,
    data_dok TEXT NOT NULL DEFAULT '',
    nomer_dokumenta TEXT NOT NULL DEFAULT '',
    sklad TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    -- new | schitat_otdelno (отдельная заготовка, учесть в объём делянки) |
    -- privyazan_k_pls (часть цепочки - НЕ учитывать второй раз) | ignored
    status TEXT NOT NULL DEFAULT 'new',
    resolved_by TEXT,
    resolved_at TEXT,
    UNIQUE(kvartal, vydel, nomer_dokumenta, poroda)
);
CREATE INDEX IF NOT EXISTS idx_egais_fls_prihod_review_status
    ON egais_fls_prihod_review(status);
"""
def migrate_schema(conn):
    """Применяет схему и добавляет недостающие колонки в уже существующую
    базу (на случай, если база была создана более старой версией db.py)."""
    conn.executescript(SCHEMA)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(delyanka)").fetchall()}
    new_cols = {
        "listok_obnaruzhil_data": "TEXT", "listok_obnaruzhil_dolzhnost": "TEXT",
        "listok_obnaruzhil_fio": "TEXT",
        "listok_proveril_data": "TEXT", "listok_proveril_dolzhnost": "TEXT",
        "listok_proveril_fio": "TEXT",
        "listok_namechaemoe_meropriyatie": "TEXT",
        "listok_reshenie_data": "TEXT", "listok_reshenie_dolzhnost": "TEXT",
        "listok_reshenie_fio": "TEXT",
        "listok_zaklyuchenie_text": "TEXT",
        "nomer_lesorubochnogo_bileta": "TEXT",
        "data_lesorubochnogo_bileta": "TEXT",
        "data_tehkarty": "TEXT",
        "god_tehkarty": "TEXT",
        "sostavil_dolzhnost": "TEXT",
        "sostavil_fio": "TEXT",
        "utverdil_dolzhnost": "TEXT",
        "utverdil_fio": "TEXT",
        "podrost_ploshad": "TEXT",
        "podrost_tys_sht": "TEXT",
        "gotovnost_komissiya_json": "TEXT",
        "data_gotovnosti": "TEXT",
        "master_lesa_fio": "TEXT",
        "brigadir_fio": "TEXT",
        # Этап "Акты освидетельствования" — сроки берутся из лесорубочного
        # билета/технологической карты, но в МДО их нет и раньше нигде в
        # БД не хранились; вводятся вручную один раз в карточке делянки.
        # Нужны для дедлайна освидетельствования по ст. 72 Лесного кодекса
        # РБ (в течение 30 дней после окончания срока вывозки/билета).
        "srok_okonchaniya_zagotovki": "TEXT",
        "srok_okonchaniya_vyvozki": "TEXT",
    }
    for col, coltype in new_cols.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE delyanka ADD COLUMN {col} {coltype}")
    existing_item_cols = {row[1] for row in conn.execute("PRAGMA table_info(delyanka_item)").fetchall()}
    # Новые поля для делянки: абрис + учёт выполнения работ лесорубом (для Viber/Telegram-бота)
    new_item_cols = {
        "abris_image_path": "TEXT",
        "abris_coords_json": "TEXT",
        "ispolnitel_fio": "TEXT",
        "ispolnitel_viber_id": "TEXT",
        "status_rabot": "TEXT DEFAULT 'ожидает'",
        "data_vypolneniya": "TEXT",
        # Импорт границ делянки из QGIS (GeoJSON/Shapefile) — см.
        # app/routers/delyanki.py:import_delyanka_geometries. Хранит ровно
        # один GeoJSON-объект geometry (Polygon/MultiPolygon, WGS84
        # lon/lat) как текст — не привязано к map_vydela.geojson: контур
        # делянки может не совпадать с контуром выдела (делянка часто —
        # часть выдела). source_srid не храним отдельно: reprojection в
        # EPSG:4326 делается один раз при импорте, на входе.
        "geom_geojson": "TEXT",
    }
    for col, coltype in new_item_cols.items():
        if col not in existing_item_cols:
            conn.execute(f"ALTER TABLE delyanka_item ADD COLUMN {col} {coltype}")
    # Расширение пресета акта освидетельствования (см. комментарий над
    # CREATE TABLE osvidetelstvovanie_komissiya_preset выше) — на случай
    # базы, созданной до этой правки.
    existing_preset_cols = {
        row[1] for row in conn.execute(
            "PRAGMA table_info(osvidetelstvovanie_komissiya_preset)"
        ).fetchall()
    }
    new_preset_cols = {
        "oblast_rayon": "TEXT",
        "predstavitel_lesxoza_dolzhnost": "TEXT",
        "predstavitel_lesxoza_fio": "TEXT",
        "lesopolz_organizatsiya": "TEXT",
        "lesopolz_dolzhnost": "TEXT",
        "lesopolz_fio": "TEXT",
        "sign_lesopolz_dolzhnost": "TEXT",
        "sign_lesopolz_fio": "TEXT",
        "vid_osvidetelstvovaniya": "TEXT",
        "sposob_rubki": "TEXT",
        "sposob_ucheta": "TEXT",
        "sposob_ochistki": "TEXT",
        "rukovoditel_dolzhnost": "TEXT",
        "rukovoditel_fio": "TEXT",
    }
    for col, coltype in new_preset_cols.items():
        if col not in existing_preset_cols:
            conn.execute(f"ALTER TABLE osvidetelstvovanie_komissiya_preset ADD COLUMN {col} {coltype}")
    # raw_reports создаётся выше через executescript(SCHEMA) (CREATE TABLE IF NOT EXISTS),
    # но подстрахуемся явной проверкой — на случай очень старых баз/будущих правок SCHEMA.
    existing_tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "raw_reports" not in existing_tables:
        conn.execute(
            """CREATE TABLE raw_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ispolnitel_viber_id TEXT,
                ispolnitel_fio TEXT,
                kvartal TEXT,
                vydels TEXT,
                raw_text TEXT,
                data_soobscheniya TEXT,
                status TEXT DEFAULT 'на проверке',
                photo_path TEXT,
                opisanie TEXT
            )"""
        )
    # добавляем photo_path в raw_reports, если база была создана до этого пивота
    existing_raw_cols = {row[1] for row in conn.execute("PRAGMA table_info(raw_reports)").fetchall()}
    if "photo_path" not in existing_raw_cols:
        conn.execute("ALTER TABLE raw_reports ADD COLUMN photo_path TEXT")
    # добавляем opisanie в raw_reports (доп. детали — рейсы/объём/примечания),
    # если база была создана до этого добавления
    if "opisanie" not in existing_raw_cols:
        conn.execute("ALTER TABLE raw_reports ADD COLUMN opisanie TEXT")
    # добавляем tip_raboty в raw_reports (см. комментарий в SCHEMA выше),
    # если база была создана до перехода на пошаговый опрос без ИИ
    if "tip_raboty" not in existing_raw_cols:
        conn.execute("ALTER TABLE raw_reports ADD COLUMN tip_raboty TEXT")

    # независимая таблица выполненных работ (полностью отвязана от delyanka_item) —
    # создаём на случай, если база была создана до этого пивота
    if "completed_works" not in existing_tables:
        conn.execute(
            """CREATE TABLE completed_works (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_vypolneniya TEXT,
                ispolnitel_fio TEXT,
                kvartal TEXT,
                vydel TEXT,
                tip_raboty TEXT,
                photo_path TEXT,
                lesnichestvo TEXT,
                opisanie TEXT,
                dolzhnost TEXT
            )"""
        )
    # добавляем lesnichestvo в completed_works, если база была создана до этого
    # добавления — без этой колонки кварталы/выделы с одинаковыми номерами
    # в разных лесничествах "склеивались" на живой карте (работы дублировались)
    existing_cw_cols = {row[1] for row in conn.execute("PRAGMA table_info(completed_works)").fetchall()}
    if "lesnichestvo" not in existing_cw_cols:
        conn.execute("ALTER TABLE completed_works ADD COLUMN lesnichestvo TEXT")
    # добавляем opisanie в completed_works (доп. детали), если база была
    # создана до этого добавления
    if "opisanie" not in existing_cw_cols:
        conn.execute("ALTER TABLE completed_works ADD COLUMN opisanie TEXT")
    # ФИО лесничего, подтвердившего запись при переносе raw_reports ->
    # completed_works (screens/ai_log/screen_completed.py:approve_and_transfer) —
    # добавляем, если база была создана до этого добавления
    if "podtverdil_fio" not in existing_cw_cols:
        conn.execute("ALTER TABLE completed_works ADD COLUMN podtverdil_fio TEXT")
    # должность исполнителя (см. комментарий в SCHEMA выше) — добавляем,
    # если база была создана до этого добавления; нужна для фильтра
    # "Должность" на вкладке "Выполненные" (screens/ai_log/)
    if "dolzhnost" not in existing_cw_cols:
        conn.execute("ALTER TABLE completed_works ADD COLUMN dolzhnost TEXT")

    # Фаза 2 плана доработки веб-версии — отметка "выполнено" + исполнители
    # на независимой пробе рубок ухода (uhody_proby). completed_at (NULL =
    # не отмечена) и ispolniteli_json (снимок [{"id","fio","dolzhnost"}] на
    # момент отметки — не живой JOIN на sotrudniki: если сотрудника потом
    # переименуют/удалят/деактивируют, история "кто выполнил" не должна
    # измениться задним числом). Отметка "выполнено" не хранится только
    # здесь — она зеркалируется в completed_works (см.
    # mark_uhody_proba_completed ниже), которую уже читает живая карта
    # (legacy/forest_map.py:_forest_map_load_completed_works) — так
    # подсветка выдела на карте начинает работать и из веб-экрана, не
    # только из отчётов бота/мобильного приложения.
    existing_uhody_cols = {row[1] for row in conn.execute("PRAGMA table_info(uhody_proby)").fetchall()}
    if "completed_at" not in existing_uhody_cols:
        conn.execute("ALTER TABLE uhody_proby ADD COLUMN completed_at TEXT")
    if "ispolniteli_json" not in existing_uhody_cols:
        conn.execute("ALTER TABLE uhody_proby ADD COLUMN ispolniteli_json TEXT DEFAULT '[]'")
    # Связь пробы рубок ухода с участками лесных культур, на которых она
    # проведена (доработка «пробы ↔ лесные культуры») — снимок списка id
    # lesokultury_uchastok.id, выбранных при сохранении пробы (JSON-массив
    # чисел, как ispolniteli_json выше). При отметке пробы выполненной
    # (mark_uhody_proba_completed) по каждому id сюда же автоматически
    # заводится запись в lesokultury_meropriyatiya, чтобы на карточке
    # участка было видно, что уход выполнен.
    if "lesokultury_uchastok_ids_json" not in existing_uhody_cols:
        conn.execute(
            "ALTER TABLE uhody_proby ADD COLUMN lesokultury_uchastok_ids_json TEXT DEFAULT '[]'"
        )
    # sotrudnik_id — кто создал пробу из мобильного приложения (право
    # uhody.submit); NULL — проба заведена офисным пользователем.
    if "sotrudnik_id" not in existing_uhody_cols:
        conn.execute("ALTER TABLE uhody_proby ADD COLUMN sotrudnik_id INTEGER REFERENCES sotrudniki(id)")
    # Фото пробы (мобильное приложение): столб границы делянки, где идёт
    # уход, и столб самой пробной площадки. Хранятся пути внутри
    # uploads/mobile_photos (см. POST /api/bot/photo); наружу пути не
    # отдаются — только флаги "есть/нет" и эндпоинт выдачи файла.
    for col in ("foto_stolb_delyanki", "foto_stolb_proby"):
        if col not in existing_uhody_cols:
            conn.execute(f"ALTER TABLE uhody_proby ADD COLUMN {col} TEXT")
    # proba_id в lesokultury_meropriyatiya — чтобы отличать запись журнала,
    # заведённую вручную, от автоматически созданной при отметке пробы
    # рубок ухода выполненной (см. mark_uhody_proba_completed); нужен для
    # unmark_uhody_proba_completed, чтобы снимать ровно свои записи, и для
    # отображения «выполнено по пробе №N» на карточке участка.
    existing_lkm_cols = {row[1] for row in conn.execute("PRAGMA table_info(lesokultury_meropriyatiya)").fetchall()}
    if existing_lkm_cols and "proba_id" not in existing_lkm_cols:
        conn.execute(
            "ALTER TABLE lesokultury_meropriyatiya ADD COLUMN proba_id INTEGER REFERENCES uhody_proby(id)"
        )
    # dannye_json — структурированные данные полевой карточки (таблица проб,
    # результаты обследования, решение) для записей, введённых с телефона
    # (POST /api/lesokultury/{id}/inventarizatsiya|perevod); NULL у записей,
    # заведённых вручную на вебе. sotrudnik_id — кто ввёл с телефона.
    existing_lkm_cols = {row[1] for row in conn.execute("PRAGMA table_info(lesokultury_meropriyatiya)").fetchall()}
    if existing_lkm_cols:
        if "dannye_json" not in existing_lkm_cols:
            conn.execute("ALTER TABLE lesokultury_meropriyatiya ADD COLUMN dannye_json TEXT")
        if "sotrudnik_id" not in existing_lkm_cols:
            conn.execute(
                "ALTER TABLE lesokultury_meropriyatiya ADD COLUMN sotrudnik_id INTEGER REFERENCES sotrudniki(id)"
            )
    # sluzhebnye_zametki и breakdown_reports создаются выше через
    # executescript(SCHEMA) (CREATE TABLE IF NOT EXISTS), но подстрахуемся
    # явной проверкой на случай баз, созданных до этого добавления.
    if "sluzhebnye_zametki" not in existing_tables:
        conn.execute(
            """CREATE TABLE sluzhebnye_zametki (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                source TEXT DEFAULT 'вручную',
                ispolnitel_fio TEXT,
                telegram_id TEXT,
                status TEXT DEFAULT 'активна',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )"""
        )
    if "breakdown_reports" not in existing_tables:
        conn.execute(
            """CREATE TABLE breakdown_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT,
                fio TEXT,
                dolzhnost TEXT,
                detail_text TEXT,
                photo_path TEXT,
                status TEXT DEFAULT 'новое',
                zametka_id INTEGER REFERENCES sluzhebnye_zametki(id),
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )"""
        )
    # таблица пресетов комиссии Техкарты (Акт готовности лесосеки) — создаётся
    # выше через executescript(SCHEMA) (CREATE TABLE IF NOT EXISTS), но
    # подстрахуемся явной проверкой на случай баз, созданных до этого добавления.
    if "tehkarta_komissiya_preset" not in existing_tables:
        conn.execute(
            """CREATE TABLE tehkarta_komissiya_preset (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nazvanie TEXT UNIQUE NOT NULL,
                sostavil_dolzhnost TEXT,
                sostavil_fio TEXT,
                utverdil_dolzhnost TEXT,
                utverdil_fio TEXT,
                master_lesa_fio TEXT,
                brigadir_fio TEXT,
                tehkarta_chleny_json TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )"""
        )
    # добавляем utverdil_dolzhnost/utverdil_fio в tehkarta_komissiya_preset,
    # если таблица была создана до этого добавления (CREATE TABLE IF NOT
    # EXISTS выше не трогает колонки уже существующей таблицы)
    existing_tehkarta_preset_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(tehkarta_komissiya_preset)").fetchall()
    }
    for col in ("utverdil_dolzhnost", "utverdil_fio"):
        if col not in existing_tehkarta_preset_cols:
            conn.execute(f"ALTER TABLE tehkarta_komissiya_preset ADD COLUMN {col} TEXT")

    # добавляем lesnichestvo в lesorub_directory, если база была создана до
    # перехода на регистрацию через кнопки (раньше лесничество извлекалось
    # из текста отчёта, теперь оно закреплено за профилем рабочего один раз)
    existing_lesorub_cols = {row[1] for row in conn.execute("PRAGMA table_info(lesorub_directory)").fetchall()}
    if "lesnichestvo" not in existing_lesorub_cols:
        conn.execute("ALTER TABLE lesorub_directory ADD COLUMN lesnichestvo TEXT")

    # --- новые колонки vydel под парсер v2 (taksatsia_parser.Record) ---
    # выполняем только если таблица vydel уже существует (иначе её создаст CREATE TABLE IF NOT EXISTS выше)
    if "vydel" in existing_tables:
        existing_vydel_cols = {row[1] for row in conn.execute("PRAGMA table_info(vydel)").fetchall()}
        new_vydel_cols = {
            "tip_obekta": "TEXT",
            "sostav_formula": "TEXT",
            "yarus": "INTEGER",
            "vozrast_let": "REAL",
            "vysota_m": "REAL",
            "diametr_sm": "REAL",
            "klass_vozrasta": "REAL",
            "gruppa_vozrasta": "REAL",
            "tip_tlu": "TEXT",
            "prizhivaemost_pct": "REAL",
            "g_a": "REAL",
            "g_b": "REAL",
            "zapas_na_vydele": "REAL",
            "po_a": "REAL", "t_a": "REAL", "suh_a": "REAL", "zah_a": "REAL",
            "po_b": "REAL", "t_b": "REAL", "suh_b": "REAL", "zah_b": "REAL",
            "dop_yarusy_json": "TEXT",
            "zametki": "TEXT",
            "flag_proverki": "TEXT",
            "syraya_stroka_a": "TEXT",
            "syraya_stroka_b": "TEXT",
        }
        for col, coltype in new_vydel_cols.items():
            if col not in existing_vydel_cols:
                conn.execute(f"ALTER TABLE vydel ADD COLUMN {col} {coltype}")

    # таблица задач (кнопка 'Мои задачи' в Telegram-боте) — создаётся выше
    # через executescript(SCHEMA) (CREATE TABLE IF NOT EXISTS), но
    # подстрахуемся явной проверкой на случай баз, созданных до этого
    # добавления (та же логика, что и для raw_reports/completed_works выше).
    if "tasks" not in existing_tables:
        conn.execute(
            """CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                telegram_id TEXT,
                opisanie TEXT,
                status TEXT DEFAULT 'активна',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )"""
        )

    # таблица гео-заметок (см. handle_location в telegram_bot.py) — создаётся
    # выше через executescript(SCHEMA) (CREATE TABLE IF NOT EXISTS), но
    # подстрахуемся явной проверкой на случай баз, созданных до этого
    # добавления (та же логика, что и для tasks/raw_reports/completed_works выше).
    if "geo_notes" not in existing_tables:
        conn.execute(
            """CREATE TABLE geo_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT,
                lat REAL,
                lon REAL,
                note_text TEXT,
                photo_path TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )"""
        )

    # независимые пробы рубок ухода (см. OsvetlenieScreen) — создаём на
    # случай, если база была создана до этого пивота (раньше пробы
    # хранились в osvetlenie_proba, привязанными к delyanka_id)
    if "uhody_proby" not in existing_tables:
        conn.execute(
            """CREATE TABLE uhody_proby (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kvartal TEXT,
                vydel TEXT,
                ploshad_vydela REAL,
                ploshad_proby REAL,
                data_zamera TEXT,
                data_json TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )"""
        )

    # пресеты комиссии экрана "Рубки ухода" (см. комментарий над CREATE
    # TABLE osvetlenie_komissiya_preset в SCHEMA) — та же подстраховка для
    # баз, созданных до добавления этой таблицы (C.3 плана).
    if "osvetlenie_komissiya_preset" not in existing_tables:
        conn.execute(
            """CREATE TABLE osvetlenie_komissiya_preset (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nazvanie TEXT UNIQUE NOT NULL,
                perechetchik_1 TEXT,
                perechetchik_2 TEXT,
                perechetchik_3 TEXT,
                proveril_doljnost TEXT,
                proveril_fio TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )"""
        )

    # текущая погодная сводка (см. SettingsScreen/DashboardScreen) —
    # создаётся выше через executescript(SCHEMA) (CREATE TABLE IF NOT
    # EXISTS), но подстрахуемся явной проверкой на случай баз, созданных
    # до этого добавления.
    if "weather_current" not in existing_tables:
        conn.execute(
            """CREATE TABLE weather_current (
                id INTEGER PRIMARY KEY,
                temperature REAL,
                humidity INTEGER,
                wind_speed REAL,
                wind_dir TEXT,
                fire_danger_class INTEGER,
                fire_danger_text TEXT,
                updated_at TEXT
            )"""
        )
    # заполняем ровно 1 дефолтной строкой (id=1), если таблица ещё пуста —
    # чтобы UI сразу мог что-то показать, не дожидаясь реальной интеграции
    # с погодным API.
    weather_row_count = conn.execute("SELECT COUNT(*) FROM weather_current").fetchone()[0]
    if weather_row_count == 0:
        conn.execute(
            "INSERT INTO weather_current "
            "(id, temperature, humidity, wind_speed, wind_dir, "
            "fire_danger_class, fire_danger_text, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            (18.0, 65, 3.5, "СЗ", 3, "Средняя пожароопасность"),
        )

    # "Рабочий календарь" (см. calendar_tasks.py) — создаются выше через
    # executescript(SCHEMA) (CREATE TABLE IF NOT EXISTS), но подстрахуемся
    # явной проверкой на случай баз, созданных до этого добавления (та же
    # логика, что и для остальных таблиц выше).
    if "calendar_tasks" not in existing_tables:
        conn.execute(
            """CREATE TABLE calendar_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT,
                recurrence TEXT NOT NULL DEFAULT 'once',
                recurrence_config_json TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )"""
        )
    if "calendar_completions" not in existing_tables:
        conn.execute(
            """CREATE TABLE calendar_completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES calendar_tasks(id),
                period_key TEXT NOT NULL,
                note TEXT,
                completed_at TEXT DEFAULT (datetime('now', 'localtime')),
                UNIQUE(task_id, period_key)
            )"""
        )

    # ==========================================================================
    #   Этап 2 плана переноса в веб — подготовка к многопользовательскому
    #   режиму: "кто и когда последний раз менял запись" для таблиц,
    #   редактируемых через PATCH-эндпоинты backend'а (delyanki.py,
    #   lesokultury.py, raskhod.py роутеры). updated_at поддерживается
    #   автоматически триггером (см. ниже) — трогать его в коде не нужно.
    #   updated_by заполняется явно из роутера (touch_updated_by() в
    #   webext.py), когда в запросе известен текущий пользователь —
    #   таблица users/sessions тоже появляется на этом этапе, см. webext.py.
    # ==========================================================================
    _touchable_tables = ("delyanka", "delyanka_item", "lesokultury_uchastok", "raskhod_naryad")
    for _table in _touchable_tables:
        _cols = {row[1] for row in conn.execute(f"PRAGMA table_info({_table})").fetchall()}
        if "updated_at" not in _cols:
            conn.execute(f"ALTER TABLE {_table} ADD COLUMN updated_at TEXT")
        if "updated_by" not in _cols:
            conn.execute(f"ALTER TABLE {_table} ADD COLUMN updated_by TEXT")
        # AFTER UPDATE-триггер сам проставляет updated_at при любом изменении
        # строки — не нужно находить и патчить каждую функцию db.py/delyanka.py,
        # которая эту таблицу обновляет. SQLite по умолчанию не рекурсирует
        # триггеры (PRAGMA recursive_triggers = OFF), так что UPDATE внутри
        # триггера не вызывает его повторно.
        conn.execute(
            f"""CREATE TRIGGER IF NOT EXISTS trg_{_table}_updated_at
                AFTER UPDATE ON {_table}
                FOR EACH ROW
                BEGIN
                    UPDATE {_table} SET updated_at = datetime('now', 'localtime')
                    WHERE id = NEW.id;
                END"""
        )

    # Метка "объём уже добавлен в egais_snapshot_detail" для очереди ФЛС
    # (см. legacy/raskhod_v2.py:add_fls_prihod_to_egais_snapshot и
    # backfill-скрипт scripts/backfill_fls_prihod_detail.py) - до
    # исправления 2026-09 разбор ФЛС писал объём ТОЛЬКО в плоский
    # egais_snapshot, поэтому у старых уже разобранных строк этот флаг
    # остаётся 0, и разовый backfill находит их по нему же, чтобы не
    # проходить по всей истории вручную и не задвоить объём при повторном
    # запуске backfill.
    existing_fls_review_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(egais_fls_prihod_review)").fetchall()
    }
    if existing_fls_review_cols and "applied_to_snapshot_detail" not in existing_fls_review_cols:
        conn.execute(
            "ALTER TABLE egais_fls_prihod_review "
            "ADD COLUMN applied_to_snapshot_detail INTEGER NOT NULL DEFAULT 0"
        )
        # Строки, разобранные ДО появления этой колонки на "privyazan_k_pls"/
        # "ignored", объём в снапшот никогда не добавляли по определению -
        # помечаем их как "применено", чтобы backfill не пытался задним
        # числом добавлять то, чего разборщик сознательно не учитывал.
        conn.execute(
            "UPDATE egais_fls_prihod_review SET applied_to_snapshot_detail=1 "
            "WHERE status IN ('privyazan_k_pls', 'ignored')"
        )

    # Разовый (но безопасный при повторных запусках — см. флаг
    # applied_to_snapshot_detail выше) backfill: строки, разобранные "считать
    # отдельно" ДО исправления 2026-09, писали объём только в плоский
    # egais_snapshot и никогда не попадали в egais_snapshot_detail, который
    # реально читает баланс на экране "Расход" (и бот) — см. докстринг
    # raskhod_v2.add_fls_prihod_to_egais_snapshot. Добираем их здесь при
    # каждом старте приложения, а не отдельным ручным скриптом: обычно
    # запрос ниже находит 0 строк (все новые разборы уже помечены флагом
    # сразу самим resolve_fls_prihod), поэтому лишней нагрузки на старте нет.
    pending_fls = conn.execute(
        "SELECT id, kvartal, vydel, poroda, sortiment, obyom, sklad "
        "FROM egais_fls_prihod_review "
        "WHERE status='schitat_otdelno' AND applied_to_snapshot_detail=0"
    ).fetchall()
    if pending_fls:
        import raskhod_v2  # локальный импорт: избегаем цикла на уровне модуля
        for row_id, kvartal, vydel, poroda, sortiment, obyom, sklad in pending_fls:
            raskhod_v2.add_fls_prihod_to_egais_snapshot(
                conn, kvartal, vydel, poroda, sortiment, obyom, sklad, review_row_id=row_id
            )

    conn.commit()


def get_current_weather(conn):
    """Возвращает текущую погодную сводку (единственная актуальная строка
    id=1 в weather_current) в виде dict, либо None, если таблицы ещё нет
    или строка почему-то отсутствует (например, вызов до migrate_schema)."""
    try:
        row = conn.execute(
            "SELECT temperature, humidity, wind_speed, wind_dir, "
            "fire_danger_class, fire_danger_text, updated_at "
            "FROM weather_current WHERE id = 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return {
        "temperature": row[0],
        "humidity": row[1],
        "wind_speed": row[2],
        "wind_dir": row[3],
        "fire_danger_class": row[4],
        "fire_danger_text": row[5],
        "updated_at": row[6],
    }


def update_current_weather(conn, data: dict) -> None:
    """Обновляет единственную строку (id=1) в weather_current значениями
    из data (dict с любым подмножеством ключей temperature/humidity/
    wind_speed/wind_dir/fire_danger_class/fire_danger_text — отсутствующие
    ключи просто не трогаются при UPDATE). updated_at выставляется
    автоматически текущим временем. Если строки почему-то ещё нет
    (например, вызвали до migrate_schema) — создаёт её."""
    fields = (
        "temperature", "humidity", "wind_speed", "wind_dir",
        "fire_danger_class", "fire_danger_text",
    )
    row = conn.execute("SELECT id FROM weather_current WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO weather_current "
            "(id, temperature, humidity, wind_speed, wind_dir, "
            "fire_danger_class, fire_danger_text, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            tuple(data.get(f) for f in fields),
        )
    else:
        present = [f for f in fields if f in data]
        if present:
            set_clause = ", ".join(f"{f} = ?" for f in present)
            conn.execute(
                f"UPDATE weather_current SET {set_clause}, "
                "updated_at = datetime('now', 'localtime') WHERE id = 1",
                tuple(data[f] for f in present),
            )
    conn.commit()


# Префиксы свободного текста (см. taksatsia_parser.FREE_TEXT_PREFIXES), по которым
# заметки v2 раскладываются обратно по старым "витринным" колонкам vydel, чтобы
# существующий UI (get_vydel_card и т.п.), рассчитанный на podlesok/podrost/...,
# не сломался. Всё, что не подошло ни под один префикс, уходит в primechaniya.
_NOTE_BUCKETS = (
    ("podlesok", ("подлесок:",)),
    ("podrost", ("подpост:", "подрост:")),
    ("tselevaya_poroda", ("целевая порода",)),
    ("ptg", ("птг-",)),
    ("povrezhdenie", ("повpеждение:", "повреждение:")),
)


def _split_zametki(notes: list[str]) -> dict:
    """Раскладывает список заметок Record.заметки по старым колонкам vydel
    (podlesok/podrost/tselevaya_poroda/ptg/povrezhdenie), остальное -> primechaniya."""
    buckets = {name: [] for name, _ in _NOTE_BUCKETS}
    ostalnoe = []
    for note in notes:
        low = note.lower()
        for name, prefixes in _NOTE_BUCKETS:
            if low.startswith(prefixes):
                buckets[name].append(note)
                break
        else:
            ostalnoe.append(note)
    out = {name: (" | ".join(vals) if vals else None) for name, vals in buckets.items()}
    out["primechaniya"] = " | ".join(ostalnoe) if ostalnoe else None
    return out


# Формула состава склеена без разделителей, напр. '6Е4С' или '+Б' (примесь).
# Разбираем на пары (доля, порода): доля — 1-2 цифры или '+' (примесь, доли нет).
_SOSTAV_RE = re.compile(r'(\+|\d{1,2})([А-ЯЁ][а-яёА-ЯЁ.\-]*?)(?=\+|\d|$)')


def parse_sostav_formula(formula: str) -> list[tuple]:
    """'6Е4С' -> [(6,'Е'), (4,'С')]; '+Б' -> [(None,'Б')].
    Эвристика по фиксированному формату вывода парсера v2 — точный грамматический
    разбор нигде не специфицирован, поэтому сырые строки (сырая_строка_A/B)
    всегда сохраняются рядом в vydel для ручной сверки, если разбор ошибся."""
    if not formula:
        return []
    out = []
    for dolya_raw, poroda in _SOSTAV_RE.findall(formula):
        dolya = None if dolya_raw == '+' else int(dolya_raw)
        poroda = poroda.strip()
        if poroda:
            out.append((dolya, poroda))
    return out


def build_db(docx_paths, db_path="lesovod.db", reset=True):
    if isinstance(docx_paths, str):
        docx_paths = [docx_paths]
    conn = sqlite3.connect(db_path)
    if reset:
        conn.executescript(
            "DROP TABLE IF EXISTS sostav; DROP TABLE IF EXISTS vydel;"
            "DROP TABLE IF EXISTS kvartal; DROP TABLE IF EXISTS lesnichestvo;"
        )
    conn.executescript(SCHEMA)

    # NB: строим таблицы из объектов Record (parse()), а не из to_rows().
    # to_rows() существует для плоского CSV-экспорта и на этом пути схлопывает
    # структурные списки (доп_ярусы, заметки) в одну строку — из такой строки
    # надёжно восстановить строки таблицы sostav (порода/доля по каждому ярусу)
    # уже нельзя. Поэтому для sostav используем структурные поля Record
    # напрямую, а to_rows() пробрасываем наружу (см. records_to_rows) на случай,
    # если он нужен для экспорта в CSV в другом месте.
    records: list[Record] = []
    for p in docx_paths:
        lines = extract_lines(p)
        part = parse(lines)
        print(f"  {p}: {len(part)} записей")
        records.extend(part)

    lesnichestvo_ids = {}
    kvartal_ids = {}
    n_vydel, n_sostav = 0, 0

    for r in records:
        lname = (r.лесничество or "").strip() or "не определено"
        if lname not in lesnichestvo_ids:
            conn.execute(
                "INSERT OR IGNORE INTO lesnichestvo(name) VALUES (?)", (lname,)
            )
            row = conn.execute(
                "SELECT id FROM lesnichestvo WHERE name=?", (lname,)
            ).fetchone()
            lesnichestvo_ids[lname] = row[0]
        lid = lesnichestvo_ids[lname]

        kvartal_nomer = r.квартал or "не определено"
        key = (lid, kvartal_nomer)
        if key not in kvartal_ids:
            conn.execute(
                "INSERT OR IGNORE INTO kvartal(lesnichestvo_id, nomer) VALUES (?, ?)",
                (lid, kvartal_nomer),
            )
            row = conn.execute(
                "SELECT id FROM kvartal WHERE lesnichestvo_id=? AND nomer=?",
                (lid, kvartal_nomer),
            ).fetchone()
            kvartal_ids[key] = row[0]
        kid = kvartal_ids[key]

        is_forested = 1 if r.тип_объекта == 'Лес' else 0
        lesnye_kultury = 1 if r.тип_объекта and 'культур' in r.тип_объекта.lower() else 0
        osobaya_zemlya = None if is_forested else r.тип_объекта
        notes_buckets = _split_zametki(r.заметки)

        # ВАЖНО: "INSERT OR REPLACE INTO vydel" ниже при конфликте по
        # UNIQUE(kvartal_id, nomer) не обновляет строку "на месте" — SQLite
        # СНАЧАЛА удаляет старую строку, ПОТОМ вставляет новую с НОВЫМ
        # autoincrement id (раз id явно не указан в INSERT). Из-за этого
        # старые строки sostav (которые ссылаются на СТАРЫЙ vydel.id) не
        # удаляются автоматически и остаются "осиротевшими" — при повторной
        # загрузке того же выдела состав задваивался/копился мусором.
        # Поэтому явно вычищаем sostav старой записи (если она есть) ДО
        # replace — так же, как это раньше происходило "бесплатно" при
        # reset=True (DROP TABLE sostav целиком), только теперь точечно.
        old_vydel_row = conn.execute(
            "SELECT id FROM vydel WHERE kvartal_id = ? AND nomer = ?",
            (kid, str(r.выдел) if r.выдел is not None else kvartal_nomer),
        ).fetchone()
        if old_vydel_row is not None:
            conn.execute("DELETE FROM sostav WHERE vydel_id = ?", (old_vydel_row[0],))

        cur = conn.execute(
            """INSERT OR REPLACE INTO vydel
               (kvartal_id, nomer, ploshad, kategoriya_lesov, podkategoriya_lesov,
                tip_lesa, tlu, bonitet, polnota, zapas_na_ga,
                osobaya_zemlya, is_forested, lesnye_kultury,
                podlesok, podrost, tselevaya_poroda, ptg, povrezhdenie, primechaniya,
                tip_obekta, sostav_formula, yarus, vozrast_let, vysota_m, diametr_sm,
                klass_vozrasta, gruppa_vozrasta, tip_tlu, prizhivaemost_pct,
                g_a, g_b, zapas_na_vydele,
                po_a, t_a, suh_a, zah_a, po_b, t_b, suh_b, zah_b,
                dop_yarusy_json, zametki, flag_proverki, syraya_stroka_a, syraya_stroka_b)
               VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,
                       ?,?,?, ?,?,?,?,?,?,?,?, ?,?,?,?,?)""",
            (
                kid, str(r.выдел) if r.выдел is not None else kvartal_nomer,
                r.площадь_га, r.категория_лесов, r.подкатегория_лесов,
                r.тип_леса, r.тлу_эдафотоп, r.бонитет, r.полнота, r.запас_на_га,
                osobaya_zemlya, is_forested, lesnye_kultury,
                notes_buckets["podlesok"], notes_buckets["podrost"],
                notes_buckets["tselevaya_poroda"], notes_buckets["ptg"],
                notes_buckets["povrezhdenie"], notes_buckets["primechaniya"],
                r.тип_объекта, r.состав, r.ярус, r.возраст_лет, r.высота_м, r.диаметр_см,
                r.класс_возраста, r.группа_возраста, r.тип_тлу, r.приживаемость_pct,
                r.g_a, r.g_b, r.запас_на_выделе,
                r.по_a, r.т_a, r.сух_a, r.зах_a, r.по_b, r.т_b, r.сух_b, r.зах_b,
                json.dumps(r.доп_ярусы, ensure_ascii=False) if r.доп_ярусы else None,
                " | ".join(r.заметки) if r.заметки else None,
                r.флаг_проверки or None,
                r.сырая_строка_A or None, r.сырая_строка_B or None,
            ),
        )
        vydel_id = cur.lastrowid
        n_vydel += 1

        # --- главный ярус: формула состава -> отдельные строки sostav (yarus='1', как раньше) ---
        idx = 0
        for dolya, poroda in parse_sostav_formula(r.состав):
            conn.execute(
                """INSERT INTO sostav (vydel_id, poryadok, yarus, poroda, dolya, vozrast, vysota, diametr)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (vydel_id, idx, "1", poroda, dolya, r.возраст_лет, r.высота_м, r.диаметр_см),
            )
            idx += 1
            n_sostav += 1

        # --- доп. ярусы (подрост/сухостой/сохранённый ярус) -> свои строки sostav ---
        for tier in r.доп_ярусы:
            for dolya, poroda in parse_sostav_formula(tier.get("состав") or ""):
                conn.execute(
                    """INSERT INTO sostav (vydel_id, poryadok, yarus, poroda, dolya, vozrast, vysota, diametr)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (vydel_id, idx, str(tier.get("ярус")), poroda, dolya,
                     tier.get("возраст"), tier.get("h"), tier.get("d")),
                )
                idx += 1
                n_sostav += 1

    conn.commit()
    print(f"Загружено: лесничеств={len(lesnichestvo_ids)}, кварталов={len(kvartal_ids)}, "
          f"выделов={n_vydel}, записей состава={n_sostav}")
    return conn


def records_to_rows(records: list[Record]) -> list[dict]:
    """Тонкая обёртка над taksatsia_parser.to_rows() — для CSV-экспорта/отладки,
    не используется при загрузке в БД (см. комментарий в build_db)."""
    return to_rows(records)
def get_vydel_card(conn, kvartal_nomer, vydel_nomer, lesnichestvo_name=None):
    """Возвращает 'карточку участка' — то, что видно в интерфейсе при выборе квартала+выдела."""
    q = """
    SELECT v.id, v.nomer, v.ploshad, v.kategoriya_lesov, v.podkategoriya_lesov,
           v.kl_tovarnosti, v.tip_lesa, v.tlu, v.bonitet, v.polnota, v.zapas_na_ga,
           v.osobaya_zemlya, v.is_forested, v.lesnye_kultury,
           v.podlesok, v.podrost, v.tselevaya_poroda, v.ptg, v.povrezhdenie, v.primechaniya,
           v.tip_tlu, v.klass_vozrasta, v.gruppa_vozrasta, v.zapas_na_vydele,
           k.nomer as kvartal_nomer, l.name as lesnichestvo
    FROM vydel v
    JOIN kvartal k ON v.kvartal_id = k.id
    JOIN lesnichestvo l ON k.lesnichestvo_id = l.id
    WHERE k.nomer = ? AND v.nomer = ?
    """
    params = [kvartal_nomer, vydel_nomer]
    if lesnichestvo_name:
        q += " AND l.name LIKE ?"
        params.append(f"%{lesnichestvo_name}%")
    row = conn.execute(q, params).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute(q, params).description]
    # повторно исполнили запрос только чтобы взять description - для читаемости оставим так
    card = dict(zip(cols, row))

    # DOS-выгрузка печатает запас на га в десятках (напр. "33" значит 330 м³/га) —
    # 'zapas_na_ga' остаётся как есть (сырое значение из БД, на случай сверки),
    # а для интерфейса добавляем уже умноженное на 10 отображаемое значение.
    raw_zapas_ga = card.get("zapas_na_ga")
    try:
        card["zapas_na_ga_display"] = round(float(raw_zapas_ga) * 10) if raw_zapas_ga is not None else None
    except (TypeError, ValueError):
        card["zapas_na_ga_display"] = None

    # zapas_na_vydele — суммарный запас по выделу, в отличие от zapas_na_ga уже
    # хранится в реальных единицах (не в десятках) — просто округляем для вывода.
    raw_zapas_vydele = card.get("zapas_na_vydele")
    try:
        card["zapas_na_vydele"] = round(float(raw_zapas_vydele)) if raw_zapas_vydele is not None else None
    except (TypeError, ValueError):
        pass

    sostav = conn.execute(
        "SELECT yarus, poroda, dolya, vozrast, vysota, diametr FROM sostav WHERE vydel_id=? ORDER BY poryadok",
        (card["id"],),
    ).fetchall()
    card["sostav"] = [
        {"yarus": y, "poroda": p, "dolya": d, "vozrast": vz, "vysota": vy, "diametr": dm}
        for y, p, d, vz, vy, dm in sostav
    ]
    card["formula_sostava"] = "".join(
        f"{s['dolya']}{s['poroda']}" if s["dolya"] else f"+{s['poroda']}"
        for s in card["sostav"] if s["yarus"] == "1"
    )
    yarus2 = [s for s in card["sostav"] if s["yarus"] != "1"]
    card["formula_sostava_2_yarus"] = "".join(
        f"{s['dolya']}{s['poroda']}" if s["dolya"] else f"+{s['poroda']}"
        for s in yarus2
    ) if yarus2 else ""
    return card


def get_tasks_for_bot(conn, telegram_id):
    """Возвращает список активных задач конкретного рабочего (кнопка
    'Мои задачи' в Telegram-боте) — telegram_id тот же идентификатор, что
    хранится в lesorub_directory.viber_id/tasks.telegram_id.

    Строки возвращаются как sqlite3.Row (если conn.row_factory настроен
    соответствующим образом в вызывающем коде — см. get_db() в
    telegram_bot.py), поэтому к полям можно обращаться и по индексу, и
    по имени колонки."""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE telegram_id=? AND status='активна'",
        (telegram_id,),
    ).fetchall()
    return rows


def complete_task_for_bot(conn, task_id, telegram_id):
    """Отмечает задачу выполненной по нажатию inline-кнопки '✅' под списком
    задач в Telegram-боте (см. handle_taskdone_callback в telegram_bot.py).

    telegram_id проверяется в WHERE, чтобы рабочий не мог закрыть чужую
    задачу (например, подобрав/угадав task_id). Обновляются только записи
    со status='активна' — если задача уже была закрыта раньше (двойное
    нажатие, гонка между устройствами и т.п.), UPDATE просто не найдёт
    строку и ничего не сломает.

    Возвращает True, если задача была найдена и переведена в статус
    'выполнена', иначе False (не найдена, чужая или уже закрыта раньше)."""
    cur = conn.execute(
        "UPDATE tasks SET status='выполнена' WHERE id=? AND telegram_id=? AND status='активна'",
        (task_id, telegram_id),
    )
    conn.commit()
    return cur.rowcount > 0


def get_active_delyanki_for_bot(conn, kvartal):
    """Возвращает список делянок (уникальные пары выдел + номер лесосеки)
    в заданном квартале — используется для inline-кнопок выбора делянки
    при запросе остатка (см. process_balance_step в telegram_bot.py):
    рабочий вводит только номер квартала, а конкретный выдел выбирает
    кнопкой, вместо того чтобы печатать его руками.

    'Активная' здесь означает status_rabot != 'выполнено' — делянка ещё
    не отмечена как полностью законченная, т.е. по ней потенциально есть
    смысл проверять остаток. Если в проекте используется другой набор
    статусов (например, отдельный признак в delyanka), поправь фильтр
    WHERE под реальную схему.

    Строки возвращаются как sqlite3.Row (см. row_factory в get_db() в
    telegram_bot.py), поэтому к полям можно обращаться по имени —
    row["vydel"], row["lesoseka_nomer"]."""
    rows = conn.execute(
        """SELECT DISTINCT vydel, lesoseka_nomer
           FROM delyanka_item
           WHERE kvartal = ? AND (status_rabot IS NULL OR status_rabot != 'выполнено')
           ORDER BY vydel, lesoseka_nomer""",
        (str(kvartal),),
    ).fetchall()
    return rows


# --------------------------------------------------------------------------- #
#   ПОЛОМКИ ТЕХНИКИ (breakdown_reports) И СЛУЖЕБНЫЕ ЗАМЕТКИ (sluzhebnye_zametki)
#   — используются кнопкой "⚠️ Поломка" (тракторист/харвестерщик) и разделом
#   "Служебные заметки" (лесничий) в telegram_bot.py.
# --------------------------------------------------------------------------- #
def get_lesnichiy_telegram_ids(conn):
    """Возвращает список telegram_id (lesorub_directory.viber_id) всех
    зарегистрированных пользователей с должностью 'лесничий' — этим id
    бот рассылает уведомление о новой поломке (см. handle_breakdown_detail_step
    в telegram_bot.py). Лесничих может быть несколько (несколько лесничеств
    на один бот) — уведомление уходит всем."""
    rows = conn.execute(
        "SELECT viber_id FROM lesorub_directory WHERE dolzhnost='лесничий'"
    ).fetchall()
    return [row[0] for row in rows]


def save_breakdown_report(conn, telegram_id, fio, dolzhnost, detail_text, photo_path=None):
    """Сохраняет отчёт о поломке техники (кнопка '⚠️ Поломка') до рассылки
    лесничим. Возвращает id новой записи — он же используется в
    callback_data инлайн-кнопки 'breakdown_add_<id>' под уведомлением у
    лесничего (см. handle_breakdown_add_callback)."""
    cursor = conn.execute(
        """INSERT INTO breakdown_reports
               (telegram_id, fio, dolzhnost, detail_text, photo_path, status, created_at)
           VALUES (?, ?, ?, ?, ?, 'новое', ?)""",
        (
            telegram_id, fio, dolzhnost, detail_text, photo_path,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def add_sluzhebnaya_zametka_from_breakdown(conn, breakdown_id):
    """По нажатию лесничим инлайн-кнопки 'Добавить в служебные записки'
    под уведомлением о поломке: создаёт запись в sluzhebnye_zametki
    (source='поломка') и помечает исходный breakdown_reports как
    status='добавлено', сохраняя ссылку на созданную заметку.

    Возвращает id новой заметки, либо None, если поломка с таким id не
    найдена или уже была обработана раньше (двойное нажатие кнопки
    несколькими лесничими одновременно — обрабатываем только первое)."""
    row = conn.execute(
        "SELECT * FROM breakdown_reports WHERE id=? AND status='новое'",
        (breakdown_id,),
    ).fetchone()
    if row is None:
        return None
    text = f"⚠️ Поломка ({row['dolzhnost']}, {row['fio']}): {row['detail_text']}"
    cursor = conn.execute(
        """INSERT INTO sluzhebnye_zametki
               (text, source, ispolnitel_fio, telegram_id, status, created_at)
           VALUES (?, 'поломка', ?, ?, 'активна', ?)""",
        (
            text, row["fio"], row["telegram_id"],
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    zametka_id = cursor.lastrowid
    conn.execute(
        "UPDATE breakdown_reports SET status='добавлено', zametka_id=? WHERE id=?",
        (zametka_id, breakdown_id),
    )
    conn.commit()
    return zametka_id


def add_sluzhebnaya_zametka(conn, text, ispolnitel_fio=None, telegram_id=None):
    """Создаёт служебную заметку вручную (лесничий пишет её сам, а не
    через принятую поломку) — source='вручную' по умолчанию колонки."""
    cursor = conn.execute(
        """INSERT INTO sluzhebnye_zametki
               (text, source, ispolnitel_fio, telegram_id, status, created_at)
           VALUES (?, 'вручную', ?, ?, 'активна', ?)""",
        (text, ispolnitel_fio, telegram_id, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return cursor.lastrowid


def list_active_sluzhebnye_zametki(conn):
    """Возвращает активные (ещё не выполненные) служебные заметки — для
    кнопки 'Служебные заметки' у лесничего в Telegram-боте и для экрана
    'Журнал ИИ' в приложении. Свежие заметки сверху."""
    rows = conn.execute(
        "SELECT * FROM sluzhebnye_zametki WHERE status='активна' ORDER BY id DESC"
    ).fetchall()
    return rows


def complete_sluzhebnaya_zametka(conn, zametka_id):
    """Отмечает служебную заметку выполненной (инлайн-кнопка '✅ выполнено'
    под каждой заметкой в боте) — после этого она пропадает из
    list_active_sluzhebnye_zametki(). Возвращает True, если заметка была
    найдена и активна, иначе False (уже закрыта раньше / не найдена)."""
    cur = conn.execute(
        "UPDATE sluzhebnye_zametki SET status='выполнена' WHERE id=? AND status='активна'",
        (zametka_id,),
    )
    conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
#   RAW_REPORTS — дедуп и отмена последнего отчёта (этап 10, telegram_bot.py)
# --------------------------------------------------------------------------- #
def save_raw_report(conn, telegram_id, fio, kvartal, vydels, tip_raboty, photo_path, opisanie):
    """Кладёт отчёт рабочего в буферную таблицу raw_reports на проверку
    лесничим (экран "Журнал ИИ"). Восстановлено в рамках подчасти 3.2
    доработки (перенос из telegram_bot.py, где раньше принимала общий
    cursor без собственного commit — здесь вызывается через отдельный
    HTTP-запрос без общего вызывающего кода, поэтому коммитит сама).
    vydels приходит списком (см. app/routers/bot.py: RawReportIn.vydels),
    в таблице хранится строкой через запятую — тот же формат, что читает
    find_recent_duplicate_report/get_last_raw_report_for_user ниже.
    data_soobscheniya пишется в формате '%d.%m.%Y %H:%M', как и ожидает
    find_recent_duplicate_report при разборе окна дублей. Возвращает id
    новой записи."""
    vydels_str = ",".join(v.strip() for v in (vydels or []) if v.strip())
    cur = conn.execute(
        """INSERT INTO raw_reports
               (ispolnitel_viber_id, ispolnitel_fio, kvartal, vydels,
                data_soobscheniya, status, photo_path, opisanie, tip_raboty)
           VALUES (?, ?, ?, ?, ?, 'на проверке', ?, ?, ?)""",
        (
            telegram_id,
            fio,
            kvartal,
            vydels_str,
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            photo_path,
            opisanie,
            tip_raboty,
        ),
    )
    conn.commit()
    return cur.lastrowid


def find_recent_duplicate_report(conn, telegram_id, kvartal, vydels, tip_raboty, window_minutes=240):
    """Ищет уже отправленный этим же рабочим и ещё не проверенный лесничим
    (status='на проверке') отчёт с тем же кварталом/выделами/типом работы
    за последние window_minutes минут — защита от случайной повторной
    отправки одного и того же отчёта (двойное нажатие кнопки, повтор после
    сбоя связи и т.п., см. process_report_photo_step в telegram_bot.py).
    Выделы сравниваются как множество строк — порядок ввода ('1,2' vs
    '2,1') не важен. Возвращает найденную строку raw_reports или None,
    если совпадений нет."""
    rows = conn.execute(
        """SELECT * FROM raw_reports
           WHERE ispolnitel_viber_id=? AND kvartal=? AND tip_raboty=?
                 AND status='на проверке'
           ORDER BY id DESC""",
        (telegram_id, kvartal, tip_raboty),
    ).fetchall()
    if not rows:
        return None

    wanted_vydels = {v.strip() for v in (vydels or []) if v.strip()}
    now = datetime.now()
    for row in rows:
        row_vydels = {v.strip() for v in (row["vydels"] or "").split(",") if v.strip()}
        if row_vydels != wanted_vydels:
            continue
        try:
            sent_at = datetime.strptime(row["data_soobscheniya"], "%d.%m.%Y %H:%M")
        except (TypeError, ValueError):
            continue
        if (now - sent_at).total_seconds() <= window_minutes * 60:
            return row
    return None


def get_last_raw_report_for_user(conn, telegram_id):
    """Последний отчёт этого рабочего, ещё ожидающий проверки лесничим
    (status='на проверке') — для кнопки '↩️ Отменить последний отчёт' в
    боте. Уже проверенный (перенесённый в completed_works) отчёт отменить
    нельзя, поэтому такие сюда не попадают."""
    return conn.execute(
        """SELECT * FROM raw_reports
           WHERE ispolnitel_viber_id=? AND status='на проверке'
           ORDER BY id DESC LIMIT 1""",
        (telegram_id,),
    ).fetchone()


def cancel_raw_report(conn, report_id, telegram_id):
    """Удаляет отчёт по кнопке '↩️ Отменить последний отчёт' — только если
    он принадлежит этому telegram_id и ещё не проверен лесничим
    (status='на проверке'). Возвращает путь к фото отчёта (чтобы
    вызывающий код мог удалить и сам файл) — пустую строку/None, если фото
    не было. Возвращает False, если отчёт не найден, принадлежит другому
    пользователю или уже обработан лесничим."""
    row = conn.execute(
        "SELECT photo_path FROM raw_reports WHERE id=? AND ispolnitel_viber_id=? AND status='на проверке'",
        (report_id, telegram_id),
    ).fetchone()
    if row is None:
        return False
    conn.execute("DELETE FROM raw_reports WHERE id=?", (report_id,))
    conn.commit()
    return row["photo_path"]


# --------------------------------------------------------------------------- #
#   НЕЗАВИСИМЫЕ ПРОБЫ РУБОК УХОДА (uhody_proby) — CRUD
#   Полностью отвязаны от delyanka/delyanka_item, см. схему выше.
# --------------------------------------------------------------------------- #
def save_uhody_proba(
    conn,
    kvartal,
    vydel,
    ploshad_vydela,
    ploshad_proby,
    data_zamera,
    data_json,
    proba_id=None,
    lesokultury_uchastok_ids=None,
):
    """Сохраняет независимую пробу рубок ухода.

    Если proba_id is None — создаёт новую запись и возвращает её id;
    иначе обновляет существующую запись с этим id (created_at не
    трогается) и возвращает тот же proba_id.
    data_json — сериализованный (json.dumps(..., ensure_ascii=False))
    словарь со всей остальной ведомостью (лесничество, состав, полнота,
    вид/способ рубки, комиссия, строки таблицы перечёта, итоги расчёта).
    lesokultury_uchastok_ids — список id lesokultury_uchastok.id, на
    которых проведена эта проба (доработка «пробы ↔ лесные культуры»);
    сохраняется как JSON-массив, используется при отметке пробы
    выполненной (mark_uhody_proba_completed) для авто-отметки ухода."""
    uchastok_ids_json = json.dumps(lesokultury_uchastok_ids or [], ensure_ascii=False)
    if proba_id is None:
        cursor = conn.execute(
            """
            INSERT INTO uhody_proby
                (kvartal, vydel, ploshad_vydela, ploshad_proby, data_zamera,
                 data_json, lesokultury_uchastok_ids_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kvartal, vydel, ploshad_vydela, ploshad_proby, data_zamera,
                data_json, uchastok_ids_json, datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return cursor.lastrowid

    conn.execute(
        """
        UPDATE uhody_proby
        SET kvartal = ?, vydel = ?, ploshad_vydela = ?, ploshad_proby = ?,
            data_zamera = ?, data_json = ?, lesokultury_uchastok_ids_json = ?
        WHERE id = ?
        """,
        (kvartal, vydel, ploshad_vydela, ploshad_proby, data_zamera, data_json,
         uchastok_ids_json, proba_id),
    )
    conn.commit()
    return proba_id


def set_uhody_proba_author(conn, proba_id, sotrudnik_id):
    """Проставляет автора-рабочего свежесозданной пробе (save_uhody_proba
    автора не знает — её сигнатуру не меняем)."""
    conn.execute("UPDATE uhody_proby SET sotrudnik_id = ? WHERE id = ?", (sotrudnik_id, proba_id))
    conn.commit()


PROBA_PHOTO_COLUMNS = {"stolb_delyanki": "foto_stolb_delyanki", "stolb_proby": "foto_stolb_proby"}


def set_uhody_proba_photos(conn, proba_id, foto_stolb_delyanki=None, foto_stolb_proby=None):
    """Проставляет пути фото пробе; None — не трогать (при правке пробы без
    новых фото старые остаются)."""
    if foto_stolb_delyanki is not None:
        conn.execute("UPDATE uhody_proby SET foto_stolb_delyanki = ? WHERE id = ?", (foto_stolb_delyanki, proba_id))
    if foto_stolb_proby is not None:
        conn.execute("UPDATE uhody_proby SET foto_stolb_proby = ? WHERE id = ?", (foto_stolb_proby, proba_id))
    conn.commit()


def get_uhody_proba_photo_path(conn, proba_id, kind):
    """Путь фото пробы (kind — ключ PROBA_PHOTO_COLUMNS) или None."""
    column = PROBA_PHOTO_COLUMNS[kind]
    row = conn.execute(f"SELECT {column} FROM uhody_proby WHERE id = ?", (proba_id,)).fetchone()
    return row[0] if row and row[0] else None


def list_uhody_proby(conn):
    """Возвращает краткий список всех независимых проб рубок ухода
    (без data_json — для отображения в списке слева на экране
    "Рубки ухода"), самые новые сверху."""
    rows = conn.execute(
        """
        SELECT id, kvartal, vydel, ploshad_vydela, ploshad_proby, data_zamera,
               created_at, completed_at, ispolniteli_json, lesokultury_uchastok_ids_json,
               sotrudnik_id
        FROM uhody_proby
        ORDER BY id DESC
        """
    ).fetchall()
    return [
        {
            "id": row[0],
            "kvartal": row[1],
            "vydel": row[2],
            "ploshad_vydela": row[3],
            "ploshad_proby": row[4],
            "data_zamera": row[5],
            "created_at": row[6],
            "completed_at": row[7],
            "ispolniteli": json.loads(row[8]) if row[8] else [],
            "lesokultury_uchastok_ids": json.loads(row[9]) if row[9] else [],
            "sotrudnik_id": row[10],
        }
        for row in rows
    ]


def get_uhody_proba(conn, proba_id):
    """Возвращает полную запись пробы (включая распарсенный data_json)
    по id, либо None, если проба не найдена."""
    row = conn.execute(
        """
        SELECT id, kvartal, vydel, ploshad_vydela, ploshad_proby, data_zamera,
               data_json, created_at, completed_at, ispolniteli_json,
               lesokultury_uchastok_ids_json, sotrudnik_id,
               foto_stolb_delyanki, foto_stolb_proby
        FROM uhody_proby
        WHERE id = ?
        """,
        (proba_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row[6]) if row[6] else {}
    except (TypeError, ValueError):
        data = {}
    uchastok_ids = json.loads(row[10]) if row[10] else []
    lesokultury_uchastki = []
    if uchastok_ids:
        placeholders = ",".join("?" for _ in uchastok_ids)
        uk_rows = conn.execute(
            f"SELECT id, kvartal, vydel, glavnaya_poroda, god_sozdaniya "
            f"FROM lesokultury_uchastok WHERE id IN ({placeholders})",
            uchastok_ids,
        ).fetchall()
        lesokultury_uchastki = [
            {"id": r[0], "kvartal": r[1], "vydel": r[2], "glavnaya_poroda": r[3], "god_sozdaniya": r[4]}
            for r in uk_rows
        ]
    return {
        "id": row[0],
        "kvartal": row[1],
        "vydel": row[2],
        "ploshad_vydela": row[3],
        "ploshad_proby": row[4],
        "data_zamera": row[5],
        "data": data,
        "created_at": row[7],
        "completed_at": row[8],
        "ispolniteli": json.loads(row[9]) if row[9] else [],
        "lesokultury_uchastok_ids": uchastok_ids,
        "lesokultury_uchastki": lesokultury_uchastki,
        "sotrudnik_id": row[11],
        # какие фото приложены (сами пути наружу не отдаём) — файл берётся
        # через GET /api/uhody/proby/{id}/photo/{kind}
        "photos": {"stolb_delyanki": bool(row[12]), "stolb_proby": bool(row[13])},
    }


def delete_uhody_proba(conn, proba_id):
    """Удаляет независимую пробу рубок ухода по id — вместе с записями,
    автоматически заведёнными в журнал лесных культур при отметке этой
    пробы выполненной (см. mark_uhody_proba_completed), чтобы не остались
    «висячие» ссылки на удалённую пробу."""
    conn.execute("DELETE FROM lesokultury_meropriyatiya WHERE proba_id = ?", (proba_id,))
    conn.execute("DELETE FROM uhody_proby WHERE id = ?", (proba_id,))
    conn.commit()


def mark_uhody_proba_completed(conn, proba_id, sotrudnik_ids):
    """Отмечает пробу рубок ухода выполненной — Фаза 2 плана доработки.

    1. Снимает снимок ФИО/должности выбранных sotrudnik_ids на СЕЙЧАС
       (в ispolniteli_json пробы) — не живую ссылку.
    2. Заводит по одной строке в completed_works на каждого исполнителя
       (kvartal/vydel пробы, tip_raboty="Рубки ухода", лесничество —
       из data_json пробы) — именно эту таблицу уже читает живая карта
       (legacy/forest_map.py), так подсветка выдела начинает работать
       сразу, без отдельного механизма для веб-экрана.

    Идемпотентно: повторный вызов на уже отмеченной пробе сначала снимает
    старую отметку (см. unmark_uhody_proba_completed) — то есть повторное
    нажатие "Отметить выполненной" с другим составом исполнителей
    ПЕРЕЗАПИСЫВАЕТ, а не дублирует записи в completed_works.

    Бросает ValueError, если проба не найдена или sotrudnik_ids пуст."""
    proba = get_uhody_proba(conn, proba_id)
    if proba is None:
        raise ValueError(f"Проба {proba_id} не найдена")
    if not sotrudnik_ids:
        raise ValueError("Не выбран ни один исполнитель")

    if proba["completed_at"]:
        unmark_uhody_proba_completed(conn, proba_id)

    placeholders = ",".join("?" for _ in sotrudnik_ids)
    rows = conn.execute(
        f"SELECT id, fio, dolzhnost FROM sotrudniki WHERE id IN ({placeholders})",
        sotrudnik_ids,
    ).fetchall()
    if not rows:
        raise ValueError("Выбранные исполнители не найдены")

    lesnichestvo = (proba["data"] or {}).get("lesnichestvo") or ""
    today = datetime.now().strftime("%Y-%m-%d")
    ispolniteli = [{"id": r[0], "fio": r[1], "dolzhnost": r[2] or ""} for r in rows]

    conn.executemany(
        "INSERT INTO completed_works "
        "(data_vypolneniya, ispolnitel_fio, kvartal, vydel, tip_raboty, lesnichestvo, dolzhnost, opisanie) "
        "VALUES (?, ?, ?, ?, 'Рубки ухода', ?, ?, ?)",
        [
            (today, i["fio"], proba["kvartal"], proba["vydel"], lesnichestvo, i["dolzhnost"],
             f"Проба рубок ухода №{proba_id}")
            for i in ispolniteli
        ],
    )
    conn.execute(
        "UPDATE uhody_proby SET completed_at=?, ispolniteli_json=? WHERE id=?",
        (datetime.now().isoformat(timespec="seconds"), json.dumps(ispolniteli, ensure_ascii=False), proba_id),
    )

    # Авто-отметка «уход выполнен» на связанных участках лесных культур —
    # по каждому id из lesokultury_uchastok_ids_json заводим запись в
    # журнал мероприятий участка (tip = вид рубки из ведомости, если
    # указан, иначе обобщённый «Уход (рубки ухода)»), помеченную этим
    # proba_id, чтобы unmark/delete могли её найти и снять.
    uchastok_ids = proba["lesokultury_uchastok_ids"]
    if uchastok_ids:
        vid_rubki = (proba["data"] or {}).get("vid_rubki") or ""
        tip = vid_rubki.strip() if vid_rubki.strip() else "Уход (рубки ухода)"
        today_iso = datetime.now().strftime("%Y-%m-%d")
        for uchastok_id in uchastok_ids:
            if get_lesokultury_uchastok(conn, uchastok_id) is None:
                continue
            conn.execute(
                "INSERT INTO lesokultury_meropriyatiya "
                "(uchastok_id, tip, data, primechaniya, proba_id) VALUES (?, ?, ?, ?, ?)",
                (uchastok_id, tip, today_iso, f"Проба рубок ухода №{proba_id}", proba_id),
            )

    conn.commit()
    return get_uhody_proba(conn, proba_id)


def unmark_uhody_proba_completed(conn, proba_id):
    """Снимает отметку "выполнено" с пробы — удаляет соответствующие
    строки completed_works (по kvartal/vydel/tip_raboty/дате отметки/
    ФИО каждого исполнителя, сохранённым в ispolniteli_json на момент
    отметки) и очищает completed_at/ispolniteli_json на самой пробе.
    Если проба не была отмечена — тихо ничего не делает."""
    proba = get_uhody_proba(conn, proba_id)
    if proba is None or not proba["completed_at"]:
        return
    today = proba["completed_at"][:10]
    for i in proba["ispolniteli"]:
        conn.execute(
            "DELETE FROM completed_works WHERE kvartal=? AND vydel=? AND tip_raboty='Рубки ухода' "
            "AND ispolnitel_fio=? AND data_vypolneniya=? AND opisanie=?",
            (proba["kvartal"], proba["vydel"], i["fio"], today, f"Проба рубок ухода №{proba_id}"),
        )
    conn.execute(
        "UPDATE uhody_proby SET completed_at=NULL, ispolniteli_json='[]' WHERE id=?",
        (proba_id,),
    )
    # снимаем и авто-записи ухода на участках лесных культур, заведённые
    # этой пробой (см. mark_uhody_proba_completed)
    conn.execute("DELETE FROM lesokultury_meropriyatiya WHERE proba_id = ?", (proba_id,))
    conn.commit()


# --------------------------------------------------------------------------- #
#   ПРЕСЕТЫ КОМИССИИ ЭКРАНА "РУБКИ УХОДА" (osvetlenie_komissiya_preset)
#   — CRUD, C.3 плана. Адресуются integer id (в отличие от UPSERT-по-
#   nazvanie у osvidetelstvovanie_komissiya_preset выше) — так проще для
#   REST-эндпоинтов app/routers/uhody.py (GET/POST/DELETE .../{id}).
# --------------------------------------------------------------------------- #
def list_osvetlenie_komissiya_presets(conn):
    """Список пресетов комиссии экрана "Рубки ухода", по названию —
    [{"id", "nazvanie", "perechetchik_1", "perechetchik_2", "perechetchik_3",
    "proveril_doljnost", "proveril_fio"}]."""
    rows = conn.execute(
        "SELECT id, nazvanie, perechetchik_1, perechetchik_2, perechetchik_3, "
        "proveril_doljnost, proveril_fio "
        "FROM osvetlenie_komissiya_preset ORDER BY nazvanie"
    ).fetchall()
    return [
        {
            "id": row[0],
            "nazvanie": row[1],
            "perechetchik_1": row[2] or "",
            "perechetchik_2": row[3] or "",
            "perechetchik_3": row[4] or "",
            "proveril_doljnost": row[5] or "",
            "proveril_fio": row[6] or "",
        }
        for row in rows
    ]


def get_osvetlenie_komissiya_preset(conn, preset_id):
    """Возвращает один пресет по id, либо None, если не найден."""
    row = conn.execute(
        "SELECT id, nazvanie, perechetchik_1, perechetchik_2, perechetchik_3, "
        "proveril_doljnost, proveril_fio "
        "FROM osvetlenie_komissiya_preset WHERE id = ?",
        (preset_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "nazvanie": row[1],
        "perechetchik_1": row[2] or "",
        "perechetchik_2": row[3] or "",
        "perechetchik_3": row[4] or "",
        "proveril_doljnost": row[5] or "",
        "proveril_fio": row[6] or "",
    }


def save_osvetlenie_komissiya_preset(
    conn, nazvanie, perechetchik_1="", perechetchik_2="", perechetchik_3="",
    proveril_doljnost="", proveril_fio="",
):
    """Сохраняет новый пресет комиссии (UPSERT по nazvanie — повторное
    сохранение под тем же названием обновляет состав, а не плодит
    дубликаты). Возвращает id пресета."""
    conn.execute(
        "INSERT INTO osvetlenie_komissiya_preset "
        "(nazvanie, perechetchik_1, perechetchik_2, perechetchik_3, "
        "proveril_doljnost, proveril_fio) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(nazvanie) DO UPDATE SET "
        "perechetchik_1 = excluded.perechetchik_1, "
        "perechetchik_2 = excluded.perechetchik_2, "
        "perechetchik_3 = excluded.perechetchik_3, "
        "proveril_doljnost = excluded.proveril_doljnost, "
        "proveril_fio = excluded.proveril_fio",
        (
            nazvanie.strip(), perechetchik_1 or "", perechetchik_2 or "", perechetchik_3 or "",
            proveril_doljnost or "", proveril_fio or "",
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM osvetlenie_komissiya_preset WHERE nazvanie = ?", (nazvanie.strip(),)
    ).fetchone()
    return row[0]


def delete_osvetlenie_komissiya_preset(conn, preset_id):
    """Удаляет пресет комиссии экрана "Рубки ухода" по id."""
    conn.execute("DELETE FROM osvetlenie_komissiya_preset WHERE id = ?", (preset_id,))
    conn.commit()


# --------------------------------------------------------------------------- #
#   АРХИВ ДОКУМЕНТОВ (screens/archive/) — этап F
# --------------------------------------------------------------------------- #
def add_archive_document(conn, title, doc_type, doc_date, tags, file_path):
    """Сохраняет один документ архива (ручной ввод, без ИИ-распознавания).

    Возвращает id новой записи в archive_documents.
    """
    cur = conn.execute(
        "INSERT INTO archive_documents (title, doc_type, doc_date, tags, file_path) "
        "VALUES (?, ?, ?, ?, ?)",
        (title, doc_type, doc_date, tags, file_path),
    )
    conn.commit()
    return cur.lastrowid


def search_archive_documents(conn, query: str = "", doc_type: str = ""):
    """Ищет документы архива по названию/тегам/типу через SQL LIKE — вместо
    прежней in-memory фильтрации списка на экране.

    query   — подстрока для поиска в title/tags/doc_type (пусто — без фильтра).
    doc_type — точный тип документа для фильтра выпадающим списком
               ("Все типы" или пусто — без фильтра по типу).
    """
    sql = (
        "SELECT id, title, doc_type, doc_date, tags, file_path, added_at "
        "FROM archive_documents WHERE 1=1"
    )
    params: list = []
    query = (query or "").strip()
    if query:
        like = f"%{query}%"
        sql += " AND (title LIKE ? OR tags LIKE ? OR doc_type LIKE ?)"
        params += [like, like, like]
    if doc_type and doc_type != "Все типы":
        sql += " AND doc_type = ?"
        params.append(doc_type)
    sql += " ORDER BY added_at DESC, id DESC"
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": row[0],
            "title": row[1],
            "doc_type": row[2],
            "doc_date": row[3],
            "tags": row[4],
            "file_path": row[5],
            "added_at": row[6],
        }
        for row in rows
    ]


# --------------------------------------------------------------------------- #
#   ПЛАН ЗАГОТОВКИ ПО МЕСЯЦАМ (harvest_plan) — этап B
# --------------------------------------------------------------------------- #
def set_harvest_plan(conn, period, plan_obyom):
    """Сохраняет/обновляет план заготовки (м3) на месяц (period — 'YYYY-MM'),
    вводимый вручную лесничим кнопкой "✏️ Задать план на месяц" на
    дашборде. UPSERT по period — повторный ввод того же месяца просто
    перезаписывает значение."""
    conn.execute(
        "INSERT INTO harvest_plan (period, plan_obyom) VALUES (?, ?) "
        "ON CONFLICT(period) DO UPDATE SET plan_obyom = excluded.plan_obyom, "
        "updated_at = datetime('now', 'localtime')",
        (period, float(plan_obyom)),
    )
    conn.commit()


def get_harvest_plan(conn, periods=None):
    """Возвращает {period: plan_obyom}. periods — необязательный список
    'YYYY-MM' для фильтра (например, последние 6 месяцев для графика на
    дашборде); без фильтра — весь сохранённый план."""
    sql = "SELECT period, plan_obyom FROM harvest_plan"
    params: list = []
    if periods:
        placeholders = ",".join("?" for _ in periods)
        sql += f" WHERE period IN ({placeholders})"
        params = list(periods)
    rows = conn.execute(sql, params).fetchall()
    return {period: plan_obyom for period, plan_obyom in rows}


# --------------------------------------------------------------------------- #
#   ЭКРАН АВТОРИЗАЦИИ ПРИ ВХОДЕ (app_login)
# --------------------------------------------------------------------------- #
def get_app_login(conn):
    """Возвращает {"fio", "dolzhnost", "lesnichestvo"}, если экран
    авторизации при входе уже пройден (строка id=1 в app_login
    существует), иначе None — тогда main.py показывает LoginScreen перед
    главным окном.

    Сброс на "нового человека за этим компьютером": удалить эту запись
    из lesovod.db (например, DB Browser for SQLite или `sqlite3
    lesovod.db "DELETE FROM app_login;"`) — при следующем запуске
    приложение снова спросит ФИО/должность."""
    try:
        row = conn.execute(
            "SELECT fio, dolzhnost, lesnichestvo FROM app_login WHERE id = 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    fio, dolzhnost, lesnichestvo = row
    return {
        "fio": fio or "",
        "dolzhnost": dolzhnost or "",
        "lesnichestvo": lesnichestvo or "",
    }


def set_app_login(conn, fio, dolzhnost="", lesnichestvo=""):
    """Сохраняет данные экрана авторизации (UPSERT единственной строки
    id=1) — вызывается один раз, когда лесничий заполнил и подтвердил
    LoginScreen при первом запуске. fio обязателен (LoginScreen и так не
    даёт отправить форму с пустым ФИО, но проверяем и здесь — на случай
    прямого вызова в обход интерфейса)."""
    fio = (fio or "").strip()
    if not fio:
        raise ValueError("ФИО не может быть пустым")
    dolzhnost = (dolzhnost or "").strip()
    lesnichestvo = (lesnichestvo or "").strip()
    conn.execute(
        "INSERT INTO app_login (id, fio, dolzhnost, lesnichestvo) VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET fio = excluded.fio, "
        "dolzhnost = excluded.dolzhnost, lesnichestvo = excluded.lesnichestvo",
        (fio, dolzhnost, lesnichestvo),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
#   ЭКРАН "АКТЫ ОСВИДЕТЕЛЬСТВОВАНИЯ"
# --------------------------------------------------------------------------- #
def set_delyanka_sroki(conn, delyanka_id, srok_zagotovki, srok_vyvozki):
    """Сохраняет срок окончания заготовки/вывозки по делянке (карточка
    делянки, поля вводятся вручную — в МДО их нет). Даты — строками в том
    же формате, что и остальные даты приложения (dd.mm.yyyy)."""
    conn.execute(
        "UPDATE delyanka SET srok_okonchaniya_zagotovki = ?, "
        "srok_okonchaniya_vyvozki = ? WHERE id = ?",
        (srok_zagotovki or None, srok_vyvozki or None, delyanka_id),
    )
    conn.commit()


def get_delyanka_sroki(conn, delyanka_id):
    """Возвращает (srok_zagotovki, srok_vyvozki) по делянке — обе строки
    либо None, если ещё не введены."""
    row = conn.execute(
        "SELECT srok_okonchaniya_zagotovki, srok_okonchaniya_vyvozki "
        "FROM delyanka WHERE id = ?",
        (delyanka_id,),
    ).fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


def ensure_checklist(conn, delyanka_id, standard_items):
    """Заводит чек-лист подготовки к освидетельствованию для делянки при
    первом обращении (если у неё ещё нет НИ ОДНОГО пункта) — засеивает
    стандартными пунктами из standard_items (список строк, см.
    STANDARD_CHECKLIST_ITEMS в screens/inspection/screen.py). Повторный
    вызов ничего не делает, если пункты уже есть — не плодит дубликаты
    при каждом открытии экрана."""
    count = conn.execute(
        "SELECT COUNT(*) FROM osvidetelstvovanie_checklist WHERE delyanka_id = ?",
        (delyanka_id,),
    ).fetchone()[0]
    if count > 0:
        return
    for text in standard_items:
        conn.execute(
            "INSERT INTO osvidetelstvovanie_checklist (delyanka_id, text, is_custom) "
            "VALUES (?, ?, 0)",
            (delyanka_id, text),
        )
    conn.commit()


def ensure_checklists_batch(conn, delyanka_ids, standard_items):
    """То же самое, что ensure_checklist(), но за ОДИН проход по списку
    delyanka_ids — один запрос на подсчёт уже имеющихся пунктов вместо
    отдельного запроса на каждую делянку (используется InspectionLoadWorker,
    который иначе открывал бы по 2-3 отдельных соединения на карточку —
    см. screens/inspection/workers.py)."""
    delyanka_ids = list(delyanka_ids)
    if not delyanka_ids:
        return
    placeholders = ",".join("?" * len(delyanka_ids))
    rows = conn.execute(
        f"SELECT delyanka_id, COUNT(*) FROM osvidetelstvovanie_checklist "
        f"WHERE delyanka_id IN ({placeholders}) GROUP BY delyanka_id",
        delyanka_ids,
    ).fetchall()
    already_has = {row[0] for row in rows}
    to_seed = [d for d in delyanka_ids if d not in already_has]
    if not to_seed:
        return
    conn.executemany(
        "INSERT INTO osvidetelstvovanie_checklist (delyanka_id, text, is_custom) "
        "VALUES (?, ?, 0)",
        [(d, text) for d in to_seed for text in standard_items],
    )
    conn.commit()


def get_checklist(conn, delyanka_id):
    """Возвращает список пунктов чек-листа делянки:
    [{"id", "text", "is_done", "is_custom"}, ...], в порядке добавления."""
    rows = conn.execute(
        "SELECT id, text, is_done, is_custom FROM osvidetelstvovanie_checklist "
        "WHERE delyanka_id = ? ORDER BY id",
        (delyanka_id,),
    ).fetchall()
    return [
        {"id": r[0], "text": r[1], "is_done": bool(r[2]), "is_custom": bool(r[3])}
        for r in rows
    ]


def get_checklists_batch(conn, delyanka_ids):
    """То же, что get_checklist(), но для НЕСКОЛЬКИХ делянок за один запрос
    — возвращает {delyanka_id: [{"id","text","is_done","is_custom"}, ...]}.
    Делянки без единого пункта чек-листа в словаре не появляются (пустой
    список на стороне вызывающего кода — см. .get(delyanka_id, []))."""
    delyanka_ids = list(delyanka_ids)
    if not delyanka_ids:
        return {}
    placeholders = ",".join("?" * len(delyanka_ids))
    rows = conn.execute(
        f"SELECT delyanka_id, id, text, is_done, is_custom "
        f"FROM osvidetelstvovanie_checklist WHERE delyanka_id IN ({placeholders}) "
        f"ORDER BY delyanka_id, id",
        delyanka_ids,
    ).fetchall()
    result = {}
    for delyanka_id, item_id, text, is_done, is_custom in rows:
        result.setdefault(delyanka_id, []).append(
            {"id": item_id, "text": text, "is_done": bool(is_done), "is_custom": bool(is_custom)}
        )
    return result


def add_checklist_item(conn, delyanka_id, text):
    """Добавляет пользовательский пункт чек-листа (is_custom=1)."""
    cur = conn.execute(
        "INSERT INTO osvidetelstvovanie_checklist (delyanka_id, text, is_custom) "
        "VALUES (?, ?, 1)",
        (delyanka_id, text.strip()),
    )
    conn.commit()
    return cur.lastrowid


def set_checklist_item_done(conn, item_id, is_done):
    conn.execute(
        "UPDATE osvidetelstvovanie_checklist SET is_done = ? WHERE id = ?",
        (1 if is_done else 0, item_id),
    )
    conn.commit()


def delete_checklist_item(conn, item_id):
    conn.execute("DELETE FROM osvidetelstvovanie_checklist WHERE id = ?", (item_id,))
    conn.commit()


def list_osvidetelstvovanie_presets(conn):
    """Список сохранённых пресетов акта освидетельствования —
    [{"nazvanie", "predsedatel_dolzhnost", "predsedatel_fio", "chleny",
    "oblast_rayon", "predstavitel_lesxoza_dolzhnost",
    "predstavitel_lesxoza_fio", "lesopolz_organizatsiya",
    "lesopolz_dolzhnost", "lesopolz_fio", "sign_lesopolz_dolzhnost",
    "sign_lesopolz_fio", "vid_osvidetelstvovaniya", "sposob_rubki",
    "sposob_ucheta", "sposob_ochistki", "rukovoditel_dolzhnost",
    "rukovoditel_fio"}]. chleny — уже распарсенный список
    [{"dolzhnost","fio"}, ...] (хранится в БД как JSON-строка
    chleny_json). Помимо состава комиссии, пресет хранит и остальные
    "организационные" поля акта, которые обычно не меняются от делянки к
    делянке (см. комментарий над CREATE TABLE
    osvidetelstvovanie_komissiya_preset в SCHEMA)."""
    rows = conn.execute(
        "SELECT nazvanie, predsedatel_dolzhnost, predsedatel_fio, chleny_json, "
        "oblast_rayon, predstavitel_lesxoza_dolzhnost, predstavitel_lesxoza_fio, "
        "lesopolz_organizatsiya, lesopolz_dolzhnost, lesopolz_fio, "
        "sign_lesopolz_dolzhnost, sign_lesopolz_fio, vid_osvidetelstvovaniya, "
        "sposob_rubki, sposob_ucheta, sposob_ochistki, "
        "rukovoditel_dolzhnost, rukovoditel_fio "
        "FROM osvidetelstvovanie_komissiya_preset ORDER BY nazvanie"
    ).fetchall()
    result = []
    for row in rows:
        (nazvanie, pred_dolzhnost, pred_fio, chleny_json,
         oblast_rayon, predstavitel_lesxoza_dolzhnost, predstavitel_lesxoza_fio,
         lesopolz_organizatsiya, lesopolz_dolzhnost, lesopolz_fio,
         sign_lesopolz_dolzhnost, sign_lesopolz_fio, vid_osvidetelstvovaniya,
         sposob_rubki, sposob_ucheta, sposob_ochistki,
         rukovoditel_dolzhnost, rukovoditel_fio) = row
        try:
            chleny = json.loads(chleny_json) if chleny_json else []
        except (TypeError, ValueError):
            chleny = []
        result.append({
            "nazvanie": nazvanie,
            "predsedatel_dolzhnost": pred_dolzhnost or "",
            "predsedatel_fio": pred_fio or "",
            "chleny": chleny,
            "oblast_rayon": oblast_rayon or "",
            "predstavitel_lesxoza_dolzhnost": predstavitel_lesxoza_dolzhnost or "",
            "predstavitel_lesxoza_fio": predstavitel_lesxoza_fio or "",
            "lesopolz_organizatsiya": lesopolz_organizatsiya or "",
            "lesopolz_dolzhnost": lesopolz_dolzhnost or "",
            "lesopolz_fio": lesopolz_fio or "",
            "sign_lesopolz_dolzhnost": sign_lesopolz_dolzhnost or "",
            "sign_lesopolz_fio": sign_lesopolz_fio or "",
            "vid_osvidetelstvovaniya": vid_osvidetelstvovaniya or "",
            "sposob_rubki": sposob_rubki or "",
            "sposob_ucheta": sposob_ucheta or "",
            "sposob_ochistki": sposob_ochistki or "",
            "rukovoditel_dolzhnost": rukovoditel_dolzhnost or "",
            "rukovoditel_fio": rukovoditel_fio or "",
        })
    return result


def save_osvidetelstvovanie_preset(
    conn, nazvanie, predsedatel_dolzhnost, predsedatel_fio, chleny,
    oblast_rayon="", predstavitel_lesxoza_dolzhnost="", predstavitel_lesxoza_fio="",
    lesopolz_organizatsiya="", lesopolz_dolzhnost="", lesopolz_fio="",
    sign_lesopolz_dolzhnost="", sign_lesopolz_fio="", vid_osvidetelstvovaniya="",
    sposob_rubki="", sposob_ucheta="", sposob_ochistki="",
    rukovoditel_dolzhnost="", rukovoditel_fio="",
):
    """Сохраняет/обновляет (UPSERT по nazvanie) пресет акта
    освидетельствования. chleny — список [{"dolzhnost": str, "fio": str},
    ...]. Остальные параметры — организационные поля акта, которые обычно
    не меняются от делянки к делянке (см. list_osvidetelstvovanie_presets);
    все необязательны — вызывающий код может сохранить только состав
    комиссии, как раньше, оставив остальные пустыми."""
    chleny_json = json.dumps(chleny or [], ensure_ascii=False)
    conn.execute(
        "INSERT INTO osvidetelstvovanie_komissiya_preset "
        "(nazvanie, predsedatel_dolzhnost, predsedatel_fio, chleny_json, "
        "oblast_rayon, predstavitel_lesxoza_dolzhnost, predstavitel_lesxoza_fio, "
        "lesopolz_organizatsiya, lesopolz_dolzhnost, lesopolz_fio, "
        "sign_lesopolz_dolzhnost, sign_lesopolz_fio, vid_osvidetelstvovaniya, "
        "sposob_rubki, sposob_ucheta, sposob_ochistki, "
        "rukovoditel_dolzhnost, rukovoditel_fio) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(nazvanie) DO UPDATE SET "
        "predsedatel_dolzhnost = excluded.predsedatel_dolzhnost, "
        "predsedatel_fio = excluded.predsedatel_fio, "
        "chleny_json = excluded.chleny_json, "
        "oblast_rayon = excluded.oblast_rayon, "
        "predstavitel_lesxoza_dolzhnost = excluded.predstavitel_lesxoza_dolzhnost, "
        "predstavitel_lesxoza_fio = excluded.predstavitel_lesxoza_fio, "
        "lesopolz_organizatsiya = excluded.lesopolz_organizatsiya, "
        "lesopolz_dolzhnost = excluded.lesopolz_dolzhnost, "
        "lesopolz_fio = excluded.lesopolz_fio, "
        "sign_lesopolz_dolzhnost = excluded.sign_lesopolz_dolzhnost, "
        "sign_lesopolz_fio = excluded.sign_lesopolz_fio, "
        "vid_osvidetelstvovaniya = excluded.vid_osvidetelstvovaniya, "
        "sposob_rubki = excluded.sposob_rubki, "
        "sposob_ucheta = excluded.sposob_ucheta, "
        "sposob_ochistki = excluded.sposob_ochistki, "
        "rukovoditel_dolzhnost = excluded.rukovoditel_dolzhnost, "
        "rukovoditel_fio = excluded.rukovoditel_fio",
        (
            nazvanie.strip(), predsedatel_dolzhnost or "", predsedatel_fio or "", chleny_json,
            oblast_rayon or "", predstavitel_lesxoza_dolzhnost or "", predstavitel_lesxoza_fio or "",
            lesopolz_organizatsiya or "", lesopolz_dolzhnost or "", lesopolz_fio or "",
            sign_lesopolz_dolzhnost or "", sign_lesopolz_fio or "", vid_osvidetelstvovaniya or "",
            sposob_rubki or "", sposob_ucheta or "", sposob_ochistki or "",
            rukovoditel_dolzhnost or "", rukovoditel_fio or "",
        ),
    )
    conn.commit()


def delete_osvidetelstvovanie_preset(conn, nazvanie):
    conn.execute(
        "DELETE FROM osvidetelstvovanie_komissiya_preset WHERE nazvanie = ?",
        (nazvanie,),
    )
    conn.commit()


def save_osvidetelstvovanie_act(conn, delyanka_id, act_date, data, file_path):
    """Сохраняет снимок сгенерированного акта освидетельствования (история
    по делянке) — data — произвольный dict вручную введённых полей,
    сохраняется как JSON."""
    cur = conn.execute(
        "INSERT INTO osvidetelstvovanie_acts (delyanka_id, act_date, data_json, file_path) "
        "VALUES (?, ?, ?, ?)",
        (delyanka_id, act_date or "", json.dumps(data or {}, ensure_ascii=False), file_path or ""),
    )
    conn.commit()
    return cur.lastrowid


def get_osvidetelstvovanie_act(conn, act_id):
    """Один акт по id (скачивание файла из "Истории актов", см.
    app/routers/inspection.py: download_act) — {"id","file_path"} или None."""
    row = conn.execute(
        "SELECT file_path FROM osvidetelstvovanie_acts WHERE id = ?", (act_id,)
    ).fetchone()
    if row is None:
        return None
    return {"id": act_id, "file_path": row[0]}


def list_osvidetelstvovanie_acts(conn, delyanka_id):
    """История актов по делянке, последние сверху —
    [{"id","act_date","data","file_path","created_at"}, ...]."""
    rows = conn.execute(
        "SELECT id, act_date, data_json, file_path, created_at "
        "FROM osvidetelstvovanie_acts WHERE delyanka_id = ? ORDER BY id DESC",
        (delyanka_id,),
    ).fetchall()
    result = []
    for act_id, act_date, data_json, file_path, created_at in rows:
        try:
            data = json.loads(data_json) if data_json else {}
        except (TypeError, ValueError):
            data = {}
        result.append({
            "id": act_id, "act_date": act_date, "data": data,
            "file_path": file_path, "created_at": created_at,
        })
    return result


def list_osvidetelstvovanie_acts_batch(conn, delyanka_ids):
    """То же, что list_osvidetelstvovanie_acts(), но для НЕСКОЛЬКИХ делянок
    за один запрос — {delyanka_id: [{"id","act_date","data","file_path",
    "created_at"}, ...]} (последние сверху внутри каждой делянки)."""
    delyanka_ids = list(delyanka_ids)
    if not delyanka_ids:
        return {}
    placeholders = ",".join("?" * len(delyanka_ids))
    rows = conn.execute(
        f"SELECT delyanka_id, id, act_date, data_json, file_path, created_at "
        f"FROM osvidetelstvovanie_acts WHERE delyanka_id IN ({placeholders}) "
        f"ORDER BY delyanka_id, id DESC",
        delyanka_ids,
    ).fetchall()
    result = {}
    for delyanka_id, act_id, act_date, data_json, file_path, created_at in rows:
        try:
            data = json.loads(data_json) if data_json else {}
        except (TypeError, ValueError):
            data = {}
        result.setdefault(delyanka_id, []).append({
            "id": act_id, "act_date": act_date, "data": data,
            "file_path": file_path, "created_at": created_at,
        })
    return result


# --------------------------------------------------------------------------- #
#   ЭКРАН "ЛЕСНЫЕ КУЛЬТУРЫ"
# --------------------------------------------------------------------------- #
def create_lesokultury_uchastok(conn, **fields):
    """Создаёт участок лесных культур (заводится вручную лесничим, как и
    делянка — НЕ выводится из таксации, см. комментарий у CREATE TABLE
    lesokultury_uchastok в SCHEMA). Принимает именованные поля:
    lesnichestvo, kvartal, vydel, delyanka_id, ploshad, kategoriya_ploshadi,
    tlu, god_sozdaniya, metod_sozdaniya, glavnaya_poroda, sostav_formula,
    gustota_posadki, normativ_perevoda, primechaniya — все необязательны
    (кроме того, что решит вызывающий код на экране)."""
    columns = [
        "lesnichestvo", "kvartal", "vydel", "delyanka_id", "ploshad",
        "kategoriya_ploshadi", "tlu", "god_sozdaniya", "metod_sozdaniya",
        "glavnaya_poroda", "sostav_formula", "gustota_posadki",
        "normativ_perevoda", "primechaniya",
    ]
    values = [fields.get(col) for col in columns]
    placeholders = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"INSERT INTO lesokultury_uchastok ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    return cur.lastrowid


def update_lesokultury_uchastok(conn, uchastok_id, **fields):
    """Обновляет поля участка культур (те же поля, что и в
    create_lesokultury_uchastok, плюс status) — только переданные."""
    allowed = {
        "lesnichestvo", "kvartal", "vydel", "delyanka_id", "ploshad",
        "kategoriya_ploshadi", "tlu", "god_sozdaniya", "metod_sozdaniya",
        "glavnaya_poroda", "sostav_formula", "gustota_posadki",
        "normativ_perevoda", "status", "primechaniya",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{col} = ?" for col in updates)
    conn.execute(
        f"UPDATE lesokultury_uchastok SET {set_clause} WHERE id = ?",
        [*updates.values(), uchastok_id],
    )
    conn.commit()


def get_lesokultury_uchastki(conn, include_spisannye=False, god=None, search=None):
    """Возвращает список участков лесных культур —
    [{"id","lesnichestvo","kvartal","vydel","delyanka_id","delyanka_nazvanie",
      "ploshad","kategoriya_ploshadi","tlu","god_sozdaniya","metod_sozdaniya",
      "glavnaya_poroda","sostav_formula","gustota_posadki",
      "normativ_perevoda","status","primechaniya","created_at",
      "last_uhod_tip","last_uhod_data"}, ...],
    активные участки сначала (переведённые/списанные — в конце, если
    include_spisannye=True; иначе не включаются вовсе).

    god — фильтр по году создания культур (сравнивается как текст с
    god_sozdaniya, т.к. поле в БД текстовое — год встречается и как
    "2023", и изредка как "2023 (весна)").
    search — свободный поиск по кварталу/выделу/лесничеству/главной
    породе участка, а также по названию связанной делянки (через
    LEFT JOIN на delyanka), регистронезависимо, подстрокой.
    last_uhod_tip/last_uhod_data — тип и дата последнего мероприятия
    журнала участка с tip, похожим на уход (агротехнический/химический
    уход или запись, автоматически заведённая пробой рубок ухода —
    см. mark_uhody_proba_completed) — для пометки на списке «уход
    выполнен» без открытия карточки."""
    where = []
    params = []
    if god:
        where.append("lk.god_sozdaniya LIKE ?")
        params.append(f"%{god}%")
    if search:
        where.append(
            "(lk.kvartal LIKE ? OR lk.vydel LIKE ? OR lk.lesnichestvo LIKE ? "
            "OR lk.glavnaya_poroda LIKE ? OR d.nazvanie LIKE ?)"
        )
        like = f"%{search}%"
        params.extend([like, like, like, like, like])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    try:
        rows = conn.execute(
            f"SELECT lk.id, lk.lesnichestvo, lk.kvartal, lk.vydel, lk.delyanka_id, "
            f"d.nazvanie, lk.ploshad, lk.kategoriya_ploshadi, lk.tlu, lk.god_sozdaniya, "
            f"lk.metod_sozdaniya, lk.glavnaya_poroda, lk.sostav_formula, lk.gustota_posadki, "
            f"lk.normativ_perevoda, lk.status, lk.primechaniya, lk.created_at, "
            f"(SELECT tip FROM lesokultury_meropriyatiya m WHERE m.uchastok_id = lk.id "
            f" AND (m.tip LIKE '%уход%' OR m.tip LIKE '%Уход%' OR m.proba_id IS NOT NULL) "
            f" ORDER BY m.id DESC LIMIT 1) AS last_uhod_tip, "
            f"(SELECT data FROM lesokultury_meropriyatiya m WHERE m.uchastok_id = lk.id "
            f" AND (m.tip LIKE '%уход%' OR m.tip LIKE '%Уход%' OR m.proba_id IS NOT NULL) "
            f" ORDER BY m.id DESC LIMIT 1) AS last_uhod_data "
            f"FROM lesokultury_uchastok lk LEFT JOIN delyanka d ON d.id = lk.delyanka_id "
            f"{where_sql} "
            f"ORDER BY (lk.status = 'активен') DESC, lk.id DESC",
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    columns = [
        "id", "lesnichestvo", "kvartal", "vydel", "delyanka_id", "delyanka_nazvanie", "ploshad",
        "kategoriya_ploshadi", "tlu", "god_sozdaniya", "metod_sozdaniya",
        "glavnaya_poroda", "sostav_formula", "gustota_posadki",
        "normativ_perevoda", "status", "primechaniya", "created_at",
        "last_uhod_tip", "last_uhod_data",
    ]
    result = [dict(zip(columns, row)) for row in rows]
    if not include_spisannye:
        result = [r for r in result if r["status"] == "активен"]
    return result


def get_lesokultury_gody(conn):
    """Возвращает отсортированный список различных годов создания культур
    (god_sozdaniya), встречающихся в базе — для выпадающего фильтра
    «Год» на экране «Лесные культуры», вместо свободного текстового
    поля. Пустые/NULL значения не включаются."""
    try:
        rows = conn.execute(
            "SELECT DISTINCT god_sozdaniya FROM lesokultury_uchastok "
            "WHERE god_sozdaniya IS NOT NULL AND TRIM(god_sozdaniya) != '' "
            "ORDER BY god_sozdaniya DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [row[0] for row in rows]


def get_lesokultury_uchastok(conn, uchastok_id):
    """Один участок культур по id, либо None."""
    row = conn.execute(
        "SELECT lk.id, lk.lesnichestvo, lk.kvartal, lk.vydel, lk.delyanka_id, d.nazvanie, "
        "lk.ploshad, lk.kategoriya_ploshadi, lk.tlu, lk.god_sozdaniya, lk.metod_sozdaniya, "
        "lk.glavnaya_poroda, lk.sostav_formula, lk.gustota_posadki, lk.normativ_perevoda, "
        "lk.status, lk.primechaniya, lk.created_at "
        "FROM lesokultury_uchastok lk LEFT JOIN delyanka d ON d.id = lk.delyanka_id "
        "WHERE lk.id = ?",
        (uchastok_id,),
    ).fetchone()
    if row is None:
        return None
    columns = [
        "id", "lesnichestvo", "kvartal", "vydel", "delyanka_id", "delyanka_nazvanie", "ploshad",
        "kategoriya_ploshadi", "tlu", "god_sozdaniya", "metod_sozdaniya",
        "glavnaya_poroda", "sostav_formula", "gustota_posadki",
        "normativ_perevoda", "status", "primechaniya", "created_at",
    ]
    return dict(zip(columns, row))


def delete_lesokultury_uchastok(conn, uchastok_id):
    """Удаляет участок культур ВМЕСТЕ с его журналом мероприятий (полное
    удаление — для случая "завели по ошибке"; чтобы просто списать
    погибший участок, используйте update_lesokultury_uchastok(status=
    'списан') + добавьте мероприятие "Списание", это сохраняет историю)."""
    conn.execute("DELETE FROM lesokultury_meropriyatiya WHERE uchastok_id = ?", (uchastok_id,))
    conn.execute("DELETE FROM lesokultury_uchastok WHERE id = ?", (uchastok_id,))
    conn.commit()


def add_lesokultury_meropriyatie(conn, uchastok_id, tip, data, prizhivaemost_pct=None,
                                  kolichestvo_na_ga=None, sostav_fakt="", primechaniya="",
                                  proba_id=None, dannye=None, sotrudnik_id=None):
    """Добавляет запись в журнал ухода за участком лесных культур —
    tip: 'Техническая приёмка' / 'Инвентаризация 1-го года' /
    'Инвентаризация 3-го года' / 'Инвентаризация на перевод' /
    'Внеплановая инвентаризация' / 'Агротехнический уход' /
    'Химический уход' / 'Дополнение' / 'Перевод в покрытые лесом земли' /
    'Списание' / произвольный текст.
    proba_id — заполняется автоматически, когда запись заведена отметкой
    пробы рубок ухода выполненной (см. mark_uhody_proba_completed);
    для ручных записей (карточка участка) остаётся None.
    dannye — dict с данными полевой карточки (сохраняется как JSON),
    sotrudnik_id — кто ввёл запись с телефона; для записей с веба оба None."""
    cur = conn.execute(
        "INSERT INTO lesokultury_meropriyatiya "
        "(uchastok_id, tip, data, prizhivaemost_pct, kolichestvo_na_ga, sostav_fakt, primechaniya, proba_id, "
        "dannye_json, sotrudnik_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (uchastok_id, tip.strip(), (data or "").strip(), prizhivaemost_pct, kolichestvo_na_ga,
         (sostav_fakt or "").strip(), (primechaniya or "").strip(), proba_id,
         json.dumps(dannye, ensure_ascii=False) if dannye is not None else None, sotrudnik_id),
    )
    conn.commit()
    return cur.lastrowid


def list_lesokultury_meropriyatiya(conn, uchastok_id):
    """История мероприятий по участку, последние сверху —
    [{"id","tip","data","prizhivaemost_pct","kolichestvo_na_ga","sostav_fakt",
      "primechaniya","proba_id","created_at","dannye","sotrudnik_id"}, ...];
    dannye — разобранный dannye_json (None для записей с веба)."""
    rows = conn.execute(
        "SELECT id, tip, data, prizhivaemost_pct, kolichestvo_na_ga, sostav_fakt, "
        "primechaniya, proba_id, created_at, dannye_json, sotrudnik_id "
        "FROM lesokultury_meropriyatiya WHERE uchastok_id = ? ORDER BY id DESC",
        (uchastok_id,),
    ).fetchall()
    return [
        {"id": r[0], "tip": r[1], "data": r[2], "prizhivaemost_pct": r[3],
         "kolichestvo_na_ga": r[4], "sostav_fakt": r[5], "primechaniya": r[6],
         "proba_id": r[7], "created_at": r[8],
         "dannye": json.loads(r[9]) if r[9] else None, "sotrudnik_id": r[10]}
        for r in rows
    ]


if __name__ == "__main__":
    import sys
    docx_paths = sys.argv[1:] if len(sys.argv) > 1 else ["/mnt/user-data/uploads/ТАКС_Описа_Образец.docx"]
    conn = build_db(docx_paths, db_path="lesovod.db")
    print("\n--- Пример карточки участка: квартал 1, выдел 42 ---")
    card = get_vydel_card(conn, 1, "42")
    print(json.dumps(card, ensure_ascii=False, indent=2))