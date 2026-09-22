# -*- coding: utf-8 -*-
"""
Генератор "Справки о количестве заготовленной древесины" (справка
лесозаготовителя) — экран "Акты освидетельствования".

По Лесному кодексу РБ (ст. 72) эта справка, подписанная руководителем
лесопользователя, — основа для заполнения таблицы "При освидетельствовании
установлено" в Акте освидетельствования лесосеки (см.
osvidetelstvovanie_generator.py).

Автозаполняемые поля (по просьбе пользователя — "будет брать данные с
нашего экрана Учёт Заготовки"):
  - лесхоз, лесничество, № лесорубочного билета/дата — из карточки делянки.
  - № квартала/выдела — из delyanka_item (если выделов несколько, все
    перечисляются через "; ").
  - площадь, пройденная рубкой — сумма delyanka_item.ploshad (из МДО).
  - таблица по породам/категориям крупности — ФАКТ из нарядов
    (raskhod_naryad/raskhod_pozitsiya), через
    screens.raskhod.balance.compute_sortiment_totals_multi(): колонка на
    каждую фактически встретившуюся породу + "Всего".

НЕ автозаполняются (нет источника данных в приложении — это то, что
физически видно только при осмотре/подсчёте на месте, значения передаются
вызывающим кодом как аргументы с разумными значениями по умолчанию,
редактируемыми в интерфейсе перед генерацией):
  - "ликвида из сучьев и кроны", "переработано дровяной", "получено
    деловых сортиментов" — по умолчанию 0.
  - площадь/объём недоруба — по умолчанию площадь 0, объём —
    max(0, лимит - факт) как разумная подсказка (если разрешённый объём
    ещё не выбран полностью), также редактируется.
  - ФИО руководителя — берётся из профиля лесничего
    (config.get_lesnichiy_data()), но передаётся явно как аргумент, чтобы
    вызывающий код мог поправить.
"""
import shutil
from pathlib import Path

from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# Полные названия пород — те же, что и в listok_generator.py (единый
# справочник кодов пород по всему приложению), чтобы в документе "Е" не
# осталось нерасшифрованной буквой, как в исходных МДО-данных.
PORODA_NAMES = {
    "Е": "Ель", "С": "Сосна", "Б": "Береза", "ОС": "Осина", "Д": "Дуб",
    "Г": "Граб", "Кл": "Клен", "Я": "Ясень", "Лп": "Липа", "Олч": "Ольха черная",
    "ОЛЧ": "Ольха черная", "Олс": "Ольха серая", "ОЛС": "Ольха серая",
    "Ив": "Ива", "ИВ": "Ива", "Ивд": "Ива древовидная", "ИВД": "Ива древовидная",
    "Лц": "Лиственница", "Кед": "Кедр", "Т": "Тополь", "Р": "Рябина",
    "Вяз": "Вяз", "Кло": "Клен остролистный",
}

FONT_NAME = "Times New Roman"
FONT_SIZE = Pt(11)


def _poroda_name(code):
    return PORODA_NAMES.get(code, code)


def _fmt(value):
    """0 -> '0', 12.0 -> '12', 12.5 -> '12.5' — без хвостовых нулей, но и
    без потери дробной части, если она есть (так печатают объёмы в
    остальных документах приложения, см. _fmt_m3 в balance.py)."""
    if value is None:
        return ""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _set_cell_borders(cell, sides=("top", "bottom", "left", "right"), sz=4):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for side in sides:
        tag = qn(f"w:{side}")
        el = borders.find(tag)
        if el is None:
            el = OxmlElement(f"w:{side}")
            borders.append(el)
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:color"), "000000")


def _cell_text(cell, text, bold=False, align=WD_ALIGN_PARAGRAPH.CENTER, size=FONT_SIZE):
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align
    run = paragraph.add_run(str(text) if text is not None else "")
    run.font.name = FONT_NAME
    run.font.size = size
    run.bold = bold
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def _add_paragraph(doc, text="", bold=False, size=FONT_SIZE, align=WD_ALIGN_PARAGRAPH.LEFT,
                    space_after=Pt(4)):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = space_after
    if text:
        run = p.add_run(text)
        run.font.name = FONT_NAME
        run.font.size = size
        run.bold = bold
    return p


