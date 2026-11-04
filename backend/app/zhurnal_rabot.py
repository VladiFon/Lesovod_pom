# -*- coding: utf-8 -*-
"""Единый журнал работ (шаг 3 разбора «сайт разбросан», 04.11.2026).

Раньше «что сделано» лежало в шести местах: отчёты за смену с телефона,
журнал выполненных работ (С телефона → Журнал), журнал мероприятий
лесокультур, «Выполнение» рубок ухода, табель и закрытые пробы. Здесь всё
это — одна лента, одна строка = одно событие (отчёт с напарниками — одна
строка с несколькими людьми, а не по строке на каждого).

Каждая строка: {kluch, istochnik, data, emoji, chto, gde, kvartal, vydel,
lesnichestvo, skolko, opisanie, lyudi: [{id, fio}], ssylka}.
Только чтение — вводить по-прежнему на своих экранах.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from app import legacy_bridge  # noqa: F401
from app import raboty_sotrudnika as rs

ISTOCHNIKI = {
    "smena": "Отчёт за смену (телефон)",
    "lk": "Журнал лесокультур",
    "zhurnal": "Журнал выполненных работ",
    "uhody": "Рубки ухода (Выполнение)",
    "tabel": "Табель",
}


def _iso(s):
    s = str(s or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _sk(*parts):
    return ", ".join(x for x in parts if x) or None


def sobrat(conn, ot: str, do: str, istochniki=None):
    from app.routers import smena
    nuzhno = set(istochniki or ISTOCHNIKI)
    po_fio = {}
    for sid, fio in conn.execute("SELECT id, fio FROM sotrudniki").fetchall():
        po_fio.setdefault(rs._norm(fio), sid)

    def chel(sid, fio):
        return {"id": sid or po_fio.get(rs._norm(fio)), "fio": fio}

    out = []

    if "smena" in nuzhno and rs._est_tablica(conn, "otchet_smeny"):
        for r in smena._stroki(conn, "o.data BETWEEN ? AND ?", [ot, do], limit=20000):
            kv = vd = les = None
            if r.get("delyanka_item_id"):
                x = conn.execute("SELECT kvartal, vydel, lesnichestvo FROM delyanka_item WHERE id=?",
                                 (r["delyanka_item_id"],)).fetchone()
                kv, vd, les = x if x else (None, None, None)
            elif r.get("lesokultury_uchastok_id"):
                x = conn.execute("SELECT kvartal, vydel, lesnichestvo FROM lesokultury_uchastok WHERE id=?",
                                 (r["lesokultury_uchastok_id"],)).fetchone()
                kv, vd, les = x if x else (None, None, None)
            elif r.get("uhody_proba_id"):
                x = conn.execute("SELECT kvartal, vydel FROM uhody_proby WHERE id=?", (r["uhody_proba_id"],)).fetchone()
                kv, vd = x if x else (None, None)
            out.append({
                "kluch": f"smena-{r['id']}", "istochnik": "smena", "data": r["data"], "emoji": r["emoji"],
                "chto": r["vid_title"], "gde": r.get("mesto"), "kvartal": kv, "vydel": vd, "lesnichestvo": les,
                "skolko": _sk(f"{rs._num(r['obyom'])} м³" if r.get("obyom") else None,
                              f"{rs._num(r['reysov'])} рейс." if r.get("reysov") else None,
                              f"{rs._num(r['ga'])} га" if r.get("ga") else None,
                              f"{rs._num(r['chasy'])} ч" if r.get("chasy") else None),
                "opisanie": _sk(r.get("tehnika"), r.get("kommentariy")),
                "lyudi": [{"id": r["sotrudnik_id"], "fio": r["fio"]}] + list(r.get("naparniki") or []),
                "ssylka": ({"screen": "plots", "params": {"d": r["delyanka_id"]}} if r.get("delyanka_id") else
                           {"screen": "forestry", "params": {"u": r["lesokultury_uchastok_id"]}}
                           if r.get("lesokultury_uchastok_id") else
                           {"screen": "uhody", "params": {"p": r["uhody_proba_id"]}} if r.get("uhody_proba_id") else
                           {"screen": "raboty", "params": {"tab": "smena"}}),
            })

    if "lk" in nuzhno and rs._est_tablica(conn, "lesokultury_meropriyatiya"):
        kol = "m.ispolniteli_json" if rs._est_kolonka(conn, "lesokultury_meropriyatiya", "ispolniteli_json") else "NULL"
        for mid, tip, d, prim, isp, uid, kv, vd, les in conn.execute(
                f"""SELECT m.id, m.tip, m.data, m.primechaniya, {kol}, u.id, u.kvartal, u.vydel, u.lesnichestvo
                    FROM lesokultury_meropriyatiya m JOIN lesokultury_uchastok u ON u.id = m.uchastok_id""").fetchall():
            di = _iso(d)
            if not di or not (ot <= di <= do):
                continue
            try:
                lst = json.loads(isp) if isp else []
            except (TypeError, ValueError):
                lst = []
            out.append({
                "kluch": f"lk-{mid}", "istochnik": "lk", "data": di, "emoji": "🌱", "chto": tip,
                "gde": f"л/к кв.{kv} выд.{vd}" + (f" · {les}" if les else ""),
                "kvartal": kv, "vydel": vd, "lesnichestvo": les, "skolko": None, "opisanie": prim or None,
                "lyudi": [{"id": i.get("id"), "fio": i.get("fio"), "storonniy": bool(i.get("storonniy"))}
                          for i in lst if i.get("fio")],
                "ssylka": {"screen": "forestry", "params": {"u": uid}},
            })

    if "zhurnal" in nuzhno and rs._est_tablica(conn, "completed_works"):
        k = lambda c: c if rs._est_kolonka(conn, "completed_works", c) else "NULL"  # noqa: E731
        gruppy = {}
        for cid, d, fio, kv, vd, tip, les, op, sid, did, mer in conn.execute(
                f"""SELECT id, data_vypolneniya, ispolnitel_fio, kvartal, vydel, tip_raboty, lesnichestvo, opisanie,
                          {k('sotrudnik_id')}, {k('delyanka_id')}, {k('lk_meropriyatie_id')}
                   FROM completed_works WHERE substr(data_vypolneniya, 1, 10) BETWEEN ? AND ?
                   ORDER BY id""", (ot, do)).fetchall():
            if mer and "lk" in nuzhno:
                continue  # уже есть строкой журнала лесокультур
            # одна работа на нескольких исполнителей (закрытие пробы, л/к) — одной строкой
            kl = (mer,) if mer else (str(d)[:10], kv, vd, tip, op) if op and op.startswith("Проба рубок ухода") else (cid,)
            g = gruppy.get(kl)
            if g is None:
                ssylka = {"screen": "plots", "params": {"d": did}} if did else None
                m = re.search(r"Проба рубок ухода №(\d+)", op or "")
                if not ssylka and m:
                    ssylka = {"screen": "uhody", "params": {"p": int(m.group(1))}}
                g = gruppy[kl] = {
                    "kluch": f"cw-{cid}", "istochnik": "zhurnal", "data": str(d)[:10], "emoji": "✅",
                    "chto": tip or "Работа", "gde": _sk(f"кв.{kv}" if kv else None, f"выд.{vd}" if vd else None, les),
                    "kvartal": kv, "vydel": vd, "lesnichestvo": les, "skolko": None, "opisanie": op or None,
                    "lyudi": [], "ssylka": ssylka or {"screen": "raboty", "params": {"tab": "zhurnal"}},
                }
                out.append(g)
            if fio:
                g["lyudi"].append(chel(sid, fio))

    if "uhody" in nuzhno and rs._est_tablica(conn, "uhody_vypolnenie"):
        kol = "v.ispolnitel_id" if rs._est_kolonka(conn, "uhody_vypolnenie", "ispolnitel_id") else "NULL"
        for vid, d, ga, isp, kv, vd, pid, isp_id in conn.execute(
                f"""SELECT v.id, v.data, v.ga, v.ispolnitel, p.kvartal, p.vydel, p.id, {kol} FROM uhody_vypolnenie v
                   JOIN uhody_proby p ON p.id = v.proba_id WHERE v.data BETWEEN ? AND ?""", (ot, do)).fetchall():
            out.append({
                "kluch": f"uv-{vid}", "istochnik": "uhody", "data": d, "emoji": "✂️", "chto": "Рубка ухода",
                "gde": f"проба №{pid} · кв.{kv} выд.{vd}", "kvartal": kv, "vydel": vd, "lesnichestvo": None,
                "skolko": f"{rs._num(ga)} га" if ga else None, "opisanie": None,
                "lyudi": [chel(isp_id, isp)] if isp else [],
                "ssylka": {"screen": "uhody", "params": {"p": pid}},
            })

    if "tabel" in nuzhno and rs._est_tablica(conn, "tabel_zapis"):
        # табель — по человеку на день; в журнал кладём «кто где был» одной
        # строкой на (день, место, вид работы), только «работал»
        gruppy = {}
        for sid, fio, d, kv, vd, les, nazv, did, lkv, lvd, lles, luid, vidr in conn.execute(
                """SELECT t.sotrudnik_id, s.fio, t.data, di.kvartal, di.vydel, di.lesnichestvo, dl.nazvanie, dl.id,
                          lu.kvartal, lu.vydel, lu.lesnichestvo, lu.id, v.nazvanie
                   FROM tabel_zapis t JOIN sotrudniki s ON s.id = t.sotrudnik_id
                   LEFT JOIN delyanka_item di ON di.id = t.delyanka_item_id
                   LEFT JOIN delyanka dl ON dl.id = di.delyanka_id
                   LEFT JOIN lesokultury_uchastok lu ON lu.id = t.lesokultury_uchastok_id
                   LEFT JOIN vidy_rabot v ON v.id = t.vid_raboty_id
                   WHERE t.data BETWEEN ? AND ? AND t.status = 'работал'""", (ot, do)).fetchall():
            kl = (d, did, kv, vd, luid, vidr)
            g = gruppy.get(kl)
            if g is None:
                if did or kv:
                    gde = f"{nazv or 'делянка'} · кв.{kv} выд.{vd}"
                elif luid:
                    gde = f"л/к кв.{lkv} выд.{lvd}"
                else:
                    gde = None
                g = gruppy[kl] = {
                    "kluch": f"t-{d}-{did}-{kv}-{vd}-{luid}-{vidr}", "istochnik": "tabel", "data": d, "emoji": "📋",
                    "chto": vidr or "Работал (табель)", "gde": gde,
                    "kvartal": kv or lkv, "vydel": vd or lvd, "lesnichestvo": les or lles, "skolko": None,
                    "opisanie": None, "lyudi": [],
                    "ssylka": ({"screen": "plots", "params": {"d": did}} if did else
                               {"screen": "forestry", "params": {"u": luid}} if luid else
                               {"screen": "tabel", "params": {}}),
                }
                out.append(g)
            g["lyudi"].append({"id": sid, "fio": fio})
        # табель не дублирует то, что уже записано отчётом/журналом в тот же
        # день: остаются только люди, о ком больше ничего нет (без телефона)
        uzhe = {(x["data"], p.get("id")) for x in out if x["istochnik"] != "tabel" for p in x["lyudi"] if p.get("id")}
        for g in gruppy.values():
            g["lyudi"] = [p for p in g["lyudi"] if (g["data"], p["id"]) not in uzhe]
            if len(g["lyudi"]) > 1:
                g["skolko"] = f"{len(g['lyudi'])} чел."
        out = [x for x in out if x["istochnik"] != "tabel" or x["lyudi"]]

    out.sort(key=lambda x: (x["data"] or "", x["kluch"]), reverse=True)
    return out


def _vydely(s):
    return {x.strip() for x in str(s or "").replace(";", ",").split(",") if x.strip()}


def filtr(stroki, q=None, sotrudnik_id=None, kvartal=None, vydel=None):
    q = (q or "").strip().casefold()
    kv = str(kvartal or "").strip()
    vd = str(vydel or "").strip()
    out = []
    for s in stroki:
        if sotrudnik_id and not any(p.get("id") == sotrudnik_id for p in s["lyudi"]):
            continue
        if kv and str(s.get("kvartal") or "").strip() != kv:
            continue
        if vd and vd not in _vydely(s.get("vydel")):
            continue
        if q:
            tekst = " ".join(str(x or "") for x in (s["chto"], s["gde"], s["opisanie"], s["skolko"],
                                                     ISTOCHNIKI.get(s["istochnik"]))).casefold()
            tekst += " " + " ".join(p["fio"] or "" for p in s["lyudi"]).casefold()
            if not all(w in tekst for w in q.split()):
                continue
        out.append(s)
    return out
