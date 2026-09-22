# -*- coding: utf-8 -*-
"""Роутер "Журнал ИИ" (screens/ai_log/) — разбор входящих отчётов
telegram-бота (raw_reports, status='на проверке') и журнал уже одобренных
работ (completed_works). Логика (SQL, поля, перенос должности из
lesorub_directory при одобрении) взята 1:1 из
screens/ai_log/screen_data.py + screen_completed.py:approve_and_transfer —
до Этапа 13 backend под этот экран не существовал вовсе.

Единственное отличие от desktop: там не было кнопки "отклонить" сырой
отчёт (только одобрение) — добавлена здесь как симметричное действие
(status='отклонено'), см. STAGE13.md."""
import os
import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401

from app.database import get_conn

router = APIRouter(prefix="/api/ai-log", tags=["ai_log"])


@router.get("/raw-reports")
def list_raw_reports(conn=Depends(get_conn)):
    try:
        rows = conn.execute(
            "SELECT id, ispolnitel_fio, data_soobscheniya, raw_text, photo_path, "
            "opisanie, kvartal, vydels, tip_raboty FROM raw_reports "
            "WHERE status='на проверке' ORDER BY id DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    cols = ["id", "ispolnitel_fio", "data_soobscheniya", "raw_text", "photo_path", "opisanie", "kvartal", "vydels", "tip_raboty"]
    return [dict(zip(cols, r)) for r in rows]


class ApproveIn(BaseModel):
    kvartal: str
    vydel: str
    tip_raboty: str
    lesnichestvo: str
    ispolnitel_fio: Optional[str] = None
    opisanie: Optional[str] = None


@router.post("/raw-reports/{report_id}/approve")
def approve_report(report_id: int, body: ApproveIn, conn=Depends(get_conn)):
    if not (body.kvartal.strip() and body.vydel.strip() and body.tip_raboty.strip() and body.lesnichestvo.strip()):
        raise HTTPException(400, "Заполните квартал, выдел, тип работы и лесничество")

    row = conn.execute("SELECT ispolnitel_fio, photo_path FROM raw_reports WHERE id=?", (report_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Отчёт не найден")
    default_fio, photo_path = row
    ispolnitel = (body.ispolnitel_fio or default_fio or "").strip()

    dolzhnost_row = conn.execute("SELECT dolzhnost FROM lesorub_directory WHERE fio=?", (ispolnitel,)).fetchone()
    dolzhnost = dolzhnost_row[0] if dolzhnost_row else None

    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO completed_works "
        "(data_vypolneniya, ispolnitel_fio, kvartal, vydel, tip_raboty, photo_path, lesnichestvo, opisanie, dolzhnost) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (today, ispolnitel, body.kvartal.strip(), body.vydel.strip(), body.tip_raboty.strip(),
         photo_path or None, body.lesnichestvo.strip(), (body.opisanie or "").strip() or None, dolzhnost),
    )
    conn.execute("UPDATE raw_reports SET status='обработано' WHERE id=?", (report_id,))
    conn.commit()
    return {"ok": True}


@router.post("/raw-reports/{report_id}/reject")
def reject_report(report_id: int, conn=Depends(get_conn)):
    cur = conn.execute("UPDATE raw_reports SET status='отклонено' WHERE id=?", (report_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "Отчёт не найден")
    return {"ok": True}


@router.get("/completed")
def list_completed(
    date_from: str,
    date_to: str,
    executor: Optional[str] = None,
    tip_raboty: Optional[str] = None,
    dolzhnost: Optional[str] = None,
    conn=Depends(get_conn),
):
    conditions = ["date(data_vypolneniya) >= date(?)", "date(data_vypolneniya) <= date(?)"]
    params: list = [date_from, date_to]
    if executor:
        conditions.append("ispolnitel_fio = ?")
        params.append(executor)
    if tip_raboty:
        conditions.append("tip_raboty = ?")
        params.append(tip_raboty)
    if dolzhnost:
        conditions.append("dolzhnost = ?")
        params.append(dolzhnost)
    where_clause = " AND ".join(conditions)
    try:
        rows = conn.execute(
            f"SELECT id, data_vypolneniya, ispolnitel_fio, kvartal, vydel, tip_raboty, "
            f"photo_path, lesnichestvo, opisanie, dolzhnost FROM completed_works "
            f"WHERE {where_clause} ORDER BY id DESC LIMIT 500",
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    cols = ["id", "data_vypolneniya", "ispolnitel_fio", "kvartal", "vydel", "tip_raboty", "photo_path", "lesnichestvo", "opisanie", "dolzhnost"]
    return [dict(zip(cols, r)) for r in rows]


@router.get("/completed/filters")
def completed_filters(conn=Depends(get_conn)):
    """Варианты для выпадающих списков фильтров — DISTINCT по всей таблице
    (без учёта текущих фильтров), как в _populate_completed_filter_options."""
    def distinct(col):
        try:
            return [r[0] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM completed_works WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}"
            ).fetchall()]
        except sqlite3.OperationalError:
            return []
    return {
        "executors": distinct("ispolnitel_fio"),
        "types": distinct("tip_raboty"),
        "dolzhnosti": distinct("dolzhnost"),
    }


@router.delete("/completed/{record_id}")
def delete_completed(record_id: int, conn=Depends(get_conn)):
    cur = conn.execute("DELETE FROM completed_works WHERE id=?", (record_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "Запись не найдена")
    return {"ok": True}


@router.get("/photo")
def get_photo(path: str, conn=Depends(get_conn)):
    """Фото присланы telegram-ботом и лежат абсолютным путём в photo_path
    (raw_reports/completed_works) — не в app.paths.UPLOADS_DIR. Отдаём по
    пути, но только если он реально числится в одной из этих таблиц (иначе
    query-параметр с произвольным путём читал бы любой файл на диске)."""
    known = conn.execute(
        "SELECT 1 FROM raw_reports WHERE photo_path=? "
        "UNION SELECT 1 FROM completed_works WHERE photo_path=?",
        (path, path),
    ).fetchone()
    if not known or not os.path.exists(path):
        raise HTTPException(404, "Файл не найден")
    return FileResponse(path)
