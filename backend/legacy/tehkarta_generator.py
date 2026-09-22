# -*- coding: utf-8 -*-
"""
Генератор "Технологической карты на разработку лесосеки" + "Акта
готовности лесосеки к рубке" (это ОДИН файл .docx, акт готовности - его
вторая часть, как в реальном бланке лесхоза).

Заполняет РЕАЛЬНЫЙ бланк лесхоза (tehkarta_shablon.docx) - копирует его и
точечно дозаполняет только переменные поля (шапка, 1.1-1.3, таблица 1.4,
1.5 подрост, места складирования, программа заготовки, подписи,
абрис-схема, акт готовности), не трогая остальной текст/форматирование/
картинки бланка. Разделы 2-5.9, 5.11-5.12 в самом бланке уже содержат
стандартные формулировки этого лесхоза - их менять не нужно.

Актуальная версия бланка (август 2026) устроена иначе, чем предыдущая:
    - индексы параграфов сдвинуты почти везде -> все поиски по тексту
      (см. _find_paragraph), НЕ по фиксированным номерам параграфов;
    - таблица "Согласовано/Утверждаю" теперь 7 колонок (0-2 слева склеены,
      3 - пустой разделитель, 4-6 справа склеены), причём строка с
      должностью/ФИО (row 3) НЕ склеена - должность и ФИО каждой стороны
      лежат в отдельных ячейках (col 0/2 слева, col 4/6 справа);
    - в бланке больше нет пункта "5.10. Схема разработки лесосеки" -
      его нужно вставлять с нуля отдельным листом между 5.9 и 5.11
      (см. блок ниже) - абрис всегда идёт на отдельной странице;
    - "Комиссия в составе:" в акте готовности - теперь таблица 3x1
      (было: один параграф с именами через таб);
    - таблица программы заготовки (5.13) в самом бланке - 3 строки, но
      по умолчанию используется 4 (как раньше) - лишняя строка дописывается.
"""
import re
import shutil
from pathlib import Path

from docx.enum.text import WD_BREAK, WD_ALIGN_PARAGRAPH
from docx.table import Table
from docx.text.paragraph import Paragraph

TEHKARTA_TEMPLATE = "tehkarta_shablon.docx"

PORODA_FULL_NAMES = {
    "Е": "Ель", "С": "Сосна", "Б": "Береза", "ОС": "Осина", "Д": "Дуб",
    "Г": "Граб", "ОЛЧ": "Ольха черная", "ОЛС": "Ольха серая",
}

DEFAULT_PROGRAMMA_ZAGOTOVKI = [
    {"nazvanie": "Дрова", "akty": "СТБ 1510-2012", "poroda": "Ос,Е,Б,С,Д", "diametr": "3 и более", "dlina": "4,05"},
    {"nazvanie": "Лесомат.круглые", "akty": "СТБ 2316-2-2013,СТБ2316-1-2013, СТБ 2187-2011",
     "poroda": "Е,С,Б", "diametr": "До 13 см", "dlina": "4,1"},
    {"nazvanie": "Лесомат.круглые", "akty": "СТБ 2316-2-2013,СТБ2316-1-2013, СТБ 2187-2011",
     "poroda": "Е,Ос", "diametr": "14-25", "dlina": "6,1"},
    {"nazvanie": "Лесомат.круглые", "akty": "СТБ 2316-2-2013,СТБ2316-1-2013, СТБ 2187-2011",
     "poroda": "Е,Ос", "diametr": "26 и более", "dlina": "6,1"},
]


MONTHS_RU = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _fmt_day_month(date_str):
    """'16.07.2026' -> '16 июля'. Если не распознано - возвращает как есть."""
    if not date_str:
        return "____ ______________"
    parts = date_str.replace("/", ".").split(".")
    if len(parts) < 2:
        return date_str
    try:
        day, month = int(parts[0]), int(parts[1])
        return f"{day} {MONTHS_RU[month]}"
    except (ValueError, IndexError):
        return date_str


def _short_lesxoz(lesxoz):
    """'Государственное лесохозяйственное учреждение "Оршанский лесхоз"' -> 'Оршанский лесхоз'"""
    if not lesxoz:
        return ""
    m = re.search(r'"([^"]+)"', lesxoz)
    return m.group(1) if m else lesxoz


