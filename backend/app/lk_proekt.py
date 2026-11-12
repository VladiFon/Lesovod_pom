# -*- coding: utf-8 -*-
"""Проекты лесных культур (Влад, 12.11.2026).

Проект лесных культур — приложение 5 к Положению о порядке лесовосстановления
и лесоразведения (пост. Минлесхоза №80 в ред. №5-2022 и №14-2024), п.21:
составляет лесничий, утверждает лесхоз до начала работ, правки — в течение
10 рабочих дней после посадки до техприёмки (п.23 формы).

Проекты составляются в АРМ ЛВ и сохраняются в Word (.doc). Здесь —
загрузка этих файлов в базу (предпросмотр → запись, повторная загрузка без
дублей), привязка к делянке, проверки по нормативам и хранение исходного
файла и плана участка, чтобы перепечатать, если бумага потеряется.

Разбор формы: Word сводится к списку «кусков» — абзацы и ячейки подряд
(app/word_doc.py). Пункты формы ищутся по их подписям («3. Рельеф» →
следующий кусок — «ровный»), подписи-продолжения выбрасываются.

Нормы для проверок:
  * прил.1 Положения — минимальная густота по ТЛУ (сеянцы ОКС / иной
    посадочный материал), для ЗКС — на 20% меньше (п.18);
  * ТКП 667-2022 табл. 6.3 — рекомендуемое размещение посадочных мест;
  * п.56 — допуски техприёмки к проекту (густота 90–120%, междурядье ±15%).
"""
import json
import re
from typing import Dict, List, Optional, Tuple

from app import word_doc

SCHEMA = """
CREATE TABLE IF NOT EXISTS lk_proekt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    klyuch TEXT,
    istochnik TEXT,               -- 'arm' — загружен из АРМ ЛВ, 'ruchnoy'
    fail_imya TEXT,
    status TEXT NOT NULL DEFAULT 'proekt',  -- proekt / utverzhden / posazhen / prinyat / otmenen
    sezon TEXT,                   -- 'весна' / 'осень'
    god INTEGER,
    lesnichestvo TEXT,
    leshoz TEXT,
    kvartal TEXT,
    vydely TEXT,
    ploshad REAL,
    delyanka_id INTEGER REFERENCES delyanka(id),
    uchastok_id INTEGER REFERENCES lesokultury_uchastok(id),
    tlu TEXT,
    tip_lesa TEXT,
    glavnaya_poroda TEXT,
    shema_smesheniya TEXT,
    na_ga REAL,                   -- посадочных мест на 1 га (всего по породам)
    vsego REAL,                   -- посадочных мест на участок
    god_perevoda INTEGER,
    polya_json TEXT NOT NULL DEFAULT '{}',   -- все пункты формы (текст + разобранное)
    plan_img BLOB,
    plan_ext TEXT,
    fail_blob BLOB,
    primechanie TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_lk_proekt_klyuch ON lk_proekt(klyuch);
CREATE INDEX IF NOT EXISTS idx_lk_proekt_delyanka ON lk_proekt(delyanka_id);
"""

STATUSY = {
    "proekt": "Проект",
    "utverzhden": "Утверждён",
    "posazhen": "Посажено",
    "prinyat": "Принят (техприёмка)",
    "otmenen": "Отменён",
}

# Подписи пунктов формы (прил.5). Ключ — поле, значение — начало подписи.
PUNKTY = [
    ("ploshad_t", r"1\.\s*Площадь участка"),
    ("radiaciya_t", r"1\.1\.?\s*В зонах радиоактивного"),
    ("kategoriya_t", r"2\.\s*Категория лесокультурной"),
    ("relef", r"3\.\s*Рельеф"),
    ("pochva", r"4\.\s*Почва"),
    ("pokrov", r"5\.\s*Почвенный покров"),
    ("tip_tlu_t", r"6\.\s*Тип леса"),
    ("estestv", r"7\.\s*Наличие естественного"),
    ("lesopatologiya", r"8\.\s*Лесопатологическ"),
    ("obrabotka", r"9\.\s*Способы и время обработки"),
    ("razmeshchenie", r"10\.\s*Размещение площадок"),
    ("rekonstr_sostav", r"11\.\s*Состав, возраст"),
    ("rekonstr_sposob", r"12\.\s*Способ реконструкции"),
    ("metod", r"13\.\s*Метод и способ"),
    ("rasstoyanie_t", r"14\.\s*Среднее расстояние"),
    ("shema_smesheniya", r"15\.\s*Схема смешения"),
    ("glavnaya_poroda", r"16\.\s*Главная порода"),
    ("material_t", r"17\.\s*Характеристика"),
    ("podgotovka", r"18\.\s*Способ подготовки"),
    ("uhody_t", r"19\.\s*Прогнозируемые"),
    ("protivopozhar", r"20\.\s*Противопожарные"),
    ("god_perevoda_t", r"21\.\s*Год перевода"),
    ("potrebnost_t", r"22\.\s*Для выполнения работ"),
    ("sostavil_t", r"Проект лесных культур составил"),
    ("soglasoval_t", r"Проект лесных культур проверил"),
    ("izmeneniya", r"23\.\s*В проект внесены"),
]

