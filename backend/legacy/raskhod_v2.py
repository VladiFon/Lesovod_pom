# -*- coding: utf-8 -*-
"""
Единый источник истины для "Учёта заготовки / Книги расхода леса" —
СЛИЯНИЕ screens/raskhod/balance.py + screens/raskhod/egais.py +
screens/raskhod/export.py (см. AUDIT.md, раздел 1, примечание про
дублирование: "стоит явно проверить, какой из двух источников считать
единственно верным... вероятно, версия в screens/raskhod/, судя по более
новым комментариям про Этап 3 плана оптимизации").

Как собран этот файл: каждая функция ниже — ТОЧНАЯ построчная выгрузка
(sed по диапазону строк, без единого ручного изменения символа) из
исходных файлов вашего проекта:
  - balance.py  (строки 175-786): get_limits, create/update/delete/
    list_naryady, compute_balance/compute_balance_batch,
    canonical_poroda, get_remaining_volumes_for_bot,
    compute_sortiment_totals_multi, compute_sortiment_limit_fakt_totals
    и другие агрегаты.
  - egais.py    (строки 153-788): _normalize_egais_header и ПОСЛЕ неё —
    актуальные _EGAIS_COL_*/_EGAIS_DOC_TYPE_* константы (более полные,
    чем устаревшая копия в шапке export.py — включают "Корректировка
    остатков", которой в export.py нет), parse_egais_reestr,
    save_egais_snapshot и т.д.
  - export.py   (строки 194-261): export_to_excel.

Единственное, что здесь НЕ перенесено буквально, — это шапки импортов
каждого файла: там были PySide6/QtWidgets и `from screens.plots import
PlotsScreen`, которые в этих трёх файлах фактически НЕ используются ни в
одной из функций ниже (проверено grep'ом по каждому имени) — то есть их
удаление НЕ меняет поведение ни одной функции, только убирает мёртвые
импорты, требовавшие бы PySide6 в headless backend'е без всякой пользы.
Ниже — тот же список чистых импортов (config/db/delyanka), что был в
хвосте оригинальных шапок, плюс общие константы (SPECIES_*,
SORTIMENT_LABELS, RASKHOD_TEMPLATE, _COLS_*), которые были ОДИНАКОВО
продублированы во всех трёх исходных файлах (сами авторы это отметили:
"Общий заголовок... продублирован в каждом файле, чтобы каждый файл
оставался самодостаточным") — здесь достаточно одной копии.

Старый корневой raskhod.py НЕ удалён и НЕ менялся — telegram_bot.py
по-прежнему импортирует функции из него (`from raskhod import
get_remaining_volumes_for_bot`). Веб-backend (этот файл) и бот теперь
временно используют два разных, хоть и почти идентичных модуля — см.
README_RASKHOD_REFACTOR.md для рекомендации по дальнейшей консолидации.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import config

try:
    from db import (
        get_vydel_card,
        migrate_schema,
        save_uhody_proba,
        list_uhody_proby,
        get_uhody_proba,
        delete_uhody_proba,
    )
except ImportError:
    get_vydel_card = None
    migrate_schema = None
    save_uhody_proba = None
    list_uhody_proby = None
    get_uhody_proba = None
    delete_uhody_proba = None

try:
    from delyanka import get_delyanka_full, save_komissiya_preset
except ImportError:
    get_delyanka_full = None
    save_komissiya_preset = None

# --- Общие константы (были продублированы во всех трёх исходных файлах) --- #
SPECIES_WITH_GRADES = ["Е", "С", "Б", "ОС", "Д", "ОЛЧ"]
SPECIES_NO_GRADES = ["Р", "ОЛС"]
ALL_SPECIES = SPECIES_WITH_GRADES + SPECIES_NO_GRADES

SORTIMENT_LABELS = {
    "KR": "деловая крупная", "SR": "деловая средняя", "ML": "деловая мелкая",
    "DROVA": "дрова", "HVOROST": "хворост",
}

RASKHOD_TEMPLATE = "raskhod_shablon.xlsx"

_COLS_DELOVAYA_GRADES = {
    "Е": ["B", "C", "D"], "С": ["E", "F", "G"], "Б": ["H", "I", "J"],
    "ОС": ["K", "L", "M"], "Д": ["N", "O", "P"], "ОЛЧ": ["Q", "R", "S"],
}
_COLS_DELOVAYA_SIMPLE = {"Р": "T", "ОЛС": "U"}
_COLS_DROVA = {
    "Е": "V", "С": "W", "Б": "X", "ОС": "Y", "Д": "Z", "Р": "AA", "ОЛС": "AB", "ОЛЧ": "AC",
}
_COL_HVOROST = "AD"
_COL_PLOSHAD = "AE"
_COL_NARYAD = "AG"


# =========================================================================
#   ИЗ balance.py (строки 175-786) — БЕЗ ИЗМЕНЕНИЙ
# =========================================================================

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


def _canonical_poroda_code(poroda):
    """Приводит породу к короткому коду МДО (как в get_limits()/наряде:
    "Е"/"С"/"ОС"/...), даже если она пришла в виде полного названия ЕГАИС
    ("Ель"/"Сосна"/..., иногда с буквой "ё" или другим регистром) — без
    этой нормализации сравнение по строковому равенству не совпадает, и
    порода задваивается в балансе на ДВЕ строки: код (лимит + факт по
    наряду, но без факта ЕГАИС) и отдельно полное имя (факт ЕГАИС, но без
    лимита и факта по наряду) — visible-баг с "Е"/"Ель" и "С"/"Сосна" в
    одной таблице вместо одной строки на породу.

    Код выбран каноном (а не полное имя), чтобы не менять уже привычное
    отображение коротких кодов в колонке "Порода" у существующих
    делянок без ЕГАИС-данных. Была уже заведённая, но нигде не
    вызывавшаяся canonical_poroda() ниже с той же идеей приведения к
    единому ключу, только в обратную сторону (к полному имени) — оставлена
    как есть на случай, если ею пользуется что-то ещё за пределами этого
    файла."""
    if not poroda:
        return poroda
    s = str(poroda).strip()
    if s in POROda_DISPLAY_NAMES:
        return s
    normalized = s.replace("ё", "е").replace("Ё", "Е").casefold()
    for code, full_name in POROda_DISPLAY_NAMES.items():
        if normalized == full_name.replace("ё", "е").replace("Ё", "Е").casefold():
            return code
    return " ".join(s.split())


def _normalize_poroda_keys(d):
    """Схлопывает {порода: {сортимент: объём}} по _canonical_poroda_code(),
    суммируя объёмы по сортиментам при совпадении ключа после нормализации
    (короткий код МДО и полное название ЕГАИС одной и той же породы после
    этого попадают в один и тот же ключ, а не в две разные строки
    баланса)."""
    out = {}
    for poroda, values in (d or {}).items():
        key = _canonical_poroda_code(poroda)
        dest = out.setdefault(key, {})
        for sub_key, val in (values or {}).items():
            dest[sub_key] = (dest.get(sub_key) or 0) + (val or 0)
    return out


def _build_balance(item, fakt, fakt_egais=None):
    """Собирает {порода: {KR/SR/ML/DROVA/HVOROST: {limit, limit_110, fakt,
    ostatok, ostatok_110, fakt_egais, ostatok_egais, ostatok_egais_110}}}
    по лимитам выдела (item, из МДО), факту по нарядам (fakt = {порода:
    {сортимент: объём}}) и, ДОПОЛНИТЕЛЬНО, факту по последней выгрузке
    ЕГАИС (fakt_egais — тот же формат, см. _fakt_egais_from_entry) — обе
    колонки остатка (по наряду и по ЕГАИС) считаются от ОДНОГО и того же
    лимита, чтобы лесничий мог сверить, совпадает ли то, что записано в
    наряде, с тем, что реально прошло через ЕГАИС.

    Общая часть compute_balance()/compute_balance_batch() (Этап 3 плана
    оптимизации), вынесенная отдельно, чтобы запрос к БД и сборка
    результата не дублировались в двух местах — раньше эта сборка была
    только внутри compute_balance(), а compute_balance_batch() пришлось бы
    либо копировать её, либо вызывать compute_balance() в цикле (что как
    раз и убирает батчинг).

    limits/fakt/fakt_egais нормализуются через _normalize_poroda_keys()
    ПЕРЕД слиянием в all_porody — иначе код МДО ("Е") и полное имя ЕГАИС
    ("Ель") для одной и той же породы не совпадают по строке и дают две
    отдельные строки в балансе вместо одной."""
    fakt_egais = fakt_egais or {}
    limits = _normalize_poroda_keys(get_limits(item))
    fakt = _normalize_poroda_keys(fakt)
    fakt_egais = _normalize_poroda_keys(fakt_egais)
    balance = {}
    all_porody = set(limits.keys()) | set(fakt.keys()) | set(fakt_egais.keys())
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
            f_egais = fakt_egais.get(poroda, {}).get(s, 0)
            balance[poroda][s] = {
                "limit": limit,
                "limit_110": limit * 1.1,
                "fakt": f,
                "ostatok": limit - f,
                "ostatok_110": limit * 1.1 - f,
                "fakt_egais": f_egais,
                "ostatok_egais": limit - f_egais,
                "ostatok_egais_110": limit * 1.1 - f_egais,
            }
        # хворост - без лимита, просто фактический учёт (ЕГАИС хворост не
        # отслеживает — porody из парсера содержит только КР/СР/МЛ/дрова/
        # б-р, отдельного бакета HVOROST там нет, поэтому у ЕГАИС-колонок
        # для хвороста строки просто не будет — это ожидаемо, не баг)
        hvorost_fakt = fakt.get(poroda, {}).get("HVOROST", 0)
        if hvorost_fakt:
            balance[poroda]["HVOROST"] = {
                "limit": None, "limit_110": None, "fakt": hvorost_fakt,
                "ostatok": None, "ostatok_110": None,
            }
    return balance


def _fakt_egais_from_entry(entry):
    """Приводит одну запись из load_egais_snapshot()/
    find_egais_entry_for_item() (entry["porody"] = {порода: {сортимент:
    объём}}, где сортимент — КР/СР/МЛ по крупности (см.
    _egais_krupnost_for_row) плюс "дрова"/"б/р") к формату fakt,
    ожидаемому _build_balance() — {порода: {KR/SR/ML/DROVA: объём}} — то
    есть напрямую сравнимому с наряд-фактом по тем же 4 колонкам.

    "б/р" (деловая древесина, у которой не вышло определить крупность по
    диаметру — ни "Группа диметров", ни "Номенклатура" не распознались)
    добавляется в ML. Осознанное упрощение, а не потеря данных: такие
    строки и так видны лесничему в статистике импорта
    krupnost_ne_opredelena (см. _parse_egais_reestr_impl) — здесь просто
    нужно было выбрать одну из 4 колонок, чтобы объём не выпал из
    остатка/итога по ЕГАИС молча."""
    fakt = {}
    for poroda, sorts in (entry.get("porody") or {}).items():
        row = {"KR": 0.0, "SR": 0.0, "ML": 0.0, "DROVA": 0.0}
        for sort_code, vol in (sorts or {}).items():
            if sort_code == "дрова":
                row["DROVA"] += vol or 0
            elif sort_code == "б/р":
                row["ML"] += vol or 0
            elif sort_code in row:
                row[sort_code] += vol or 0
        fakt[poroda] = row
    return fakt


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

    ЕГАИС-факт (колонки "остаток (ЕГАИС)" в балансе — Б.4 доработок):
    снапшот ЕГАИС один на всю БД (последняя выгрузка), поэтому грузится
    ОДИН раз на весь батч, а не в цикле по каждому item — то же
    соображение, что и у самого батчинга по нарядам выше."""
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

    loaded_egais, _ = load_egais_snapshot(conn)
    fakt_egais_by_item = {}
    if loaded_egais:
        for item in items:
            entry = find_egais_entry_for_item(loaded_egais, item)
            if entry:
                fakt_egais_by_item[item["id"]] = _fakt_egais_from_entry(entry)

    return {
        item["id"]: _build_balance(
            item, fakt_by_item.get(item["id"], {}), fakt_egais_by_item.get(item["id"], {})
        )
        for item in items
    }


