# -*- coding: utf-8 -*-
"""Связи между разделами (шаг 2 разбора «сайт разбросан», 04.11.2026):
участок лесных культур ↔ пробы рубок ухода ↔ выдел ↔ люди.

Раньше с участка культур нельзя было попасть на его пробы рубок ухода и
обратно, хотя проба хранит, к каким участкам относится
(uhody_proby.lesokultury_uchastok_ids_json). Здесь — только чтение.
"""
from __future__ import annotations

import json

from app import legacy_bridge  # noqa: F401
from app import uhody_vypolnenie as uv


def _proba_kratko(p, itog, zakryta):
    it = itog.get(p["id"]) or {}
    return {
        "id": p["id"], "kvartal": p["kv"], "vydel": p["vd"],
        "data": p["data"].isoformat() if p["data"] and p["data"].year > 1 else None,
        "ploshad": p["ploshad"], "sdelano_ga": it.get("sdelano_ga") or 0, "pct": it.get("pct"),
        "zakryta": bool(zakryta.get(p["id"])),
    }


def _zakrytye(conn):
    return dict(conn.execute("SELECT id, completed_at FROM uhody_proby").fetchall())


def proby_vydela(conn, kvartal, vydel, uchastok_id=None):
    """Пробы рубок ухода на выделе (кв/выд) и/или привязанные к участку культур."""
    uv.ensure(conn)
    kv, vd = uv._norm(kvartal), uv._norm(vydel)
    itog = uv.kratko_vse(conn)
    zak = _zakrytye(conn)
    out = []
    for p in uv._proby(conn):
        po_uch = uchastok_id is not None and uchastok_id in p["uids"]
        po_vyd = kv and p["kv"] == kv and vd and vd in {x.strip() for x in p["vd"].replace(";", ",").split(",")}
        if po_uch or po_vyd:
            out.append({**_proba_kratko(p, itog, zak), "privyazana": po_uch})
    out.sort(key=lambda x: x["data"] or "", reverse=True)
    return out


def lyudi_uchastka(conn, uchastok_id):
    """Кто работал на участке культур: «Кто делал» в журнале мероприятий и
    отчёты за смену с телефона (автор и напарники)."""
    po = {}

    def dob(sid, fio, data, chto):
        if not fio:
            return
        k = sid or f"x:{fio}"
        x = po.setdefault(k, {"id": sid, "fio": fio, "raz": 0, "posledniy": None, "chto": set()})
        x["raz"] += 1
        if data and (not x["posledniy"] or data > x["posledniy"]):
            x["posledniy"] = data
        if chto:
            x["chto"].add(chto)

    for tip, data, isp in conn.execute(
            "SELECT tip, data, ispolniteli_json FROM lesokultury_meropriyatiya WHERE uchastok_id = ?",
            (uchastok_id,)).fetchall():
        try:
            lst = json.loads(isp) if isp else []
        except (TypeError, ValueError):
            lst = []
        for i in lst:
            dob(i.get("id"), i.get("fio"), (data or "")[:10], tip)
    try:
        from app.routers import smena
        smena.ensure(conn)
        for r in smena._stroki(conn, "o.lesokultury_uchastok_id = ?", [uchastok_id], limit=2000):
            dob(r["sotrudnik_id"], r["fio"], r["data"], r["vid_title"])
            for n in r.get("naparniki") or []:
                dob(n["id"], n["fio"], r["data"], r["vid_title"])
    except Exception:  # noqa: BLE001 — нет таблиц отчётов: просто без них
        pass
    out = [{**x, "chto": sorted(x["chto"])} for x in po.values()]
    out.sort(key=lambda x: (x["posledniy"] or ""), reverse=True)
    return out


def uchastok(conn, uchastok_id):
    u = conn.execute("SELECT kvartal, vydel, lesnichestvo FROM lesokultury_uchastok WHERE id = ?",
                     (uchastok_id,)).fetchone()
    if not u:
        return None
    return {
        "kvartal": u[0], "vydel": u[1], "lesnichestvo": u[2],
        "proby": proby_vydela(conn, u[0], u[1], uchastok_id),
        "lyudi": lyudi_uchastka(conn, uchastok_id),
    }
