# -*- coding: utf-8 -*-
"""
Склады (места хранения/отгрузки древесины) — точки на Живой карте,
которые пользователь заводит и убирает вручную по известным ему
координатам (см. чат: "хочу чтобы отображались склады которые
действуют... могу размещать с помощью координат... добавить и
удалить недействующий или неправильный"). Никакой привязки к
лесосекам/выделам/лесничеству — простой список точек с названием и
координатами, см. таблицу sklad в db.py:SCHEMA.
"""
from typing import List, Optional


def list_sklady(conn) -> List[dict]:
    rows = conn.execute(
        "SELECT id, nazvanie, lat, lon, comment, created_at FROM sklad ORDER BY nazvanie"
    ).fetchall()
    cols = ["id", "nazvanie", "lat", "lon", "comment", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def create_sklad(conn, nazvanie: str, lat: float, lon: float, comment: Optional[str] = None) -> dict:
    cur = conn.execute(
        "INSERT INTO sklad (nazvanie, lat, lon, comment) VALUES (?, ?, ?, ?)",
        (nazvanie.strip(), lat, lon, (comment or "").strip() or None),
    )
    conn.commit()
    return {"id": cur.lastrowid, "nazvanie": nazvanie.strip(), "lat": lat, "lon": lon, "comment": comment}


def delete_sklad(conn, sklad_id: int) -> int:
    cur = conn.execute("DELETE FROM sklad WHERE id = ?", (sklad_id,))
    conn.commit()
    return cur.rowcount
