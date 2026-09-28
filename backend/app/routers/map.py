# -*- coding: utf-8 -*-
"""Роутер "Живая карта" (screens/live_map/) — оборачивает forest_map.py без
изменения его внутренней логики (Этап 2 доработки лишь ДОБАВИЛ в
forest_map.py bbox-стриминг, не тронув generate_forest_map()/
get_sanitary_vydely()). Требует geopandas в окружении backend'а (см.
AUDIT.md/requirements.txt) и файлы map_kvartala.geojson/map_vydela.geojson
в RESOURCE_DIR (legacy/config.py); folium нужен только для /generate
(HTML-экспорт), сама живая карта на нём больше не основана."""
from pathlib import Path
from typing import Optional
import hmac

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401
import config as legacy_config
import forest_map
import map_import
import sklad as sklad_store

from app.database import get_conn, get_connection
from app.doc_tasks import new_task_dir, register_document
from app import map_features
from app.auth import get_current_user, map_reader, require_permission
import webext

router = APIRouter(prefix="/api/map", tags=["map"])



def _lesnichestvo_name(lesnichestvo_num: Optional[str]) -> Optional[str]:
    """num_lch (то, чем оперируют /kvartaly, /vydela и выбор в LiveMap.jsx)
    -> название лесничества (то, чем хранятся lesnichestvo в остальных
    таблицах, включая imported_map_layer) — через тот же LCH_MAP, что и
    везде. Если соответствия нет — используем сам номер как есть, лишь бы
    не терять фильтр."""
    if not lesnichestvo_num:
        return None
    matches = [k for k, v in legacy_config.LCH_MAP.items() if str(v) == str(lesnichestvo_num)]
    return matches[0] if matches else str(lesnichestvo_num)


@router.get("/lesnichestva")
def list_lesnichestva():
    """{"название лесничества": "номер (num_lch)"} — см. legacy/config.py
    и legacy/lch_map.json."""
    return legacy_config.LCH_MAP


@router.get("/sanitary")
def get_sanitary(lesnichestvo_num: str, _user=Depends(map_reader)):
    return forest_map.get_sanitary_vydely(legacy_config.DB_PATH, lesnichestvo_num)


def _map_layer_error_to_http(e: Exception) -> HTTPException:
    """Единая точка перевода ошибок forest_map.get_map_layer_geojson() в
    HTTP-статусы — используется обоими эндпоинтами ниже, чтобы не
    дублировать один и тот же except-блок."""
    if isinstance(e, ValueError):
        return HTTPException(400, str(e))
    if isinstance(e, FileNotFoundError):
        return HTTPException(404, str(e))
    if isinstance(e, ImportError):
        return HTTPException(
            503,
            "Для живой карты нужен пакет geopandas на сервере backend'а — "
            "раскомментируйте его в requirements.txt и переустановите "
            f"зависимости ({e}).",
        )
    return HTTPException(500, f"Не удалось построить слой карты: {e}")


@router.get("/kvartaly")
def get_kvartaly_layer(lesnichestvo_num: str, bbox: Optional[str] = None, zoom: Optional[float] = None,
                      _user=Depends(map_reader)):
    """GeoJSON границ кварталов, обрезанный по bbox текущего вида карты и
    упрощённый под zoom (см. forest_map.get_map_layer_geojson). bbox —
    строка "minLon,minLat,maxLon,maxLat" (LiveMap.jsx собирает её из
    L.LatLngBounds на moveend/zoomend); без bbox отдаётся весь слой
    лесничества целиком."""
    try:
        return forest_map.get_map_layer_geojson(
            legacy_config.DB_PATH, lesnichestvo_num, "kvartaly", bbox=bbox, zoom=zoom,
        )
    except Exception as e:  # noqa: BLE001
        raise _map_layer_error_to_http(e)


@router.get("/vydela")
def get_vydela_layer(lesnichestvo_num: str, bbox: Optional[str] = None, zoom: Optional[float] = None,
                     _user=Depends(map_reader)):
    """То же самое для выделов (map_vydela.geojson, 56 МБ исходник —
    поэтому bbox здесь не опция, а необходимость, см. PLAN_DORABOTKI.md).
    properties каждого feature дополнены status_color/status_label —
    подсветкой по категории выполненных работ (completed_works), той же,
    что рисует HTML-версия карты (generate_forest_map/_vydel_style)."""
    try:
        return forest_map.get_map_layer_geojson(
            legacy_config.DB_PATH, lesnichestvo_num, "vydela", bbox=bbox, zoom=zoom,
        )
    except Exception as e:  # noqa: BLE001
        raise _map_layer_error_to_http(e)