def compute_balance(conn, item, item_id):
    """Возвращает {порода: {KR/SR/ML/DROVA: {limit, limit_110, fakt, ostatok, ostatok_110,
    fakt_egais, ostatok_egais, ostatok_egais_110}}} для ОДНОГО выдела.

    Этап 3: теперь просто обёртка над compute_balance_batch() с списком из
    одного элемента — тот же SQL и та же сборка результата, что и в
    батч-версии, без дублирования логики. Сигнатура и поведение для
    вызывающего кода не изменились (screens/raskhod/screen.py,
    get_remaining_volumes_for_bot и т.д. продолжают работать как раньше)."""
    lookup_item = item if item.get("id") == item_id else {**item, "id": item_id}
    return compute_balance_batch(conn, [lookup_item]).get(item_id, _build_balance(item, {}))


def _parse_ploshad_value(raw):
    """Разбирает текстовое поле площади (delyanka_item.ploshad или
    raskhod_naryad.ploshad — оба TEXT, часто с запятой вместо точки, как
    приходят из МДО или введены вручную в форме наряда) в float.
    Нераспознанное/пустое значение — 0.0, а не исключение, чтобы одна
    кривая строка не роняла весь расчёт площади по выделу."""
    if not raw:
        return 0.0
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def compute_limit_kubatura_total(item):
    """Общий лимит кубатуры по выделу (делянке) — сумма КР+СР+МЛ+Дрова
    ПО ВСЕМ породам сразу (без разбивки), м3.

    Нужен для строки "Площадь делянки/остаток" в балансе, а также как
    знаменатель формулы автоподсчёта площади наряда на фронте (см.
    NaryadModal/handleCalcPloshad в Raskhod.jsx):
        площадь_наряда = кубатура_наряда * площадь_делянки / этот_итог
    Использует те же лимиты из МДО, что и get_limits()/_build_balance()
    — отдельного источника данных не заводим, чтобы цифры не могли
    разъехаться между балансом по породам и этим итогом."""
    limits = get_limits(item)
    total = 0.0
    for sortiments in limits.values():
        total += (sortiments.get("KR") or 0) + (sortiments.get("SR") or 0) \
            + (sortiments.get("ML") or 0) + (sortiments.get("DROVA") or 0)
    return total


def compute_ploshad_summary(conn, item, item_id):
    """Возвращает {"ploshad_delyanki", "limit_kubatura_total",
    "ploshad_naryadov", "ploshad_ostatok"} для строки "Площадь делянки /
    Площадь остаток" в балансе экрана "Расход/ЕГАИС":

      ploshad_delyanki     — площадь выдела (delyanka_item.ploshad, из МДО);
      limit_kubatura_total — знаменатель формулы автоподсчёта площади
                              наряда, см. compute_limit_kubatura_total;
      ploshad_naryadov     — сумма площадей ВСЕХ уже созданных нарядов
                              этого выдела (raskhod_naryad.ploshad);
      ploshad_ostatok      — ploshad_delyanki - ploshad_naryadov,
                              округлено до сотых. Может уйти в минус, если
                              в наряды вручную занесли площадь больше, чем
                              в МДО, — это сигнал лесничему перепроверить
                              наряды, а не ошибка расчёта."""
    ploshad_delyanki = _parse_ploshad_value(item.get("ploshad"))
    rows = conn.execute(
        "SELECT ploshad FROM raskhod_naryad WHERE item_id=?", (item_id,)
    ).fetchall()
    ploshad_naryadov = sum(_parse_ploshad_value(r[0]) for r in rows)
    return {
        "ploshad_delyanki": round(ploshad_delyanki, 2),
        "limit_kubatura_total": round(compute_limit_kubatura_total(item), 2),
        "ploshad_naryadov": round(ploshad_naryadov, 2),
        "ploshad_ostatok": round(ploshad_delyanki - ploshad_naryadov, 2),
    }


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


