# -*- coding: utf-8 -*-
"""
Генератор "Акта освидетельствования лесосеки" — v3 (официальный бланк).

Документ строится не с нуля, а на основе реального официального бланка
(templates/akt_osvidetelstvovaniya_shablon.docx, табличная вёрстка с
рамками-подчёркиваниями на уровне ячеек) — в него точечно вписывается
текст в заранее определённые ячейки (см. akt_template_fill.py). Всё
остальное — жирные подписи, рамки, объединения ячеек — берётся из шаблона
без изменений, поэтому внешний вид документа не меняется от заполнения.

Публичный интерфейс (generate_akt_osvidetelstvovaniya /
generate_blank_akt_template) СОХРАНЁН как в предыдущей версии — роутер
(app/routers/inspection.py) менять не нужно.

Отличия официального бланка от прежнего пользовательского шаблона:
  - слово "лесосеки" в строке "произвели освидетельствование ___лесосеки"
    теперь напечатано в самом бланке — заполняется только вид лесосеки
    (ГП/ССР/ВСР и т.п.), vid_lesoseki, сразу после него;
  - верхний блок "уполномоченные представители" вмещает до 3 членов
    комиссии (d["chleny"][:3]) вместо прежних 2 — если нужно больше,
    придётся редактировать сам файл-шаблон (добавить строку в таблицу);
  - в бланке нет отдельных линий для даты выдачи лесорубочного билета и
    для сроков окончания заготовки/вывозки — эти даты в документе не
    печатаются (данные при этом остаются в карточке делянки).
"""
import os
from pathlib import Path

from akt_template_fill import fill_akt

TEMPLATE_PATH = Path(__file__).parent / "templates" / "akt_osvidetelstvovaniya_shablon.docx"

_MONTHS_GENITIVE = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _split_date(value):
    """"ДД.ММ.ГГГГ" -> (день, месяц словом в родительном падеже, год).
    Если формат не распознан — возвращает (исходная строка, "", "") чтобы
    хоть что-то попало в акт, а не потерялось молча."""
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


def _fmt_num(value):
    if value is None or value == "":
        return ""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _dolzhnost_fio(dolzhnost, fio):
    return f"{dolzhnost or ''} {fio or ''}".strip()


