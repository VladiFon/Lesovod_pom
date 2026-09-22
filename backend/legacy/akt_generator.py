# -*- coding: utf-8 -*-
"""
Генератор "Акта обследования расстроенных лесных насаждений" из данных
делянки (МДО + таксация + вручную введённые поля).

Логика выбора бланка: если категория леса содержит "Эксплуатационные" -
бланк AKT_EXPL_TEMPLATE, иначе (Защитные/Природоохранные/Рекреационные/
Биотопические и т.п.) - бланк AKT_ZASH_TEMPLATE.
"""
import re
import shutil
import calendar
from pathlib import Path

import openpyxl

AKT_EXPL_TEMPLATE = "akt_expl_shablon.xlsx"
AKT_ZASH_TEMPLATE = "akt_zash_shablon.xlsx"

MONTHS_RU = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

# ---------------------------------------------------------------------------
# Точные координаты полей в каждом из двух известных бланков.
# Если появятся новые варианты бланков - добавить сюда третий layout.
# ---------------------------------------------------------------------------
LAYOUTS = {
    "expl": {
        "date_cell": "H6",
        "lesnichestvo_lesxoz_cell": "A8",
        "predsedatel_sentence_cell": "A9",
        "chleny_sentence_cell": "A10",
        "table_data_start_row": 15,
        "causes_cell": "A16", "causes_extra_cell": "A17",
        "vrediteli_cell": "A18",
        "meropriyatiya_cell": "A19",
        "sroki_cell": "A21",
        "polnota_zhivyh_cell": "A22",
        "preduprezhdenie_cell": "A23",
        "krasnaya_kniga_cell": "A25",
        "predsedatel_main_row": 29,
        "chleny_start_row": 31,
        "chleny_count": 2,
    },
    "zash": {
        "date_cell": "H6",
        "lesnichestvo_lesxoz_cell": "A8",
        "predsedatel_sentence_cell": "A9",
        "chleny_sentence_cell": "A10",
        "table_data_start_row": 16,
        "causes_cell": "A17", "causes_extra_cell": "A18",
        "vrediteli_cell": "A19",
        "meropriyatiya_cell": "A20",
        "sroki_cell": "A22",
        "polnota_zhivyh_cell": "A23",
        "preduprezhdenie_cell": "A24",
        "krasnaya_kniga_cell": "A26",
        "predsedatel_main_row": 30,
        "chleny_start_row": 32,
        "chleny_count": 3,
    },
}

LABELS = {
    "causes": "Причины, вызвавшие ослабление(расстройство) древостоев, и их состояние на день обследования(проверки) ",
    "vrediteli": "Преобладающие виды вредителей, болезней лесов (при их наличии) ",
    "meropriyatiya": "Назначаемые мероприятия и их обоснование ",
    "sroki": "Сроки проведения сплошной санитарной рубки ",
    "polnota_zhivyh": (
        "Относительная полнота жизнеспособных деревьев (1-3 категорий состояния) "
        "(определяется глазомерно в случаях, когда пробные площади не закладываются) "
    ),
    "preduprezhdenie": (
        "Мероприятия, необходимые для предупреждения заражения или повреждения "
        "смежных лесных насаждений "
    ),
    "krasnaya_kniga": (
        "Мероприятия по сохранению произрастающих дикорастущих растений или "
        "обитающих диких животных, относящихся к видам, включенным в Красную "
        "книгу Республики Беларусь "
    ),
}


def choose_template(kategoriya_lesov):
    """Возвращает ('expl'|'zash', имя_файла_бланка) по категории лесов."""
    if kategoriya_lesov and "эксплуатацион" in kategoriya_lesov.lower():
        return "expl", AKT_EXPL_TEMPLATE
    return "zash", AKT_ZASH_TEMPLATE


def _fmt_date_words(date_str):
    """'16.07.2026' -> '16 июля 2026 г.' Если формат не распознан - возвращает как есть."""
    if not date_str:
        return ""
    parts = date_str.replace("/", ".").split(".")
    if len(parts) != 3:
        return date_str
    try:
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{day} {MONTHS_RU[month]} {year} г."
    except (ValueError, IndexError):
        return date_str


def _short_lesxoz(lesxoz):
    """'Государственное лесохозяйственное учреждение "Оршанский лесхоз"' -> 'Оршанский лесхоз'"""
    if not lesxoz:
        return ""
    m = re.search(r'"([^"]+)"', lesxoz)
    return m.group(1) if m else lesxoz


