# -*- coding: utf-8 -*-
"""Qt-свободная логика экрана "Рубки ухода" (осветление/прочистка в
молодняках) — расчёт запаса хвороста по обмеру укладок на пробных
площадях и сборка/валидация данных независимой пробы (uhody_proby).

Источник — screens/raskhod/osvetlenie/core.py (calculate_osvetlenie,
calculate_total_area, _parse_float), .../ai_recognition.py
(_collect_row_data) и .../komissiya.py (save_proba, тело сборки payload)
в десктопном проекте (PySide6). Здесь та же математика и та же форма
payload, но без единого виджета Qt — принимает и возвращает обычные
Python-структуры (list/dict), чтобы app/routers/uhody.py (Часть 2 плана)
мог использовать её напрямую в FastAPI-эндпоинтах.

Экран рубок ухода НЕ связан с деревом делянок (delyanka/delyanka_item) —
участок ищется напрямую в таксационной базе по кварталу/выделу через
get_vydel_card() (db.py), точно так же, как на экране "Таксация".
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any


# --- Список пород по умолчанию для выпадающего списка на фронтенде
# (десктопная версия допускала свободный ввод — сюда переносим тот же
# список как подсказку/значение по умолчанию, фронт не обязан им
# ограничиваться) ---
DEFAULT_PORODY = [
    "Сосна", "Ель", "Береза", "Осина", "Дуб",
    "Ольха черная", "Ольха серая", "Граб", "Клен", "Ясень", "Липа",
]

VIDY_RUBKI = ["Осветление", "Прочистка", "Прореживание", "Проходная рубка", "ССР", "Иное"]


# ======================================================================= #
#   РАСЧЁТ ПО СТРОКЕ УКЛАДКИ ХВОРОСТА
# ======================================================================= #
def _parse_float(value: Any) -> float | None:
    """Разбирает число из строки/числа так же терпимо, как десктопная
    версия (запятая как разделитель, пустая строка -> None)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def calculate_row(shirina: Any, vysota: Any, dlina: Any) -> dict | None:
    """Считает одну строку укладки хвороста по формулам эталонной
    ведомости:

      T (Объём складочный)   = Ширина * Высота * Длина
      U (Коэфф. перевода)    = 0.1,  если Длина < 2 м
                                0.12, если 2 <= Длина <= 4 м
                                0.2,  если Длина > 4 м
      V (Запас на укладке)   = T*U * 0.9,  если Длина > 2 м  (-10% на пустоты)
                                T*U * 0.8,  если Длина <= 2 м (-20% на пустоты)

    Возвращает None, если ширина/высота/длина не заданы (строка ещё не
    заполнена) — вызывающий код должен пропустить такую строку, как это
    делал calculate_osvetlenie() в десктопной версии."""
    shirina_v = _parse_float(shirina)
    vysota_v = _parse_float(vysota)
    dlina_v = _parse_float(dlina)

    if shirina_v is None or vysota_v is None or dlina_v is None:
        return None

    obyom_sklad = shirina_v * vysota_v * dlina_v

    if dlina_v < 2:
        koeff = 0.1
    elif dlina_v <= 4:
        koeff = 0.12
    else:
        koeff = 0.2

    raw = obyom_sklad * koeff
    zapas = raw * 0.9 if dlina_v > 2 else raw * 0.8

    return {
        "shirina": shirina_v,
        "vysota": vysota_v,
        "dlina": dlina_v,
        "obyom_sklad": round(obyom_sklad, 3),
        "koeff": round(koeff, 2),
        "zapas": round(zapas, 3),
    }


class UhodyValidationError(ValueError):
    """Ошибка входных данных расчёта — сообщение уже готово для показа
    пользователю (те же тексты, что и QMessageBox.warning в десктопной
    версии)."""