def get_remaining_volumes_grouped_for_bot(conn, kvartal, vydel, lesoseka=None):
    """Версия get_remaining_volumes_for_bot() выше, но со сверкой ЕГАИС —
    используется ТОЛЬКО ботом (handle_balance_callback в telegram_bot.py,
    см. _format_remaining_reply), которому нужны:
      - разбивка деловая/дрова (а не по КР/СР/МЛ отдельно);
      - факт по ЕГАИС рядом с фактом по наряду (fakt_egais), чтобы взять
        БОЛЬШИЙ из двух как реальный расход (ostatok_safe = limit -
        max(fakt_naryad, fakt_egais)) — иначе, если ЕГАИС показывает
        больше, чем внесённые наряды, бот показал бы завышенный остаток и
        мог привести к перерубу "на бумаге";
      - явное "нет данных" по ЕГАИС, если выгрузку в приложение вообще
        ни разу не загружали (в отличие от "загружали, но по этой
        делянке пусто" — это 0, не None).

    ПРЕДЫСТОРИЯ (важно, если это снова понадобится трогать): раньше в
    проекте существовала функция get_remaining_volumes_for_bot ИМЕННО в
    файле raskhod.py (не raskhod_v2.py) с этой же логикой — telegram_bot.py
    был написан и заточен под её формат ответа (см. _format_remaining_reply:
    ожидает result["grouped"]/result["egais_imported_at"]). Тот raskhod.py
    в какой-то момент был перезаписан копией FastAPI-роутера и функция
    физически исчезла из кодовой базы (обнаружено при починке падения
    бота на "ModuleNotFoundError: No module named 'app'" — простая замена
    импорта на raskhod_v2.get_remaining_volumes_for_bot убрала краш, но
    бот перестал находить остатки: тот словарь плоский ({(порода,
    сортимент): объём}, без ЕГАИС) и _format_remaining_reply просто не
    находил в нём ключ "grouped"). Эта функция — восстановленная замена,
    собранная из уже существующих в этом файле кирпичиков
    (compute_balance_batch — даёт fakt/fakt_egais по КР/СР/МЛ/дрова с
    той же "умной" сверкой составных выделов, что и раньше;
    load_egais_snapshot — даёт признак "снапшот вообще загружали").
    get_remaining_volumes_for_bot() выше НЕ тронута (её отдельно
    использует веб через GET /api/raskhod/remaining) — специально заведена
    новая функция, а не изменён существующий контракт.
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

    empty = {"found": False, "item_ids": [], "grouped": {}, "last_update": None, "egais_imported_at": None}
    if not rows:
        return empty

    wanted_numbers = _extract_vydel_numbers(vydel)
    if not wanted_numbers:
        return empty

    all_items = [dict(zip(cols, r)) for r in rows]
    items = [
        item for item in all_items
        if wanted_numbers & _extract_vydel_numbers(item.get("vydel"))
    ]
    if not items:
        return empty

    item_ids = [item["id"] for item in items]

    balances_by_item = compute_balance_batch(conn, items)
    loaded_egais, egais_imported_at_raw = load_egais_snapshot(conn)
    has_egais_snapshot = bool(loaded_egais)

    grouped = {}
    for item in items:
        balance = balances_by_item.get(item["id"], {})
        for poroda, sortimenty in balance.items():
            target = grouped.setdefault(poroda, {
                "delovaya": {"limit": 0.0, "fakt_naryad": 0.0, "fakt_egais": 0.0},
                "drova": {"limit": 0.0, "fakt_naryad": 0.0, "fakt_egais": 0.0},
            })
            for code in ("KR", "SR", "ML"):
                vals = sortimenty.get(code)
                if not vals:
                    continue
                target["delovaya"]["limit"] += vals.get("limit") or 0
                target["delovaya"]["fakt_naryad"] += vals.get("fakt") or 0
                target["delovaya"]["fakt_egais"] += vals.get("fakt_egais") or 0
            drova_vals = sortimenty.get("DROVA") or {}
            target["drova"]["limit"] += drova_vals.get("limit") or 0
            target["drova"]["fakt_naryad"] += drova_vals.get("fakt") or 0
            target["drova"]["fakt_egais"] += drova_vals.get("fakt_egais") or 0

    for poroda_vals in grouped.values():
        for group_vals in poroda_vals.values():
            fakt_egais = group_vals["fakt_egais"] if has_egais_snapshot else None
            fakt_naryad = group_vals["fakt_naryad"]
            limit = group_vals["limit"]
            fakt_effektivny = max(fakt_naryad, fakt_egais) if fakt_egais is not None else fakt_naryad
            group_vals["fakt_egais"] = fakt_egais
            group_vals["ostatok_safe"] = limit - fakt_effektivny

    placeholders = ",".join("?" for _ in item_ids)
    row = conn.execute(
        f"SELECT MAX(created_at) FROM raskhod_naryad WHERE item_id IN ({placeholders})",
        item_ids,
    ).fetchone()
    last_update_raw = row[0] if row else None
    if not last_update_raw:
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
        "grouped": grouped,
        "last_update": _parse_db_datetime(last_update_raw),
        "egais_imported_at": _parse_db_datetime(egais_imported_at_raw) if has_egais_snapshot else None,
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


def compute_balance_totals_multi(conn, items):
    """Сливает compute_balance() по списку выделов (delyanka_item) в ОДИН
    баланс, БЕЗ схлопывания по сортименту (в отличие от
    compute_poroda_totals_multi, которая сворачивает KR/SR/ML в один
    "delovaya") и БЕЗ потери разбивки по породам (в отличие от
    compute_sortiment_limit_fakt_totals, которая суммирует все породы
    вместе) — {порода: {KR/SR/ML/DROVA: {limit, limit_110, fakt, ostatok,
    ostatok_110}, HVOROST: {fakt}}}.

    Формат результата ТОТ ЖЕ, что у compute_balance() для одного выдела —
    поэтому существующий фронтенд-компонент BalanceTable (frontend/src/
    pages/Raskhod.jsx) отображает такую сводку без изменений: экран
    "Расход/ЕГАИС" (B.2 доработок) использует эту функцию для кнопки
    "Сводка по породам" — по одной делянке (items = get_delyanka_items())
    или по всем активным делянкам (items = get_active_delyanka_items())."""
    balances_by_item = compute_balance_batch(conn, items)
    merged: dict = {}
    for item in items:
        balance = balances_by_item.get(item["id"], {})
        for poroda, sortiments in balance.items():
            target = merged.setdefault(poroda, {})
            for sortiment, vals in sortiments.items():
                cell = target.setdefault(
                    sortiment, {"limit": 0.0, "limit_110": 0.0, "fakt": 0.0, "ostatok": 0.0, "ostatok_110": 0.0}
                )
                for key, v in vals.items():
                    if key in cell:
                        cell[key] += v or 0
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

# =========================================================================
#   ИЗ egais.py (строки 153-788) — БЕЗ ИЗМЕНЕНИЙ
# =========================================================================

def _normalize_egais_header(header):
    """Приводит название колонки выгрузки ЕГАИС к устойчивому виду для
    сравнения. На двух РЕАЛЬНЫХ выгрузках одного и того же лесхоза с
    разницей в один день колонки, логически означающие одно и то же,
    назывались чуть по-разному: "Номер документа" / "Номер  документа"
    (двойной пробел), "Склад контрагент" / "Склад-контрагент" (дефис вместо
    пробела). Если сравнивать названия колонок буквально, парсер молча "не
    находит" нужную колонку при малейшей вариации написания - без ошибки,
    просто отдаёт None вместо значения, а дальше это тихо превращается в
    пустые/нулевые данные. Здесь дефисы приравниваются к пробелам, а любые
    цепочки пробельных символов схлопываются в один - так "Номер  документа"
    и "Номер документа", "Склад контрагент" и "Склад-контрагент" совпадают
    после нормализации, не совпадая до неё."""
    if header is None:
        return ""
    return re.sub(r"\s+", " ", str(header).replace("-", " ")).strip()


_EGAIS_COL_KVARTAL = _normalize_egais_header("Номер лесного квартала")
_EGAIS_COL_VYDEL = _normalize_egais_header("Номер таксационного выдела ")  # именно с пробелом в конце
_EGAIS_COL_OBYOM = _normalize_egais_header("Объем")
_EGAIS_COL_DOC_TYPE = _normalize_egais_header("Тип документа")
_EGAIS_COL_DOC_NUM = _normalize_egais_header("Номер документа")
_EGAIS_COL_SKLAD_ID = _normalize_egais_header("id Склад операции")
_EGAIS_COL_SKLAD_NAME = _normalize_egais_header("Склад операции")
_EGAIS_COL_OSNOVANIE = _normalize_egais_header("Основание")
_EGAIS_COL_OSNOVANIE_NUM = _normalize_egais_header("Номер основания")
_EGAIS_COL_LINKED_DOC = _normalize_egais_header("Номер связанного  документа")  # да, два пробела - так в выгрузке
_EGAIS_COL_PORODA = _normalize_egais_header("Порода")
_EGAIS_COL_SORT = _normalize_egais_header("Сорт")
_EGAIS_COL_GODNOST = _normalize_egais_header("Техническая годность")

_EGAIS_COL_DATA_DOK = _normalize_egais_header("Дата документа")
_EGAIS_COL_SOTRUDNIK = _normalize_egais_header("Сотрудник")
_EGAIS_COL_SKLAD_KONTRAGENT = _normalize_egais_header("Склад контрагент")
_EGAIS_COL_KOLVO = _normalize_egais_header("Кол-во")

# Служебные/технические колонки выгрузки — не участвуют в ключе
# дедупликации журнала (см. compute_egais_operation_key) - это метаданные
# ОБРАБОТКИ строки в ЕГАИС (кто/когда её создал или изменил), а не её
# содержание, и практика показала (реальная выгрузка, проверено
# 2026-09-24), что "Дата и время обработки на сервере" у буквально
# идентичного дубля строки (см. ниже) может даже совпадать, так что это
# не проблема - но исключаем на случай, если ЕГАИС когда-нибудь пересчитает
# эту метку при повторной выгрузке того же периода, а остальное содержимое
# строки не изменится.
_EGAIS_AUDIT_COLUMNS = {
    _normalize_egais_header("Дата и время обработки на сервере"),
    _normalize_egais_header("Пользователь создания"),
    _normalize_egais_header("Дата изменения"),
    _normalize_egais_header("Пользователь изменения"),
    _normalize_egais_header("Статус"),
}

# Крупность (KR/SR/ML) деловой древесины в выгрузке ЕГАИС НЕ хранится
# отдельной колонкой - её нужно доставать из диаметра, который лежит в
# одной из этих двух колонок в зависимости от "Метод определения объема":
#   - поштучный учёт ("шт") - точный диаметр текстом внутри "Номенклатуры"
#     (например "Лесоматериалы круглые шт, Сосна, 6 м., 36 см, C");
#   - групповой учёт ("гр", мелкая древесина) - диаметр НЕ точный, лежит
#     структурированно в "Группа диметров" (да, опечатка в самой выгрузке
#     ЕГАИС - без "а" - колонка называется именно так) - например "до 13 см".
# Колонка "Сорт" (C/D/...) сюда не имеет отношения - это качество по
# ГОСТу, а не размер, см. _egais_krupnost_for_row ниже.
_EGAIS_COL_NOMENKLATURA = _normalize_egais_header("Номенклатура")
_EGAIS_COL_GRUPPA_DIAMETROV = _normalize_egais_header("Группа диметров")

_EGAIS_DOC_TYPE_PRIHOD = "Приход"
_EGAIS_DOC_TYPE_VNUTR_PEREMESHENIE = "Расход при внутреннем перемещении"
# "Расход при реализации потребителю" - финальная продажа со склада
# покупателю. Объём не прибавляет (древесина просто уходит), но это
# ОЖИДАЕМЫЙ, легитимный тип документа - его не нужно ни считать в факте,
# ни подсвечивать как "незнакомую операцию".
_EGAIS_DOC_TYPE_REALIZATSIYA = "Расход при реализации потребителю"
# "Корректировка остатков" - официальная складская операция ЕГАИС (см.
# гл. 9 руководства пользователя ЕГАИС), которой можно вручную поменять
# остаток склада БЕЗ прихода/расхода. В "Реестр движения по складам" она
# попадает отдельным типом документа - раньше парсер её вообще не видел
# (смотрел только на "Приход"), и объём мог задним числом "появиться" на
# складе делянки незамеченным. Теперь такие строки не подмешиваются в
# факт молча, а собираются отдельным списком на каждой делянке
# (entry["korrektirovki"]) - дата/сотрудник/объём видны на экране.
_EGAIS_DOC_TYPE_KORREKTIROVKA = "Корректировка остатков"
# "Перевод" - переклассификация УЖЕ учтённой древесины между сортами/
# номенклатурой на том же складе (по Приказу), НЕ новое поступление на
# склад - подтверждено пользователем на реальном примере выгрузки
# (24.09.2026: кв.21, 16.09.2026, порода Ель - Расход при внутр.
# перемещении -13.304 + Приход +3 + Перевод +10.304 = 0 день в день).
# Объём нейтрален - не идёт ни в приход, ни в расход (см.
# compute_egais_balance_check), но и не должен шуметь в "неизвестных
# операциях" при каждом импорте, раз тип документа опознан и осмыслен.
_EGAIS_DOC_TYPE_PEREVOD = "Перевод"

# Любой "Тип документа", который встретится в выгрузке и не входит в этот
# список - раньше молча игнорировался. Теперь такие строки не пропадают:
# они собираются в общий список "неизвестные операции" (см. stats ниже),
# чтобы при появлении в ЕГАИС новых типов документов ни один объём не
# "терялся" без следа.
_EGAIS_KNOWN_DOC_TYPES = {
    _EGAIS_DOC_TYPE_PRIHOD,
    _EGAIS_DOC_TYPE_VNUTR_PEREMESHENIE,
    _EGAIS_DOC_TYPE_REALIZATSIYA,
    _EGAIS_DOC_TYPE_KORREKTIROVKA,
    _EGAIS_DOC_TYPE_PEREVOD,
}

# Автосгенерировано разбиением screens/raskhod.py на модули по экрану.
# Общий заголовок (импорты/константы модуля) продублирован в каждом файле,
# чтобы каждый файл оставался самодостаточным и поведение не изменилось.


def parse_egais_reestr(excel_path):
    """Парсит выгрузку из модуля ЕГАИС "Реестр движения по складам" и
    считает фактически заготовленный ("чистый") объём по каждой делянке,
    породе и сортименту/сорту.

    Почему нельзя просто просуммировать все строки с "Тип документа" ==
    "Приход" (задвоение объёмов)
    ---------------------------------------------------------------------
    В ЕГАИС к одной лесосеке может быть привязано несколько складов
    (например ФЛС и ПЛС), и древесина может двигаться между складами самого
    лесопользователя операцией "Расход при внутреннем перемещении". Когда
    такой расходный документ проводится на складе-грузоотправителе, на
    складе-грузополучателе (складе-контрагенте) в ЕГАИС обязательно нужно
    провести операцию "Приход" по этому же расходному документу (поиском по
    номеру документа/QR-коду), чтобы принять списанную продукцию - это
    механизм самого ЕГАИС.

    Официальное руководство пользователя ЕГАИС прямо предупреждает (раздел
    про модуль "Сопровождение абонплаты"): учётные данные по объёмам,
    полученные при проведении операции "Приход" по складским документам
    операции "Расход при внутреннем перемещении", не учитываются, так как
    здесь древесина учитывается повторно.

    То есть если выгрузка "Реестр движения по складам" сформирована не
    только по складам делянки (ФЛС/ПЛС), а по всем складам лесхоза (включая
    цеха/нижние склады), в ней будет и "исходный" Приход (реальная заготовка
    на делянке), и "вторичный" Приход - принятие того же объёма на
    складе-контрагенте при внутреннем перемещении. Если суммировать оба -
    объём задвоится.

    Как отличаем "чистый" Приход от "вторичного" (задвоенного)
    ---------------------------------------------------------------------
    Строится множество "связанных" номеров документов - это значения
    колонки "Номер связанного документа" у всех строк
    "Расход при внутреннем перемещении" (в ЕГАИС это номер того приходного
    документа, который создаётся/подтверждается на складе-контрагенте).
    Строка "Приход" считается "чистой" заготовкой (и попадает в сумму),
    только если ОДНОВРЕМЕННО:
      1) "Тип документа" == "Приход";
      2) "Номер документа" этой строки НЕ входит в собранное множество
         связанных номеров (т.е. этот приход - не пара к какому-то
         "Расходу при внутреннем перемещении");
      3) колонки "Основание" и "Номер основания" у строки пустые - в
         примерах выгрузок именно у первичного прихода (сама лесосека -
         источник) эти поля не заполняются, а у "автоматизированного
         оприходования" по расходному документу - заполняются. Это
         дополнительная подстраховка на случай, если в конкретной выгрузке
         связанный номер документа почему-то не заполнен.

    Группировка
    ---------------------------------------------------------------------
    Ключ делянки - кортеж `(kvartal, vydel)`: номер лесного квартала и номер
    таксационного выдела, оба - строки, очищенные функцией
    `_egais_clean_number` (например, `139.0` -> `"139"`). Это привязка не к
    складу ЕГАИС, а именно к участку (кварталу/выделу) - потому что к одной
    делянке в ЕГАИС может быть привязано сразу несколько складов (ФЛС и ПЛС),
    и без такой привязки объём по одному и тому же участку разъехался бы по
    разным ключам. Если у строки не заполнены ни квартал, ни выдел - строка
    пропускается (без квартала/выдела её физически некуда привязать).
    Названия складов ЕГАИС, из которых собран участок (обычно "ФЛС ..." и
    "ПЛС ..."), сохраняются в `nazvanie_sklada` через "; ", чтобы не терять
    эту информацию при объединении.
    Внутри участка объём группируется по породе ("Порода") и сортименту.
    Для дровяной древесины ("Техническая годность" == "Дровяная древесина")
    сортимент помечается как "дрова". Для деловой древесины "сортимент" -
    это уже КРУПНОСТЬ KR/SR/ML (те же коды, что и в module raskhod.py у
    наряды/лимитов) - определяется по диаметру, который достаётся из
    "Номенклатуры" (поштучный учёт, "шт") или "Группы диметров" (групповой
    учёт мелкой древесины, "гр"), см. _egais_krupnost_for_row. Колонка
    "Сорт" (буква C/D/... по ГОСТу) для этого НЕ используется - она про
    качество, а не про размер. Если диаметр не удалось определить ни из
    одной колонки, строка попадает в отдельный бакет "б/р" (без размера),
    а не молча в KR/SR/ML - см. "krupnost_ne_opredelena" в
    `parse_egais_reestr_with_stats`.

    Параметры
    ---------
    excel_path : str | Path - путь к .xlsx-выгрузке "Реестр движения по
        складам".

    Возвращает
    ----------
    dict вида (ключ - кортеж `(kvartal, vydel)`, обе части строки)::

        {
            ("139", "15"): {
                "nazvanie_sklada": "ПЛС кв.139, выд.15 л.1 1,1 га ССР; ФЛС кв.139, выд.15 л.1 1,1 га ССР",
                "kvartal": "139",
                "vydel": "15",
                "porody": {
                    "Ель": {"SR": 12.34, "дрова": 4.0, ...},
                    "Сосна": {"KR": 5.6, "ML": 1.2, ...},
                },
            },
            ...
        }

    Если нужна сверка/аудит того, сколько строк было исключено как
    задвоение и на какой объём - см. `parse_egais_reestr_with_stats`.
    """
    result, _stats = _parse_egais_reestr_impl(excel_path)
    return result


def parse_egais_reestr_with_stats(excel_path):
    """То же, что `parse_egais_reestr`, но дополнительно возвращает
    статистику по исключённым (задвоенным) строкам - для сверки/аудита:

        (data, stats)

    где `stats` - dict::

        {
            "prihod_rows_total": int,       # всего строк "Приход" в файле
            "prihod_rows_excluded": int,    # из них исключено как задвоение
            "obyom_excluded": float,        # суммарный исключённый объём (м3)
            "prihod_rows_used": int,        # использовано в сумме
        }
    """
    return _parse_egais_reestr_impl(excel_path)


def _extract_vydel_numbers(value):
    """Извлекает все числа из значения выдела в множество строк -
    используется для "умного" сравнения. И искомый vydel (delyanka_item.vydel
    из БД), и ключи в загруженной выгрузке ЕГАИС могут быть составными:
    delyanka_item.vydel хранит МДО-запись целиком ('6,10,12,18' - несколько
    выделов одной лесосеки), а в ЕГАИС каждый склад (ФЛС/ПЛС) привязан к
    ОДНОМУ конкретному выделу - то есть у выгрузки ЕГАИС на одну такую
    делянку приходится НЕСКОЛЬКО разных ключей (kvartal, vydel), каждый со
    своим единственным числом. Прямое сравнение строк "6,10,12,18" == "6"
    никогда не совпадёт - поэтому сравнивать нужно по пересечению множеств
    чисел, а не по точному равенству строк (тот же приём, что и в
    get_remaining_volumes_for_bot/_extract_vydel_numbers из raskhod.py)."""
    return set(re.findall(r"\d+", str(value)))


def find_egais_entry_for_item(loaded_egais_data, item):
    """Умный поиск записи(-ей) в загруженной выгрузке ЕГАИС для делянки с
    возможно составным выделом (см. _extract_vydel_numbers) - используется
    вместо простого loaded_egais_data.get((kvartal, vydel)), который для
    составных выделов всегда возвращал None (главная причина, по которой
    колонка "Факт (ЕГАИС)" оставалась пустой у многовыдельных делянок).

    Ищет ВСЕ ключи (kvartal, vydel) в loaded_egais_data с тем же кварталом
    и непустым пересечением чисел выдела, и сливает их в одну запись:
    объёмы по породам/сортиментам суммируются, названия складов и
    корректировки остатков объединяются. Возвращает None, если совпадений
    не нашлось (в т.ч. если файл ЕГАИС не загружен вовсе)."""
    if not loaded_egais_data:
        return None

    kvartal_clean = _egais_clean_number(item.get("kvartal"))
    wanted_vydel_numbers = _extract_vydel_numbers(item.get("vydel"))
    if not wanted_vydel_numbers:
        return None

    matched = [
        entry
        for (kv, vd), entry in loaded_egais_data.items()
        if kv == kvartal_clean and wanted_vydel_numbers & _extract_vydel_numbers(vd)
    ]
    if not matched:
        return None
    if len(matched) == 1:
        return matched[0]

    merged = {
        "nazvanie_sklada": "",
        "kvartal": kvartal_clean,
        "vydel": item.get("vydel"),
        "porody": {},
        "korrektirovki": [],
    }
    sklad_names = []
    for entry in matched:
        for name in (entry.get("nazvanie_sklada") or "").split("; "):
            if name and name not in sklad_names:
                sklad_names.append(name)
        for poroda, sorts in (entry.get("porody") or {}).items():
            dest = merged["porody"].setdefault(poroda, {})
            for sort_code, vol in sorts.items():
                dest[sort_code] = dest.get(sort_code, 0) + vol
        merged["korrektirovki"].extend(entry.get("korrektirovki") or [])
    merged["nazvanie_sklada"] = "; ".join(sklad_names)
    return merged


def _egais_date_sort_key(value):
    """"ДД.ММ.ГГГГ" -> "ГГГГ-ММ-ДД" для корректной сортировки ORDER BY
    (сама колонка хранится в исходном виде ЕГАИС для отображения). Если
    формат не распознан - пустая строка (такие записи уйдут в начало при
    сортировке по убыванию, не потеряются)."""
    text = str(value or "").strip()
    for sep in (".", "/", "-"):
        parts = text.split(sep)
        if len(parts) == 3:
            d, m, y = parts
            if len(y) == 4 and d.isdigit() and m.isdigit():
                return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return ""


def compute_egais_operation_key(row):
    """Стабильный ключ дедупликации ОДНОЙ строки выгрузки ЕГАИС для журнала
    (см. CREATE TABLE egais_operation в db.py) - хэш от ВСЕХ содержательных
    колонок строки, кроме служебных (_EGAIS_AUDIT_COLUMNS). row - сырой
    dict {нормализованный_заголовок: значение}, как отдаёт _read_egais_rows().

    Почему нельзя просто взять "id Склад операции" или "Номер документа" -
    на реальной выгрузке (проверено 2026-09-24, см. переписку с
    пользователем) "id Склад операции" оказалась ID СКЛАДА, а не строки
    (66 уникальных значений на 5409 строк) - для дедупликации бесполезна.
    "Номер документа" одного документа может содержать НЕСКОЛЬКО строк
    (разные породы/брёвна поштучного учёта) - их нельзя схлопывать в одну.
    Хэш от всех содержательных колонок различает оба случая правильно:
    буквальный дубль строки в самой выгрузке ЕГАИС (все колонки совпадают)
    схлопывается, а разные брёвна одного документа (отличаются
    "Номенклатурой"/"Кол-во") - нет."""
    items = sorted(
        (k, "" if v is None else str(v))
        for k, v in row.items()
        if k not in _EGAIS_AUDIT_COLUMNS
    )
    raw = "\x1f".join(f"{k}\x1e{v}" for k, v in items)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract_egais_operations(excel_path):
    """Построчный разбор выгрузки ЕГАИС для ЖУРНАЛА (egais_operation) -
    в отличие от parse_egais_reestr (который только суммирует "чистый"
    приход по делянкам, с исключением задвоений и откладыванием ФЛС на
    разбор) здесь сохраняется КАЖДАЯ содержательная строка любого типа
    документа как есть, без интерпретации - сырой аудиторский след,
    который лесничий видит на экране "Журнал ЕГАИС". Пропускается только
    служебный "футер" отчёта (см. _operations_from_raw_rows - строка с
    одновременно пустыми "Тип документа" и "Склад операции")."""
    return _operations_from_raw_rows(_read_egais_rows(excel_path))


def _operations_from_raw_rows(rows):
    """Общая часть extract_egais_operations/_parse_egais_reestr_impl -
    сырые строки Excel (см. _read_egais_rows) -> нормализованные
    dict-операции (тот же формат, что хранится построчно в
    egais_operation, см. _EGAIS_OPERATION_COLUMNS)."""
    operations = []
    for row in rows:
        doc_type = row.get(_EGAIS_COL_DOC_TYPE)
        sklad_name = row.get(_EGAIS_COL_SKLAD_NAME)
        if not _egais_not_empty(doc_type) and not _egais_not_empty(sklad_name):
            continue
        data_dok = _egais_str(row.get(_EGAIS_COL_DATA_DOK))
        operations.append({
            "natural_key": compute_egais_operation_key(row),
            "data_dokumenta": data_dok,
            "data_dokumenta_sort": _egais_date_sort_key(data_dok),
            "tip_dokumenta": _egais_str(doc_type),
            "nomer_dokumenta": _egais_str(row.get(_EGAIS_COL_DOC_NUM)),
            "nomer_svyazannogo_dokumenta": _egais_str(row.get(_EGAIS_COL_LINKED_DOC)),
            "kvartal": _egais_clean_number(row.get(_EGAIS_COL_KVARTAL)),
            "vydel": _egais_clean_number(row.get(_EGAIS_COL_VYDEL)),
            "sklad": _egais_str(sklad_name),
            "sklad_kontragent": _egais_str(row.get(_EGAIS_COL_SKLAD_KONTRAGENT)),
            "poroda": _egais_str(row.get(_EGAIS_COL_PORODA)),
            "sort": _egais_str(row.get(_EGAIS_COL_SORT)),
            "tehnicheskaya_godnost": _egais_str(row.get(_EGAIS_COL_GODNOST)),
            "nomenklatura": _egais_str(row.get(_EGAIS_COL_NOMENKLATURA)),
            "gruppa_diametrov": _egais_str(row.get(_EGAIS_COL_GRUPPA_DIAMETROV)),
            "kolvo": _egais_str(row.get(_EGAIS_COL_KOLVO)),
            "obyom": _egais_to_float(row.get(_EGAIS_COL_OBYOM)),
            "osnovanie": _egais_str(row.get(_EGAIS_COL_OSNOVANIE)),
            "nomer_osnovaniya": _egais_str(row.get(_EGAIS_COL_OSNOVANIE_NUM)),
            "sotrudnik": _egais_str(row.get(_EGAIS_COL_SOTRUDNIK)),
        })
    return operations


def save_egais_operations(conn, operations):
    """Сохраняет строки журнала ЕГАИС (см. extract_egais_operations) -
    INSERT OR IGNORE по UNIQUE(natural_key), поэтому повторный импорт того
    же файла или пересекающихся по датам выгрузок НИЧЕГО не задваивает - в
    отличие от save_egais_snapshot (которая замещает данные по затронутым
    делянкам), эта таблица только растёт, что и требуется для ежедневных
    выгрузок-"дельт" по всем кварталам (см. обсуждение с пользователем,
    24.09.2026). Возвращает число РЕАЛЬНО добавленных (новых) строк - чтобы
    после импорта показать лесничему "добавлено N новых записей в журнал",
    а не молча повторить то, что уже было."""
    if not operations:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.executemany(
        "INSERT OR IGNORE INTO egais_operation "
        "(natural_key, data_dokumenta, data_dokumenta_sort, tip_dokumenta, nomer_dokumenta, "
        "nomer_svyazannogo_dokumenta, kvartal, vydel, sklad, sklad_kontragent, "
        "poroda, sort, tehnicheskaya_godnost, nomenklatura, gruppa_diametrov, "
        "kolvo, obyom, osnovanie, nomer_osnovaniya, sotrudnik, imported_at) "
        "VALUES (:natural_key, :data_dokumenta, :data_dokumenta_sort, :tip_dokumenta, "
        ":nomer_dokumenta, :nomer_svyazannogo_dokumenta, :kvartal, :vydel, :sklad, "
        ":sklad_kontragent, :poroda, :sort, :tehnicheskaya_godnost, :nomenklatura, "
        ":gruppa_diametrov, :kolvo, :obyom, :osnovanie, :nomer_osnovaniya, :sotrudnik, "
        ":imported_at)",
        [dict(op, imported_at=now) for op in operations],
    )
    conn.commit()
    # rowcount по executemany с INSERT OR IGNORE в sqlite3 считает и
    # проигнорированные попытки - поэтому реальное число новых строк
    # считаем отдельным запросом, а не полагаемся на cur.rowcount.
    keys = [op["natural_key"] for op in operations]
    placeholders = ",".join("?" * len(keys))
    added = conn.execute(
        f"SELECT COUNT(*) FROM egais_operation WHERE natural_key IN ({placeholders}) "
        "AND imported_at = ?",
        (*keys, now),
    ).fetchone()[0]
    return added


_EGAIS_OPERATION_COLUMNS = (
    "id", "data_dokumenta", "data_dokumenta_sort", "tip_dokumenta", "nomer_dokumenta",
    "nomer_svyazannogo_dokumenta", "kvartal", "vydel", "sklad", "sklad_kontragent",
    "poroda", "sort", "tehnicheskaya_godnost", "nomenklatura", "gruppa_diametrov",
    "kolvo", "obyom", "osnovanie", "nomer_osnovaniya", "sotrudnik", "imported_at",
)


def list_egais_operations_for_item(conn, item, limit=1000):
    """Журнал ЕГАИС (сырые строки egais_operation) по ОДНОМУ выделу делянки,
    для видимого экрана "Журнал ЕГАИС" - та же "умная" привязка по
    пересечению чисел выдела, что и find_egais_entry_for_item
    (delyanka_item.vydel может быть составным: "6,10,12,18"). Сортировка -
    по дате документа по убыванию (сначала свежее)."""
    kvartal_clean = _egais_clean_number(item.get("kvartal"))
    wanted_vydel_numbers = _extract_vydel_numbers(item.get("vydel"))
    if not kvartal_clean or not wanted_vydel_numbers:
        return []
    rows = conn.execute(
        f"SELECT {', '.join(_EGAIS_OPERATION_COLUMNS)} FROM egais_operation "
        "WHERE kvartal=? ORDER BY data_dokumenta_sort DESC, id DESC",
        (kvartal_clean,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(zip(_EGAIS_OPERATION_COLUMNS, row))
        if wanted_vydel_numbers & _extract_vydel_numbers(d["vydel"]):
            result.append(d)
            if len(result) >= limit:
                break
    return result


def list_egais_operations(conn, kvartal=None, vydel=None, tip_dokumenta=None, limit=500):
    """Журнал ЕГАИС без привязки к конкретной делянке - для общего
    просмотра/поиска (например "все операции за такой-то квартал")."""
    where = []
    params = []
    if kvartal:
        where.append("kvartal=?")
        params.append(_egais_clean_number(kvartal))
    if vydel:
        where.append("vydel=?")
        params.append(_egais_clean_number(vydel))
    if tip_dokumenta:
        where.append("tip_dokumenta=?")
        params.append(tip_dokumenta)
    sql = f"SELECT {', '.join(_EGAIS_OPERATION_COLUMNS)} FROM egais_operation"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY data_dokumenta_sort DESC, id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(zip(_EGAIS_OPERATION_COLUMNS, row)) for row in rows]


def _egais_linked_doc_numbers(conn):
    """Множество номеров документов-приходов, которые являются "вторичным"
    (парным) приходом к "Расходу при внутреннем перемещении" - см.
    докстринг parse_egais_reestr про задвоение. Строится по ВСЕМУ журналу
    (всем накопленным импортам), а не по одному файлу, как в
    _parse_egais_reestr_impl - при ежедневных выгрузках-дельтах пара
    приход/расход может обнаружиться в РАЗНЫХ импортах."""
    rows = conn.execute(
        "SELECT DISTINCT nomer_svyazannogo_dokumenta FROM egais_operation "
        "WHERE tip_dokumenta=? AND nomer_svyazannogo_dokumenta != ''",
        (_EGAIS_DOC_TYPE_VNUTR_PEREMESHENIE,),
    ).fetchall()
    return {r[0] for r in rows}


def compute_egais_balance_check(conn, item):
    """Сверка "расход не может быть больше прихода" по журналу ЕГАИС
    (egais_operation) для ОДНОГО выдела делянки - НАКОПИТЕЛЬНО по всей
    сохранённой истории, а не по одному импорту (специально для
    ежедневных выгрузок-дельт по всем кварталам, см. обсуждение с
    пользователем 24.09.2026).

    Логика склада: приход не может быть меньше расхода-реализации (продали
    больше, чем приняли на склад, без корректировки остатков - физически
    невозможно). Если это всё же произошло в данных - значит либо
    неразобранный приход на ФЛС ещё не подтверждён (см.
    egais_fls_prihod_review), либо была корректировка остатков, либо у
    делянки есть более ранняя история движения, не попавшая в текущий
    журнал ("холодный старт" - делянка начала отгружаться раньше, чем в
    приложение стали загружать выгрузки ЕГАИС).

    "Перевод" и "Расход при внутреннем перемещении" в приход/расход не
    идут - оба нейтральны (см. _EGAIS_DOC_TYPE_PEREVOD, докстринг
    parse_egais_reestr).

    Возвращает None, если по этому выделу в журнале вообще нет строк
    (значит, выгрузку по нему ещё не загружали - это не дефицит, а просто
    отсутствие данных). Иначе dict:
        prihod_chisty, rashod_realizatsii, deficit (>=0),
        fls_unresolved, korrektirovki_unresolved,
        explained (bool - дефицит покрывается неразобранными ФЛС/
        корректировками, ничего дополнительно делать не нужно, кроме как
        разобрать именно их)."""
    kvartal_clean = _egais_clean_number(item.get("kvartal"))
    wanted_vydel_numbers = _extract_vydel_numbers(item.get("vydel"))
    if not kvartal_clean or not wanted_vydel_numbers:
        return None

    rows = conn.execute(
        "SELECT tip_dokumenta, nomer_dokumenta, osnovanie, nomer_osnovaniya, sklad, vydel, obyom "
        "FROM egais_operation WHERE kvartal=?",
        (kvartal_clean,),
    ).fetchall()
    matched = [r for r in rows if wanted_vydel_numbers & _extract_vydel_numbers(r[5])]
    if not matched:
        return None

    linked = _egais_linked_doc_numbers(conn)
    prihod_chisty = 0.0
    rashod_realizatsii = 0.0
    for tip, nomer, osnovanie, osnovanie_num, sklad, vydel, obyom in matched:
        obyom = obyom or 0.0
        if tip == _EGAIS_DOC_TYPE_PRIHOD:
            is_linked_pair = bool(nomer) and nomer in linked
            has_osnovanie = bool(osnovanie) or bool(osnovanie_num)
            is_fls = (sklad or "").startswith("ФЛС")
            if is_linked_pair or (has_osnovanie and not is_fls):
                continue  # вторичный приход (задвоение) - не считаем
            if is_fls:
                continue  # ФЛС-приход - отдельно, через fls_unresolved ниже
            prihod_chisty += obyom
        elif tip == _EGAIS_DOC_TYPE_REALIZATSIYA:
            rashod_realizatsii += abs(obyom)
        # "Расход при внутреннем перемещении", "Перевод" - нейтральны.

    def _sum_unresolved(table):
        rows = conn.execute(
            f"SELECT vydel, obyom FROM {table} WHERE kvartal=? AND status='new'",
            (kvartal_clean,),
        ).fetchall()
        return sum(o or 0.0 for vd, o in rows if wanted_vydel_numbers & _extract_vydel_numbers(vd))

    fls_unresolved = _sum_unresolved("egais_fls_prihod_review")
    korrektirovki_unresolved = _sum_unresolved("egais_korrektirovka_review")

    deficit = max(0.0, rashod_realizatsii - prihod_chisty)
    explained = deficit <= 0.01 or (fls_unresolved + korrektirovki_unresolved) >= deficit - 0.5

    return {
        "prihod_chisty": round(prihod_chisty, 3),
        "rashod_realizatsii": round(rashod_realizatsii, 3),
        "deficit": round(deficit, 3),
        "fls_unresolved": round(fls_unresolved, 3),
        "korrektirovki_unresolved": round(korrektirovki_unresolved, 3),
        "explained": explained,
    }


def add_fls_prihod_to_egais_snapshot(conn, kvartal, vydel, poroda, sortiment, obyom, sklad="",
                                      review_row_id=None):
    """Добавляет ОДИН объём — результат разбора одной строки очереди
    egais_fls_prihod_review со статусом "считать отдельно" — сразу в ОБА
    снапшота ЕГАИС: egais_snapshot (плоский, которым изначально
    пользовался только бот) И egais_snapshot_detail (структурный).

    До этой функции resolve_fls_prihod (app/routers/raskhod.py) писал
    объём ТОЛЬКО в egais_snapshot, ошибочно полагая, что бот и веб-баланс
    берут ЕГАИС-факт из разных мест. На деле и веб-таблица баланса
    (compute_balance_batch), и сам бот (get_remaining_volumes_for_bot,
    он тоже вызывает compute_balance) читают ЕГАИС ИСКЛЮЧИТЕЛЬНО через
    load_egais_snapshot(), а он смотрит в egais_snapshot_detail — туда
    старый код вообще не писал. Поэтому разобранная ФЛС "подтверждалась"
    в очереди, объём физически попадал в БД, но нигде в балансе не
    появлялся; особенно заметно, если в выгрузке ЕГАИС вообще нет обычных
    приходов на ПЛС и весь факт делянки — только из ФЛС.

    Раздельная сумма по сортименту накапливается в porody_json так же, как
    это делает save_egais_snapshot() при обычном импорте — сохраняем
    формат идентичным, чтобы load_egais_snapshot() не отличал "пришедшее
    из разбора очереди" от "пришедшего из файла".

    review_row_id: если передан, дополнительно помечает саму строку
    egais_fls_prihod_review (applied_to_snapshot_detail=1) — и живой
    resolve_fls_prihod(), и одноразовый backfill в db.py:migrate_schema()
    (для строк, разобранных ДО этого исправления) обязаны передавать его,
    иначе при следующем перезапуске backfill найдёт ту же строку снова
    (status='schitat_otdelno' и флаг всё ещё 0) и задвоит объём."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1) плоский снапшот — как и раньше, для обратной совместимости.
    drova = obyom if sortiment == "дрова" else 0
    delovaya = obyom if sortiment != "дрова" else 0
    existing_flat = conn.execute(
        "SELECT id, delovaya_obyom, drova_obyom FROM egais_snapshot "
        "WHERE kvartal=? AND vydel=? AND poroda=?",
        (kvartal, vydel, poroda),
    ).fetchone()
    if existing_flat:
        conn.execute(
            "UPDATE egais_snapshot SET delovaya_obyom=delovaya_obyom+?, drova_obyom=drova_obyom+? "
            "WHERE id=?",
            (delovaya, drova, existing_flat[0]),
        )
    else:
        conn.execute(
            "INSERT INTO egais_snapshot (imported_at, kvartal, vydel, poroda, delovaya_obyom, drova_obyom) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now, kvartal, vydel, poroda, delovaya, drova),
        )

    # 2) детальный снапшот — именно его раньше не хватало (см. докстринг).
    existing_detail = conn.execute(
        "SELECT porody_json FROM egais_snapshot_detail WHERE kvartal=? AND vydel=?",
        (kvartal, vydel),
    ).fetchone()
    if existing_detail:
        (porody_json,) = existing_detail
        try:
            porody = json.loads(porody_json) if porody_json else {}
        except (TypeError, ValueError):
            porody = {}
        sorta = porody.setdefault(poroda, {})
        sorta[sortiment] = (sorta.get(sortiment) or 0) + obyom
        conn.execute(
            "UPDATE egais_snapshot_detail SET porody_json=?, imported_at=? "
            "WHERE kvartal=? AND vydel=?",
            (json.dumps(porody, ensure_ascii=False), now, kvartal, vydel),
        )
    else:
        porody = {poroda: {sortiment: obyom}}
        conn.execute(
            "INSERT INTO egais_snapshot_detail "
            "(kvartal, vydel, imported_at, nazvanie_sklada, porody_json, korrektirovki_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (kvartal, vydel, now, sklad or "", json.dumps(porody, ensure_ascii=False), "[]"),
        )
    conn.commit()

    if review_row_id is not None:
        conn.execute(
            "UPDATE egais_fls_prihod_review SET applied_to_snapshot_detail=1 WHERE id=?",
            (review_row_id,),
        )
        conn.commit()


