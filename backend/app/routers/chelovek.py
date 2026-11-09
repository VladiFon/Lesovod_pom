# -*- coding: utf-8 -*-
"""Карточка человека (Влад, 04.11.2026 — «сайт разбросан: табель и журнал
мероприятий не вместе»).

Всё, что сайт знает о сотруднике, в одном ответе: справочник, бригада и
где она сейчас, закреплённая техника, «сегодня» (отметка с телефона,
табель, задачи), лента «что делал» (табель + отчёты за смену + журнал
выполненных работ + лесокультуры + рубки ухода — app/raboty_sotrudnika.py),
итоги, задачи плана, заметки и «не сходится» (табель против отчётов).

Только чтение: ничего не меняет, вводить по-прежнему на своих экранах.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app import legacy_bridge  # noqa: F401
from app import raboty_sotrudnika as rs
from app.auth import require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/chelovek", tags=["chelovek"])

NE_RABOTAL = ("не работал", "больничный", "отпуск", "выходной")


def _tab(conn, t):
    return rs._est_tablica(conn, t)


def _brigada(conn, sid, segodnya):
    if not _tab(conn, "brigada_sostav"):
        return None
    r = conn.execute(
        """SELECT b.id, b.nazvanie, b.brigadir_sotrudnik_id, s.fio, bs.data_vstupleniya
           FROM brigada_sostav bs JOIN brigada b ON b.id = bs.brigada_id
           LEFT JOIN sotrudniki s ON s.id = b.brigadir_sotrudnik_id
           WHERE bs.sotrudnik_id = ? AND bs.data_vyhoda IS NULL AND b.is_active = 1
           ORDER BY bs.data_vstupleniya DESC LIMIT 1""", (sid,)).fetchone()
    out = None
    if r:
        out = {"id": r[0], "nazvanie": r[1], "brigadir_id": r[2], "brigadir_fio": r[3], "s": r[4],
               "tovarishchi": [{"id": x[0], "fio": x[1]} for x in conn.execute(
                   """SELECT s.id, s.fio FROM brigada_sostav bs JOIN sotrudniki s ON s.id = bs.sotrudnik_id
                      WHERE bs.brigada_id = ? AND bs.data_vyhoda IS NULL AND s.id <> ? ORDER BY s.fio""",
                   (r[0], sid)).fetchall()]}
    if _tab(conn, "brigada_naznachenie"):
        where = "n.sotrudnik_id = ?" + (" OR n.brigada_id = ?" if out else "")
        args = [sid] + ([out["id"]] if out else [])
        naz = conn.execute(
            f"""SELECT n.delyanka_id, d.nazvanie, n.data_nachala, n.data_okonchaniya, n.status
                FROM brigada_naznachenie n LEFT JOIN delyanka d ON d.id = n.delyanka_id
                WHERE ({where}) AND n.status IN ('активно', 'запланировано')
                ORDER BY CASE n.status WHEN 'активно' THEN 0 ELSE 1 END, n.data_nachala LIMIT 3""", args).fetchall()
        out = out or {}
        out["naznacheniya"] = [{"delyanka_id": x[0], "delyanka": x[1] or f"делянка №{x[0]}", "s": x[2], "po": x[3],
                                "status": x[4]} for x in naz]
    return out or None


def _tehnika(conn, sid):
    if not _tab(conn, "tehnika"):
        return []
    return [{"id": r[0], "nazvanie": r[1], "nomer": r[2], "tip": r[3]} for r in conn.execute(
        "SELECT id, nazvanie, nomer, tip FROM tehnika WHERE zakreplen_sotrudnik_id = ? AND aktivna = 1 ORDER BY nazvanie",
        (sid,)).fetchall()]


def _zadachi(conn, sid, segodnya):
    if not _tab(conn, "work_plan"):
        return []
    rows = conn.execute(
        """SELECT w.id, w.data, w.zadacha, w.status, di.delyanka_id, d.nazvanie, di.kvartal, di.vydel,
                  w.lesokultury_uchastok_id, lu.kvartal, lu.vydel
           FROM work_plan w
           LEFT JOIN delyanka_item di ON di.id = w.delyanka_item_id
           LEFT JOIN delyanka d ON d.id = di.delyanka_id
           LEFT JOIN lesokultury_uchastok lu ON lu.id = w.lesokultury_uchastok_id
           WHERE w.sotrudnik_id = ? AND (w.status = 'активна' OR w.data >= ?)
           ORDER BY w.data DESC, w.id DESC LIMIT 40""",
        (sid, (date.fromisoformat(segodnya) - timedelta(days=31)).isoformat())).fetchall()
    out = []
    for r in rows:
        gde, ssylka = None, None
        if r[4]:
            gde = f"{r[5] or 'делянка'} · кв.{r[6]} выд.{r[7]}"
            ssylka = {"screen": "plots", "params": {"d": r[4]}}
        elif r[8]:
            gde = f"л/к кв.{r[9]} выд.{r[10]}"
            ssylka = {"screen": "forestry", "params": {"u": r[8]}}
        out.append({"id": r[0], "data": r[1], "zadacha": r[2], "status": r[3], "gde": gde, "ssylka": ssylka,
                    "prosrochena": r[3] == "активна" and r[1] < segodnya})
    return out


def _otmetka(conn, sid, segodnya):
    if not _tab(conn, "attendance_marks"):
        return None
    r = conn.execute(
        "SELECT status, created_at FROM attendance_marks WHERE sotrudnik_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (sid,)).fetchone()
    if not r:
        return None
    return {"status": r[0], "kogda": r[1], "segodnya": (r[1] or "")[:10] == segodnya}


def _zametki(conn, sid):
    if not _tab(conn, "worker_notes"):
        return []
    return [{"id": r[0], "text": r[1], "kogda": r[2], "prochitana": bool(r[3])} for r in conn.execute(
        "SELECT id, text, created_at, is_read FROM worker_notes WHERE sotrudnik_id = ? ORDER BY created_at DESC LIMIT 8",
        (sid,)).fetchall()]


def _summy(conn, sid, ot, do):
    """Итоги за период: дни по табелю и объёмы из отчётов за смену."""
    out = {"dney_rabotal": 0, "dney_ne_rabotal": 0, "obyom": 0.0, "reysov": 0, "ga": 0.0, "chasy": 0.0, "otchetov": 0}
    if _tab(conn, "tabel_zapis"):
        for st, n in conn.execute(
                "SELECT status, COUNT(*) FROM tabel_zapis WHERE sotrudnik_id = ? AND data BETWEEN ? AND ? GROUP BY status",
                (sid, ot, do)).fetchall():
            if st in ("работал", "ремонт", "командировка"):  # на работе, хоть и не на делянке
                out["dney_rabotal"] += n
            else:
                out["dney_ne_rabotal"] += n
    if _tab(conn, "otchet_smeny"):
        r = conn.execute(
            """SELECT COUNT(*), SUM(obyom), SUM(reysov), SUM(ga), SUM(chasy) FROM otchet_smeny
               WHERE deleted = 0 AND sotrudnik_id = ? AND data BETWEEN ? AND ?""", (sid, ot, do)).fetchone()
        out.update({"otchetov": r[0] or 0, "obyom": round(r[1] or 0, 2), "reysov": int(r[2] or 0),
                    "ga": round(r[3] or 0, 2), "chasy": round(r[4] or 0, 1)})
    return out


def _ne_shoditsya(dni, segodnya):
    """Дни, где табель и отчёты/журналы говорят разное."""
    out = []
    for d in dni:
        if d["data"] >= segodnya:
            continue
        t, raboty = d.get("tabel"), d.get("raboty") or []
        if t and t.get("status") == "работал" and not raboty:
            continue  # обычный день без отчёта — не шумим, это норма для рабочих без телефона
        if t and t.get("status") in NE_RABOTAL and raboty:
            out.append({"data": d["data"], "chto": f"в табеле «{t['status']}», а работы записаны: "
                        + ", ".join(sorted({r['chto'] for r in raboty}))})
        elif not t and raboty:
            out.append({"data": d["data"], "chto": "работы записаны, а в табеле этого дня нет: "
                        + ", ".join(sorted({r['chto'] for r in raboty}))})
    return out[:15]


def _ne_privyazano(conn, sid, fio):
    """Записи журнала без ссылки на человека, где фамилия совпадает — возможно,
    это он (опечатка в имени или однофамилец)."""
    fam = rs._norm(fio).split(" ")[0] if fio else ""
    if not fam or not _tab(conn, "completed_works") or not rs._est_kolonka(conn, "completed_works", "sotrudnik_id"):
        return []
    out = []
    for i, d, f, tip in conn.execute(
            "SELECT id, data_vypolneniya, ispolnitel_fio, tip_raboty FROM completed_works "
            "WHERE sotrudnik_id IS NULL AND ispolnitel_fio IS NOT NULL ORDER BY data_vypolneniya DESC").fetchall():
        if rs._norm(f).split(" ")[0] == fam:
            out.append({"id": i, "data": (d or "")[:10], "fio": f, "chto": tip})
            if len(out) >= 10:
                break
    return out


@router.get("")
def spisok(vse: bool = False, user=Depends(require_office_or_master), conn=Depends(get_conn)):
    """Список людей для левой колонки: ФИО, должность, бригада, отметка сегодня."""
    segodnya = date.today().isoformat()
    rows = conn.execute(
        "SELECT id, fio, dolzhnost, uchastok, is_active FROM sotrudniki"
        + ("" if vse else " WHERE is_active = 1") + " ORDER BY fio").fetchall()
    brig = {}
    if _tab(conn, "brigada_sostav"):
        for sid, naz in conn.execute(
                """SELECT bs.sotrudnik_id, b.nazvanie FROM brigada_sostav bs JOIN brigada b ON b.id = bs.brigada_id
                   WHERE bs.data_vyhoda IS NULL AND b.is_active = 1""").fetchall():
            brig.setdefault(sid, naz)
    tabel = {}
    if _tab(conn, "tabel_zapis"):
        tabel = dict(conn.execute("SELECT sotrudnik_id, status FROM tabel_zapis WHERE data = ?", (segodnya,)).fetchall())
    return [{"id": r[0], "fio": r[1], "dolzhnost": r[2], "uchastok": r[3], "aktiven": bool(r[4]),
             "brigada": brig.get(r[0]), "segodnya": tabel.get(r[0])} for r in rows]


@router.get("/{sid}")
def kartochka(sid: int, dney: int = Query(31, ge=7, le=366), do: Optional[str] = None,
              user=Depends(require_office_or_master), conn=Depends(get_conn)):
    s = conn.execute("SELECT id, fio, dolzhnost, uchastok, login, is_active, created_at FROM sotrudniki WHERE id = ?",
                     (sid,)).fetchone()
    if not s:
        raise HTTPException(404, "Сотрудник не найден")
    segodnya = date.today().isoformat()
    ist = rs.istoriya(conn, sid, dney, do)
    po_dnyam = {d["data"]: d for d in ist["dni"]}
    sevodnya = po_dnyam.get(segodnya) or {}
    return {
        "id": s[0], "fio": s[1], "dolzhnost": s[2], "uchastok": s[3], "login": s[4], "aktiven": bool(s[5]),
        "s_kakogo": s[6],
        "brigada": _brigada(conn, sid, segodnya),
        "tehnika": _tehnika(conn, sid),
        "segodnya": {
            "data": segodnya,
            "otmetka": _otmetka(conn, sid, segodnya),
            "tabel": sevodnya.get("tabel"),
            "raboty": sevodnya.get("raboty") or [],
        },
        "zadachi": _zadachi(conn, sid, segodnya),
        "ot": ist["ot"], "do": ist["do"],
        "dni": ist["dni"],
        "itogo": ist["itogo"],
        "summy": _summy(conn, sid, ist["ot"], ist["do"]),
        "zametki": _zametki(conn, sid),
        "ne_shoditsya": _ne_shoditsya(ist["dni"], segodnya),
        "ne_privyazano": _ne_privyazano(conn, sid, s[1]),
    }
