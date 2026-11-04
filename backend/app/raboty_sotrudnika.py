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

import re
from datetime import date, timedelta

from app import legacy_bridge  # noqa: F401


def _norm(s):
    return " ".join(str(s or "").lower().replace("ё", "е").split())


def _num(x):
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def _est_tablica(conn, t):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def najti_po_fio(conn, fio):
    """id сотрудника по ФИО — только если совпадение одно (без учёта
    регистра, ё/е и лишних пробелов); иначе None."""
    n = _norm(fio)
    if not n:
        return None
    ids = [sid for sid, f in conn.execute("SELECT id, fio FROM sotrudniki").fetchall() if _norm(f) == n]
    return ids[0] if len(ids) == 1 else None


def _est_kolonka(conn, t, c):
    return any(r[1] == c for r in conn.execute(f"PRAGMA table_info({t})").fetchall())


def zapolnit_ssylki(conn):
    """Старые записи «Журнала выполненных работ» и «Выполнения» рубок ухода
    знали исполнителя только текстом ФИО. Проставить ссылку на сотрудника
    там, где ФИО однозначно совпадает со справочником (карточка человека,
    04.11.2026). Однофамильцев и опечатки не трогаем — их видно в карточке
    как «не привязано»."""
    if not _est_tablica(conn, "sotrudniki"):
        return 0
    po_fio = {}
    for sid, fio in conn.execute("SELECT id, fio FROM sotrudniki").fetchall():
        po_fio.setdefault(_norm(fio), []).append(sid)
    n = 0
    for t, kol_id, kol_fio in (("completed_works", "sotrudnik_id", "ispolnitel_fio"),
                               ("uhody_vypolnenie", "ispolnitel_id", "ispolnitel")):
        if not _est_tablica(conn, t) or not _est_kolonka(conn, t, kol_id):
            continue
        for rid, fio in conn.execute(f"SELECT id, {kol_fio} FROM {t} WHERE {kol_id} IS NULL AND {kol_fio} IS NOT NULL").fetchall():
            ids = po_fio.get(_norm(fio)) or []
            if len(ids) == 1:
                conn.execute(f"UPDATE {t} SET {kol_id}=? WHERE id=?", (ids[0], rid))
                n += 1
    conn.commit()
    return n


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
        for sid, d, st, kv, vd, nazv, lkv, lvd, lles, vid, kom, did, luid in conn.execute(
                """SELECT t.sotrudnik_id, t.data, t.status, di.kvartal, di.vydel, dl.nazvanie,
                          lu.kvartal, lu.vydel, lu.lesnichestvo, v.nazvanie, t.kommentariy, dl.id, lu.id
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
            s["tabel"] = {"status": st, "gde": gde, "vid": vid, "kommentariy": kom or None,
                          "ssylka": ({"screen": "plots", "params": {"d": did}} if did else
                                     {"screen": "forestry", "params": {"u": luid}} if luid else None)}

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
                    "ssylka": ({"screen": "plots", "params": {"d": r["delyanka_id"]}} if r.get("delyanka_id") else
                               {"screen": "forestry", "params": {"u": r["lesokultury_uchastok_id"]}}
                               if r.get("lesokultury_uchastok_id") else
                               {"screen": "uhody", "params": {"p": r["uhody_proba_id"]}}
                               if r.get("uhody_proba_id") else None),
                })

    # журнал выполненных работ
    if _est_tablica(conn, "completed_works"):
        kol_id = "sotrudnik_id" if _est_kolonka(conn, "completed_works", "sotrudnik_id") else "NULL"
        kol_del = "delyanka_id" if _est_kolonka(conn, "completed_works", "delyanka_id") else "NULL"
        kol_lk = "lesokultury_uchastok_id" if _est_kolonka(conn, "completed_works", "lesokultury_uchastok_id") else "NULL"
        kol_mer = "lk_meropriyatie_id" if _est_kolonka(conn, "completed_works", "lk_meropriyatie_id") else "NULL"
        for d, fio, kv, vd, tip, les, op, cw_sid, cw_del, cw_lk, cw_mer in conn.execute(
                f"""SELECT data_vypolneniya, ispolnitel_fio, kvartal, vydel, tip_raboty, lesnichestvo, opisanie,
                          {kol_id}, {kol_del}, {kol_lk}, {kol_mer}
                   FROM completed_works WHERE substr(data_vypolneniya, 1, 10) BETWEEN ? AND ?""", (ot, do)).fetchall():
            sid = cw_sid or po_fio.get(_norm(fio))
            if not sid:
                continue
            s = slot(sid, (d or "")[:10])
            if s is None:
                continue
            gde = ", ".join(x for x in (f"кв.{kv}" if kv else None, f"выд.{vd}" if vd else None, les or None) if x)
            ssylka = None
            if cw_del:
                ssylka = {"screen": "plots", "params": {"d": cw_del}}
            elif cw_mer and cw_lk is None:
                u = conn.execute("SELECT uchastok_id FROM lesokultury_meropriyatiya WHERE id=?", (cw_mer,)).fetchone()
                if u:
                    ssylka = {"screen": "forestry", "params": {"u": u[0]}}
            elif cw_lk:
                ssylka = {"screen": "forestry", "params": {"u": cw_lk}}
            if ssylka is None and op:
                m = re.search(r"Проба рубок ухода №(\d+)", op)
                if m:
                    ssylka = {"screen": "uhody", "params": {"p": int(m.group(1))}}
            s["raboty"].append({"istochnik": "zhurnal", "emoji": "✅", "chto": tip or "Работа", "gde": gde or None,
                                "skolko": None, "opisanie": op or None, "ssylka": ssylka})

    # рубки ухода, внесённые в офисе
    if _est_tablica(conn, "uhody_vypolnenie"):
        kol_id = "v.ispolnitel_id" if _est_kolonka(conn, "uhody_vypolnenie", "ispolnitel_id") else "NULL"
        for d, ga, isp, kv, vd, pid, isp_id in conn.execute(
                f"""SELECT v.data, v.ga, v.ispolnitel, p.kvartal, p.vydel, p.id, {kol_id} FROM uhody_vypolnenie v
                   JOIN uhody_proby p ON p.id = v.proba_id WHERE v.data BETWEEN ? AND ?""", (ot, do)).fetchall():
            sid = isp_id or po_fio.get(_norm(isp))
            if not sid:
                continue
            s = slot(sid, d)
            if s is None:
                continue
            s["raboty"].append({"istochnik": "uhody", "emoji": "✂️", "chto": "Рубка ухода",
                                "gde": f"проба №{pid} · кв.{kv} выд.{vd}", "skolko": f"{_num(ga)} га",
                                "ssylka": {"screen": "uhody", "params": {"p": pid}}})
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