def _egais_matched_keys_for_item(conn, kvartal_clean, wanted_vydel_numbers):
    """Ключи (kvartal, vydel), реально встречающиеся в данных ЕГАИС для
    этого выдела - объединяет egais_operation (журнал, Этап 1 - основной,
    полный источник) И egais_snapshot_detail (старый снимок - на случай
    БД, где журнал ещё пуст, см. load_egais_snapshot/_load_egais_snapshot_legacy),
    иначе для делянок с пустым "чистым" приходом (весь приход отложен на
    ФЛС/задвоен - в старый снимок такие вообще не попадали, см.
    save_egais_snapshot) найденных ключей не было бы вовсе, и удалить их
    данные из журнала не получилось бы."""
    keys = set()
    for table in ("egais_operation", "egais_snapshot_detail"):
        try:
            rows = conn.execute(
                f"SELECT DISTINCT kvartal, vydel FROM {table} WHERE kvartal=?",
                (kvartal_clean,),
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        keys.update(
            (kv, vd) for kv, vd in rows if wanted_vydel_numbers & _extract_vydel_numbers(vd)
        )
    return keys


def _delete_egais_data_for_keys(conn, matched_keys):
    for kv, vd in matched_keys:
        conn.execute("DELETE FROM egais_operation WHERE kvartal=? AND vydel=?", (kv, vd))
        conn.execute("DELETE FROM egais_snapshot_detail WHERE kvartal=? AND vydel=?", (kv, vd))
        conn.execute("DELETE FROM egais_snapshot WHERE kvartal=? AND vydel=?", (kv, vd))


def delete_egais_snapshot_for_item(conn, item):
    """Удаляет данные выгрузки ЕГАИС, относящиеся к ОДНОМУ выделу делянки
    (kvartal/vydel из delyanka_item), не трогая записи остальных выделов.
    Ключи (kvartal, vydel) ищутся тем же "умным" пересечением чисел
    выдела, что и в find_egais_entry_for_item - иначе для составных
    выделов ничего бы не удалилось.

    Чистит ВСЕ три таблицы данных ЕГАИС: журнал (egais_operation, Этап 1 -
    основной источник, из которого теперь читает баланс, см.
    load_egais_snapshot) и обе таблицы старого снимка (egais_snapshot,
    egais_snapshot_detail) - раньше (до перевода баланса на журнал) чистка
    только снимка была достаточна; теперь без удаления из журнала кнопка
    "удалить данные ЕГАИС" молча переставала бы работать (данные
    оставались бы видны, потому что баланс их всё равно читает из
    нетронутого журнала). Очереди ручного разбора (egais_*_review) не
    трогаются - это история, а не снимок, удаление выгрузки по одной
    делянке не должно "забывать", что корректировка или неизвестная
    делянка когда-то были замечены.

    Возвращает True, если что-то было удалено, иначе False (нечего
    удалять - выгрузка ЕГАИС не загружена вовсе, либо в ней нет данных по
    этому выделу)."""
    kvartal_clean = _egais_clean_number(item.get("kvartal"))
    wanted_vydel_numbers = _extract_vydel_numbers(item.get("vydel"))
    if not wanted_vydel_numbers:
        return False

    matched_keys = _egais_matched_keys_for_item(conn, kvartal_clean, wanted_vydel_numbers)
    if not matched_keys:
        return False

    _delete_egais_data_for_keys(conn, matched_keys)
    conn.commit()
    return True


def delete_egais_snapshot_for_delyanka(conn, items):
    """Массовое удаление данных выгрузки ЕГАИС сразу по всем выделам ОДНОЙ
    делянки — та же "умная" логика сопоставления kvartal/vydel, что и в
    delete_egais_snapshot_for_item (см. её докстринг, включая журнал), но
    одним проходом по списку items делянки (см. get_delyanka_items) и
    одним commit в конце, а не по одному выделу за раз - иначе
    пользователю пришлось бы заходить в каждый выдел делянки по очереди,
    чтобы почистить ошибочную выгрузку.

    Очереди ручного разбора (egais_*_review) не трогаются по тем же
    причинам, что и в delete_egais_snapshot_for_item.

    Возвращает список items (из переданных), по которым реально что-то
    удалилось - вызывающий код использует len() для сообщения вида
    "удалено N из M выделов"."""
    touched = []
    for item in items:
        kvartal_clean = _egais_clean_number(item.get("kvartal"))
        wanted_vydel_numbers = _extract_vydel_numbers(item.get("vydel"))
        if not wanted_vydel_numbers:
            continue
        matched_keys = _egais_matched_keys_for_item(conn, kvartal_clean, wanted_vydel_numbers)
        if not matched_keys:
            continue
        _delete_egais_data_for_keys(conn, matched_keys)
        touched.append(item)
    if touched:
        conn.commit()
    return touched


_EGAIS_DIAMETER_DO_RE = re.compile(r"до\s*(\d+)")
_EGAIS_DIAMETER_RANGE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")
_EGAIS_DIAMETER_RE = re.compile(r"(\d+)\s*см")


def _egais_diameter_category(diameter_cm):
    """Классификация по крупности, которой пользуется лесничий при сверке
    с нарядами: до 13 см - мелкая (ML), 14-25 см - средняя (SR), 26 см и
    более - крупная (KR). diameter_cm может быть дробным (например,
    середина диапазона "Группы диметров" вида "20-30") - сравнения ниже
    это переживают."""
    if diameter_cm is None:
        return None
    if diameter_cm <= 13:
        return "ML"
    if diameter_cm <= 25:
        return "SR"
    return "KR"


def _egais_krupnost_for_row(poroda, nomenklatura, gruppa_diametrov):
    """Определяет крупность (KR/SR/ML) деловой древесины по диаметру -
    НЕ по колонке "Сорт" (та про качество по ГОСТу, а не про размер).

    Источник диаметра зависит от метода учёта конкретной строки:
      - строки "гр" (групповой учёт, мелкая древесина) - диаметр не
        точный, берём из структурированной колонки "Группа диметров"
        (например "до 13 см");
      - строки "шт" (поштучный учёт) - точный диаметр текстом внутри
        "Номенклатуры" (например "36 см") - у "гр"-строк эта колонка
        обычно дублирует то же самое текстом, поэтому колонка "Группа
        диметров", если она непустая, в приоритете, а "Номенклатура" -
        запасной вариант.

    Особый случай - Осина, категория крупности ЕГАИС "4-40" (широкий
    групповой диапазон диаметра, отдельный от обычной сетки "до 13 см" -
    в отличие от прочих пород у осины эта группа считается ОТДЕЛЬНОЙ
    категорией крупности, а не мелкой): по решению лесничего относится к
    средней (SR) целиком, независимо от арифметики диапазона.

    Возвращает None, если ни в "Группе диметров", ни в "Номенклатуре" не
    нашлось ничего похожего на диаметр/группу - такие строки не
    выбрасываются молча, а попадают в стат. список
    "krupnost_ne_opredelena" в _parse_egais_reestr_impl."""
    poroda_norm = str(poroda or "").strip().casefold()
    # ВАЖНО: "Группа диметров" в реальной выгрузке пуста почти всегда
    # (заполнена только у строк "гр") - если КАЖДОЕ значение колонки в
    # файле пустое, pandas читает её как float64 NaN, и даже
    # df.where(df.notna(), None) не превращает такую ячейку в None (NaN
    # остаётся NaN - в float-колонке None физически не хранится, pandas
    # молча приводит его обратно к NaN). Голый `gruppa_diametrov or ""`
    # на NaN даёт строку "nan" (NaN truthy!), которая не парсится и на
    # каждой такой строке ложно уводит объём в "б/р". Поэтому здесь
    # обязательно используем _egais_not_empty (уже отличает NaN от
    # реального текста), а не проверку через `or`.
    gruppa = str(gruppa_diametrov).strip() if _egais_not_empty(gruppa_diametrov) else ""
    nomen = str(nomenklatura).strip() if _egais_not_empty(nomenklatura) else ""

    combined_no_spaces = (gruppa + " " + nomen).replace(" ", "")
    if poroda_norm == "осина" and "4-40" in combined_no_spaces:
        return "SR"

    text = gruppa or nomen
    if not text:
        return None

    m = _EGAIS_DIAMETER_DO_RE.search(text)
    if m:
        return _egais_diameter_category(int(m.group(1)))

    m = _EGAIS_DIAMETER_RANGE_RE.search(text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return _egais_diameter_category((lo + hi) / 2)

    m = _EGAIS_DIAMETER_RE.search(text)
    if m:
        return _egais_diameter_category(int(m.group(1)))

    return None


def _parse_egais_reestr_impl(excel_path):
    rows = _read_egais_rows(excel_path)

    # ЕГАИС умеет отдавать "Реестр движения по складам" с разным набором
    # колонок в зависимости от настроек экспорта - на практике встречался
    # вариант БЕЗ "Порода"/"Сорт"/"Объем"/"Кол-во"/"Номенклатура"/
    # "Сотрудник" вообще (только служебные поля вроде статуса доставки).
    # Без явной проверки такой файл тихо "парсился" в пустые/нулевые
    # данные - количество документов и склады находились правильно, а
    # объёмы оставались 0, что выглядело как баг сверки, хотя на самом
    # деле в файле просто неоткуда взять цифры. Проверяем сразу и даём
    # понятную ошибку вместо тихой пустоты.
    if rows:
        available_columns = set(rows[0].keys())
        required_columns = {_EGAIS_COL_PORODA, _EGAIS_COL_OBYOM}
        missing = required_columns - available_columns
        if missing:
            raise ValueError(
                "В выбранном файле нет колонок " + ", ".join(sorted(missing)) + " — "
                "похоже, это не тот отчёт ЕГАИС (или экспортирован с другим набором "
                "колонок). Нужен «Реестр движения по складам» с колонками Порода, "
                "Сорт, Объём, Кол-во, Номенклатура, Сотрудник — переэкспортируйте файл "
                "с полным набором колонок."
            )

    operations = _operations_from_raw_rows(rows)
    return _aggregate_egais_operations(operations)


def _aggregate_egais_operations(operations):
    """Общая логика агрегации нормализованных операций ЕГАИС (формат
    extract_egais_operations/egais_operation, см. _EGAIS_OPERATION_COLUMNS)
    в {(kvartal, vydel): {...}} + stats — раньше это был единственный
    проход по СЫРЫМ строкам Excel внутри _parse_egais_reestr_impl (см.
    _operations_from_raw_rows выше — та же логика колонок, просто
    вынесенная в отдельный шаг); теперь эта же проверенная логика (дедуп
    задвоений, классификация крупности, отсрочка ФЛС, корректировки,
    неизвестные типы) используется ЕЩЁ и load_egais_snapshot() для
    агрегации НАКОПЛЕННОГО журнала (egais_operation) - и на одном свежем
    файле, и на всей истории объёмы считаются идентично, одним кодом."""
    # 1) множество номеров документов, которые являются "вторичным приходом"
    #    (парой к "Расходу при внутреннем перемещении")
    linked_doc_numbers = set()
    for op in operations:
        if op["tip_dokumenta"] == _EGAIS_DOC_TYPE_VNUTR_PEREMESHENIE:
            linked = op.get("nomer_svyazannogo_dokumenta")
            if linked:
                linked_doc_numbers.add(str(linked).strip())

    result = {}
    # Точные названия складов на делянку - множество, НЕ подстрока в строке.
    # Раньше проверка "sklad_name not in entry['nazvanie_sklada']" была
    # проверкой ВХОЖДЕНИЯ ПОДСТРОКИ в уже накопленную строку "А; Б; В" - а
    # в реальной выгрузке ЕГАИС встречаются склады вида "ФЛС кв.90, выд.4
    # л.1 РГП" и "ФЛС кв.90, выд.4 л.1 РГП №2", где первое имя - буквально
    # подстрока второго. Если склад с "№2" попадался в файле раньше
    # базового имени, базовое имя молча "не добавлялось" (программа решала,
    # что оно уже учтено) - хотя это два разных склада. На сумму объёма это
    # не влияло (группировка идёт по кварталу/выделу, не по названию
    # склада), но список складов на экране мог показывать не все реально
    # задействованные склады.
    sklad_names_seen = {}
    prihod_total = 0
    prihod_excluded = 0
    obyom_excluded = 0.0
    prihod_used = 0
    fls_total = 0  # строк "Приход" на склад ФЛС, отложенных на разбор - см. ниже
    neizvestnye_tipy = []  # строки с незнакомым "Тип документа" - см. _EGAIS_KNOWN_DOC_TYPES
    krupnost_ne_opredelena = []  # деловая древесина, у которой не вышло определить KR/SR/ML - см. _egais_krupnost_for_row

    for op in operations:
        doc_type = op["tip_dokumenta"]

        if doc_type not in _EGAIS_KNOWN_DOC_TYPES:
            # Ничего не выбрасываем молча - собираем "как есть", чтобы
            # объём был виден на экране, даже если мы пока не знаем, что
            # это за тип документа (в т.ч. пустые/битые строки выгрузки).
            neizvestnye_tipy.append({
                "tip_dokumenta": doc_type,
                "kvartal": op.get("kvartal") or "",
                "vydel": op.get("vydel") or "",
                "sklad": op.get("sklad") or "",
                "obyom": op.get("obyom") or 0.0,
                "data": op.get("data_dokumenta") or "",
                "sotrudnik": op.get("sotrudnik") or "",
                "nomer_dokumenta": op.get("nomer_dokumenta") or "",
            })
            continue

        if doc_type == _EGAIS_DOC_TYPE_KORREKTIROVKA:
            kvartal_str = op.get("kvartal") or ""
            vydel_str = op.get("vydel") or ""
            if not kvartal_str and not vydel_str:
                continue
            delyanka_key = (kvartal_str, vydel_str)
            entry = result.setdefault(delyanka_key, {
                "nazvanie_sklada": "",
                "kvartal": kvartal_str,
                "vydel": vydel_str,
                "porody": {},
                "korrektirovki": [],
                "fls_prihod": [],
            })
            entry.setdefault("korrektirovki", []).append({
                "data": op.get("data_dokumenta") or "",
                "sklad": op.get("sklad") or "",
                "poroda": op.get("poroda") or "",
                "obyom": op.get("obyom") or 0.0,
                "sotrudnik": op.get("sotrudnik") or "",
                "nomer_dokumenta": op.get("nomer_dokumenta") or "",
            })
            continue

        if doc_type != _EGAIS_DOC_TYPE_PRIHOD:
            # "Расход при внутреннем перемещении" (уже разобран выше на
            # linked_doc_numbers), "Расход при реализации потребителю"
            # (продажа - объём не прибавляет) и "Перевод" (переклассификация
            # уже учтённой древесины, не новое поступление) - в факт этой
            # функции (только приход) не идут. Расход-реализация и
            # накопительная сверка приход/расход считаются отдельно, по
            # журналу - см. compute_egais_balance_check.
            continue
        prihod_total += 1

        doc_num = str(op.get("nomer_dokumenta") or "").strip()
        osnovanie = op.get("osnovanie")
        osnovanie_num = op.get("nomer_osnovaniya")
        sklad_name_check = str(op.get("sklad") or "").strip()

        is_linked_pair = bool(doc_num) and doc_num in linked_doc_numbers
        has_osnovanie = bool(osnovanie) or bool(osnovanie_num)
        is_fls_sklad = sklad_name_check.startswith("ФЛС")

        # "Основание"/"Номер основания" заполнены - надёжный признак
        # ВТОРИЧНОГО (задвоенного) прихода, но ТОЛЬКО для складов, отличных
        # от ФЛС (см. докстринг parse_egais_reestr: у первичного прихода
        # эти поля пусты, у "автоматизированного оприходования" по
        # расходному документу - заполнены). На складе ФЛС "Основание"
        # сплошь и рядом ссылается на лесорубочный билет/декларацию
        # именно ПЕРВИЧНОГО прихода - ФЛС является верхним складом
        # делянки, туда древесина попадает впервые, а не "автоматически
        # оприходуется" по чужому расходному документу. Раньше эвристика
        # has_osnovanie применялась и к складам ФЛС наравне со всеми - изза
        # чего реальный приход на ФЛС тихо выбрасывался в prihod_excluded
        # ЕЩЁ ДО ветки sklad_name.startswith("ФЛС") ниже (строка 1639 в
        # старой нумерации) и не попадал даже в очередь ручного разбора
        # (fls_prihod) - объём исчезал без единого следа, даже "Разбор
        # ЕГАИС" показывал 0. Настоящую пару к "Расходу при внутреннем
        # перемещении" (is_linked_pair) по-прежнему исключаем независимо
        # от склада - это надёжный признак задвоения сам по себе, ФЛС не
        # исключение.
        if is_linked_pair or (has_osnovanie and not is_fls_sklad):
            prihod_excluded += 1
            obyom_excluded += op.get("obyom") or 0.0
            continue

        prihod_used += 1

        kvartal_str = op.get("kvartal") or ""
        vydel_str = op.get("vydel") or ""
        if not kvartal_str and not vydel_str:
            # совсем без привязки к участку - пропускаем строку, чтобы не
            # собрать мусорный ключ ("", "")
            continue
        delyanka_key = (kvartal_str, vydel_str)

        entry = result.setdefault(delyanka_key, {
            "nazvanie_sklada": "",
            "kvartal": kvartal_str,
            "vydel": vydel_str,
            "porody": {},
            "korrektirovki": [],
            "fls_prihod": [],
        })
        sklad_name = sklad_name_check
        if sklad_name:
            seen = sklad_names_seen.setdefault(delyanka_key, [])
            if sklad_name not in seen:
                seen.append(sklad_name)
                entry["nazvanie_sklada"] = "; ".join(seen)

        poroda = str(op.get("poroda") or "").strip()
        if not poroda:
            continue

        godnost = str(op.get("tehnicheskaya_godnost") or "").strip()
        if godnost == "Дровяная древесина":
            sortiment = "дрова"
        else:
            krupnost = _egais_krupnost_for_row(
                poroda, op.get("nomenklatura"), op.get("gruppa_diametrov"),
            )
            if krupnost is None:
                # Не смогли достать диаметр/группу ни из "Номенклатуры",
                # ни из "Группы диметров" - не теряем объём молча (как и
                # с неизвестными типами документа выше): кладём в
                # отдельный бакет "б/р" (без размера) и фиксируем строку
                # в статистике, чтобы это было видно на экране импорта.
                sortiment = "б/р"
                krupnost_ne_opredelena.append({
                    "kvartal": kvartal_str,
                    "vydel": vydel_str,
                    "poroda": poroda,
                    "nomenklatura": str(op.get("nomenklatura") or "").strip(),
                    "gruppa_diametrov": str(op.get("gruppa_diametrov") or "").strip(),
                    "obyom": op.get("obyom") or 0.0,
                    "nomer_dokumenta": doc_num,
                })
            else:
                sortiment = krupnost

        obyom = op.get("obyom") or 0.0

        # Приход на склад ФЛС (верхний склад делянки) - редкий, но
        # легальный случай полной цепочки складов: Приход-ФЛС →
        # Расход-ФЛС → Приход-ПЛС (тот же объём) → Расход-ПЛС потребителю.
        # Если приплюсовать его сюда же, где и обычный (основной) приход
        # на ПЛС, объём делянки задвоится, когда позже (в этом же файле
        # или в следующем месяце) появится соответствующий приход на ПЛС.
        # Поэтому ФЛС-приход НЕ идёт в porody автоматически - откладываем
        # его в отдельный список на ручной разбор (см.
        # egais_fls_prihod_review в save_egais_snapshot ниже), где
        # лесничий сам решает: отдельная заготовка (учесть) или часть уже
        # посчитанной цепочки (не учитывать второй раз).
        if sklad_name.startswith("ФЛС"):
            fls_total += 1
            entry.setdefault("fls_prihod", []).append({
                "data": op.get("data_dokumenta") or "",
                "sklad": sklad_name,
                "poroda": poroda,
                "sortiment": sortiment,
                "obyom": obyom,
                "nomer_dokumenta": doc_num,
            })
            continue

        porody = entry["porody"]
        porody[poroda] = porody.get(poroda, {})
        porody[poroda][sortiment] = porody[poroda].get(sortiment, 0) + obyom

    stats = {
        "prihod_rows_total": prihod_total,
        "prihod_rows_excluded": prihod_excluded,
        "obyom_excluded": round(obyom_excluded, 3),
        "prihod_rows_used": prihod_used,
        # Строки с "Тип документа", не входящим в _EGAIS_KNOWN_DOC_TYPES -
        # ничего не потеряно молча, всё видно здесь (обычно пусто; если
        # ЕГАИС введёт новый тип операции, он попадёт сюда, а не исчезнет).
        "neizvestnye_tipy": neizvestnye_tipy,
        # Суммарный объём корректировок остатков по всем делянкам сразу -
        # для быстрого предупреждения на экране ("были корректировки на
        # столько-то м3, откройте делянку и посмотрите откуда").
        "korrektirovki_total_obyom": round(
            sum(k["obyom"] for entry in result.values() for k in entry.get("korrektirovki", [])),
            3,
        ),
        "korrektirovki_count": sum(len(entry.get("korrektirovki", [])) for entry in result.values()),
        # Приход на ФЛС, отложенный на ручной разбор (см. комментарий выше
        # про полную цепочку складов) - НЕ входит в объём делянки, пока
        # его не разберут на экране "Расход → ЕГАИС".
        "fls_prihod_total_obyom": round(
            sum(k["obyom"] for entry in result.values() for k in entry.get("fls_prihod", [])),
            3,
        ),
        "fls_prihod_count": fls_total,
        # Деловая древесина, у которой не вышло определить крупность
        # (KR/SR/ML) по "Номенклатуре"/"Группе диметров" - см.
        # _egais_krupnost_for_row. Такие строки не теряются: они попадают
        # в porody[порода]["б/р"], а не молча в KR/SR/ML.
        "krupnost_ne_opredelena": krupnost_ne_opredelena,
        "krupnost_ne_opredelena_obyom": round(
            sum(r["obyom"] for r in krupnost_ne_opredelena), 3
        ),
    }
    return result, stats


def _egais_to_float(value):
    """Безопасно превращает значение колонки "Объем" в float. В реальной
    выгрузке встречаются не только нормальные числа (int/float), но и
    строки вида '1 024.141' (пробел - разделитель разрядов тысяч,
    добавляется Excel/ЕГАИС при экспорте некоторых строк как текст) - на
    обычный float(...) это падает с ValueError. Здесь пробел (обычный и
    неразрывный \\xa0) вычищается перед парсингом; запятая как десятичный
    разделитель тоже на всякий случай подстраховывается."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return 0.0 if value != value else float(value)  # value != value -> NaN
    text = str(value).strip().replace("\xa0", "").replace(" ", "")
    if not text:
        return 0.0
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _egais_not_empty(value):
    if value is None:
        return False
    if isinstance(value, float):
        return value == value  # False для NaN
    text = str(value).strip()
    return bool(text) and text.lower() != "nan"


def _egais_str(value):
    """Приводит сырую ячейку выгрузки к строке, НЕ теряя пустоту на NaN —
    в отличие от наивного str(value or "").strip(), которое на NaN молча
    портит данные. _read_egais_rows (через pandas df.where(df.notna(),
    None)) подменяет NaN на None не во всех колонках — на практике живой
    float('nan') всё же встречается (проверено 24.09.2026 на реальной
    выгрузке, колонка "Основание"), а float('nan') в Python ИСТИНЕН как
    bool (не равен нулю) — поэтому "value or ''" возвращает сам nan, и
    str(nan) даёт буквальную строку "nan", которая дальше читается как
    непустое значение (например, ошибочно включает дедуп задвоений
    приходов — см. регрессию 24.09.2026: без этой функции почти весь
    приход в выгрузке ошибочно считался "вторичным"). _egais_not_empty
    уже умеет отличать такой NaN (в обеих формах — float и уже ставшую
    строку "nan") от настоящего значения — переиспользуем её вместо
    повторения той же проверки."""
    return str(value).strip() if _egais_not_empty(value) else ""


def _egais_clean_number(value):
    """139.0 -> '139', уже-строка остаётся как есть."""
    if value is None:
        return ""
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        if value.is_integer():
            return str(int(value))
        return str(value)
    return str(value).strip()


def _read_egais_rows(excel_path):
    """Читает выгрузку ЕГАИС и возвращает список dict {заголовок: значение}
    по каждой строке. Пробует pandas (быстрее, надёжнее с типами), при
    отсутствии pandas - падает обратно на openpyxl. Заголовки нормализуются
    через _normalize_egais_header() сразу здесь, в одном месте - весь
    остальной код парсера ищет колонки уже по нормализованным ключам."""
    try:
        import pandas as pd
    except ImportError:
        return _read_egais_rows_openpyxl(excel_path)

    df = pd.read_excel(excel_path)
    df = df.where(df.notna(), None)
    df.columns = [_normalize_egais_header(c) for c in df.columns]
    return df.to_dict(orient="records")


def _read_egais_rows_openpyxl(excel_path):
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)
    try:
        headers = next(rows_iter)
    except StopIteration:
        return []
    headers = [_normalize_egais_header(h) for h in headers]
    result = []
    for values in rows_iter:
        if all(v is None for v in values):
            continue
        result.append(dict(zip(headers, values)))
    return result


def save_egais_snapshot(conn, loaded_egais_data):
    """Сохраняет разобранную выгрузку ЕГАИС (результат parse_egais_reestr)
    в БД в ДВУХ видах, чтобы каждый потребитель брал свой:

    1) egais_snapshot — плоские суммы (delovaya_obyom/drova_obyom по
       породе), которыми пользуется Telegram-бот (см.
       _load_egais_grouped_for_vydel в raskhod.py) - формат и поведение
       не меняются, чтобы не трогать работающий бот.
    2) egais_snapshot_detail — полная структура без потери детализации
       (porody с реальными сортами ЕГАИС + korrektirovki), которой
       пользуется десктоп-экран "Расход" при восстановлении
       self.loaded_egais_data после перезапуска приложения (см.
       load_egais_snapshot ниже и RaskhodScreen.__init__ в
       screens/raskhod/screen.py) - именно её раньше не хватало, из-за
       чего после закрытия окна выгрузка ЕГАИС "пропадала" с экрана,
       хотя бот её продолжал видеть.

    Вызывается из screens/raskhod/screen.py сразу после
    rk.parse_egais_reestr_with_stats() при импорте файла.

    ВАЖНО (исправлено 2026-09; было DELETE FROM egais_snapshot без WHERE -
    полностью стирало ВСЕ делянки при каждом импорте, включая те, что не
    встретились в текущем файле - например, импорт августовской выгрузки
    стирал июльские данные делянок, которых не было в августовском файле,
    хотя их отдельно никто не переимпортировал). Теперь снимок - НЕ "вся
    база", а "последняя выгрузка ПО КАЖДОЙ делянке отдельно": при импорте
    заменяются старые строки только тех (квартал, выдел), что реально
    присутствуют в loaded_egais_data сейчас, данные остальных делянок из
    прошлых импортов не трогаются."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows_to_insert = []
    detail_rows_to_insert = []
    delyanka_keys = list((loaded_egais_data or {}).keys())
    for (kvartal, vydel), entry in (loaded_egais_data or {}).items():
        porody = entry.get("porody") or {}
        for poroda, sortimenty in porody.items():
            drova_obyom = float(sortimenty.get("дрова") or 0)
            delovaya_obyom = sum(v for k, v in sortimenty.items() if k != "дрова")
            if not delovaya_obyom and not drova_obyom:
                continue
            rows_to_insert.append((now, kvartal, vydel, poroda, delovaya_obyom, drova_obyom))

        # В detail-снапшот попадает делянка целиком, даже если porody
        # пусто, но есть корректировки остатков - иначе они бы молча
        # терялись при восстановлении после перезапуска.
        if porody or entry.get("korrektirovki"):
            detail_rows_to_insert.append((
                kvartal,
                vydel,
                now,
                entry.get("nazvanie_sklada") or "",
                json.dumps(porody, ensure_ascii=False),
                json.dumps(entry.get("korrektirovki") or [], ensure_ascii=False),
            ))

    # Удаляем старые строки ТОЛЬКО для делянок из текущего файла - не всю
    # таблицу целиком (см. докстринг выше). Делянки, которых в этом файле
    # нет вообще, сохраняют свой снимок от прошлого импорта нетронутым.
    if delyanka_keys:
        conn.executemany(
            "DELETE FROM egais_snapshot WHERE kvartal=? AND vydel=?", delyanka_keys
        )
    if rows_to_insert:
        conn.executemany(
            "INSERT INTO egais_snapshot (imported_at, kvartal, vydel, poroda, delovaya_obyom, drova_obyom) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows_to_insert,
        )

    if delyanka_keys:
        conn.executemany(
            "DELETE FROM egais_snapshot_detail WHERE kvartal=? AND vydel=?", delyanka_keys
        )
    if detail_rows_to_insert:
        conn.executemany(
            "INSERT INTO egais_snapshot_detail "
            "(kvartal, vydel, imported_at, nazvanie_sklada, porody_json, korrektirovki_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            detail_rows_to_insert,
        )

    _save_egais_review_queues(conn, loaded_egais_data, now)

    conn.commit()