def generate_spravka(
    delyanka: dict,
    items: list,
    sortiment_totals: dict,
    output_path,
    *,
    ploshad_proydennaya=None,
    nedorub_ploshad=0,
    nedorub_obyom=None,
    likvid_such_krony=0,
    pererabotano_drovyanoy=0,
    poluchemo_delovyh=0,
    rukovoditel_dolzhnost="Руководитель",
    rukovoditel_fio="",
):
    """Строит "Справку о количестве заготовленной древесины" и сохраняет в
    output_path.

    delyanka: dict с полями делянки (nazvanie, nomer_lesorubochnogo_bileta,
        data_lesorubochnogo_bileta).
    items: список ПОЛНЫХ словарей delyanka_item (для lesxoz/lesnichestvo/
        kvartal/vydel — берём из первого; при разных kvartal/vydel по
        выделам перечисляем все через "; ").
    sortiment_totals: результат
        screens.raskhod.balance.compute_sortiment_totals_multi(conn, items)
        — {порода: {"KR":ф,"SR":ф,"ML":ф,"DROVA":ф,"HVOROST":ф}}.
    ploshad_proydennaya: площадь, пройденная рубкой, га (обычно —
        compute_ploshad_proydennaya_rubkoy(items)); если не передано, 0.
    nedorub_ploshad/nedorub_obyom: площадь/объём недоруба — данные не из
        приложения, значения по умолчанию 0/None (None -> тоже 0).
    likvid_such_krony/pererabotano_drovyanoy/poluchemo_delovyh: строки
        без источника данных в приложении, по умолчанию 0.
    rukovoditel_dolzhnost/rukovoditel_fio: подпись внизу справки.
    """
    doc = Document()
    section = doc.sections[0]
    section.left_margin = Cm(2)
    section.right_margin = Cm(1)
    section.top_margin = Cm(1.5)
    section.bottom_margin = Cm(1.5)

    style = doc.styles["Normal"]
    style.font.name = FONT_NAME
    style.font.size = FONT_SIZE

    _add_paragraph(doc, "СПРАВКА", bold=True, size=Pt(14), align=WD_ALIGN_PARAGRAPH.CENTER,
                    space_after=Pt(0))
    _add_paragraph(doc, "о количестве заготовленной древесины", bold=True, size=Pt(13),
                    align=WD_ALIGN_PARAGRAPH.CENTER, space_after=Pt(12))

    first_item = items[0] if items else {}
    lesxoz = delyanka.get("lesxoz") or first_item.get("lesxoz") or ""
    lesnichestvo = delyanka.get("lesnichestvo") or first_item.get("lesnichestvo") or ""

    kv_vyd_parts = []
    for it in items:
        kv = it.get("kvartal") or "?"
        vd = it.get("vydel") or "?"
        label = f"кв.{kv}/выд.{vd}"
        if label not in kv_vyd_parts:
            kv_vyd_parts.append(label)
    kv_vyd_text = "; ".join(kv_vyd_parts) if kv_vyd_parts else "___"

    bilet_nomer = delyanka.get("nomer_lesorubochnogo_bileta") or "___"
    bilet_data = delyanka.get("data_lesorubochnogo_bileta") or "___"
    delyanka_nomer = delyanka.get("nazvanie") or "___"

    _add_paragraph(doc, f"Выдана {lesxoz}".strip(), space_after=Pt(6))
    _add_paragraph(doc, f"в том, что {lesnichestvo} лесничество".strip(), space_after=Pt(6))
    _add_paragraph(
        doc,
        f"по лесорубочному билету № {bilet_nomer} от {bilet_data} г., {kv_vyd_text}, "
        f"{lesnichestvo} лесничества, делянка № {delyanka_nomer} заготовлено:",
        space_after=Pt(12),
    )

    # --- динамическая таблица: строки-показатели x (Всего + по каждой породе) ---
    porody = sorted(sortiment_totals.keys())
    n_data_cols = 1 + len(porody)  # "Всего" + по одной колонке на породу
    n_cols = 2 + n_data_cols  # № п/п, Наименование, ...данные...

    def poroda_sum(sortiment_key):
        return {p: sortiment_totals[p].get(sortiment_key, 0.0) for p in porody}

    kr = poroda_sum("KR")
    sr = poroda_sum("SR")
    ml = poroda_sum("ML")
    drova = poroda_sum("DROVA")
    hvorost = poroda_sum("HVOROST")
    delovaya = {p: kr[p] + sr[p] + ml[p] for p in porody}
    itogo = {p: delovaya[p] + drova[p] + hvorost[p] for p in porody}

    def col_total(d):
        return sum(d.values())

    table = doc.add_table(rows=1, cols=n_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    header = table.rows[0].cells
    _cell_text(header[0], "№ п/п", bold=True)
    _cell_text(header[1], "Наименование", bold=True)
    _cell_text(header[2], "Всего", bold=True)
    for i, p in enumerate(porody):
        _cell_text(header[3 + i], _poroda_name(p), bold=True)
    for c in header:
        _set_cell_borders(c)

    def add_row(nomer, name, values_by_poroda, total_value=None, bold_name=False,
                blank_poroda_cols=False):
        row = table.add_row().cells
        _cell_text(row[0], nomer)
        _cell_text(row[1], name, align=WD_ALIGN_PARAGRAPH.LEFT, bold=bold_name)
        total = total_value if total_value is not None else col_total(values_by_poroda or {})
        _cell_text(row[2], _fmt(total))
        for i, p in enumerate(porody):
            if blank_poroda_cols:
                _cell_text(row[3 + i], "")
            else:
                _cell_text(row[3 + i], _fmt((values_by_poroda or {}).get(p, 0)))
        for c in row:
            _set_cell_borders(c)
        return row

    add_row("1", "Площадь, пройденная рубкой, га", None, total_value=ploshad_proydennaya or 0,
            blank_poroda_cols=True)
    add_row("2", "Древесины - всего, куб.м", None, total_value=col_total(itogo),
            blank_poroda_cols=True)
    add_row("", "В том числе деловой - всего", delovaya)
    add_row("", "в том числе:", {})
    add_row("", "крупной", kr)
    add_row("", "средней", sr)
    add_row("", "мелкой", ml)
    add_row("", "дровяной", drova)
    add_row("", "ликвида из сучьев и кроны", {p: 0 for p in porody}, total_value=likvid_such_krony)
    add_row("", "хвороста", hvorost)
    add_row("", "Итого", itogo)
    add_row("", "Кроме того, переработано дровяной древесины, куб.м", {p: 0 for p in porody},
            total_value=pererabotano_drovyanoy, blank_poroda_cols=True)
    add_row("", "получено деловых сортиментов и полуфабрикатов, куб.м", {p: 0 for p in porody},
            total_value=poluchemo_delovyh, blank_poroda_cols=True)
    add_row("3", "Площадь недоруба, га", None, total_value=nedorub_ploshad or 0,
            blank_poroda_cols=True)
    add_row("4", "Объём недоруба, куб.м", None, total_value=nedorub_obyom or 0,
            blank_poroda_cols=True)

    _add_paragraph(doc, "", space_after=Pt(12))
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run(f"{rukovoditel_dolzhnost}  ________________  {rukovoditel_fio}")
    run.font.name = FONT_NAME
    run.font.size = FONT_SIZE
    p2 = doc.add_paragraph()
    run2 = p2.add_run("                              (подпись)                       (фамилия, инициалы)")
    run2.font.name = FONT_NAME
    run2.font.size = Pt(9)
    run2.italic = True

    output_path = str(output_path)
    doc.save(output_path)
    return output_path
