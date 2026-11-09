# -*- coding: utf-8 -*-
"""Книга учёта площадей лесовосстановления и лесоразведения — API.

* GET    /api/kniga-lvlr                 — все строки с адресом «разворот/строка»
* GET    /api/kniga-lvlr/chto-vpisat     — новые строки, что дописать, что перенести на бумагу
* POST   /api/kniga-lvlr                 — новая строка (из делянки, участка культур или пустая)
* PUT    /api/kniga-lvlr/{id}            — правка граф / числа строк / примечания / участка
* POST   /api/kniga-lvlr/{id}/na-bumage  — «вписал ручкой / вклеил» (все или выбранные графы)
* DELETE /api/kniga-lvlr/{id}            — только последняя строка
* GET/PUT /api/kniga-lvlr/nastroyki      — начало нумерации, ширины граф, шрифт
* GET    /api/kniga-lvlr/vkleyka.docx    — печать разворота (часть 1 / 2 / обе), строки с..по
* GET    /api/kniga-lvlr/kalibrovka.docx — пробный лист с линейкой 100 мм
Логика — app/kniga_lvlr.py, печать — app/kniga_lvlr_docx.py.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app import kniga_lvlr as kn
from app import kniga_lvlr_docx
from app.auth import get_current_user, require_permission
from app.database import get_conn

router = APIRouter(prefix="/api/kniga-lvlr", tags=["kniga-lvlr"])
PRAVO = "lesokultury.edit"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class NovayaIn(BaseModel):
    delyanka_id: Optional[int] = None
    uchastok_id: Optional[int] = None
    vid: Optional[str] = None  # 'spisanie' — строка из списания культур
    grafy: Dict[str, str] = {}


class PravkaIn(BaseModel):
    grafy: Dict[str, str] = {}
    strok: Optional[int] = None
    primechanie: Optional[str] = None
    uchastok_id: Optional[int] = None
    menyat_uchastok: bool = False


class BumagaIn(BaseModel):
    grafy: Optional[List[int]] = None


def _otvet(z: dict) -> dict:
    return {**z, "grafy": {str(k): v for k, v in z["grafy"].items()},
            "na_bumage": {str(k): v for k, v in z["na_bumage"].items()},
            "ne_na_bumage": kn.ne_na_bumage(z)}


@router.get("")
def spisok(conn=Depends(get_conn), _u=Depends(get_current_user)):
    vse = kn.zapisi(conn)
    return {
        "zapisi": [_otvet(z) for z in vse],
        "nastroyki": kn.nastroyki(conn),
        "nazvaniya": {str(k): v for k, v in kn.NAZVANIYA.items()},
        "avto_grafy": sorted(kn.AVTO_GRAFY),
        "vidy_zemel": kn.VIDY_ZEMEL,
        "strok_na_razvorote": kn.STROK_NA_RAZVOROTE,
        "sleduyushchiy_nomer": kn.sleduyushchiy_nomer(conn),
        "svoe": kn.svoe(conn),
        "lesnichestva": kn.lesnichestva(conn),
    }


@router.get("/chto-vpisat")
def chto_vpisat(vse_rubki: bool = False, conn=Depends(get_conn), _u=Depends(get_current_user)):
    out = kn.chto_vpisat(conn, vse_rubki=vse_rubki)
    for x in out["novye"]:
        x["grafy"] = {str(k): v for k, v in x["grafy"].items()}
    return out


@router.get("/nastroyki")
def get_nastroyki(conn=Depends(get_conn), _u=Depends(get_current_user)):
    return kn.nastroyki(conn)


@router.put("/nastroyki")
def put_nastroyki(polya: Dict[str, Any], conn=Depends(get_conn), _u=Depends(require_permission(PRAVO))):
    try:
        return kn.sohranit_nastroyki(conn, polya)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@router.get("/vkleyka.docx")
def vkleyka(razvorot: int, chast: str = "obe", s: int = 1, po: int = kn.STROK_NA_RAZVOROTE,
            nomera_graf: bool = True, setka: bool = True, ids: str = "",
            conn=Depends(get_conn), _u=Depends(get_current_user)):
    if chast not in ("1", "2", "obe"):
        raise HTTPException(400, "chast: 1, 2 или obe")
    tolko = [int(x) for x in ids.split(",") if x.strip().isdigit()] or None
    data = kniga_lvlr_docx.vkleyka(conn, razvorot, chast, s, po, nomera_graf, setka, tolko)
    imya = f"kniga_lvlr_razvorot_{razvorot}_{'chast_' + chast if chast != 'obe' else 'obe'}.docx"
    return Response(data, media_type=DOCX, headers={"Content-Disposition": f'attachment; filename="{imya}"'})


@router.get("/kalibrovka.docx")
def kalibrovka(conn=Depends(get_conn), _u=Depends(get_current_user)):
    return Response(kniga_lvlr_docx.kalibrovka(conn), media_type=DOCX,
                    headers={"Content-Disposition": 'attachment; filename="kniga_lvlr_proverka_pechati.docx"'})


@router.get("/predprosmotr")
def predprosmotr(delyanka_id: Optional[int] = None, uchastok_id: Optional[int] = None,
                 conn=Depends(get_conn), _u=Depends(get_current_user)):
    """Что встанет в графы, если внести эту делянку/участок."""
    g = kn.avto(conn, {"delyanka_id": delyanka_id, "uchastok_id": uchastok_id})
    return {"grafy": {str(k): v for k, v in g.items()}, "nomer": kn.sleduyushchiy_nomer(conn)}


@router.post("")
def sozdat(body: NovayaIn, conn=Depends(get_conn), _u=Depends(require_permission(PRAVO))):
    try:
        z = kn.sozdat(conn, body.delyanka_id, body.uchastok_id, body.grafy, vid=body.vid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _otvet(z)


@router.put("/{zid}")
def pravka(zid: int, body: PravkaIn, conn=Depends(get_conn), _u=Depends(require_permission(PRAVO))):
    try:
        z = kn.obnovit(conn, zid, body.grafy, body.strok, body.primechanie,
                       body.uchastok_id if body.menyat_uchastok else ...)
    except KeyError:
        raise HTTPException(404, "Строка книги не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _otvet(z)


@router.post("/{zid}/na-bumage")
def na_bumage(zid: int, body: BumagaIn, conn=Depends(get_conn), _u=Depends(require_permission(PRAVO))):
    try:
        return _otvet(kn.otmetit_na_bumage(conn, zid, body.grafy))
    except KeyError:
        raise HTTPException(404, "Строка книги не найдена")


@router.delete("/{zid}")
def udalit(zid: int, conn=Depends(get_conn), _u=Depends(require_permission(PRAVO))):
    try:
        sdvinuto = kn.udalit(conn, zid)
    except KeyError:
        raise HTTPException(404, "Строка книги не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "sdvinuto": sdvinuto}
