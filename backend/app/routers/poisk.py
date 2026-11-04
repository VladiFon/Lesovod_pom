# -*- coding: utf-8 -*-
"""Общий поиск по сайту (Ctrl+K, шаг 3 разбора «сайт разбросан», 04.11.2026):
люди, делянки, выдел «71/2», участки лесных культур, пробы рубок ухода.
Каждый ответ — {tip, title, hint, screen, params}: куда открыть."""
import re

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401
from app.auth import require_office_or_master
from app.database import get_conn
from app import raboty_sotrudnika as rs

router = APIRouter(prefix="/api/poisk", tags=["poisk"])

KV_VYD = re.compile(r"^\D*?(\d+)\s*(?:[/\\.,:-]|\s+выд\.?|\s+в\.?|\s)\s*(\d+[а-яa-z]?)\s*$", re.I)
PROBA = re.compile(r"^(?:проба|пр\.?)\s*№?\s*(\d+)$", re.I)


def _vydely(s):
    return {x.strip() for x in str(s or "").replace(";", ",").split(",") if x.strip()}


def iskat(conn, q, limit=8):
    q = " ".join((q or "").split())
    if len(q) < 2 and not q.isdigit():
        return []
    out = []
    qcf = q.casefold()

    def add(tip, title, hint, screen, params):
        out.append({"tip": tip, "title": title, "hint": hint, "screen": screen, "params": params})

    m = KV_VYD.match(q)
    kv = vd = None
    if m:
        kv, vd = m.group(1), m.group(2)
        add("vydel", f"Выдел кв.{kv} выд.{vd}", "Жизнь выдела: таксация, рубки, культуры, пробы, кто работал",
            "taxation", {"kv": kv, "vyd": vd})
    elif q.isdigit():
        kv = q

    pm = PROBA.match(q)
    if pm and rs._est_tablica(conn, "uhody_proby"):
        r = conn.execute("SELECT id, kvartal, vydel FROM uhody_proby WHERE id=?", (int(pm.group(1)),)).fetchone()
        if r:
            add("proba", f"Проба рубок ухода №{r[0]}", f"кв.{r[1]} выд.{r[2]}", "uhody", {"p": r[0]})

    # люди
    if not m and not q.isdigit():
        lyudi = [r for r in conn.execute("SELECT id, fio, dolzhnost, is_active FROM sotrudniki").fetchall()
                 if all(w in (r[1] or "").casefold() for w in qcf.split())]
        # сначала те, у кого с запроса начинается фамилия, потом активные
        lyudi.sort(key=lambda r: (not (r[1] or "").casefold().startswith(qcf), not r[3], r[1] or ""))
        for sid, fio, dol, akt in lyudi[:limit]:
            add("chelovek", fio, (dol or "сотрудник") + ("" if akt else " · неактивен"),
                "sotrudniki", {"tab": "kartochka", "s": sid})

    # делянки — по названию или по кварталу/выделу
    n = 0
    vid = set()
    for did, nazv, st, ikv, ivd, les in conn.execute(
            """SELECT d.id, d.nazvanie, d.status, di.kvartal, di.vydel, di.lesnichestvo
               FROM delyanka d LEFT JOIN delyanka_item di ON di.delyanka_id = d.id
               ORDER BY CASE d.status WHEN 'активна' THEN 0 WHEN 'черновик' THEN 1 ELSE 2 END, d.id DESC""").fetchall():
        if did in vid:
            continue
        po_kv = kv and str(ikv or "").strip() == kv and (not vd or vd in _vydely(ivd))
        po_imeni = not m and not q.isdigit() and qcf in (nazv or "").casefold()
        if po_kv or po_imeni:
            vid.add(did)
            add("delyanka", nazv or f"Делянка №{did}",
                ", ".join(x for x in (f"кв.{ikv} выд.{ivd}" if ikv else None, les, st) if x), "plots", {"d": did})
            n += 1
            if n >= limit:
                break

    # лесные культуры и пробы — по кварталу/выделу
    if kv:
        if rs._est_tablica(conn, "lesokultury_uchastok"):
            n = 0
            for uid, ukv, uvd, les, god, por, st in conn.execute(
                    "SELECT id, kvartal, vydel, lesnichestvo, god_sozdaniya, glavnaya_poroda, status "
                    "FROM lesokultury_uchastok WHERE TRIM(kvartal) = ? ORDER BY id DESC", (kv,)).fetchall():
                if vd and vd not in _vydely(uvd):
                    continue
                add("kultury", f"Лесные культуры кв.{ukv} выд.{uvd}",
                    ", ".join(x for x in (por, f"{god} г." if god else None, les, st) if x), "forestry", {"u": uid})
                n += 1
                if n >= limit:
                    break
        if rs._est_tablica(conn, "uhody_proby"):
            n = 0
            for pid, pkv, pvd, zak in conn.execute(
                    "SELECT id, kvartal, vydel, completed_at FROM uhody_proby WHERE TRIM(kvartal) = ? ORDER BY id DESC",
                    (kv,)).fetchall():
                if vd and vd not in _vydely(pvd):
                    continue
                add("proba", f"Проба рубок ухода №{pid}", f"кв.{pkv} выд.{pvd}" + (" · закрыта" if zak else ""),
                    "uhody", {"p": pid})
                n += 1
                if n >= limit:
                    break
    return out


@router.get("")
def poisk(q: str = "", user=Depends(require_office_or_master), conn=Depends(get_conn)):
    return {"q": q, "naydeno": iskat(conn, q)}
