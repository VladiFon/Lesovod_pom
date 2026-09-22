# -*- coding: utf-8 -*-
"""Роутер "Учёт заготовки / Книга расхода леса" (screens/raskhod/, экран
RaskhodScreen) — оборачивает legacy/raskhod_v2.py, объединённый и
верифицированный единый источник истины (см. AUDIT.md, раздел 1: старый
корневой raskhod.py и screens/raskhod/{balance,egais,export}.py дублировали
друг друга; raskhod_v2.py — точная построчная выгрузка более полной
screens/raskhod/-версии, без единого изменения логики, см. докстринг
raskhod_v2.py). Старый корневой raskhod.py оставлен нетронутым — им
по-прежнему пользуется telegram_bot.py."""
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401
import config as legacy_config
import delyanka
import raskhod_v2 as legacy_raskhod

from app.database import get_conn, get_connection
from app.doc_tasks import new_task_dir, register_document
from app.paths import UPLOADS_DIR
from app.auth import require_permission
import webext

router = APIRouter(prefix="/api/raskhod", tags=["raskhod"])


def _get_item(conn, item_id: int) -> dict:
    row = conn.execute("SELECT * FROM delyanka_item WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Выдел делянки не найден")
    cols = [d[0] for d in conn.execute("SELECT * FROM delyanka_item WHERE id=?", (item_id,)).description]
    return dict(zip(cols, row))


@router.get("/items/{item_id}/limits")
def get_limits(item_id: int, conn=Depends(get_conn)):
    item = _get_item(conn, item_id)
    return legacy_raskhod.get_limits(item)


@router.get("/items/{item_id}/balance")
def get_balance(item_id: int, conn=Depends(get_conn)):
    item = _get_item(conn, item_id)
    return legacy_raskhod.compute_balance(conn, item, item_id)


@router.get("/items/{item_id}/ploshad")
def get_ploshad_summary(item_id: int, conn=Depends(get_conn)):
    """Площадь делянки / площадь остаток + знаменатель формулы
    автоподсчёта площади наряда (см. raskhod_v2.compute_ploshad_summary).
    Отдельный эндпоинт, а не поле внутри /balance — там ключи верхнего
    уровня это ПОРОДЫ (BalanceTable делает Object.keys(balance)), мешать
    туда служебные поля значило бы аккуратно ловить их как "породу"."""
    item = _get_item(conn, item_id)
    return legacy_raskhod.compute_ploshad_summary(conn, item, item_id)


@router.get("/items/{item_id}/naryady")
def list_naryady(item_id: int, conn=Depends(get_conn)):
    return legacy_raskhod.list_naryady(conn, item_id)


@router.get("/items/{item_id}/egais")
def get_item_egais(item_id: int, conn=Depends(get_conn)):
    """Расход по данным ПОСЛЕДНЕЙ выгрузки ЕГАИС для этого выдела — читает
    egais_snapshot_detail (см. save_egais_snapshot/load_egais_snapshot в
    raskhod_v2.py) и находит запись(-и) по kvartal/vydel тем же "умным"
    поиском, что и телеграм-бот (find_egais_entry_for_item — умеет
    сливать несколько частей составного выдела).

    Отдаёт {imported_at, nazvanie_sklada, porody} , где porody —
    {порода: {сорт_ЕГАИС_или_"дрова": объём}}. ЕГАИС не различает
    крупную/среднюю/мелкую деловую древесину (только "деловая суммой" +
    реальный сорт внутри неё) — это НЕ то же самое, что колонки KR/SR/ML
    у /balance и /naryady, поэтому формат ответа сознательно другой, а
    не подогнан под тот же SORTIMENT_LABELS."""
    item = _get_item(conn, item_id)
    loaded, imported_at = legacy_raskhod.load_egais_snapshot(conn)
    entry = legacy_raskhod.find_egais_entry_for_item(loaded, item)
    return {
        "imported_at": imported_at,
        "nazvanie_sklada": (entry or {}).get("nazvanie_sklada") or "",
        "porody": (entry or {}).get("porody") or {},
    }


@router.delete("/items/{item_id}/egais")
def delete_item_egais(item_id: int, user=Depends(require_permission("raskhod.edit")),
                       conn=Depends(get_conn)):
    """Удаляет данные последней выгрузки ЕГАИС по этому выделу (см.
    legacy_raskhod.delete_egais_snapshot_for_item) - например, если
    выгрузка была загружена ошибочно или устарела для этой делянки.
    Остальных выделов из того же снапшота не касается."""
    item = _get_item(conn, item_id)
    deleted = legacy_raskhod.delete_egais_snapshot_for_item(conn, item)
    if not deleted:
        raise HTTPException(404, "Данных ЕГАИС по этому выделу нет")
    return {"ok": True}


