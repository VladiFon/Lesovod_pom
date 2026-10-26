# -*- coding: utf-8 -*-
"""Пробные площади на карте (26.10.2026) — см. app/proby_karta.py.

Видят все, кто вошёл (рабочие в приложении, сотрудники на сайте): пробу
ставят один раз, а через 1–3 года на неё выходит другой человек.
Ставить может любой рабочий и офис с правом записи; править и убирать —
автор, руководители (мастер / пом. лесничего / лесничий) и офис."""
import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import legacy_bridge  # noqa: F401
import config as legacy_config

from app import map_features, proby_karta
from app.auth import OFFICE_WRITE_ROLES, get_current_user
from app.database import get_conn
from app.routers.bot import _PHOTO_SUFFIXES, _check_photo_path

router = APIRouter(prefix="/api/proby", tags=["proby"])


class ProbaIn(BaseModel):
    forma: str = "krug"
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_m: Optional[float] = None
    dlina_m: Optional[float] = None
    shirina_m: Optional[float] = None
    azimut: Optional[float] = Field(default=None, ge=0, le=360)
    # обход по GPS: [[lon, lat], ...]
    tochki: Optional[List[List[float]]] = None
    tochnost_m: Optional[float] = Field(default=None, ge=0, le=1000)
    nomer: Optional[str] = Field(default=None, max_length=20)
    uchastok_id: Optional[int] = None
    lesnichestvo: Optional[str] = Field(default=None, max_length=100)
    kvartal: Optional[str] = Field(default=None, max_length=20)
    vydel: Optional[str] = Field(default=None, max_length=20)
    orientir: Optional[str] = Field(default=None, max_length=500)
    photo_path: Optional[str] = None


class ProbaPatch(BaseModel):
    """Не переданное (null) не меняется. Новая точка/форма — граница
    перестраивается («перенести пробу сюда», «радиус не тот»)."""

    nomer: Optional[str] = Field(default=None, max_length=20)
    uchastok_id: Optional[int] = None
    orientir: Optional[str] = Field(default=None, max_length=500)
    forma: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_m: Optional[float] = None
    dlina_m: Optional[float] = None
    shirina_m: Optional[float] = None
    azimut: Optional[float] = Field(default=None, ge=0, le=360)
    tochki: Optional[List[List[float]]] = None
    tochnost_m: Optional[float] = Field(default=None, ge=0, le=1000)
    photo_path: Optional[str] = None


def _pishushchiy(user: dict) -> None:
    if user.get("role") == "worker" and user.get("sotrudnik_id"):
        return
    if user.get("role") in OFFICE_WRITE_ROLES:
        return
    raise HTTPException(403, "Ставить пробы могут рабочие в приложении и офис с правом записи")


def _rukovoditel(conn, user: dict) -> bool:
    if user.get("role") in OFFICE_WRITE_ROLES:
        return True
    if user.get("role") != "worker" or not user.get("sotrudnik_id"):
        return False
    row = conn.execute("SELECT dolzhnost FROM sotrudniki WHERE id = ? AND is_active = 1", (user["sotrudnik_id"],)).fetchone()
    return bool(row) and (row[0] or "").strip().casefold() in legacy_config.DOLZHNOSTI_MASTER_URODNYA


def _mozhno_pravit(conn, user: dict, proba: dict) -> bool:
    if user.get("role") == "worker" and user.get("sotrudnik_id") and proba.get("sozdal_sotrudnik_id") == user["sotrudnik_id"]:
        return True
    return _rukovoditel(conn, user)


def _s_pravami(conn, user: dict, proby: List[dict]) -> List[dict]:
    rukovoditel = _rukovoditel(conn, user)
    for p in proby:
        svoya = user.get("role") == "worker" and p.get("sozdal_sotrudnik_id") == user.get("sotrudnik_id")
        p["mozhno_pravit"] = rukovoditel or bool(svoya)
    return proby


