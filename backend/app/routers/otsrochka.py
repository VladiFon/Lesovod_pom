# -*- coding: utf-8 -*-
"""Отсрочка по срокам заготовки/вывозки (просьба Влада 03.11.2026).

Срок делянки подходит к концу, а заготовка не закончена — надо брать
отсрочку. Здесь:

* GET  /api/otsrochka/kandidaty        — делянки, которым нужна отсрочка:
  активные, срок заготовки прошёл или подходит (за N дней), площадь по
  нарядам не пройдена и есть что рубить; с остатком м³ (деловая / дрова /
  всего) и га. Тот же расчёт освоения, что «Освоение делянки» (большее из
  нарядов и ЕГАИС по каждому сортименту).
* GET  /api/otsrochka/kandidaty.xlsx   — то же Excel-файлом (к заявлению).
* POST /api/otsrochka                  — ввести отсрочку одной или
  нескольким делянкам: новые сроки заготовки/вывозки + основание.
* GET  /api/otsrochka/{id}, DELETE /api/otsrochka/{id}/poslednyaya —
  история и отмена последней (сроки возвращаются прежние).

Новые сроки пишутся прямо в delyanka.srok_okonchaniya_*, поэтому Инспекция
(срок акта = вывозка + 30), колокольчик, Распределение бригад и бланк акта
сразу работают по продлённым срокам. Прежние даты хранятся в истории."""
import io
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401
import db as legacy_db
import raskhod_v2

from app import etap, storonnyaya
from app.auth import get_current_user, require_permission
from app.database import get_conn

router = APIRouter(prefix="/api/otsrochka", tags=["otsrochka"])

SCHEMA = """
CREATE TABLE IF NOT EXISTS delyanka_otsrochka (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delyanka_id INTEGER NOT NULL REFERENCES delyanka(id),
    prezhniy_srok_zagotovki TEXT,
    prezhniy_srok_vyvozki TEXT,
    novyy_srok_zagotovki TEXT,
    novyy_srok_vyvozki TEXT,
    osnovanie TEXT,
    kto TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_delyanka_otsrochka ON delyanka_otsrochka(delyanka_id, id);
"""

DELOVAYA = ("KR", "SR", "ML")
OSTATOK_MIN_M3 = 0.5  # меньше — «дорубили», отсрочка не нужна


def ensure(conn) -> None:
    conn.executescript(SCHEMA)


def _d(s) -> Optional[date]:
    s = str(s or "").strip()[:10]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _ru(s) -> Optional[str]:
    """«2026-12-31» / «31.12.2026» → «31.12.2026»; None — не дата."""
    d = _d(s)
    return d.strftime("%d.%m.%Y") if d else None


def istoriya(conn, ids) -> dict:
    ensure(conn)
    ids = list(ids)
    out: dict = {}
    if not ids:
        return out
    ph = ",".join("?" * len(ids))
    cols = ["id", "delyanka_id", "prezhniy_srok_zagotovki", "prezhniy_srok_vyvozki",
            "novyy_srok_zagotovki", "novyy_srok_vyvozki", "osnovanie", "kto", "created_at"]
    for r in conn.execute(
        f"SELECT {', '.join(cols)} FROM delyanka_otsrochka WHERE delyanka_id IN ({ph}) ORDER BY id",
        ids,
    ).fetchall():
        row = dict(zip(cols, r))
        out.setdefault(row["delyanka_id"], []).append(row)
    return out


def _ostatki(conn, ids) -> dict:
    """{id: {limit, fakt, ostatok, delovaya, drova}} — остаток = лимит − факт,
    факт по каждому сортименту — большее из нарядов и ЕГАИС (как в
    «Освоении делянки», чтобы не попросить меньше, чем реально осталось)."""
    items_by_d = raskhod_v2.get_delyanka_items_batch(conn, ids)
    all_items = [it for d in ids for it in items_by_d.get(d, [])]
    balances = raskhod_v2.compute_balance_batch(conn, all_items) if all_items else {}
    out = {}
    for d in ids:
        lim = {"delovaya": 0.0, "drova": 0.0}
        fakt = {"delovaya": 0.0, "drova": 0.0}
        for it in items_by_d.get(d, []):
            for _poroda, sortimenty in (balances.get(it["id"]) or {}).items():
                for code in DELOVAYA + ("DROVA",):
                    v = sortimenty.get(code)
                    if not v:
                        continue
                    g = "drova" if code == "DROVA" else "delovaya"
                    lim[g] += v.get("limit") or 0
                    fakt[g] += max(v.get("fakt") or 0, v.get("fakt_egais") or 0)
        ost = {g: max(lim[g] - fakt[g], 0.0) for g in lim}
        out[d] = {
            "limit": round(lim["delovaya"] + lim["drova"], 2),
            "fakt": round(fakt["delovaya"] + fakt["drova"], 2),
            "ostatok_delovaya": round(ost["delovaya"], 2),
            "ostatok_drova": round(ost["drova"], 2),
            "ostatok": round(ost["delovaya"] + ost["drova"], 2),
            "vydely": ", ".join(
                f"кв.{it.get('kvartal') or '—'} выд.{it.get('vydel') or '—'}" for it in items_by_d.get(d, [])),
            "lesnichestvo": ", ".join(sorted({(it.get("lesnichestvo") or "").strip()
                                              for it in items_by_d.get(d, []) if it.get("lesnichestvo")})),
        }
    return out


