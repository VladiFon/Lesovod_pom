# -*- coding: utf-8 -*-
"""Пометки лесосек на картах (12.11.2026) — см. app/karta_pometki.py.

«Скрыть с карт» и «это лесные культуры» ставят: сайт (карточка делянки,
Настройки → Карты), телефон из карточки лесосеки и QGIS-плагин по
выделенным полигонам (служебный токен). Менять могут руководители (мастер /
помощник лесничего / лесничий) и офис с правом записи — как лесные дороги."""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import karta_pometki, vidy
from app.database import get_conn
from app.auth import get_current_user
from app.routers.dorogi import _rukovoditel
from app.routers.map import _check_service_token

router = APIRouter(tags=["karta"])


class PometkaIn(BaseModel):
    istochnik: str
    klyuchi: List[str] = Field(..., min_length=1, max_length=5000)
    # True — скрыть, False — вернуть, None — не менять
    skryta: Optional[bool] = None
    # "da" — это культуры, "net" — не культуры, "avto" — определять само, None — не менять
    lesokultury: Optional[str] = None
    opisaniya: Optional[Dict[str, str]] = None


class NastroykiIn(BaseModel):
    skryt_zakrytye: Optional[bool] = None
    skryt_vidy: Optional[List[str]] = None
    gisleshoz_let: Optional[int] = Field(default=None, ge=0, le=100)


_LK = {"da": True, "net": False, "avto": None}


def _primenit(conn, body: PometkaIn, kto: str) -> dict:
    if body.lesokultury is not None and body.lesokultury not in _LK:
        raise HTTPException(400, "lesokultury: da / net / avto")
    try:
        n = karta_pometki.postavit(
            conn, body.istochnik, body.klyuchi, skryta=body.skryta,
            lesokultury=_LK[body.lesokultury] if body.lesokultury is not None else "ne_menyat",
            opisaniya=body.opisaniya, kto=kto)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "izmeneno": n}


def _vidy_rubok() -> List[dict]:
    return [{"kod": v["kod"], "label": v["label"], "color": v["color"]}
            for v in vidy.legendy()["vidy_rubok"] if v.get("kod")]


def _sloi(conn) -> List[dict]:
    """Загруженные на сервер слои контуров (пачки imported_map_layer): из QGIS
    «Опубликовать в Лесовод» и старые файлы, загруженные руками. Старые
    файлы публикация из QGIS не заменяет — их контуры висят в телефоне, пока
    пачку не удалить здесь."""
    import map_import

    out = []
    for b in map_import.list_import_batches(conn):
        name = str(b.get("layer_name") or "")
        out.append({**b, "iz_qgis": name in ("лесосеки_qgis", "qgis_lesoseki"),
                    "lesoseki": "лесосек" in name.lower() or "lesosek" in name.lower()})
    return out


def _svodka(conn, user=None) -> dict:
    from app import legacy_bridge  # noqa: F401
    import webext

    return {
        "sloi": _sloi(conn),
        "mozhno_udalyat_sloi": user is not None and webext.has_permission(user, "map.import"),
        "nastroyki": karta_pometki.nastroyki(conn),
        "skrytye": karta_pometki.spisok_skrytyh(conn),
        "vidy_rubok": _vidy_rubok(),
        "mozhno": True if user is None else _rukovoditel(conn, user),
    }


def _need(conn, user):
    if not _rukovoditel(conn, user):
        raise HTTPException(403, "Скрывать лесосеки с карт могут мастер, помощник лесничего, лесничий и контора")


# ------------------------------------------------------------ сайт / телефон --

@router.get("/api/karta/pometki")
def get_pometki(conn=Depends(get_conn), user=Depends(get_current_user)):
    return _svodka(conn, user)


@router.post("/api/karta/pometki")
def post_pometki(body: PometkaIn, conn=Depends(get_conn), user=Depends(get_current_user)):
    _need(conn, user)
    return _primenit(conn, body, user.get("fio") or user.get("login") or "")


@router.put("/api/karta/nastroyki")
def put_nastroyki(body: NastroykiIn, conn=Depends(get_conn), user=Depends(get_current_user)):
    _need(conn, user)
    return {"ok": True, "nastroyki": karta_pometki.sohranit_nastroyki(conn, body.model_dump(exclude_none=True))}


@router.get("/api/karta/delyanka/{delyanka_id}")
def get_pometka_delyanki(delyanka_id: int, conn=Depends(get_conn), user=Depends(get_current_user)):
    """Для карточки делянки на сайте: скрыта ли и почему, на культурах ли."""
    row = conn.execute(
        "SELECT MIN(i.kvartal), GROUP_CONCAT(i.vydel, ','), MIN(i.vid_rubki_kod), MIN(i.mdo_raw_json), "
        "MIN(d.meropriyatiya), MIN(d.listok_namechaemoe_meropriyatie) "
        "FROM delyanka d LEFT JOIN delyanka_item i ON i.delyanka_id = d.id WHERE d.id = ?", (delyanka_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Делянка не найдена")
    filtr = karta_pometki.Filtr(conn)
    vid = vidy.vid_rubki_info(row[2], row[3], row[4], row[5])
    props = {"delyanka_id": delyanka_id, "kvartal": row[0], "vydel": row[1], "vid_rubki_kod": vid["vid_rubki_kod"]}
    filtr.razmetit_delyanku(props)
    p = filtr.pom.get(("delyanka", str(delyanka_id))) or {}
    return {
        "skryta": props["skryta"], "skryta_prichina": props["skryta_prichina"],
        "skryta_vruchnuyu": bool(p.get("skryta")),
        "lesokultury": props["lesokultury"], "lk_info": props["lk_info"],
        "lesokultury_rezhim": {True: "da", False: "net"}.get(p.get("lesokultury"), "avto"),
        "mozhno": _rukovoditel(conn, user),
    }


# -------------------------------------------------------------- QGIS-плагин --

@router.get("/api/map/qgis/pometki.json")
def get_pometki_qgis(token: str, conn=Depends(get_conn)):
    _check_service_token(token)
    return {**karta_pometki.dlya_qgis(conn), "skrytye": karta_pometki.spisok_skrytyh(conn),
            "vidy_rubok": _vidy_rubok()}


@router.post("/api/map/qgis/pometki")
def post_pometki_qgis(body: PometkaIn, token: str, conn=Depends(get_conn)):
    _check_service_token(token)
    return _primenit(conn, body, "QGIS")


@router.put("/api/map/qgis/karta-nastroyki")
def put_nastroyki_qgis(body: NastroykiIn, token: str, conn=Depends(get_conn)):
    _check_service_token(token)
    return {"ok": True, "nastroyki": karta_pometki.sohranit_nastroyki(conn, body.model_dump(exclude_none=True))}
