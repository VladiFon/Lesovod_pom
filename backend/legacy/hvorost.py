# -*- coding: utf-8 -*-
"""Хворост делянки (Влад, 04.11.2026).

Документы на хворост делаются так же, как на рубки ухода (проба с
обмером укладок, экран «Рубки ухода»), но относятся к делянке главного
пользования. Такая проба помечается uhody_proby.delyanka_id — она уходит
из списка рубок ухода и не ловит отчёты с телефона.

На делянке выбирается, откуда брать «разрешено» по хворосту:
  - 'mdo'   — «ликвид из кроны» из МДО выдела (по породам);
  - 'proba' — запас м³/га пробы «хворост делянки» × площадь выдела
              (по породам — в той же доле, что в обмере укладок);
  - 'net' / нет записи — не учитывать (как было: хворост без лимита,
              только факт по нарядам).
Лимит попадает в баланс Расхода (сортимент HVOROST) и в акт
освидетельствования (строка «хворост» — «Разрешено»). В итоги деловой и
дров хворост не входит, как и раньше.
"""
from __future__ import annotations

import json

ISTOCHNIKI = ("mdo", "proba", "net")

SCHEMA = """
CREATE TABLE IF NOT EXISTS delyanka_hvorost (
    delyanka_id INTEGER PRIMARY KEY REFERENCES delyanka(id),
    istochnik TEXT NOT NULL DEFAULT 'net',
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""


def ensure(conn):
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(uhody_proby)").fetchall()}
    if cols and "delyanka_id" not in cols:
        conn.execute("ALTER TABLE uhody_proby ADD COLUMN delyanka_id INTEGER REFERENCES delyanka(id)")
        conn.commit()


def _f(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _norm(s):
    return " ".join(str(s or "").replace(" ", "").lower().split())


def istochniki(conn, delyanka_ids):
    """{delyanka_id: 'mdo'|'proba'|'net'}"""
    ids = sorted({d for d in delyanka_ids if d is not None})
    if not ids:
        return {}
    ensure(conn)
    rows = conn.execute(
        f"SELECT delyanka_id, istochnik FROM delyanka_hvorost WHERE delyanka_id IN ({','.join('?' * len(ids))})",
        ids).fetchall()
    out = {d: "net" for d in ids}
    out.update({r[0]: r[1] or "net" for r in rows})
    return out


def set_istochnik(conn, delyanka_id, istochnik):
    if istochnik not in ISTOCHNIKI:
        raise ValueError("Источник хвороста: mdo, proba или net")
    ensure(conn)
    conn.execute(
        """INSERT INTO delyanka_hvorost (delyanka_id, istochnik, updated_at) VALUES (?, ?, datetime('now','localtime'))
           ON CONFLICT(delyanka_id) DO UPDATE SET istochnik=excluded.istochnik, updated_at=excluded.updated_at""",
        (delyanka_id, istochnik))
    conn.commit()


def proby_delyanok(conn, delyanka_ids):
    """{delyanka_id: [{id, kvartal, vydel, data_zamera, zapas_na_1ga, doli: {порода: доля}}]} — новые сверху."""
    ids = sorted({d for d in delyanka_ids if d is not None})
    if not ids:
        return {}
    ensure(conn)
    out = {}
    for pid, did, kv, vd, dz, dj in conn.execute(
            f"""SELECT id, delyanka_id, kvartal, vydel, data_zamera, data_json FROM uhody_proby
                WHERE delyanka_id IN ({','.join('?' * len(ids))}) ORDER BY id DESC""", ids).fetchall():
        try:
            data = json.loads(dj) if dj else {}
        except (TypeError, ValueError):
            data = {}
        po = {}
        for r in data.get("rows") or []:
            z = _f(r.get("zapas")) or 0
            if z > 0:
                p = (r.get("poroda") or "").strip()
                p = p if p and p != "—" else "Хворост"
                po[p] = po.get(p, 0) + z
        vsego = sum(po.values())
        out.setdefault(did, []).append({
            "id": pid, "kvartal": kv, "vydel": vd, "data_zamera": dz,
            "zapas_na_1ga": _f(data.get("zapas_na_1ga")) or 0.0,
            "doli": {p: z / vsego for p, z in po.items()} if vsego else {"Хворост": 1.0},
        })
    return out


def _proba_dlya_item(proby, item):
    """Проба того же выдела, иначе самая новая на делянке."""
    kv, vd = _norm(item.get("kvartal")), _norm(item.get("vydel"))
    for p in proby:
        if _norm(p["kvartal"]) == kv and _norm(p["vydel"]) == vd:
            return p
    return proby[0] if proby else None


def mdo_po_item(item):
    """{порода: м³} «ликвид из кроны» из МДО выдела."""
    raw = item.get("mdo_raw_json")
    if not raw:
        return {}
    try:
        vol = (json.loads(raw) or {}).get("poroda_volumes") or {}
    except (TypeError, ValueError):
        return {}
    out = {}
    for p, v in vol.items():
        if p == "Итого по лесосеке" or not isinstance(v, dict):
            continue
        x = _f(v.get("likvid_iz_krony")) or 0
        if x > 0:
            out[p] = x
    return out


def limity_batch(conn, items):
    """{item_id: {порода: м³}} — «разрешено» по хворосту для выделов, где он
    учитывается. Выделы делянок без источника в ответ не попадают."""
    items = list(items or [])
    if not items:
        return {}
    try:
        ist = istochniki(conn, [it.get("delyanka_id") for it in items])
    except Exception:  # noqa: BLE001 — таблицы ещё нет (старая БД в тесте)
        return {}
    nuzhny_proby = [d for d, s in ist.items() if s == "proba"]
    proby = proby_delyanok(conn, nuzhny_proby) if nuzhny_proby else {}
    out = {}
    for it in items:
        s = ist.get(it.get("delyanka_id"))
        if s == "mdo":
            lim = mdo_po_item(it)
        elif s == "proba":
            p = _proba_dlya_item(proby.get(it.get("delyanka_id")) or [], it)
            pl = _f(it.get("ploshad")) or 0
            if not p or not pl or not p["zapas_na_1ga"]:
                continue
            vsego = p["zapas_na_1ga"] * pl
            lim = {por: vsego * d for por, d in p["doli"].items()}
        else:
            continue
        if lim:
            out[it["id"]] = lim
    return out