def generate_akt_osvidetelstvovaniya(delyanka: dict, items: list, sortiment_totals: dict,
                                      act_data: dict, output_path):
    """Совместимо по сигнатуре с прошлой версией — вызывается из
    app/routers/inspection.py (_run_generate_akt_osv) без изменений."""
    d = act_data or {}
    delyanka = delyanka or {}
    items = items or []
    first_item = items[0] if items else {}

    lesxoz = delyanka.get("lesxoz") or first_item.get("lesxoz") or ""
    lesnichestvo = delyanka.get("lesnichestvo") or first_item.get("lesnichestvo") or ""

    kv_vyd_parts = []
    for it in items:
        kv = it.get("kvartal") or "?"
        vd = it.get("vydel") or "?"
        if (kv, vd) not in kv_vyd_parts:
            kv_vyd_parts.append((kv, vd))
    kv_text = "; ".join(kv for kv, _ in kv_vyd_parts) or ""
    vyd_text = "; ".join(vd for _, vd in kv_vyd_parts) or ""

    act_day, act_month, act_year = _split_date(d.get("act_date"))
    osn_day, osn_month, osn_year = _split_date(d.get("osnovanie_data"))
    izv_day, izv_month, izv_year = _split_date(d.get("izveshchenie_data"))

    st = sortiment_totals or {}
    has_sortiment_data = bool(st)

    def sv(key, field):
        if not has_sortiment_data:
            return ""
        return _fmt_num((st.get(key) or {}).get(field, 0))

    if has_sortiment_data:
        total_limit = sum((st.get(k) or {}).get("limit", 0) for k in ("KR", "SR", "ML", "DROVA"))
        total_fakt = sum((st.get(k) or {}).get("fakt", 0) for k in ("KR", "SR", "ML", "DROVA"))
    else:
        total_limit = total_fakt = ""

    chleny_raw = d.get("chleny") or []
    chleny_lines = [_dolzhnost_fio(c.get("dolzhnost"), c.get("fio")) for c in chleny_raw]

    fill_data = {
        "act_day": act_day, "act_month": act_month, "act_year": act_year,
        "oblast_rayon": d.get("oblast_rayon", ""),
        "lesxoz": lesxoz, "lesnichestvo": lesnichestvo,
        "predstavitel_lesxoza": d.get("predstavitel_lesxoza_dolzhnost_fio") or _dolzhnost_fio(
            d.get("predstavitel_lesxoza_dolzhnost"), d.get("predstavitel_lesxoza_fio")),
        "predstavitel_lesopolz_organizatsiya": d.get("predstavitel_lesopolz_organizatsiya", ""),
        "predstavitel_lesopolz_dolzhnost_fio": _dolzhnost_fio(
            d.get("predstavitel_lesopolz_dolzhnost"), d.get("predstavitel_lesopolz_fio")),
        "osnovanie_nomer": d.get("osnovanie_nomer", ""),
        "osnovanie_day": osn_day, "osnovanie_month": osn_month, "osnovanie_year": osn_year,
        "izveshchenie_day": izv_day, "izveshchenie_month": izv_month, "izveshchenie_year": izv_year,
        "chleny": chleny_lines,
        "vid_lesoseki": d.get("vid_lesoseki", ""),
        "kvartal": kv_text, "vydel": vyd_text,
        "bilet_nomer": delyanka.get("nomer_lesorubochnogo_bileta", ""),
        "sposob_rubki": d.get("sposob_rubki") or "сплошной",
        "sposob_ucheta": d.get("sposob_ucheta") or "по площади",
        "sposob_ochistki": d.get("sposob_ochistki") or
            "измельчение и разбрасывание порубочных остатков на лесосеке",
        "ploshad_razresheno": _fmt_num(d.get("ploshad_razresheno")),
        "ploshad_fakt": _fmt_num(d.get("ploshad_fakt")),
        "obyom_vsego_limit": _fmt_num(total_limit), "obyom_vsego_fakt": _fmt_num(total_fakt),
        "sortiment_totals": {
            k: {"limit": sv(k, "limit"), "fakt": sv(k, "fakt")}
            for k in ("KR", "SR", "ML", "DROVA", "HVOROST")
        } if has_sortiment_data else {},
        "podrost_ploshad_ga": d.get("podrost_ploshad_ga", ""),
        "podrost_ploshad_protsent": d.get("podrost_ploshad_protsent", ""),
        "podrost_kolichestvo_tys": d.get("podrost_kolichestvo_tys", ""),
        "podrost_kolichestvo_protsent": d.get("podrost_kolichestvo_protsent", ""),
        "narusheniya": d.get("narusheniya") or [],
        "harakteristika_podrosta": d.get("harakteristika_podrosta", ""),
        "kachestvo_rubok": d.get("kachestvo_rubok", ""),
        "zayavleniya_lesopolzovatelya": d.get("zayavleniya_lesopolzovatelya", ""),
        "zayavleniya_drugih": d.get("zayavleniya_drugih", ""),
        "prilozhenie_4": d.get("prilozhenie_4", ""),
        "predsedatel_dolzhnost": d.get("predsedatel_dolzhnost", ""),
        "predsedatel_fio": d.get("predsedatel_fio", ""),
        "chleny_podpisi": chleny_raw,
        "predstavitel_lesopolzovaniya_dolzhnost": d.get("predstavitel_lesopolzovaniya_dolzhnost", ""),
        "predstavitel_lesopolzovaniya_fio": d.get("predstavitel_lesopolzovaniya_fio", ""),
        "rukovoditel_fio": d.get("rukovoditel_fio", ""),
    }

    return fill_akt(str(TEMPLATE_PATH), fill_data, output_path)


def generate_blank_akt_template(output_path):
    """Пустой бланк — та же функция с пустыми данными (все ячейки
    останутся пустыми, но с правильными рамками/шрифтами)."""
    return generate_akt_osvidetelstvovaniya(
        delyanka={}, items=[], sortiment_totals={}, act_data={}, output_path=output_path,
    )
