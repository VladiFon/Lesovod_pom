# -*- coding: utf-8 -*-
"""Помощник путевых листов (просьба Влада 09.11.2026).

Путевые листы пишутся РУКОЙ — программа не печатает, а подсказывает, что
вписать: вводится только пробег за день и заправка, остальное тянется
цепочкой с прошлого листа той же машины:

    спидометр при выезде   = спидометр при возвращении прошлого листа
    спидометр при возврате = выезд + пробег
    остаток при выезде     = остаток при возвращении прошлого листа + заправка
    расход                 = пробег × норма (л/км, у УАЗа 0,1392)
    остаток при возврате   = остаток при выезде − расход

Первый лист машины берёт стартовые показания из её карточки
(tehnika.start_spidometr / start_ostatok). Норма — с историей
(tehnika_norma: «с какой даты»), поэтому смена нормы в декабре не
переписывает ноябрьские листы. Если показание реально другое (заменили
спидометр, слили топливо), у листа можно «прибить» выезд руками —
spid_vyezd_fix / ost_vyezd_fix, дальше цепочка пойдёт от него.

«Заполнить месяц» (generator_mesyaca) раскладывает пробег и заправки по
рабочим дням 5/2 (минус праздники РБ и отпуск/больничный водителя по
табелю), чтобы суммы сошлись до километра и литра, а бак не уходил в минус.

Закрытый месяц (сдан в бухгалтерию) не пересчитывается и не правится.
"""
import random
from datetime import date, timedelta

from app.routers import smena

SCHEMA = """
CREATE TABLE IF NOT EXISTS tehnika_norma (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tehnika_id INTEGER NOT NULL REFERENCES tehnika(id),
    s_daty TEXT NOT NULL,
    norma REAL NOT NULL,
    kommentariy TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(tehnika_id, s_daty)
);
CREATE TABLE IF NOT EXISTS putevoy_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tehnika_id INTEGER NOT NULL REFERENCES tehnika(id),
    data TEXT NOT NULL,
    nomer INTEGER,
    sotrudnik_id INTEGER REFERENCES sotrudniki(id),
    probeg REAL NOT NULL DEFAULT 0,
    zapravka REAL NOT NULL DEFAULT 0,
    spid_vyezd_fix REAL,
    ost_vyezd_fix REAL,
    spid_vyezd REAL,
    spid_vozvrat REAL,
    ost_vyezd REAL,
    norma REAL,
    rashod REAL,
    ost_vozvrat REAL,
    vremya_vyezd TEXT,
    vremya_vozvrat TEXT,
    marshrut TEXT,
    kommentariy TEXT,
    istochnik TEXT NOT NULL DEFAULT 'ruchnoy',
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(tehnika_id, data)
);
CREATE INDEX IF NOT EXISTS idx_putevoy_list_data ON putevoy_list(data);
CREATE TABLE IF NOT EXISTS putevoy_mesyac (
    tehnika_id INTEGER NOT NULL REFERENCES tehnika(id),
    mesyac TEXT NOT NULL,
    zakryt INTEGER NOT NULL DEFAULT 0,
    zakryt_at TEXT,
    PRIMARY KEY (tehnika_id, mesyac)
);
"""

# Поля карточки машины, нужные путевым (добавляются к tehnika из smena.py).
TEHNIKA_KOLONKI = (
    ("marka", "TEXT"),
    ("edinica", "TEXT"),          # 'км' | 'моточас'
    ("bak_l", "REAL"),            # объём бака, л
    ("start_data", "TEXT"),       # с какого дня ведём путевые
    ("start_spidometr", "REAL"),
    ("start_ostatok", "REAL"),
    ("vremya_vyezd", "TEXT"),     # по умолчанию для «Заполнить месяц»
    ("vremya_vozvrat", "TEXT"),
    ("marshrut", "TEXT"),
)
EDINICY = ("км", "моточас")
MAX_PROBEG = 3000          # км/моточасов за день — защита от лишнего нуля
MAX_ZAPRAVKA = 2000        # л за день


