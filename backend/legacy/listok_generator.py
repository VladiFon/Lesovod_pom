# -*- coding: utf-8 -*-
"""
Генератор "Листка сигнализации о выявлении неблагополучного состояния
лесного фонда и намечаемых мероприятиях".

Автозаполняемые поля (по просьбе пользователя):
  - ГПЛХО, юрлицо (лесхоз), лесничество - берутся из данных делянки,
    обычно не меняются от делянки к делянке.
  - № квартала/выдела, площадь, поврежденная порода, возраст - из МДО
    (то же, что уже хранится в delyanka_item).
  - Характер повреждения - стандартная формулировка по умолчанию
    (аналогично типовым полям акта), можно поправить в интерфейсе.

Остальные поля бланка (кто обнаружил, кто проверил, намечаемое
мероприятие, решение, заключение специалистов) в бланке остаются
пустыми - заполняются от руки после печати, т.к. таких данных нет
ни в МДО, ни в таксации.

Если делянка включает несколько выделов - генерируется отдельный
листок на каждый (в документе один блок "место обнаружения" под один
выдел).
"""
import shutil
from pathlib import Path

import openpyxl

LISTOK_TEMPLATE = "listok_shablon.xlsx"

DEFAULT_GPLHO = "Витебское"
DEFAULT_HARAKTER_POVREZHDENIYA = "ед. усыхающие, ед. ветровально-буреломные"

# код породы (как в формуле состава) -> полное название для листка сигнализации
PORODA_NAMES = {
    "Е": "Ель", "С": "Сосна", "Б": "Береза", "ОС": "Осина", "Д": "Дуб",
    "Г": "Граб", "Кл": "Клен", "Я": "Ясень", "Лп": "Липа", "Олч": "Ольха черная",
    "ОЛЧ": "Ольха черная", "Олс": "Ольха серая", "ОЛС": "Ольха серая",
    "Ив": "Ива", "ИВ": "Ива", "Ивд": "Ива древовидная", "ИВД": "Ива древовидная",
    "Лц": "Лиственница", "Кед": "Кедр", "Т": "Тополь", "Р": "Рябина",
    "Вяз": "Вяз", "Кло": "Клен остролистный",
}


def _short_lesxoz(lesxoz):
    import re
    if not lesxoz:
        return ""
    m = re.search(r'"([^"]+)"', lesxoz)
    return m.group(1) if m else lesxoz


def _sostav_to_poroda_names(sostav):
    """'6Е4С+Б+ОС' -> 'Ель,Сосна,Береза,Осина' (все породы состава)"""
    if not sostav:
        return ""
    import re
    codes = re.findall(r"\+?\d*([А-ЯЁа-яё]+)", sostav)
    names = []
    for code in codes:
        name = PORODA_NAMES.get(code, code)
        if name not in names:
            names.append(name)
    return ",".join(names)


def _fmt_ploshad(ploshad):
    """'1.1' -> '1,1' (десятичная запятая, как принято в РБ)"""
    if ploshad is None:
        return ""
    return str(ploshad).replace(".", ",")


DEFAULT_NAMECHAEMOE_MEROPRIYATIE = "Сплошная санитарная рубка (ССР)"
DEFAULT_PROVERIL_DOLZHNOST = "лесничий"


def generate_listok(item, extra_fields=None, templates_dir=".", output_path=None):
    """
    item: dict с полями delyanka_item (lesxoz, lesnichestvo, kvartal, vydel,
          ploshad, sostav, vozrast, ...)
    extra_fields: dict, необязательно - переопределяет значения по умолчанию
        и задаёт данные комиссии/подписей:
        gplho, harakter_povrezhdeniya,
        obnaruzhil_data, obnaruzhil_dolzhnost, obnaruzhil_fio,
        proveril_data, proveril_dolzhnost, proveril_fio,
        namechaemoe_meropriyatie,
        reshenie_data, reshenie_dolzhnost, reshenie_fio,
        zaklyuchenie_text.
    """
    extra_fields = extra_fields or {}
    template_path = Path(templates_dir) / LISTOK_TEMPLATE
    if not template_path.exists():
        raise FileNotFoundError(f"Не найден бланк {template_path}")

    if output_path is None:
        output_path = f"Листок_сигнализации_кв{item.get('kvartal')}_выд{item.get('vydel')}.xlsx"
    output_path = str(output_path)
    shutil.copy(template_path, output_path)

    wb = openpyxl.load_workbook(output_path)
    ws = wb["Лист1"] if "Лист1" in wb.sheetnames else wb.active

    ws["I5"] = extra_fields.get("gplho", DEFAULT_GPLHO)
    ws["G7"] = f'ГЛХУ "{_short_lesxoz(item.get("lesxoz", ""))}"'
    ws["C8"] = item.get("lesnichestvo", "")

    ws["A9"] = "№ лесного квартала/№ таксационного выдела " + \
        f"{item.get('kvartal', '')}/{item.get('vydel', '')}"

    ploshad = _fmt_ploshad(item.get("ploshad", ""))
    a10_template = (
        "2. Ориентировочная площадь в средне-и старшевозрвстных насаждениях "
        f"{ploshad} га, в несомкнувшихся лесных культурах и молодняках "
        "_____га, в лесных питомниках____га, в лесосеменных плантациях____га, на других "
    )
    ws["A10"] = a10_template

    ws["A14"] = extra_fields.get("harakter_povrezhdeniya", DEFAULT_HARAKTER_POVREZHDENIYA)

    ws["A16"] = "4. Поврежденная древесная порода " + _sostav_to_poroda_names(item.get("sostav", ""))
    ws["A17"] = "5. Возраст, лет " + str(item.get("vozrast", "") or "")

    # --- 6. Обнаружил и сообщил (строка 20, подписи-заглушки в строке 21) ---
    ws["A20"] = extra_fields.get("obnaruzhil_data", "")
    ws["D20"] = extra_fields.get("obnaruzhil_dolzhnost", "")
    ws["J20"] = extra_fields.get("obnaruzhil_fio", "")

    # --- 7. Проверил лесничий (строка 24, подписи-заглушки в строке 25) ---
    ws["A24"] = extra_fields.get("proveril_data", "")
    ws["E24"] = extra_fields.get("proveril_dolzhnost", DEFAULT_PROVERIL_DOLZHNOST)
    ws["J24"] = extra_fields.get("proveril_fio", "")

    # --- 8. Намечаемое лесозащитное мероприятие (строка 28) ---
    ws["A28"] = extra_fields.get("namechaemoe_meropriyatie", DEFAULT_NAMECHAEMOE_MEROPRIYATIE)

    # --- 9. Решение должностного лица (строка 34, подписи-заглушки в строке 35) ---
    ws["A34"] = extra_fields.get("reshenie_data", "")
    ws["D34"] = extra_fields.get("reshenie_dolzhnost", "")
    ws["J34"] = extra_fields.get("reshenie_fio", "")

    # --- 10. Заключение специалистов (необязательно, строки 38-42) ---
    if extra_fields.get("zaklyuchenie_text"):
        ws["A38"] = extra_fields["zaklyuchenie_text"]

    wb.save(output_path)
    return output_path


if __name__ == "__main__":
    item = {
        "lesxoz": "Государственное лесохозяйственное учреждение \"Оршанский лесхоз\"",
        "lesnichestvo": "Болбасовское",
        "kvartal": "1", "vydel": "1",
        "ploshad": "1,1", "sostav": "6Е4С+Б", "vozrast": "25",
    }
    out = generate_listok(item, templates_dir="/home/claude/lesovod")
    print("Сгенерирован:", out)
