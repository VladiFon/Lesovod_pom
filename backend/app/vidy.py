"""Справочники видов рубок и видов лесных культур для окраски карты.

Коды хозмероприятий (xmer) — из справочника лесоустройства РБ, как в модуле
ГИСлесхоз (dictionary.xmer). Группы пользования — как «вид пользования»
лесосеки ГИСлесхоза: главное / промежуточное / прочие рубки.

Вид рубки делянки: ручной выбор (delyanka_item.vid_rubki_kod), иначе
угадывается по тексту МДО («рубка леса», «вид рубки») и мероприятию делянки.
Вид культур участка: ручной выбор (lesokultury_uchastok.vid_kultur), иначе по
назначению плантации / способу создания, по умолчанию — обычные лесные культуры.
"""

import json
from typing import Dict, List, Optional

GRUPPA_GLAVNOE = "glavnoe"
GRUPPA_PROMEZH = "promezhutochnoe"
GRUPPA_PROCHIE = "prochie"

GRUPPY_POLZOVANIYA = [
    {"kod": GRUPPA_GLAVNOE, "label": "Рубки главного пользования", "color": "#d32f2f"},
    {"kod": GRUPPA_PROMEZH, "label": "Рубки промежуточного пользования", "color": "#43a047"},
    {"kod": GRUPPA_PROCHIE, "label": "Прочие рубки", "color": "#78909c"},
]

# Порядок важен для угадывания по тексту: более узкие виды — раньше
# («выборочная санитарная» раньше «выборочной», «сплошная санитарная» раньше «сплошной»).
VIDY_RUBOK = [
    {"kod": "ССР", "label": "Сплошная санитарная рубка", "gruppa": GRUPPA_PROMEZH, "color": "#8e24aa",
     "xmer": [1601], "slova": [("сплош", "санитар")]},
    {"kod": "ВСР", "label": "Выборочная санитарная рубка", "gruppa": GRUPPA_PROMEZH, "color": "#ce93d8",
     "xmer": [1605], "slova": [("выбороч", "санитар"), ("санитар",)]},
    {"kod": "УЗ", "label": "Уборка захламленности", "gruppa": GRUPPA_PROMEZH, "color": "#5c6bc0",
     "xmer": [1621], "slova": [("захламл",)]},
    {"kod": "РР", "label": "Рубка реконструкции", "gruppa": GRUPPA_PROMEZH, "color": "#1e88e5",
     "xmer": [1701, 1704, 1705], "slova": [("реконстр",)]},
    {"kod": "ОСВ", "label": "Осветление", "gruppa": GRUPPA_PROMEZH, "color": "#fff176",
     "xmer": [1411], "slova": [("осветл",)]},
    {"kod": "ПРЧ", "label": "Прочистка", "gruppa": GRUPPA_PROMEZH, "color": "#d4e157",
     "xmer": [1425], "slova": [("прочист",)]},
    {"kod": "ПРЖ", "label": "Прореживание", "gruppa": GRUPPA_PROMEZH, "color": "#9ccc65",
     "xmer": [1431], "slova": [("прорежив",)]},
    {"kod": "ПРХ", "label": "Проходная рубка", "gruppa": GRUPPA_PROMEZH, "color": "#2e7d32",
     "xmer": [1435], "slova": [("проходн",)]},
    {"kod": "РУЛ", "label": "Рубка улучшения", "gruppa": GRUPPA_PROMEZH, "color": "#26a69a",
     "xmer": [1550, 1527, 1528], "slova": [("улучшен",)]},
    {"kod": "РФО", "label": "Рубка формирования / обновления", "gruppa": GRUPPA_PROMEZH, "color": "#00838f",
     "xmer": [1552, 1554, 1551], "slova": [("формирован",), ("обновлен",), ("ландшафт",)]},
    {"kod": "РПС", "label": "Рубка по состоянию", "gruppa": GRUPPA_GLAVNOE, "color": "#6d4c41",
     "xmer": [1269], "slova": [("по состоян",)]},
    {"kod": "ПСТ", "label": "Постепенная рубка", "gruppa": GRUPPA_GLAVNOE, "color": "#f57c00",
     "xmer": [1222, 1223, 1224, 1225, 1227, 1228, 1251], "slova": [("постепен",)]},
    {"kod": "ВБР", "label": "Добровольно-выборочная рубка", "gruppa": GRUPPA_GLAVNOE, "color": "#ad1457",
     "xmer": [1265], "slova": [("выбороч",)]},
    {"kod": "РСП", "label": "Рубка с сохранением подроста", "gruppa": GRUPPA_GLAVNOE, "color": "#ff7043",
     "xmer": [1212], "slova": [("сохранен", "подрост")]},
    {"kod": "СПЛ", "label": "Сплошная рубка главного пользования", "gruppa": GRUPPA_GLAVNOE, "color": "#c62828",
     "xmer": [1211, 1216], "slova": [("сплош",), ("узколесосеч",)]},
    {"kod": "РУ", "label": "Рубка ухода (вид не указан)", "gruppa": GRUPPA_PROMEZH, "color": "#66bb6a",
     "xmer": [], "slova": [("уход",), ("промежут",)]},
    {"kod": "ПР", "label": "Прочие рубки", "gruppa": GRUPPA_PROCHIE, "color": "#78909c",
     "xmer": [1301, 1321, 1556, 1808, 1809, 1810, 1812, 1813, 1842, 1843, 1845, 1846, 1847, 1848,
              1849, 1851, 1852, 1853, 1857, 1858, 1881, 1884],
     "slova": [("проч",), ("расчистк",), ("разруб",), ("просек",), ("опасн",)]},
]
VID_RUBKI_NEIZVESTEN = {"kod": "", "label": "Вид рубки не указан", "gruppa": "", "color": "#9e9e9e"}

