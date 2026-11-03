# -*- coding: utf-8 -*-
"""«Перекличка» — игровой ввод табеля (просьба Влада 03.11.2026).

Обычный «Ввод табеля» не меняется, это ещё одна вкладка того же экрана.
Пишет в ту же таблицу tabel_zapis через тот же POST /api/tabel/day.

Важное от Влада: бригады у нас не «назначаются на делянку» — одна бригада
может работать на разных делянках, а пара-тройка людей всё время работает
вместе и делает разную работу. Поэтому место в табель НЕ берётся из
распределения бригад. Вместо этого:

* «Звенья» (tabel_zveno) — свои группы людей, которые обычно вместе;
  отмечаешь звено целиком одним действием (где + что).
* «Как в прошлый раз» — у каждого его последняя запись табеля до этой
  даты (место, вид работы, статус).
* «Частые места» — что чаще всего ставили за последние 30 дней
  (делянка/культура + вид работы), одной кнопкой.
* Подсказка звеньев — кто чаще всего работал в один день на одном месте.
* Счёт: дней в этом месяце у каждого, «табель полный N рабочих дней
  подряд»."""
import json
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import webext
import webext

from app.auth import require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/tabel-igra", tags=["tabel-igra"])

SCHEMA = """
CREATE TABLE IF NOT EXISTS tabel_zveno (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT NOT NULL,
    emoji TEXT DEFAULT '🪓',
    sostav TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""

CHASTYE_DNEY = 30
PODSKAZKA_DNEY = 60
PODSKAZKA_MIN_DNEY = 5


def ensure(conn):
    conn.executescript(SCHEMA)


def _iso(s):
    try:
        return datetime.strptime(s or "", "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Дата в формате ГГГГ-ММ-ДД")


def _mesto_label(r):
    """r: dict с d_kvartal/d_vydel/d_nazvanie или lku_* — подпись места."""
    if r.get("delyanka_item_id"):
        return f"кв.{r.get('d_kvartal') or '—'} выд.{r.get('d_vydel') or '—'}"
    if r.get("lesokultury_uchastok_id"):
        por = r.get("lku_poroda")
        return f"🌱 кв.{r.get('lku_kvartal') or '—'} выд.{r.get('lku_vydel') or '—'}" + (f" · {por}" if por else "")
    return ""


_ZAPIS_SQL = """
    SELECT tz.sotrudnik_id, tz.data, tz.status, tz.delyanka_item_id, tz.lesokultury_uchastok_id,
           tz.vid_raboty_id, v.nazvanie, di.kvartal, di.vydel, lku.kvartal, lku.vydel, lku.glavnaya_poroda
    FROM tabel_zapis tz
    LEFT JOIN delyanka_item di ON di.id = tz.delyanka_item_id
    LEFT JOIN lesokultury_uchastok lku ON lku.id = tz.lesokultury_uchastok_id
    LEFT JOIN vidy_rabot v ON v.id = tz.vid_raboty_id