# Строки бланка, которые не являются значениями (продолжения подписей).
_SHABLON = [
    r"^гектаров\.?$", r"^\(.*\)$", r"^и рекомендуемые лесозащитные мероприятия$",
    r"^\(?пластов, валов, холмиков\)?$", r"^окон, их количество", r"^механизированный, марки машин\)?$",
    r"^гектар, на всей площади$", r"^посадочного материала \(вид, возраст", r"^полосы, пожароустойчивость",
    r"^насаждений\)$", r"^Дата$", r"^_+", r"^Ки/км2;?$", r"^мощность дозы гамма", r"^мкЗв/ч",
    r"^открытой территории$", r"^ч/год", r"^кг семян на 1 гектар", r"^кг на всю площадь",
    r"^для посадки лесов$", r"^тысяч штук на", r"^площадь, в том числе по породам$",
    r"^\(юридическое лицо", r"^\(фамилия", r"^\(Фамилия", r"^Главный лесничий$",
]
_SHABLON_RE = [re.compile(p, re.I) for p in _SHABLON]

# Минимальная густота (прил.1 Положения): группа ТЛУ → (СН с ОКС, иной ПМ), шт/га.
NORMA_GUSTOTY = {
    "A": (5600, 5600),
    "B": (5200, 3600),
    "C": (4300, 3400),
    "D": (4000, 3300),
    "T": (3600, 3200),  # выработанные торфяники, осушенные земли
}
# Допустимые главные породы по группе ТЛУ (прил.1, гр.4).
GLAVNYE = {
    "A": "С Б",
    "B": "С Е Л П Д Лп Б",
    "C": "Е С Л П Д Бк Я Кл В Лп Олч Б",
    "D": "Д Бк Я Кл В С Е Л П Лп Олч Б",
    "T": "С Е Олч Б",
}
# Рекомендуемое размещение (ТКП 667 табл. 6.3): междурядье, шаг (мин, макс), м.
RAZMESHCHENIE = {
    "A": ((2.0, 3.5), (0.5, 0.8), (0.5, 0.8)),
    "B": ((2.0, 3.8), (0.5, 0.9), (0.5, 1.3)),
    "C": ((2.0, 4.0), (0.5, 1.1), (0.5, 1.4)),
    "D": ((2.0, 4.0), (0.5, 1.2), (0.5, 1.5)),
    "T": ((2.0, 4.0), (0.5, 1.3), (0.5, 1.4)),
}
PORODY = {
    "сосна": "С", "ель": "Е", "береза": "Б", "берёза": "Б", "дуб": "Д", "ольха черная": "Олч",
    "ольха чёрная": "Олч", "ольха": "Олч", "лиственница": "Л", "пихта": "П", "липа": "Лп",
    "клен": "Кл", "клён": "Кл", "ясень": "Я", "бук": "Бк", "вяз": "В",
}
_LAT = str.maketrans({"А": "A", "В": "B", "С": "C", "Д": "D", "а": "A", "в": "B", "с": "C", "д": "D",
                      "a": "A", "b": "B", "c": "C", "d": "D"})


class ProektError(Exception):
    """Ошибка, понятная человеку."""


def ensure(conn) -> None:
    conn.executescript(SCHEMA)


# --------------------------------------------------------------------------- #
#   Мелочи
# --------------------------------------------------------------------------- #
def _num(s) -> Optional[float]:
    t = str(s or "").strip().replace(",", ".").replace(" ", "")
    m = re.match(r"^-?\d+(\.\d+)?$", t)
    return float(t) if m else None


def _json(s, default):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


def poroda_kod(p) -> str:
    t = str(p or "").strip()
    low = t.lower()
    for k, v in PORODY.items():
        if low == k:
            return v
    for k, v in PORODY.items():
        if low.startswith(k[:4]):
            return v
    return t[:3]


def gruppa_tlu(tlu) -> Optional[str]:
    """«С2», «C2», «Д2», «кисличный/Д2» → «C»/«D»…; торфяник → «T»."""
    t = str(tlu or "")
    if re.search(r"торф|осушен", t, re.I):
        return "T"
    m = re.search(r"([АВСДABCDавсдabcd])\s*([1-5])", t)
    if not m:
        return None
    return m.group(1).translate(_LAT)


def tlu_norm(tlu) -> str:
    m = re.search(r"([АВСДABCDавсдabcd])\s*([1-5])", str(tlu or ""))
    return (m.group(1).translate(_LAT) + m.group(2)) if m else str(tlu or "").strip()


# --------------------------------------------------------------------------- #
#   Разбор Word-проекта из АРМ ЛВ
# --------------------------------------------------------------------------- #
def _shablon(c: str) -> bool:
    return any(r.search(c) for r in _SHABLON_RE)