def _save_egais_review_queues(conn, loaded_egais_data, now):
    """Наполняет очереди ручного разбора экрана "Расход → ЕГАИС" -
    корректировки остатков, приход на ФЛС без пары и неизвестные делянки
    (см. комментарий у соответствующих CREATE TABLE в db.py). В отличие от
    egais_snapshot/egais_snapshot_detail это ИСТОРИЯ, не снимок -
    существующие строки не трогаем (INSERT OR IGNORE по UNIQUE), меняет их
    только сам разбор на экране (см. app/routers/raskhod.py:
    /egais/review/*). Вызывается из save_egais_snapshot() внутри той же
    транзакции (общий conn.commit() в конце save_egais_snapshot)."""
    korrektirovka_rows = []
    fls_prihod_rows = []
    delyanka_keys_seen = set()

    for (kvartal, vydel), entry in (loaded_egais_data or {}).items():
        delyanka_keys_seen.add((kvartal, vydel))
        for k in entry.get("korrektirovki") or []:
            korrektirovka_rows.append((
                kvartal, vydel, k.get("poroda") or "", k.get("obyom") or 0,
                k.get("data") or "", k.get("nomer_dokumenta") or "",
                k.get("sklad") or "", k.get("sotrudnik") or "", now,
            ))
        for f in entry.get("fls_prihod") or []:
            fls_prihod_rows.append((
                kvartal, vydel, f.get("poroda") or "", f.get("sortiment") or "",
                f.get("obyom") or 0, f.get("data") or "", f.get("nomer_dokumenta") or "",
                f.get("sklad") or "", now,
            ))

    if korrektirovka_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO egais_korrektirovka_review "
            "(kvartal, vydel, poroda, obyom, data_dok, nomer_dokumenta, sklad, sotrudnik, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            korrektirovka_rows,
        )

    if fls_prihod_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO egais_fls_prihod_review "
            "(kvartal, vydel, poroda, sortiment, obyom, data_dok, nomer_dokumenta, sklad, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            fls_prihod_rows,
        )

    # Неизвестные делянки - квартал/выдел из ЕГАИС, которых нет ни в одной
    # delyanka_item. Денормализованное поле delyanka_item.kvartal/vydel -
    # тот же формат (TEXT), что и ключи loaded_egais_data, сравниваем
    # напрямую без парсинга номеров.
    if delyanka_keys_seen:
        known = {
            (row[0], row[1])
            for row in conn.execute(
                "SELECT DISTINCT kvartal, vydel FROM delyanka_item "
                "WHERE kvartal IS NOT NULL AND vydel IS NOT NULL"
            ).fetchall()
        }
        unmatched = delyanka_keys_seen - known
        for kvartal, vydel in unmatched:
            sklad = (loaded_egais_data.get((kvartal, vydel)) or {}).get("nazvanie_sklada") or ""
            conn.execute(
                "INSERT INTO egais_unmatched_delyanka "
                "(kvartal, vydel, nazvanie_sklada, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(kvartal, vydel) DO UPDATE SET "
                "last_seen_at=excluded.last_seen_at, "
                "nazvanie_sklada=excluded.nazvanie_sklada "
                "WHERE status='new'",
                (kvartal, vydel, sklad, now, now),
            )


