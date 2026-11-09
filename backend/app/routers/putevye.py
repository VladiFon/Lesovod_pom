# -*- coding: utf-8 -*-
"""API помощника путевых листов (логика — app/putevye.py).

GET  /api/putevye?tehnika_id=&mesyac=2026-11   — месяц машины: листы, итоги, дни
GET  /api/putevye/mashiny                      — машины с нормой/баком для выбора
PUT  /api/putevye/mashina/{tid}                — бак, ед. учёта, стартовые показания…
POST /api/putevye/mashina/{tid}/norma          — новая норма с даты
DELETE /api/putevye/norma/{nid}
POST /api/putevye/list                         — новый лист (пробег, заправка)
PUT  /api/putevye/list/{lid}                   — правка → пересчёт цепочки дальше
DELETE /api/putevye/list/{lid}
POST /api/putevye/generator                    — черновик «Заполнить месяц» (ничего не пишет)
POST /api/putevye/generator/sohranit           — записать черновик
POST /api/putevye/mesyac/zakryt?tehnika_id=&mesyac=&on=
GET  /api/putevye/svodka?mesyac=               — все машины за месяц
"""
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import putevye as P
from app.auth import require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/putevye", tags=["putevye"])


def _mesyac(s):
    s = (s or date.today().isoformat())[:7]
    try:
        P.mesyac_granicy(s)
    except Exception:
        raise HTTPException(400, "Месяц в виде ГГГГ-ММ")
    return s


def _data(s):
    try:
        return date.fromisoformat(str(s)[:10]).isoformat()
    except Exception:
        raise HTTPException(400, "Дата в виде ГГГГ-ММ-ДД")


def _m(conn, tid):
    m = P.mashina(conn, tid)
    if not m:
        raise HTTPException(404, "Машина не найдена")
    return m


@router.get("/mashiny")
def mashiny(user=Depends(require_office_or_master), conn=Depends(get_conn)):
    P.ensure(conn)
    out = []
    for (tid,) in conn.execute("SELECT id FROM tehnika WHERE aktivna=1 ORDER BY tip, nazvanie").fetchall():
        m = P.mashina(conn, tid)
        nm = P.normy(conn, tid)
        m["norma"] = P.norma_na(nm, date.today().isoformat())
        m["listov"] = conn.execute("SELECT COUNT(*) FROM putevoy_list WHERE tehnika_id=?", (tid,)).fetchone()[0]
        out.append(m)
    lyudi = [{"id": i, "fio": f} for i, f in conn.execute(
        "SELECT id, fio FROM sotrudniki WHERE is_active=1 ORDER BY fio").fetchall()]
    return {"mashiny": out, "lyudi": lyudi, "edinicy": list(P.EDINICY)}


@router.get("")
def mesyac(tehnika_id: int, mesyac: Optional[str] = None, user=Depends(require_office_or_master),
           conn=Depends(get_conn)):
    P.ensure(conn)
    _m(conn, tehnika_id)
    return P.mesyac_mashiny(conn, tehnika_id, _mesyac(mesyac))


class MashinaIn(BaseModel):
    marka: Optional[str] = None
    edinica: Optional[str] = None
    bak_l: Optional[float] = None
    start_data: Optional[str] = None
    start_spidometr: Optional[float] = None
    start_ostatok: Optional[float] = None
    vremya_vyezd: Optional[str] = None
    vremya_vozvrat: Optional[str] = None
    marshrut: Optional[str] = None