def _short_kategoriya(kategoriya_lesov):
    """Короткая форма категории для таблицы акта: 'эксп.' либо как есть (с заглавной буквы)."""
    if not kategoriya_lesov:
        return ""
    if "эксплуатацион" in kategoriya_lesov.lower():
        return "эксп."
    return kategoriya_lesov[0].upper() + kategoriya_lesov[1:]


def _fmt_tip_lesa(tip_lesa):
    if not tip_lesa:
        return ""
    t = tip_lesa.strip().lower()
    return t if t.endswith(".") else t + "."


def generate_akt(delyanka, items, templates_dir=".", output_path=None):
    """
    delyanka: dict с полями акта (см. db.py: get_delyanka_full):
        data_akta (ДД.ММ.ГГГГ), prichiny, vrediteli, meropriyatiya, sroki_rubki,
        polnota_zhivyh, preduprezhdenie, krasnaya_kniga_meropriyatiya,
        predsedatel_dolzhnost, predsedatel_fio,
        chleny (список [{"dolzhnost":..., "fio":...}, ...])
    items: список dict с полями по каждому выделу:
        kategoriya_lesov, kvartal, vydel, ploshad, zapas_na_ga, vyrubaemyy_zapas,
        krasnaya_kniga (по умолчанию "-"), proishozhdenie ("ест."/"искусств."),
        sostav, vozrast, polnota, tip_lesa, bonitet, lesnichestvo, lesxoz
    Возвращает путь к сгенерированному файлу.
    """
    if not items:
        raise ValueError("Нужен хотя бы один выдел (items пуст)")

    kategorii = {it.get("kategoriya_lesov", "") for it in items}
    layout_key, template_name = choose_template(items[0].get("kategoriya_lesov", ""))
    if len(kategorii) > 1:
        mixed_keys = {choose_template(k)[0] for k in kategorii}
        if len(mixed_keys) > 1:
            raise ValueError(
                "Выделы делянки относятся к разным группам категорий лесов "
                "(нужны разные бланки акта) - разбейте делянку на две."
            )

    layout = LAYOUTS[layout_key]
    template_path = Path(templates_dir) / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Не найден бланк {template_path}")

    if output_path is None:
        first = items[0]
        output_path = f"Акт_обследования_кв{first.get('kvartal')}_выд{first.get('vydel')}.xlsx"
    output_path = str(output_path)
    shutil.copy(template_path, output_path)

    wb = openpyxl.load_workbook(output_path)
    ws = wb.active

    n_extra_rows = len(items) - 1
    if n_extra_rows > 0:
        ws.insert_rows(layout["table_data_start_row"] + 1, amount=n_extra_rows)

    # --- шапка ---
    first_item = items[0]
    data_akta = delyanka.get("data_akta", "") or ""
    year_match = data_akta.split(".")[-1] if "." in data_akta else ""
    if year_match:
        ws["N4"] = f"{year_match} г."
    ws[layout["date_cell"]] = "от " + _fmt_date_words(data_akta)
    ws[layout["lesnichestvo_lesxoz_cell"]] = (
        f"В {first_item.get('lesnichestvo', '')} лесничестве ГЛХУ \"{_short_lesxoz(first_item.get('lesxoz', ''))}\""
    )
    ws[layout["predsedatel_sentence_cell"]] = (
        f"Комиссия в составе председателя: {delyanka.get('predsedatel_dolzhnost', '')} "
        f"{delyanka.get('predsedatel_fio', '')}"
    )
    chleny = delyanka.get("chleny", []) or []
    chleny_str = ", ".join(
        f"{c.get('dolzhnost', '')} {c.get('fio', '')}".strip() for c in chleny
    )
    ws[layout["chleny_sentence_cell"]] = f"и членов: {chleny_str}" if chleny_str else "и членов: "

    # --- таблица по выделам ---
    row = layout["table_data_start_row"]
    for idx, it in enumerate(items):
        prefix = "-" if len(items) == 1 else str(idx + 1)
        ws.cell(row=row, column=1, value=prefix)                                   # A - № п/п
        ws.cell(row=row, column=2, value=_short_kategoriya(it.get("kategoriya_lesov", "")))  # B
        ws.cell(row=row, column=3, value=it.get("kvartal", ""))                     # C
        ws.cell(row=row, column=4, value=it.get("vydel", ""))                       # D
        ws.cell(row=row, column=5, value=it.get("ploshad", ""))                     # E
        ws.cell(row=row, column=6, value=it.get("zapas_na_ga", ""))                 # F
        ws.cell(row=row, column=7, value=it.get("vyrubaemyy_zapas", ""))            # G
        ws.cell(row=row, column=8, value=it.get("krasnaya_kniga", "-") or "-")       # H
        ws.cell(row=row, column=12, value=it.get("proishozhdenie", "ест."))         # L
        ws.cell(row=row, column=13, value=it.get("sostav", ""))                     # M
        ws.cell(row=row, column=14, value=it.get("vozrast", ""))                    # N
        ws.cell(row=row, column=15, value=it.get("polnota", ""))                    # O
        ws.cell(row=row, column=16, value=_fmt_tip_lesa(it.get("tip_lesa", "")))    # P
        ws.cell(row=row, column=17, value=it.get("bonitet", ""))                    # Q
        row += 1

    offset = n_extra_rows  # всё, что ниже таблицы, сместилось вниз на столько строк

    def cell_below(addr):
        col = "".join(ch for ch in addr if ch.isalpha())
        r = int("".join(ch for ch in addr if ch.isdigit())) + offset
        return f"{col}{r}"

    ws[cell_below(layout["causes_cell"])] = LABELS["causes"] + (delyanka.get("prichiny", "") or "")
    ws[cell_below(layout["causes_extra_cell"])] = ""
    ws[cell_below(layout["vrediteli_cell"])] = LABELS["vrediteli"] + (delyanka.get("vrediteli", "") or "")
    ws[cell_below(layout["meropriyatiya_cell"])] = LABELS["meropriyatiya"] + (delyanka.get("meropriyatiya", "") or "")
    ws[cell_below(layout["sroki_cell"])] = LABELS["sroki"] + (delyanka.get("sroki_rubki", "") or "")
    ws[cell_below(layout["polnota_zhivyh_cell"])] = LABELS["polnota_zhivyh"] + str(delyanka.get("polnota_zhivyh", "") or "")
    ws[cell_below(layout["preduprezhdenie_cell"])] = LABELS["preduprezhdenie"] + (delyanka.get("preduprezhdenie", "") or "")
    ws[cell_below(layout["krasnaya_kniga_cell"])] = LABELS["krasnaya_kniga"] + (delyanka.get("krasnaya_kniga_meropriyatiya", "") or "нет")

    # --- подписи ---
    pred_row = layout["predsedatel_main_row"] + offset
    ws.cell(row=pred_row, column=6, value=delyanka.get("predsedatel_dolzhnost", ""))
    ws.cell(row=pred_row, column=14, value=delyanka.get("predsedatel_fio", ""))

    chleny_row = layout["chleny_start_row"] + offset
    max_slots = layout["chleny_count"]
    for idx in range(max_slots):
        r = chleny_row + idx * 2
        if idx < len(chleny):
            ws.cell(row=r, column=6, value=chleny[idx].get("dolzhnost", ""))
            ws.cell(row=r, column=14, value=chleny[idx].get("fio", ""))
        else:
            ws.cell(row=r, column=6, value="")
            ws.cell(row=r, column=14, value="")

    wb.save(output_path)
    return output_path