def load_egais_snapshot(conn):
    """Данные ЕГАИС ТОЧНО в том формате, что возвращает
    parse_egais_reestr()/parse_egais_reestr_with_stats() —
    {(kvartal, vydel): {"nazvanie_sklada", "kvartal", "vydel", "porody",
    "korrektirovki"}} — без потери детализации (сорта ЕГАИС, корректировки
    остатков), чтобы им можно было напрямую заполнить self.loaded_egais_data
    на экране "Расход" при старте приложения (см. RaskhodScreen.__init__ в
    screens/raskhod/screen.py), а не только сумму, которой довольствуется
    Telegram-бот через egais_snapshot/_load_egais_grouped_for_vydel.

    С появлением журнала (egais_operation, Этап 1) источник —
    НАКОПЛЕННЫЙ журнал, агрегированный через _aggregate_egais_operations
    (та же логика, что и в parse_egais_reestr на свежем файле) - а не
    egais_snapshot_detail (снимок ПОСЛЕДНЕГО импорта, который при
    ежедневных выгрузках-дельтах по всем кварталам заменял бы данные по
    затронутым делянкам и терял накопленную историю, см. обсуждение с
    пользователем 24.09.2026). Если журнал ещё пуст (например, все
    имеющиеся импорты были СДЕЛАНЫ до появления этой таблицы, Этап 1, и
    файл с тех пор не переимпортировали) — подстраховка старым снимком
    (_load_egais_snapshot_legacy), чтобы уже загруженные данные не
    "исчезли" из интерфейса до следующего импорта.

    Возвращает (data, imported_at):
        data: dict в формате loaded_egais_data, {} если данных нет;
        imported_at: str | None — время последнего импорта из БД (как
        сохранено save_egais_operations/save_egais_snapshot,
        "%Y-%m-%d %H:%M:%S"), либо None, если импортов ещё не было."""
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_EGAIS_OPERATION_COLUMNS)} FROM egais_operation"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []

    if not rows:
        return _load_egais_snapshot_legacy(conn)

    operations = [dict(zip(_EGAIS_OPERATION_COLUMNS, row)) for row in rows]
    data, _stats = _aggregate_egais_operations(operations)
    imported_at = max(
        (op["imported_at"] for op in operations if op.get("imported_at")),
        default=None,
    )
    return data, imported_at


