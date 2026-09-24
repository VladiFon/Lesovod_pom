# -*- coding: utf-8 -*-
"""
Заполнение "Акта освидетельствования лесосеки" на основе РЕАЛЬНОГО бланка
пользователя (табличная вёрстка, рамки-подчёркивания на уровне ячеек) —
вместо построения документа с нуля.

Механика: берём файл-образец (TEMPLATE_PATH), в каждой генерации меняем
текст только в конкретных ячейках (по координатам row/col), всё остальное
(жирные подписи, рамки, объединения ячеек) остаётся как в оригинале.

Если текст не помещается в ячейку в одну строку — кегль автоматически
уменьшается (а не переносится на 2 строки), чтобы не было "рваных" ячеек.
"""
import copy
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

FONT = "Times New Roman"
BASE_SIZE = 11          # кегль данных по умолчанию (как в бланке)
MIN_SIZE = 7             # не сжимать мельче этого
# Примерная ширина символа в "единицах кегля" для Times New Roman (эмпирически)
CHAR_WIDTH_EM = 0.50


def _cell_width_cm(cell):
    try:
        return cell.width.cm
    except Exception:
        return 3.0


def set_cell_text(table, row, col, text, bold=False,
                   align=WD_ALIGN_PARAGRAPH.CENTER, base_size=BASE_SIZE):
    """Заменяет содержимое ячейки на ОДНУ строку текста, автоматически
    уменьшая кегль, если строка не помещается по ширине ячейки — чтобы
    никогда не было переноса на вторую строку внутри ячейки бланка."""
    cell = table.rows[row].cells[col]
    # оставляем один параграф
    for p in cell.paragraphs[1:]:
        p._element.getparent().remove(p._element)
    para = cell.paragraphs[0]
    for r in list(para.runs):
        r._element.getparent().remove(r._element)
    para.alignment = align

    text = "" if text is None else str(text)
    if text:
        width_cm = _cell_width_cm(cell)
        # доступная ширина с небольшим запасом на внутренние отступы ячейки
        usable_cm = max(width_cm - 0.15, 0.3)
        size = base_size
        while size > MIN_SIZE:
            # ширина строки (см) ~ кол-во символов * кегль(pt->cm) * коэфф.
            approx_width_cm = len(text) * (size * CHAR_WIDTH_EM) * (2.54 / 72)
            if approx_width_cm <= usable_cm:
                break
            size -= 0.5
        run = para.add_run(text)
        run.font.name = FONT
        run.font.size = Pt(size)
        run.bold = bold
    return cell