def _fmt_num(v):
    if v is None or v == "":
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _replace_in_paragraph(paragraph, old, new):
    """Заменяет подстроку old->new в тексте параграфа, сохраняя форматирование
    первого run'а (упрощение, но приемлемое для этих полей-бланков)."""
    full_text = paragraph.text
    if old not in full_text:
        return False
    new_text = full_text.replace(old, new)
    if paragraph.runs:
        paragraph.runs[0].text = new_text
        for r in paragraph.runs[1:]:
            r.text = ""
    else:
        paragraph.add_run(new_text)
    return True


def _set_paragraph_text(paragraph, new_text):
    if paragraph.runs:
        paragraph.runs[0].text = new_text
        for r in paragraph.runs[1:]:
            r.text = ""
    else:
        paragraph.add_run(new_text)


def _find_paragraph_idx(doc, contains, start=0):
    for i, p in enumerate(doc.paragraphs):
        if i >= start and contains in p.text:
            return i
    return None


def _find_paragraph(doc, contains, start=0):
    idx = _find_paragraph_idx(doc, contains, start=start)
    return doc.paragraphs[idx] if idx is not None else None


def _usable_page_width(doc):
    """Ширина области печати текущей секции (ширина страницы за вычетом
    левого/правого полей)."""
    section = doc.sections[0]
    return section.page_width - section.left_margin - section.right_margin


def _usable_page_height(doc):
    """Высота области печати текущей секции (высота страницы за вычетом
    верхнего/нижнего полей)."""
    section = doc.sections[0]
    return section.page_height - section.top_margin - section.bottom_margin


def _picture_size_fit(doc, image_path, reserve_height=0):
    """Считает (width, height) в EMU для вставки картинки так, чтобы она
    ГАРАНТИРОВАННО влезала в печатную область страницы по ОБЕИМ сторонам
    сразу, с учётом уже занятого места (reserve_height - например, под
    заголовок над картинкой).

    Раньше картинка абриса вставлялась только с width=ширина страницы,
    без учёта height - а т.к. печатная область (за вычетом полей) почти
    никогда не имеет ровно ту же пропорцию сторон, что и сама картинка
    (да ещё и заголовок над ней съедает часть высоты), после такого
    масштабирования по ширине картинка оказывалась ЧУТЬ выше, чем
    оставшееся место на странице - и целиком "съезжала" на следующую
    страницу, а за ней тянулся лишний почти пустой лист. Здесь масштаб
    считается по МЕНЬШЕЙ из двух возможных - по ширине и по высоте -
    так что картинка всегда помещается на одном листе целиком."""
    from PIL import Image

    with Image.open(image_path) as im:
        img_w_px, img_h_px = im.size

    max_w = _usable_page_width(doc)
    max_h = _usable_page_height(doc) - reserve_height

    scale = min(max_w / img_w_px, max_h / img_h_px)
    return int(img_w_px * scale), int(img_h_px * scale)


def _set_cell(cell, text):
    cell.text = str(text) if text is not None else ""


_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP_NS = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def _strip_floating_anchors(doc):
    """Убирает из документа "плавающие" (anchored, не inline) картинки -
    в реальном бланке лесхоза на месте пункта 5.10 обнаружился не пустой
    задел, а забытый пример реальной заполненной схемы (целая страница
    абриса с чужими координатами), приклеенный как floating-картинка поверх
    пустого параграфа - обычный текстовый поиск её не находит (p.text у
    такого параграфа пустой), поэтому чистим на уровне XML: снимаем любые
    w:drawing с дочерним wp:anchor по всему документу (в т.ч. внутри ячеек
    таблиц), не трогая обычные inline-картинки бланка (легенды, схемы 5.11
    и т.д. - у них wp:inline, а не wp:anchor)."""
    for drawing in doc.element.body.findall(f".//{_W_NS}drawing"):
        if drawing.find(f"{_WP_NS}anchor") is None:
            continue
        run = drawing.getparent()
        if run is None:
            continue
        run.remove(drawing)
        if not any(c.tag != f"{_W_NS}rPr" for c in run):
            parent = run.getparent()
            if parent is not None:
                parent.remove(run)


def _table_after_paragraph(doc, paragraph):
    """Возвращает первую таблицу (docx Table), которая идёт СРАЗУ после
    данного параграфа в реальном порядке документа (не через doc.tables[N],
    а через обход соседних XML-элементов) - устойчиво к тому, что где-то
    выше/ниже добавится ещё одна таблица и собьёт фиксированные индексы."""
    if paragraph is None:
        return None
    sibling = paragraph._element.getnext()
    while sibling is not None:
        tag = sibling.tag.rsplit("}", 1)[-1]
        if tag == "tbl":
            return Table(sibling, doc)
        sibling = sibling.getnext()
    return None