def _posle(chunks: List[str], podpis_re: str, start: int = 0) -> Tuple[Optional[str], int]:
    """Первое непустое значение после куска с подписью (сама подпись не в счёт)."""
    r = re.compile(podpis_re, re.I)
    for i in range(start, len(chunks)):
        if r.search(chunks[i]):
            for j in range(i + 1, min(i + 4, len(chunks))):
                c = chunks[j]
                if c:
                    return c, i
            return None, i
    return None, -1


def razobrat_chunks(chunks: List[str]) -> dict:
    ch = [c for c in chunks if c is not None]
    nz = [c for c in ch if c]
    p: Dict[str, object] = {}

    # --- шапка ---
    for c in nz:
        m = re.match(r"^(весну|весна|осень|осенью)\s+(\d{4})", c, re.I)
        if m:
            p["sezon"] = "весна" if m.group(1).lower().startswith("вес") else "осень"
            p["god"] = int(m.group(2))
            break
    for i, c in enumerate(nz):
        if re.search(r"лесничеств|лесопункт", c, re.I) and len(c) < 60 and not c.startswith("("):
            p["lesnichestvo"] = c
            for c2 in nz[i + 1:i + 4]:
                if re.search(r"лесхоз", c2, re.I):
                    p["leshoz"] = c2
                    break
            break
    kv, _ = _posle(nz, r"номер лесного квартала")
    vyd, _ = _posle(nz, r"номер таксационного выдела")
    vid, _ = _posle(nz, r"вид создаваемого насаждения")
    p["kvartal"] = (kv or "").strip()
    p["vydely"] = re.sub(r"\s+", "", vyd or "")
    if vid and not re.match(r"План участка", vid, re.I):
        p["vid_nasazhdeniya"] = vid

    # --- план: «Выд. 2- 1.5 га, выд. 8 -2.2 га» ---
    i_plan = next((i for i, c in enumerate(nz) if re.match(r"План участка", c, re.I)), -1)
    i_p1 = next((i for i, c in enumerate(nz) if re.match(r"1\.\s*Площадь", c, re.I)), -1)
    plan_t = " ".join(nz[i_plan + 1:i_p1]) if 0 <= i_plan < i_p1 else ""
    p["plan_tekst"] = plan_t
    p["vydely_ploshad"] = [
        {"vydel": m.group(1), "ploshad": float(m.group(2).replace(",", "."))}
        for m in re.finditer(r"выд\.?\s*([\w/]+)\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*га", plan_t, re.I)
    ]

    # --- пункты: всё между подписью и следующей подписью, кроме слов бланка ---
    poz = []
    for key, rx in PUNKTY:
        r = re.compile(rx, re.I)
        i = next((k for k, c in enumerate(nz) if r.search(c)), -1)
        if i >= 0:
            poz.append((i, key))
    poz.sort()
    for n, (i, key) in enumerate(poz):
        konec = poz[n + 1][0] if n + 1 < len(poz) else len(nz)
        vals = [c for c in nz[i + 1:konec] if not _shablon(c)]
        p[key] = "; ".join(vals)
    # «16. Главная порода | ель» — внутри 15-го пункта не путать
    # 1.1 — радиация: числа после соответствующих подписей
    rad = {}
    for key, rx in (("cs137", r"цезием-137"), ("doza", r"гамма-излучения"),
                    ("otkr", r"^открытой территории$"), ("tehnika", r"на технике")):
        v, _ = _posle(nz, rx)
        if _num(v) is not None:
            rad[key] = _num(v)
    p["radiaciya"] = rad

    # --- разбор значений ---
    pl = re.search(r"\d+(?:[.,]\d+)?", str(p.get("ploshad_t") or ""))
    p["ploshad"] = float(pl.group(0).replace(",", ".")) if pl else None
    kt = str(p.get("kategoriya_t") or "")
    m = re.search(r"«\s*([абвгд])\s*»|^\s*\"?([абвгд])\"?\s*[-–]", kt, re.I)
    p["kategoriya"] = (m.group(1) or m.group(2)).lower() if m else ""
    m = re.search(r"пней\s*(\d+)", kt, re.I)
    p["pni_na_ga"] = int(m.group(1)) if m else None
    m = re.search(r"[Вв]ырубка\s+(\d{4})", kt)
    p["god_vyrubki"] = int(m.group(1)) if m else None
    tt = str(p.get("tip_tlu_t") or "")
    if "/" in tt:
        a, b = tt.split("/", 1)
        p["tip_lesa"], p["tlu"] = a.strip(), tlu_norm(b) or b.strip()
    else:
        p["tip_lesa"], p["tlu"] = tt.strip(), tlu_norm(tt) if gruppa_tlu(tt) else ""

    # 14: «Е-3.2*0.76 м., 2460 шт./га., 9102 шт. всего; …»
    porody = []
    for m in re.finditer(
            r"([А-ЯЁ][а-яё]{0,3})\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*[*xх×]\s*(\d+(?:[.,]\d+)?)\s*м\.?,?\s*"
            r"(\d+(?:[.,]\d+)?)\s*шт\.?\s*/\s*га\.?,?\s*(\d+(?:[.,]\d+)?)\s*шт\.?\s*всего",
            str(p.get("rasstoyanie_t") or "")):
        porody.append({
            "poroda": m.group(1), "mezhduryade": float(m.group(2).replace(",", ".")),
            "shag": float(m.group(3).replace(",", ".")), "na_ga": float(m.group(4).replace(",", ".")),
            "vsego": float(m.group(5).replace(",", ".")),
        })
    # 15: «6рЕ3рБ1рС» → рядов по породам
    ryady = {m.group(2): int(m.group(1)) for m in re.finditer(r"(\d+)\s*р\s*([А-ЯЁ][а-яё]{0,3})", str(p.get("shema_smesheniya") or ""))}
    # 17: «Е - СН6 с ЗКС; Б - СН2»
    material = {}
    for kusok in re.split(r";", str(p.get("material_t") or "")):
        m = re.match(r"\s*([А-ЯЁ][а-яё]{0,3}(?:\s*,\s*[А-ЯЁ][а-яё]{0,3})*)\s*[-–]\s*(.+)", kusok)
        if m:
            for por in re.split(r"\s*,\s*", m.group(1)):
                material[por] = m.group(2).strip()
    for x in porody:
        x["ryadov"] = ryady.get(x["poroda"])
        x["material"] = material.get(x["poroda"], "")
        x["zks"] = bool(re.search(r"ЗКС", x["material"], re.I))
    p["porody"] = porody
    p["na_ga"] = sum(x["na_ga"] for x in porody) or None
    p["vsego"] = sum(x["vsego"] for x in porody) or None
    p["glavnaya_poroda"] = str(p.get("glavnaya_poroda") or "").strip()
    # 19: «2027 - 2-ой; 2028 - 2-ой; 2029 - 3-ий;»
    p["uhody"] = [{"god": int(m.group(1)), "kolichestvo": int(m.group(2))}
                  for m in re.finditer(r"(\d{4})\s*[-–]\s*(\d+)", str(p.get("uhody_t") or ""))]
    m = re.search(r"\d{4}", str(p.get("god_perevoda_t") or ""))
    p["god_perevoda"] = int(m.group(0)) if m else None
    # 22: потребность
    potr = {}
    for key, rx in (("posev_kg_ga", r"для посева лесов"), ("posev_kg", r"^кг семян на 1 гектар"),
                    ("posadka_tys_ga", r"^для посадки лесов$"), ("posadka_tys", r"^тысяч штук на 1 гектар")):
        v, _ = _posle(nz, rx)
        if _num(v) is not None:
            potr[key] = _num(v)
    v, _ = _posle(nz, r"^площадь, в том числе по породам$")
    if v and not re.match(r"Проект лесных культур", v):
        potr["po_porodam"] = v
    p["potrebnost"] = potr
    # подписи и даты
    p["sostavil"] = _fio(nz, r"составил лесничий")
    p["soglasoval"] = _fio(nz, r"проверил и согласовал")
    p["data_sostavleniya"] = _data_posle(nz, r"составил лесничий")
    p["data_soglasovaniya"] = _data_posle(nz, r"проверил и согласовал")
    return p


