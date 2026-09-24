# -*- coding: utf-8 -*-
"""
Генератор "Справки о количестве заготовленной древесины" (справка
лесозаготовителя) — экран "Акты освидетельствования".

По Лесному кодексу РБ (ст. 72) эта справка, подписанная руководителем
лесопользователя, — основа для заполнения таблицы "При освидетельствовании
установлено" в Акте освидетельствования лесосеки (см.
osvidetelstvovanie_generator.py).

Документ строится на основе официального бланка
(templates/spravka_shablon.docx) — текст точечно вписывается в заранее
определённые ячейки (см. spravka_template_fill.py), поэтому внешний вид
документа не меняется от заполнения. Бланк даёт ФИКСИРОВАННЫЙ набор
колонок по породам (Ель, Сосна, Береза, Осина, Дуб, Ольха С, Липа) — порода,
не входящая в этот список, попадает только в колонку "Всего".

Автозаполняемые поля (по просьбе пользователя — "будет брать данные с
нашего экрана Учёт Заготовки"):
  - лесхоз, лесничество, № лесорубочного билета/дата — из карточки делянки.
  - № квартала/выдела — из delyanka_item (если выделов несколько, все
    перечисляются через "; ").
  - площадь, пройденная рубкой — сумма delyanka_item.ploshad (из МДО).
  - таблица по породам/категориям крупности — ФАКТ из нарядов
    (raskhod_naryad/raskhod_pozitsiya), через
    screens.raskhod.balance.compute_sortiment_totals_multi().

НЕ автозаполняются (нет источника данных в приложении — значения
передаются вызывающим кодом как аргументы с разумными значениями по
умолчанию, редактируемыми в интерфейсе перед генерацией):
  - "ликвида из сучьев и кроны" — по умолчанию 0.
  - наименование лесопользователя — бланк требует его отдельной строкой,
    в приложении такого поля на этом экране нет, редактируется вручную.
  - ФИО руководителя — передаётся явно как аргумент.
"""
from pathlib import Path

from spravka_template_fill import fill_spravka, PORODA_COL

TEMPLATE_PATH = Path(__file__).parent / "templates" / "spravka_shablon.docx"

_MONTHS_GENITIVE = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _split_date(value):
    """"ДД.ММ.ГГГГ" -> (день, месяц словом в родительном падеже, год)."""
    if not value:
        return "", "", ""
    value = str(value).strip()
    for sep in (".", "/", "-"):
        parts = value.split(sep)
        if len(parts) == 3:
            d, m, y = parts
            try:
                mi = int(m)
                if 1 <= mi <= 12:
                    return d.lstrip("0") or "0", _MONTHS_GENITIVE[mi], y
            except ValueError:
                pass
    return value, "", ""


