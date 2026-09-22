# -*- coding: utf-8 -*-
"""
Роутер "Делянки" (screens/plots/) — оборачивает delyanka.py, не меняя его
внутреннюю логику.

Генерация документов (Акт/Листки/Техкарты/Акт готовности) — через
BackgroundTasks с сохранением в /backend/storage/documents/<task_id>/ и
записью в таблицу documents (см. app/doc_tasks.py). Статус опрашивается
через GET /api/tasks/{task_id}.
"""
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import delyanka/db/config
import config as legacy_config
import delyanka
import tehkarta_generator

from app.database import get_conn, get_connection
from app.doc_tasks import new_task_dir, register_document
from app.paths import UPLOADS_DIR
from app.auth import require_permission
import webext

router = APIRouter(prefix="/api/delyanki", tags=["delyanki"])


# --------------------------------------------------------------------------- #
#   CRUD делянок
# --------------------------------------------------------------------------- #
@router.get("/")
def list_delyanki(status: Optional[str] = None, conn=Depends(get_conn)):
    return delyanka.list_delyanki(conn, status=status)


class ManualDelyankaIn(BaseModel):
    nazvanie: str
    kvartal: str
    vydel: str
    lesnichestvo: Optional[str] = None


@router.post("/manual")
def create_delyanka_manual(body: ManualDelyankaIn,
                            user=Depends(require_permission("delyanka.edit")),
                            conn=Depends(get_conn)):
    """Создание делянки с карты (Фаза 6 плана доработки) — один выдел, без
    импорта MDO (см. delyanka.create_delyanka_manual). Тот же смысл, что
    и /import-mdo выше, только источник данных — тап по карте в
    приложении, а не .rtf файл."""
    delyanka_id = delyanka.create_delyanka_manual(
        conn, body.nazvanie, body.kvartal, body.vydel, body.lesnichestvo,
    )
    return {"delyanka_id": delyanka_id}


@router.get("/for-map")
def get_delyanki_for_map(conn=Depends(get_conn)):
    """Облегчённый список для подсветки делянок на живой карте (веб и
    мобильное приложение) — см. delyanka.list_delyanka_items_for_map."""
    return delyanka.list_delyanka_items_for_map(conn)


# --------------------------------------------------------------------------- #
#   Импорт геометрии делянок из QGIS — перенесён в app/routers/map.py как
#   самостоятельный слой карты (POST /api/map/import-layer), больше НЕ
#   создаёт делянки. create_delyanka_from_geometry()/GET /geometries ниже
#   оставлены как есть — только для чтения уже существующих делянок с
#   собственным контуром (были заведены так раньше).
# --------------------------------------------------------------------------- #