def calculate_proba(
    rows: list[dict],
    kol_prob: Any,
    ploshad_ploshadki: Any,
    ploshad_lesoseki: Any = None,
) -> dict:
    """Считает запас по пробе целиком — построчно (calculate_row) плюс
    экстраполяция на 1 га и, если задана площадь лесосеки, на всю
    лесосеку. Повторяет calculate_osvetlenie()/calculate_total_area() из
    core.py, но без UI: вместо QMessageBox поднимает UhodyValidationError
    с тем же текстом сообщения.

    rows — список словарей с ключами poroda/shirina/vysota/dlina (в любом
    порядке, лишние ключи игнорируются) — как правило, ровно то, что
    прислал фронтенд из таблицы обмера укладок.

    Возвращает словарь:
        {
            "rows": [ {..calculate_row.., "poroda": ..., "nomer": ...}, ... ],
            "obyom_sklad_total": float,
            "zapas_proby_total": float,
            "zapas_na_1ga": float,
            "zapas_na_lesoseke": float | None,
        }
    """
    kol_prob_v = _parse_float(kol_prob) or 0
    ploshad_ploshadki_v = _parse_float(ploshad_ploshadki) or 0
    s_prob = kol_prob_v * ploshad_ploshadki_v

    if s_prob <= 0:
        raise UhodyValidationError(
            "Общая площадь пробных площадок равна нулю — проверьте "
            "число площадок и площадь одной площадки."
        )

    computed_rows: list[dict] = []
    total_obyom_sklad = 0.0
    total_zapas = 0.0

    for idx, row in enumerate(rows or [], start=1):
        result = calculate_row(row.get("shirina"), row.get("vysota"), row.get("dlina"))
        if result is None:
            # Незаполненная строка — пропускаем, как и в десктопной версии
            # (там просто очищались расчётные столбцы этой строки).
            continue
        result["nomer"] = idx
        result["poroda"] = (row.get("poroda") or "").strip() or "—"
        computed_rows.append(result)
        total_obyom_sklad += result["obyom_sklad"]
        total_zapas += result["zapas"]

    if not computed_rows:
        raise UhodyValidationError(
            "Заполните хотя бы одну укладку (ширина/высота/длина), прежде чем считать запас."
        )

    zapas_na_1ga = total_zapas / s_prob

    zapas_na_lesoseke = None
    ploshad_lesoseki_v = _parse_float(ploshad_lesoseki)
    if ploshad_lesoseki_v is not None and ploshad_lesoseki_v > 0:
        zapas_na_lesoseke = zapas_na_1ga * ploshad_lesoseki_v

    return {
        "rows": computed_rows,
        "obyom_sklad_total": round(total_obyom_sklad, 3),
        "zapas_proby_total": round(total_zapas, 3),
        "zapas_na_1ga": round(zapas_na_1ga, 3),
        "zapas_na_lesoseke": round(zapas_na_lesoseke, 3) if zapas_na_lesoseke is not None else None,
    }


def calculate_total_area(zapas_na_1ga: Any, ploshad_lesoseki: Any) -> float:
    """Пересчёт уже посчитанного запаса "на 1 га" на всю площадь
    лесосеки — эквивалент calculate_total_area() в core.py (W * G5).
    Отдельная функция нужна для эндпоинта, который меняет только площадь
    лесосеки, не пересчитывая заново все укладки."""
    zapas_na_1ga_v = _parse_float(zapas_na_1ga) or 0.0
    ploshad_lesoseki_v = _parse_float(ploshad_lesoseki)

    if ploshad_lesoseki_v is None or ploshad_lesoseki_v <= 0:
        raise UhodyValidationError("Площадь лесосеки должна быть больше нуля.")
    if zapas_na_1ga_v <= 0:
        raise UhodyValidationError(
            "Сначала выполните расчёт запаса по пробе (кнопка "
            '"Рассчитать запас по пробе").'
        )

    return round(zapas_na_1ga_v * ploshad_lesoseki_v, 3)


# ======================================================================= #
#   СБОРКА / ВАЛИДАЦИЯ PAYLOAD ПРОБЫ (аналог _collect_row_data + save_proba)
# ======================================================================= #
def build_proba_payload(form: dict, calc_result: dict) -> dict:
    """Собирает JSON-payload пробы (то, что раньше уходило в
    uhody_proby.data_json) из данных формы (шапка ведомости + комиссия) и
    уже готового результата расчёта (см. calculate_proba). Формат 1:1
    повторяет payload из save_proba() в komissiya.py — фронтенд и
    экспортёры (Word/Excel) рассчитывают именно на эти ключи.

    form ожидает (все поля опциональны, отсутствующие -> "" / 0 / None):
        lesnichestvo, nomer_lesoseki, ploshad_lesoseki, kategoriya_lesov,
        vozrast, sostav, polnota, vid_polzovaniya, vid_rubki,
        sposob_rubki, god_rubki, metod, kol_ploshadok, ploshad_ploshadki,
        komissiya: {perechet1, perechet2, perechet3, doljnost, fio}
    """
    komissiya = form.get("komissiya") or {}
    return {
        "lesnichestvo": form.get("lesnichestvo") or "",
        "nomer_lesoseki": form.get("nomer_lesoseki") or "",
        "ploshad_lesoseki": form.get("ploshad_lesoseki"),
        "kategoriya_lesov": form.get("kategoriya_lesov") or "",
        "vozrast": form.get("vozrast"),
        "sostav": form.get("sostav") or "",
        "polnota": form.get("polnota"),
        "vid_polzovaniya": form.get("vid_polzovaniya") or "",
        "vid_rubki": form.get("vid_rubki") or "",
        "sposob_rubki": form.get("sposob_rubki") or "",
        "god_rubki": form.get("god_rubki"),
        "metod": form.get("metod") or "По пробным площадям (обмер укладок хвороста)",
        "kol_ploshadok": form.get("kol_ploshadok"),
        "ploshad_ploshadki": form.get("ploshad_ploshadki"),
        "rows": calc_result.get("rows", []),
        "obyom_sklad_total": calc_result.get("obyom_sklad_total", 0.0),
        "zapas_proby_total": calc_result.get("zapas_proby_total", 0.0),
        "zapas_na_1ga": calc_result.get("zapas_na_1ga", 0.0),
        "zapas_na_lesoseke": calc_result.get("zapas_na_lesoseke") or 0.0,
        "komissiya": {
            "perechet1": komissiya.get("perechet1") or "",
            "perechet2": komissiya.get("perechet2") or "",
            "perechet3": komissiya.get("perechet3") or "",
            "doljnost": komissiya.get("doljnost") or "",
            "fio": komissiya.get("fio") or "",
        },
    }