def _fio(nz, rx) -> str:
    r = re.compile(rx, re.I)
    for i, c in enumerate(nz):
        if r.search(c):
            ost = r.split(c, 1)[-1].strip(" :")
            ost = re.sub(r"^(лесничий|специалист по лесовосстановлению)\s*", "", ost, flags=re.I)
            if ost and not _shablon(ost):
                return ost
            for c2 in nz[i + 1:i + 3]:
                if c2.startswith("(") or c2.lower() == "дата" or re.match(r"\d+\.", c2):
                    break
                if not _shablon(c2) and not re.search(r"специалист|лесовосстановлен", c2, re.I):
                    return c2
            return ""
    return ""


MESYACY = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8,
           "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}


def _data_posle(nz, rx) -> str:
    r = re.compile(rx, re.I)
    for i, c in enumerate(nz):
        if r.search(c):
            for c2 in nz[i + 1:i + 6]:
                m = re.search(r"«?\s*(\d{1,2})\s*»?\s+([а-я]+)\s+(\d{4})", c2, re.I)
                if m:
                    mes = next((v for k, v in MESYACY.items() if m.group(2).lower().startswith(k)), None)
                    if mes:
                        return f"{int(m.group(3)):04d}-{mes:02d}-{int(m.group(1)):02d}"
                m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", c2)
                if m:
                    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
                if re.match(r"Проект лесных|23\.", c2):
                    break
            return ""
    return ""