@router.delete("/delyanki/{delyanka_id}/egais")
def delete_delyanka_egais(delyanka_id: int, user=Depends(require_permission("raskhod.edit")),
                           conn=Depends(get_conn)):
    """Массово удаляет данные последней выгрузки ЕГАИС сразу по ВСЕМ
    выделам делянки за один запрос (см.
    legacy_raskhod.delete_egais_snapshot_for_delyanka) - чтобы не заходить
    в каждый выдел по очереди и не жать "Удалить" по десять раз, если
    выгрузка по всей делянке загружена ошибочно или устарела."""
    items = legacy_raskhod.get_delyanka_items(conn, delyanka_id)
    if not items:
        raise HTTPException(404, "Делянка не найдена или в ней нет выделов")
    touched = legacy_raskhod.delete_egais_snapshot_for_delyanka(conn, items)
    if not touched:
        raise HTTPException(404, "Данных ЕГАИС по выделам этой делянки нет")
    return {"ok": True, "items_affected": len(touched), "items_total": len(items)}


class NaryadIn(BaseModel):
    data: str = ""
    nomer_naryada: str = ""
    ploshad: str = ""
    primechanie: str = ""
    pozitsii: List[Dict[str, Any]] = []


@router.post("/items/{item_id}/naryady")
def create_naryad(item_id: int, body: NaryadIn, user=Depends(require_permission("raskhod.edit")),
                   conn=Depends(get_conn)):
    item = _get_item(conn, item_id)
    naryad_id = legacy_raskhod.create_naryad(
        conn, item["delyanka_id"], item_id, body.data,
        nomer_naryada=body.nomer_naryada, ploshad=body.ploshad,
        primechanie=body.primechanie, pozitsii=body.pozitsii,
    )
    return {"id": naryad_id}


class NaryadUpdateIn(BaseModel):
    data: Optional[str] = None
    nomer_naryada: Optional[str] = None
    ploshad: Optional[str] = None
    primechanie: Optional[str] = None
    pozitsii: Optional[List[Dict[str, Any]]] = None


@router.patch("/naryady/{naryad_id}")
def update_naryad(naryad_id: int, body: NaryadUpdateIn,
                   user=Depends(require_permission("raskhod.edit")), conn=Depends(get_conn)):
    legacy_raskhod.update_naryad(
        conn, naryad_id, data=body.data, nomer_naryada=body.nomer_naryada,
        ploshad=body.ploshad, primechanie=body.primechanie, pozitsii=body.pozitsii,
    )
    webext.touch_updated_by(conn, "raskhod_naryad", naryad_id, user["login"])
    return {"ok": True}


@router.delete("/naryady/{naryad_id}")
def delete_naryad(naryad_id: int, user=Depends(require_permission("raskhod.edit")),
                   conn=Depends(get_conn)):
    legacy_raskhod.delete_naryad(conn, naryad_id)
    return {"ok": True}


@router.get("/summary")
def get_species_summary(delyanka_id: Optional[int] = None, conn=Depends(get_conn)):
    """Сводка баланса по породам (B.2 доработок): без delyanka_id — по всем
    активным делянкам сразу, с delyanka_id — только по выделам этой
    делянки. Формат ответа — тот же, что у /items/{item_id}/balance
    (см. compute_balance_totals_multi), рендерится тем же BalanceTable."""
    if delyanka_id is not None:
        items = legacy_raskhod.get_delyanka_items(conn, delyanka_id)
    else:
        items = legacy_raskhod.get_active_delyanka_items(conn)
    return legacy_raskhod.compute_balance_totals_multi(conn, items)


@router.get("/remaining")
def get_remaining(kvartal: str, vydel: str, lesoseka: Optional[str] = None, conn=Depends(get_conn)):
    return legacy_raskhod.get_remaining_volumes_for_bot(conn, kvartal, vydel, lesoseka=lesoseka)