def kandidaty(conn, dney: int = 30, segodnya: Optional[date] = None) -> List[dict]:
    """Активные делянки: срок заготовки прошёл или наступит за `dney` дней,
    акта нет, площадь не пройдена, остаток ≥ OSTATOK_MIN_M3 м³ (или лимита
    нет, но площадь не пройдена). Сначала самые срочные."""
    segodnya = segodnya or date.today()
    granica = segodnya + timedelta(days=dney)
    rows = conn.execute(
        "SELECT id, nazvanie, status, srok_okonchaniya_zagotovki, srok_okonchaniya_vyvozki, "
        "nomer_lesorubochnogo_bileta, data_lesorubochnogo_bileta FROM delyanka WHERE status = 'активна'"
    ).fetchall()
    podkhodyat = []
    for did, nazv, status, zag, vyv, bilet, bilet_data in rows:
        srok = _d(zag)
        if srok and srok <= granica:
            podkhodyat.append({"id": did, "nazvanie": nazv, "status": status, "srok_zagotovki": zag,
                               "srok_vyvozki": vyv, "bilet": bilet, "bilet_data": _ru(bilet_data) or bilet_data,
                               "_srok": srok})
    if not podkhodyat:
        return []
    ids = [r["id"] for r in podkhodyat]
    et = etap.etapy(conn, podkhodyat)
    ost = _ostatki(conn, ids)
    st = storonnyaya.load(conn, ids)
    ist = istoriya(conn, ids)
    from app.routers import inspection
    items_by_d = raskhod_v2.get_delyanka_items_batch(conn, ids)
    acts = legacy_db.list_osvidetelstvovanie_acts_batch(conn, ids)
    pl = inspection._ploshad_po_naryadam(conn, podkhodyat, items_by_d, acts)
    out = []
    for r in podkhodyat:
        e = et.get(r["id"]) or {}
        if e.get("kod") in ("dorublena", "osvid"):
            continue  # площадь пройдена или акт уже есть — рубить нечего
        o = ost.get(r["id"]) or {}
        if o.get("limit") and o.get("ostatok", 0) < OSTATOK_MIN_M3:
            continue
        p = pl.get(r["id"]) or {}
        dney_ostalos = (r["_srok"] - segodnya).days
        out.append({
            **{k: v for k, v in r.items() if not k.startswith("_")},
            "dney_ostalos": dney_ostalos,
            "prosrochen": dney_ostalos < 0,
            "etap": e,
            "storonnyaya": storonnyaya.kratko(st.get(r["id"])),
            **o,
            "ploshad_vsego": p.get("ploshad_vsego"),
            "ploshad_ostatok": p.get("ploshad_ostatok"),
            "otsrochek": len(ist.get(r["id"], [])),
        })
    out.sort(key=lambda x: (x["dney_ostalos"], x["nazvanie"] or ""))
    return out


@router.get("/kandidaty")
def get_kandidaty(dney: int = 30, conn=Depends(get_conn), _user=Depends(get_current_user)):
    return kandidaty(conn, max(0, min(dney, 365)))


