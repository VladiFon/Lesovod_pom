# -*- coding: utf-8 -*-
"""Генератор "Паспорта насаждения искусственного происхождения"
(приложение 8 к постановлению Минлесхоза от 19.12.2016 N 80) —
заполняет templates/pasport_nasazhdeniya_shablon.docx данными участка и
всего журнала мероприятий (см. pasport_template_fill.py)."""
import os

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from akt_template_fill import set_cell_text
import pasport_template_fill as fill

_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "templates", "pasport_nasazhdeniya_shablon.docx",
)


def generate_pasport(uchastok, meropriyatiya, output_path, **manual_fields):
    """uchastok — dict из db.get_lesokultury_uchastok(); meropriyatiya —
    полный список из db.list_lesokultury_meropriyatiya() (любой порядок,
    сортировка по датам делается внутри pasport_template_fill).

    manual_fields (без источника данных в базе, все необязательны):
        yuridicheskoe_litso, relyef, pochva, pokrov,
        nalichie_estestvennogo_vozobnovleniya, vremya_sposob_obrabotki_pochvy,
        shema_smesheniya, harakteristika_materiala."""
    template_path = manual_fields.pop("template_path", None) or _TEMPLATE_PATH
    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"Не найден шаблон паспорта: {template_path}")

    doc = Document(template_path)
    tables = doc.tables
    if len(tables) < 5:
        raise ValueError("Шаблон паспорта повреждён — ожидались 5 таблиц")
    t_header, t_uhody, t_prizhivaemost, t_dopolnenie, t_perevod = tables[:5]

    # --- Таблица 0: шапка ---
    set_cell_text(t_header, 0, 1, manual_fields.get("yuridicheskoe_litso", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t_header, 1, 1, uchastok.get("lesnichestvo") or "", align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t_header, 2, 1, uchastok.get("god_sozdaniya") or "")
    set_cell_text(t_header, 2, 3, uchastok.get("kategoriya_ploshadi") or "")
    set_cell_text(t_header, 3, 1, uchastok.get("kvartal") or "")
    set_cell_text(t_header, 3, 3, uchastok.get("vydel") or "")
    set_cell_text(t_header, 4, 1, uchastok.get("ploshad") or "")
    set_cell_text(t_header, 4, 3, uchastok.get("tlu") or "")
    set_cell_text(t_header, 5, 1, uchastok.get("tip_lesa") or "", align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t_header, 5, 3, manual_fields.get("relyef", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t_header, 6, 1, manual_fields.get("pochva", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t_header, 6, 3, manual_fields.get("pokrov", ""), align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t_header, 7, 1, uchastok.get("metod_sozdaniya") or "", align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t_header, 7, 3, uchastok.get("glavnaya_poroda") or "", align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t_header, 8, 1, uchastok.get("sostav_formula") or "", align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(t_header, 8, 3, uchastok.get("gustota_posadki") or "")

    # --- Таблицы 1-4: журнал по типам ---
    fill.fill_uhody_table(t_uhody, meropriyatiya)
    fill.fill_prizhivaemost_table(t_prizhivaemost, meropriyatiya)
    fill.fill_dopolnenie_table(t_dopolnenie, meropriyatiya)
    fill.fill_perevod_spisanie_table(t_perevod, meropriyatiya, uchastok.get("ploshad"))

    output_path = str(output_path)
    doc.save(output_path)
    return output_path
