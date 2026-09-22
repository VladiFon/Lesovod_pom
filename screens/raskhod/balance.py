#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Экраны "Учет заготовки" (Книга расхода леса) и "Рубки ухода" (Осветление).

Классы:
    RaskhodScreen     — учёт заготовки: баланс лимит/факт/остаток, наряды.
    OsvetlenieScreen  — рубки ухода: пробы перечёта, экспорт по шаблону .docx.
"""

import json
import re
import sqlite3
from datetime import datetime

# TODO п.1.6 (аудит Этапа 0): этот файл исторически получил в шапку
# PySide6.QtCore/QtGui/QtWidgets (плюс ai_vision/config/db/delyanka/
# screens.plots.PlotsScreen) при автоматическом разбиении бывшего
# screens/raskhod.py на модули по экрану — общий заголовок был
# продублирован в каждый файл-фрагмент "для самодостаточности", без
# проверки, что каждый фрагмент реально использует. По факту же все
# функции ниже (get_limits/compute_balance/compute_items_totals и т.д.)
# — чистые вычисления над conn/dict, ни одна из них не создаёт и не
# принимает ни одного Qt-объекта. Импорты, которые нигде в этом файле не
# использовались, удалены (см. историю git при необходимости сверить):
# PySide6.*, os, shutil, sys, pathlib.Path, ai_vision, config,
# screens.plots.PlotsScreen, db.get_vydel_card/migrate_schema/
# save_uhody_proba/list_uhody_proby/get_uhody_proba/delete_uhody_proba,
# delyanka.get_delyanka_full/save_komissiya_preset — все они относились к
# Qt-экрану (RaskhodScreen/OsvetlenieScreen), который на самом деле живёт
# в screens/raskhod/screen.py, а не в этом файле. Модуль теперь не тянет
# PySide6 при импорте и его функции можно переиспользовать из веб-бэкенда
# без десктопных зависимостей (см. backend/legacy/raskhod_v2.py — там уже
# лежит Qt-свободная копия этих же функций для web).

# ======================================================================= #
#   БЭКЕНД МОДУЛЯ 3 — Учёт заготовки (Книга расхода леса)
# ======================================================================= #
# Раньше этот функционал жил в отдельном файле raskhod.py и подключался
# как `import raskhod as rk`. Он встроен прямо сюда (единый файл экрана),
# со всеми функциями:
#   get_limits(item) — лимиты по делянке из данных МДО (poroda_volumes);
#   строится по ФАКТИЧЕСКИ присутствующим в МДО породам, а не по жёсткому
#   списку — иначе порода, заготовленная только на дрова и отсутствующая
#   в старом списке ALL_SPECIES, молча выпадала из лимитов.
#   compute_balance(conn, item, item_id) — считает баланс лимит/факт/остаток
#   по породам и сортиментам для конкретного выдела; item — ПОЛНЫЙ словарь
#   delyanka_item (нужен mdo_raw_json, из него достаются лимиты); единообразно
#   отдаёт все 4 сортимента (KR/SR/ML/DROVA) для любой породы;
#   create_naryad(conn, delyanka_id, item_id, data, nomer_naryada, ploshad,
#   primechanie, pozitsii) — записывает наряд; pozitsii — список
#   {"poroda", "sortiment": "KR"/"SR"/"ML"/"DROVA"/"HVOROST", "obyom"};
#   export_to_excel(conn, delyanka, item, output_path, templates_dir) —
#   выгружает Книгу расхода леса по конкретному выделу в .xlsx.
#
# ------------------------------------------------------------------- #

# деловая древесина с разбивкой на крупную/среднюю/мелкую — используется
# только косметически (пока нигде не влияет на состав лимитов, см. ниже).
SPECIES_WITH_GRADES = ["Е", "С", "Б", "ОС", "Д", "ОЛЧ"]
# деловая древесина без разбивки (учитывается одной суммой)
SPECIES_NO_GRADES = ["Р", "ОЛС"]
ALL_SPECIES = SPECIES_WITH_GRADES + SPECIES_NO_GRADES
# ВАЖНО: ALL_SPECIES/SPECIES_WITH_GRADES/SPECIES_NO_GRADES раньше служили
# ФИКСИРОВАННЫМ списком, по которому get_limits() отбирал породы — то есть
# порода из МДО, которой в этом списке не было (мало- или неценные породы
# вроде ивы/липы/клёна/тополя, которые чаще всего идут ТОЛЬКО на дрова —
# отсюда и жалоба "породы только с дровами не попадают в учёт заготовки"),
# в лимиты вообще не попадала и не показывалась на экране "Учет заготовки",
# даже если реально числилась в ведомости МДО. Теперь get_limits() строит
# лимиты по ФАКТИЧЕСКИ присутствующим в МДО породам (см. ниже) — список
# оставлен только для читаемости кода, но больше ничего не фильтрует.

SORTIMENT_LABELS = {
    "KR": "деловая крупная", "SR": "деловая средняя", "ML": "деловая мелкая",
    "DROVA": "дрова", "HVOROST": "хворост",
}

RASKHOD_TEMPLATE = "raskhod_shablon.xlsx"


# --- Заголовки выгрузки ЕГАИС "Реестр движения по складам" (как они реально
# приходят в .xlsx-файле - с "родными" опечатками/пробелами ЕГАИС, менять
# нельзя, иначе не найдём колонку) ---
_EGAIS_COL_KVARTAL = "Номер лесного квартала"
_EGAIS_COL_VYDEL = "Номер таксационного выдела "  # именно с пробелом в конце
_EGAIS_COL_OBYOM = "Объем"
_EGAIS_COL_DOC_TYPE = "Тип документа"
_EGAIS_COL_DOC_NUM = "Номер документа"
_EGAIS_COL_SKLAD_ID = "id Склад операции"
_EGAIS_COL_SKLAD_NAME = "Склад операции"
_EGAIS_COL_OSNOVANIE = "Основание"
_EGAIS_COL_OSNOVANIE_NUM = "Номер основания"
_EGAIS_COL_LINKED_DOC = "Номер связанного  документа"  # да, два пробела - так в выгрузке
_EGAIS_COL_PORODA = "Порода"
_EGAIS_COL_SORT = "Сорт"
_EGAIS_COL_GODNOST = "Техническая годность"

_EGAIS_DOC_TYPE_PRIHOD = "Приход"
_EGAIS_DOC_TYPE_VNUTR_PEREMESHENIE = "Расход при внутреннем перемещении"

# Автосгенерировано разбиением screens/raskhod.py на модули по экрану.
# Общий заголовок (импорты/константы модуля) продублирован в каждом файле,
# чтобы каждый файл оставался самодостаточным и поведение не изменилось.


def _item_poroda_volumes(item):
    raw = item.get("mdo_raw_json")
    if not raw:
        return {}
    try:
        mdo = json.loads(raw)
        return mdo.get("poroda_volumes", {})
    except (json.JSONDecodeError, TypeError):
        return {}


def get_limits(item):
    """Возвращает лимиты по делянке: {порода: {KR, SR, ML, DROVA}} (м3),
    взятые из данных МДО, сохранённых в этом выделе.

    Строится по ФАКТИЧЕСКИ присутствующим в МДО породам (ключи
    poroda_volumes из mdo_parser), а НЕ по фиксированному списку ALL_SPECIES
    — раньше порода, отсутствующая в этом списке (например, малоценная
    порода, заготовленная только на дрова), молча выпадала из лимитов, хотя
    реально числилась в ведомости. "Итого по лесосеке" — служебная строка
    mdo_parser с суммой по всей лесосеке, а не порода — исключаем явно."""
    volumes = _item_poroda_volumes(item)
    limits = {}
    for poroda, v in volumes.items():
        if not v or poroda == "Итого по лесосеке":
            continue
        limits[poroda] = {
            "KR": v.get("krupnaya") or 0,
            "SR": v.get("srednyaya") or 0,
            "ML": v.get("melkaya") or 0,
            "DROVA": v.get("drovyanaya") or 0,
        }
    return limits


def create_naryad(conn, delyanka_id, item_id, data, nomer_naryada="", ploshad="", primechanie="", pozitsii=None):
    """pozitsii: список {"poroda":.., "sortiment": "KR"/"SR"/"ML"/"DROVA"/"HVOROST", "obyom": float}"""
    cur = conn.execute(
        """INSERT INTO raskhod_naryad (delyanka_id, item_id, data, nomer_naryada, ploshad, primechanie)
           VALUES (?,?,?,?,?,?)""",
        (delyanka_id, item_id, data, nomer_naryada, ploshad, primechanie),
    )
    naryad_id = cur.lastrowid
    for p in (pozitsii or []):
        if not p.get("obyom"):
            continue
        conn.execute(
            "INSERT INTO raskhod_pozitsiya (naryad_id, poroda, sortiment, obyom) VALUES (?,?,?,?)",
            (naryad_id, p["poroda"], p["sortiment"], float(p["obyom"])),
        )
    conn.commit()
    return naryad_id


def update_naryad(conn, naryad_id, data=None, nomer_naryada=None, ploshad=None, primechanie=None, pozitsii=None):
    fields = {}
    if data is not None:
        fields["data"] = data
    if nomer_naryada is not None:
        fields["nomer_naryada"] = nomer_naryada
    if ploshad is not None:
        fields["ploshad"] = ploshad
    if primechanie is not None:
        fields["primechanie"] = primechanie
    if fields:
        set_clause = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE raskhod_naryad SET {set_clause} WHERE id=?", (*fields.values(), naryad_id))
    if pozitsii is not None:
        conn.execute("DELETE FROM raskhod_pozitsiya WHERE naryad_id=?", (naryad_id,))
        for p in pozitsii:
            if not p.get("obyom"):
                continue
            conn.execute(
                "INSERT INTO raskhod_pozitsiya (naryad_id, poroda, sortiment, obyom) VALUES (?,?,?,?)",
                (naryad_id, p["poroda"], p["sortiment"], float(p["obyom"])),
            )
    conn.commit()


def delete_naryad(conn, naryad_id):
    conn.execute("DELETE FROM raskhod_pozitsiya WHERE naryad_id=?", (naryad_id,))
    conn.execute("DELETE FROM raskhod_naryad WHERE id=?", (naryad_id,))
    conn.commit()


def list_naryady(conn, item_id):
    """Список нарядов по выделу, с позициями, отсортировано по дате."""
    rows = conn.execute(
        "SELECT * FROM raskhod_naryad WHERE item_id=? ORDER BY data, id", (item_id,)
    ).fetchall()
    cols = [d[0] for d in conn.execute(
        "SELECT * FROM raskhod_naryad WHERE item_id=? ORDER BY data, id", (item_id,)
    ).description]
    naryady = [dict(zip(cols, r)) for r in rows]
    for n in naryady:
        prows = conn.execute(
            "SELECT poroda, sortiment, obyom FROM raskhod_pozitsiya WHERE naryad_id=?", (n["id"],)
        ).fetchall()
        n["pozitsii"] = [{"poroda": p, "sortiment": s, "obyom": o} for p, s, o in prows]
    return naryady


def _build_balance(item, fakt):
    """Собирает {порода: {KR/SR/ML/DROVA/HVOROST: {limit, limit_110, fakt,
    ostatok, ostatok_110}}} по лимитам выдела (item, из МДО) и уже
    посчитанному факту (fakt = {порода: {сортимент: объём}}).

    Общая часть compute_balance()/compute_balance_batch() (Этап 3 плана
    оптимизации), вынесенная отдельно, чтобы запрос к БД и сборка
    результата не дублировались в двух местах — раньше эта сборка была
    только внутри compute_balance(), а compute_balance_batch() пришлось бы
    либо копировать её, либо вызывать compute_balance() в цикле (что как
    раз и убирает батчинг)."""
    limits = get_limits(item)
    balance = {}
    all_porody = set(limits.keys()) | set(fakt.keys())
    for poroda in all_porody:
        balance[poroda] = {}
        # Раньше здесь был выбор по SPECIES_WITH_GRADES/иначе KR+DROVA —
        # но mdo_parser отдаёт крупную/среднюю/мелкую по КАЖДОЙ породе
        # (даже если это просто 0 — например, если у породы вообще нет
        # деловой), так что показывать/принимать наряд можно по всем 4
        # сортиментам единообразно, без завязки на список пород.
        sortiments = ["KR", "SR", "ML", "DROVA"]
        for s in sortiments:
            limit = limits.get(poroda, {}).get(s, 0)
            f = fakt.get(poroda, {}).get(s, 0)
            balance[poroda][s] = {
                "limit": limit,
                "limit_110": limit * 1.1,
                "fakt": f,
                "ostatok": limit - f,
                "ostatok_110": limit * 1.1 - f,
            }
        # хворост - без лимита, просто фактический учёт
        hvorost_fakt = fakt.get(poroda, {}).get("HVOROST", 0)
        if hvorost_fakt:
            balance[poroda]["HVOROST"] = {
                "limit": None, "limit_110": None, "fakt": hvorost_fakt,
                "ostatok": None, "ostatok_110": None,
            }
    return balance


def compute_balance_batch(conn, items):
    """То же самое, что compute_balance(), но для СПИСКА выделов сразу —
    ОДНИМ запросом к БД (WHERE n.item_id IN (...)) вместо одного запроса
    на каждый item_id (Этап 3 плана оптимизации — "что осталось" из
    Этапа 2: этот SQL был последней частью загрузки экрана "Акты
    освидетельствования", которая ещё делала запрос на каждый ВЫДЕЛ).

    items — список ПОЛНЫХ словарей delyanka_item (нужны id и mdo_raw_json).
    Возвращает {item_id: <тот же формат словаря, что у compute_balance()>}.
    Порода/выдел без единого наряда всё равно попадёт в результат (с
    fakt=0), как и раньше — просто fakt для него не находится в rows.
    """
    items = list(items)
    if not items:
        return {}
    item_ids = [item["id"] for item in items]
    placeholders = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"""SELECT n.item_id, p.poroda, p.sortiment, SUM(p.obyom)
            FROM raskhod_pozitsiya p JOIN raskhod_naryad n ON p.naryad_id = n.id
            WHERE n.item_id IN ({placeholders})
            GROUP BY n.item_id, p.poroda, p.sortiment""",
        item_ids,
    ).fetchall()
    fakt_by_item = {}
    for item_id, poroda, sortiment, total in rows:
        fakt_by_item.setdefault(item_id, {}).setdefault(poroda, {})[sortiment] = total or 0

    return {
        item["id"]: _build_balance(item, fakt_by_item.get(item["id"], {}))
        for item in items
    }


def compute_balance(conn, item, item_id):
    """Возвращает {порода: {KR/SR/ML/DROVA: {limit, limit_110, fakt, ostatok, ostatok_110}}}
    для ОДНОГО выдела.

    Этап 3: теперь просто обёртка над compute_balance_batch() с списком из
    одного элемента — тот же SQL и та же сборка результата, что и в
    батч-версии, без дублирования логики. Сигнатура и поведение для
    вызывающего кода не изменились (screens/raskhod/screen.py,
    get_remaining_volumes_for_bot и т.д. продолжают работать как раньше)."""
    lookup_item = item if item.get("id") == item_id else {**item, "id": item_id}
    return compute_balance_batch(conn, [lookup_item]).get(item_id, _build_balance(item, {}))


# МДО породы хранятся короткими кодами (см. ALL_SPECIES выше) — если у
# вас в проекте уже есть такой словарь в другом месте, лучше
# переиспользовать его вместо этого.
POROda_DISPLAY_NAMES = {
    "Е": "Ель", "С": "Сосна", "Б": "Береза", "ОС": "Осина",
    "Д": "Дуб", "ОЛЧ": "Ольха черная", "Р": "Разные", "ОЛС": "Ольха серая",
}


def _poroda_label(poroda):
    return POROda_DISPLAY_NAMES.get(poroda, poroda)


def canonical_poroda(poroda):
    """Приводит название породы к единому ключу для сопоставления МДО
    (короткие коды "Е"/"С"/...) и ЕГАИС (полные названия "Ель"/"Сосна"/...,
    иногда с иным регистром, буквой "ё" или лишним пробелом) — без этой
    нормализации сравнение по строковому равенству не совпадает и порода
    задваивается как "лимита нет, но заготовка идёт" (см. тот же фикс и
    его обоснование на реальных данных в raskhod.py — точка для
    Telegram-бота; здесь — та же логика для экрана "Учёт заготовки")."""
    if not poroda:
        return poroda
    s = str(poroda).strip()
    if s in POROda_DISPLAY_NAMES:
        return POROda_DISPLAY_NAMES[s]
    normalized = " ".join(s.replace("ё", "е").replace("Ё", "Е").split())
    for full_name in POROda_DISPLAY_NAMES.values():
        full_norm = full_name.replace("ё", "е").replace("Ё", "Е")
        if normalized.casefold() == full_norm.casefold():
            return full_name
    return normalized


def _parse_db_datetime(value):
    """Превращает значение created_at (TEXT DEFAULT datetime('now',
    'localtime')) из SQLite в datetime. На всякий случай пробуем
    несколько форматов."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
                "%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _extract_vydel_numbers(value):
    """Извлекает все числа из значения выдела в множество строк —
    используется для "умного" сравнения. И искомый vydel, и значение
    delyanka_item.vydel в БД могут быть составными: '17, 33', список
    ['17', '33'], либо просто '17'. str(value) + regex одинаково
    нормализует все эти варианты в {'17', '33'}."""
    return set(re.findall(r"\d+", str(value)))


def get_remaining_volumes_for_bot(conn, kvartal, vydel, lesoseka=None):
    """Считает остаток лимита (Лимит - Факт) по кварталу/выделу для ответа
    Telegram-боту на вопрос мастера "сколько осталось". Переиспользует
    compute_balance(), которым уже пользуется экспорт в Excel.

    "Умный" поиск по составным выделам: delyanka_item.vydel может хранить
    не одно число, а строку вида "17, 33" (несколько выделов в одной
    записи МДО), поэтому строгое SQL-сравнение vydel=? делянку не находит.
    Вместо этого из БД выбираются все записи по kvartal(+lesoseka), а
    совпадение выдела проверяется в Python — по пересечению множества
    чисел искомого vydel (тоже может прийти списком/строкой от бота) с
    множеством чисел из item['vydel']. Делянка считается найденной при
    любом непустом пересечении.

    Если пересеклось несколько записей (несколько лесосек/составных
    записей задели искомый выдел) — остатки суммируются по всем найденным.

    Возвращает:
    {
        "found": bool,
        "item_ids": [...],
        "remaining": {(poroda, sortiment): volume, ...},  # sortiment: KR/SR/ML/DROVA
        "last_update": datetime | None,
    }
    """
    query = "SELECT * FROM delyanka_item WHERE kvartal = ?"
    params = [kvartal]
    if lesoseka:
        query += " AND lesoseka_nomer = ?"
        params.append(lesoseka)
    query += " ORDER BY id"

    cur = conn.execute(query, params)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()

    if not rows:
        return {"found": False, "item_ids": [], "remaining": {}, "last_update": None}

    wanted_numbers = _extract_vydel_numbers(vydel)
    if not wanted_numbers:
        # искомый vydel не содержит ни одного числа — сравнивать не с чем
        return {"found": False, "item_ids": [], "remaining": {}, "last_update": None}

    # compute_balance()/get_limits() ожидают dict с .get() — приводим
    # строки к словарю независимо от того, установлен ли у соединения
    # row_factory = sqlite3.Row (у него .get() нет) или нет
    all_items = [dict(zip(cols, r)) for r in rows]

    # --- Умный поиск: пересечение множеств чисел искомого и хранимого vydel ---
    items = [
        item for item in all_items
        if wanted_numbers & _extract_vydel_numbers(item.get("vydel"))
    ]

    if not items:
        return {"found": False, "item_ids": [], "remaining": {}, "last_update": None}

    item_ids = [item["id"] for item in items]

    # --- Остаток: суммируем баланс по всем найденным по пересечению delyanka_item ---
    # Этап 3: один запрос на весь items вместо compute_balance() в цикле
    # (здесь items обычно 1-2 записи на составной выдел, но раз
    # compute_balance_batch() уже есть — нет смысла держать два способа
    # посчитать то же самое рядом).
    balances_by_item = compute_balance_batch(conn, items)
    remaining = {}
    for item in items:
        balance = balances_by_item.get(item["id"], {})
        for poroda, sortiments in balance.items():
            for sortiment, vals in sortiments.items():
                if vals["ostatok"] is None:
                    # хворост — без лимита, в остаток не входит
                    continue
                key = (poroda, sortiment)
                remaining[key] = remaining.get(key, 0) + vals["ostatok"]

    # --- Дата последнего обновления: самый свежий наряд по этим делянкам ---
    placeholders = ",".join("?" for _ in item_ids)
    row = conn.execute(
        f"SELECT MAX(created_at) FROM raskhod_naryad WHERE item_id IN ({placeholders})",
        item_ids,
    ).fetchone()
    last_update_raw = row[0] if row else None

    if not last_update_raw:
        # нарядов ещё не было — берём дату создания самой делянки
        delyanka_ids = sorted({item["delyanka_id"] for item in items})
        dplaceholders = ",".join("?" for _ in delyanka_ids)
        drow = conn.execute(
            f"SELECT MAX(created_at) FROM delyanka WHERE id IN ({dplaceholders})",
            delyanka_ids,
        ).fetchone()
        last_update_raw = drow[0] if drow else None

    return {
        "found": True,
        "item_ids": item_ids,
        "remaining": remaining,
        "last_update": _parse_db_datetime(last_update_raw),
    }


def _fmt_m3(value):
    """Единое форматирование объёма (м3) для UI баланса (Этап 7 плана
    доработок): округляет до 3 знаков и убирает хвостовые нули/лишнюю
    точку, чтобы `11.920000000000002` показывалось как `11.92`, а `10.0`
    — как `10`, без плавающей "грязи" из-за арифметики с float.
    None (например, лимит для Хвороста, которого в МДО нет) — показываем
    прочерком."""
    if value is None:
        return "—"
    try:
        v = round(float(value), 3)
    except (TypeError, ValueError):
        return str(value)
    return f"{v:g}"


def compute_poroda_totals(balance):
    """Агрегирует compute_balance() по породе в две итоговые группы —
    "деловая" (сумма KR+SR+ML) и "дрова" (копия строки DROVA) — плюс
    отдельно фактический объём хвороста (без лимита).

    Используется экраном "Учет заготовки" (Этап 7 плана доработок) для
    показа итоговых строк по породе в дереве баланса, без изменения
    формата, который возвращает compute_balance() (на него могут
    полагаться другие потребители, например export_to_excel()).

    Возвращает:
    {порода: {
        "delovaya": {limit, limit_110, fakt, ostatok, ostatok_110},
        "drova":    {limit, limit_110, fakt, ostatok, ostatok_110},
        "hvorost_fakt": float,
    }}
    """
    totals = {}
    for poroda, sortimenty in (balance or {}).items():
        delovaya = {"limit": 0.0, "limit_110": 0.0, "fakt": 0.0, "ostatok": 0.0, "ostatok_110": 0.0}
        for code in ("KR", "SR", "ML"):
            vals = sortimenty.get(code)
            if not vals:
                continue
            for key in delovaya:
                v = vals.get(key)
                if v is not None:
                    delovaya[key] += v

        drova_vals = sortimenty.get("DROVA") or {}
        drova = {
            "limit": drova_vals.get("limit") or 0,
            "limit_110": drova_vals.get("limit_110") or 0,
            "fakt": drova_vals.get("fakt") or 0,
            "ostatok": drova_vals.get("ostatok") if drova_vals.get("ostatok") is not None else 0,
            "ostatok_110": drova_vals.get("ostatok_110") if drova_vals.get("ostatok_110") is not None else 0,
        }

        hvorost_fakt = (sortimenty.get("HVOROST") or {}).get("fakt") or 0

        totals[poroda] = {"delovaya": delovaya, "drova": drova, "hvorost_fakt": hvorost_fakt}
    return totals


def get_delyanka_items(conn, delyanka_id):
    """Возвращает список ПОЛНЫХ словарей delyanka_item (все колонки, в т.ч.
    mdo_raw_json) для одной делянки — используется агрегатором
    compute_items_totals() (Этап B плана доработок: перерубы; заложено и
    для будущих Этапов C/D — цветовая индикация делянки и сводка по
    породам, которым нужен тот же суммарный лимит/факт по выделу)."""
    cur = conn.execute("SELECT * FROM delyanka_item WHERE delyanka_id = ?", (delyanka_id,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_delyanka_items_batch(conn, delyanka_ids):
    """То же, что get_delyanka_items(), но для НЕСКОЛЬКИХ делянок за один
    запрос — {delyanka_id: [items...]}. Используется экраном "Акты
    освидетельствования" (InspectionLoadWorker), который раньше делал
    отдельный SELECT на каждую делянку в списке."""
    delyanka_ids = list(delyanka_ids)
    if not delyanka_ids:
        return {}
    placeholders = ",".join("?" * len(delyanka_ids))
    cur = conn.execute(
        f"SELECT * FROM delyanka_item WHERE delyanka_id IN ({placeholders})",
        delyanka_ids,
    )
    cols = [d[0] for d in cur.description]
    result = {}
    for row in cur.fetchall():
        item = dict(zip(cols, row))
        result.setdefault(item["delyanka_id"], []).append(item)
    return result


def compute_items_totals(conn, items, balances_by_item=None):
    """Агрегатор лимит/факт/остаток по списку выделов (delyanka_item) в ОДНУ
    сумму (Этап B плана доработок).

    Раньше "перерубы"/"обзор заготовки" считались наивным SQL вида
    SUM(delyanka_item.obyom) — такой колонки в БД физически нет (реальный
    лимит собирается сложнее, через МДО в mdo_raw_json), поэтому запрос
    тихо падал (except sqlite3.OperationalError: pass) и превращался в
    пустой/нулевой результат. Эта функция вместо этого честно считает
    через уже проверенные compute_balance()/compute_poroda_totals() по
    каждому выделу и суммирует "деловую" + "дрова" по всем породам
    (Хворост — без лимита, в сумму не входит, как и в compute_balance()).

    items — список ПОЛНЫХ словарей delyanka_item (нужен mdo_raw_json и id;
    см. get_delyanka_items()).

    balances_by_item — Этап 3: необязательный {item_id: balance} от УЖЕ
    посчитанного compute_balance_batch() (например, сразу по всем выделам
    ВСЕХ делянок экрана, одним запросом) — если передан, этот вызов не
    делает ни одного обращения к БД сам. Если не передан (как раньше),
    balance по items считается здесь одним запросом через
    compute_balance_batch() — раньше это был отдельный SQL-запрос НА
    КАЖДЫЙ item (по одному compute_balance() на выдел).

    Возвращает {"limit": float, "limit_110": float, "fakt": float,
                "ostatok": float, "ostatok_110": float}."""
    if balances_by_item is None:
        balances_by_item = compute_balance_batch(conn, items)
    total = {"limit": 0.0, "limit_110": 0.0, "fakt": 0.0, "ostatok": 0.0, "ostatok_110": 0.0}
    for item in items:
        balance = balances_by_item.get(item["id"], {})
        poroda_totals = compute_poroda_totals(balance)
        for vals in poroda_totals.values():
            for group in ("delovaya", "drova"):
                group_vals = vals[group]
                for key in total:
                    total[key] += group_vals.get(key) or 0
    return total


def get_active_delyanka_items(conn):
    """Возвращает список ПОЛНЫХ словарей delyanka_item (нужен mdo_raw_json)
    по ВСЕМ неархивным делянкам сразу — используется глобальной сводкой
    по породам D1 (Этап D плана доработок: "по всем активным выделам
    сразу"). "Активная" делянка — status != 'архив', тот же критерий, что
    и в перерубах (Этап B) и цветовой индикации (Этап C)."""
    cur = conn.execute(
        "SELECT di.* FROM delyanka_item di "
        "JOIN delyanka d ON d.id = di.delyanka_id "
        "WHERE d.status != 'архив'"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def compute_poroda_totals_multi(conn, items):
    """Сливает compute_balance()+compute_poroda_totals() по СПИСКУ выделов
    в одну сводку по породам (Этап D плана доработок): D1 — по всем
    активным выделам сразу (items = get_active_delyanka_items()), D2 — по
    одной делянке (items = get_delyanka_items(conn, delyanka_id)). Разница
    между D1/D2 — только в наборе items, который передаётся сюда, логика
    слияния одна и та же.

    Формат результата — ТОТ ЖЕ, что у compute_poroda_totals() для одного
    выдела ({порода: {"delovaya": {...}, "drova": {...}, "hvorost_fakt":
    float}}), только просуммированный по всем items, — поэтому его можно
    отобразить той же логикой, что и баланс одного выдела."""
    # Этап 3: один запрос на весь items вместо compute_balance() в цикле.
    balances_by_item = compute_balance_batch(conn, items)
    merged: dict = {}
    for item in items:
        balance = balances_by_item.get(item["id"], {})
        poroda_totals = compute_poroda_totals(balance)
        for poroda, vals in poroda_totals.items():
            target = merged.setdefault(poroda, {
                "delovaya": {"limit": 0.0, "limit_110": 0.0, "fakt": 0.0, "ostatok": 0.0, "ostatok_110": 0.0},
                "drova": {"limit": 0.0, "limit_110": 0.0, "fakt": 0.0, "ostatok": 0.0, "ostatok_110": 0.0},
                "hvorost_fakt": 0.0,
            })
            for group in ("delovaya", "drova"):
                for key, v in vals[group].items():
                    target[group][key] = target[group].get(key, 0.0) + (v or 0)
            target["hvorost_fakt"] += vals.get("hvorost_fakt") or 0
    return merged


def compute_sortiment_totals_multi(conn, items):
    """Сливает ФАКТ (без лимитов) по списку выделов в сводку
    {порода: {"KR": объём, "SR": ..., "ML": ..., "DROVA": ..., "HVOROST": ...}}
    — используется "Справкой заготовителя" (screens/inspection/):
    в отличие от compute_poroda_totals_multi() (Этап D, схлопывает
    KR+SR+ML в один "delovaya"), справке нужна КАЖДАЯ категория крупности
    отдельной строкой ("в том числе деловой: крупной/средней/мелкой"),
    поэтому берём сырой compute_balance() по каждому выделу и суммируем
    fakt без свёртки по сортиментам."""
    # Этап 3: один запрос на весь items вместо compute_balance() в цикле.
    balances_by_item = compute_balance_batch(conn, items)
    totals: dict = {}
    for item in items:
        balance = balances_by_item.get(item["id"], {})
        for poroda, sortiments in balance.items():
            target = totals.setdefault(
                poroda, {"KR": 0.0, "SR": 0.0, "ML": 0.0, "DROVA": 0.0, "HVOROST": 0.0}
            )
            for sortiment, vals in sortiments.items():
                target[sortiment] = target.get(sortiment, 0.0) + (vals.get("fakt") or 0)
    return totals


def compute_ploshad_proydennaya_rubkoy(items):
    """Суммирует "площадь" (delyanka_item.ploshad, из МДО) по списку
    выделов делянки — рабочее допущение для строки "Площадь, пройденная
    рубкой" в "Справке заготовителя": в МДО хранится площадь таксвыдела
    целиком, а не фактически вырубленная площадь (которая может быть
    меньше при выборочных рубках) — при генерации справки это значение
    подставляется как предзаполненное, но остаётся редактируемым полем,
    чтобы лесничий мог поправить его на месте, если рубка была не
    сплошная по всей площади выдела."""
    total = 0.0
    for item in items:
        raw = item.get("ploshad")
        if not raw:
            continue
        try:
            total += float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            continue
    return total


def compute_sortiment_limit_fakt_totals(conn, items):
    """Сумма ЛИМИТА и ФАКТА по каждому сортименту (KR/SR/ML/DROVA/HVOROST),
    сложенная across ВСЕХ пород — {"KR": {"limit":, "fakt":}, ...}.
    Используется таблицей "Разрешено/Фактически" Акта освидетельствования
    (screens/inspection/) — там колонка "Разрешено (установлено
    лесорубочным билетом)"/"Фактически вырублено" не различает породу,
    в отличие от Справки заготовителя (см. compute_sortiment_totals_multi,
    которая породу как раз сохраняет)."""
    totals = {"KR": {"limit": 0.0, "fakt": 0.0}, "SR": {"limit": 0.0, "fakt": 0.0},
              "ML": {"limit": 0.0, "fakt": 0.0}, "DROVA": {"limit": 0.0, "fakt": 0.0},
              "HVOROST": {"limit": 0.0, "fakt": 0.0}}
    # Этап 3: один запрос на весь items вместо compute_balance() в цикле.
    balances_by_item = compute_balance_batch(conn, items)
    for item in items:
        balance = balances_by_item.get(item["id"], {})
        for sortiments in balance.values():
            for sortiment, vals in sortiments.items():
                if sortiment not in totals:
                    continue
                totals[sortiment]["limit"] += vals.get("limit") or 0
                totals[sortiment]["fakt"] += vals.get("fakt") or 0
    return totals


def _month_name(date_str):
    months = ["", "январь", "февраль", "март", "апрель", "май", "июнь",
              "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
    if not date_str:
        return ""
    parts = date_str.replace("/", ".").split(".")
    if len(parts) < 2:
        return ""
    try:
        return months[int(parts[1])]
    except (ValueError, IndexError):
        return ""