def _fmt(value):
    """0 -> '0', 12.0 -> '12', 12.5 -> '12.5' — без хвостовых нулей, но и
    без потери дробной части, если она есть."""
    if value is None:
        return ""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def generate_spravka(
    delyanka: dict,
    items: list,
    sortiment_totals: dict,
    output_path,
    *,
    ploshad_proydennaya=None,
    likvid_such_krony=0,
    lesopolzovatel="",
    rukovoditel_fio="",
):
    """Строит "Справку о количестве заготовленной древесины" по официальному
    бланку и сохраняет в output_path.

    delyanka: dict с полями делянки (nazvanie, nomer_lesorubochnogo_bileta,
        data_lesorubochnogo_bileta).
    items: список ПОЛНЫХ словарей delyanka_item (для lesxoz/lesnichestvo/
        kvartal/vydel — берём из первого; при разных kvartal/vydel по
        выделам перечисляем все через "; ").
    sortiment_totals: результат
        screens.raskhod.balance.compute_sortiment_totals_multi(conn, items)
        — {порода: {"KR":ф,"SR":ф,"ML":ф,"DROVA":ф,"HVOROST":ф}}.
    ploshad_proydennaya: площадь, пройденная рубкой, га; если не передано, 0.
    likvid_such_krony: данные не из приложения, по умолчанию 0.
    lesopolzovatel: наименование лесопользователя (для строки "что ___").
    rukovoditel_fio: подпись внизу справки.
    """
    d = delyanka or {}
    items = items or []
    first_item = items[0] if items else {}

    lesxoz = d.get("lesxoz") or first_item.get("lesxoz") or ""
    lesnichestvo = d.get("lesnichestvo") or first_item.get("lesnichestvo") or ""

    kvartal_parts, vydel_parts = [], []
    for it in items:
        kv = it.get("kvartal") or "?"
        vd = it.get("vydel") or "?"
        if kv not in kvartal_parts:
            kvartal_parts.append(kv)
        if vd not in vydel_parts:
            vydel_parts.append(vd)
    kvartal_text = "; ".join(kvartal_parts) if kvartal_parts else ""
    vydel_text = "; ".join(vydel_parts) if vydel_parts else ""

    bilet_day, bilet_month, bilet_year = _split_date(d.get("data_lesorubochnogo_bileta"))

    st = sortiment_totals or {}

    def by_poroda(sortiment_key):
        return {code: _fmt(vals.get(sortiment_key, 0.0)) for code, vals in st.items()
                if code in PORODA_COL}

    def total(sortiment_key):
        return _fmt(sum(vals.get(sortiment_key, 0.0) for vals in st.values()))

    kr_by, sr_by, ml_by = by_poroda("KR"), by_poroda("SR"), by_poroda("ML")
    drova_by, hvorost_by = by_poroda("DROVA"), by_poroda("HVOROST")

    def sum_by(*keys):
        codes = set(st.keys())
        return {code: _fmt(sum(st[code].get(k, 0.0) for k in keys)) for code in codes
                if code in PORODA_COL}

    delovaya_by = sum_by("KR", "SR", "ML")
    delovaya_total = _fmt(sum(vals.get(k, 0.0) for vals in st.values() for k in ("KR", "SR", "ML")))
    # "Древесины - всего" и "Итого" — одна и та же сумма всех категорий
    # (так же дублировалась и в прежней, собираемой с нуля, версии).
    vsego_by = sum_by("KR", "SR", "ML", "DROVA", "HVOROST")
    vsego_total = _fmt(sum(vals.get(k, 0.0) for vals in st.values()
                            for k in ("KR", "SR", "ML", "DROVA", "HVOROST")))

    fill_data = {
        "lesxoz": lesxoz,
        "lesopolzovatel": lesopolzovatel,
        "bilet_nomer": d.get("nomer_lesorubochnogo_bileta", ""),
        "bilet_day": bilet_day, "bilet_month": bilet_month, "bilet_year": bilet_year,
        "kvartal": kvartal_text, "vydel": vydel_text,
        "lesnichestvo": lesnichestvo,
        "delyanka_nomer": d.get("nazvanie", ""),
        "ploshad_proydennaya": _fmt(ploshad_proydennaya or 0),
        "itogo_total": vsego_total, "itogo_by_poroda": vsego_by,
        "delovaya_total": delovaya_total, "delovaya_by_poroda": delovaya_by,
        "kr_total": total("KR"), "kr_by_poroda": kr_by,
        "sr_total": total("SR"), "sr_by_poroda": sr_by,
        "ml_total": total("ML"), "ml_by_poroda": ml_by,
        "drova_total": total("DROVA"), "drova_by_poroda": drova_by,
        "likvid_such_krony": _fmt(likvid_such_krony or 0),
        "hvorost_total": total("HVOROST"), "hvorost_by_poroda": hvorost_by,
        "vsego_total": vsego_total, "vsego_by_poroda": vsego_by,
        "rukovoditel_fio": rukovoditel_fio,
    }

    return fill_spravka(str(TEMPLATE_PATH), fill_data, output_path)