if __name__ == "__main__":
    # быстрый тест на реальных данных (квартал 139 / выдел 15)
    delyanka = {
        "data_akta": "16.07.2026",
        "prichiny": "неблагоприятные погодные условия и последующее повреждение деревьев стволовыми вредителями",
        "vrediteli": "короед-типограф",
        "meropriyatiya": "сплошная санитарная рубка в связи с утратой лесным насаждением биологической устойчивости",
        "sroki_rubki": "2026 год",
        "polnota_zhivyh": "0.5",
        "preduprezhdenie": "лесопатологический мониторинг",
        "krasnaya_kniga_meropriyatiya": "нет",
        "predsedatel_dolzhnost": "главный лесничий",
        "predsedatel_fio": "Р.В.Михайленко",
        "chleny": [
            {"dolzhnost": "лесничий Болбасовского лесничества", "fio": "И.Л. Сказецкий"},
        ],
    }
    items = [{
        "kategoriya_lesov": "Природоохранные леса",
        "kvartal": 139, "vydel": "15", "ploshad": "1.1",
        "zapas_na_ga": 350, "vyrubaemyy_zapas": 477.01,
        "proishozhdenie": "ест.", "sostav": "6Е4С+Б", "vozrast": "111",
        "polnota": "0.6", "tip_lesa": "кис.", "bonitet": "1",
        "lesnichestvo": "Болбасовское", "lesxoz": "Оршанский лесхоз",
    }]
    out = generate_akt(delyanka, items, templates_dir="/home/claude/akt")
    print("Сгенерирован:", out)