# ======================================================================= #
#   ЭКСПОРТ В EXCEL (.xlsx) — сверх плана Части 1, по просьбе пользователя
# ======================================================================= #
def build_osvetlenie_workbook(record: dict):
    """Собирает .xlsx максимально близко к эталонной бланк-форме
    "ВЕДОМОСТЬ ПЕРЕЧЕТА ДЕРЕВЬЕВ И ОБМЕРА ДРЕВЕСИНЫ НА ПРОБНЫХ ПЛОЩАДЯХ" —
    построчный перенос _build_osvetlenie_workbook() из
    screens/raskhod/osvetlenie/export_excel.py (десктопная версия), но
    вместо чтения значений из виджетов Qt берёт их из record — записи
    пробы в формате get_uhody_proba() (db.py): {id, kvartal, vydel,
    ploshad_vydela, data_zamera, data: {...}}.

    Возвращает объект openpyxl.Workbook — вызывающий код (роутер) сам
    решает, сохранить ли его на диск или сразу отдать как поток в ответе.
    """
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, Side

    data = record.get("data") or {}
    rows_data = data.get("rows") or []
    komissiya = data.get("komissiya") or {}

    FONT = Font(name="Times New Roman", size=11)
    FONT_BOLD = Font(name="Times New Roman", size=11, bold=True)
    FONT_TITLE = Font(name="Times New Roman", size=11, bold=True)
    CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
    CENTER_NOWRAP = Alignment(horizontal="center", vertical="center")
    LEFT_WRAP = Alignment(horizontal="left", vertical="top", wrap_text=True)
    THIN = Side(style="thin")
    BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    UNDERLINE = Border(bottom=THIN)

    wb = openpyxl.Workbook()
    ws = wb.active

    def box_range(cell_range: str) -> None:
        for row in ws[cell_range]:
            for cell in row:
                cell.border = BOX

    def underline(cell_range: str) -> None:
        target = ws[cell_range]
        if isinstance(target, tuple):
            for row in target:
                for cell in row:
                    cell.border = UNDERLINE
        else:
            target.border = UNDERLINE

    def label(coord: str, text, bold: bool = False, align=None) -> None:
        ws[coord] = text
        ws[coord].font = FONT_BOLD if bold else FONT
        if align is not None:
            ws[coord].alignment = align

    def value(coord: str, val, align=CENTER_NOWRAP) -> None:
        ws[coord] = val
        ws[coord].font = FONT
        ws[coord].alignment = align

    kvartal = str(record.get("kvartal") or "-")
    vydel = str(record.get("vydel") or "-")
    ws.title = f"кв {kvartal} в {vydel}"[:31]

    # --- Ширины столбцов и высоты строк (как в эталонном файле) ---
    col_widths = {
        "A": 8.71, "B": 7.29, "C": 6.43, "D": 6.57, "E": 6.14, "F": 5.86,
        "G": 5.71, "H": 6.57, "I": 6.14, "J": 6.71, "L": 7.43, "M": 7.14,
        "O": 8.86, "P": 7.71, "Q": 8.14, "R": 7.86, "S": 6.86,
        "U": 10.86, "V": 9.14, "W": 11.71, "X": 8.29,
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width
    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 27
    ws.row_dimensions[14].height = 45

    # --- Заголовок ведомости ---
    label("A1", "ВЕДОМОСТЬ ПЕРЕЧЕТА ДЕРЕВЬЕВ И ОБМЕРА ДРЕВЕСИНЫ НА ПРОБНЫХ ПЛОЩАДЯХ", bold=True, align=CENTER)
    ws.merge_cells("A1:N1")

    # --- Заголовок таблицы укладок (O:X) ---
    label("O1", "Порода", align=CENTER)
    ws.merge_cells("O1:O2")
    label("P1", "№ проба", align=CENTER)
    ws.merge_cells("P1:P2")
    label("Q1", "Размер укладки", align=CENTER)
    ws.merge_cells("Q1:T1")
    label("U1", "Объемный перевод. Коэф.", align=CENTER)
    ws.merge_cells("U1:U2")
    label("V1", "запас, м", align=CENTER)
    ws.merge_cells("V1:X1")
    for coord, text in (("Q2", "ширина, м"), ("R2", "высота, м"), ("S2", "длина, м"), ("T2", "Объем склад.,")):
        label(coord, text, align=CENTER)
    for coord, text in (("V2", "на пробе"), ("W2", "на 1 га"), ("X2", "на лесосеке")):
        label(coord, text, align=CENTER)
    box_range("O1:X2")

    label("O3", "ХВОРОСТ", bold=True, align=CENTER)
    ws.merge_cells("O3:X3")

    # --- Шапка с общими данными (та же раскладка ячеек, что в оригинале) ---
    label("A3", "Лесхоз")
    ws.merge_cells("B3:E3")
    underline("B3:E3")
    label("F3", "Лесничество")
    ws.merge_cells("F3:G3")
    value("H3", data.get("lesnichestvo") or "")
    ws.merge_cells("H3:N3")
    underline("H3:N3")

    label("A4", "№ лесного квартала")
    value("D4", kvartal if record.get("kvartal") else "", align=Alignment(horizontal="left"))
    underline("C4:F4")
    label("G4", "№ таксационного выдела")
    value("K4", vydel if record.get("vydel") else "")
    ws.merge_cells("K4:N4")
    underline("K4:N4")

    ws.merge_cells("A5:B5")
    label("A5", "№ лесосеки")
    value("C5", data.get("nomer_lesoseki") or "")
    ws.merge_cells("D5:F5")
    label("D5", "Площадь лесосеки", align=Alignment(horizontal="left"))
    value("G5", data.get("ploshad_lesoseki") or 0)
    underline("G5")
    ws.merge_cells("H5:J5")
    label("H5", "Категория лесов")
    ws.merge_cells("K5:N5")
    value("K5", data.get("kategoriya_lesov") or "")
    underline("K5:N5")

    label("A6", "Возраст")
    value("B6", data.get("vozrast") or 0)
    ws.merge_cells("C6:E6")
    label("C6", "Вид пользования")
    ws.merge_cells("F6:H6")
    value("F6", data.get("vid_polzovaniya") or "")
    ws.merge_cells("I6:L6")
    label("I6", "Состав лесного насаждения")
    ws.merge_cells("M6:N6")
    value("M6", data.get("sostav") or "")
    underline("M6:N6")

    label("B7", "Полнота")
    ws.merge_cells("C7:D7")
    value("C7", data.get("polnota") or 0)
    ws.merge_cells("E7:F7")
    label("E7", "Год рубки")
    ws.merge_cells("G7:H7")
    value("G7", data.get("god_rubki") or "")
    label("I7", "Вид рубки")
    ws.merge_cells("K7:N7")
    value("K7", data.get("vid_rubki") or "")

    ws.merge_cells("A8:B8")
    label("A8", "Способ рубки")
    ws.merge_cells("C8:F8")
    value("C8", data.get("sposob_rubki") or "")
    label("G8", "Дата")
    ws.merge_cells("H8:J8")
    data_zamera = record.get("data_zamera") or ""
    value("H8", data_zamera)

    ws.merge_cells("A9:F9")
    label("A9", "Метод определения объема древесины на корню")
    ws.merge_cells("G9:N9")
    value("G9", data.get("metod") or "")

    ws.merge_cells("A10:B10")
    label("A10", "Число площадок")
    ws.merge_cells("C10:D10")
    kol_ploshadok = data.get("kol_ploshadok") or 0
    value("C10", kol_ploshadok)
    ws.merge_cells("E10:G10")
    label("E10", "Площадь площадки", align=Alignment(horizontal="left"))
    ws.merge_cells("H10:I10")
    value("H10", data.get("ploshad_ploshadki") or 0)

    # --- Таблица укладок: фиксированные строки 4..23, итог всегда в
    # строке 24 (как в эталоне) — раздвигается только если укладок > 20. ---
    first_row = 4
    FIXED_LAST_ROW = 23
    last_data_row = first_row + len(rows_data) - 1 if rows_data else first_row - 1
    table_end_row = max(FIXED_LAST_ROW, last_data_row)

    for offset, row_data in enumerate(rows_data):
        r = first_row + offset
        value(f"O{r}", row_data.get("poroda") or "—", align=CENTER_NOWRAP)
        value(f"P{r}", row_data.get("nomer") or offset + 1)
        value(f"Q{r}", row_data.get("shirina"))
        value(f"R{r}", row_data.get("vysota"))
        value(f"S{r}", row_data.get("dlina"))
        value(f"T{r}", f"=Q{r}*R{r}*S{r}")
        value(f"U{r}", f'=IF(S{r}<2,0.1,IF(AND(S{r}>=2,S{r}<=4),0.12,IF(S{r}>4,0.2,0)))')
        value(f"V{r}", f"=IF(S{r}>2,T{r}*U{r}-(T{r}*U{r}*0.1),T{r}*U{r}-(T{r}*U{r}*0.2))")
        value(f"W{r}", f"=V{r}/$H$10")
        value(f"X{r}", f"=W{r}*$G$5")

    box_range(f"O4:X{table_end_row}")

    total_row = table_end_row + 1
    value(f"T{total_row}", f"=SUM(T{first_row}:T{table_end_row})")
    value(f"V{total_row}", f"=SUM(V{first_row}:V{table_end_row})")
    value(f"W{total_row}", f"=SUM(W{first_row}:W{table_end_row})")
    value(f"X{total_row}", f"=SUM(X{first_row}:X{table_end_row})")
    box_range(f"T{total_row}:X{total_row}")

    # --- Скелет таблицы "Ступень толщины / Число деревьев по породам /
    # Модельные деревья по породам" (A12:N31) — часть печатной формы,
    # присутствует в бланке "как есть", данными не заполняется (метод
    # расчёта на этом экране — обмер укладок хвороста, а не полный
    # перечёт по ступеням толщины). ---
    label("A12", "Ступень толщины", bold=True, align=CENTER)
    ws.merge_cells("A12:A14")
    label("B12", "№ проб", bold=True, align=CENTER)
    ws.merge_cells("B12:B14")
    label("C12", "Число деревьев по породам", bold=True, align=CENTER)
    ws.merge_cells("C12:H12")
    label("I12", "Модельные деревья по породам", bold=True, align=CENTER)
    ws.merge_cells("I12:N12")

    species_spans = [("C13", "D13", "Сосна"), ("E13", "F13", "Береза"), ("G13", "H13", "Осина"),
                      ("I13", "J13", "Сосна"), ("K13", "L13", "Береза"), ("M13", "N13", "Осина")]
    for start, end, text in species_spans:
        label(start, text, align=CENTER)
        ws.merge_cells(f"{start}:{end}")

    row14_labels = ["деловых", "дровяных"] * 6
    for col, text in zip("CDEFGHIJKLMN", row14_labels):
        label(f"{col}14", text, align=CENTER, bold=True)

    diameter_rows = [(15, 16, 8), (17, 18, 12), (19, 20, 16), (21, 23, 20),
                      (24, 25, 24), (26, 27, 28), (28, 29, 32), (30, 31, 36)]
    for start_row, end_row, diameter in diameter_rows:
        coord = f"A{start_row}"
        label(coord, diameter, align=CENTER_NOWRAP)
        ws[coord].font = Font(name="Times New Roman", size=14)
        if end_row > start_row:
            ws.merge_cells(f"A{start_row}:A{end_row}")

    box_range("A12:N31")

    # --- Футер: типовая оговорка об ответственности и строки подписей.
    # Если укладок больше 20 и итоговая строка "уехала" вниз, футер
    # сдвигается вместе с ней. ---
    footer_start = max(26, total_row + 2)
    disclaimer = (
        "С правилами закладки пробных площадей и определения количества "
        "заготовленной лесопродукции ознакомлены и предупреждены о том, "
        "что несут ответственность за содержание данных, не "
        "соответствующих действительности."
    )
    label(f"O{footer_start}", disclaimer, align=LEFT_WRAP)
    ws.merge_cells(f"O{footer_start}:X{footer_start + 1}")

    signatures_row = footer_start + 2
    label(f"O{signatures_row}", "Перечеты и обмеры произвели :", align=Alignment(horizontal="center"))
    label(f"T{signatures_row}", "Проверил лесничий", align=Alignment(horizontal="right"))
    underline(f"V{signatures_row}")

    date_row = signatures_row + 1
    label(f"O{date_row}", f"Дата \"{data_zamera}\" г." if data_zamera else "Дата \"__\" _______ г.")

    for i in range(3):
        r = date_row + 1 + i
        underline(f"O{r}:Q{r}")
        label(f"R{r}", "(ФИО)", align=CENTER_NOWRAP)

    last_content_row = max(31, date_row + 3)
    _apply_print_layout(ws, last_row=last_content_row, last_col="X")

    return wb


def _apply_print_layout(ws, last_row: int, last_col: str) -> None:
    """Настраивает параметры печати листа так, чтобы вся ведомость
    выводилась на ОДНУ страницу — перенесено 1:1 из
    export_excel.py._apply_print_layout (десктопная версия): fitToPage
    1x1 принудительно вписывает print_area в один лист, чтобы Excel не
    расставлял собственные разрывы страниц посреди таблиц."""
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.page_setup.fitToPage = True
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    ws.print_area = f"A1:{last_col}{last_row}"

    ws.row_breaks.brk = []
    ws.col_breaks.brk = []

    ws.page_margins.left = 0.3
    ws.page_margins.right = 0.3
    ws.page_margins.top = 0.3
    ws.page_margins.bottom = 0.3
    ws.page_margins.header = 0.0
    ws.page_margins.footer = 0.0

    ws.print_options.horizontalCentered = True
    ws.sheet_view.showGridLines = False


def build_osvetlenie_xlsx_filename(record: dict) -> str:
    """Имя файла выгрузки — тот же паттерн, что и default_name в
    export_to_excel() десктопной версии."""
    kvartal = str(record.get("kvartal") or "б_н")
    vydel = str(record.get("vydel") or "б_н")
    return f"Проба_рубки_ухода_кв{kvartal}_в{vydel}.xlsx"


# ======================================================================= #
#   ЭКСПОРТ В WORD (.docx) ПО ЭТАЛОННОМУ ШАБЛОНУ — Часть 2 плана
# ======================================================================= #
# Шаблон уже лежит в backend/legacy/templates/templates/
# proba_rubki_uhoda_template.docx (см. C3_plan_rubki_uhoda.md, раздел
# "Что уже готово в backend") — путь ниже собран относительно этого
# файла (backend/legacy/uhody.py), чтобы работать независимо от текущей
# рабочей директории процесса.
_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "templates", "templates", "proba_rubki_uhoda_template.docx",
)


