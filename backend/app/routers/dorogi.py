# -*- coding: utf-8 -*-
"""Лесные дороги (12.11.2026) — см. app/lesnye_dorogi.py.

Видят все, кто вошёл: по дорогам телефон строит маршрут. Рисовать и
править могут руководители (мастер леса / помощник лесничего / лесничий)
и офис с правом записи — так попросил Влад, чтобы дороги не плодил
каждый. Ответ списка несёт флаг mozhno_risovat, по нему телефон
показывает или прячет кнопку «Нарисовать дорогу»."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import legacy_bridge  # noqa: F401
import config as legacy_config

from app import lesnye_dorogi, map_features
from app.auth import OFFICE_WRITE_ROLES, get_current_user
from app.database import get_conn

router = APIRouter(prefix="/api/dorogi", tags=["dorogi"])


class DorogaIn(BaseModel):
    nazvanie: Optional[str] = Field(default=None, max_length=120)
    tip: Optional[str] = "gruntovka"
    proezd: Optional[List[str]] = None
    # [[lon, lat], ...]
    tochki: List[List[float]]
    lesnichestvo: Optional[str] = Field(default=None, max_length=100)
    kommentariy: Optional[str] = Field(default=None, max_length=500)


class DorogaPatch(BaseModel):
    """Не переданное (null) не меняется."""

    nazvanie: Optional[str] = Field(default=None, max_length=120)
    tip: Optional[str] = None
    proezd: Optional[List[str]] = None
    tochki: Optional[List[List[float]]] = None
    kommentariy: Optional[str] = Field(default=None, max_length=500)


def _rukovoditel(conn, user: dict) -> bool:
    if user.get("role") in OFFICE_WRITE_ROLES:
        return True
    if user.get("role") != "worker" or not user.get("sotrudnik_id"):
        return False
    row = conn.execute("SELECT dolzhnost FROM sotrudniki WHERE id = ? AND is_active = 1", (user["sotrudnik_id"],)).fetchone()
    return bool(row) and (row[0] or "").strip().casefold() in {
        d.casefold() for d in legacy_config.DOLZHNOSTI_MASTER_URODNYA
    }


def _need_rukovoditel(conn, user: dict) -> None:
    if not _rukovoditel(conn, user):
        raise HTTPException(403, "Рисовать дороги могут мастер, помощник лесничего, лесничий и контора")


@router.get("")
def list_dorogi(conn=Depends(get_conn), user=Depends(get_current_user)):
    return {"dorogi": lesnye_dorogi.spisok(conn), "mozhno_risovat": _rukovoditel(conn, user)}


@router.post("")
def create_doroga(body: DorogaIn, conn=Depends(get_conn), user=Depends(get_current_user)):
    _need_rukovoditel(conn, user)
    try:
        tochki = lesnye_dorogi.proverit_tochki(body.tochki)
        tip = lesnye_dorogi.proverit_tip(body.tip)
        proezd = lesnye_dorogi.proverit_proezd(body.proezd, tip)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    worker = user.get("role") == "worker"
    lesnichestvo = map_features.canonical_lesnichestvo(body.lesnichestvo) if body.lesnichestvo else None
    cur = conn.execute(
        "INSERT INTO lesnye_dorogi (nazvanie, tip, proezd, geom_geojson, dlina_m, lesnichestvo, kommentariy, "
        "sozdal_identity, sozdal_sotrudnik_id, sozdal_fio) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            (body.nazvanie or "").strip() or None, tip, ",".join(proezd), lesnye_dorogi.geom_json(tochki),
            round(lesnye_dorogi.dlina(tochki), 1), lesnichestvo, (body.kommentariy or "").strip() or None,
            user.get("app_identity") if worker else user.get("login"),
            user.get("sotrudnik_id") if worker else None, user.get("fio"),
        ),
    )
    conn.commit()
    return lesnye_dorogi.odna(conn, cur.lastrowid)


@router.patch("/{doroga_id}")
def update_doroga(doroga_id: int, body: DorogaPatch, conn=Depends(get_conn), user=Depends(get_current_user)):
    _need_rukovoditel(conn, user)
    doroga = lesnye_dorogi.odna(conn, doroga_id)
    if doroga is None:
        raise HTTPException(404, "Дорога не найдена")
    fields = {}
    try:
        tip = lesnye_dorogi.proverit_tip(body.tip) if body.tip is not None else doroga["tip"]
        if body.tip is not None:
            fields["tip"] = tip
        if body.proezd is not None:
            fields["proezd"] = ",".join(lesnye_dorogi.proverit_proezd(body.proezd, tip))
        if body.tochki is not None:
            tochki = lesnye_dorogi.proverit_tochki(body.tochki)
            fields["geom_geojson"] = lesnye_dorogi.geom_json(tochki)
            fields["dlina_m"] = round(lesnye_dorogi.dlina(tochki), 1)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if body.nazvanie is not None:
        fields["nazvanie"] = body.nazvanie.strip() or None
    if body.kommentariy is not None:
        fields["kommentariy"] = body.kommentariy.strip() or None
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE lesnye_dorogi SET {sets}, updated_at = datetime('now', 'localtime'), izmenil_fio = ? WHERE id = ?",
            (*fields.values(), user.get("fio") or user.get("login"), doroga_id),
        )
        conn.commit()
    return lesnye_dorogi.odna(conn, doroga_id)


@router.delete("/{doroga_id}")
def delete_doroga(doroga_id: int, conn=Depends(get_conn), user=Depends(get_current_user)):
    """Мягкое удаление: дорога пропадает с карты, но остаётся в базе."""
    _need_rukovoditel(conn, user)
    if lesnye_dorogi.odna(conn, doroga_id) is None:
        raise HTTPException(404, "Дорога не найдена")
    conn.execute(
        "UPDATE lesnye_dorogi SET udalena = 1, udalil_fio = ?, udalena_at = datetime('now', 'localtime') WHERE id = ?",
        (user.get("fio") or user.get("login"), doroga_id),
    )
    conn.commit()
    return {"deleted": True}