def _load_egais_snapshot_legacy(conn):
    """Старый путь load_egais_snapshot — читает egais_snapshot_detail
    (снимок ПОСЛЕДНЕГО импорта) напрямую. Подстраховка на случай, если
    журнал (egais_operation) ещё пуст — см. докстринг load_egais_snapshot."""
    try:
        rows = conn.execute(
            "SELECT kvartal, vydel, imported_at, nazvanie_sklada, porody_json, korrektirovki_json "
            "FROM egais_snapshot_detail"
        ).fetchall()
    except sqlite3.OperationalError:
        # Таблицы ещё нет (БД старее миграции egais_snapshot_detail, а
        # migrate_schema() почему-то не был вызван раньше) — ведём себя
        # как при пустом снапшоте, а не роняем старт экрана.
        return {}, None

    data = {}
    imported_at = None
    for kvartal, vydel, row_imported_at, nazvanie_sklada, porody_json, korrektirovki_json in rows:
        try:
            porody = json.loads(porody_json) if porody_json else {}
        except (TypeError, ValueError):
            porody = {}
        try:
            korrektirovki = json.loads(korrektirovki_json) if korrektirovki_json else []
        except (TypeError, ValueError):
            korrektirovki = []

        data[(kvartal, vydel)] = {
            "nazvanie_sklada": nazvanie_sklada or "",
            "kvartal": kvartal,
            "vydel": vydel,
            "porody": porody,
            "korrektirovki": korrektirovki,
        }
        if row_imported_at and (imported_at is None or row_imported_at > imported_at):
            imported_at = row_imported_at

    return data, imported_at