def ensure(conn):
    smena.ensure(conn)
    conn.executescript(SCHEMA)
    est = {r[1] for r in conn.execute("PRAGMA table_info(tehnika)").fetchall()}
    for kol, tip in TEHNIKA_KOLONKI:
        if kol not in est:
            conn.execute(f"ALTER TABLE tehnika ADD COLUMN {kol} {tip}")


def r2(v):
    return round((v or 0) + 1e-9, 2) if v is not None else None


def _d(s):
    return date.fromisoformat(str(s)[:10])


def mesyac_granicy(mesyac):
    """'2026-11' → (date(2026,11,1), date(2026,11,30))."""
    g, m = (int(x) for x in mesyac.split("-")[:2])
    ot = date(g, m, 1)
    do = (date(g + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    return ot, do


# ------------------------------------------------------------ календарь ---

# Государственные праздники Республики Беларусь — нерабочие дни. В РБ
# праздник, выпавший на выходной, НЕ переносится на понедельник; переносы
# рабочих дней (рабочие субботы) — постановлением Совмина на каждый год,
# их Влад отмечает галочками в окне «Заполнить месяц».
PRAZDNIKI_RB = {(1, 1): "Новый год", (1, 2): "Новый год", (1, 7): "Рождество (правосл.)",
                (3, 8): "День женщин", (5, 1): "Праздник труда", (5, 9): "День Победы",
                (7, 3): "День Независимости", (11, 7): "День Октябрьской революции",
                (12, 25): "Рождество (катол.)"}


def pravoslavnaya_pasha(god):
    """Православная Пасха (григорианская дата), алгоритм Гаусса/Меёса."""
    a, b, c = god % 4, god % 7, god % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    mes = (d + e + 114) // 31
    den = (d + e + 114) % 31 + 1
    return date(god, mes, den) + timedelta(days=13)  # юлианская → григорианская (1900–2099)


def prazdnik(d):
    """Название праздника РБ или None. Радуница — 9-й день после Пасхи (вторник)."""
    if (d.month, d.day) in PRAZDNIKI_RB:
        return PRAZDNIKI_RB[(d.month, d.day)]
    if d == pravoslavnaya_pasha(d.year) + timedelta(days=9):
        return "Радуница"
    return None


def otsutstviya(conn, sotrudnik_id, ot, do):
    """{дата: статус} отпуск/больничный/не работал водителя по табелю."""
    if not sotrudnik_id:
        return {}
    try:
        rows = conn.execute(
            "SELECT data, status FROM tabel_zapis WHERE sotrudnik_id=? AND data>=? AND data<=? "
            "AND status IN ('отпуск','больничный','не работал')",
            (sotrudnik_id, ot.isoformat(), do.isoformat())).fetchall()
    except Exception:  # таблицы табеля ещё нет на пустой базе
        return {}
    return {r[0]: r[1] for r in rows}


def dni_mesyaca(conn, mesyac, sotrudnik_id=None):
    """Все дни месяца с пометкой: рабочий по 5/2 или почему нет."""
    ot, do = mesyac_granicy(mesyac)
    ots = otsutstviya(conn, sotrudnik_id, ot, do)
    out, d = [], ot
    while d <= do:
        pr = prazdnik(d)
        prichina = ("выходной" if d.weekday() >= 5 else None) or (f"праздник: {pr}" if pr else None) \
            or (f"по табелю: {ots[d.isoformat()]}" if d.isoformat() in ots else None)
        out.append({"data": d.isoformat(), "den_nedeli": d.weekday(), "rabochiy": prichina is None,
                    "prichina": prichina})
        d += timedelta(days=1)
    return out


# ------------------------------------------------------------- нормы ---

def normy(conn, tid):
    return [{"id": r[0], "s_daty": r[1], "norma": r[2], "kommentariy": r[3]} for r in conn.execute(
        "SELECT id, s_daty, norma, kommentariy FROM tehnika_norma WHERE tehnika_id=? ORDER BY s_daty",
        (tid,)).fetchall()]


def norma_na(spisok_norm, data):
    """Норма, действующая на дату (последняя с s_daty ≤ data); None — не задана."""
    n = None
    for x in spisok_norm:
        if x["s_daty"] <= data:
            n = x["norma"]
    if n is None and spisok_norm:
        # Листы раньше первой нормы — считаем по первой (иначе расход 0).
        n = spisok_norm[0]["norma"]
    return n


# ---------------------------------------------------------- цепочка ---

def mashina(conn, tid):
    r = conn.execute(
        "SELECT id, nazvanie, tip, nomer, toplivo, zakreplen_sotrudnik_id, marka, edinica, bak_l, start_data, "
        "start_spidometr, start_ostatok, vremya_vyezd, vremya_vozvrat, marshrut, aktivna FROM tehnika WHERE id=?",
        (tid,)).fetchone()
    if not r:
        return None
    k = ("id", "nazvanie", "tip", "nomer", "toplivo", "zakreplen_sotrudnik_id", "marka", "edinica", "bak_l",
         "start_data", "start_spidometr", "start_ostatok", "vremya_vyezd", "vremya_vozvrat", "marshrut", "aktivna")
    m = dict(zip(k, r))
    m["edinica"] = m["edinica"] or "км"
    return m


def zakrytye_mesyacy(conn, tid):
    return {r[0] for r in conn.execute(
        "SELECT mesyac FROM putevoy_mesyac WHERE tehnika_id=? AND zakryt=1", (tid,)).fetchall()}


def posledniy_zakrytyy(conn, tid):
    z = zakrytye_mesyacy(conn, tid)
    return max(z) if z else None


def mozhno_pravit(conn, tid, data):
    """Лист на эту дату можно менять, если ни его месяц, ни более поздний не закрыт."""
    pz = posledniy_zakrytyy(conn, tid)
    return pz is None or data[:7] > pz


def _start(m):
    return (m["start_spidometr"] or 0.0, m["start_ostatok"] or 0.0)


def pereschitat(conn, tid, s_daty=None):
    """Пересчитать цепочку машины начиная с листа на s_daty (или со всех
    открытых). Закрытые месяцы не трогаем — они точка опоры."""
    m = mashina(conn, tid)
    if not m:
        return 0
    nm = normy(conn, tid)
    pz = posledniy_zakrytyy(conn, tid)
    granica = s_daty or "0000-00-00"
    if pz and granica <= pz + "-31":
        granica = pz + "-32"  # строго после закрытого месяца
    prev = conn.execute(
        "SELECT spid_vozvrat, ost_vozvrat FROM putevoy_list WHERE tehnika_id=? AND data<? ORDER BY data DESC LIMIT 1",
        (tid, granica)).fetchone()
    spid, ost = (prev[0] or 0.0, prev[1] or 0.0) if prev else _start(m)
    n = 0
    for lid, data, probeg, zapr, sfix, ofix in conn.execute(
            "SELECT id, data, probeg, zapravka, spid_vyezd_fix, ost_vyezd_fix FROM putevoy_list "
            "WHERE tehnika_id=? AND data>=? ORDER BY data", (tid, granica)).fetchall():
        sv = sfix if sfix is not None else spid
        ov = r2((ofix if ofix is not None else ost) + (zapr or 0))
        nr = norma_na(nm, data)
        ras = r2((probeg or 0) * (nr or 0))
        spid, ost = r2(sv + (probeg or 0)), r2(ov - ras)
        conn.execute("UPDATE putevoy_list SET spid_vyezd=?, spid_vozvrat=?, ost_vyezd=?, norma=?, rashod=?, "
                     "ost_vozvrat=?, updated_at=datetime('now','localtime') WHERE id=?",
                     (r2(sv), spid, ov, nr, ras, ost, lid))
        n += 1
    return n


def sleduyushchiy_nomer(conn, god):
    r = conn.execute("SELECT MAX(nomer) FROM putevoy_list WHERE substr(data,1,4)=?", (str(god),)).fetchone()
    return (r[0] or 0) + 1


LIST_POLYA = ("id", "tehnika_id", "data", "nomer", "sotrudnik_id", "probeg", "zapravka", "spid_vyezd_fix",
              "ost_vyezd_fix", "spid_vyezd", "spid_vozvrat", "ost_vyezd", "norma", "rashod", "ost_vozvrat",
              "vremya_vyezd", "vremya_vozvrat", "marshrut", "kommentariy", "istochnik")


def listy(conn, tid, ot, do):
    rows = conn.execute(
        f"SELECT {', '.join('p.' + k for k in LIST_POLYA)}, s.fio FROM putevoy_list p "
        "LEFT JOIN sotrudniki s ON s.id=p.sotrudnik_id WHERE p.tehnika_id=? AND p.data>=? AND p.data<=? "
        "ORDER BY p.data", (tid, ot, do)).fetchall()
    return [dict(zip(LIST_POLYA + ("fio",), r)) for r in rows]


def smena_po_dnyam(conn, tid, ot, do):
    """Что водители написали в «Отчёте за смену» с телефона по этой машине."""
    return {r[0]: {"zapravka": r2(r[1]), "rashod": r2(r[2]), "kto": r[3]} for r in conn.execute(
        "SELECT o.data, SUM(COALESCE(o.zapravka,0)), SUM(COALESCE(o.toplivo_rashod,0)), GROUP_CONCAT(DISTINCT s.fio) "
        "FROM otchet_smeny o JOIN sotrudniki s ON s.id=o.sotrudnik_id "
        "WHERE o.deleted=0 AND o.tehnika_id=? AND o.data>=? AND o.data<=? GROUP BY o.data", (tid, ot, do)).fetchall()}


def preduprezhdeniya(lst, m, ots, sm):
    """Подсказки к листу: минус в баке, перелив, отпуск, расхождение с телефоном."""
    out = []
    if (lst["ost_vozvrat"] or 0) < 0:
        out.append({"ton": "danger", "text": f"в баке минус {abs(lst['ost_vozvrat']):g} л — не хватает заправки"})
    if m.get("bak_l") and (lst["ost_vyezd"] or 0) > m["bak_l"] + 0.01:
        out.append({"ton": "danger", "text": f"при выезде {lst['ost_vyezd']:g} л, а бак {m['bak_l']:g} л — не влезет"})
    if lst["norma"] is None and (lst["probeg"] or 0) > 0:
        out.append({"ton": "warn", "text": "не задана норма расхода — расход 0"})
    if lst["data"] in ots:
        out.append({"ton": "warn", "text": f"водитель по табелю: {ots[lst['data']]}"})
    s = sm.get(lst["data"])
    if s and s["zapravka"] and abs((s["zapravka"] or 0) - (lst["zapravka"] or 0)) > 0.01:
        out.append({"ton": "info", "text": f"в отчёте за смену заправка {s['zapravka']:g} л ({s['kto']})",
                    "zapravka_iz_smeny": s["zapravka"]})
    return out


def itogi(lst_list, nachalo_ost=None, nachalo_spid=None):
    if not lst_list:
        return {"listov": 0, "probeg": 0, "zapravka": 0, "rashod": 0, "ost_nachalo": nachalo_ost,
                "ost_konec": nachalo_ost, "spid_nachalo": nachalo_spid, "spid_konec": nachalo_spid}
    p, l = lst_list[0], lst_list[-1]
    return {"listov": len(lst_list),
            "probeg": r2(sum(x["probeg"] or 0 for x in lst_list)),
            "zapravka": r2(sum(x["zapravka"] or 0 for x in lst_list)),
            "rashod": r2(sum(x["rashod"] or 0 for x in lst_list)),
            "ost_nachalo": r2((p["ost_vyezd"] or 0) - (p["zapravka"] or 0)),
            "ost_konec": l["ost_vozvrat"],
            "spid_nachalo": p["spid_vyezd"], "spid_konec": l["spid_vozvrat"]}


def nachalo_mesyaca(conn, tid, ot, m):
    prev = conn.execute("SELECT spid_vozvrat, ost_vozvrat FROM putevoy_list WHERE tehnika_id=? AND data<? "
                        "ORDER BY data DESC LIMIT 1", (tid, ot.isoformat())).fetchone()
    return (prev[0], prev[1]) if prev else _start(m)


def mesyac_mashiny(conn, tid, mesyac):
    m = mashina(conn, tid)
    ot, do = mesyac_granicy(mesyac)
    ll = listy(conn, tid, ot.isoformat(), do.isoformat())
    ots = otsutstviya(conn, m["zakreplen_sotrudnik_id"], ot, do)
    for x in ll:
        ots_x = otsutstviya(conn, x["sotrudnik_id"], ot, do) if x["sotrudnik_id"] != m["zakreplen_sotrudnik_id"] else ots
        x["preduprezhdeniya"] = preduprezhdeniya(x, m, ots_x, {})
    sm = smena_po_dnyam(conn, tid, ot.isoformat(), do.isoformat())
    for x in ll:
        x["preduprezhdeniya"] += [p for p in preduprezhdeniya(x, m, {}, sm) if p["ton"] == "info"]
    spid0, ost0 = nachalo_mesyaca(conn, tid, ot, m)
    it = itogi(ll, ost0, spid0)
    it["smena_zapravka"] = r2(sum(v["zapravka"] or 0 for v in sm.values()))
    it["smena_rashod"] = r2(sum(v["rashod"] or 0 for v in sm.values()))
    zakryt = mesyac in zakrytye_mesyacy(conn, tid)
    return {"mashina": m, "mesyac": mesyac, "zakryt": zakryt,
            "mozhno_pravit": mozhno_pravit(conn, tid, ot.isoformat()),
            "listy": ll, "itogi": it, "dni": dni_mesyaca(conn, mesyac, m["zakreplen_sotrudnik_id"]),
            "smena": sm, "normy": normy(conn, tid)}


# ------------------------------------------------------ «Заполнить месяц» ---

def raskidat_probeg(vsego, n, razbros, rng):
    """vsego целых км на n дней с разбросом ±razbros (доля), сумма — ровно vsego."""
    if n <= 0:
        return []
    vsego = int(round(vsego))
    ves = [1 + (rng.uniform(-razbros, razbros) if razbros else 0) for _ in range(n)]
    s = sum(ves)
    syroe = [vsego * w / s for w in ves]
    cel = [int(x) for x in syroe]
    ost = vsego - sum(cel)
    for i in sorted(range(n), key=lambda i: syroe[i] - cel[i], reverse=True)[:ost]:
        cel[i] += 1
    return cel


class GenOshibka(ValueError):
    pass


def generator_mesyaca(conn, tid, mesyac, *, dni=None, sotrudnik_id=None, probeg_vsego=None, km_v_den=None,
                      razbros=0.1, zapravki="vsego", litrov_vsego=None, raz=None, po_datam=None,
                      porog=0.25, vremya_vyezd=None, vremya_vozvrat=None, marshrut=None, seed=None):
    """Черновик месяца (ничего не пишет). Возвращает строки и итоги.

    dni — список ISO-дат, когда машина работала (из галочек окна); по
    умолчанию — рабочие дни 5/2 без праздников и отсутствий водителя.
    Дни, где уже есть лист, внесённый руками, остаются как есть: их пробег
    и заправка вычитаются из итогов месяца.
    zapravki: 'vsego' (litrov_vsego за raz заправок), 'po_datam' ({дата: л}),
    'avto' (доливать до полного, когда к вечеру в баке меньше porog×бак),
    'net' (без заправок)."""
    m = mashina(conn, tid)
    if not m:
        raise GenOshibka("Машина не найдена")
    ot, do = mesyac_granicy(mesyac)
    if not mozhno_pravit(conn, tid, ot.isoformat()):
        raise GenOshibka("Месяц (или более поздний) закрыт — сначала откройте его")
    sid = sotrudnik_id or m["zakreplen_sotrudnik_id"]
    if dni is None:
        dni = [x["data"] for x in dni_mesyaca(conn, mesyac, sid) if x["rabochiy"]]
    dni = sorted({d for d in dni if ot.isoformat() <= d <= do.isoformat()})
    ruchnye = {x["data"]: x for x in listy(conn, tid, ot.isoformat(), do.isoformat()) if x["istochnik"] == "ruchnoy"}
    svobodnye = [d for d in dni if d not in ruchnye]
    n = len(svobodnye)
    if probeg_vsego is None:
        probeg_vsego = (km_v_den or 0) * n + sum(x["probeg"] or 0 for x in ruchnye.values())
    ostaetsya_km = max(0, float(probeg_vsego) - sum(x["probeg"] or 0 for x in ruchnye.values()))
    rng = random.Random(seed if seed is not None else f"{tid}:{mesyac}")
    km = raskidat_probeg(ostaetsya_km, n, max(0.0, min(0.5, razbros or 0)), rng)
    nm = normy(conn, tid)
    if not nm:
        raise GenOshibka("У машины не задана норма расхода — впишите её в карточке машины")

    # Строки месяца (ручные + новые) по датам.
    stroki = []
    for d in sorted(set(svobodnye) | set(ruchnye)):
        if d in ruchnye:
            x = ruchnye[d]
            stroki.append({"data": d, "probeg": x["probeg"] or 0, "zapravka": x["zapravka"] or 0, "ruchnoy": True,
                           "spid_vyezd_fix": x["spid_vyezd_fix"], "ost_vyezd_fix": x["ost_vyezd_fix"]})
        else:
            stroki.append({"data": d, "probeg": km[svobodnye.index(d)], "zapravka": 0.0, "ruchnoy": False,
                           "spid_vyezd_fix": None, "ost_vyezd_fix": None})
    for s in stroki:
        s["norma"] = norma_na(nm, s["data"])
        s["rashod"] = r2(s["probeg"] * (s["norma"] or 0))

    spid0, ost0 = nachalo_mesyaca(conn, tid, ot, m)
    bak = m["bak_l"]
    svob_idx = [i for i, s in enumerate(stroki) if not s["ruchnoy"]]
    preduprezhdeniya_gen = []

    if zapravki == "po_datam":
        for d, litr in (po_datam or {}).items():
            for s in stroki:
                if s["data"] == d and not s["ruchnoy"]:
                    s["zapravka"] = r2(float(litr))
    elif zapravki == "vsego" and litrov_vsego and svob_idx:
        litrov_vsego = float(litrov_vsego) - sum(s["zapravka"] for s in stroki if s["ruchnoy"])
        k = max(1, min(int(raz or 1), len(svob_idx)))
        porcii = [float(int(litrov_vsego // k))] * k
        porcii[-1] = r2(litrov_vsego - sum(porcii[:-1]))
        # Равномерно по месяцу, затем сдвигаем раньше, если бак уходит в минус.
        plan = [svob_idx[min(len(svob_idx) - 1, int(j * len(svob_idx) / k))] for j in range(k)]
        for _ in range(len(stroki) * k + 1):
            ost, sdvig = ost0, False
            zapr = {}
            for p_i, i in enumerate(plan):
                zapr.setdefault(i, 0.0)
                zapr[i] += porcii[p_i]
            for i, s in enumerate(stroki):
                ost = ost + (s["zapravka"] if s["ruchnoy"] else zapr.get(i, 0.0)) - s["rashod"]
                if ost < -0.001:
                    # ближайшую будущую заправку переносим на этот (или ближайший свободный до него) день
                    budushchie = [p for p, ii in enumerate(plan) if ii > i]
                    kuda = max([ii for ii in svob_idx if ii <= i], default=None)
                    if budushchie and kuda is not None:
                        plan[budushchie[0]] = kuda
                        plan.sort()
                        sdvig = True
                    break
            if not sdvig:
                break
        for i in svob_idx:
            stroki[i]["zapravka"] = 0.0
        if bak:
            # Есть бак — заправляем, когда порция влезает и к вечеру в баке
            # было бы меньше четверти; оставшиеся порции не копим к концу:
            # если порций осталось столько же, сколько свободных дней, — льём.
            if max(porcii) > bak:
                preduprezhdeniya_gen.append(f"заправка по {max(porcii):g} л больше бака {bak:g} л — увеличьте число заправок "
                                            f"(нужно хотя бы {int(-(-litrov_vsego // bak))})")
            ost, ostalos = ost0, list(porcii)
            for i, s in enumerate(stroki):
                if not s["ruchnoy"] and ostalos:
                    dney_ostalos = sum(1 for ii in svob_idx if ii >= i)
                    vlezet = ost + ostalos[0] <= bak + 0.001
                    nado = ost - s["rashod"] < bak * 0.25 or ost - s["rashod"] < 0
                    if (vlezet and nado) or len(ostalos) >= dney_ostalos:
                        s["zapravka"] = ostalos.pop(0)
                ost = ost + s["zapravka"] - s["rashod"]
            if ostalos:
                preduprezhdeniya_gen.append(f"не влезло в бак {len(ostalos)} заправок по {ostalos[0]:g} л — "
                                            "уменьшите литры или увеличьте число заправок")
        else:
            for p_i, i in enumerate(plan):
                stroki[i]["zapravka"] = r2(stroki[i]["zapravka"] + porcii[p_i])
    elif zapravki == "avto":
        if not bak:
            raise GenOshibka("Для «доливать до полного» впишите объём бака в карточке машины")
        ost = ost0
        for s in stroki:
            if not s["ruchnoy"] and ost - s["rashod"] < bak * (porog or 0):
                s["zapravka"] = float(int(bak - ost)) if bak - ost >= 1 else 0.0
            ost = ost + s["zapravka"] - s["rashod"]

    # Цепочка, как в pereschitat.
    spid, ost = spid0, ost0
    for s in stroki:
        sv = s["spid_vyezd_fix"] if s["spid_vyezd_fix"] is not None else spid
        ov = r2((s["ost_vyezd_fix"] if s["ost_vyezd_fix"] is not None else ost) + s["zapravka"])
        s.update(spid_vyezd=r2(sv), spid_vozvrat=r2(sv + s["probeg"]), ost_vyezd=ov, ost_vozvrat=r2(ov - s["rashod"]))
        spid, ost = s["spid_vozvrat"], s["ost_vozvrat"]
        s["preduprezhdeniya"] = preduprezhdeniya(dict(s, norma=s["norma"]), m, {}, {})

    vsego_rashod = r2(sum(s["rashod"] for s in stroki))
    vsego_zapr = r2(sum(s["zapravka"] for s in stroki))
    nuzhno = r2(vsego_rashod - ost0)
    if zapravki == "vsego" and litrov_vsego is not None and r2(ost0 + vsego_zapr - vsego_rashod) < 0:
        preduprezhdeniya_gen.append(
            f"на {r2(sum(s['probeg'] for s in stroki)):g} {m['edinica']} нужно {vsego_rashod:g} л, "
            f"заправок {vsego_zapr:g} л и в баке было {r2(ost0):g} л — не хватает {r2(vsego_rashod - ost0 - vsego_zapr):g} л")
    if any((s["ost_vozvrat"] or 0) < 0 for s in stroki):
        preduprezhdeniya_gen.append("в какие-то дни бак уходит в минус — добавьте заправку или уменьшите пробег")
    return {"mashina": m, "mesyac": mesyac, "sotrudnik_id": sid,
            "vremya_vyezd": vremya_vyezd or m["vremya_vyezd"] or "08:00",
            "vremya_vozvrat": vremya_vozvrat or m["vremya_vozvrat"] or "17:00",
            "marshrut": marshrut if marshrut is not None else (m["marshrut"] or ""),
            "stroki": stroki, "nachalo": {"spidometr": spid0, "ostatok": r2(ost0)},
            "itogi": {"dney": len(stroki), "probeg": r2(sum(s["probeg"] for s in stroki)), "zapravka": vsego_zapr,
                      "rashod": vsego_rashod, "ost_konec": stroki[-1]["ost_vozvrat"] if stroki else r2(ost0),
                      "spid_konec": stroki[-1]["spid_vozvrat"] if stroki else spid0,
                      "nuzhno_zapravit_minimum": nuzhno if nuzhno > 0 else 0},
            "preduprezhdeniya": preduprezhdeniya_gen}


def sohranit_generator(conn, tid, chernovik):
    """Записать черновик: листы «generator» месяца заменяются, ручные не трогаем."""
    ot, do = mesyac_granicy(chernovik["mesyac"])
    starye = conn.execute("SELECT data, nomer FROM putevoy_list WHERE tehnika_id=? AND istochnik='generator' "
                          "AND data>=? AND data<=? ORDER BY data", (tid, ot.isoformat(), do.isoformat())).fetchall()
    svob_nomera = sorted(n for _, n in starye if n)
    conn.execute("DELETE FROM putevoy_list WHERE tehnika_id=? AND istochnik='generator' AND data>=? AND data<=?",
                 (tid, ot.isoformat(), do.isoformat()))
    nomer = sleduyushchiy_nomer(conn, ot.year)
    n = 0
    for s in chernovik["stroki"]:
        if s["ruchnoy"]:
            continue
        if svob_nomera:
            nm = svob_nomera.pop(0)
        else:
            nm, nomer = nomer, nomer + 1
        conn.execute(
            "INSERT INTO putevoy_list (tehnika_id, data, nomer, sotrudnik_id, probeg, zapravka, vremya_vyezd, "
            "vremya_vozvrat, marshrut, istochnik) VALUES (?,?,?,?,?,?,?,?,?, 'generator')",
            (tid, s["data"], nm, chernovik["sotrudnik_id"], s["probeg"], s["zapravka"], chernovik["vremya_vyezd"],
             chernovik["vremya_vozvrat"], chernovik["marshrut"] or None))
        n += 1
    # Номера месяца — по порядку дат (тот же набор номеров, что был).
    rows = conn.execute("SELECT id, nomer FROM putevoy_list WHERE tehnika_id=? AND data>=? AND data<=? ORDER BY data",
                        (tid, ot.isoformat(), do.isoformat())).fetchall()
    nomera = sorted(r[1] for r in rows if r[1] is not None)
    if len(nomera) == len(rows):
        for (lid, _), nm in zip(rows, nomera):
            conn.execute("UPDATE putevoy_list SET nomer=? WHERE id=?", (nm, lid))
    pereschitat(conn, tid, ot.isoformat())
    return n


# --------------------------------------------------------- сводка всех ---

def svodka_vseh(conn, mesyac):
    """Все машины с листами за месяц + итог по ДТ / АИ-92."""
    ot, do = mesyac_granicy(mesyac)
    out = []
    for (tid,) in conn.execute("SELECT DISTINCT tehnika_id FROM putevoy_list WHERE data>=? AND data<=?",
                               (ot.isoformat(), do.isoformat())).fetchall():
        m = mashina(conn, tid)
        ll = listy(conn, tid, ot.isoformat(), do.isoformat())
        spid0, ost0 = nachalo_mesyaca(conn, tid, ot, m)
        sm = smena_po_dnyam(conn, tid, ot.isoformat(), do.isoformat())
        it = itogi(ll, ost0, spid0)
        it.update(tehnika_id=tid, nazvanie=m["nazvanie"], nomer=m["nomer"], toplivo=m["toplivo"],
                  edinica=m["edinica"], zakryt=mesyac in zakrytye_mesyacy(conn, tid),
                  smena_zapravka=r2(sum(v["zapravka"] or 0 for v in sm.values())),
                  smena_rashod=r2(sum(v["rashod"] or 0 for v in sm.values())))
        out.append(it)
    out.sort(key=lambda x: x["nazvanie"] or "")
    po_toplivu = {}
    for x in out:
        t = x["toplivo"] or "—"
        p = po_toplivu.setdefault(t, {"probeg": 0.0, "zapravka": 0.0, "rashod": 0.0})
        for k in p:
            p[k] = r2(p[k] + (x[k] or 0))
    return {"mesyac": mesyac, "mashiny": out, "po_toplivu": po_toplivu}