"""


def _zapis(row):
    r = {
        "sotrudnik_id": row[0], "data": row[1], "status": row[2], "delyanka_item_id": row[3],
        "lesokultury_uchastok_id": row[4], "vid_raboty_id": row[5], "vid_raboty": row[6],
        "d_kvartal": row[7], "d_vydel": row[8], "lku_kvartal": row[9], "lku_vydel": row[10], "lku_poroda": row[11],
    }
    r["mesto"] = _mesto_label(r)
    return r


def proshloe(conn, data):
    """Последняя запись табеля каждого сотрудника ДО даты."""
    rows = conn.execute(
        _ZAPIS_SQL + """
        JOIN (SELECT sotrudnik_id sid, MAX(data) md FROM tabel_zapis WHERE data < ? GROUP BY sotrudnik_id) last
          ON last.sid = tz.sotrudnik_id AND last.md = tz.data""",
        (data,),
    ).fetchall()
    return {r[0]: _zapis(r) for r in rows}


def chastye_mesta(conn, data, limit=10):
    ot = (_iso(data) - timedelta(days=CHASTYE_DNEY)).isoformat()
    rows = conn.execute(
        _ZAPIS_SQL + """
        WHERE tz.status = 'работал' AND tz.data >= ? AND tz.data <= ?
          AND (tz.delyanka_item_id IS NOT NULL OR tz.lesokultury_uchastok_id IS NOT NULL)""",
        (ot, data),
    ).fetchall()
    cnt, primer = {}, {}
    for row in rows:
        z = _zapis(row)
        k = (z["delyanka_item_id"], z["lesokultury_uchastok_id"], z["vid_raboty_id"])
        cnt[k] = cnt.get(k, 0) + 1
        primer.setdefault(k, z)
    out = []
    for k, n in sorted(cnt.items(), key=lambda x: -x[1])[:limit]:
        z = primer[k]
        out.append({
            "delyanka_item_id": z["delyanka_item_id"], "lesokultury_uchastok_id": z["lesokultury_uchastok_id"],
            "vid_raboty_id": z["vid_raboty_id"], "vid_raboty": z["vid_raboty"], "mesto": z["mesto"], "raz": n,
        })
    return out


def podskazka_zvenev(conn, data, zvenya):
    """Составы, которые чаще всего работали вместе: один день + одно место =
    одна «команда». Считаем одинаковые составы целиком (пара, тройка…) и
    предлагаем те, что встречались ≥ PODSKAZKA_MIN_DNEY раз и ещё не
    сохранены звеном (и не входят в звено целиком)."""
    ot = (_iso(data) - timedelta(days=PODSKAZKA_DNEY)).isoformat()
    rows = conn.execute(
        """SELECT data, COALESCE('d' || delyanka_item_id, 'l' || lesokultury_uchastok_id), sotrudnik_id
           FROM tabel_zapis WHERE status='работал' AND data >= ? AND data < ?
             AND (delyanka_item_id IS NOT NULL OR lesokultury_uchastok_id IS NOT NULL)""",
        (ot, data),
    ).fetchall()
    gruppy = {}
    for d, m, sid in rows:
        gruppy.setdefault((d, m), set()).add(sid)
    sostavy = {}
    for lyudi in gruppy.values():
        if len(lyudi) >= 2:
            k = frozenset(lyudi)
            sostavy[k] = sostavy.get(k, 0) + 1
    est = [set(z["sostav"]) for z in zvenya]
    out = []
    for k, n in sorted(sostavy.items(), key=lambda x: (-x[1], -len(x[0]))):
        if n < PODSKAZKA_MIN_DNEY or any(set(k) <= e for e in est):
            continue
        out.append({"sostav": sorted(k), "dney": n})
        if len(out) >= 4:
            break
    return out


def seriya_polnogo(conn, data, aktivnyh):
    """Рабочих дней подряд (до даты, сама дата — если уже полная), когда в
    табеле есть все активные сотрудники. Выходные серию не рвут."""
    if not aktivnyh:
        return 0
    ot = (_iso(data) - timedelta(days=120)).isoformat()
    po_dnyam = dict(conn.execute(
        "SELECT data, COUNT(*) FROM tabel_zapis WHERE data >= ? AND data <= ? GROUP BY data", (ot, data)
    ).fetchall())
    d = _iso(data)
    if (po_dnyam.get(d.isoformat()) or 0) < aktivnyh:
        d -= timedelta(days=1)
    n = 0
    for _ in range(120):
        if (po_dnyam.get(d.isoformat()) or 0) >= aktivnyh:
            n += 1
        elif d.weekday() < 5:
            break
        d -= timedelta(days=1)
    return n


def spisok_zvenev(conn):
    ensure(conn)
    return [
        {"id": r[0], "nazvanie": r[1], "emoji": r[2] or "🪓", "sostav": json.loads(r[3] or "[]")}
        for r in conn.execute("SELECT id, nazvanie, emoji, sostav FROM tabel_zveno ORDER BY id").fetchall()
    ]


@router.get("/den")
def den(data: str, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    d = _iso(data)
    lyudi = webext.get_tabel_day(conn, data)
    conn.row_factory = None
    pr = proshloe(conn, data)
    mesyac = dict(conn.execute(
        "SELECT sotrudnik_id, COUNT(*) FROM tabel_zapis WHERE status='работал' AND data >= ? AND data <= ? "
        "GROUP BY sotrudnik_id", (d.replace(day=1).isoformat(), data),
    ).fetchall())
    for r in lyudi:
        r["mesto"] = _mesto_label({
            "delyanka_item_id": r.get("delyanka_item_id"), "d_kvartal": r.get("d_kvartal"), "d_vydel": r.get("d_vydel"),
            "lesokultury_uchastok_id": r.get("lesokultury_uchastok_id"), "lku_kvartal": r.get("lku_kvartal"),
            "lku_vydel": r.get("lku_vydel"), "lku_poroda": r.get("lku_glavnaya_poroda"),
        })
        r["proshloe"] = pr.get(r["sotrudnik_id"])
        r["dney_v_mesyace"] = mesyac.get(r["sotrudnik_id"], 0)
    zvenya = spisok_zvenev(conn)
    return {
        "data": data,
        "lyudi": lyudi,
        "zvenya": zvenya,
        "chastye": chastye_mesta(conn, data),
        "podskazka": podskazka_zvenev(conn, data, zvenya),
        "vidy_rabot": webext.list_vidy_rabot(conn),
        "seriya": seriya_polnogo(conn, data, len(lyudi)),
    }


class ZvenoIn(BaseModel):
    nazvanie: str
    emoji: Optional[str] = "🪓"
    sostav: List[int]


def _check(body: ZvenoIn):
    naz = (body.nazvanie or "").strip()
    if not naz:
        raise HTTPException(400, "Назови звено")
    if len(set(body.sostav)) < 1:
        raise HTTPException(400, "В звене должен быть хотя бы один человек")
    return naz[:60], (body.emoji or "🪓")[:8], json.dumps(sorted(set(body.sostav)))


@router.get("/zvenya")
def zvenya(user=Depends(require_office_or_master), conn=Depends(get_conn)):
    return spisok_zvenev(conn)


@router.post("/zvenya")
def sozdat_zveno(body: ZvenoIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    ensure(conn)
    naz, em, sost = _check(body)
    cur = conn.execute("INSERT INTO tabel_zveno (nazvanie, emoji, sostav) VALUES (?,?,?)", (naz, em, sost))
    conn.commit()
    return {"id": cur.lastrowid}


@router.put("/zvenya/{zid}")
def izmenit_zveno(zid: int, body: ZvenoIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    ensure(conn)
    naz, em, sost = _check(body)
    cur = conn.execute("UPDATE tabel_zveno SET nazvanie=?, emoji=?, sostav=? WHERE id=?", (naz, em, sost, zid))
    if not cur.rowcount:
        raise HTTPException(404, "Звено не найдено")
    conn.commit()
    return {"ok": True}


@router.delete("/zvenya/{zid}")
def udalit_zveno(zid: int, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    ensure(conn)
    conn.execute("DELETE FROM tabel_zveno WHERE id=?", (zid,))
    conn.commit()
    return {"ok": True}
