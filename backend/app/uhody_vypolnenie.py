# -*- coding: utf-8 -*-
"""Выполнение рубок ухода по пробе (Влад, 04.11.2026).

Проба рубок ухода (uhody_proby) описывает участок: площадь и запас
хвороста м³/га. Сколько на нём уже сделано, складывается из:
  - отчётов за смену с телефона (otchet_smeny, vid='rubka_uhoda') — по
    участку лесных культур пробы или по тому же кварталу/выделу (участок
    культур или выдел делянки), с даты замера пробы; если на выдел есть
    несколько проб, отчёт идёт к последней по дате замера до отчёта;
  - строк, внесённых руками в офисе (uhody_vypolnenie).
Кубы считаются сами: м³/га пробы × сделанные га.

Пробы «хворост делянки» (uhody_proby.delyanka_id, legacy/hvorost.py) —
не рубки ухода: отчёты к ним не цепляются.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from app import legacy_bridge  # noqa: F401
import hvorost

SCHEMA = """
CREATE TABLE IF NOT EXISTS uhody_vypolnenie (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proba_id INTEGER NOT NULL REFERENCES uhody_proby(id),
    data TEXT NOT NULL,
    ga REAL NOT NULL,
    ispolnitel TEXT,
    kommentariy TEXT,
    created_by TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_uhody_vypolnenie_proba ON uhody_vypolnenie(proba_id);
"""


def ensure(conn):
    conn.executescript(SCHEMA)
    hvorost.ensure(conn)


def _f(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _r(x):
    return round(x or 0.0, 2)


def _norm(s):
    return "".join(str(s or "").lower().split())


def _norm_lesn(s):
    return _norm(str(s or "").lower().replace("лесничество", ""))


def _data(s):
    s = (s or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _proby(conn):
    """Пробы рубок ухода (без хвороста делянок) с тем, что нужно для сопоставления."""
    out = []
    for pid, kv, vd, pl_v, dz, dj, uids in conn.execute(
            """SELECT id, kvartal, vydel, ploshad_vydela, data_zamera, data_json, lesokultury_uchastok_ids_json
               FROM uhody_proby WHERE delyanka_id IS NULL""").fetchall():
        try:
            data = json.loads(dj) if dj else {}
        except (TypeError, ValueError):
            data = {}
        try:
            uids = set(json.loads(uids) if uids else [])
        except (TypeError, ValueError):
            uids = set()
        out.append({
            "id": pid, "kv": _norm(kv), "vd": _norm(vd), "lesn": _norm_lesn(data.get("lesnichestvo")),
            "uids": uids, "data": _data(dz) or date.min,
            "ploshad": _f(data.get("ploshad_lesoseki")) or _f(pl_v),
            "zapas_na_1ga": _f(data.get("zapas_na_1ga")) or 0.0,
        })
    return out


def _otchety(conn):
    from app.routers import smena
    smena.ensure(conn)
    return conn.execute(
        """SELECT o.id, o.data, o.ga, s.fio, o.lesokultury_uchastok_id,
                  COALESCE(lu.kvartal, di.kvartal), COALESCE(lu.vydel, di.vydel),
                  COALESCE(lu.lesnichestvo, di.lesnichestvo),
                  (SELECT COUNT(*) FROM otchet_smeny_uchastnik u WHERE u.otchet_id = o.id AND u.sotrudnik_id <> o.sotrudnik_id)
           FROM otchet_smeny o
           JOIN sotrudniki s ON s.id = o.sotrudnik_id
           LEFT JOIN lesokultury_uchastok lu ON lu.id = o.lesokultury_uchastok_id
           LEFT JOIN delyanka_item di ON di.id = o.delyanka_item_id
           WHERE o.deleted = 0 AND o.vid = 'rubka_uhoda'
           ORDER BY o.data, o.id""").fetchall()


def raspredelit(conn):
    """{proba_id: [отчёт, ...]} — к какой пробе относится каждый отчёт о рубке ухода."""
    proby = _proby(conn)
    out = {}
    for oid, d, ga, fio, uid, kv, vd, lesn, nap in _otchety(conn):
        dd = _data(d)
        kv, vd, lesn = _norm(kv), _norm(vd), _norm_lesn(lesn)
        best = None
        for p in proby:
            if dd and p["data"] > dd:
                continue
            po_uch = uid is not None and uid in p["uids"]
            po_vyd = kv and vd and p["kv"] == kv and p["vd"] == vd and (not p["lesn"] or not lesn or p["lesn"] == lesn)
            if not (po_uch or po_vyd):
                continue
            if best is None or (p["data"], p["id"]) > (best["data"], best["id"]):
                best = p
        if best:
            out.setdefault(best["id"], []).append({
                "id": oid, "data": d, "ga": _r(ga), "fio": fio, "naparnikov": nap or 0,
            })
    return out


def _ruchnye(conn, proba_ids=None):
    q = "SELECT id, proba_id, data, ga, ispolnitel, kommentariy, created_by FROM uhody_vypolnenie"
    args = []
    if proba_ids is not None:
        if not proba_ids:
            return {}
        q += f" WHERE proba_id IN ({','.join('?' * len(proba_ids))})"
        args = list(proba_ids)
    out = {}
    for rid, pid, d, ga, isp, kom, kto in conn.execute(q + " ORDER BY data, id", args).fetchall():
        out.setdefault(pid, []).append({"id": rid, "data": d, "ga": _r(ga), "ispolnitel": isp,
                                        "kommentariy": kom, "created_by": kto})
    return out


def _itog(p, otchety, ruchnye):
    sdelano = sum(x["ga"] for x in otchety) + sum(x["ga"] for x in ruchnye)
    pl = p["ploshad"]
    m3 = p["zapas_na_1ga"]
    return {
        "ploshad": pl, "zapas_na_1ga": m3,
        "sdelano_ga": _r(sdelano),
        "ostatok_ga": _r(max(pl - sdelano, 0)) if pl else None,
        "pct": round(sdelano / pl * 100) if pl else None,
        "kubov": _r(sdelano * m3),
        "kubov_vsego": _r(pl * m3) if pl else None,
    }


def kratko_vse(conn):
    """{proba_id: итог} — для списка проб."""
    ensure(conn)
    po = raspredelit(conn)
    ru = _ruchnye(conn)
    out = {}
    for p in _proby(conn):
        o, r = po.get(p["id"], []), ru.get(p["id"], [])
        if o or r:
            out[p["id"]] = _itog(p, o, r)
    return out


def svodka(conn, proba_id):
    ensure(conn)
    p = next((x for x in _proby(conn) if x["id"] == proba_id), None)
    if p is None:
        return None
    o = raspredelit(conn).get(proba_id, [])
    r = _ruchnye(conn, [proba_id]).get(proba_id, [])
    for x in o:
        x["kubov"] = _r(x["ga"] * p["zapas_na_1ga"])
    for x in r:
        x["kubov"] = _r(x["ga"] * p["zapas_na_1ga"])
    return {"proba_id": proba_id, **_itog(p, o, r), "otchety": o, "ruchnye": r}


def dobavit(conn, proba_id, data, ga, ispolnitel=None, kommentariy=None, created_by=None):
    ensure(conn)
    conn.execute(
        "INSERT INTO uhody_vypolnenie (proba_id, data, ga, ispolnitel, kommentariy, created_by) VALUES (?,?,?,?,?,?)",
        (proba_id, data, ga, (ispolnitel or "").strip()[:200] or None, (kommentariy or "").strip()[:1000] or None,
         created_by))
    conn.commit()


def udalit(conn, vid):
    ensure(conn)
    r = conn.execute("SELECT proba_id FROM uhody_vypolnenie WHERE id=?", (vid,)).fetchone()
    if not r:
        return None
    conn.execute("DELETE FROM uhody_vypolnenie WHERE id=?", (vid,))
    conn.commit()
    return r[0]