# --------------------------------------------------------------------------- #
#   Импорт выгрузки ЕГАИС (.xlsx) — фоновая задача
# --------------------------------------------------------------------------- #
def _run_import_egais(task_id: str, xlsx_path: str):
    conn = get_connection()
    try:
        webext.set_task_running(conn, task_id)
        loaded = legacy_raskhod.parse_egais_reestr(xlsx_path)
        legacy_raskhod.save_egais_snapshot(conn, loaded)
        webext.set_task_done(conn, task_id, result={"imported": True})
    except Exception as e:  # noqa: BLE001
        webext.set_task_error(conn, task_id, str(e))
    finally:
        Path(xlsx_path).unlink(missing_ok=True)
        conn.close()


@router.post("/egais/import")
def import_egais(background_tasks: BackgroundTasks, file: UploadFile = File(...),
                  user=Depends(require_permission("raskhod.edit")), conn=Depends(get_conn)):
    dest = UPLOADS_DIR / f"egais_{uuid4().hex}_{file.filename}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    task_id = webext.create_task(conn, "import_egais")
    background_tasks.add_task(_run_import_egais, task_id, str(dest))
    return {"task_id": task_id}


# --------------------------------------------------------------------------- #
#   Экспорт "Книги расхода леса" в Excel — фоновая задача
# --------------------------------------------------------------------------- #
def _run_export_excel(task_id: str, item_id: int, created_by: Optional[str]):
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        item = _get_item(conn, item_id)
        d, _ = delyanka.get_delyanka_full(conn, item["delyanka_id"])
        if d is None:
            raise ValueError(f"Делянка {item['delyanka_id']} не найдена")
        output_path = task_dir / f"Raskhod_{item_id}.xlsx"
        path = legacy_raskhod.export_to_excel(
            conn, d, item, str(output_path), templates_dir=legacy_config.RESOURCE_DIR
        )
        doc_id = register_document(conn, "raskhod_export", item["delyanka_id"], path, created_by=created_by)
        webext.set_task_done(conn, task_id, result={"document_ids": [doc_id]})
    except Exception as e:  # noqa: BLE001
        register_document(conn, "raskhod_export", None, "", created_by=created_by,
                           status="ошибка", error_text=str(e))
        webext.set_task_error(conn, task_id, str(e))
    finally:
        conn.close()


@router.post("/items/{item_id}/export")
def export_item(item_id: int, background_tasks: BackgroundTasks,
                 user=Depends(require_permission("documents.generate")), conn=Depends(get_conn)):
    _get_item(conn, item_id)  # 404 если выдела нет
    task_id = webext.create_task(conn, "export_raskhod")
    background_tasks.add_task(_run_export_excel, task_id, item_id, user["login"])
    return {"task_id": task_id}


# --------------------------------------------------------------------------- #
#   Расход → ЕГАИС: очереди на ручной разбор при импорте (см. комментарии у
#   egais_korrektirovka_review / egais_unmatched_delyanka /
#   egais_fls_prihod_review в legacy/db.py и _save_egais_review_queues в
#   legacy/raskhod_v2.py). Три независимых механизма, каждый закрывается
#   отдельно от остальных.
# --------------------------------------------------------------------------- #
def _now_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@router.get("/egais/review/summary")
def egais_review_summary(user=Depends(require_permission("raskhod.edit")), conn=Depends(get_conn)):
    """Счётчики новых (ещё не разобранных) записей в каждой из трёх
    очередей — для бейджей на вкладках экрана."""
    def count(table):
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE status='new'").fetchone()[0]
    return {
        "korrektirovki_new": count("egais_korrektirovka_review"),
        "unmatched_delyanka_new": count("egais_unmatched_delyanka"),
        "fls_prihod_new": count("egais_fls_prihod_review"),
    }


