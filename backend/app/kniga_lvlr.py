# -*- coding: utf-8 -*-
"""Книга учёта площадей лесовосстановления и лесоразведения (Влад, 09.11.2026).

Форма — приложение 6 к Положению о порядке ЛВ и ЛР (ред. 2024). Бумажная
книга ведётся ручкой, распечатку можно вклеивать. В раскрытой книге слева
часть 1 (графы 1–19), справа часть 2 (графы 20–29), строка идёт поперёк
разворота, на развороте 18 строк по 6 мм.

Строка книги = запись kniga_lvlr. Графы 2–29 хранятся текстом — снимком того,
что попало (или попадёт) на бумагу, поэтому правка делянки задним числом
строку не двигает: вместо этого экран показывает «в делянке теперь другое».
Автозаполнение берёт данные из делянки (билет, МДО, акт освидетельствования,
техкарта), таксации выдела и участка лесных культур (журнал: техприёмка,
перевод, списание).

«На бумаге» (na_bumage_json) — какие значения граф уже вписаны/вклеены в
бумажную книгу; всё, что отличается, попадает в «Перенести на бумагу» с
адресом «разворот N, строка K».
"""
import json
import re
from datetime import date, datetime
from typing import Dict, List, Optional

GRAFY = list(range(2, 30))
CHAST_1 = list(range(1, 20))
CHAST_2 = list(range(20, 30))
STROK_NA_RAZVOROTE = 18

# Ширины граф, см — замеры Влада по его книге (09.11.2026).
SHIRINY_1 = [0.9, 1.25, 2.5, 1, 1.75, 1, 1.5, 1.5, 1.5, 1.25, 1.25, 1.5, 1.25, 1.25, 1.25, 1.5, 1.4, 1.25, 1.2]
SHIRINY_2 = [0.9, 1, 3.9, 4, 4.8, 2, 2, 1.65, 2.8, 3.1]

NASTROYKI_DEFAULT = {
    "nachalo_nomer": 847,      # первый № п/п, который ведёт программа (2026 год)
    "nachalo_razvorot": 1,     # где он стоит в бумажной книге
    "nachalo_stroka": 1,
    "kultury_s_goda": 2026,    # билеты и списания раньше этого года — не предлагать (уже в бумажной книге)
    "shiriny_1": SHIRINY_1,
    "shiriny_2": SHIRINY_2,
    "shrift_pt": 7,
    "nazvanie_lesnichestva": "",
}

# Названия граф (коротко — для экрана и подсказок).
NAZVANIYA = {
    1: "№ п/п",
    2: "Квартал, выдел, участок (лесосека)",
    3: "Вид земель",
    4: "Площадь прогалин, пустырей — ТЛУ",
    5: "№ лесорубочного билета, год рубки",
    6: "Площадь лесосеки, га",
    7: "Состав вырубаемого древостоя",
    8: "Тип леса, ТЛУ",
    9: "Подрост ценных пород: га, тыс. шт/га",
    10: "Вырублено всего, га",
    11: "в т.ч. с сохранением подроста, га",
    12: "Сохранившийся подрост: тыс/га, состав, высота, возраст",
    13: "Оставлено семенников: шт/га, порода",
    14: "Проект: лесные культуры (га, порода)",
    15: "Проект: сохранение подроста",
    16: "Проект: сопутствующее возобновление",
    17: "Проект: ест. возобновление без мер содействия",
    18: "Проект: ест. возобновление с мерами содействия",
    19: "Проект: перевод в другой вид земель",
    20: "ЛК: сезон и год закладки",
    21: "ЛК: площадь, главная порода",
    22: "ЛК: перевод в покрытые лесом (га, порода, документ, дата); при гибели — проект",
    23: "Сохранение подроста: перевод (га, порода, документ, дата)",
    24: "Сопутствующее возобновление: перевод",
    25: "Содействие ЕВ: год работ",
    26: "Содействие ЕВ: метод",
    27: "Содействие ЕВ: площадь, га",
    28: "Содействие ЕВ: переведено (га, порода, документ, дата)",
    29: "Ест. возобновление: перевод в покрытые лесом / другие виды земель",
}
# Что программа умеет подставлять сама (остальное — вручную).
AVTO_GRAFY = {2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 20, 21, 22}

VIDY_ZEMEL = ["вырубка", "гарь", "прогалина", "пустырь", "редина", "погибшие насаждения",
              "погибшие лесные культуры", "несомкнувшиеся культуры", "земли сельхозназначения"]