# --------------------------------------------------------------------------- #
#   Импорт из QGIS — самостоятельный слой карты (см. legacy/map_import.py)
# --------------------------------------------------------------------------- #
# По явному решению (см. чат) — файл со съёмкой из QGIS/'Лесной страж' не
# создаёт делянки (как было раньше, см. историю app/routers/delyanki.py),
# а просто ложится на Живую карту отдельным слоем поверх кварталов/
# выделов, никак не привязанным к делянкам. Слой хранится целиком (не по
# bbox — обычно это десятки-сотни объектов одной съёмки, не 56 МБ, как
# map_vydela.geojson) и отдаётся сразу целиком при выборе лесничества.

@router.post("/import-layer")
async def import_map_layer(
    file: UploadFile = File(...),
    layer_name: Optional[str] = None,
    lesnichestvo_num: Optional[str] = None,
    conn=Depends(get_conn),
    user=Depends(require_permission("map.import")),
):
    """Загружает GeoJSON/Shapefile (.zip) или экспорт 'Лесной страж' и
    сохраняет его как отдельный слой карты (imported_map_layer). Один
    файл = один batch_id — им же слой убирается с карты целиком, см.
    DELETE /import-layers/{batch_id}.

    require_permission("map.import") добавлена 16.09.2026 — раньше этот
    эндпоинт принимал файл от кого угодно без всякой проверки (см.
    legacy/config.py:get_map_import_service_token, почему это
    обнаружилось именно сейчас и почему это не мелочь)."""
    suffix = Path(file.filename or "").suffix.lower() or ".geojson"
    if suffix not in (".geojson", ".json", ".zip", ".shp"):
        raise HTTPException(400, "Поддерживаются файлы .geojson/.json или .zip (Shapefile)")

    content = await file.read()
    try:
        features = map_import.parse_uploaded_file(content, suffix)
    except ImportError as e:
        raise HTTPException(
            503,
            "Для импорта из QGIS нужен пакет geopandas на сервере backend'а "
            f"(см. requirements.txt) ({e}).",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001 — не geopandas/парсинг-специфичная ошибка
        raise HTTPException(400, f"Не удалось прочитать файл: {e}")

    if not features:
        raise HTTPException(400, "В файле не найдено ни одного объекта (геометрии)")

    return map_import.create_import_batch(
        conn, layer_name or (file.filename or "Импорт QGIS"),
        _lesnichestvo_name(lesnichestvo_num), features,
    )


@router.get("/import-layers")
def get_import_layers(lesnichestvo_num: Optional[str] = None, conn=Depends(get_conn), _user=Depends(map_reader)):
    """FeatureCollection всех импортированных слоёв — независимый от
    делянок оверлей на Живой карте (см. LiveMap.jsx)."""
    return map_import.list_import_layer_geojson(conn, lesnichestvo=_lesnichestvo_name(lesnichestvo_num))


@router.get("/import-layers/batches")
def get_import_batches(lesnichestvo_num: Optional[str] = None, conn=Depends(get_conn), _user=Depends(map_reader)):
    """Список загруженных файлов (для панели управления слоями в
    LiveMap.jsx — посмотреть что уже загружено и убрать одну загрузку
    целиком)."""
    return map_import.list_import_batches(conn, lesnichestvo=_lesnichestvo_name(lesnichestvo_num))


def _check_service_token(token: Optional[str]) -> None:
    """Токен QGIS-моста в строке запроса (?token=...) — QGIS умеет добавить
    слой только по URL целиком, свой заголовок туда не вставить."""
    service_token = legacy_config.get_map_import_service_token()
    if not service_token or not token or not hmac.compare_digest(token, service_token):
        raise HTTPException(403, "Неверный токен")


@router.get("/geo-notes.geojson")
def get_geo_notes_geojson(token: str, conn=Depends(get_conn)):
    """Обратное направление к QGIS-мосту (16.09.2026) — метки/заметки,
    которые рабочие оставляют с телефона (POST /api/bot/geo-notes),
    отданные как GeoJSON, специально чтобы QGIS мог подключить этот адрес
    напрямую как обычный слой (Слой -> Добавить слой -> Добавить векторный
    слой -> протокол HTTP(S)/облако, вставить URL) — обновляется кнопкой
    "Reload" в QGIS. Плагин «Лесовод-мост» (кнопка «Метки рабочих»)
    добавляет этот слой сам, с подписями и всплывающим окном с фото.

    Токен — параметром строки запроса (?token=...), а не заголовком
    Authorization: диалог "Добавить векторный слой" в QGIS принимает
    только URL целиком. Сверяется с тем же LESOVOD_MAP_IMPORT_SERVICE_TOKEN,
    что и публикация в обратную сторону (POST /import-layer).

    28.09.2026: добавлены author_fio, kategoriya (+ подпись и цвет) и
    photo_url — адрес фото относительно сервера, к которому клиент сам
    дописывает ?token= (фото отдаёт GET /geo-notes/{id}/photo ниже)."""
    _check_service_token(token)
    labels = {c["code"]: c for c in map_features.GEO_NOTE_CATEGORIES}
    features = []
    for note in map_features.list_geo_notes(conn):
        category = labels[note["kategoriya"]]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [note["lon"], note["lat"]]},
            "properties": {
                "id": note["id"],
                "telegram_id": note["telegram_id"],
                "author_fio": note["author_fio"],
                "note_text": note["note_text"],
                "kategoriya": note["kategoriya"],
                "kategoriya_label": category["label"],
                "color": category["color"],
                "photo_url": f"/api/map/geo-notes/{note['id']}/photo" if note["has_photo"] else None,
                "created_at": note["created_at"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


@router.get("/geo-notes/{note_id}/photo")
def get_geo_note_photo_for_qgis(note_id: int, token: str, conn=Depends(get_conn)):
    """Фото метки для всплывающего окна в QGIS (<img src="...?token=...">)."""
    _check_service_token(token)
    return _geo_note_photo_response(conn, note_id)


def _geo_note_photo_response(conn, note_id: int):
    row = map_features.geo_note_photo_path(conn, note_id)
    if row is None or not row[1]:
        raise HTTPException(404, "Фото не найдено")
    path = Path(row[1])
    if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".heic"}:
        raise HTTPException(404, "Фото не найдено")
    return FileResponse(str(path), headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"})


# --------------------------------------------------------------------------- #
#   Карта мобильного приложения (28.09.2026): цвета, статусы, поиск, история
# --------------------------------------------------------------------------- #
@router.get("/work-colors")
def get_work_colors(lesnichestvo_num: str, conn=Depends(get_conn), _user=Depends(get_current_user)):
    """Раскраска выделов по видам выполненных работ — отдельно от геометрии
    (GET /vydela), чтобы телефон мог держать геометрию в кэше неделями, а
    цвета обновлять каждые несколько минут."""
    return map_features.work_colors(conn, lesnichestvo_num)


@router.get("/delyanka-statuses")
def get_delyanka_statuses(_user=Depends(get_current_user)):
    """Легенда статусов делянок (delyanka_item.status_rabot)."""
    return map_features.DELYANKA_STATUSES


@router.get("/search")
def search_map(q: str, lesnichestvo_num: Optional[str] = None, conn=Depends(get_conn),
               _user=Depends(get_current_user)):
    """Поиск по кварталу ("12"), выделу ("12/5", "кв 12 выд 5"), делянке
    (по названию) и лесным культурам (порода, год)."""
    return map_features.search(conn, q, lesnichestvo_num)


@router.get("/lesokultury")
def get_lesokultury_for_map(lesnichestvo_num: Optional[str] = None, conn=Depends(get_conn),
                            _user=Depends(get_current_user)):
    """Участки лесных культур для подсветки выделов на карте."""
    return map_features.lesokultury_for_map(conn, lesnichestvo_num)


@router.get("/vydel-history")
def get_vydel_history(kvartal: str, vydel: str, lesnichestvo_num: Optional[str] = None,
                      conn=Depends(get_conn), _user=Depends(get_current_user)):
    """Что делали на выделе: выполненные работы, делянки, лесные культуры."""
    return map_features.vydel_history(conn, lesnichestvo_num, kvartal, vydel)


@router.get("/completed-work/{work_id}/photo")
def get_completed_work_photo(work_id: int, conn=Depends(get_conn), _user=Depends(get_current_user)):
    """Фото выполненной работы для истории выдела (по id, а не по пути на диске)."""
    row = conn.execute("SELECT photo_path FROM completed_works WHERE id=?", (work_id,)).fetchone()
    if row is None or not row[0]:
        raise HTTPException(404, "Фото не найдено")
    path = Path(row[0])
    if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}:
        raise HTTPException(404, "Фото не найдено")
    return FileResponse(str(path), headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"})


# --------------------------------------------------------------------------- #
#   Слои для QGIS (кнопки плагина «Лесовод-мост»), токен — как у geo-notes
# --------------------------------------------------------------------------- #
def _vydel_polygons(lesnichestvo_num: Optional[str], wanted: dict):
    """{(num_lch, кв, выд): props} -> Features с полигонами выделов из
    map_vydela.geojson (своей геометрии у делянок/л/к обычно нет)."""
    nums = [lesnichestvo_num] if lesnichestvo_num else sorted({k[0] for k in wanted})
    features = []
    for num in nums:
        try:
            gdf = forest_map._read_filtered_layer(
                forest_map.FOREST_MAP_VYDELA_GEOJSON, num,
                forest_map.FOREST_MAP_SOURCE_EPSG, forest_map.FOREST_MAP_TARGET_EPSG,
            )
        except Exception as e:  # noqa: BLE001
            raise _map_layer_error_to_http(e)
        if gdf.empty:
            continue
        for _, row in gdf.iterrows():
            key = (str(num), map_features.norm_id(row.get("num_kv")), map_features.norm_id(row.get("num_vd")))
            for props in wanted.get(key, []):
                features.append({
                    "type": "Feature",
                    "geometry": row.geometry.__geo_interface__,
                    "properties": props,
                })
    return {"type": "FeatureCollection", "features": features}


def _num_for_lesnichestvo(name: Optional[str]) -> Optional[str]:
    canonical = map_features.canonical_lesnichestvo(name)
    num = legacy_config.LCH_MAP.get(canonical) if canonical else None
    return str(num) if num is not None else None


@router.get("/qgis/delyanki.geojson")
def get_delyanki_geojson_for_qgis(token: str, lesnichestvo_num: Optional[str] = None, conn=Depends(get_conn)):
    """Делянки со статусом работ — полигоны выделов, для QGIS."""
    _check_service_token(token)
    colors = {s["status"]: s["color"] for s in map_features.DELYANKA_STATUSES}
    wanted: dict = {}
    for item_id, d_id, nazvanie, kv, vd, lesn, status_rabot, ploshad in conn.execute(
        """SELECT i.id, d.id, d.nazvanie, i.kvartal, i.vydel, i.lesnichestvo, i.status_rabot, i.ploshad
           FROM delyanka_item i JOIN delyanka d ON d.id = i.delyanka_id"""
    ).fetchall():
        num = _num_for_lesnichestvo(lesn)
        if num is None or (lesnichestvo_num and num != str(lesnichestvo_num)):
            continue
        status = status_rabot or map_features.STATUS_WAITING
        wanted.setdefault((num, map_features.norm_id(kv), map_features.norm_id(vd)), []).append({
            "item_id": item_id, "delyanka_id": d_id, "nazvanie": nazvanie,
            "kvartal": map_features.norm_id(kv), "vydel": map_features.norm_id(vd),
            "lesnichestvo": lesn, "status_rabot": status, "color": colors.get(status, "#9e9e9e"),
            "ploshad": ploshad,
        })
    return _vydel_polygons(lesnichestvo_num, wanted)


@router.get("/qgis/lesokultury.geojson")
def get_lesokultury_geojson_for_qgis(token: str, lesnichestvo_num: Optional[str] = None, conn=Depends(get_conn)):
    """Участки лесных культур — полигоны выделов, для QGIS."""
    _check_service_token(token)
    wanted: dict = {}
    for u in map_features.lesokultury_for_map(conn, lesnichestvo_num):
        num = _num_for_lesnichestvo(u["lesnichestvo"])
        if num is None or (lesnichestvo_num and num != str(lesnichestvo_num)):
            continue
        wanted.setdefault((num, u["kvartal"], u["vydel"]), []).append(u)
    return _vydel_polygons(lesnichestvo_num, wanted)


@router.get("/qgis/tracks.geojson")
def get_tracks_geojson_for_qgis(token: str, conn=Depends(get_conn)):
    """Контуры, обмеренные обходом с телефона."""
    _check_service_token(token)
    features = []
    for t in map_features.list_tracks(conn):
        geometry = t.pop("geometry")
        features.append({"type": "Feature", "geometry": geometry, "properties": t})
    return {"type": "FeatureCollection", "features": features}


@router.delete("/import-layers/{batch_id}")
def delete_import_layer(
    batch_id: str,
    conn=Depends(get_conn),
    user=Depends(require_permission("map.import")),
):
    deleted = map_import.delete_import_batch(conn, batch_id)
    if not deleted:
        raise HTTPException(404, "Слой с таким batch_id не найден")
    return {"deleted": deleted}


# --------------------------------------------------------------------------- #
#   Склады — точки на карте, добавляются/удаляются вручную по координатам
#   (см. legacy/sklad.py). Не фильтруются по лесничеству — отдаются все
#   сразу, чтобы на карте сразу было видно, где что находится.
# --------------------------------------------------------------------------- #

class SkladCreate(BaseModel):
    nazvanie: str
    lat: float
    lon: float
    comment: Optional[str] = None


@router.get("/sklady")
def get_sklady(conn=Depends(get_conn), _user=Depends(map_reader)):
    return sklad_store.list_sklady(conn)


@router.post("/sklady")
def create_sklad(payload: SkladCreate, conn=Depends(get_conn), _user=Depends(require_permission("delyanka.edit"))):
    if not payload.nazvanie.strip():
        raise HTTPException(400, "Укажите название склада")
    if not (-90 <= payload.lat <= 90 and -180 <= payload.lon <= 180):
        raise HTTPException(400, "Координаты вне допустимого диапазона (широта -90..90, долгота -180..180)")
    return sklad_store.create_sklad(conn, payload.nazvanie, payload.lat, payload.lon, payload.comment)


@router.delete("/sklady/{sklad_id}")
def delete_sklad(sklad_id: int, conn=Depends(get_conn), _user=Depends(require_permission("delyanka.edit"))):
    deleted = sklad_store.delete_sklad(conn, sklad_id)
    if not deleted:
        raise HTTPException(404, "Склад не найден")
    return {"deleted": deleted}


@router.get("/delyanka-location")
def get_delyanka_location(lesnichestvo_num: str, kvartal: str, vydel: str, _user=Depends(map_reader)):
    """Мобильное приложение (Фаза 6): координаты одной делянки для экрана
    "Карта" — центроид её выдела, без стриминга всего слоя лесничества
    (см. докстринг forest_map.get_delyanka_location). Если координаты не
    нашлись (нет geopandas на сервере, нет такого квартала/выдела в
    map_vydela.geojson и т.п.) — не 500-я ошибка, а просто found=false:
    экран приложения должен в этом случае молча спрятать кнопку
    "Маршрут", а не показать пользователю текст ошибки."""
    location = forest_map.get_delyanka_location(lesnichestvo_num, kvartal, vydel)
    if location is None:
        return {"found": False}
    return {"found": True, **location}


def _run_generate_map(task_id: str, lesnichestvo_num: str, created_by: Optional[str]):
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        output_path = task_dir / "forest_map.html"
        path = forest_map.generate_forest_map(
            legacy_config.DB_PATH, lesnichestvo_num, output_path=str(output_path)
        )
        doc_id = register_document(conn, "forest_map", None, path, created_by=created_by)
        webext.set_task_done(conn, task_id, result={"document_ids": [doc_id]})
    except Exception as e:  # noqa: BLE001
        register_document(conn, "forest_map", None, "", created_by=created_by,
                           status="ошибка", error_text=str(e))
        webext.set_task_error(conn, task_id, str(e))
    finally:
        conn.close()


@router.post("/generate")
def generate_map(lesnichestvo_num: str, background_tasks: BackgroundTasks,
                  created_by: Optional[str] = None, conn=Depends(get_conn), _user=Depends(require_permission("map.view"))):
    """Пересчёт HTML-карты (folium/geopandas) — долгая операция на больших
    geojson-файлах, поэтому выполняется в фоне (см. AUDIT.md, п.4
    "Общие замечания")."""
    if lesnichestvo_num not in legacy_config.LCH_MAP.values() and lesnichestvo_num not in legacy_config.LCH_MAP:
        # мягкая проверка — LCH_MAP может быть {имя: номер} или содержать
        # номер напрямую, в зависимости от того, как вы заполнили lch_map.json
        pass
    task_id = webext.create_task(conn, "generate_map")
    background_tasks.add_task(_run_generate_map, task_id, lesnichestvo_num, created_by)
    return {"task_id": task_id}
