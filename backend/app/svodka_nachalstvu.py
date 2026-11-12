# -*- coding: utf-8 -*-
"""Сводка за месяц для начальства (разбор сайта 09.11.2026, шаг 2).

Одна страница «как прошёл месяц»: сколько заготовили (по нарядам, по
сортиментам, лучшие делянки, сравнение с прошлым месяцем), как осваиваются
активные делянки и что горит по срокам, люди (явки, часы, больничные),
техника (пробег, топливо по путевым), лес (мероприятия лесокультур, рубки
ухода по пробам), отчёты смены с телефона.

Каждая часть считается отдельно и не роняет остальные: нет таблицы — пустая
часть. Даты нарядов в базе бывают и «ДД.ММ.ГГГГ», и ISO — разбираются обе.
"""
import datetime
import sqlite3

SORT_NAZV = {"KR": "Крупная", "SR": "Средняя", "ML": "Мелкая", "DROVA": "Дрова", "HVOROST": "Хворост"}


def _ym(value):
    s = str(value or "").strip()[:10]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    return None


def _proshlyy(ym):
    y, m = (int(x) for x in ym.split("-"))
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def _r1(v):
    return round(float(v or 0), 1)


def _zagotovka(conn, ym):
    po_sort, po_del, naryady = {}, {}, set()
    proshlyy = _proshlyy(ym)
    god_nazad = f"{int(ym[:4]) - 1:04d}{ym[4:]}"
    bylo, bylo_god_nazad = 0.0, 0.0
    rows = conn.execute(
        "SELECT n.id, n.data, n.delyanka_id, COALESCE(d.nazvanie, 'делянка №' || n.delyanka_id), p.sortiment, p.obyom "
        "FROM raskhod_pozitsiya p JOIN raskhod_naryad n ON p.naryad_id = n.id "
        "LEFT JOIN delyanka d ON d.id = n.delyanka_id"
    ).fetchall()
    for nid, data, did, nazv, sort, ob in rows:
        k = _ym(data)
        if k == proshlyy:
            bylo += ob or 0
        if k == god_nazad:
            bylo_god_nazad += ob or 0
        if k != ym:
            continue
        naryady.add(nid)
        s = sort or "?"
        po_sort[s] = po_sort.get(s, 0) + (ob or 0)
        x = po_del.setdefault(did, {"id": did, "nazvanie": nazv, "m3": 0.0})
        x["m3"] += ob or 0
    vsego = sum(po_sort.values())
    return {
        "m3": _r1(vsego),
        "m3_proshlyy": _r1(bylo),
        "izmenenie_pct": round((vsego - bylo) / bylo * 100) if bylo else None,
        "m3_god_nazad": _r1(bylo_god_nazad),
        "k_godu_pct": round((vsego - bylo_god_nazad) / bylo_god_nazad * 100) if bylo_god_nazad else None,
        "naryadov": len(naryady),
        "po_sortimentam": [
            {"kod": k, "nazvanie": SORT_NAZV.get(k, k), "m3": _r1(v)}
            for k, v in sorted(po_sort.items(), key=lambda kv: -kv[1])
        ],
        "po_delyankam": sorted(({**x, "m3": _r1(x["m3"])} for x in po_del.values()), key=lambda x: -x["m3"])[:8],
    }


def _delyanki(conn):
    from app.routers.dashboard import _build_plots_table
    plots = _build_plots_table(conn)
    goryat = [p for p in plots if p.get("dney") is not None and p["dney"] <= 30]
    return {
        "aktivnyh": len(plots),
        "prosrocheno": sum(1 for p in goryat if p["dney"] < 0),
        "do_30_dney": sum(1 for p in goryat if p["dney"] >= 0),
        "spisok": plots,
    }


def _lyudi(conn, ym):
    from app import tabel_mesyac
    t = tabel_mesyac.get_mesyac(conn, ym)
    s = {"lyudey": len(t["lyudi"]), "rabochih_dney": t["rabochih_dney"]}
    for k in ("yavki", "chasov", "bolnichnyy", "otpusk", "nn", "pusto"):
        s[k] = sum(ch["itogo"][k] for ch in t["lyudi"])
    return s


