# -*- coding: utf-8 -*-
"""Роутер экрана "Рубки ухода" (C.3 плана) — тонкий HTTP-слой поверх
legacy/uhody.py (чистая логика расчёта + генерация .docx/.xlsx) и
legacy/db.py (CRUD проб uhody_proby + пресетов комиссии
osvetlenie_komissiya_preset). Роутер сам ничего не считает — все формулы
живут в legacy/uhody.py, фронт тоже не считает сам (см. RubkiUhoda.jsx).

В отличие от черновика этого роутера из отдельного чата (C3_chast2_...) —
здесь используется РЕАЛЬНАЯ инфраструктура проекта, а не самодельная:
  - app.database.get_conn/get_connection — та же зависимость, что и у
    остальных роутеров (taxation.py, raskhod.py, inspection.py);
  - webext.create_task/set_task_running/set_task_done/set_task_error —
    тот же механизм фоновых задач, что и везде, опрашивается через уже
    существующий GET /api/tasks/{task_id} (app/routers/tasks.py) — свой
    эндпоинт опроса не нужен;
  - app.doc_tasks.register_document — сгенерированный файл попадает в
    общую таблицу documents и скачивается через уже существующий
    GET /api/documents/{id}/download (app/routers/documents.py) — свой
    эндпоинт скачивания не нужен. delyanka_id для наших документов всегда
    None (проба не привязана к делянке — см. docstring legacy/uhody.py),
    как и у generate_blank_template в inspection.py;
  - app.auth.require_permission — "uhody.edit" для CRUD проб/пресетов
    (добавлено в legacy/webext.py:PERMISSIONS), "uhody.submit" для создания
    пробы (admin/lesovod/worker), "documents.generate" для генерации
    файлов (то же право, что и у остальных генераторов документов в
    inspection.py/raskhod.py) — GET /proby и /proby/{id} требуют только
    факт входа (get_current_user, без роли: их читает и рабочий из
    мобильного приложения), расчёт-предпросмотр и справочники — без
    авторизации, по образцу taxation.py/lesokultury.py.

Поиск участка по кварталу/выделу НЕ дублируется — фронт напрямую зовёт уже
существующий GET /api/taxation/vydel (та же db.get_vydel_card).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import legacy_bridge  # noqa: F401 — обязателен до import db/uhody
import db as legacy_db
import uhody as legacy_uhody

from app.auth import get_current_user, require_permission
from app.database import get_conn, get_connection
from app.paths import UPLOADS_DIR
from app.doc_tasks import new_task_dir, register_document
import webext

router = APIRouter(prefix="/api/uhody", tags=["uhody"])


# --------------------------------------------------------------------------- #
#   Схемы запросов
# --------------------------------------------------------------------------- #
class KomissiyaData(BaseModel):
    perechet1: str = ""
    perechet2: str = ""
    perechet3: str = ""
    doljnost: str = ""
    fio: str = ""


class UkladkaRow(BaseModel):
    poroda: str = ""
    shirina: Any = None
    vysota: Any = None
    dlina: Any = None


class CalculateRequest(BaseModel):
    rows: list[UkladkaRow] = Field(default_factory=list)
    kol_ploshadok: Any = None
    ploshad_ploshadki: Any = None
    ploshad_lesoseki: Any = None


class RecalculateAreaRequest(BaseModel):
    zapas_na_1ga: Any
    ploshad_lesoseki: Any


class ProbaFormData(BaseModel):
    """Шапка ведомости — те же поля, что build_proba_payload() ожидает в
    form (см. legacy/uhody.py)."""

    lesnichestvo: str = ""
    nomer_lesoseki: str = ""
    ploshad_lesoseki: Any = None
    kategoriya_lesov: str = ""
    vozrast: Any = None
    sostav: str = ""
    polnota: Any = None
    vid_polzovaniya: str = ""
    vid_rubki: str = ""
    sposob_rubki: str = ""
    god_rubki: Any = None
    metod: str = ""
    kol_ploshadok: Any = None
    ploshad_ploshadki: Any = None
    komissiya: KomissiyaData = Field(default_factory=KomissiyaData)


class ProbaSaveRequest(BaseModel):
    kvartal: str
    vydel: str
    ploshad_vydela: Any = None
    data_zamera: str = ""
    rows: list[UkladkaRow] = Field(default_factory=list)
    form: ProbaFormData = Field(default_factory=ProbaFormData)
    # Участки лесных культур, на которых проведена эта проба (доработка
    # «пробы ↔ лесные культуры») — при отметке пробы выполненной на
    # каждом из них автоматически заводится запись «уход выполнен»
    # (см. legacy_db.mark_uhody_proba_completed).
    lesokultury_uchastok_ids: list[int] = Field(default_factory=list)
    # Фото пробы — пути из POST /api/bot/photo: столб границы делянки, где
    # идёт уход, и столб самой пробной площадки. При создании пробы рабочим
    # (мобильное приложение) оба обязательны (400 без них); у офиса и при
    # правке (PATCH) — необязательны: веб-форма пока не умеет грузить фото,
    # а старые пробы фото не имеют. Если переданы — проверяются всегда.
    foto_stolb_delyanki: Optional[str] = None
    foto_stolb_proby: Optional[str] = None


class KomissiyaPresetRequest(BaseModel):
    nazvanie: str
    perechetchik_1: Optional[str] = None
    perechetchik_2: Optional[str] = None
    perechetchik_3: Optional[str] = None
    proveril_doljnost: Optional[str] = None
    proveril_fio: Optional[str] = None


# --------------------------------------------------------------------------- #
#   Справочники для фронтенда
# --------------------------------------------------------------------------- #
@router.get("/porody")
def get_porody() -> dict:
    return {"porody": legacy_uhody.DEFAULT_PORODY, "vidy_rubki": legacy_uhody.VIDY_RUBKI}


# --------------------------------------------------------------------------- #
#   Расчёт (не сохраняет, только считает — кнопка "Рассчитать")
# --------------------------------------------------------------------------- #
@router.post("/calculate")
def calculate(payload: CalculateRequest) -> dict:
    try:
        return legacy_uhody.calculate_proba(
            rows=[row.model_dump() for row in payload.rows],
            kol_prob=payload.kol_ploshadok,
            ploshad_ploshadki=payload.ploshad_ploshadki,
            ploshad_lesoseki=payload.ploshad_lesoseki,
        )
    except legacy_uhody.UhodyValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/calculate/lesoseka")
def calculate_lesoseka(payload: RecalculateAreaRequest) -> dict:
    """Пересчёт только запаса на лесосеку, когда меняется только её
    площадь (без повторного парсинга укладок) — calculate_total_area()."""
    try:
        return {
            "zapas_na_lesoseke": legacy_uhody.calculate_total_area(
                payload.zapas_na_1ga, payload.ploshad_lesoseki
            )
        }
    except legacy_uhody.UhodyValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
#   CRUD проб (uhody_proby)
# --------------------------------------------------------------------------- #
@router.get("/proby")
def list_proby(user=Depends(get_current_user), conn=Depends(get_conn)) -> list[dict]:
    return legacy_db.list_uhody_proby(conn)


@router.get("/proby/{proba_id}")
def get_proba(proba_id: int, user=Depends(get_current_user), conn=Depends(get_conn)) -> dict:
    record = legacy_db.get_uhody_proba(conn, proba_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Проба не найдена.")
    return record


# Фото принимаем только из каталога, куда их кладёт POST /api/bot/photo, и
# только картинки: путь приходит от клиента, без этой проверки можно было бы
# сослаться на любой файл сервера и затем получить его через выдачу фото, а
# html/svg отдавался бы с нашего же origin.
PROBA_PHOTO_DIR = UPLOADS_DIR / "mobile_photos"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
PROBA_PHOTO_LABELS = {
    "foto_stolb_delyanki": "фото столба делянки",
    "foto_stolb_proby": "фото столба пробной площадки",
}


def _resolve_proba_photo(path: str) -> Optional[Path]:
    """Путь → безопасный существующий файл-картинка внутри mobile_photos,
    иначе None."""
    try:
        resolved = Path(path).resolve()
        base = PROBA_PHOTO_DIR.resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(base) or resolved.suffix.lower() not in IMAGE_SUFFIXES:
        return None
    return resolved if resolved.is_file() else None


def _checked_photo_paths(payload: ProbaSaveRequest, required: bool) -> dict:
    """{'foto_stolb_delyanki': путь|None, 'foto_stolb_proby': путь|None} —
    нормализованные пути; 400, если фото обязательны и не переданы, либо
    переданный путь не годится."""
    checked = {}
    for field, label in PROBA_PHOTO_LABELS.items():
        raw = getattr(payload, field)
        if not raw or not raw.strip():
            if required:
                raise HTTPException(
                    status_code=400,
                    detail="Нужны оба фото пробы: столб делянки и столб пробной площадки "
                           f"(не передано: {label}).",
                )
            checked[field] = None
            continue
        resolved = _resolve_proba_photo(raw.strip())
        if resolved is None:
            raise HTTPException(
                status_code=400,
                detail=f"Некорректное {label}: загрузите снимок через POST /api/bot/photo "
                       "и передайте полученный photo_path.",
            )
        checked[field] = str(resolved)
    return checked


def _check_lesokultury_ids(conn, ids: list[int]) -> None:
    if not ids:
        return
    unique = sorted(set(ids))
    placeholders = ",".join("?" for _ in unique)
    found = {r[0] for r in conn.execute(
        f"SELECT id FROM lesokultury_uchastok WHERE id IN ({placeholders})", unique
    ).fetchall()}
    missing = [i for i in unique if i not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"Участки лесных культур не найдены: {missing}")


def _save_proba(conn, payload: ProbaSaveRequest, proba_id: int | None, photos: dict | None = None) -> dict:
    form = payload.form.model_dump()
    try:
        calc_result = legacy_uhody.calculate_proba(
            rows=[row.model_dump() for row in payload.rows],
            kol_prob=payload.form.kol_ploshadok,
            ploshad_ploshadki=payload.form.ploshad_ploshadki,
            ploshad_lesoseki=payload.form.ploshad_lesoseki,
        )
    except legacy_uhody.UhodyValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    data_payload = legacy_uhody.build_proba_payload(form, calc_result)

    kol_ploshadok = payload.form.kol_ploshadok or 0
    ploshad_ploshadki = payload.form.ploshad_ploshadki or 0
    try:
        ploshad_proby = float(kol_ploshadok) * float(ploshad_ploshadki)
    except (TypeError, ValueError):
        ploshad_proby = 0

    new_id = legacy_db.save_uhody_proba(
        conn,
        kvartal=payload.kvartal,
        vydel=payload.vydel,
        ploshad_vydela=payload.ploshad_vydela,
        ploshad_proby=ploshad_proby,
        data_zamera=payload.data_zamera,
        data_json=json.dumps(data_payload, ensure_ascii=False),
        proba_id=proba_id,
        lesokultury_uchastok_ids=payload.lesokultury_uchastok_ids,
    )
    if photos:
        legacy_db.set_uhody_proba_photos(conn, new_id, **photos)
    return legacy_db.get_uhody_proba(conn, new_id)


@router.post("/proby")
def create_proba(
    payload: ProbaSaveRequest,
    user=Depends(require_permission("uhody.submit")),
    conn=Depends(get_conn),
) -> dict:
    """Создание пробы — admin/lesovod из веба и рабочий из мобильного
    приложения (uhody.submit). Для рабочего проба сохраняется с автором
    user["sotrudnik_id"] (тот же принцип identity, что в work-plan/
    attendance/notes — из токена, не из тела запроса); для офиса автор
    остаётся NULL. Править/удалять пробы (PATCH/DELETE) рабочий не может."""
    # Все проверки — до сохранения, чтобы отказ не оставлял недописанную пробу.
    photos = _checked_photo_paths(payload, required=user.get("role") == "worker")
    _check_lesokultury_ids(conn, payload.lesokultury_uchastok_ids)
    record = _save_proba(conn, payload, proba_id=None, photos=photos)
    if user.get("role") == "worker":
        legacy_db.set_uhody_proba_author(conn, record["id"], user["sotrudnik_id"])
        record["sotrudnik_id"] = user["sotrudnik_id"]
        # Уведомление руководителям — только для проб от рабочего (у пробы
        # офиса автор NULL, уведомлять некого: её завёл сам руководитель).
        webext.notify(
            conn, "proba",
            f"Новая проба ухода: кв. {payload.kvartal}, выд. {payload.vydel} — {user['fio']}",
            related_id=record["id"],
        )
    return record


@router.patch("/proby/{proba_id}")
def update_proba(
    proba_id: int,
    payload: ProbaSaveRequest,
    user=Depends(require_permission("uhody.edit")),
    conn=Depends(get_conn),
) -> dict:
    if legacy_db.get_uhody_proba(conn, proba_id) is None:
        raise HTTPException(status_code=404, detail="Проба не найдена.")
    photos = _checked_photo_paths(payload, required=False)
    _check_lesokultury_ids(conn, payload.lesokultury_uchastok_ids)
    return _save_proba(conn, payload, proba_id=proba_id, photos=photos)


@router.get("/proby/{proba_id}/photo/{kind}")
def get_proba_photo(
    proba_id: int,
    kind: Literal["stolb_delyanki", "stolb_proby"],
    user=Depends(get_current_user),
    conn=Depends(get_conn),
):
    """Фото пробы (столб делянки / столб пробной площадки). Файл определяется
    по id пробы, а не по пути из запроса; путь из БД проверяется повторно.
    Нужен вход (как у самой пробы) — поэтому фронтенд грузит картинку
    fetch'ем с токеном, а не прямым <img src>."""
    if legacy_db.get_uhody_proba(conn, proba_id) is None:
        raise HTTPException(status_code=404, detail="Проба не найдена.")
    stored = legacy_db.get_uhody_proba_photo_path(conn, proba_id, kind)
    resolved = _resolve_proba_photo(stored) if stored else None
    if resolved is None:
        raise HTTPException(status_code=404, detail="Фото не приложено.")
    return FileResponse(resolved, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"})


@router.delete("/proby/{proba_id}")
def delete_proba(
    proba_id: int,
    user=Depends(require_permission("uhody.edit")),
    conn=Depends(get_conn),
) -> dict:
    if legacy_db.get_uhody_proba(conn, proba_id) is None:
        raise HTTPException(status_code=404, detail="Проба не найдена.")
    legacy_db.delete_uhody_proba(conn, proba_id)
    return {"ok": True, "id": proba_id}


# --------------------------------------------------------------------------- #
#   Отметка "выполнено" + исполнители (Фаза 2 плана доработки). Отдельный
#   лёгкий /sotrudniki здесь (а не переиспользование GET /api/auth/workers,
#   который требует users.manage — только admin) — лесничий с uhody.edit
#   должен уметь выбрать исполнителя, не имея прав управлять учётками
#   мобильного приложения целиком.
# --------------------------------------------------------------------------- #
@router.get("/sotrudniki")
def list_sotrudniki_for_picker(
    user=Depends(require_permission("uhody.edit")), conn=Depends(get_conn)
) -> list[dict]:
    return [s for s in webext.list_sotrudniki(conn) if s["is_active"]]


@router.get("/lesokultury-uchastki")
def list_lesokultury_uchastki_for_picker(
    search: Optional[str] = None,
    user=Depends(require_permission("uhody.edit")), conn=Depends(get_conn)
) -> list[dict]:
    """Лёгкий список активных участков лесных культур для выбора при
    сохранении пробы (мульти-select «на каких участках проведена проба») —
    тот же принцип, что и /sotrudniki выше."""
    return legacy_db.get_lesokultury_uchastki(conn, include_spisannye=False, search=search)


class CompleteProbaRequest(BaseModel):
    sotrudnik_ids: list[int] = Field(min_length=1)


@router.post("/proby/{proba_id}/complete")
def complete_proba(
    proba_id: int,
    payload: CompleteProbaRequest,
    user=Depends(require_permission("uhody.edit")),
    conn=Depends(get_conn),
) -> dict:
    try:
        return legacy_db.mark_uhody_proba_completed(conn, proba_id, payload.sotrudnik_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/proby/{proba_id}/uncomplete")
def uncomplete_proba(
    proba_id: int,
    user=Depends(require_permission("uhody.edit")),
    conn=Depends(get_conn),
) -> dict:
    if legacy_db.get_uhody_proba(conn, proba_id) is None:
        raise HTTPException(status_code=404, detail="Проба не найдена.")
    legacy_db.unmark_uhody_proba_completed(conn, proba_id)
    return legacy_db.get_uhody_proba(conn, proba_id)


# --------------------------------------------------------------------------- #
#   Пресеты комиссии (osvetlenie_komissiya_preset)
# --------------------------------------------------------------------------- #
@router.get("/komissiya-presets")
def list_komissiya_presets(conn=Depends(get_conn)) -> list[dict]:
    return legacy_db.list_osvetlenie_komissiya_presets(conn)


@router.post("/komissiya-presets")
def save_komissiya_preset(
    payload: KomissiyaPresetRequest,
    user=Depends(require_permission("uhody.edit")),
    conn=Depends(get_conn),
) -> dict:
    preset_id = legacy_db.save_osvetlenie_komissiya_preset(
        conn,
        nazvanie=payload.nazvanie,
        perechetchik_1=payload.perechetchik_1,
        perechetchik_2=payload.perechetchik_2,
        perechetchik_3=payload.perechetchik_3,
        proveril_doljnost=payload.proveril_doljnost,
        proveril_fio=payload.proveril_fio,
    )
    return legacy_db.get_osvetlenie_komissiya_preset(conn, preset_id)


@router.delete("/komissiya-presets/{preset_id}")
def delete_komissiya_preset(
    preset_id: int,
    user=Depends(require_permission("uhody.edit")),
    conn=Depends(get_conn),
) -> dict:
    if legacy_db.get_osvetlenie_komissiya_preset(conn, preset_id) is None:
        raise HTTPException(status_code=404, detail="Пресет не найден.")
    legacy_db.delete_osvetlenie_komissiya_preset(conn, preset_id)
    return {"ok": True, "id": preset_id}


# --------------------------------------------------------------------------- #
#   Генерация документов (.docx / .xlsx) — фоновые задачи, тот же паттерн,
#   что и в inspection.py/raskhod.py: webext.create_task -> BackgroundTasks
#   -> register_document -> webext.set_task_done(result={"document_ids":[..]}).
#   Опрос статуса — существующий GET /api/tasks/{task_id}; скачивание —
#   существующий GET /api/documents/{document_id}/download.
# --------------------------------------------------------------------------- #
def _run_generate_word(task_id: str, proba_id: int, created_by: Optional[str]) -> None:
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        record = legacy_db.get_uhody_proba(conn, proba_id)
        if record is None:
            raise ValueError(f"Проба {proba_id} не найдена")
        document = legacy_uhody.build_osvetlenie_document(record)
        filename = legacy_uhody.build_osvetlenie_docx_filename(record)
        output_path = task_dir / filename
        document.save(str(output_path))
        doc_id = register_document(conn, "uhody_proba_word", None, output_path, created_by=created_by)
        webext.set_task_done(conn, task_id, result={"document_ids": [doc_id]})
    except Exception as exc:  # noqa: BLE001 — тот же паттерн, что и в inspection.py
        register_document(conn, "uhody_proba_word", None, "", created_by=created_by,
                           status="ошибка", error_text=str(exc))
        webext.set_task_error(conn, task_id, str(exc))
    finally:
        conn.close()


def _run_generate_excel(task_id: str, proba_id: int, created_by: Optional[str]) -> None:
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        record = legacy_db.get_uhody_proba(conn, proba_id)
        if record is None:
            raise ValueError(f"Проба {proba_id} не найдена")
        workbook = legacy_uhody.build_osvetlenie_workbook(record)
        filename = legacy_uhody.build_osvetlenie_xlsx_filename(record)
        output_path = task_dir / filename
        workbook.save(str(output_path))
        doc_id = register_document(conn, "uhody_proba_excel", None, output_path, created_by=created_by)
        webext.set_task_done(conn, task_id, result={"document_ids": [doc_id]})
    except Exception as exc:  # noqa: BLE001
        register_document(conn, "uhody_proba_excel", None, "", created_by=created_by,
                           status="ошибка", error_text=str(exc))
        webext.set_task_error(conn, task_id, str(exc))
    finally:
        conn.close()


@router.post("/{proba_id}/documents/word")
def generate_word(
    proba_id: int,
    background_tasks: BackgroundTasks,
    user=Depends(require_permission("documents.generate")),
    conn=Depends(get_conn),
) -> dict:
    if legacy_db.get_uhody_proba(conn, proba_id) is None:
        raise HTTPException(status_code=404, detail="Проба не найдена.")
    task_id = webext.create_task(conn, "generate_uhody_word")
    background_tasks.add_task(_run_generate_word, task_id, proba_id, user["login"])
    return {"task_id": task_id}


@router.post("/{proba_id}/documents/excel")
def generate_excel(
    proba_id: int,
    background_tasks: BackgroundTasks,
    user=Depends(require_permission("documents.generate")),
    conn=Depends(get_conn),
) -> dict:
    if legacy_db.get_uhody_proba(conn, proba_id) is None:
        raise HTTPException(status_code=404, detail="Проба не найдена.")
    task_id = webext.create_task(conn, "generate_uhody_excel")
    background_tasks.add_task(_run_generate_excel, task_id, proba_id, user["login"])
    return {"task_id": task_id}