def generate_tehkarta(delyanka, item, output_path, templates_dir="."):
    """
    delyanka: dict с полями делянки (см. delyanka.py):
        nomer_lesoseki, nomer_lesorubochnogo_bileta, data_lesorubochnogo_bileta,
        data_tehkarty, god_tehkarty, predsedatel_dolzhnost/fio, chleny[...],
        sostavil_dolzhnost/fio, podrost_ploshad/tys_sht,
        gotovnost_komissiya[...], data_gotovnosti, master_lesa_fio, brigadir_fio,
        programma_zagotovki (опционально, иначе используется стандартная).
    item: delyanka_item dict (lesnichestvo, lesxoz, kvartal, vydel,
        poroda_volumes, poroda_order, abris_image_path).
    """
    from docx import Document

    template_path = Path(templates_dir) / TEHKARTA_TEMPLATE
    if not template_path.exists():
        raise FileNotFoundError(f"Не найден бланк {template_path}")

    output_path = str(output_path)
    shutil.copy(template_path, output_path)
    doc = Document(output_path)
    _strip_floating_anchors(doc)

    def g(key, default=""):
        return delyanka.get(key) or default

    lesnichestvo = item.get("lesnichestvo", "")
    lesxoz_short = _short_lesxoz(item.get("lesxoz", ""))
    god = g("god_tehkarty", "2026")

    # --- шапка "Согласовано / Утверждаю" ---
    # Таблица 7 колонок: 0-2 склеены (левая половина), 3 - разделитель,
    # 4-6 склеены (правая половина). Строка 3 (должность/ФИО) НЕ склеена -
    # должность и ФИО лежат в раздельных ячейках по обе стороны.
    header_table = doc.tables[0]
    _set_cell(header_table.cell(1, 0), f"«{lesxoz_short}»" if lesxoz_short else "«ЛЕСХОЗ»")
    _set_cell(header_table.cell(1, 4), f"{lesnichestvo} лесничество" if lesnichestvo else "")

    _set_cell(header_table.cell(3, 0), g("predsedatel_dolzhnost", "Главный лесничий"))
    _set_cell(header_table.cell(3, 2), g("predsedatel_fio", ""))

    # "Утвердил" — берётся из выделенных полей делянки (utverdil_dolzhnost/
    # utverdil_fio), а не из первого члена комиссии. Если поля ещё не
    # заполнены (старые делянки), сохраняем прежнее поведение как запасной
    # вариант.
    chleny = delyanka.get("chleny") or []
    utverdil_dolzhnost = g("utverdil_dolzhnost") or (
        chleny[0].get("dolzhnost", "Лесничий") if chleny else "Лесничий"
    )
    utverdil_fio = g("utverdil_fio") or (chleny[0].get("fio", "") if chleny else "")
    _set_cell(header_table.cell(3, 4), utverdil_dolzhnost)
    _set_cell(header_table.cell(3, 6), utverdil_fio)

    _set_cell(header_table.cell(5, 0), f'__ ________________ {god} г.')
    _set_cell(header_table.cell(5, 4), f'__ ________________ {god} г.')

    # --- заголовок / номера ---
    p_lesoseka = _find_paragraph(doc, "на разработку лесосеки №")
    _set_paragraph_text(
        p_lesoseka,
        f'на разработку лесосеки №\xa0{g("nomer_lesoseki", item.get("lesoseka_nomer", "___"))} '
        f'от {_fmt_day_month(g("data_tehkarty", ""))} {god} года',
    )
    p_bilet = _find_paragraph(doc, "к лесорубочному билету №")
    _set_paragraph_text(
        p_bilet,
        f'к лесорубочному билету №\xa0{g("nomer_lesorubochnogo_bileta", "___")} '
        f'от {_fmt_day_month(g("data_lesorubochnogo_bileta", ""))} {god} года',
    )

    # --- 1.1-1.3 ---
    _set_paragraph_text(_find_paragraph(doc, "1.1."), f'1.1.\xa0Лесничество {lesnichestvo}')
    _set_paragraph_text(_find_paragraph(doc, "1.2."), f'1.2.\xa0Лесной квартал {item.get("kvartal", "")}')
    _set_paragraph_text(_find_paragraph(doc, "1.3."), f'1.3.\xa0Таксационный выдел {item.get("vydel", "")}')

    # --- 1.4 таблица объёма по породам ---
    poroda_volumes = item.get("poroda_volumes") or {}
    poroda_order = [p for p in item.get("poroda_order", []) if p != "Итого по лесосеке"][:5]
    itogo = poroda_volumes.get("Итого по лесосеке", {})
    vol_table = doc.tables[1]
    for i, poroda in enumerate(poroda_order):
        _set_cell(vol_table.cell(1, 1 + i), PORODA_FULL_NAMES.get(poroda, poroda))
    rows_spec = [
        (2, "delovaya_itogo"), (3, "drovyanaya"), (4, "likvid_iz_krony"),
        (5, "nelikvid"), (6, "vsego"),
    ]
    for row_idx, key in rows_spec:
        for i, poroda in enumerate(poroda_order):
            val = poroda_volumes.get(poroda, {}).get(key)
            _set_cell(vol_table.cell(row_idx, 1 + i), _fmt_num(val))
        _set_cell(vol_table.cell(row_idx, 6), _fmt_num(itogo.get(key)))

    # --- 1.5 подрост ---
    podrost_pl = g("podrost_ploshad", "")
    podrost_sht = g("podrost_tys_sht", "")
    _set_paragraph_text(
        _find_paragraph(doc, "Условия сохранения подроста"),
        f'1.5.\xa0Условия сохранения подроста {podrost_pl}га; {podrost_sht} тыс.шт/га, '
        f'и живого напочвенного покрова',
    )

    # --- 5.7 места складирования ---
    p57 = _find_paragraph(doc, "Места складирования лесопродукции")
    if p57:
        _set_paragraph_text(
            p57,
            f'5.7.\xa0Места складирования лесопродукции верхний склад, лесосека_       '
            f'кв {item.get("kvartal", "")} в {item.get("vydel", "")}',
        )

    # --- 5.10 схема (абрис) ---
    # В текущей версии бланка (авг. 2026) пункта "5.10. Схема разработки
    # лесосеки" как текста нет, но само МЕСТО под него в вёрстке
    # зарезервировано: между параграфом 5.9 "(период)" и заголовком
    # "5.11. Схема разработки пасек лесосеки" в бланке уже стоят подряд
    # ДВА пустых параграфа с принудительным разрывом страницы
    # (<w:br w:type="page"/>, в p.text они не видны). Это и есть готовая
    # пустая страница-заглушка под ручную схему: первый разрыв закрывает
    # страницу с 5.1-5.9, второй сразу же открывает страницу с 5.11 -
    # между ними получается ровно один пустой лист.
    # Поэтому свои заголовок и картинку нужно вставлять МЕЖДУ этими двумя
    # разрывами (а не добавлять третий), иначе вместо одного отдельного
    # листа получится два лишних пустых.
    anchor_p = _find_paragraph(doc, "Схема разработки пасек лесосеки")

    def _is_page_break_only(p):
        if p is None or p.text.strip():
            return False
        return any(
            br.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type") == "page"
            for r in p.runs
            for br in r._element.findall(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br"
            )
        )

    def _prev_paragraph(p):
        el = p._element.getprevious() if p is not None else None
        while el is not None:
            if el.tag.rsplit("}", 1)[-1] == "p":
                return Paragraph(el, doc)
            el = el.getprevious()
        return None

    break2 = _prev_paragraph(anchor_p)  # разрыв прямо перед 5.11
    break1 = _prev_paragraph(break2)    # разрыв прямо перед пустым листом
    has_reserved_page = _is_page_break_only(break1) and _is_page_break_only(break2)

    abris_image_path = item.get("abris_image_path")
    if anchor_p is not None and abris_image_path and Path(abris_image_path).exists():
        insert_before = break2 if has_reserved_page else anchor_p

        def _new_paragraph_before():
            return insert_before.insert_paragraph_before()

        if not has_reserved_page:
            # Заглушки в бланке не нашлось (бланк снова поменялся) -
            # подстраховываемся и делаем разрыв сами, как раньше.
            _new_paragraph_before().add_run().add_break(WD_BREAK.PAGE)

        heading_p = _new_paragraph_before()
        heading_p.add_run("5.10. Схема разработки лесосеки")

        img_p = _new_paragraph_before()
        img_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = img_p.add_run()
        try:
            # Учитываем ширину И высоту одновременно (см. _picture_size_fit)
            # - иначе абрис может оказаться чуть выше остатка страницы и
            # съехать на лишний лист. Резервируем немного места сверху под
            # заголовок "5.10. Схема разработки лесосеки".
            from docx.shared import Cm
            w, h = _picture_size_fit(doc, abris_image_path, reserve_height=Cm(1.2))
            run.add_picture(abris_image_path, width=w, height=h)
        except Exception:
            img_p.text = "[не удалось вставить изображение схемы]"

        if not has_reserved_page:
            _new_paragraph_before().add_run().add_break(WD_BREAK.PAGE)

    # --- 5.12 очередность разработки пасек: оставляем бланк (заполняется от руки) ---

    # --- 5.13 программа заготовки лесоматериалов ---
    programma = delyanka.get("programma_zagotovki") or DEFAULT_PROGRAMMA_ZAGOTOVKI
    # Таблица идёт сразу после параграфа "5.13. Программа заготовки
    # лесоматериалов" - ищем её через соседний XML-элемент, а не по
    # фиксированному индексу doc.tables[N]: так остаётся устойчивым, даже
    # если раздел 5.10 (см. выше) добавит/уберёт таблицы где-то раньше.
    p_513 = _find_paragraph(doc, "5.13. Программа заготовки лесоматериалов")
    prog_table = _table_after_paragraph(doc, p_513) or doc.tables[-1]
    for i, row in enumerate(programma):
        r = i + 1
        if r >= len(prog_table.rows):
            prog_table.add_row()
        _set_cell(prog_table.cell(r, 0), row.get("nazvanie", ""))
        _set_cell(prog_table.cell(r, 1), row.get("akty", ""))
        _set_cell(prog_table.cell(r, 2), row.get("poroda", ""))
        _set_cell(prog_table.cell(r, 3), row.get("diametr", ""))
        _set_cell(prog_table.cell(r, 4), row.get("dlina", ""))

    # --- составил ---
    p_sost = _find_paragraph(doc, "Технологическую карту составил")
    if p_sost:
        _set_paragraph_text(
            p_sost,
            f'Технологическую карту составил: {g("sostavil_dolzhnost", "")} {g("sostavil_fio", "")}',
        )

    # --- Акт готовности лесосеки (вторая часть того же файла) ---
    # "Комиссия в составе:" в актуальном бланке - таблица 3x1 (по одной
    # строке на члена комиссии), а не параграф с именами через таб.
    gotov_komissiya = delyanka.get("gotovnost_komissiya") or []
    p_komissiya = _find_paragraph(doc, "Комиссия в составе:")
    komissiya_table = _table_after_paragraph(doc, p_komissiya)
    if komissiya_table is not None:
        for i, c in enumerate(gotov_komissiya[: len(komissiya_table.rows)]):
            _set_cell(
                komissiya_table.cell(i, 0),
                f'{c.get("dolzhnost", "")} {c.get("fio", "")}'.strip(),
            )

    akt_start = _find_paragraph_idx(doc, "Комиссия в составе:") or 0

    p_podgotovlena = _find_paragraph(doc, "данная лесосека к разработке", start=akt_start)
    if p_podgotovlena:
        full_text = p_podgotovlena.text
        full_text = full_text.replace("________", _fmt_day_month(g("data_gotovnosti", "")))
        full_text = full_text.replace("2025", god)
        _set_paragraph_text(p_podgotovlena, full_text)

    for i, c in enumerate(gotov_komissiya[:3]):
        p_sign = _find_paragraph(doc, f"{i + 1}.___", start=akt_start)
        if p_sign:
            _set_paragraph_text(
                p_sign,
                f'{i + 1}. {c.get("fio", "")}' + " " * 20 + "(Ф.И.О., подпись, дата)",
            )

    p_master = _find_paragraph(doc, "Мастер леса", start=akt_start)
    if p_master and delyanka.get("master_lesa_fio"):
        _replace_in_paragraph(
            p_master, "_________________________ (",
            f'{delyanka["master_lesa_fio"]} (',
        )
    p_brigadir = _find_paragraph(doc, "Бригадир:", start=akt_start)
    if p_brigadir and delyanka.get("brigadir_fio"):
        _replace_in_paragraph(
            p_brigadir, "_________________________ _ (",
            f'{delyanka["brigadir_fio"]} (',
        )

    doc.save(output_path)
    return output_path


def generate_akt_gotovnosti(delyanka, output_path):
    """Оставлено для обратной совместимости со старым вызовом из
    delyanka.py - акт готовности теперь входит в тот же файл, что и
    техкарта (см. generate_tehkarta), отдельно больше не генерируется."""
    return None