VIDY_KULTUR = [
    {"kod": "ЛК", "label": "Лесные культуры", "color": "#00bcd4", "xmer": [3211]},
    {"kod": "ПП", "label": "Лесные культуры под пологом леса", "color": "#7cb342", "xmer": [3214]},
    {"kod": "ПЛ", "label": "Плантационные лесные культуры", "color": "#ff9800", "xmer": [3329, 3233, 3234, 3235]},
    {"kod": "ЛШ", "label": "Ландшафтные культуры", "color": "#ec407a", "xmer": [3203]},
    {"kod": "ДК", "label": "Декоративные посадки", "color": "#ab47bc", "xmer": [3202, 3212]},
    {"kod": "ЛСУ", "label": "Лесосеменные участки / плантации", "color": "#8d6e63", "xmer": [3330, 3331, 3332]},
]
VID_KULTUR_DEFAULT = "ЛК"

_RUBKI_BY_KOD = {v["kod"]: v for v in VIDY_RUBOK}
_KULTURY_BY_KOD = {v["kod"]: v for v in VIDY_KULTUR}
_GRUPPY_BY_KOD = {g["kod"]: g for g in GRUPPY_POLZOVANIYA}


def _norm(text) -> str:
    return " ".join(str(text or "").lower().replace("ё", "е").split())


def vid_rubki_po_tekstu(*texts) -> Optional[str]:
    """Код вида рубки по свободному тексту (МДО, мероприятие) или None."""
    t = _norm(" ".join(str(x or "") for x in texts)).replace("несплош", "несплш")
    if not t:
        return None
    for vid in VIDY_RUBOK:
        if vid["kod"] == "СПЛ" and "несплш" in t:
            continue
        for slova in vid["slova"]:
            if all(s in t for s in slova):
                return vid["kod"]
    return None


def _gruppa_po_tekstu(*texts) -> Optional[str]:
    t = _norm(" ".join(str(x or "") for x in texts))
    if "главн" in t:
        return GRUPPA_GLAVNOE
    if "промежут" in t or "уход" in t or "санитар" in t:
        return GRUPPA_PROMEZH
    if "проч" in t:
        return GRUPPA_PROCHIE
    return None