def _check_uchastok(conn, uchastok_id: Optional[int]) -> None:
    if uchastok_id and conn.execute("SELECT 1 FROM lesokultury_uchastok WHERE id = ?", (uchastok_id,)).fetchone() is None:
        raise HTTPException(404, "Участок лесных культур не найден")


@router.get("")
def list_proby(lesnichestvo_num: Optional[str] = None, uchastok_id: Optional[int] = None,
               conn=Depends(get_conn), user=Depends(get_current_user)):
    """Все пробы (лесничества / участка) — у всех одинаково, не только свои."""
    return _s_pravami(conn, user, proby_karta.spisok(conn, lesnichestvo_num, uchastok_id))


@router.get("/{proba_id}")
def get_proba(proba_id: int, conn=Depends(get_conn), user=Depends(get_current_user)):
    proba = proby_karta.odna(conn, proba_id)
    if proba is None:
        raise HTTPException(404, "Проба не найдена")
    return _s_pravami(conn, user, [proba])[0]


@router.post("")
def create_proba(body: ProbaIn, conn=Depends(get_conn), user=Depends(get_current_user)):
    _pishushchiy(user)
    try:
        geo = proby_karta.postroit(body.forma, body.lat, body.lon, body.radius_m, body.dlina_m, body.shirina_m,
                                   body.azimut, body.tochki)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    lesnichestvo = map_features.canonical_lesnichestvo(body.lesnichestvo) if body.lesnichestvo else None
    kvartal = map_features.norm_id(body.kvartal) or None
    vydel = map_features.norm_id(body.vydel) or None
    uchastok_id = body.uchastok_id
    _check_uchastok(conn, uchastok_id)
    avto = False
    if not uchastok_id:
        uchastok_id = proby_karta.naiti_uchastok(conn, geo["lat"], geo["lon"], kvartal, vydel, lesnichestvo)
        avto = uchastok_id is not None
    if uchastok_id and not kvartal:
        row = conn.execute("SELECT kvartal, vydel, lesnichestvo FROM lesokultury_uchastok WHERE id = ?", (uchastok_id,)).fetchone()
        if row:
            kvartal, vydel = map_features.norm_id(row[0]) or None, vydel or map_features.norm_id(row[1]) or None
            lesnichestvo = lesnichestvo or row[2]
    nomer = (body.nomer or "").strip() or proby_karta.sleduyushchiy_nomer(conn, uchastok_id, kvartal, vydel)
    worker = user.get("role") == "worker"
    cur = conn.execute(
        "INSERT INTO karta_proby (nomer, uchastok_id, lesnichestvo, kvartal, vydel, lat, lon, forma, radius_m, dlina_m, "
        "shirina_m, azimut, ploshad_m2, geom_geojson, tochnost_m, orientir, photo_path, sozdal_identity, "
        "sozdal_sotrudnik_id, sozdal_fio) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (nomer, uchastok_id, lesnichestvo, kvartal, vydel, geo["lat"], geo["lon"], body.forma,
         body.radius_m if body.forma == "krug" else None,
         body.dlina_m if body.forma == "pryamougolnik" else None,
         body.shirina_m if body.forma == "pryamougolnik" else None,
         body.azimut if body.forma == "pryamougolnik" else None,
         proby_karta.ploshad_formy(body.forma, geo["geometry"], body.radius_m, body.dlina_m, body.shirina_m),
         _json(geo["geometry"]), body.tochnost_m,
         (body.orientir or "").strip() or None, _check_photo_path(body.photo_path),
         user.get("app_identity") if worker else user.get("login"),
         user.get("sotrudnik_id") if worker else None, user.get("fio")),
    )
    conn.commit()
    proba = _s_pravami(conn, user, [proby_karta.odna(conn, cur.lastrowid)])[0]
    proba["uchastok_avto"] = avto
    return proba


