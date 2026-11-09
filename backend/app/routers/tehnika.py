# -*- coding: utf-8 -*-
"""Справочник «Техника» (просьба Влада 04.11.2026): трактора, харвестеры,
форвардеры, авто, бензопилы. За машиной можно закрепить человека — тогда
в «Отчёте за смену» на телефоне она подставляется сама; работал на чужой —
выбирает из списка. Тип топлива (ДТ / АИ-92) берётся из машины для сводки
«⛽ Топливо» (GET /api/smena/toplivo).

Таблица tehnika создаётся в app/routers/smena.py (ensure) — там же отчёты."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_office_or_master
from app.database import get_conn
from app import putevye
from app.routers import smena

router = APIRouter(prefix="/api/tehnika", tags=["tehnika"])

TIPY = ["Трактор", "Харвестер", "Форвардер", "Автомобиль", "Бензопила", "Другое"]


class TehnikaIn(BaseModel):
    nazvanie: str
    tip: Optional[str] = None
    nomer: Optional[str] = None
    toplivo: Optional[str] = None
    zakreplen_sotrudnik_id: Optional[int] = None
    kommentariy: Optional[str] = None
    # Объём бака, л (просьба Влада 09.11.2026) — для путевых листов: остаток
    # больше бака подсвечивается, «доливать до полного» считает от него.
    bak_l: Optional[float] = None


def _check(conn, b: TehnikaIn):
    if not b.nazvanie.strip():
        raise HTTPException(400, "Название обязательно")
    if b.toplivo and b.toplivo not in smena.TOPLIVO:
        raise HTTPException(400, "Топливо — ДТ или АИ-92")
    if b.zakreplen_sotrudnik_id and not conn.execute(
            "SELECT 1 FROM sotrudniki WHERE id=?", (b.zakreplen_sotrudnik_id,)).fetchone():
        raise HTTPException(404, "Сотрудник не найден")
    if b.bak_l is not None and not (0 <= b.bak_l <= 5000):
        raise HTTPException(400, "Объём бака — от 0 до 5000 л")


def _vals(b: TehnikaIn):
    return (b.nazvanie.strip()[:80], (b.tip or "").strip()[:40] or None, (b.nomer or "").strip()[:40] or None,
            b.toplivo or None, b.zakreplen_sotrudnik_id or None, (b.kommentariy or "").strip()[:500] or None,
            b.bak_l or None)


@router.get("")
def spisok(vse: bool = False, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    putevye.ensure(conn)
    rows = conn.execute(
        f"""SELECT t.id, t.nazvanie, t.tip, t.nomer, t.toplivo, t.zakreplen_sotrudnik_id, s.fio, t.kommentariy, t.aktivna, t.bak_l,
                   (SELECT MAX(data) FROM otchet_smeny o WHERE o.deleted=0 AND o.tehnika_id=t.id),
                   (SELECT COUNT(*) FROM otchet_smeny o WHERE o.deleted=0 AND o.tehnika_id=t.id)
            FROM tehnika t LEFT JOIN sotrudniki s ON s.id = t.zakreplen_sotrudnik_id
            {'' if vse else 'WHERE t.aktivna=1'} ORDER BY t.aktivna DESC, t.tip, t.nazvanie""").fetchall()
    return {"tehnika": [{"id": r[0], "nazvanie": r[1], "tip": r[2], "nomer": r[3], "toplivo": r[4],
                         "zakreplen_sotrudnik_id": r[5], "zakreplen": r[6], "kommentariy": r[7], "aktivna": bool(r[8]),
                         "bak_l": r[9], "posledniy_otchet": r[10], "otchetov": r[11]} for r in rows],
            "tipy": TIPY, "toplivo": list(smena.TOPLIVO),
            "lyudi": [{"id": i, "fio": f, "dolzhnost": d} for i, f, d in conn.execute(
                "SELECT id, fio, dolzhnost FROM sotrudniki WHERE is_active=1 ORDER BY fio").fetchall()]}


@router.post("")
def sozdat(b: TehnikaIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    putevye.ensure(conn)
    _check(conn, b)
    cur = conn.execute("INSERT INTO tehnika (nazvanie, tip, nomer, toplivo, zakreplen_sotrudnik_id, kommentariy, bak_l) "
                       "VALUES (?,?,?,?,?,?,?)", _vals(b))
    conn.commit()
    return {"id": cur.lastrowid}


@router.put("/{tid}")
def izmenit(tid: int, b: TehnikaIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    putevye.ensure(conn)
    _check(conn, b)
    if not conn.execute("SELECT 1 FROM tehnika WHERE id=?", (tid,)).fetchone():
        raise HTTPException(404, "Техника не найдена")
    conn.execute("UPDATE tehnika SET nazvanie=?, tip=?, nomer=?, toplivo=?, zakreplen_sotrudnik_id=?, kommentariy=?, "
                 "bak_l=? WHERE id=?", (*_vals(b), tid))
    conn.commit()
    return {"ok": True}


@router.post("/{tid}/aktivna")
def aktivna(tid: int, on: bool = True, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    """Списать (on=false) / вернуть машину. Не удаляем — на неё ссылаются отчёты."""
    putevye.ensure(conn)
    cur = conn.execute("UPDATE tehnika SET aktivna=? WHERE id=?", (1 if on else 0, tid))
    if not cur.rowcount:
        raise HTTPException(404, "Техника не найдена")
    conn.commit()
    return {"ok": True}