def fill_akt(template_path, data, output_path):
    doc = Document(template_path)
    t0 = doc.tables[0]
    t1 = doc.tables[1]
    d = data

    # --- дата акта (день / месяц словом / год) — короткая строка справа
    # от заголовка ---
    set_cell_text(t0, 2, 24, d.get("act_day", ""))
    set_cell_text(t0, 2, 26, d.get("act_month", ""))
    set_cell_text(t0, 2, 29, (d.get("act_year", "") + " г.") if d.get("act_year") else "",
                  align=WD_ALIGN_PARAGRAPH.LEFT)

    # --- область/район (в данных приложения это одно поле свободного
    # текста — целиком идёт в первую линию, "область"), лесхоз/лесничество
    # (структурное подразделение) ---
    set_cell_text(t0, 3, 2, d.get("oblast_rayon", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t0, 4, 0, d.get("lesxoz", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t0, 6, 0, d.get("lesnichestvo", ""), align=WD_ALIGN_PARAGRAPH.LEFT)

    # --- "Мы, нижеподписавшиеся" — представитель лесхоза (руководитель
    # освидетельствования) ---
    set_cell_text(t0, 8, 7, d.get("predstavitel_lesxoza", ""), align=WD_ALIGN_PARAGRAPH.LEFT)

    # --- в присутствии представителя лесопользователя ---
    set_cell_text(t0, 14, 9, d.get("predstavitel_lesopolz_organizatsiya", ""),
                  align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t0, 16, 0, d.get("predstavitel_lesopolz_dolzhnost_fio", ""),
                  align=WD_ALIGN_PARAGRAPH.LEFT)

    # --- основание / извещение ---
    set_cell_text(t0, 21, 11, d.get("osnovanie_nomer", ""))
    set_cell_text(t0, 21, 18, f"«{d.get('osnovanie_day','')}»" if d.get("osnovanie_day") else "")
    set_cell_text(t0, 21, 22, d.get("osnovanie_month", ""))
    set_cell_text(t0, 21, 27, (d.get("osnovanie_year", "") + " г.") if d.get("osnovanie_year") else "")
    set_cell_text(t0, 22, 18, f"«{d.get('izveshchenie_day','')}»" if d.get("izveshchenie_day") else "")
    set_cell_text(t0, 22, 22, d.get("izveshchenie_month", ""))
    set_cell_text(t0, 22, 27, (d.get("izveshchenie_year", "") + " г.") if d.get("izveshchenie_year") else "")

    # --- уполномоченные представители лесхоза (до 3 строк; председатель —
    # это predstavitel_lesxoza выше, "руководитель освидетельствования") ---
    chleny = d.get("chleny") or []
    for row, idx in ((27, 0), (29, 1), (31, 2)):
        if idx < len(chleny):
            set_cell_text(t0, row, 1, chleny[idx], align=WD_ALIGN_PARAGRAPH.LEFT)

    # --- вид лесосеки (ГП/ССР/ВСР) — слово "лесосеки" уже напечатано в бланке ---
    set_cell_text(t0, 34, 21, d.get("vid_lesoseki", ""))

    # --- квартал / выдел / билет / кому выдан ---
    set_cell_text(t0, 36, 5, d.get("kvartal", ""))
    set_cell_text(t0, 36, 23, d.get("vydel", ""))
    set_cell_text(t0, 37, 3, d.get("bilet_nomer", ""))
    set_cell_text(t0, 37, 15, d.get("predstavitel_lesopolz_organizatsiya", ""),
                  align=WD_ALIGN_PARAGRAPH.LEFT)

    # --- способы (в бланке уже напечатаны значения по умолчанию —
    # перезаписываем, если в данных указано другое) ---
    set_cell_text(t0, 40, 7, d.get("sposob_rubki", "сплошной"))
    set_cell_text(t0, 40, 21, d.get("sposob_ucheta", "по площади"))
    set_cell_text(t0, 41, 4, d.get("sposob_ochistki",
                  "измельчение и разбрасывание порубочных остатков на лесосеке"),
                  align=WD_ALIGN_PARAGRAPH.LEFT)

    # --- сроки окончания заготовки/вывозки — в бланке нет линии для
    # заполнения (только надпись), поэтому не печатаем поверх неё ---

    # --- таблица объёмов ---
    st = d.get("sortiment_totals") or {}
    def sv(key, field):
        return (st.get(key) or {}).get(field, "")
    set_cell_text(t0, 45, 13, d.get("ploshad_razresheno", ""))
    set_cell_text(t0, 45, 20, d.get("ploshad_fakt", ""))
    set_cell_text(t0, 46, 13, d.get("obyom_vsego_limit", ""))
    set_cell_text(t0, 46, 20, d.get("obyom_vsego_fakt", ""))
    for row, key in ((48, "KR"), (49, "SR"), (50, "ML"), (51, "DROVA")):
        set_cell_text(t0, row, 13, sv(key, "limit"))
        set_cell_text(t0, row, 20, sv(key, "fakt"))
    set_cell_text(t0, 52, 13, sv("HVOROST", "limit"))
    set_cell_text(t0, 52, 20, sv("HVOROST", "fakt"))

    set_cell_text(t0, 55, 13, d.get("podrost_ploshad_ga", ""))
    set_cell_text(t0, 55, 20, d.get("podrost_ploshad_protsent", ""))
    set_cell_text(t0, 56, 13, d.get("podrost_kolichestvo_tys", ""))
    set_cell_text(t0, 56, 20, d.get("podrost_kolichestvo_protsent", ""))

    # ===================== страница 2 =====================
    narusheniya = d.get("narusheniya") or []
    for i in range(5):
        if i < len(narusheniya):
            set_cell_text(t1, 2 + i, 2, narusheniya[i].get("vid", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
            set_cell_text(t1, 2 + i, 14, narusheniya[i].get("kolichestvo", ""))

    set_cell_text(t1, 8, 9, d.get("harakteristika_podrosta", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t1, 12, 4, d.get("kachestvo_rubok", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t1, 17, 8, d.get("zayavleniya_lesopolzovatelya", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t1, 21, 11, d.get("zayavleniya_drugih", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t1, 28, 1, d.get("prilozhenie_4", ""), align=WD_ALIGN_PARAGRAPH.LEFT)

    set_cell_text(t1, 30, 7, d.get("predsedatel_dolzhnost", ""))
    set_cell_text(t1, 30, 13, d.get("predsedatel_fio", ""))
    chleny_low = d.get("chleny_podpisi") or chleny
    slots = [(32, 7, 13), (34, 0, 6)]
    for i, (row, dcol, fcol) in enumerate(slots):
        if i < len(chleny_low):
            # ожидаем строку "должность; ФИО" либо просто текст
            val = chleny_low[i]
            if isinstance(val, dict):
                set_cell_text(t1, row, dcol, val.get("dolzhnost", ""))
                set_cell_text(t1, row, fcol, val.get("fio", ""))
    set_cell_text(t1, 36, 7, d.get("predstavitel_lesopolzovaniya_dolzhnost", ""))
    set_cell_text(t1, 36, 13, d.get("predstavitel_lesopolzovaniya_fio", ""))

    set_cell_text(t1, 45, 5, "")  # подпись (пусто)
    set_cell_text(t1, 45, 12, d.get("rukovoditel_fio", ""))

    output_path = str(output_path)
    doc.save(output_path)
    return output_path