@router.patch("/{proba_id}")
def update_proba(proba_id: int, body: ProbaPatch, conn=Depends(get_conn), user=Depends(get_current_user)):
    proba = proby_karta.odna(conn, proba_id)
    if proba is None:
        raise HTTPException(404, "Проба не найдена")
    if not _mozhno_pravit(conn, user, proba):
        raise HTTPException(403, "Править пробу могут её автор, руководители и офис")
    fields = {}
    if body.nomer is not None and body.nomer.strip():
        fields["nomer"] = body.nomer.strip()
    if body.orientir is not None:
        fields["orientir"] = body.orientir.strip() or None
    if body.uchastok_id is not None:
        _check_uchastok(conn, body.uchastok_id or None)
        fields["uchastok_id"] = body.uchastok_id or None  # 0 — отвязать
    if body.photo_path is not None:
        fields["photo_path"] = _check_photo_path(body.photo_path) if body.photo_path else None
    geom_change = any(v is not None for v in (body.forma, body.lat, body.lon, body.radius_m, body.dlina_m,
                                              body.shirina_m, body.azimut, body.tochki))
    if geom_change:
        forma = body.forma or proba["forma"]
        pick = lambda new, old: new if new is not None else old  # noqa: E731
        radius = pick(body.radius_m, proba["radius_m"])
        dlina, shirina, azimut = pick(body.dlina_m, proba["dlina_m"]), pick(body.shirina_m, proba["shirina_m"]), pick(body.azimut, proba["azimut"])
        tochki = body.tochki
        lat, lon = pick(body.lat, proba["lat"]), pick(body.lon, proba["lon"])
        if forma == "kontur" and tochki is None:
            if proba["forma"] != "kontur":
                raise HTTPException(400, "Для обхода нужны точки")
            # тот же контур, сдвинутый в новую точку
            ring = proba["geometry"]["coordinates"][0]
            dlon, dlat = lon - proba["lon"], lat - proba["lat"]
            tochki = [[p[0] + dlon, p[1] + dlat] for p in ring]
        try:
            geo = proby_karta.postroit(forma, lat, lon, radius, dlina, shirina, azimut, tochki)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        fields.update(
            forma=forma, lat=geo["lat"], lon=geo["lon"],
            radius_m=radius if forma == "krug" else None,
            dlina_m=dlina if forma == "pryamougolnik" else None,
            shirina_m=shirina if forma == "pryamougolnik" else None,
            azimut=azimut if forma == "pryamougolnik" else None,
            ploshad_m2=proby_karta.ploshad_formy(forma, geo["geometry"], radius, dlina, shirina),
            geom_geojson=_json(geo["geometry"]),
        )
        if body.tochnost_m is not None:
            fields["tochnost_m"] = body.tochnost_m
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE karta_proby SET {sets}, updated_at = datetime('now', 'localtime') WHERE id = ?",
                     (*fields.values(), proba_id))
        conn.commit()
    return _s_pravami(conn, user, [proby_karta.odna(conn, proba_id)])[0]


@router.delete("/{proba_id}")
def delete_proba(proba_id: int, conn=Depends(get_conn), user=Depends(get_current_user)):
    """Мягкое удаление: проба пропадает с карты, но остаётся в базе."""
    proba = proby_karta.odna(conn, proba_id)
    if proba is None:
        raise HTTPException(404, "Проба не найдена")
    if not _mozhno_pravit(conn, user, proba):
        raise HTTPException(403, "Убрать пробу могут её автор, руководители и офис")
    conn.execute("UPDATE karta_proby SET udalena = 1, udalil_fio = ?, udalena_at = datetime('now', 'localtime') "
                 "WHERE id = ?", (user.get("fio") or user.get("login"), proba_id))
    conn.commit()
    return {"deleted": True}


@router.get("/{proba_id}/photo")
def get_proba_photo(proba_id: int, conn=Depends(get_conn), _user=Depends(get_current_user)):
    path = proby_karta.photo_path(conn, proba_id)
    if not path or not Path(path).is_file() or Path(path).suffix.lower() not in _PHOTO_SUFFIXES:
        raise HTTPException(404, "Фото не найдено")
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"})


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