# =========================================================================
#   ИЗ export.py (строки 194-261) — БЕЗ ИЗМЕНЕНИЙ
# =========================================================================

def export_to_excel(conn, delyanka, item, output_path, templates_dir="."):
    import openpyxl

    template_path = Path(templates_dir) / RASKHOD_TEMPLATE
    if not template_path.exists():
        raise FileNotFoundError(f"Не найден бланк {template_path}")

    output_path = str(output_path)
    shutil.copy(template_path, output_path)
    wb = openpyxl.load_workbook(output_path)
    ws = wb["ОБРАЗЕЦ"]
    ws.title = f"кв {item.get('kvartal')} в {item.get('vydel')}"[:31]

    ws["B2"] = item.get("kvartal", "")
    ws["B3"] = item.get("vydel", "")
    ws["B4"] = item.get("lesoseka_nomer", "")
    ws["B7"] = delyanka.get("nomer_lesorubochnogo_bileta", "")

    limits = get_limits(item)
    row_limit = 11
    row_limit_110 = 15
    for poroda, cols in _COLS_DELOVAYA_GRADES.items():
        lim = limits.get(poroda, {})
        total = (lim.get("KR", 0) or 0) + (lim.get("SR", 0) or 0) + (lim.get("ML", 0) or 0)
        ws[f"{cols[0]}{row_limit}"] = total
        ws[f"{cols[0]}{row_limit_110}"] = round(total * 1.1, 2)
    for poroda, col in _COLS_DELOVAYA_SIMPLE.items():
        lim = limits.get(poroda, {})
        total = lim.get("KR", 0) or 0
        ws[f"{col}{row_limit}"] = total
        ws[f"{col}{row_limit_110}"] = round(total * 1.1, 2)
    for poroda, col in _COLS_DROVA.items():
        lim = limits.get(poroda, {})
        total = lim.get("DROVA", 0) or 0
        ws[f"{col}{row_limit}"] = total
        ws[f"{col}{row_limit_110}"] = round(total * 1.1, 2)

    naryady = list_naryady(conn, item["id"])
    row = 19
    last_month = None
    for n in naryady:
        month = _month_name(n.get("data", ""))
        if month != last_month:
            ws[f"A{row}"] = month
            last_month = month
        for pos in n["pozitsii"]:
            poroda, sortiment, obyom = pos["poroda"], pos["sortiment"], pos["obyom"]
            col = None
            if sortiment in ("KR", "SR", "ML") and poroda in _COLS_DELOVAYA_GRADES:
                idx = {"KR": 0, "SR": 1, "ML": 2}[sortiment]
                col = _COLS_DELOVAYA_GRADES[poroda][idx]
            elif sortiment == "KR" and poroda in _COLS_DELOVAYA_SIMPLE:
                col = _COLS_DELOVAYA_SIMPLE[poroda]
            elif sortiment == "DROVA":
                col = _COLS_DROVA.get(poroda)
            elif sortiment == "HVOROST":
                col = _COL_HVOROST
            if col:
                existing = ws[f"{col}{row}"].value or 0
                ws[f"{col}{row}"] = existing + obyom
        if n.get("ploshad"):
            ws[f"{_COL_PLOSHAD}{row}"] = n["ploshad"]
        if n.get("nomer_naryada"):
            ws[f"{_COL_NARYAD}{row}"] = n["nomer_naryada"]
        row += 1

    wb.save(output_path)
    return output_path