def _tehnika(conn, ym):
    out = []
    for tid, nazv, nomer, ed, probeg, zapr, rashod, listov in conn.execute(
        "SELECT t.id, t.nazvanie, t.nomer, COALESCE(t.edinica, 'км'), SUM(p.probeg), SUM(p.zapravka), SUM(p.rashod), COUNT(*) "
        "FROM putevoy_list p JOIN tehnika t ON t.id = p.tehnika_id WHERE substr(p.data, 1, 7) = ? "
        "GROUP BY t.id ORDER BY t.nazvanie", (ym,)
    ).fetchall():
        out.append({"id": tid, "nazvanie": nazv, "nomer": nomer or "", "edinica": ed, "probeg": _r1(probeg),
                    "zapravka": _r1(zapr), "rashod": _r1(rashod), "listov": listov})
    return {"mashiny": out, "toplivo_vsego": _r1(sum(x["zapravka"] for x in out)),
            "rashod_vsego": _r1(sum(x["rashod"] for x in out))}


def _les(conn, ym):
    mer = {}
    for tip, data in conn.execute("SELECT tip, data FROM lesokultury_meropriyatiya").fetchall():
        if _ym(data) == ym:
            mer[tip] = mer.get(tip, 0) + 1
    ga = 0.0
    for data, g in conn.execute("SELECT data, ga FROM uhody_vypolnenie").fetchall():
        if _ym(data) == ym:
            ga += g or 0
    return {"meropriyatiya": [{"tip": k, "kol": v} for k, v in sorted(mer.items(), key=lambda kv: -kv[1])],
            "uhody_ga": _r1(ga)}


def _smeny(conn, ym):
    out = {}
    for vid, n, ob, ga in conn.execute(
        "SELECT vid, COUNT(*), SUM(obyom), SUM(ga) FROM otchet_smeny WHERE deleted = 0 AND substr(data, 1, 7) = ? GROUP BY vid",
        (ym,),
    ).fetchall():
        out[vid] = {"vid": vid, "otchetov": n, "m3": _r1(ob), "ga": _r1(ga)}
    return sorted(out.values(), key=lambda x: -x["otchetov"])


def svodka(conn, ym):
    y, m = (int(x) for x in str(ym).split("-")[:2])
    if not (2000 <= y <= 2100 and 1 <= m <= 12):
        raise ValueError("Месяц в виде ГГГГ-ММ")
    ym = f"{y:04d}-{m:02d}"
    out = {"ym": ym}
    for key, fn in (
        ("zagotovka", lambda: _zagotovka(conn, ym)),
        ("delyanki", lambda: _delyanki(conn)),
        ("lyudi", lambda: _lyudi(conn, ym)),
        ("tehnika", lambda: _tehnika(conn, ym)),
        ("les", lambda: _les(conn, ym)),
        ("smeny", lambda: _smeny(conn, ym)),
    ):
        try:
            out[key] = fn()
        except (sqlite3.OperationalError, KeyError, TypeError, ValueError):
            out[key] = None
    return out