def _mdo(raw) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def vid_rubki_info(kod_vruchnuyu: Optional[str] = None, mdo_raw_json: Optional[str] = None,
                   *drugie_teksty) -> Dict[str, object]:
    """Поля для карты: vid_rubki_kod, vid_rubki (подпись), vid_rubki_color,
    vid_rubki_avto (угадан, не выбран вручную), gruppa, gruppa_label, gruppa_color."""
    kod = (kod_vruchnuyu or "").strip()
    avto = False
    if kod not in _RUBKI_BY_KOD:
        mdo = _mdo(mdo_raw_json)
        teksty = (mdo.get("sposob_rubki"), mdo.get("vid_rubki"), *drugie_teksty)
        kod = next((k for k in (vid_rubki_po_tekstu(t) for t in teksty) if k), "")
        avto = True
    vid = _RUBKI_BY_KOD.get(kod, VID_RUBKI_NEIZVESTEN)
    gruppa = _GRUPPY_BY_KOD.get(vid["gruppa"])
    if gruppa is None and avto:
        # вид не распознан, но «главного / промежуточного пользования» в тексте есть
        gruppa = _GRUPPY_BY_KOD.get(_gruppa_po_tekstu(mdo.get("vid_rubki"), mdo.get("sposob_rubki"), *drugie_teksty))
    return {
        "vid_rubki_kod": vid["kod"],
        "vid_rubki": vid["label"],
        "vid_rubki_color": vid["color"],
        "vid_rubki_avto": avto,
        "gruppa": gruppa["kod"] if gruppa else "",
        "gruppa_label": gruppa["label"] if gruppa else "Вид пользования не указан",
        "gruppa_color": gruppa["color"] if gruppa else VID_RUBKI_NEIZVESTEN["color"],
    }


def vid_kultur_info(kod_vruchnuyu: Optional[str] = None, naznachenie_plantatsii: Optional[str] = None,
                    *drugie_teksty) -> Dict[str, object]:
    """Поля для карты: vid_kultur_kod, vid_kultur (подпись), vid_kultur_color, vid_kultur_avto."""
    kod = (kod_vruchnuyu or "").strip()
    avto = False
    if kod not in _KULTURY_BY_KOD:
        avto = True
        t = _norm(" ".join(str(x or "") for x in drugie_teksty))
        if _norm(naznachenie_plantatsii) or ("плантац" in t and "семен" not in t):
            kod = "ПЛ"
        elif "семен" in t:
            kod = "ЛСУ"
        elif "полог" in t:
            kod = "ПП"
        elif "ландшафт" in t:
            kod = "ЛШ"
        elif "декоратив" in t:
            kod = "ДК"
        else:
            kod = VID_KULTUR_DEFAULT
    vid = _KULTURY_BY_KOD[kod]
    return {"vid_kultur_kod": vid["kod"], "vid_kultur": vid["label"],
            "vid_kultur_color": vid["color"], "vid_kultur_avto": avto}


def proverit_vid_rubki(kod: Optional[str]) -> Optional[str]:
    """Пустое — сброс на автоопределение; неизвестный код — ValueError."""
    kod = (kod or "").strip()
    if not kod:
        return None
    if kod not in _RUBKI_BY_KOD:
        raise ValueError(f"Неизвестный вид рубки: {kod}")
    return kod


def proverit_vid_kultur(kod: Optional[str]) -> Optional[str]:
    kod = (kod or "").strip()
    if not kod:
        return None
    if kod not in _KULTURY_BY_KOD:
        raise ValueError(f"Неизвестный вид культур: {kod}")
    return kod


def legendy() -> Dict[str, List[dict]]:
    """Справочники с цветами для сайта, телефона и QGIS."""
    # slova — части слов для распознавания по тексту (плагин QGIS красит ими
    # слой «Лесосеки» ГИСлесхоза по полю cuttingtyp)
    return {
        "vidy_rubok": [dict(v, slova=[list(s) for s in v["slova"]]) for v in VIDY_RUBOK]
        + [dict(VID_RUBKI_NEIZVESTEN, xmer=[], slova=[])],
        "gruppy_polzovaniya": GRUPPY_POLZOVANIYA,
        "vidy_kultur": VIDY_KULTUR,
    }