def _set_cell_text(cell, text: str) -> None:
    """Записывает текст в ячейку таблицы docx, СОХРАНЯЯ форматирование
    (шрифт/размер/жирность) первого прогона первого абзаца — перенесено
    1:1 из _OsvetlenieExportWordMixin._set_cell_text (export_word.py,
    десктопная версия)."""
    paragraph = cell.paragraphs[0]
    if paragraph.runs:
        paragraph.runs[0].text = str(text)
        for extra_run in paragraph.runs[1:]:
            extra_run.text = ""
    else:
        paragraph.text = str(text)
    for extra_paragraph in cell.paragraphs[1:]:
        extra_paragraph.text = ""


def _set_paragraph_text(paragraph, text: str) -> None:
    """То же самое, что _set_cell_text, но для обычного (не табличного)
    абзаца — перенесено 1:1 из export_word.py."""
    if paragraph.runs:
        paragraph.runs[0].text = str(text)
        for extra_run in paragraph.runs[1:]:
            extra_run.text = ""
    else:
        paragraph.text = str(text)


def _fmt_num(value, decimals: int = 2, dot: bool = False) -> str:
    """Форматирует число как в эталонной ведомости: запятая — десятичный
    разделитель для физических величин, точка — только для коэффициента
    объёмного перевода. Перенесено 1:1 из export_word.py."""
    value_f = _parse_float(value) or 0.0
    text = f"{value_f:.{decimals}f}"
    return text if dot else text.replace(".", ",")


