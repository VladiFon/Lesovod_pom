# -*- coding: utf-8 -*-
"""Роутер "Акты освидетельствования" (screens/inspection/) — оборачивает
db.py (чек-лист/пресеты/сроки/история актов), spravka_generator.py и
osvidetelstvovanie_generator.py, без изменения их внутренней логики.

STANDARD_CHECKLIST_ITEMS — перенесён из screens/inspection/screen.py
вашего проекта (lesovod_project_fixed_v5.zip).

compute_sortiment_totals_multi/compute_sortiment_limit_fakt_totals теперь
берутся из legacy/raskhod_v2.py (настоящие функции из вашего
screens/raskhod/balance.py) — раньше здесь стояло приблизительное
переизобретение той же формы в app/aggregations.py (см. docstring этого
файла — оставлен как есть на случай отката, но больше нигде не
импортируется)."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401
import config as legacy_config
import db as legacy_db
import delyanka
import osvidetelstvovanie_generator
import raskhod_v2
import spravka_generator

from app.database import get_conn, get_connection
from app.doc_tasks import new_task_dir, register_document
from app.auth import require_permission
import webext

compute_sortiment_totals_multi = raskhod_v2.compute_sortiment_totals_multi
compute_sortiment_limit_fakt_totals = raskhod_v2.compute_sortiment_limit_fakt_totals

router = APIRouter(prefix="/api/inspection", tags=["inspection"])

STANDARD_CHECKLIST_ITEMS = [
    "Уборка захламлённости",
    "Проверка полноты вывозки древесины (недоруб)",
    "Сохранность подроста и молодняка",
    "Сохранность семенных деревьев",
    "Сохранность лесохозяйственных знаков и границ лесосеки",
    "Состояние лесохозяйственных дорог и подъездных путей",
    "Сохранность плодородного слоя почвы",
    "Очистка лесосеки от порубочных остатков",
]


def _parse_date(value: Optional[str]):
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


@router.get("/")
def list_inspection(conn=Depends(get_conn)):
    """Батч-эквивалент InspectionLoadWorker: список делянок с бейджами
    срочности, % освоения лимита и состоянием чек-листа за один проход.
    Только 'активна' — черновики (сразу после импорта МДО, без номера/даты
    лесорубочного билета) освидетельствовать рано, см. activate_delyanka."""
    delyanki = delyanka.list_delyanki(conn, status="активна")
    ids = [d["id"] for d in delyanki]
    checklists = legacy_db.get_checklists_batch(conn, ids)
    acts = legacy_db.list_osvidetelstvovanie_acts_batch(conn, ids)
    # Инспекция работает по НАРЯДАМ (решение Влада, 2026-10-09): акт
    # освидетельствования и справка берут «Фактически вырублено» из нарядов
    # (compute_sortiment_limit_fakt_totals / compute_sortiment_totals_multi),
    # поэтому и % освоения в списке — по нарядам, чтобы цифра в списке
    # совпадала с цифрой в акте. % по ЕГАИС отдаём рядом для сверки.
    osvoenie = raskhod_v2.compute_osvoenie_batch(conn, ids)

    result = []
    for d in delyanki:
        srok_zagotovki, srok_vyvozki = legacy_db.get_delyanka_sroki(conn, d["id"])
        osv = osvoenie.get(d["id"]) or {}
        pct_osvoeniya = osv.get("pct_naryad")

        deadline = None
        vyvozka_dt = _parse_date(srok_vyvozki)
        if vyvozka_dt:
            deadline = (vyvozka_dt + timedelta(days=30)).strftime("%d.%m.%Y")

        result.append({
            **d,
            "srok_okonchaniya_zagotovki": srok_zagotovki,
            "srok_okonchaniya_vyvozki": srok_vyvozki,
            "srok_osvidetelstvovaniya": deadline,
            "pct_osvoeniya_limita": pct_osvoeniya,
            "pct_osvoeniya_naryad": osv.get("pct_naryad"),
            "pct_osvoeniya_egais": osv.get("pct_egais"),
            "osvoenie_level": raskhod_v2._osvoenie_level(pct_osvoeniya),
            "checklist": checklists.get(d["id"], []),
            "acts": acts.get(d["id"], []),
        })
    return result


class SrokiIn(BaseModel):
    srok_zagotovki: Optional[str] = None
    srok_vyvozki: Optional[str] = None


@router.patch("/{delyanka_id}/sroki")
def set_sroki(delyanka_id: int, body: SrokiIn, user=Depends(require_permission("inspection.edit")),
              conn=Depends(get_conn)):
    legacy_db.set_delyanka_sroki(conn, delyanka_id, body.srok_zagotovki, body.srok_vyvozki)
    return {"ok": True}


# --------------------------------------------------------------------------- #
#   Чек-лист подготовки
# --------------------------------------------------------------------------- #
@router.get("/{delyanka_id}/checklist")
def get_checklist(delyanka_id: int, conn=Depends(get_conn)):
    return legacy_db.get_checklist(conn, delyanka_id)


@router.post("/{delyanka_id}/checklist/ensure")
def ensure_checklist(delyanka_id: int, user=Depends(require_permission("inspection.edit")),
                      conn=Depends(get_conn)):
    legacy_db.ensure_checklist(conn, delyanka_id, STANDARD_CHECKLIST_ITEMS)
    return {"ok": True}


@router.post("/{delyanka_id}/checklist")
def add_checklist_item(delyanka_id: int, text: str, user=Depends(require_permission("inspection.edit")),
                        conn=Depends(get_conn)):
    item_id = legacy_db.add_checklist_item(conn, delyanka_id, text)
    return {"id": item_id}


@router.patch("/checklist/{item_id}")
def set_checklist_item_done(item_id: int, is_done: bool,
                             user=Depends(require_permission("inspection.edit")), conn=Depends(get_conn)):
    legacy_db.set_checklist_item_done(conn, item_id, is_done)
    return {"ok": True}


@router.delete("/checklist/{item_id}")
def delete_checklist_item(item_id: int, user=Depends(require_permission("inspection.edit")),
                           conn=Depends(get_conn)):
    legacy_db.delete_checklist_item(conn, item_id)
    return {"ok": True}


# --------------------------------------------------------------------------- #
#   Пресеты акта освидетельствования
# --------------------------------------------------------------------------- #
@router.get("/presets")
def list_presets(conn=Depends(get_conn)):
    """Пресеты акта + составы комиссий, сохранённые в карточке делянки
    (komissiya_preset): один общий справочник комиссий, а не отдельный
    на каждый документ (анализ удобства 01.10.2026)."""
    own = legacy_db.list_osvidetelstvovanie_presets(conn)
    names = {p["nazvanie"] for p in own}
    for p in delyanka.list_komissiya_presets(conn):
        if p["nazvanie"] in names or not (p.get("predsedatel_fio") or p.get("chleny")):
            continue
        own.append({"nazvanie": p["nazvanie"], "predsedatel_dolzhnost": p.get("predsedatel_dolzhnost") or "",
                    "predsedatel_fio": p.get("predsedatel_fio") or "", "chleny": p.get("chleny") or [],
                    "iz_delyanki": True})
    return sorted(own, key=lambda p: p["nazvanie"])


@router.get("/{delyanka_id}/act-defaults")
def act_defaults(delyanka_id: int, conn=Depends(get_conn)):
    """Что уже известно для акта освидетельствования этой делянки — чтобы
    не заполнять 30+ полей с нуля: № и дата лесорубочного билета
    (основание), разрешённая площадь (сумма по выделам), способ рубки (вид
    рубки выделов), комиссия из карточки делянки, подрост, лесничий из
    Настроек и «постоянные» поля (область, район, руководитель,
    лесопользователь) из последнего составленного акта."""
    d, items = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    out = {}
    last = conn.execute(
        "SELECT data_json FROM osvidetelstvovanie_acts WHERE data_json IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last:
        try:
            prev = json.loads(last[0] or "{}")
        except ValueError:
            prev = {}
        for k in ("oblast", "rayon", "rukovoditel_dolzhnost", "rukovoditel_fio",
                  "predstavitel_lesopolz_organizatsiya", "predstavitel_lesopolz_dolzhnost",
                  "predstavitel_lesopolz_fio", "predstavitel_lesopolzovaniya_dolzhnost",
                  "predstavitel_lesopolzovaniya_fio", "sposob_ucheta", "sposob_ochistki",
                  "vid_osvidetelstvovaniya"):
            if prev.get(k):
                out[k] = prev[k]
    lesnichiy = legacy_db.get_app_login(conn) or {}
    if lesnichiy.get("fio"):
        out["predstavitel_lesxoza_fio"] = lesnichiy["fio"]
        out["predstavitel_lesxoza_dolzhnost"] = lesnichiy.get("dolzhnost") or "Лесничий"
    if d.get("nomer_lesorubochnogo_bileta"):
        out["osnovanie_nomer"] = d["nomer_lesorubochnogo_bileta"]
    if d.get("data_lesorubochnogo_bileta"):
        dt = str(d["data_lesorubochnogo_bileta"])
        out["osnovanie_data"] = f"{dt[8:10]}.{dt[5:7]}.{dt[:4]}" if len(dt) == 10 and dt[4] == "-" else dt
    ploshad = sum(float(it.get("ploshad") or 0) for it in items)
    if ploshad:
        out["ploshad_razresheno"] = str(round(ploshad, 2))
    from app.vidy import vid_rubki_info

    vidy = []
    for it in items:
        info = vid_rubki_info(it.get("vid_rubki_kod"), it.get("mdo_raw_json"))
        nazv = info["vid_rubki"] if info["vid_rubki_kod"] else None
        if nazv and nazv not in vidy:
            vidy.append(nazv)
    if vidy:
        out["sposob_rubki"] = ", ".join(vidy)
    if d.get("predsedatel_fio"):
        out["predsedatel_fio"] = d["predsedatel_fio"]
        out["predsedatel_dolzhnost"] = d.get("predsedatel_dolzhnost") or ""
    try:
        chleny = json.loads(d.get("chleny_json") or "[]")
    except ValueError:
        chleny = []
    if chleny:
        out["chleny"] = chleny
    if d.get("podrost_ploshad"):
        out["podrost_ploshad_ga"] = str(d["podrost_ploshad"])
    if d.get("podrost_tys_sht"):
        out["podrost_kolichestvo_tys"] = str(d["podrost_tys_sht"])
    return out


@router.post("/presets")
def save_preset(nazvanie: str, fields: Dict[str, Any], user=Depends(require_permission("inspection.edit")),
                 conn=Depends(get_conn)):
    legacy_db.save_osvidetelstvovanie_preset(
        conn, nazvanie,
        predsedatel_dolzhnost=fields.pop("predsedatel_dolzhnost", ""),
        predsedatel_fio=fields.pop("predsedatel_fio", ""),
        chleny=fields.pop("chleny", []),
        **fields,
    )
    return {"ok": True}


@router.delete("/presets/{nazvanie}")
def delete_preset(nazvanie: str, user=Depends(require_permission("inspection.edit")), conn=Depends(get_conn)):
    legacy_db.delete_osvidetelstvovanie_preset(conn, nazvanie)
    return {"ok": True}


@router.get("/{delyanka_id}/acts")
def list_acts(delyanka_id: int, conn=Depends(get_conn)):
    return legacy_db.list_osvidetelstvovanie_acts(conn, delyanka_id)


@router.get("/acts/{act_id}/download")
def download_act(act_id: int, conn=Depends(get_conn)):
    """Скачивание файла акта прямо из "Истории актов" — акты хранятся в
    своей таблице (osvidetelstvovanie_acts), отдельно от documents
    (см. save_osvidetelstvovanie_act в _run_generate_akt_osv выше), поэтому
    /api/documents/{id}/download здесь не подходит."""
    act = legacy_db.get_osvidetelstvovanie_act(conn, act_id)
    if act is None:
        raise HTTPException(404, "Акт не найден")
    file_path = act["file_path"]
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(409, "Файл акта недоступен")
    return FileResponse(file_path, filename=Path(file_path).name)


# --------------------------------------------------------------------------- #
#   Генерация документов (фоновые задачи)
# --------------------------------------------------------------------------- #
class SpravkaIn(BaseModel):
    ploshad_proydennaya: Optional[float] = None
    likvid_such_krony: float = 0
    lesopolzovatel: str = ""
    rukovoditel_fio: str = ""


def _run_generate_spravka(task_id: str, delyanka_id: int, body: dict, created_by: Optional[str]):
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        d, items = delyanka.get_delyanka_full(conn, delyanka_id)
        if d is None:
            raise ValueError(f"Делянка {delyanka_id} не найдена")
        sortiment_totals = compute_sortiment_totals_multi(conn, items)
        output_path = task_dir / f"Spravka_{delyanka_id}.docx"
        path = spravka_generator.generate_spravka(d, items, sortiment_totals, str(output_path), **body)
        doc_id = register_document(conn, "spravka", delyanka_id, path, created_by=created_by)
        webext.set_task_done(conn, task_id, result={"document_ids": [doc_id]})
    except Exception as e:  # noqa: BLE001
        register_document(conn, "spravka", delyanka_id, "", created_by=created_by,
                           status="ошибка", error_text=str(e))
        webext.set_task_error(conn, task_id, str(e))
    finally:
        conn.close()


@router.post("/{delyanka_id}/documents/spravka")
def generate_spravka(delyanka_id: int, body: SpravkaIn, background_tasks: BackgroundTasks,
                      user=Depends(require_permission("documents.generate")), conn=Depends(get_conn)):
    d, _ = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    task_id = webext.create_task(conn, "generate_spravka")
    background_tasks.add_task(_run_generate_spravka, task_id, delyanka_id, body.dict(), user["login"])
    return {"task_id": task_id}


def _run_generate_akt_osv(task_id: str, delyanka_id: int, act_data: dict, created_by: Optional[str]):
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        d, items = delyanka.get_delyanka_full(conn, delyanka_id)
        if d is None:
            raise ValueError(f"Делянка {delyanka_id} не найдена")
        sortiment_totals = compute_sortiment_limit_fakt_totals(conn, items)
        output_path = task_dir / f"Akt_osvidetelstvovaniya_{delyanka_id}.docx"
        path = osvidetelstvovanie_generator.generate_akt_osvidetelstvovaniya(
            d, items, sortiment_totals, act_data, str(output_path)
        )
        doc_id = register_document(conn, "akt_osvidetelstvovaniya", delyanka_id, path, created_by=created_by)
        legacy_db.save_osvidetelstvovanie_act(
            conn, delyanka_id, act_data.get("act_date", ""), act_data, path
        )
        webext.set_task_done(conn, task_id, result={"document_ids": [doc_id]})
    except Exception as e:  # noqa: BLE001
        register_document(conn, "akt_osvidetelstvovaniya", delyanka_id, "", created_by=created_by,
                           status="ошибка", error_text=str(e))
        webext.set_task_error(conn, task_id, str(e))
    finally:
        conn.close()


@router.post("/{delyanka_id}/documents/akt-osvidetelstvovaniya")
def generate_akt_osvidetelstvovaniya(delyanka_id: int, act_data: Dict[str, Any],
                                      background_tasks: BackgroundTasks,
                                      user=Depends(require_permission("documents.generate")),
                                      conn=Depends(get_conn)):
    d, _ = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    task_id = webext.create_task(conn, "generate_akt_osvidetelstvovaniya")
    background_tasks.add_task(_run_generate_akt_osv, task_id, delyanka_id, act_data, user["login"])
    return {"task_id": task_id}


def _run_generate_blank_template(task_id: str, created_by: Optional[str]):
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        output_path = task_dir / "Akt_osvidetelstvovaniya_blank.docx"
        path = osvidetelstvovanie_generator.generate_blank_akt_template(str(output_path))
        doc_id = register_document(conn, "blank_akt", None, path, created_by=created_by)
        webext.set_task_done(conn, task_id, result={"document_ids": [doc_id]})
    except Exception as e:  # noqa: BLE001
        register_document(conn, "blank_akt", None, "", created_by=created_by,
                           status="ошибка", error_text=str(e))
        webext.set_task_error(conn, task_id, str(e))
    finally:
        conn.close()


@router.post("/documents/blank-template")
def generate_blank_template(background_tasks: BackgroundTasks,
                             user=Depends(require_permission("documents.generate")),
                             conn=Depends(get_conn)):
    task_id = webext.create_task(conn, "generate_blank_template")
    background_tasks.add_task(_run_generate_blank_template, task_id, user["login"])
    return {"task_id": task_id}