def razobrat_fail(data: bytes, imya: str = "") -> dict:
    try:
        doc = word_doc.prochitat(data, imya)
    except word_doc.WordError as exc:
        raise ProektError(str(exc))
    chunks = doc["chunks"]
    if not any(re.search(r"Проект", c or "", re.I) for c in chunks[:15]) or \
            not any(re.match(r"1\.\s*Площадь участка", c or "") for c in chunks):
        raise ProektError(f"{imya or 'Файл'}: это не проект лесных культур (нет «1. Площадь участка»)")
    p = razobrat_chunks(chunks)
    # План участка — самая большая картинка (рядом бывает миниатюра)
    kart = sorted(doc["kartinki"], key=lambda k: len(k[1]), reverse=True)
    p["_plan"] = kart[0] if kart else None
    p["_fail_imya"] = imya
    if not p.get("kvartal"):
        m = re.search(r"кв\.?\s*(\d+)", imya or "", re.I)
        if m:
            p["kvartal"] = m.group(1)
    return p


# --------------------------------------------------------------------------- #
#   Проверки по нормам
# --------------------------------------------------------------------------- #
def norma_gustoty(p: dict) -> Tuple[Optional[int], str]:
    """Минимальная густота (прил.1) по ТЛУ и материалу главной породы (п.18)."""
    gr = gruppa_tlu(p.get("tlu") or p.get("tip_tlu_t"))
    porody = p.get("porody") or []
    if gr not in NORMA_GUSTOTY or not porody:
        return None, ""
    glav = poroda_kod(p.get("glavnaya_poroda"))
    gx = next((x for x in porody if x["poroda"] == glav), porody[0])
    sn, pm = NORMA_GUSTOTY[gr]
    mat = gx.get("material") or ""
    if re.search(r"саж|СЖ", mat, re.I):
        norma, vid = pm, "саженцы"
    else:
        norma, vid = sn, "сеянцы ОКС"
    if gx.get("zks"):
        norma, vid = round(sn * 0.8), "ЗКС"
    return norma, vid


def proverki(p: dict) -> List[dict]:
    """[{"uroven": "oshibka"/"vnimanie"/"ok", "tekst"}] — по пунктам формы."""
    out: List[dict] = []
    gr = gruppa_tlu(p.get("tlu") or p.get("tip_tlu_t"))
    porody = p.get("porody") or []
    S = p.get("ploshad")
    if not porody:
        out.append({"uroven": "vnimanie", "tekst": "Не разобрано размещение по породам (п.14) — проверки густоты нет"})
        return out
    glav = poroda_kod(p.get("glavnaya_poroda"))
    gx = next((x for x in porody if x["poroda"] == glav), porody[0])
    # 1. Густота по схеме
    for x in porody:
        if x.get("mezhduryade") and x.get("shag"):
            x["na_ga_po_sheme"] = round(10000 / (x["mezhduryade"] * x["shag"]))
    po_sheme = {(x["mezhduryade"], x["shag"]) for x in porody if x.get("mezhduryade")}
    na_ga = sum(x["na_ga"] for x in porody)
    if len(po_sheme) == 1:
        m, s = next(iter(po_sheme))
        teor = 10000 / (m * s)
        if abs(teor - na_ga) / teor > 0.05:
            out.append({"uroven": "vnimanie", "tekst": f"По схеме {m}×{s} м выходит {round(teor)} шт./га, а по породам в сумме {round(na_ga)}"})
    # 2. Минимальная густота по ТЛУ
    if gr in NORMA_GUSTOTY:
        norma, vid = norma_gustoty(p)
        if na_ga < norma:
            out.append({"uroven": "oshibka", "tekst": f"Густота {round(na_ga)} шт./га ниже минимальной {norma} для ТЛУ {p.get('tlu')} ({vid}, прил.1)"})
        else:
            out.append({"uroven": "ok", "tekst": f"Густота {round(na_ga)} шт./га ≥ норматива {norma} для ТЛУ {p.get('tlu')} ({vid}, прил.1)"})
        # 3. Главная порода допустима
        if glav and glav not in GLAVNYE[gr].split():
            out.append({"uroven": "oshibka", "tekst": f"Главная порода «{p.get('glavnaya_poroda')}» не допускается в ТЛУ {p.get('tlu')} (прил.1: {GLAVNYE[gr]})"})
        elif glav == "Б":
            out.append({"uroven": "vnimanie", "tekst": "Берёза главной породой — только в коренных березовых типах или в очагах корневой губки (прил.1)"})
        elif glav == "Д" and gr == "B":
            out.append({"uroven": "vnimanie", "tekst": "Дуб главной в суборях — только прируслово-пойменный тип леса (прил.1)"})
        # 4. Размещение по ТКП
        (m1, m2), (s1, s2), (s1p, s2p) = RAZMESHCHENIE[gr]
        for x in porody:
            m, s = x.get("mezhduryade"), x.get("shag")
            if m and not (m1 <= m <= m2):
                out.append({"uroven": "vnimanie", "tekst": f"{x['poroda']}: междурядье {m} м вне рекомендуемых {m1}–{m2} м (ТКП 667, табл. 6.3)"})
            if s and not (s1 <= s <= max(s2, s2p)):
                out.append({"uroven": "vnimanie", "tekst": f"{x['poroda']}: шаг {s} м вне рекомендуемых {s1}–{max(s2, s2p)} м (ТКП 667, табл. 6.3)"})
    else:
        out.append({"uroven": "vnimanie", "tekst": "ТЛУ не распознан — норматив густоты не проверен"})
    # 5. Арифметика: всего = на 1 га × площадь
    if S:
        for x in porody:
            ozh = x["na_ga"] * S
            if ozh and abs(ozh - x["vsego"]) > max(5, ozh * 0.02):
                out.append({"uroven": "vnimanie", "tekst": f"{x['poroda']}: {x['na_ga']:.0f} шт./га × {S} га = {ozh:.0f}, а в проекте всего {x['vsego']:.0f}"})
        vp = p.get("vydely_ploshad") or []
        if vp:
            summa = round(sum(v["ploshad"] for v in vp), 2)
            if abs(summa - S) > 0.05:
                out.append({"uroven": "vnimanie", "tekst": f"По выделам на плане {summa} га, а площадь участка {S} га"})
            for v in vp:
                if v["ploshad"] == 0:
                    out.append({"uroven": "vnimanie", "tekst": f"Выдел {v['vydel']}: 0.0 га на плане — выдел лишний в проекте?"})
    potr = p.get("potrebnost") or {}
    if potr.get("posadka_tys") and p.get("vsego") and abs(potr["posadka_tys"] * 1000 - p["vsego"]) > 50:
        out.append({"uroven": "vnimanie", "tekst": f"П.22: {potr['posadka_tys']} тыс. шт., а по породам {p['vsego']:.0f} шт."})
    if p.get("kategoriya") == "б" and (p.get("pni_na_ga") or 0) > 500:
        out.append({"uroven": "vnimanie", "tekst": f"Категория «б», но пней {p['pni_na_ga']} шт./га (больше 500 — это «в», ТКП 6.1.1)"})
    if p.get("kategoriya") == "в" and p.get("pni_na_ga") is not None and p["pni_na_ga"] <= 500:
        out.append({"uroven": "vnimanie", "tekst": f"Категория «в», но пней {p['pni_na_ga']} шт./га (до 500 — это «б», ТКП 6.1.1)"})
    return out


