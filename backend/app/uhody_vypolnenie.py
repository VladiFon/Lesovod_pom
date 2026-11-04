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
    # исполнитель ссылкой на справочник (карточка человека, 04.11.2026)
    if not any(r[1] == "ispolnitel_id" for r in conn.execute("PRAGMA table_info(uhody_vypolnenie)").fetchall()):
        conn.execute("ALTER TABLE uhody_vypolnenie ADD COLUMN ispolnitel_id INTEGER")
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
                  (SELECT COUNT(*) FROM otchet_smeny_uchastnik u WHERE u.otchet_id = o.id AND u.sotrudnik_id <> o.sotrudnik_id),
                  o.uhody_proba_id, o.sotrudnik_id
           FROM otchet_smeny o
           JOIN sotrudniki s ON s.id = o.sotrudnik_id
           LEFT JOIN lesokultury_uchastok lu ON lu.id = o.lesokultury_uchastok_id
           LEFT JOIN delyanka_item di ON di.id = o.delyanka_item_id
           WHERE o.deleted = 0 AND o.vid = 'rubka_uhoda'
           ORDER BY o.data, o.id""").fetchall()


def raspredelit(conn):
    """{proba_id: [отчёт, ...]} — к какой пробе относится каждый отчёт о рубке ухода."""
    proby = _proby(conn)
    po_id = {p["id"]: p for p in proby}
    out = {}
    for oid, d, ga, fio, uid, kv, vd, lesn, nap, pid, sid in _otchety(conn):
        if pid:  # телефон 0.11.2+: отчёт сразу по пробе
            if pid in po_id:
                out.setdefault(pid, []).append({"id": oid, "data": d, "ga": _r(ga), "fio": fio, "sotrudnik_id": sid, "naparnikov": nap or 0})
            continue
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
                "id": oid, "data": d, "ga": _r(ga), "fio": fio, "sotrudnik_id": sid, "naparnikov": nap or 0,
            })
    return out


def _ruchnye(conn, proba_ids=None):
    q = "SELECT id, proba_id, data, ga, ispolnitel, kommentariy, created_by, ispolnitel_id FROM uhody_vypolnenie"
    args = []
    if proba_ids is not None:
        if not proba_ids:
            return {}
        q += f" WHERE proba_id IN ({','.join('?' * len(proba_ids))})"
        args = list(proba_ids)
    out = {}
    for rid, pid, d, ga, isp, kom, kto, isp_id in conn.execute(q + " ORDER BY data, id", args).fetchall():
        out.setdefault(pid, []).append({"id": rid, "data": d, "ga": _r(ga), "ispolnitel": isp, "ispolnitel_id": isp_id,
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
    zak = conn.execute("SELECT completed_at FROM uhody_proby WHERE id=?", (proba_id,)).fetchone()
    return {"proba_id": proba_id, **_itog(p, o, r), "otchety": o, "ruchnye": r,
            "zakryta": bool(zak and zak[0]), "zakryta_data": zak[0] if zak else None}


def dobavit(conn, proba_id, data, ga, ispolnitel=None, kommentariy=None, created_by=None):
    ensure(conn)
    from app.raboty_sotrudnika import najti_po_fio
    isp = (ispolnitel or "").strip()[:200] or None
    conn.execute(
        "INSERT INTO uhody_vypolnenie (proba_id, data, ga, ispolnitel, kommentariy, created_by, ispolnitel_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (proba_id, data, ga, isp, (kommentariy or "").strip()[:1000] or None, created_by,
         najti_po_fio(conn, isp) if isp else None))
    conn.commit()


def udalit(conn, vid):
    ensure(conn)
    r = conn.execute("SELECT proba_id FROM uhody_vypolnenie WHERE id=?", (vid,)).fetchone()
    if not r:
        return None
    conn.execute("DELETE FROM uhody_vypolnenie WHERE id=?", (vid,))
    conn.commit()
    return r[0]


def dlya_telefona(conn, sid=None):
    """Пробы рубок ухода для отчёта смены на телефоне: где сколько сделано и
    осталось. Незаконченные сверху, свежие замеры раньше."""
    ensure(conn)
    po = raspredelit(conn)
    ru = _ruchnye(conn)
    info = {r[0]: r[1:] for r in conn.execute(
        "SELECT id, data_json, completed_at, lesokultury_uchastok_ids_json, data_zamera FROM uhody_proby WHERE delyanka_id IS NULL"
    ).fetchall()}
    moi = {}
    if sid:
        for pid, d in conn.execute(
                """SELECT uhody_proba_id, MAX(data) FROM otchet_smeny WHERE deleted=0 AND uhody_proba_id IS NOT NULL
                   AND (sotrudnik_id=? OR id IN (SELECT otchet_id FROM otchet_smeny_uchastnik WHERE sotrudnik_id=?))
                   GROUP BY uhody_proba_id""", (sid, sid)).fetchall():
            moi[pid] = d
    out = []
    for p in _proby(conn):
        dj, completed, uids, dz = info.get(p["id"], (None, None, None, None))
        if completed:  # закрыта (работы закончены) — на телефоне не нужна
            continue
        try:
            data = json.loads(dj) if dj else {}
        except (TypeError, ValueError):
            data = {}
        it = _itog(p, po.get(p["id"], []), ru.get(p["id"], []))
        kv = conn.execute("SELECT kvartal, vydel FROM uhody_proby WHERE id=?", (p["id"],)).fetchone()
        lesn = (data.get("lesnichestvo") or "").strip()
        vid_rubki = (data.get("vid_rubki") or "").strip()
        label = f"кв.{kv[0] or '—'} выд.{kv[1] or '—'}" + (f" · {lesn}" if lesn else "") + f" · проба №{p['id']}"
        gotovo = bool(completed) or (it["ostatok_ga"] is not None and it["ostatok_ga"] <= 0 and it["sdelano_ga"] > 0)
        out.append({
            "id": p["id"], "kvartal": kv[0], "vydel": kv[1], "label": label, "vid_rubki": vid_rubki or None,
            "data_zamera": dz, "ploshad": it["ploshad"], "zapas_na_1ga": it["zapas_na_1ga"],
            "sdelano": it["sdelano_ga"], "ostatok": it["ostatok_ga"], "kubov": it["kubov"],
            "gotovo": gotovo, "nedavno": moi.get(p["id"]),
            "na_kulturah": bool(json.loads(uids) if uids else []),
        })
    out.sort(key=lambda x: (x["gotovo"], x["nedavno"] is None, -(x["id"])))
    return out


ZAKRYT_DOLYA = 0.98  # как у циклов отчёта смены: округления га


def ispolniteli(conn, proba_id):
    """Кто работал на пробе: (ids сотрудников из отчётов — авторы и
    напарники — и из ручных строк, если ФИО нашлось в справочнике;
    сторонние ФИО из ручных строк)."""
    ensure(conn)
    from app.routers import smena
    smena.ensure(conn)
    otch = [r["id"] for r in raspredelit(conn).get(proba_id, [])]
    ids = []
    if otch:
        ph = ",".join("?" * len(otch))
        for (sid,) in conn.execute(
                f"""SELECT sotrudnik_id FROM otchet_smeny WHERE id IN ({ph})
                    UNION SELECT sotrudnik_id FROM otchet_smeny_uchastnik WHERE otchet_id IN ({ph})""",
                otch + otch).fetchall():
            if sid not in ids:
                ids.append(sid)
    po_fio = {}
    for sid, fio in conn.execute("SELECT id, fio FROM sotrudniki").fetchall():
        po_fio.setdefault(_norm(fio), sid)
    storonnie = []
    for r in _ruchnye(conn, [proba_id]).get(proba_id, []):
        name = " ".join((r.get("ispolnitel") or "").split())
        if not name:
            continue
        sid = po_fio.get(_norm(name))
        if sid:
            if sid not in ids:
                ids.append(sid)
        elif name.casefold() not in {n.casefold() for n in storonnie}:
            storonnie.append(name)
    return ids, storonnie


def proverit_zakrytie(conn, proba_id):
    """Сделана вся площадь пробы (≥98%) — закрываем её сами («выполнена»,
    исполнители — кто работал). Возвращает True, если закрыли сейчас."""
    import db as legacy_db
    r = conn.execute("SELECT completed_at, delyanka_id FROM uhody_proby WHERE id=?", (proba_id,)).fetchone()
    if not r or r[0] or r[1]:
        return False
    sv = svodka(conn, proba_id)
    if not sv or not sv.get("ploshad") or sv["sdelano_ga"] < sv["ploshad"] * ZAKRYT_DOLYA:
        return False
    ids, storonnie = ispolniteli(conn, proba_id)
    if not ids and not storonnie:
        return False
    try:
        legacy_db.mark_uhody_proba_completed(conn, proba_id, ids, storonnie=storonnie)
    except ValueError:
        return False
    return True