@router.put("/mashina/{tid}")
def mashina_put(tid: int, b: MashinaIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    P.ensure(conn)
    _m(conn, tid)
    if b.edinica and b.edinica not in P.EDINICY:
        raise HTTPException(400, "Единица — км или моточас")
    for v, naz in ((b.bak_l, "Объём бака"), (b.start_spidometr, "Спидометр"), (b.start_ostatok, "Остаток")):
        if v is not None and v < 0:
            raise HTTPException(400, f"{naz} не может быть меньше нуля")
    if b.bak_l is not None and b.bak_l > 5000:
        raise HTTPException(400, "Объём бака больше 5000 л — проверьте")
    conn.execute(
        "UPDATE tehnika SET marka=?, edinica=?, bak_l=?, start_data=?, start_spidometr=?, start_ostatok=?, "
        "vremya_vyezd=?, vremya_vozvrat=?, marshrut=? WHERE id=?",
        ((b.marka or "").strip()[:80] or None, b.edinica or "км", b.bak_l or None,
         _data(b.start_data) if b.start_data else None, b.start_spidometr, b.start_ostatok,
         (b.vremya_vyezd or "").strip()[:5] or None, (b.vremya_vozvrat or "").strip()[:5] or None,
         (b.marshrut or "").strip()[:300] or None, tid))
    P.pereschitat(conn, tid)
    conn.commit()
    return {"ok": True}


class NormaIn(BaseModel):
    s_daty: str
    norma: float
    kommentariy: Optional[str] = None


@router.post("/mashina/{tid}/norma")
def norma_post(tid: int, b: NormaIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    P.ensure(conn)
    _m(conn, tid)
    if not (0 < b.norma < 10):
        raise HTTPException(400, "Норма в литрах на 1 км (моточас): например 0,1392")
    d = _data(b.s_daty)
    if not P.mozhno_pravit(conn, tid, d):
        raise HTTPException(409, "С этой даты месяц уже закрыт — норма его не изменит. Выберите дату позже.")
    conn.execute("INSERT INTO tehnika_norma (tehnika_id, s_daty, norma, kommentariy) VALUES (?,?,?,?) "
                 "ON CONFLICT(tehnika_id, s_daty) DO UPDATE SET norma=excluded.norma, kommentariy=excluded.kommentariy",
                 (tid, d, round(b.norma, 4), (b.kommentariy or "").strip()[:200] or None))
    n = P.pereschitat(conn, tid, d)
    conn.commit()
    return {"ok": True, "pereschitano": n}


@router.delete("/norma/{nid}")
def norma_delete(nid: int, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    P.ensure(conn)
    r = conn.execute("SELECT tehnika_id, s_daty FROM tehnika_norma WHERE id=?", (nid,)).fetchone()
    if not r:
        raise HTTPException(404, "Норма не найдена")
    if not P.mozhno_pravit(conn, r[0], r[1]):
        raise HTTPException(409, "Норма действует в закрытом месяце — удалить нельзя")
    conn.execute("DELETE FROM tehnika_norma WHERE id=?", (nid,))
    P.pereschitat(conn, r[0], r[1])
    conn.commit()
    return {"ok": True}


class ListIn(BaseModel):
    tehnika_id: Optional[int] = None
    data: Optional[str] = None
    nomer: Optional[int] = None
    sotrudnik_id: Optional[int] = None
    probeg: float = 0
    zapravka: float = 0
    spid_vyezd_fix: Optional[float] = None
    ost_vyezd_fix: Optional[float] = None
    vremya_vyezd: Optional[str] = None
    vremya_vozvrat: Optional[str] = None
    marshrut: Optional[str] = None
    kommentariy: Optional[str] = None


def _proverit(b: ListIn):
    if b.probeg < 0 or b.probeg > P.MAX_PROBEG:
        raise HTTPException(400, f"Пробег от 0 до {P.MAX_PROBEG}")
    if b.zapravka < 0 or b.zapravka > P.MAX_ZAPRAVKA:
        raise HTTPException(400, f"Заправка от 0 до {P.MAX_ZAPRAVKA} л")
    for v in (b.spid_vyezd_fix, b.ost_vyezd_fix):
        if v is not None and v < 0:
            raise HTTPException(400, "Показания не могут быть меньше нуля")


def _vals(b: ListIn):
    return (b.nomer, b.sotrudnik_id or None, round(b.probeg, 1), round(b.zapravka, 2), b.spid_vyezd_fix,
            b.ost_vyezd_fix, (b.vremya_vyezd or "").strip()[:5] or None, (b.vremya_vozvrat or "").strip()[:5] or None,
            (b.marshrut or "").strip()[:300] or None, (b.kommentariy or "").strip()[:500] or None)


@router.post("/list")
def list_post(b: ListIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    P.ensure(conn)
    if not b.tehnika_id or not b.data:
        raise HTTPException(400, "Нужны машина и дата")
    m = _m(conn, b.tehnika_id)
    d = _data(b.data)
    _proverit(b)
    if not P.mozhno_pravit(conn, b.tehnika_id, d):
        raise HTTPException(409, "Месяц закрыт — сначала откройте его")
    if conn.execute("SELECT 1 FROM putevoy_list WHERE tehnika_id=? AND data=?", (b.tehnika_id, d)).fetchone():
        raise HTTPException(409, "На этот день у машины уже есть лист")
    if b.nomer is None:
        b.nomer = P.sleduyushchiy_nomer(conn, d[:4])
    if b.sotrudnik_id is None:
        b.sotrudnik_id = m["zakreplen_sotrudnik_id"]
    cur = conn.execute(
        "INSERT INTO putevoy_list (nomer, sotrudnik_id, probeg, zapravka, spid_vyezd_fix, ost_vyezd_fix, vremya_vyezd, "
        "vremya_vozvrat, marshrut, kommentariy, tehnika_id, data, istochnik) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'ruchnoy')",
        (*_vals(b), b.tehnika_id, d))
    P.pereschitat(conn, b.tehnika_id, d)
    conn.commit()
    return {"id": cur.lastrowid}


@router.put("/list/{lid}")
def list_put(lid: int, b: ListIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    P.ensure(conn)
    r = conn.execute("SELECT tehnika_id, data FROM putevoy_list WHERE id=?", (lid,)).fetchone()
    if not r:
        raise HTTPException(404, "Лист не найден")
    tid, d = r
    _proverit(b)
    if not P.mozhno_pravit(conn, tid, d):
        raise HTTPException(409, "Месяц закрыт — сначала откройте его")
    # Правка руками превращает лист генератора в ручной: перезаполнение
    # месяца его уже не перетрёт.
    conn.execute(
        "UPDATE putevoy_list SET nomer=?, sotrudnik_id=?, probeg=?, zapravka=?, spid_vyezd_fix=?, ost_vyezd_fix=?, "
        "vremya_vyezd=?, vremya_vozvrat=?, marshrut=?, kommentariy=?, istochnik='ruchnoy' WHERE id=?", (*_vals(b), lid))
    n = P.pereschitat(conn, tid, d)
    conn.commit()
    return {"ok": True, "pereschitano": n}


@router.delete("/list/{lid}")
def list_delete(lid: int, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    P.ensure(conn)
    r = conn.execute("SELECT tehnika_id, data FROM putevoy_list WHERE id=?", (lid,)).fetchone()
    if not r:
        raise HTTPException(404, "Лист не найден")
    if not P.mozhno_pravit(conn, r[0], r[1]):
        raise HTTPException(409, "Месяц закрыт — сначала откройте его")
    conn.execute("DELETE FROM putevoy_list WHERE id=?", (lid,))
    P.pereschitat(conn, r[0], r[1])
    conn.commit()
    return {"ok": True}


class GenIn(BaseModel):
    tehnika_id: int
    mesyac: str
    dni: Optional[List[str]] = None
    sotrudnik_id: Optional[int] = None
    probeg_vsego: Optional[float] = None
    km_v_den: Optional[float] = None
    razbros: float = 0.1
    zapravki: str = "vsego"
    litrov_vsego: Optional[float] = None
    raz: Optional[int] = None
    po_datam: Optional[Dict[str, float]] = None
    porog: float = 0.25
    vremya_vyezd: Optional[str] = None
    vremya_vozvrat: Optional[str] = None
    marshrut: Optional[str] = None
    seed: Optional[int] = None


def _gen(conn, b: GenIn):
    P.ensure(conn)
    _m(conn, b.tehnika_id)
    if b.zapravki not in ("vsego", "po_datam", "avto", "net"):
        raise HTTPException(400, "Способ заправок: vsego / po_datam / avto / net")
    if b.probeg_vsego is not None and not (0 <= b.probeg_vsego <= P.MAX_PROBEG * 31):
        raise HTTPException(400, "Пробег за месяц — проверьте число")
    try:
        return P.generator_mesyaca(conn, b.tehnika_id, _mesyac(b.mesyac), **b.model_dump(exclude={"tehnika_id", "mesyac"}))
    except P.GenOshibka as e:
        raise HTTPException(400, str(e))


@router.post("/generator")
def generator(b: GenIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    return _gen(conn, b)


@router.post("/generator/sohranit")
def generator_sohranit(b: GenIn, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    ch = _gen(conn, b)
    n = P.sohranit_generator(conn, b.tehnika_id, ch)
    conn.commit()
    return {"ok": True, "zapisano": n}


@router.post("/mesyac/zakryt")
def zakryt(tehnika_id: int, mesyac: str, on: bool = True, user=Depends(require_office_or_master),
           conn=Depends(get_conn)):
    P.ensure(conn)
    _m(conn, tehnika_id)
    ms = _mesyac(mesyac)
    if not on:
        pozzhe = [x for x in P.zakrytye_mesyacy(conn, tehnika_id) if x > ms]
        if pozzhe:
            raise HTTPException(409, f"Сначала откройте {max(pozzhe)} — он позже и тоже закрыт")
    if on:
        P.pereschitat(conn, tehnika_id)
    conn.execute("INSERT INTO putevoy_mesyac (tehnika_id, mesyac, zakryt, zakryt_at) VALUES (?,?,?, datetime('now','localtime')) "
                 "ON CONFLICT(tehnika_id, mesyac) DO UPDATE SET zakryt=excluded.zakryt, zakryt_at=excluded.zakryt_at",
                 (tehnika_id, ms, 1 if on else 0))
    conn.commit()
    return {"ok": True}


@router.get("/svodka")
def svodka(mesyac: Optional[str] = None, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    P.ensure(conn)
    return P.svodka_vseh(conn, _mesyac(mesyac))