def dopuski_tehpriemki(p: dict) -> dict:
    """Что примут на техприёмке (п.56): густота 90–120% проекта, но ≥ норматива;
    междурядье ±15%."""
    na_ga = p.get("na_ga") or 0
    out = {"gustota_min": round(na_ga * 0.9), "gustota_max": round(na_ga * 1.2)}
    norma, _ = norma_gustoty(p)
    if norma:
        out["gustota_min"] = max(out["gustota_min"], norma)
        out["norma"] = norma
    m = next((x["mezhduryade"] for x in (p.get("porody") or []) if x.get("mezhduryade")), None)
    if m:
        out["mezhduryade_min"] = round(m * 0.85, 2)
        out["mezhduryade_max"] = round(m * 1.15, 2)
    return out


# --------------------------------------------------------------------------- #
#   Делянка и ключ
# --------------------------------------------------------------------------- #
def _vydely_set(s) -> List[str]:
    return [v for v in re.split(r"[,;\s]+", str(s or "")) if v]


def klyuch(p: dict) -> str:
    from app.kniga_lvlr import _norm_mesto
    return "|".join([
        _norm_mesto(p.get("lesnichestvo"))[:6], str(p.get("kvartal") or "").strip(),
        ",".join(sorted(_vydely_set(p.get("vydely")), key=lambda v: (len(v), v))),
        str(p.get("god") or ""), str(p.get("sezon") or ""),
    ])


def nayti_delyanku(conn, p: dict) -> Optional[dict]:
    """Делянка с тем же кварталом и пересечением выделов; при дублях —
    с актом освидетельствования, потом с большим совпадением, потом свежая."""
    from app.kniga_lvlr import _sovpadaet
    kv = str(p.get("kvartal") or "").strip()
    vyd = set(_vydely_set(p.get("vydely")))
    if not kv:
        return None
    kand: Dict[int, dict] = {}
    for did, lesn, ivyd, naz in conn.execute(
            "SELECT i.delyanka_id, i.lesnichestvo, i.vydel, d.nazvanie FROM delyanka_item i "
            "JOIN delyanka d ON d.id = i.delyanka_id WHERE TRIM(i.kvartal) = ?", (kv,)).fetchall():
        if not _sovpadaet(lesn, p.get("lesnichestvo")):
            continue
        obshchie = vyd & set(_vydely_set(ivyd))
        if vyd and not obshchie:
            continue
        k = kand.setdefault(did, {"id": did, "nazvanie": naz, "sovp": set()})
        k["sovp"] |= obshchie
    if not kand:
        return None
    akty = {r[0]: r[1] for r in conn.execute(
        "SELECT delyanka_id, MAX(act_date) FROM osvidetelstvovanie_acts GROUP BY delyanka_id").fetchall()}
    luchshe = sorted(kand.values(), key=lambda k: (k["id"] in akty, len(k["sovp"]), k["id"]), reverse=True)
    best = luchshe[0]
    return {"id": best["id"], "nazvanie": best["nazvanie"], "akt": akty.get(best["id"]),
            "drugie": [k["id"] for k in luchshe[1:]]}