@router.get("/kandidaty.xlsx")
def get_kandidaty_xlsx(dney: int = 30, conn=Depends(get_conn), _user=Depends(get_current_user)):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    rows = kandidaty(conn, max(0, min(dney, 365)))
    wb = Workbook()
    ws = wb.active
    ws.title = "Отсрочка"
    ws.append([f"Делянки, по которым нужна отсрочка (срок заготовки до {(date.today() + timedelta(days=dney)):%d.%m.%Y}), "
               f"сформировано {date.today():%d.%m.%Y}"])
    ws["A1"].font = Font(bold=True)
    head = ["№", "Делянка", "Лесничество", "Квартал / выдел", "Лесорубочный билет", "Срок заготовки",
            "Срок вывозки", "Дней до срока", "Лимит, м³", "Заготовлено, м³", "Осталось деловой, м³",
            "Осталось дров, м³", "Осталось всего, м³", "Площадь, га", "Осталось, га", "Заготовитель", "Отсрочек было"]
    ws.append(head)
    for c in ws[2]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for i, r in enumerate(rows, 1):
        ws.append([
            i, r["nazvanie"], r.get("lesnichestvo"), r.get("vydely"),
            " от ".join(x for x in (r.get("bilet"), r.get("bilet_data")) if x) or None,
            r["srok_zagotovki"], r["srok_vyvozki"], r["dney_ostalos"],
            r.get("limit"), r.get("fakt"), r.get("ostatok_delovaya"), r.get("ostatok_drova"), r.get("ostatok"),
            r.get("ploshad_vsego"), r.get("ploshad_ostatok"),
            (r.get("storonnyaya") or {}).get("zagotovitel") or "мы", r.get("otsrochek"),
        ])
    if rows:
        n = len(rows) + 2
        ws.append(["", "Итого", "", "", "", "", "", "",
                   f"=SUM(I3:I{n})", f"=SUM(J3:J{n})", f"=SUM(K3:K{n})", f"=SUM(L3:L{n})", f"=SUM(M3:M{n})",
                   f"=SUM(N3:N{n})", f"=SUM(O3:O{n})"])
        for c in ws[n + 1]:
            c.font = Font(bold=True)
    for col, w in zip("ABCDEFGHIJKLMNOPQ", (4, 28, 18, 26, 20, 12, 12, 9, 10, 11, 11, 10, 11, 9, 9, 18, 9)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    name = f"otsrochka_{date.today():%Y-%m-%d}.xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


class OtsrochkaIn(BaseModel):
    ids: List[int]
    srok_zagotovki: Optional[str] = None
    srok_vyvozki: Optional[str] = None
    osnovanie: str = ""


@router.post("")
def vvesti_otsrochku(body: OtsrochkaIn, user=Depends(require_permission("inspection.edit")),
                     conn=Depends(get_conn)):
    if not body.ids:
        raise HTTPException(400, "Не выбраны делянки")
    zag = _ru(body.srok_zagotovki) if (body.srok_zagotovki or "").strip() else None
    vyv = _ru(body.srok_vyvozki) if (body.srok_vyvozki or "").strip() else None
    if (body.srok_zagotovki or "").strip() and not zag:
        raise HTTPException(400, "Новый срок заготовки — дата ДД.ММ.ГГГГ")
    if (body.srok_vyvozki or "").strip() and not vyv:
        raise HTTPException(400, "Новый срок вывозки — дата ДД.ММ.ГГГГ")
    if not zag and not vyv:
        raise HTTPException(400, "Укажите новый срок заготовки и/или вывозки")
    if zag and vyv and _d(vyv) < _d(zag):
        raise HTTPException(400, "Срок вывозки не может быть раньше срока заготовки")
    ensure(conn)
    sdelano = 0
    for did in dict.fromkeys(body.ids):
        old_zag, old_vyv = legacy_db.get_delyanka_sroki(conn, did)
        if conn.execute("SELECT 1 FROM delyanka WHERE id=?", (did,)).fetchone() is None:
            continue
        legacy_db.set_delyanka_sroki(conn, did, zag or old_zag, vyv or old_vyv)
        conn.execute(
            "INSERT INTO delyanka_otsrochka (delyanka_id, prezhniy_srok_zagotovki, prezhniy_srok_vyvozki, "
            "novyy_srok_zagotovki, novyy_srok_vyvozki, osnovanie, kto) VALUES (?,?,?,?,?,?,?)",
            (did, old_zag, old_vyv, zag or old_zag, vyv or old_vyv, body.osnovanie.strip() or None, user["login"]),
        )
        sdelano += 1
    conn.commit()
    return {"ok": True, "sdelano": sdelano}


@router.get("/{delyanka_id}")
def get_istoriya(delyanka_id: int, conn=Depends(get_conn), _user=Depends(get_current_user)):
    return list(reversed(istoriya(conn, [delyanka_id]).get(delyanka_id, [])))


@router.delete("/{delyanka_id}/poslednyaya")
def otmenit_poslednyuyu(delyanka_id: int, user=Depends(require_permission("inspection.edit")),
                        conn=Depends(get_conn)):
    """Ошибочно ввели — вернуть сроки, которые были до последней отсрочки."""
    ensure(conn)
    row = conn.execute(
        "SELECT id, prezhniy_srok_zagotovki, prezhniy_srok_vyvozki FROM delyanka_otsrochka "
        "WHERE delyanka_id=? ORDER BY id DESC LIMIT 1", (delyanka_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Отсрочек по делянке нет")
    legacy_db.set_delyanka_sroki(conn, delyanka_id, row[1], row[2])
    conn.execute("DELETE FROM delyanka_otsrochka WHERE id=?", (row[0],))
    conn.commit()
    return {"ok": True}
