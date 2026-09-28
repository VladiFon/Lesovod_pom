# -*- coding: utf-8 -*-
"""Заполнение шаблона "Паспорт насаждения искусственного происхождения"
(templates/pasport_nasazhdeniya_shablon.docx, адаптация приложения 8) —
раскладывает журнал мероприятий участка (lesokultury_meropriyatiya) по
5 подтаблицам шаблона. См. pasport_generator.py (сборка вызова) и Этап 2
плана (агрегация по типам записей журнала)."""
from datetime import datetime

from docx.enum.text import WD_ALIGN_PARAGRAPH

from akt_template_fill import set_cell_text
from lesokultury_field_card_fill import _clone_rows_for

UHOD_TIPY = {"Агротехнический уход", "Химический уход"}
INVENTORY_TIPY = {
    "Инвентаризация 1-го года", "Инвентаризация 3-го года",
    "Инвентаризация на перевод", "Внеплановая инвентаризация",
}
PEREVOD_SPISANIE_TIPY = {"Перевод в покрытые лесом земли", "Списание"}


def _parse_date(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d.%m.%Y")
    except ValueError:
        return None


def _sorted_by_date(records):
    """Сортирует по дате по возрастанию — записи без разбираемой даты
    уходят в конец, сохраняя относительный порядок (id по возрастанию,
    т.к. list_lesokultury_meropriyatiya отдаёт DESC — здесь разворачиваем)."""
    records = list(reversed(records))
    return sorted(records, key=lambda m: (_parse_date(m.get("data")) is None, _parse_date(m.get("data")) or datetime.min))


def fill_uhody_table(table, meropriyatiya):
    """Таблица 1: уход за культурами — до 6 фиксированных строк (шаблон:
    заголовок + 6 строк-заготовок), в хронологическом порядке."""
    uhody = [m for m in meropriyatiya if m.get("tip") in UHOD_TIPY]
    uhody = _sorted_by_date(uhody)[:6]
    for i, m in enumerate(uhody):
        row = 1 + i
        set_cell_text(table, row, 0, m.get("data") or "", align=WD_ALIGN_PARAGRAPH.CENTER)
        opisanie = m.get("tip") or ""
        if m.get("primechaniya"):
            opisanie += f" — {m['primechaniya']}"
        set_cell_text(table, row, 1, opisanie, align=WD_ALIGN_PARAGRAPH.LEFT)


def fill_prizhivaemost_table(table, meropriyatiya):
    """Таблица 2: приживаемость по инвентаризациям — до 3 строк (шаблон:
    заголовок + 3 строки-заготовки), только записи с заполненной
    приживаемостью, в хронологическом порядке."""
    invs = [
        m for m in meropriyatiya
        if m.get("tip") in INVENTORY_TIPY and m.get("prizhivaemost_pct") is not None
    ]
    invs = _sorted_by_date(invs)[:3]
    for i, m in enumerate(invs):
        row = 1 + i
        set_cell_text(table, row, 0, m.get("data") or "", align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_text(table, row, 1, m.get("prizhivaemost_pct"), align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_text(table, row, 2, m.get("tip") or "", align=WD_ALIGN_PARAGRAPH.LEFT)


def fill_dopolnenie_table(table, meropriyatiya):
    """Таблица 3: дополнение лесных культур — растущая (шаблон: заголовок
    + 1 строка-заготовка, клонируется под фактическое число записей)."""
    dop = [m for m in meropriyatiya if m.get("tip") == "Дополнение"]
    dop = _sorted_by_date(dop)
    n = len(dop)
    if n == 0:
        for c in range(4):
            set_cell_text(table, 1, c, "", align=WD_ALIGN_PARAGRAPH.CENTER)
        return
    _clone_rows_for(table, n - 1)
    for i, m in enumerate(dop):
        row = 1 + i
        set_cell_text(table, row, 0, m.get("data") or "", align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_text(table, row, 1, m.get("sostav_fakt") or "", align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_text(table, row, 2, m.get("kolichestvo_na_ga"), align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_text(table, row, 3, m.get("primechaniya") or "", align=WD_ALIGN_PARAGRAPH.LEFT)


def fill_perevod_spisanie_table(table, meropriyatiya, ploshad_uchastka):
    """Таблица 4: перевод в покрытые лесом земли / списание — до 4
    фиксированных строк (шаблон: заголовок + 4 строки-заготовки).
    Площадь по конкретной записи журнала не хранится — берётся площадь
    участка целиком (эти события относятся к участку как таковому)."""
    events = [m for m in meropriyatiya if m.get("tip") in PEREVOD_SPISANIE_TIPY]
    events = _sorted_by_date(events)[:4]
    for i, m in enumerate(events):
        row = 1 + i
        set_cell_text(table, row, 0, m.get("tip") or "", align=WD_ALIGN_PARAGRAPH.LEFT)
        set_cell_text(table, row, 1, ploshad_uchastka, align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_text(table, row, 2, m.get("data") or "", align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_text(table, row, 3, m.get("id"), align=WD_ALIGN_PARAGRAPH.CENTER)
