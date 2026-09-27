# -*- coding: utf-8 -*-
"""Роутер экрана "Распределение бригад" — состав бригад (с историей
членства, brigada_sostav) и назначение бригады/рабочего на делянку ИЛИ
на участок лесных культур с диапазоном дат (brigada_naznachenie), плюс
сигнал "делянка близка к завершению" (list_delyanki_dlya_raspredeleniya,
делянка-only — см. докстринг backend/legacy/brigada.py), посчитанный уже
существующими функциями raskhod_v2.

Чтение (GET) оставлено открытым — тот же принцип, что и в
app/routers/inspection.py (GET /api/inspection/ без require_permission);
запись — за require_permission("brigady.edit") (admin/lesovod, см.
webext.PERMISSIONS)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import brigada/webext
import brigada
import webext

from app.auth import require_permission
from app.database import get_conn

router = APIRouter(prefix="/api/brigady", tags=["brigady"])


# --------------------------------------------------------------------------- #
#   Бригады и состав
# --------------------------------------------------------------------------- #
@router.get("/")
def list_brigady(conn=Depends(get_conn)) -> list[dict]:
    return brigada.list_brigady(conn)


@router.get("/sotrudniki")
def list_sotrudniki_for_picker(conn=Depends(get_conn)) -> list[dict]:
    """Лёгкий список активных работников — для пикеров состава бригады/
    исполнителя назначения (тот же принцип, что и GET /api/work-plan/sotrudniki)."""
    return [s for s in webext.list_sotrudniki(conn) if s["is_active"]]


class BrigadaCreateIn(BaseModel):
    nazvanie: str
    brigadir_sotrudnik_id: Optional[int] = None


@router.post("/")
def create_brigada(body: BrigadaCreateIn, user=Depends(require_permission("brigady.edit")),
                    conn=Depends(get_conn)) -> dict:
    brigada_id = brigada.create_brigada(conn, body.nazvanie, body.brigadir_sotrudnik_id)
    return {"id": brigada_id}


class BrigadaUpdateIn(BaseModel):
    nazvanie: Optional[str] = None
    brigadir_sotrudnik_id: Optional[int] = -1  # -1 = не менять
    is_active: Optional[bool] = None


@router.patch("/{brigada_id}")
def update_brigada(brigada_id: int, body: BrigadaUpdateIn,
                    user=Depends(require_permission("brigady.edit")), conn=Depends(get_conn)) -> dict:
    brigada.update_brigada(
        conn, brigada_id, nazvanie=body.nazvanie,
        brigadir_sotrudnik_id=body.brigadir_sotrudnik_id, is_active=body.is_active,
    )
    return {"ok": True}


class BrigadaSostavIn(BaseModel):
    sotrudnik_ids: list[int]


@router.patch("/{brigada_id}/sostav")
def set_brigada_sostav(brigada_id: int, body: BrigadaSostavIn,
                        user=Depends(require_permission("brigady.edit")), conn=Depends(get_conn)) -> dict:
    brigada.set_brigada_sostav(conn, brigada_id, body.sotrudnik_ids)
    return {"ok": True}


@router.get("/sotrudniki/{sotrudnik_id}/istoriya")
def get_sotrudnik_brigada_history(sotrudnik_id: int, conn=Depends(get_conn)) -> list[dict]:
    return brigada.get_sotrudnik_brigada_history(conn, sotrudnik_id)


@router.get("/lesokultury-uchastki")
def list_lesokultury_uchastki_for_picker(
    user=Depends(require_permission("brigady.edit")), conn=Depends(get_conn)
) -> list[dict]:
    """Лёгкий список активных участков лесных культур — для переключателя
    "Делянка / Лесные культуры" в модалке назначения (тот же принцип, что
    и GET /api/work-plan/lesokultury-uchastki)."""
    import db as legacy_db
    return legacy_db.get_lesokultury_uchastki(conn, include_spisannye=False)


# --------------------------------------------------------------------------- #
#   Сигнал "делянка близка к завершению"
# --------------------------------------------------------------------------- #
@router.get("/delyanki-status")
def list_delyanki_dlya_raspredeleniya(conn=Depends(get_conn)) -> list[dict]:
    return brigada.list_delyanki_dlya_raspredeleniya(conn)


# --------------------------------------------------------------------------- #
#   Назначения на делянку
# --------------------------------------------------------------------------- #
@router.get("/naznacheniya")
def list_naznacheniya(
    delyanka_id: Optional[int] = None,
    lesokultury_uchastok_id: Optional[int] = None,
    brigada_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    conn=Depends(get_conn),
) -> list[dict]:
    return brigada.list_naznacheniya(
        conn, delyanka_id=delyanka_id, lesokultury_uchastok_id=lesokultury_uchastok_id,
        brigada_id=brigada_id, status=status, date_from=date_from, date_to=date_to,
    )


class NaznachenieCreateIn(BaseModel):
    delyanka_id: Optional[int] = None
    lesokultury_uchastok_id: Optional[int] = None
    data_nachala: str  # "ГГГГ-ММ-ДД"
    data_okonchaniya: Optional[str] = None
    brigada_id: Optional[int] = None
    sotrudnik_id: Optional[int] = None
    kommentariy: Optional[str] = None
    close_current_for_brigada: bool = True


@router.post("/naznacheniya")
def create_naznachenie(body: NaznachenieCreateIn,
                        user=Depends(require_permission("brigady.edit")), conn=Depends(get_conn)) -> dict:
    try:
        naznachenie_id = brigada.create_naznachenie(
            conn, body.data_nachala, delyanka_id=body.delyanka_id,
            lesokultury_uchastok_id=body.lesokultury_uchastok_id,
            data_okonchaniya=body.data_okonchaniya, brigada_id=body.brigada_id,
            sotrudnik_id=body.sotrudnik_id, kommentariy=body.kommentariy,
            created_by=user["login"], close_current_for_brigada=body.close_current_for_brigada,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return brigada.get_naznachenie(conn, naznachenie_id)


class NaznachenieUpdateIn(BaseModel):
    status: Optional[str] = None
    data_nachala: Optional[str] = None
    data_okonchaniya: Optional[str] = None
    kommentariy: Optional[str] = None


@router.patch("/naznacheniya/{naznachenie_id}")
def update_naznachenie(naznachenie_id: int, body: NaznachenieUpdateIn,
                        user=Depends(require_permission("brigady.edit")), conn=Depends(get_conn)) -> dict:
    if brigada.get_naznachenie(conn, naznachenie_id) is None:
        raise HTTPException(404, "Назначение не найдено")
    brigada.update_naznachenie(
        conn, naznachenie_id, status=body.status, data_nachala=body.data_nachala,
        data_okonchaniya=body.data_okonchaniya, kommentariy=body.kommentariy,
    )
    return brigada.get_naznachenie(conn, naznachenie_id)


@router.delete("/naznacheniya/{naznachenie_id}")
def delete_naznachenie(naznachenie_id: int, user=Depends(require_permission("brigady.edit")),
                        conn=Depends(get_conn)) -> dict:
    if brigada.get_naznachenie(conn, naznachenie_id) is None:
        raise HTTPException(404, "Назначение не найдено")
    brigada.delete_naznachenie(conn, naznachenie_id)
    return {"ok": True, "id": naznachenie_id}