@router.get("/geometries")
def get_delyanka_geometries(lesnichestvo: Optional[str] = None, conn=Depends(get_conn)):
    """FeatureCollection собственных контуров делянок (не выделов) — для
    показа на карте (веб LiveMap и мобильное приложение) поверх/вместо
    слоя выделов, там где делянка была заведена через импорт из QGIS и
    несёт свою геометрию (см. delyanka.list_delyanka_geometries)."""
    import json as _json

    rows = delyanka.list_delyanka_geometries(conn, lesnichestvo=lesnichestvo)
    features = []
    for row in rows:
        try:
            geom = _json.loads(row["geom_geojson"])
        except (TypeError, ValueError):
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "item_id": row["item_id"],
                "delyanka_id": row["delyanka_id"],
                "nazvanie": row["nazvanie"],
                "status_rabot": row["status_rabot"],
                "kvartal": row["kvartal"],
                "vydel": row["vydel"],
                "lesnichestvo": row["lesnichestvo"],
                "ploshad": row["ploshad"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


@router.get("/by-location")
def get_delyanki_by_location(kvartal: str, vydel: str, lesnichestvo: Optional[str] = None,
                              conn=Depends(get_conn)):
    """Ищет делянки, у которых есть выдел с таким кварталом/выделом — нужно
    Блоку 2 (живая карта): клик по полигону выдела на карте показывает
    карточку участка (GET /api/taxation/vydel — уже было готово), а этот
    эндпоинт добавляет к ней "это ещё и делянка №N, статус ...", если
    делянка на этот выдел уже заведена в системе.

    ВАЖНО: должен быть объявлен раньше "/{delyanka_id}" ниже — иначе
    FastAPI попытается прочитать "by-location" как delyanka_id: int и
    ответит 422 вместо вызова этого обработчика.

    Возвращает список (обычно 0 или 1 элемент, но delyanka_item не имеет
    уникального ограничения на kvartal+vydel+lesnichestvo, поэтому в
    принципе их может быть несколько — например, старая архивная делянка
    и новая на тот же выдел)."""
    q = """
        SELECT d.id AS delyanka_id, d.nazvanie, d.status AS delyanka_status,
               i.id AS item_id, i.status_rabot, i.ispolnitel_fio, i.data_vypolneniya
        FROM delyanka_item i
        JOIN delyanka d ON d.id = i.delyanka_id
        WHERE i.kvartal = ? AND i.vydel = ?
    """
    params = [kvartal, vydel]
    if lesnichestvo:
        q += " AND i.lesnichestvo LIKE ?"
        params.append(f"%{lesnichestvo}%")
    rows = conn.execute(q, params).fetchall()
    cols = ["delyanka_id", "nazvanie", "delyanka_status", "item_id", "status_rabot",
            "ispolnitel_fio", "data_vypolneniya"]
    return [dict(zip(cols, r)) for r in rows]


@router.get("/{delyanka_id}")
def get_delyanka(delyanka_id: int, conn=Depends(get_conn)):
    d, items = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    return {"delyanka": d, "items": items}


@router.patch("/{delyanka_id}")
def update_delyanka(delyanka_id: int, fields: Dict[str, Any],
                     user=Depends(require_permission("delyanka.edit")), conn=Depends(get_conn)):
    d, _ = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    delyanka.update_delyanka_fields(conn, delyanka_id, **fields)
    webext.touch_updated_by(conn, "delyanka", delyanka_id, user["login"])
    return {"ok": True}


@router.delete("/{delyanka_id}")
def delete_delyanka(delyanka_id: int, user=Depends(require_permission("delyanka.delete")),
                     conn=Depends(get_conn)):
    d, _ = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    delyanka.delete_delyanka(conn, delyanka_id)
    return {"ok": True}


@router.post("/{delyanka_id}/archive")
def archive_delyanka(delyanka_id: int, user=Depends(require_permission("delyanka.edit")),
                      conn=Depends(get_conn)):
    d, _ = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    delyanka.archive_delyanka(conn, delyanka_id)
    webext.touch_updated_by(conn, "delyanka", delyanka_id, user["login"])
    return {"ok": True}


class ActivateDelyankaIn(BaseModel):
    nomer_lesorubochnogo_bileta: str
    data_lesorubochnogo_bileta: str


@router.post("/{delyanka_id}/activate")
def activate_delyanka(delyanka_id: int, body: ActivateDelyankaIn,
                       user=Depends(require_permission("delyanka.edit")), conn=Depends(get_conn)):
    """Переводит делянку (обычно черновик после импорта МДО) в статус
    'активна' — только после этого она попадает в расход и акты
    освидетельствования (см. status= фильтр в list_delyanki)."""
    d, _ = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    try:
        delyanka.activate_delyanka(
            conn, delyanka_id, body.nomer_lesorubochnogo_bileta, body.data_lesorubochnogo_bileta,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    webext.touch_updated_by(conn, "delyanka", delyanka_id, user["login"])
    return {"ok": True}


@router.patch("/items/{item_id}")
def update_item(item_id: int, fields: Dict[str, Any],
                 user=Depends(require_permission("delyanka.edit")), conn=Depends(get_conn)):
    delyanka.update_delyanka_item(conn, item_id, **fields)
    webext.touch_updated_by(conn, "delyanka_item", item_id, user["login"])
    return {"ok": True}


@router.post("/items/{item_id}/abris")
def upload_abris(item_id: int, file: UploadFile = File(...),
                  user=Depends(require_permission("delyanka.edit")), conn=Depends(get_conn)):
    """Сохраняет PNG абриса, привязанный к выделу — заменяет мост
    QWebChannel (AbrisBridge) десктоп-версии обычной загрузкой файла.

    Блок 5 плана доработки отмечал баг: item_id раньше не проверялся —
    несуществующий выдел не давал ошибки, просто "терял" файл на диске
    (save_abris_image молча ничего не обновляет, если UPDATE не находит
    строку). Проверяем явно и отдаём 404, как везде в этом роутере
    (в delyanka.py нет отдельного get_delyanka_item — запрос напрямую,
    без изменения существующей бизнес-логики)."""
    exists = conn.execute("SELECT 1 FROM delyanka_item WHERE id=?", (item_id,)).fetchone()
    if exists is None:
        raise HTTPException(404, "Выдел делянки не найден")
    dest = UPLOADS_DIR / f"abris_{item_id}_{uuid4().hex}_{file.filename}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    delyanka.save_abris_image(conn, item_id, str(dest))
    return {"ok": True, "abris_image_path": str(dest)}


# --------------------------------------------------------------------------- #
#   Импорт МДО (.rtf) — фоновая задача (парсинг + сверка с таксацией)
# --------------------------------------------------------------------------- #
# Блок C.2 плана доработки ("нет окна выбора главного выдела"): раньше
# ask_vydel был заглушкой, всегда возвращавшей "отмена" — delyanka.py молча
# брал первое найденное число как главный выдел, без участия пользователя.
#
# Теперь ask_vydel(text, title) реально показывает диалог, но не через
# Tkinter/Qt (на headless-сервере это невозможно), а через двухшаговый
# веб-флоу: задача переводится в статус 'needs_vydel_choice' с вариантами,
# а этот СИНХРОННЫЙ колбэк (таким его ожидает delyanka.py) блокирует
# фоновый поток на threading.Event, пока фронт не пришлёт ответ через
# POST /api/delyanki/import-mdo/{task_id}/resolve-vydel. Блокировка потока
# безопасна: BackgroundTasks выполняет синхронные функции в отдельном
# потоке threadpool'а (run_in_threadpool), а не в основном event loop'е —
# остальные запросы к API (включая сам resolve-vydel) обрабатываются
# независимо. VYDEL_CHOICE_TIMEOUT_SECONDS — защита от того, чтобы поток
# не завис навсегда, если пользователь закрыл вкладку и не ответил.
VYDEL_CHOICE_TIMEOUT_SECONDS = 20 * 60  # 20 минут

# task_id -> {"event": threading.Event, "answer": Optional[str]}
_pending_vydel_choices: Dict[str, Dict[str, Any]] = {}
_pending_vydel_lock = threading.Lock()

_VYDEL_CANDIDATES_RE = re.compile(r"Указано несколько выделов:\s*(.+)")


def _extract_vydel_candidates(text: str) -> List[str]:
    """Достаёт номера-кандидаты из текста вопроса, который формирует
    delyanka.py (см. create_delyanka_from_mdo) — сам текст туда передаётся
    как есть, отдельного канала для структурированных данных у колбэка
    ask_vydel(text, title) нет, поэтому парсим ту же строку, что видел бы
    пользователь в диалоге."""
    m = _VYDEL_CANDIDATES_RE.search(text)
    raw = m.group(1).splitlines()[0] if m else text
    return re.findall(r"\d+", raw)


def _run_import_mdo(task_id: str, rtf_paths: List[str], merge_into_one: bool):
    conn = get_connection()
    try:
        webext.set_task_running(conn, task_id, progress=f"0/{len(rtf_paths)}")

        def ask_vydel(text: str, title: str) -> str:
            candidates = _extract_vydel_candidates(text)
            event = threading.Event()
            with _pending_vydel_lock:
                _pending_vydel_choices[task_id] = {"event": event, "answer": None}
            webext.set_task_needs_input(
                conn, task_id, "needs_vydel_choice",
                {"question": text, "title": title, "candidates": candidates},
            )
            answered = event.wait(timeout=VYDEL_CHOICE_TIMEOUT_SECONDS)
            with _pending_vydel_lock:
                entry = _pending_vydel_choices.pop(task_id, {})
            if not answered:
                raise TimeoutError(
                    "Не получен ответ на выбор главного выдела в течение "
                    f"{VYDEL_CHOICE_TIMEOUT_SECONDS // 60} минут — запустите импорт заново."
                )
            # Возвращаемся в 'running', чтобы фронт (pollTask) вышел из
            # режима диалога и снова показывал обычный индикатор загрузки —
            # актуально при merge_into_one=True/пачке файлов, где ask_vydel
            # может быть вызван ещё раз для следующего составного выдела.
            webext.set_task_running(conn, task_id, progress=f"0/{len(rtf_paths)}")
            return entry.get("answer") or ""

        if merge_into_one:
            delyanka_id, not_found = delyanka.create_delyanka_from_mdo(conn, rtf_paths, ask_vydel=ask_vydel)
            result = {"delyanka_ids": [delyanka_id], "not_found_in_taxation": not_found, "errors": []}
        else:
            results, errors = delyanka.create_delyanki_from_mdo_batch(conn, rtf_paths, ask_vydel=ask_vydel)
            result = {
                "delyanka_ids": [r[1] for r in results],
                "not_found_in_taxation": [nf for r in results for nf in r[2]],
                "errors": [{"file": e[0], "error": e[1]} for e in errors],
            }
        webext.set_task_done(conn, task_id, result=result)
    except Exception as e:  # noqa: BLE001
        webext.set_task_error(conn, task_id, str(e))
    finally:
        for p in rtf_paths:
            Path(p).unlink(missing_ok=True)
        conn.close()


@router.post("/import-mdo")
def import_mdo(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    merge_into_one: bool = False,
    user=Depends(require_permission("delyanka.edit")),
    conn=Depends(get_conn),
):
    """Загружает один или несколько файлов МДО (.rtf).
    merge_into_one=false (по умолчанию) — штатный сценарий: КАЖДЫЙ файл
    становится ОТДЕЛЬНОЙ делянкой (create_delyanki_from_mdo_batch).
    merge_into_one=true — все файлы объединяются в ОДНУ делянку с
    несколькими выделами (create_delyanka_from_mdo)."""
    saved_paths = []
    for f in files:
        dest = UPLOADS_DIR / f"mdo_{uuid4().hex}_{f.filename}"
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved_paths.append(str(dest))

    task_id = webext.create_task(conn, "import_mdo")
    background_tasks.add_task(_run_import_mdo, task_id, saved_paths, merge_into_one)
    return {"task_id": task_id}


class ResolveVydelIn(BaseModel):
    answer: str = ""


@router.post("/import-mdo/{task_id}/resolve-vydel")
def resolve_vydel_choice(task_id: str, payload: ResolveVydelIn,
                          user=Depends(require_permission("delyanka.edit"))):
    """Отвечает на диалог "выбор главного выдела", которым ask_vydel()
    внутри _run_import_mdo() (см. выше) блокирует фоновый поток при
    составной записи выдела в МДО (Блок C.2 плана доработки).

    payload.answer — номер выдела, который выбрал/ввёл пользователь, либо
    "" (эквивалент нажатия "Отмена" в старом Tkinter-диалоге — delyanka.py
    в этом случае сам берёт первое найденное число как главный выдел, см.
    default_match в create_delyanka_from_mdo)."""
    with _pending_vydel_lock:
        entry = _pending_vydel_choices.get(task_id)
        if entry is None:
            raise HTTPException(
                409,
                "Задача не ожидает выбора выдела (уже отвечена, ещё не дошла "
                "до диалога или истёк таймаут ожидания — запустите импорт заново)",
            )
        entry["answer"] = payload.answer
        entry["event"].set()
    return {"ok": True}


# --------------------------------------------------------------------------- #
#   Пресеты составов комиссии
# --------------------------------------------------------------------------- #
class PresetIn(BaseModel):
    nazvanie: str
    fields: Dict[str, Any] = {}


@router.get("/presets/komissiya")
def list_komissiya_presets(conn=Depends(get_conn)):
    return delyanka.list_komissiya_presets(conn)


@router.post("/presets/komissiya")
def save_komissiya_preset(preset: PresetIn, user=Depends(require_permission("delyanka.edit")),
                           conn=Depends(get_conn)):
    delyanka.save_komissiya_preset(conn, preset.nazvanie, **preset.fields)
    return {"ok": True}


@router.delete("/presets/komissiya/{preset_id}")
def delete_komissiya_preset(preset_id: int, user=Depends(require_permission("delyanka.edit")),
                             conn=Depends(get_conn)):
    delyanka.delete_komissiya_preset(conn, preset_id)
    return {"ok": True}


@router.get("/presets/listok")
def list_listok_presets(conn=Depends(get_conn)):
    return delyanka.list_listok_komissiya_presets(conn)


@router.post("/presets/listok")
def save_listok_preset(preset: PresetIn, user=Depends(require_permission("delyanka.edit")),
                        conn=Depends(get_conn)):
    delyanka.save_listok_komissiya_preset(conn, preset.nazvanie, **preset.fields)
    return {"ok": True}


@router.delete("/presets/listok/{preset_id}")
def delete_listok_preset(preset_id: int, user=Depends(require_permission("delyanka.edit")),
                          conn=Depends(get_conn)):
    delyanka.delete_listok_komissiya_preset(conn, preset_id)
    return {"ok": True}


@router.get("/presets/tehkarta")
def list_tehkarta_presets(conn=Depends(get_conn)):
    return delyanka.list_tehkarta_komissiya_presets(conn)


@router.post("/presets/tehkarta")
def save_tehkarta_preset(preset: PresetIn, user=Depends(require_permission("delyanka.edit")),
                          conn=Depends(get_conn)):
    delyanka.save_tehkarta_komissiya_preset(conn, preset.nazvanie, **preset.fields)
    return {"ok": True}


@router.delete("/presets/tehkarta/{preset_id}")
def delete_tehkarta_preset(preset_id: int, user=Depends(require_permission("delyanka.edit")),
                            conn=Depends(get_conn)):
    delyanka.delete_tehkarta_komissiya_preset(conn, preset_id)
    return {"ok": True}


# --------------------------------------------------------------------------- #
#   Генерация документов делянки (фоновые задачи)
# --------------------------------------------------------------------------- #
def _run_generate_akt(task_id: str, delyanka_id: int, created_by: Optional[str]):
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        output_path = task_dir / f"Akt_{delyanka_id}.xlsx"
        path = delyanka.generate_akt_for_delyanka(
            conn, delyanka_id, templates_dir=legacy_config.RESOURCE_DIR, output_path=str(output_path)
        )
        doc_id = register_document(conn, "akt", delyanka_id, path, created_by=created_by)
        webext.set_task_done(conn, task_id, result={"document_ids": [doc_id]})
    except Exception as e:  # noqa: BLE001
        register_document(conn, "akt", delyanka_id, "", created_by=created_by,
                           status="ошибка", error_text=str(e))
        webext.set_task_error(conn, task_id, str(e))
    finally:
        conn.close()


def _run_generate_listki(task_id: str, delyanka_id: int, created_by: Optional[str]):
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        paths = delyanka.generate_listki_for_delyanka(
            conn, delyanka_id, templates_dir=legacy_config.RESOURCE_DIR, output_dir=str(task_dir)
        )
        doc_ids = [register_document(conn, "listok", delyanka_id, p, created_by=created_by) for p in paths]
        webext.set_task_done(conn, task_id, result={"document_ids": doc_ids})
    except Exception as e:  # noqa: BLE001
        register_document(conn, "listok", delyanka_id, "", created_by=created_by,
                           status="ошибка", error_text=str(e))
        webext.set_task_error(conn, task_id, str(e))
    finally:
        conn.close()


def _run_generate_tehkarty(task_id: str, delyanka_id: int, created_by: Optional[str]):
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        paths = delyanka.generate_tehkarty_for_delyanka(
            conn, delyanka_id, output_dir=str(task_dir), templates_dir=legacy_config.RESOURCE_DIR
        )
        doc_ids = [register_document(conn, "tehkarta", delyanka_id, p, created_by=created_by) for p in paths]
        webext.set_task_done(conn, task_id, result={"document_ids": doc_ids})
    except Exception as e:  # noqa: BLE001
        register_document(conn, "tehkarta", delyanka_id, "", created_by=created_by,
                           status="ошибка", error_text=str(e))
        webext.set_task_error(conn, task_id, str(e))
    finally:
        conn.close()


def _run_generate_akt_gotovnosti(task_id: str, delyanka_id: int, created_by: Optional[str]):
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        d, items = delyanka.get_delyanka_full(conn, delyanka_id)
        if d is None:
            raise ValueError(f"Делянка {delyanka_id} не найдена")
        import json as _json
        d = dict(d)
        d["gotovnost_komissiya"] = _json.loads(d.get("gotovnost_komissiya_json") or "[]")
        output_path = task_dir / f"Akt_gotovnosti_{delyanka_id}.docx"
        path = tehkarta_generator.generate_akt_gotovnosti(d, str(output_path))
        doc_id = register_document(conn, "akt_gotovnosti", delyanka_id, path, created_by=created_by)
        webext.set_task_done(conn, task_id, result={"document_ids": [doc_id]})
    except Exception as e:  # noqa: BLE001
        register_document(conn, "akt_gotovnosti", delyanka_id, "", created_by=created_by,
                           status="ошибка", error_text=str(e))
        webext.set_task_error(conn, task_id, str(e))
    finally:
        conn.close()


@router.post("/{delyanka_id}/documents/akt")
def generate_akt(delyanka_id: int, background_tasks: BackgroundTasks,
                  user=Depends(require_permission("documents.generate")), conn=Depends(get_conn)):
    d, _ = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    task_id = webext.create_task(conn, "generate_akt")
    background_tasks.add_task(_run_generate_akt, task_id, delyanka_id, user["login"])
    return {"task_id": task_id}


@router.post("/{delyanka_id}/documents/listki")
def generate_listki(delyanka_id: int, background_tasks: BackgroundTasks,
                     user=Depends(require_permission("documents.generate")), conn=Depends(get_conn)):
    d, _ = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    task_id = webext.create_task(conn, "generate_listki")
    background_tasks.add_task(_run_generate_listki, task_id, delyanka_id, user["login"])
    return {"task_id": task_id}


@router.post("/{delyanka_id}/documents/tehkarty")
def generate_tehkarty(delyanka_id: int, background_tasks: BackgroundTasks,
                       user=Depends(require_permission("documents.generate")), conn=Depends(get_conn)):
    d, _ = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    task_id = webext.create_task(conn, "generate_tehkarty")
    background_tasks.add_task(_run_generate_tehkarty, task_id, delyanka_id, user["login"])
    return {"task_id": task_id}


@router.post("/{delyanka_id}/documents/akt-gotovnosti")
def generate_akt_gotovnosti_endpoint(delyanka_id: int, background_tasks: BackgroundTasks,
                                      user=Depends(require_permission("documents.generate")),
                                      conn=Depends(get_conn)):
    d, _ = delyanka.get_delyanka_full(conn, delyanka_id)
    if d is None:
        raise HTTPException(404, "Делянка не найдена")
    task_id = webext.create_task(conn, "generate_akt_gotovnosti")
    background_tasks.add_task(_run_generate_akt_gotovnosti, task_id, delyanka_id, user["login"])
    return {"task_id": task_id}