# --------------------------------------------------------------------------- #
#   Импорт
# --------------------------------------------------------------------------- #
def _publichno(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


def plan_importa(conn, faily: List[Tuple[str, bytes]]) -> dict:
    ensure(conn)
    stroki = []
    for imya, data in faily:
        try:
            p = razobrat_fail(data, imya)
        except ProektError as exc:
            stroki.append({"fail": imya, "oshibka": str(exc)})
            continue
        k = klyuch(p)
        est = conn.execute("SELECT id, status FROM lk_proekt WHERE klyuch = ? ORDER BY id DESC LIMIT 1", (k,)).fetchone()
        d = nayti_delyanku(conn, p)
        stroki.append({
            "fail": imya, "klyuch": k, "proekt": _publichno(p), "proverki": proverki(p),
            "delyanka": d, "est_id": est[0] if est else None, "est_status": est[1] if est else None,
            "deystvie": ("obnovit" if est and est[1] in ("proekt", "utverzhden") else "propustit") if est else "novyy",
            "_p": p, "_data": data,
        })
    itog = {
        "novyh": sum(1 for s in stroki if s.get("deystvie") == "novyy"),
        "obnovit": sum(1 for s in stroki if s.get("deystvie") == "obnovit"),
        "propustit": sum(1 for s in stroki if s.get("deystvie") == "propustit"),
        "oshibok": sum(1 for s in stroki if s.get("oshibka")),
        "bez_delyanki": sum(1 for s in stroki if not s.get("oshibka") and not s.get("delyanka")),
    }
    return {"itog": itog, "stroki": stroki}


def publichnyy_plan(plan: dict) -> dict:
    return {"itog": plan["itog"], "stroki": [{k: v for k, v in s.items() if not k.startswith("_")} for s in plan["stroki"]]}


_STOLBCY = ("lesnichestvo", "leshoz", "sezon", "god", "kvartal", "vydely", "ploshad", "tlu", "tip_lesa",
            "glavnaya_poroda", "shema_smesheniya", "na_ga", "vsego", "god_perevoda")


def zapisat(conn, p: dict, data: Optional[bytes], imya: str, delyanka_id: Optional[int],
            proekt_id: Optional[int] = None, istochnik: str = "arm") -> int:
    ensure(conn)
    plan = p.get("_plan")
    znach = {c: p.get(c) for c in _STOLBCY}
    polya = json.dumps(_publichno(p), ensure_ascii=False)
    if proekt_id:
        sets = ", ".join(f"{c} = ?" for c in _STOLBCY)
        conn.execute(
            f"UPDATE lk_proekt SET {sets}, polya_json = ?, klyuch = ?, fail_imya = ?, fail_blob = COALESCE(?, fail_blob), "
            "plan_img = COALESCE(?, plan_img), plan_ext = COALESCE(?, plan_ext), "
            "delyanka_id = COALESCE(delyanka_id, ?), updated_at = datetime('now','localtime') WHERE id = ?",
            [*znach.values(), polya, klyuch(p), imya, data, plan[1] if plan else None, plan[0] if plan else None,
             delyanka_id, proekt_id])
        return proekt_id
    cols = ", ".join(_STOLBCY)
    cur = conn.execute(
        f"INSERT INTO lk_proekt ({cols}, polya_json, klyuch, istochnik, fail_imya, fail_blob, plan_img, plan_ext, delyanka_id) "
        f"VALUES ({', '.join('?' * len(_STOLBCY))}, ?, ?, ?, ?, ?, ?, ?, ?)",
        [*znach.values(), polya, klyuch(p), istochnik, imya, data, plan[1] if plan else None,
         plan[0] if plan else None, delyanka_id])
    return cur.lastrowid


def primenit(conn, plan: dict, propustit: List[str], delyanki: Dict[str, Optional[int]]) -> dict:
    sozdano, obnovleno, propushcheno = [], [], []
    for s in plan["stroki"]:
        if s.get("oshibka"):
            continue
        if s["fail"] in propustit or s["deystvie"] == "propustit":
            propushcheno.append(s["fail"])
            continue
        did = delyanki.get(s["fail"], (s.get("delyanka") or {}).get("id"))
        pid = zapisat(conn, s["_p"], s["_data"], s["fail"], did,
                      s["est_id"] if s["deystvie"] == "obnovit" else None)
        (obnovleno if s["deystvie"] == "obnovit" else sozdano).append(pid)
    conn.commit()
    return {"sozdano": sozdano, "obnovleno": obnovleno, "propushcheno": propushcheno}


# --------------------------------------------------------------------------- #
#   Чтение
# --------------------------------------------------------------------------- #
def spisok(conn, god: Optional[int] = None, status: Optional[str] = None) -> List[dict]:
    ensure(conn)
    where, args = [], []
    if god:
        where.append("p.god = ?")
        args.append(god)
    if status:
        where.append("p.status = ?")
        args.append(status)
    q = ("SELECT p.id, p.status, p.sezon, p.god, p.lesnichestvo, p.kvartal, p.vydely, p.ploshad, p.tlu, p.tip_lesa, "
         "p.glavnaya_poroda, p.shema_smesheniya, p.na_ga, p.vsego, p.god_perevoda, p.delyanka_id, d.nazvanie, "
         "p.uchastok_id, p.istochnik, p.fail_imya, p.plan_img IS NOT NULL, p.fail_blob IS NOT NULL, p.polya_json, p.updated_at "
         "FROM lk_proekt p LEFT JOIN delyanka d ON d.id = p.delyanka_id "
         + ("WHERE " + " AND ".join(where) if where else "") + " ORDER BY p.god DESC, p.sezon, CAST(p.kvartal AS INTEGER), p.id")
    out = []
    for r in conn.execute(q, args).fetchall():
        polya = _json(r[22], {})
        out.append({
            "id": r[0], "status": r[1], "status_tekst": STATUSY.get(r[1], r[1]), "sezon": r[2], "god": r[3],
            "lesnichestvo": r[4], "kvartal": r[5], "vydely": r[6], "ploshad": r[7], "tlu": r[8], "tip_lesa": r[9],
            "glavnaya_poroda": r[10], "shema_smesheniya": r[11], "na_ga": r[12], "vsego": r[13], "god_perevoda": r[14],
            "delyanka_id": r[15], "delyanka": r[16], "uchastok_id": r[17], "istochnik": r[18], "fail_imya": r[19],
            "est_plan": bool(r[20]), "est_fail": bool(r[21]), "updated_at": r[23],
            "porody": polya.get("porody") or [],
            "proverki": [x for x in proverki(polya) if x["uroven"] != "ok"],
        })
    return out


def odin(conn, pid: int) -> Optional[dict]:
    ensure(conn)
    cur = conn.execute(
        "SELECT p.*, d.nazvanie AS delyanka FROM lk_proekt p LEFT JOIN delyanka d ON d.id = p.delyanka_id WHERE p.id = ?", (pid,))
    r = cur.fetchone()
    if not r:
        return None
    x = dict(zip([c[0] for c in cur.description], r))
    est_plan, est_fail = x.pop("plan_img") is not None, x.pop("fail_blob") is not None
    x["est_plan"], x["est_fail"] = est_plan, est_fail
    x["polya"] = _json(x.pop("polya_json"), {})
    x["status_tekst"] = STATUSY.get(x["status"], x["status"])
    x["proverki"] = proverki(x["polya"])
    x["dopuski"] = dopuski_tehpriemki(x["polya"])
    return x


def plan_kartinka(conn, pid: int) -> Optional[Tuple[bytes, str]]:
    r = conn.execute("SELECT plan_img, plan_ext FROM lk_proekt WHERE id = ?", (pid,)).fetchone()
    return (r[0], r[1] or "png") if r and r[0] else None


def ishodnyy_fail(conn, pid: int) -> Optional[Tuple[bytes, str]]:
    r = conn.execute("SELECT fail_blob, fail_imya FROM lk_proekt WHERE id = ?", (pid,)).fetchone()
    return (r[0], r[1] or f"proekt_{pid}.doc") if r and r[0] else None


def obnovit(conn, pid: int, status: Optional[str] = None, delyanka_id=..., primechanie: Optional[str] = None) -> dict:
    if status is not None:
        if status not in STATUSY:
            raise ProektError("Неизвестный статус")
        conn.execute("UPDATE lk_proekt SET status = ?, updated_at = datetime('now','localtime') WHERE id = ?", (status, pid))
    if delyanka_id is not ...:
        conn.execute("UPDATE lk_proekt SET delyanka_id = ? WHERE id = ?", (delyanka_id, pid))
    if primechanie is not None:
        conn.execute("UPDATE lk_proekt SET primechanie = ? WHERE id = ?", (primechanie, pid))
    conn.commit()
    return odin(conn, pid)


def udalit(conn, pid: int) -> None:
    conn.execute("DELETE FROM lk_proekt WHERE id = ?", (pid,))
    conn.commit()


def potrebnost(conn, god: Optional[int] = None, sezon: Optional[str] = None) -> dict:
    """Сколько посадочного материала нужно на сезон: порода × вид материала."""
    itog: Dict[Tuple[str, str], dict] = {}
    for x in spisok(conn, god=god):
        if x["status"] == "otmenen" or (sezon and x["sezon"] != sezon):
            continue
        for por in x["porody"]:
            mat = por.get("material") or ""
            key = (por["poroda"], mat)
            t = itog.setdefault(key, {"poroda": por["poroda"], "material": mat, "sht": 0, "proektov": 0, "ga": 0.0})
            t["sht"] += por.get("vsego") or 0
            t["proektov"] += 1
            t["ga"] += x["ploshad"] or 0
    stroki = sorted(itog.values(), key=lambda t: -t["sht"])
    return {"stroki": stroki, "vsego_sht": sum(t["sht"] for t in stroki)}