def build_osvetlenie_document(record: dict, template_path: str | None = None):
    """Открывает эталонный шаблон .docx и подставляет в него данные
    сохранённой пробы — перенос 1:1 логики
    _OsvetlenieExportWordMixin._build_osvetlenie_docx() (export_word.py,
    десктопная версия), но вместо чтения значений из виджетов Qt берёт
    их из record — записи пробы в формате db.get_uhody_proba(): {id,
    kvartal, vydel, ploshad_vydela, data_zamera, data: {...}}.

    template_path позволяет переопределить путь к шаблону (по умолчанию
    _TEMPLATE_PATH); полезно для тестов.

    Возвращает объект docx.Document — вызывающий код (роутер) сам решает,
    сохранить его на диск или отдать сразу как поток в ответе (как и
    build_osvetlenie_workbook() для Excel).

    Бросает FileNotFoundError, если шаблон не найден, и ValueError, если
    структура шаблона не совпадает с ожидаемой (не 6 таблиц) — роутер
    должен превращать оба исключения в понятный HTTP-ответ (404/500),
    как раньше это делали QMessageBox.critical в десктопной версии.
    """
    import copy
    from docx import Document

    path = template_path or _TEMPLATE_PATH
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Не найден эталонный файл шаблона: {path}. Положите "
            "proba_rubki_uhoda_template.docx в backend/legacy/templates/templates/."
        )

    document = Document(path)
    tables = document.tables
    paragraphs = document.paragraphs
    if len(tables) < 6:
        raise ValueError(
            "Шаблон повреждён или имеет другую структуру — ожидались "
            "6 таблиц (2 таблицы шапки, ступени толщины, укладки "
            "хвороста, \"Проверил\", ФИО перечетчиков)."
        )
    header_table_1 = tables[0]
    header_table_2 = tables[1]
    hvorost_table = tables[3]
    proveril_table = tables[4]
    perechet_table = tables[5]

    data = record.get("data") or {}
    komissiya = data.get("komissiya") or {}
    rows_data = data.get("rows") or []

    kvartal = str(record.get("kvartal") or "")
    vydel = str(record.get("vydel") or "")
    date_str = record.get("data_zamera") or ""

    # --- Шапка ведомости (2 таблицы) ---
    _set_cell_text(header_table_1.cell(0, 9), data.get("lesnichestvo") or "")
    _set_cell_text(header_table_1.cell(1, 5), kvartal)
    _set_cell_text(header_table_1.cell(1, 10), vydel)
    _set_cell_text(header_table_1.cell(2, 3), data.get("nomer_lesoseki") or "")
    _set_cell_text(header_table_1.cell(2, 7), _fmt_num(data.get("ploshad_lesoseki"), 2))
    _set_cell_text(header_table_1.cell(2, 10), data.get("kategoriya_lesov") or "")
    _set_cell_text(header_table_1.cell(3, 2), str(data.get("vozrast") or ""))
    _set_cell_text(header_table_1.cell(3, 6), data.get("vid_polzovaniya") or "")
    _set_cell_text(header_table_1.cell(3, 11), data.get("sostav") or "")

    _set_cell_text(header_table_2.cell(0, 1), _fmt_num(data.get("polnota"), 1))
    _set_cell_text(header_table_2.cell(0, 5), str(data.get("god_rubki") or ""))
    _set_cell_text(header_table_2.cell(0, 11), data.get("vid_rubki") or "")
    _set_cell_text(header_table_2.cell(1, 2), data.get("sposob_rubki") or "")
    _set_cell_text(header_table_2.cell(1, 9), date_str)
    _set_cell_text(header_table_2.cell(2, 6), data.get("metod") or "")
    _set_cell_text(header_table_2.cell(3, 3), str(data.get("kol_ploshadok") or ""))
    _set_cell_text(header_table_2.cell(3, 10), _fmt_num(data.get("ploshad_ploshadki"), 3))

    # --- Таблица укладок хвороста: фиксированная область строк
    # 3..(последняя строка таблицы), последняя строка отводится под
    # "Итого" — досоздаётся копированием, если укладок много (>17). ---
    FIRST_ROW = 3
    kol_ploshadok_v = _parse_float(data.get("kol_ploshadok")) or 0.0
    ploshad_ploshadki_v = _parse_float(data.get("ploshad_ploshadki")) or 0.0
    s_prob = kol_ploshadok_v * ploshad_ploshadki_v
    ploshad_lesoseki_v = _parse_float(data.get("ploshad_lesoseki")) or 0.0
    n_cols = len(hvorost_table.columns)

    last_row_index = len(hvorost_table.rows) - 1
    capacity = last_row_index - FIRST_ROW + 1
    needed = len(rows_data) + 1  # +1 строка "Итого"
    if needed > capacity:
        extra_needed = needed - capacity
        template_row_tr = hvorost_table.rows[last_row_index]._tr
        for _ in range(extra_needed):
            new_row_tr = copy.deepcopy(template_row_tr)
            hvorost_table._tbl.append(new_row_tr)
        last_row_index += extra_needed

    total_row = last_row_index
    for offset in range(total_row - FIRST_ROW):
        r = FIRST_ROW + offset
        if offset < len(rows_data):
            row_data = rows_data[offset]
            v_zapas = _parse_float(row_data.get("zapas")) or 0.0
            w_na_1ga = (v_zapas / s_prob) if s_prob > 0 else 0.0
            x_na_lesoseke = w_na_1ga * ploshad_lesoseki_v
            _set_cell_text(hvorost_table.cell(r, 0), row_data.get("poroda") or "")
            _set_cell_text(hvorost_table.cell(r, 1), str(row_data.get("nomer") or ""))
            _set_cell_text(hvorost_table.cell(r, 2), _fmt_num(row_data.get("shirina"), 2))
            _set_cell_text(hvorost_table.cell(r, 3), _fmt_num(row_data.get("vysota"), 2))
            _set_cell_text(hvorost_table.cell(r, 4), _fmt_num(row_data.get("dlina"), 2))
            _set_cell_text(hvorost_table.cell(r, 5), _fmt_num(row_data.get("obyom_sklad"), 2))
            _set_cell_text(hvorost_table.cell(r, 6), _fmt_num(row_data.get("koeff"), 2, dot=True))
            _set_cell_text(hvorost_table.cell(r, 7), _fmt_num(v_zapas, 3))
            _set_cell_text(hvorost_table.cell(r, 8), _fmt_num(w_na_1ga, 3))
            _set_cell_text(hvorost_table.cell(r, 9), _fmt_num(x_na_lesoseke, 3))
            if n_cols > 10:
                _set_cell_text(hvorost_table.cell(r, 10), "")
        else:
            # Строка-заготовка сверх фактических укладок — очищаем, чтобы
            # не оставить пример-заглушку из шаблона.
            for c in range(n_cols):
                _set_cell_text(hvorost_table.cell(r, c), "")

    total_obyom_sklad = sum(_parse_float(row.get("obyom_sklad")) or 0.0 for row in rows_data)
    total_zapas = sum(_parse_float(row.get("zapas")) or 0.0 for row in rows_data)
    total_w = (total_zapas / s_prob) if s_prob > 0 else 0.0
    total_x = total_w * ploshad_lesoseki_v
    _set_cell_text(hvorost_table.cell(total_row, 0), "Итого")
    for c in range(1, n_cols):
        if c not in (5, 7, 8, 9):
            _set_cell_text(hvorost_table.cell(total_row, c), "")
    _set_cell_text(hvorost_table.cell(total_row, 5), _fmt_num(total_obyom_sklad, 2))
    _set_cell_text(hvorost_table.cell(total_row, 7), _fmt_num(total_zapas, 3))
    _set_cell_text(hvorost_table.cell(total_row, 8), _fmt_num(total_w, 3))
    _set_cell_text(hvorost_table.cell(total_row, 9), _fmt_num(total_x, 3))

    # --- Блок "Проверил / Должность / Ф.И.О." + "Дата". Пустые поля
    # оставляют эталонные плейсхолдеры нетронутыми — документ остаётся
    # пригодным для заполнения от руки, если проверяющего не указали. ---
    doljnost = (komissiya.get("doljnost") or "").strip()
    if doljnost:
        _set_cell_text(proveril_table.cell(0, 1), doljnost)

    proveril_fio = (komissiya.get("fio") or "").strip()
    if proveril_fio:
        _set_cell_text(proveril_table.cell(0, 2), proveril_fio)

    _set_cell_text(proveril_table.cell(1, 0), f'Дата "{date_str}" г.')

    # --- ФИО перечетчиков + дата под "Перечеты и обмеры произвели" ---
    perechetchiki = [
        (komissiya.get("perechet1") or "").strip(),
        (komissiya.get("perechet2") or "").strip(),
        (komissiya.get("perechet3") or "").strip(),
    ]
    for offset, fio in enumerate(perechetchiki):
        if fio and offset < len(perechet_table.rows):
            _set_cell_text(perechet_table.cell(offset, 0), fio)

    for paragraph in paragraphs:
        if paragraph.text.strip().startswith('Дата "__"'):
            _set_paragraph_text(paragraph, f'Дата "{date_str}" г.')
            break

    return document


def build_osvetlenie_docx_filename(record: dict) -> str:
    """Имя файла выгрузки .docx — тот же паттерн, что и
    build_osvetlenie_xlsx_filename()."""
    kvartal = str(record.get("kvartal") or "б_н")
    vydel = str(record.get("vydel") or "б_н")
    return f"Проба_рубки_ухода_кв{kvartal}_в{vydel}.docx"