# --------------------------------------------------------------------------- #
#   Итоги сезона (шаг 6 разбора 09.11.2026): год целиком и сравнение с прошлым
# --------------------------------------------------------------------------- #
MES_KOR = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _god_zagotovka(conn, god):
    po_mes = {god: [0.0] * 12, god - 1: [0.0] * 12}
    po_del, naryady = {}, set()
    for nid, data, did, nazv, ob in conn.execute(
        "SELECT n.id, n.data, n.delyanka_id, COALESCE(d.nazvanie, 'делянка №' || n.delyanka_id), p.obyom "
        "FROM raskhod_pozitsiya p JOIN raskhod_naryad n ON p.naryad_id = n.id LEFT JOIN delyanka d ON d.id = n.delyanka_id"
    ).fetchall():
        k = _ym(data)
        if not k:
            continue
        y, m = int(k[:4]), int(k[5:7])
        if y in po_mes:
            po_mes[y][m - 1] += ob or 0
        if y == god:
            naryady.add(nid)
            x = po_del.setdefault(did, {"id": did, "nazvanie": nazv, "m3": 0.0})
            x["m3"] += ob or 0
    vsego, bylo = sum(po_mes[god]), sum(po_mes[god - 1])
    return {
        "m3": _r1(vsego), "m3_proshlyy": _r1(bylo),
        "izmenenie_pct": round((vsego - bylo) / bylo * 100) if bylo else None,
        "naryadov": len(naryady), "delyanok": len(po_del),
        "mesyacy": MES_KOR,
        "po_mesyacam": [_r1(v) for v in po_mes[god]],
        "po_mesyacam_proshlyy": [_r1(v) for v in po_mes[god - 1]],
        "luchshiy_mesyac": MES_KOR[max(range(12), key=lambda i: po_mes[god][i])] if vsego else None,
        "po_delyankam": sorted(({**x, "m3": _r1(x["m3"])} for x in po_del.values()), key=lambda x: -x["m3"])[:10],
    }


def _god_lyudi(conn, god):
    from app.tabel_mesyac import RABOCHIE, CHASOV_V_DEN
    po = {}
    for sid, fio, st in conn.execute(
        "SELECT t.sotrudnik_id, s.fio, t.status FROM tabel_zapis t JOIN sotrudniki s ON s.id = t.sotrudnik_id "
        "WHERE substr(t.data, 1, 4) = ?", (str(god),)
    ).fetchall():
        x = po.setdefault(sid, {"id": sid, "fio": fio, "yavki": 0, "bolnichnyy": 0})
        if st in RABOCHIE:
            x["yavki"] += 1
        elif st == "больничный":
            x["bolnichnyy"] += 1
    lyudi = sorted(po.values(), key=lambda x: -x["yavki"])
    yavki = sum(x["yavki"] for x in lyudi)
    return {"lyudey": len(lyudi), "yavki": yavki, "chasov": yavki * CHASOV_V_DEN,
            "bolnichnyy": sum(x["bolnichnyy"] for x in lyudi), "geroi": lyudi[:8]}


def _god_tehnika(conn, god):
    r = conn.execute(
        "SELECT SUM(probeg), SUM(zapravka), SUM(rashod), COUNT(*) FROM putevoy_list WHERE substr(data, 1, 4) = ?",
        (str(god),)).fetchone()
    return {"probeg": _r1(r[0]), "zapravka": _r1(r[1]), "rashod": _r1(r[2]), "listov": r[3] or 0}


def _god_les(conn, god):
    mer = {}
    for tip, data in conn.execute("SELECT tip, data FROM lesokultury_meropriyatiya").fetchall():
        k = _ym(data)
        if k and k[:4] == str(god):
            mer[tip] = mer.get(tip, 0) + 1
    ga = sum(g or 0 for d, g in conn.execute("SELECT data, ga FROM uhody_vypolnenie").fetchall()
             if (_ym(d) or "")[:4] == str(god))
    return {"meropriyatiya": [{"tip": k, "kol": v} for k, v in sorted(mer.items(), key=lambda kv: -kv[1])],
            "uhody_ga": _r1(ga)}


def itogi(conn, god):
    god = int(god)
    if not 2000 <= god <= 2100:
        raise ValueError("Год в виде ГГГГ")
    out = {"god": god}
    for key, fn in (
        ("zagotovka", lambda: _god_zagotovka(conn, god)),
        ("lyudi", lambda: _god_lyudi(conn, god)),
        ("tehnika", lambda: _god_tehnika(conn, god)),
        ("les", lambda: _god_les(conn, god)),
    ):
        try:
            out[key] = fn()
        except (sqlite3.OperationalError, KeyError, TypeError, ValueError):
            out[key] = None
    return out