@router.get("/egais/review/korrektirovki")
def list_korrektirovki_review(status: str = "new", user=Depends(require_permission("raskhod.edit")),
                               conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM egais_korrektirovka_review WHERE status=? ORDER BY data_dok DESC, id DESC",
        (status,),
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM egais_korrektirovka_review LIMIT 0").description]
    return [dict(zip(cols, r)) for r in rows]


class ReviewResolveIn(BaseModel):
    status: str  # "resolved" | "ignored"


@router.post("/egais/review/korrektirovki/{row_id}/resolve")
def resolve_korrektirovka(row_id: int, body: ReviewResolveIn,
                           user=Depends(require_permission("raskhod.edit")), conn=Depends(get_conn)):
    if body.status not in ("resolved", "ignored"):
        raise HTTPException(400, "status должен быть 'resolved' или 'ignored'")
    cur = conn.execute(
        "UPDATE egais_korrektirovka_review SET status=?, resolved_by=?, resolved_at=? "
        "WHERE id=? AND status='new'",
        (body.status, user["login"], _now_str(), row_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "Запись не найдена или уже разобрана")
    return {"ok": True}


@router.get("/egais/review/unmatched-delyanka")
def list_unmatched_delyanka(status: str = "new", user=Depends(require_permission("raskhod.edit")),
                             conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM egais_unmatched_delyanka WHERE status=? ORDER BY last_seen_at DESC, id DESC",
        (status,),
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM egais_unmatched_delyanka LIMIT 0").description]
    return [dict(zip(cols, r)) for r in rows]


class UnmatchedLinkIn(BaseModel):
    delyanka_id: int


@router.post("/egais/review/unmatched-delyanka/{row_id}/link")
def link_unmatched_delyanka(row_id: int, body: UnmatchedLinkIn,
                             user=Depends(require_permission("raskhod.edit")), conn=Depends(get_conn)):
    exists = conn.execute("SELECT 1 FROM delyanka WHERE id=?", (body.delyanka_id,)).fetchone()
    if exists is None:
        raise HTTPException(404, f"Делянка {body.delyanka_id} не найдена")
    cur = conn.execute(
        "UPDATE egais_unmatched_delyanka SET status='linked', linked_delyanka_id=?, "
        "resolved_by=?, resolved_at=? WHERE id=? AND status='new'",
        (body.delyanka_id, user["login"], _now_str(), row_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "Запись не найдена или уже разобрана")
    return {"ok": True}


@router.post("/egais/review/unmatched-delyanka/{row_id}/ignore")
def ignore_unmatched_delyanka(row_id: int, user=Depends(require_permission("raskhod.edit")),
                               conn=Depends(get_conn)):
    cur = conn.execute(
        "UPDATE egais_unmatched_delyanka SET status='ignored', resolved_by=?, resolved_at=? "
        "WHERE id=? AND status='new'",
        (user["login"], _now_str(), row_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "Запись не найдена или уже разобрана")
    return {"ok": True}


@router.get("/egais/review/fls-prihod")
def list_fls_prihod_review(status: str = "new", user=Depends(require_permission("raskhod.edit")),
                            conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM egais_fls_prihod_review WHERE status=? ORDER BY data_dok DESC, id DESC",
        (status,),
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM egais_fls_prihod_review LIMIT 0").description]
    return [dict(zip(cols, r)) for r in rows]


class FlsPrihodResolveIn(BaseModel):
    status: str  # "schitat_otdelno" | "privyazan_k_pls" | "ignored"


@router.post("/egais/review/fls-prihod/{row_id}/resolve")
def resolve_fls_prihod(row_id: int, body: FlsPrihodResolveIn,
                        user=Depends(require_permission("raskhod.edit")), conn=Depends(get_conn)):
    if body.status not in ("schitat_otdelno", "privyazan_k_pls", "ignored"):
        raise HTTPException(400, "status должен быть 'schitat_otdelno', 'privyazan_k_pls' или 'ignored'")

    row = conn.execute(
        "SELECT kvartal, vydel, poroda, sortiment, obyom, sklad FROM egais_fls_prihod_review "
        "WHERE id=? AND status='new'",
        (row_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Запись не найдена или уже разобрана")
    kvartal, vydel, poroda, sortiment, obyom, sklad = row

    if body.status == "schitat_otdelno":
        # Лесничий подтвердил: это ОТДЕЛЬНАЯ заготовка (не часть уже
        # посчитанной цепочки ФЛС→ПЛС) - пишем объём сразу в ОБА снапшота
        # ЕГАИС (плоский egais_snapshot для бота и детальный
        # egais_snapshot_detail для веб-баланса) - см. докстринг
        # legacy_raskhod.add_fls_prihod_to_egais_snapshot: раньше сюда
        # писался только плоский снапшот, из-за чего разобранная ФЛС не
        # попадала в таблицу баланса на экране "Расход" (особенно заметно,
        # если в выгрузке вообще нет обычных приходов на ПЛС).
        legacy_raskhod.add_fls_prihod_to_egais_snapshot(
            conn, kvartal, vydel, poroda, sortiment, obyom, sklad, review_row_id=row_id
        )
    # "privyazan_k_pls" и "ignored" не трогают egais_snapshot - объём либо
    # уже учтён соответствующим приходом на ПЛС, либо сознательно пропущен.

    conn.execute(
        "UPDATE egais_fls_prihod_review SET status=?, resolved_by=?, resolved_at=? WHERE id=?",
        (body.status, user["login"], _now_str(), row_id),
    )
    conn.commit()
    return {"ok": True}
