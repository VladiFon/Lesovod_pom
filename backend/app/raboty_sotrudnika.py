# -*- coding: utf-8 -*-
"""Кто где был и что делал (Влад, 04.11.2026) — для Табеля.

Собирает по сотруднику и дню всё, что о нём известно:
  - 📋 табель (tabel_zapis): статус, место, вид работы, комментарий;
  - 🚜 отчёты за смену с телефона (otchet_smeny), где он автор или напарник;
  - ✅ «Журнал выполненных работ» (completed_works): лесокультуры (кто
    делал запись журнала), пробы рубок ухода, одобренные отчёты и т.п.;
  - ✂️ «Выполнение» рубок ухода, внесённое в офисе (uhody_vypolnenie).
Сотрудник в completed_works / uhody_vypolnenie ищется по ФИО.
"""
from __future__ import annotations

from datetime import date, timedelta

from app import legacy_bridge  # noqa: F401


def _norm(s):
    return " ".join(str(s or "").lower().replace("ё", "е").split())


def _num(x):
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def _est_tablica(conn, t):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def sobrat(conn, ot: str, do: str, sotrudnik_ids=None):
    """{sotrudnik_id: {data ISO: {"tabel": {...}|None, "raboty": [...]}}}"""
    from app.routers import smena
    ids = set(sotrudnik_ids) if sotrudnik_ids else None
    sotr = conn.execute("SELECT id, fio FROM sotrudniki").fetchall()
    po_fio = {}
    for sid, fio in sotr:
        po_fio.setdefault(_norm(fio), sid)
    out = {}

    def slot(sid, d):
        if ids is not None and sid not in ids:
            return None
        return out.setdefault(sid, {}).setdefault(d, {"tabel": None, "raboty": []})

    # табель
    if _est_tablica(conn, "tabel_zapis"):
        for sid, d, st, kv, vd, nazv, lkv, lvd, lles, vid, kom in conn.execute(
                """SELECT t.sotrudnik_id, t.data, t.status, di.kvartal, di.vydel, dl.nazvanie,
                          lu.kvartal, lu.vydel, lu.lesnichestvo, v.nazvanie, t.kommentariy
                   FROM tabel_zapis t
                   LEFT JOIN delyanka_item di ON di.id = t.delyanka_item_id
                   LEFT JOIN delyanka dl ON dl.id = di.delyanka_id
                   LEFT JOIN lesokultury_uchastok lu ON lu.id = t.lesokultury_uchastok_id
                   LEFT JOIN vidy_rabot v ON v.id = t.vid_raboty_id
                   WHERE t.data BETWEEN ? AND ?""", (ot, do)).fetchall():
            s = slot(sid, d)
            if s is None:
                continue
            gde = (f"{nazv or 'делянка'} · кв.{kv} выд.{vd}" if kv or nazv else
                   f"л/к кв.{lkv} выд.{lvd}" + (f" · {lles}" if lles else "") if lkv else None)
            s["tabel"] = {"status": st, "gde": gde, "vid": vid, "kommentariy": kom or None}

    # отчёты за смену
    if _est_tablica(conn, "otchet_smeny"):
        for r in smena._stroki(conn, "o.data BETWEEN ? AND ?", [ot, do], limit=20000):
            skolko = ", ".join(x for x in (
                f"{_num(r['obyom'])} м³" if r.get("obyom") else None,
                f"{_num(r['reysov'])} рейс." if r.get("reysov") else None,
                f"{_num(r['ga'])} га" if r.get("ga") else None,
                f"{_num(r['chasy'])} ч" if r.get("chasy") else None,
            ) if x)
            nap = r.get("naparniki") or []
            for sid in [r["sotrudnik_id"]] + [n["id"] for n in nap]:
                s = slot(sid, r["data"])
                if s is None:
                    continue
                s["raboty"].append({
                    "istochnik": "smena", "emoji": r["emoji"], "chto": r["vid_title"], "gde": r.get("mesto"),
                    "skolko": skolko or None,
                    "s_kem": ", ".join(([r["fio"]] if sid != r["sotrudnik_id"] else []) +
                                       [n["fio"] for n in nap if n["id"] != sid]) or None,
                    "tehnika": r.get("tehnika"),
                })

    # журнал выполненных работ
    if _est_tablica(conn, "completed_works"):
        for d, fio, kv, vd, tip, les, op in conn.execute(
                """SELECT data_vypolneniya, ispolnitel_fio, kvartal, vydel, tip_raboty, lesnichestvo, opisanie
                   FROM completed_works WHERE substr(data_vypolneniya, 1, 10) BETWEEN ? AND ?""", (ot, do)).fetchall():
            sid = po_fio.get(_norm(fio))
            if not sid:
                continue
            s = slot(sid, (d or "")[:10])
            if s is None:
                continue
            gde = ", ".join(x for x in (f"кв.{kv}" if kv else None, f"выд.{vd}" if vd else None, les or None) if x)
            s["raboty"].append({"istochnik": "zhurnal", "emoji": "✅", "chto": tip or "Работа", "gde": gde or None,
                                "skolko": None, "opisanie": op or None})

    # рубки ухода, внесённые в офисе
    if _est_tablica(conn, "uhody_vypolnenie"):
        for d, ga, isp, kv, vd, pid in conn.execute(
                """SELECT v.data, v.ga, v.ispolnitel, p.kvartal, p.vydel, p.id FROM uhody_vypolnenie v
                   JOIN uhody_proby p ON p.id = v.proba_id WHERE v.data BETWEEN ? AND ?""", (ot, do)).fetchall():
            sid = po_fio.get(_norm(isp))
            if not sid:
                continue
            s = slot(sid, d)
            if s is None:
                continue
            s["raboty"].append({"istochnik": "uhody", "emoji": "✂️", "chto": "Рубка ухода",
                                "gde": f"проба №{pid} · кв.{kv} выд.{vd}", "skolko": f"{_num(ga)} га"})
    return out


def za_den(conn, data: str):
    """{sotrudnik_id: [работы]} на один день (табель берётся из своей таблицы)."""
    return {sid: dni.get(data, {}).get("raboty", []) for sid, dni in sobrat(conn, data, data).items()}


def istoriya(conn, sotrudnik_id: int, dney: int = 31, do: str | None = None):
    do_d = date.fromisoformat(do) if do else date.today()
    ot_d = do_d - timedelta(days=dney - 1)
    dni = sobrat(conn, ot_d.isoformat(), do_d.isoformat(), [sotrudnik_id]).get(sotrudnik_id, {})
    fio = conn.execute("SELECT fio, dolzhnost FROM sotrudniki WHERE id=?", (sotrudnik_id,)).fetchone()
    spisok = [{"data": d, **v} for d, v in sorted(dni.items(), reverse=True) if v["tabel"] or v["raboty"]]
    itogo = {}
    for x in spisok:
        for r in x["raboty"]:
            itogo[r["chto"]] = itogo.get(r["chto"], 0) + 1
        if x["tabel"] and x["tabel"]["status"]:
            k = "📋 " + x["tabel"]["status"]
            itogo[k] = itogo.get(k, 0) + 1
    return {"sotrudnik_id": sotrudnik_id, "fio": fio[0] if fio else None, "dolzhnost": fio[1] if fio else None,
            "ot": ot_d.isoformat(), "do": do_d.isoformat(), "dni": spisok,
            "itogo": sorted(({"chto": k, "dney": v} for k, v in itogo.items()), key=lambda x: -x["dney"])}