SPLOSHNYE_KODY = {"СПЛ", "ССР", "РСП", "РР"}
# Какие рубки идут в книгу (Влад, 09.11.2026): все, кроме выборочных — сплошные
# главного пользования, сплошные санитарные, с сохранением подроста,
# реконструкции, постепенные. Рубки ухода, выборочные санитарные и прочие — нет.
# Вид не распознан — тоже предлагаем (с пометкой), пусть решит человек.
V_KNIGU_KODY = SPLOSHNYE_KODY | {"ПСТ"}
VID_SPISANIE = "spisanie"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kniga_lvlr (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nomer INTEGER NOT NULL UNIQUE,
    god INTEGER,
    strok INTEGER NOT NULL DEFAULT 1,
    delyanka_id INTEGER REFERENCES delyanka(id),
    uchastok_id INTEGER REFERENCES lesokultury_uchastok(id),
    grafy_json TEXT NOT NULL DEFAULT '{}',
    na_bumage_json TEXT NOT NULL DEFAULT '{}',
    primechanie TEXT,
    vid TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_kniga_lvlr_delyanka ON kniga_lvlr(delyanka_id);
CREATE INDEX IF NOT EXISTS idx_kniga_lvlr_uchastok ON kniga_lvlr(uchastok_id);
CREATE TABLE IF NOT EXISTS kniga_lvlr_nastroyki (
    klyuch TEXT PRIMARY KEY,
    znachenie TEXT
);
"""

PORODY = [
    ("сосн", "С"), ("ел", "Е"), ("берез", "Б"), ("берёз", "Б"), ("дуб", "Д"), ("ольх", "Олч"),
    ("осин", "Ос"), ("лиственниц", "Лц"), ("клен", "Кл"), ("клён", "Кл"), ("ясен", "Яс"),
    ("липа", "Лп"), ("пихт", "П"), ("граб", "Г"), ("тополь", "Т"), ("кедр", "К"),
]


def ensure(conn) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(kniga_lvlr)").fetchall()}
    if "vid" not in cols:  # строка из списания культур — 'spisanie'
        conn.execute("ALTER TABLE kniga_lvlr ADD COLUMN vid TEXT")


# --------------------------------------------------------------------------- #
#   Мелочи
# --------------------------------------------------------------------------- #
def _num(v) -> Optional[float]:
    s = str(v if v is not None else "").strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        m = re.search(r"\d+(?:\.\d+)?", s)
        return float(m.group()) if m else None


def fmt(v) -> str:
    """3.40 → «3,4»; None → «»."""
    if v is None:
        return ""
    v = round(float(v), 2)
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _d(s) -> Optional[date]:
    s = str(s or "").strip()[:10]
    for f in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def _god(s) -> Optional[int]:
    d = _d(s)
    if d:
        return d.year
    m = re.search(r"(19|20)\d{2}", str(s or ""))
    return int(m.group()) if m else None


def _kd(s) -> str:
    """Дата коротко для узкой графы: 03.10.2026 → 03.10.26."""
    d = _d(s)
    return d.strftime("%d.%m.%y") if d else str(s or "").strip()


def poroda_kratko(p) -> str:
    s = str(p or "").strip()
    if not s:
        return ""
    low = s.lower()
    for kor, kod in PORODY:
        if low.startswith(kor):
            return kod
    return s


def _json(s, default):
    try:
        v = json.loads(s) if s else default
    except ValueError:
        return default
    return v if isinstance(v, type(default)) else default


# --------------------------------------------------------------------------- #
#   Настройки
# --------------------------------------------------------------------------- #
def nastroyki(conn) -> dict:
    ensure(conn)
    out = json.loads(json.dumps(NASTROYKI_DEFAULT))
    for k, v in conn.execute("SELECT klyuch, znachenie FROM kniga_lvlr_nastroyki").fetchall():
        if k in out:
            out[k] = _json(v, out[k]) if isinstance(out[k], list) else (json.loads(v) if v else out[k])
    return out


def sohranit_nastroyki(conn, polya: dict) -> dict:
    tek = nastroyki(conn)
    for k, v in polya.items():
        if k not in NASTROYKI_DEFAULT or v is None:
            continue
        if k in ("shiriny_1", "shiriny_2"):
            nado = len(CHAST_1) if k == "shiriny_1" else len(CHAST_2)
            if not isinstance(v, list) or len(v) != nado or any(_num(x) is None or _num(x) <= 0 for x in v):
                raise ValueError(f"Ширины: нужно {nado} положительных чисел (см)")
            v = [_num(x) for x in v]
        elif k in ("nachalo_nomer", "nachalo_razvorot", "nachalo_stroka", "kultury_s_goda", "shrift_pt"):
            v = int(v)
            if v < 1 or (k == "nachalo_stroka" and v > STROK_NA_RAZVOROTE) or (k == "shrift_pt" and v > 12):
                raise ValueError(f"Недопустимое значение: {k}")
        else:
            v = str(v)
        tek[k] = v
        conn.execute("INSERT OR REPLACE INTO kniga_lvlr_nastroyki(klyuch, znachenie) VALUES (?, ?)",
                     (k, json.dumps(v, ensure_ascii=False)))
    conn.commit()
    return tek


# --------------------------------------------------------------------------- #
#   Источники данных
# --------------------------------------------------------------------------- #
def _vydel(conn, lesnichestvo, kvartal, vydel) -> dict:
    """Таксация выдела (ТЛУ, тип леса, вид земель, целевая порода)."""
    kv = _num(kvartal)
    vyd = str(vydel or "").strip()
    if kv is None or not vyd:
        return {}
    q = ("SELECT v.tlu, v.tip_lesa, v.tip_obekta, v.tselevaya_poroda, v.ploshad, l.name "
         "FROM vydel v JOIN kvartal k ON k.id = v.kvartal_id JOIN lesnichestvo l ON l.id = k.lesnichestvo_id "
         "WHERE k.nomer = ? AND v.nomer = ?")
    try:
        rows = conn.execute(q, (int(kv), vyd)).fetchall()
    except Exception:  # noqa: BLE001 — таксации может не быть в базе
        return {}
    if not rows:
        return {}
    lesn = str(lesnichestvo or "").strip().lower()
    row = next((r for r in rows if lesn and lesn in str(r[5] or "").lower()), rows[0])
    return {"tlu": row[0] or "", "tip_lesa": row[1] or "", "tip_obekta": row[2] or "",
            "tselevaya_poroda": row[3] or "", "ploshad": row[4]}


def _delyanka(conn, did) -> Optional[dict]:
    cur = conn.execute("SELECT * FROM delyanka WHERE id = ?", (did,))
    r = cur.fetchone()
    if not r:
        return None
    d = dict(zip([c[0] for c in cur.description], r))
    cur = conn.execute("SELECT * FROM delyanka_item WHERE delyanka_id = ? ORDER BY poryadok, id", (did,))
    cols = [c[0] for c in cur.description]
    d["items"] = [dict(zip(cols, x)) for x in cur.fetchall()]
    return d


def _akt(conn, did) -> Optional[dict]:
    r = conn.execute("SELECT act_date, data_json FROM osvidetelstvovanie_acts WHERE delyanka_id = ? "
                     "ORDER BY id DESC LIMIT 1", (did,)).fetchone()
    if not r:
        return None
    data = _json(r[1], {})
    data.setdefault("act_date", r[0])
    return data


def _storonnyaya(d) -> dict:
    if not d.get("zagotovka_storonnyaya"):
        return {}
    return _json(d.get("storonnyaya_json"), {})


def vid_rubki_kody(d) -> List[str]:
    from app.vidy import vid_rubki_info
    out = []
    for it in d.get("items") or []:
        kod = vid_rubki_info(it.get("vid_rubki_kod"), it.get("mdo_raw_json"))["vid_rubki_kod"]
        if kod and kod not in out:
            out.append(kod)
    return out


def _mesto_delyanki(d) -> str:
    items = d.get("items") or []
    if not items:
        return d.get("nazvanie") or ""
    po_kv: Dict[str, List[str]] = {}
    lesoseki: List[str] = []
    for it in items:
        kv = str(it.get("kvartal") or "").strip()
        po_kv.setdefault(kv, [])
        for v in re.split(r"[,\s]+", str(it.get("vydel") or "")):
            if v and v not in po_kv[kv]:
                po_kv[kv].append(v)
        ls = str(it.get("lesoseka_nomer") or "").strip()
        if ls and ls not in lesoseki:
            lesoseki.append(ls)
    chasti = [f"кв.{kv} в.{','.join(v)}" if v else f"кв.{kv}" for kv, v in po_kv.items()]
    s = "; ".join(chasti)
    if lesoseki:
        s += " л." + ",".join(lesoseki)
    return s


def _mesto_uchastka(u) -> str:
    vyd = str(u.get("vydel") or "").strip()
    if u.get("podvydel"):
        vyd = f"{vyd}({u['podvydel']})" if vyd else str(u["podvydel"])
    return f"кв.{u.get('kvartal') or ''}" + (f" в.{vyd}" if vyd else "")


def _uchastok(conn, uid) -> Optional[dict]:
    cur = conn.execute("SELECT * FROM lesokultury_uchastok WHERE id = ?", (uid,))
    r = cur.fetchone()
    if not r:
        return None
    u = dict(zip([c[0] for c in cur.description], r))
    cols = ["id", "tip", "data", "sostav_fakt", "primechaniya", "dannye_json"]
    est = {row[1] for row in conn.execute("PRAGMA table_info(lesokultury_meropriyatiya)").fetchall()}
    sel = ", ".join(c if c in est else f"NULL AS {c}" for c in cols)
    u["zhurnal"] = [dict(zip(cols, x)) for x in conn.execute(
        f"SELECT {sel} FROM lesokultury_meropriyatiya WHERE uchastok_id = ? ORDER BY id", (uid,)).fetchall()]
    for m in u["zhurnal"]:
        m["dannye"] = _json(m.pop("dannye_json"), {})
    return u


def _sezon(u) -> str:
    """«весна 2027» — по дате техприёмки (или первой записи журнала)."""
    prm = [m for m in u["zhurnal"] if "приёмк" in (m["tip"] or "").lower() or "приемк" in (m["tip"] or "").lower()]
    d = _d(prm[0]["data"]) if prm else None
    god = d.year if d else _god(u.get("god_sozdaniya"))
    if not god:
        return ""
    if d:
        if 2 <= d.month <= 6:
            return f"весна {god}"
        if 8 <= d.month <= 12:
            return f"осень {god}"
    tekst = str(u.get("god_sozdaniya") or "").lower()
    if "весн" in tekst:
        return f"весна {god}"
    if "осен" in tekst:
        return f"осень {god}"
    return str(god)


def _grafy_kultur(u) -> Dict[int, str]:
    pl = _num(u.get("ploshad"))
    por = poroda_kratko(u.get("glavnaya_poroda"))
    g: Dict[int, str] = {}
    g[20] = _sezon(u)
    g[21] = " ".join(x for x in (fmt(pl), por) if x)
    perevod = [m for m in u["zhurnal"] if (m["tip"] or "").startswith("Перевод в покрытые")]
    spisanie = [m for m in u["zhurnal"] if (m["tip"] or "") == "Списание"]
    if perevod:
        m = perevod[-1]
        t = m["dannye"].get("taksatsiya") or {}
        ppl = _num(t.get("ploshad")) or pl
        sostav = t.get("sostav") or m.get("sostav_fakt") or ""
        dok = m["dannye"].get("kartochka") or ""
        dok = dok.replace("полевая карточка", "карт.").strip()
        g[22] = ", ".join(x for x in (
            " ".join(x for x in (fmt(ppl), sostav.strip() or por) if x),
            dok, _kd(m["data"])) if x)
    elif spisanie:
        m = spisanie[-1]
        d = m["dannye"]
        spl = _num(d.get("ploshad")) or pl
        akt = " ".join(x for x in (f"акт №{d['akt_nomer']}" if d.get("akt_nomer") else "акт",
                                    f"от {_kd(d.get('akt_data') or m['data'])}") if x)
        g[22] = f"списано {fmt(spl)} га, {akt}"
    return {k: v for k, v in g.items() if v}


def avto_iz_delyanki(conn, did) -> Dict[int, str]:
    d = _delyanka(conn, did)
    if d is None:
        return {}
    items = d["items"]
    g: Dict[int, str] = {2: _mesto_delyanki(d)}
    kody = vid_rubki_kody(d)
    if set(kody) & SPLOSHNYE_KODY:
        g[3] = "вырубка"
    akt = _akt(conn, did) or {}
    st = _storonnyaya(d)
    god = _god(d.get("data_lesorubochnogo_bileta")) or _god(akt.get("act_date")) or _god(st.get("spravka_data"))
    bilet = str(d.get("nomer_lesorubochnogo_bileta") or "").strip()
    if bilet or god:
        g[5] = " / ".join(x for x in (f"№{bilet}" if bilet else "", str(god or "")) if x)
    pl = sum(_num(it.get("ploshad")) or 0 for it in items)
    if pl:
        g[6] = fmt(pl)
    sostavy = []
    for it in sorted(items, key=lambda x: -(_num(x.get("ploshad")) or 0)):
        s = str(it.get("sostav") or "").strip()
        if s and s not in sostavy:
            sostavy.append(s)
    if sostavy:
        g[7] = "; ".join(sostavy[:2])
    tl = []
    for it in items:
        tlu = _vydel(conn, it.get("lesnichestvo"), it.get("kvartal"),
                     re.split(r"[,\s]+", str(it.get("vydel") or "").strip())[0]).get("tlu") or ""
        s = " / ".join(x for x in (str(it.get("tip_lesa") or "").strip(), tlu) if x)
        if s and s not in tl:
            tl.append(s)
    if tl:
        g[8] = "; ".join(tl[:2])
    pp, pt = _num(d.get("podrost_ploshad")), _num(d.get("podrost_tys_sht"))
    if pp or pt:
        g[9] = " / ".join((fmt(pp) or "—", fmt(pt) or "—"))
    fakt = _num(akt.get("ploshad_fakt")) or _num(st.get("ploshad_fakt"))
    if fakt:
        g[10] = fmt(fakt)
    # Лесные культуры на месте делянки — графы 14 и 20–22.
    u = privyazannyy_uchastok(conn, did)
    if u:
        uu = _uchastok(conn, u)
        if uu:
            g[14] = " ".join(x for x in (fmt(_num(uu.get("ploshad"))), poroda_kratko(uu.get("glavnaya_poroda"))) if x)
            g.update(_grafy_kultur(uu))
    return {k: v for k, v in g.items() if v}


def avto_iz_uchastka(conn, uid) -> Dict[int, str]:
    u = _uchastok(conn, uid)
    if u is None:
        return {}
    g: Dict[int, str] = {2: _mesto_uchastka(u)}
    t = _vydel(conn, u.get("lesnichestvo"), u.get("kvartal"), u.get("vydel_staryy") or u.get("vydel"))
    kat = str(u.get("kategoriya_ploshadi") or "").strip().lower()
    vid = next((v for v in VIDY_ZEMEL if v.split()[0][:6] in kat), "") if kat else ""
    if not vid and t.get("tip_obekta") and str(t["tip_obekta"]).lower() != "лес":
        vid = str(t["tip_obekta"]).lower()
    if vid:
        g[3] = vid
    tlu = u.get("tlu") or t.get("tlu") or ""
    if vid and vid != "вырубка":
        g[4] = " — ".join(x for x in (fmt(_num(u.get("ploshad"))), tlu) if x)
    g[14] = " ".join(x for x in (fmt(_num(u.get("ploshad"))), poroda_kratko(u.get("glavnaya_poroda"))) if x)
    g.update(_grafy_kultur(u))
    return {k: v for k, v in g.items() if v}


def spisanie_uchastka(u) -> Optional[dict]:
    """Последняя запись «Списание» в журнале участка (или None)."""
    sp = [m for m in u["zhurnal"] if (m["tip"] or "") == "Списание"]
    return sp[-1] if sp else None


def avto_iz_spisaniya(conn, uid) -> Dict[int, str]:
    """Списанные лесные культуры — новая строка книги: участок снова ждёт
    лесовосстановления (вид земель «погибшие лесные культуры»)."""
    u = _uchastok(conn, uid)
    if u is None:
        return {}
    m = spisanie_uchastka(u) or {}
    d = m.get("dannye") or {}
    pl = _num(d.get("ploshad")) or _num(u.get("ploshad"))
    t = _vydel(conn, u.get("lesnichestvo"), u.get("kvartal"), u.get("vydel_staryy") or u.get("vydel"))
    tlu = u.get("tlu") or t.get("tlu") or ""
    g: Dict[int, str] = {2: _mesto_uchastka(u), 3: d.get("vid_zemel") or "погибшие лесные культуры",
                         4: " — ".join(x for x in (fmt(pl), tlu) if x)}
    return {k: v for k, v in g.items() if v}


def privyazannyy_uchastok(conn, did) -> Optional[int]:
    r = conn.execute("SELECT id FROM lesokultury_uchastok WHERE delyanka_id = ? "
                     "AND (status IS NULL OR status != 'удалён') ORDER BY id LIMIT 1", (did,)).fetchone()
    return r[0] if r else None


def avto(conn, z: dict) -> Dict[int, str]:
    """Что программа подставила бы в графы этой строки сейчас."""
    if z.get("vid") == VID_SPISANIE and z.get("uchastok_id"):
        return avto_iz_spisaniya(conn, z["uchastok_id"])
    if z.get("delyanka_id"):
        g = avto_iz_delyanki(conn, z["delyanka_id"])
        if z.get("uchastok_id") and z["uchastok_id"] != privyazannyy_uchastok(conn, z["delyanka_id"]):
            uu = _uchastok(conn, z["uchastok_id"])
            if uu:
                g[14] = " ".join(x for x in (fmt(_num(uu.get("ploshad"))), poroda_kratko(uu.get("glavnaya_poroda"))) if x)
                g.update(_grafy_kultur(uu))
        return g
    if z.get("uchastok_id"):
        return avto_iz_uchastka(conn, z["uchastok_id"])
    return {}


# --------------------------------------------------------------------------- #
#   Записи книги и их адрес на бумаге
# --------------------------------------------------------------------------- #
_COLS = ["id", "nomer", "god", "strok", "delyanka_id", "uchastok_id", "grafy_json", "na_bumage_json",
         "primechanie", "created_at", "updated_at", "vid"]


def _zapis(r) -> dict:
    z = dict(zip(_COLS, r))
    z["grafy"] = {int(k): v for k, v in _json(z.pop("grafy_json"), {}).items()}
    z["na_bumage"] = {int(k): v for k, v in _json(z.pop("na_bumage_json"), {}).items()}
    return z


def zapisi(conn) -> List[dict]:
    ensure(conn)
    rows = [_zapis(r) for r in conn.execute(f"SELECT {', '.join(_COLS)} FROM kniga_lvlr ORDER BY nomer").fetchall()]
    n = nastroyki(conn)
    kursor = (n["nachalo_razvorot"] - 1) * STROK_NA_RAZVOROTE + (n["nachalo_stroka"] - 1)
    for z in rows:
        if z["nomer"] < n["nachalo_nomer"]:
            z["razvorot"] = z["stroka"] = None
            continue
        strok = max(1, min(int(z["strok"] or 1), 3))
        # Запись не переносится через разворот — начинается на следующем.
        if kursor % STROK_NA_RAZVOROTE + strok > STROK_NA_RAZVOROTE:
            kursor += STROK_NA_RAZVOROTE - kursor % STROK_NA_RAZVOROTE
        z["razvorot"] = kursor // STROK_NA_RAZVOROTE + 1
        z["stroka"] = kursor % STROK_NA_RAZVOROTE + 1
        kursor += strok
    return rows


def zapis(conn, zid) -> Optional[dict]:
    return next((z for z in zapisi(conn) if z["id"] == zid), None)


def sleduyushchiy_nomer(conn) -> int:
    ensure(conn)
    n = nastroyki(conn)
    r = conn.execute("SELECT MAX(nomer) FROM kniga_lvlr").fetchone()
    return max((r[0] or 0) + 1, n["nachalo_nomer"])


def sozdat(conn, delyanka_id=None, uchastok_id=None, grafy=None, god=None, vid=None) -> dict:
    ensure(conn)
    if vid == VID_SPISANIE:
        if not uchastok_id:
            raise ValueError("Для списания нужен участок культур")
        if conn.execute("SELECT 1 FROM kniga_lvlr WHERE uchastok_id = ? AND vid = ?", (uchastok_id, vid)).fetchone():
            raise ValueError("Списание этого участка уже есть в книге")
        g = avto_iz_spisaniya(conn, uchastok_id)
        for k, v in (grafy or {}).items():
            if int(k) in GRAFY:
                g[int(k)] = str(v or "").strip()
        nomer = sleduyushchiy_nomer(conn)
        cur = conn.execute(
            "INSERT INTO kniga_lvlr(nomer, god, uchastok_id, vid, grafy_json) VALUES (?, ?, ?, ?, ?)",
            (nomer, god or date.today().year, uchastok_id, vid,
             json.dumps({str(k): v for k, v in g.items() if v}, ensure_ascii=False)))
        conn.commit()
        return zapis(conn, cur.lastrowid)
    if delyanka_id and conn.execute("SELECT 1 FROM kniga_lvlr WHERE delyanka_id = ?", (delyanka_id,)).fetchone():
        raise ValueError("Эта делянка уже есть в книге")
    if uchastok_id and conn.execute("SELECT 1 FROM kniga_lvlr WHERE uchastok_id = ? AND COALESCE(vid, '') != ?",
                                    (uchastok_id, VID_SPISANIE)).fetchone():
        raise ValueError("Этот участок культур уже есть в книге")
    g = {}
    if delyanka_id or uchastok_id:
        g = avto(conn, {"delyanka_id": delyanka_id, "uchastok_id": uchastok_id})
        if delyanka_id and not uchastok_id:
            uchastok_id = privyazannyy_uchastok(conn, delyanka_id)
    for k, v in (grafy or {}).items():
        k = int(k)
        if k in GRAFY:
            g[k] = str(v or "").strip()
    nomer = sleduyushchiy_nomer(conn)
    cur = conn.execute(
        "INSERT INTO kniga_lvlr(nomer, god, delyanka_id, uchastok_id, grafy_json) VALUES (?, ?, ?, ?, ?)",
        (nomer, god or date.today().year, delyanka_id, uchastok_id,
         json.dumps({str(k): v for k, v in g.items() if v}, ensure_ascii=False)))
    conn.commit()
    return zapis(conn, cur.lastrowid)


def obnovit(conn, zid, grafy=None, strok=None, primechanie=None, uchastok_id=...) -> dict:
    z = zapis(conn, zid)
    if z is None:
        raise KeyError(zid)
    g = dict(z["grafy"])
    for k, v in (grafy or {}).items():
        k = int(k)
        if k not in GRAFY:
            continue
        v = str(v or "").strip()
        if v:
            g[k] = v
        else:
            g.pop(k, None)
    sets, params = ["grafy_json = ?", "updated_at = datetime('now', 'localtime')"], \
        [json.dumps({str(k): v for k, v in g.items()}, ensure_ascii=False)]
    if strok is not None:
        sets.append("strok = ?")
        params.append(max(1, min(int(strok), 3)))
    if primechanie is not None:
        sets.append("primechanie = ?")
        params.append(primechanie)
    if uchastok_id is not ...:
        if uchastok_id and conn.execute("SELECT 1 FROM kniga_lvlr WHERE uchastok_id = ? AND id != ? "
                                        "AND COALESCE(vid, '') != ?", (uchastok_id, zid, VID_SPISANIE)).fetchone():
            raise ValueError("Этот участок культур уже привязан к другой строке книги")
        sets.append("uchastok_id = ?")
        params.append(uchastok_id)
    conn.execute(f"UPDATE kniga_lvlr SET {', '.join(sets)} WHERE id = ?", (*params, zid))
    conn.commit()
    return zapis(conn, zid)


def otmetit_na_bumage(conn, zid, grafy: Optional[List[int]] = None) -> dict:
    """Вписал/вклеил: запомнить текущие значения граф (все или выбранные)."""
    z = zapis(conn, zid)
    if z is None:
        raise KeyError(zid)
    nb = dict(z["na_bumage"])
    for k in (grafy or GRAFY):
        if k in z["grafy"]:
            nb[k] = z["grafy"][k]
        else:
            nb.pop(k, None)
    conn.execute("UPDATE kniga_lvlr SET na_bumage_json = ? WHERE id = ?",
                 (json.dumps({str(k): v for k, v in nb.items()}, ensure_ascii=False), zid))
    conn.commit()
    return zapis(conn, zid)


def udalit(conn, zid) -> None:
    """Удалить можно только последнюю строку — иначе поедет нумерация книги."""
    z = zapis(conn, zid)
    if z is None:
        raise KeyError(zid)
    mx = conn.execute("SELECT MAX(nomer) FROM kniga_lvlr").fetchone()[0]
    if z["nomer"] != mx:
        raise ValueError("Удалить можно только последнюю запись книги — иначе поедут номера. "
                         "Ошибочную строку лучше исправить.")
    conn.execute("DELETE FROM kniga_lvlr WHERE id = ?", (zid,))
    conn.commit()


def ne_na_bumage(z: dict) -> List[int]:
    """Графы, где значение в программе отличается от вписанного на бумагу."""
    return [k for k in GRAFY if (z["grafy"].get(k) or "") != (z["na_bumage"].get(k) or "")]


# --------------------------------------------------------------------------- #
#   «Что вписать»
# --------------------------------------------------------------------------- #
def chto_vpisat(conn, vse_rubki: bool = False) -> dict:
    ensure(conn)
    n = nastroyki(conn)
    vse = zapisi(conn)
    v_knige_d = {z["delyanka_id"] for z in vse if z["delyanka_id"]}
    v_knige_u = {z["uchastok_id"] for z in vse if z["uchastok_id"]}

    # 1) Делянки — как только выписан лесорубочный билет (и свои, и сторонние);
    #    акт освидетельствования потом сам попадёт в «дописать» (гр. 10).
    novye = []
    s_goda = n["kultury_s_goda"]
    for did, bilet, data_b, status in conn.execute(
            "SELECT id, nomer_lesorubochnogo_bileta, data_lesorubochnogo_bileta, status FROM delyanka "
            "WHERE TRIM(COALESCE(nomer_lesorubochnogo_bileta, '')) != ''").fetchall():
        if did in v_knige_d or status == "удалена":
            continue
        god_b = _god(data_b)
        if god_b and god_b < s_goda:
            continue
        d = _delyanka(conn, did)
        if d is None:
            continue
        kody = vid_rubki_kody(d)
        v_knigu = bool(set(kody) & V_KNIGU_KODY)
        neizvesten = not kody
        if not (v_knigu or neizvesten or vse_rubki):
            continue
        akt = _akt(conn, did) or {}
        g = avto_iz_delyanki(conn, did)
        novye.append({"tip": "delyanka", "delyanka_id": did, "mesto": g.get(2) or d.get("nazvanie"),
                      "akt_data": akt.get("act_date") or "", "bilet": f"№{bilet} от {data_b}" if data_b else f"№{bilet}",
                      "sploshnaya": v_knigu, "vid_neizvesten": neizvesten,
                      "storonnyaya": bool(d.get("zagotovka_storonnyaya")),
                      "vid_rubki": ", ".join(kody), "grafy": g})
    # 2) Списанные лесные культуры (созданные культуры отдельной строкой не вносятся).
    spisany = {z["uchastok_id"] for z in vse if z.get("vid") == VID_SPISANIE}
    for (uid,) in conn.execute("SELECT DISTINCT uchastok_id FROM lesokultury_meropriyatiya WHERE tip = 'Списание'").fetchall():
        if uid in spisany:
            continue
        u = _uchastok(conn, uid)
        if u is None:
            continue
        m = spisanie_uchastka(u) or {}
        god_s = _god((m.get("dannye") or {}).get("akt_data")) or _god(m.get("data"))
        if god_s and god_s < s_goda:
            continue
        g = avto_iz_spisaniya(conn, uid)
        novye.append({"tip": "spisanie", "uchastok_id": uid, "delyanka_id": u.get("delyanka_id"), "mesto": g.get(2),
                      "akt_data": _kd(m.get("data")), "sploshnaya": False, "vid_rubki": "", "grafy": g})

    # 3) В строках книги: программа знает больше, чем записано (пусто → есть).
    dopisat, rashozhdeniya, na_bumagu = [], [], []
    for z in vse:
        a = avto(conn, z)
        for k, v in a.items():
            tek = z["grafy"].get(k) or ""
            if not tek:
                dopisat.append({"id": z["id"], "nomer": z["nomer"], "razvorot": z["razvorot"], "stroka": z["stroka"],
                                "grafa": k, "nazvanie": NAZVANIYA[k], "znachenie": v})
            elif tek != v and k not in (2,):
                rashozhdeniya.append({"id": z["id"], "nomer": z["nomer"], "grafa": k, "nazvanie": NAZVANIYA[k],
                                      "v_knige": tek, "seychas": v})
        raz = ne_na_bumage(z)
        if raz:
            na_bumagu.append({"id": z["id"], "nomer": z["nomer"], "razvorot": z["razvorot"], "stroka": z["stroka"],
                              "mesto": z["grafy"].get(2) or "", "vsya": not z["na_bumage"],
                              "grafy": [{"grafa": k, "znachenie": z["grafy"].get(k) or "",
                                         "bylo": z["na_bumage"].get(k) or ""} for k in raz]})
    return {"novye": novye, "dopisat": dopisat, "rashozhdeniya": rashozhdeniya, "na_bumagu": na_bumagu,
            "sleduyushchiy_nomer": sleduyushchiy_nomer(conn)}
