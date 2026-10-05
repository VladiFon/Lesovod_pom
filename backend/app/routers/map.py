# -*- coding: utf-8 -*-
"""Роутер "Живая карта" (screens/live_map/) — оборачивает forest_map.py без
изменения его внутренней логики (Этап 2 доработки лишь ДОБАВИЛ в
forest_map.py bbox-стриминг, не тронув generate_forest_map()/
get_sanitary_vydely()). Требует geopandas в окружении backend'а (см.
AUDIT.md/requirements.txt) и файлы map_kvartala.geojson/map_vydela.geojson
в RESOURCE_DIR (legacy/config.py); folium нужен только для /generate
(HTML-экспорт), сама живая карта на нём больше не основана."""
import json
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
from app import map_features, vidy
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
    lesn = _lesnichestvo_name(lesnichestvo_num)
    result = map_import.list_import_layer_geojson(conn, lesnichestvo=lesn)
    for f in result["features"]:
        # лесосеки из ГИСлесхоза (плагин «Лесовод-мост») несут вид рубки и вид
        # пользования в cuttingtyp / usetype — тот же цвет, что у делянок
        raw = {str(k).lower(): v for k, v in (f["properties"].get("raw") or {}).items()}
        if raw.get("cuttingtyp") or raw.get("usetype"):
            info = vidy.vid_rubki_info(None, None, raw.get("cuttingtyp"), raw.get("usetype"))
            f["properties"].update({k: info[k] for k in _VID_RUBKI_KEYS})
    result["features"].extend(_own_lesoseki(conn, lesn, result["features"]))
    return result


_VID_RUBKI_KEYS = ("vid_rubki_kod", "vid_rubki", "vid_rubki_color", "gruppa", "gruppa_label", "gruppa_color")


def _own_lesoseki(conn, lesnichestvo: Optional[str], existing: list) -> list:
    """Собственные контуры лесосек из карточек делянок (delyanka_item.geom_geojson)
    — как слой «лесосеки_делянки», чтобы телефон рисовал их вместо примерного
    прямоугольника. Лесосеки, уже присланные из QGIS тем же кв/выд, не дублируем."""
    import delyanka as delyanka_store

    have = {(map_features.norm_id(f["properties"].get("kvartal")), map_features.norm_id(f["properties"].get("vydel")))
            for f in existing if "лесосек" in str(f["properties"].get("layer_name") or "").lower()}
    features = []
    for row in delyanka_store.list_delyanka_geometries(conn, lesnichestvo=lesnichestvo):
        kv = map_features.norm_id(row["kvartal"])
        vd = map_features.norm_id(str(row["vydel"] or "").replace(";", ",").split(",")[0])
        if (kv, vd) in have:
            continue
        try:
            geometry = json.loads(row["geom_geojson"])
        except (TypeError, ValueError):
            continue
        features.append({"type": "Feature", "geometry": geometry, "properties": {
            "item_id": None, "batch_id": None, "layer_name": "лесосеки_делянки",
            "kvartal": kv, "vydel": vd, "nazvanie": row["nazvanie"],
            "delyanka_id": row["delyanka_id"], "status_rabot": row["status_rabot"], "raw": {},
            **{k: row[k] for k in _VID_RUBKI_KEYS},
        }})
    return features


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


@router.get("/legendy")
def get_legendy(_user=Depends(get_current_user)):
    """Справочники видов рубок, видов пользования и видов культур с цветами."""
    return vidy.legendy()


@router.get("/qgis/legendy.json")
def get_legendy_for_qgis(token: str):
    """То же для плагина QGIS (токен сервиса)."""
    _check_service_token(token)
    return vidy.legendy()


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


@router.get("/lesokultury/{uchastok_id}/kartochka")
def get_lesokultury_kartochka(uchastok_id: int, conn=Depends(get_conn), _user=Depends(get_current_user)):
    """Карточка участка лесных культур по тапу на карте телефона (05.10.2026):
    то же, что «Что здесь» в QGIS — способ создания, схема, густота, ТЛУ,
    последнее мероприятие — плюс журнал мероприятий."""
    cols = [d[0] for d in conn.execute("SELECT * FROM lesokultury_uchastok LIMIT 0").description]
    row = conn.execute("SELECT * FROM lesokultury_uchastok WHERE id = ?", (uchastok_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Участок лесных культур не найден")
    u = dict(zip(cols, row))
    base = {k: u.get(k) for k in ("id", "lesnichestvo", "kvartal", "vydel", "ploshad", "god_sozdaniya",
                                   "glavnaya_poroda", "sostav_formula", "status")}
    base["has_kontur"] = bool(u.get("geom_geojson"))
    base.update(vidy.vid_kultur_info(u.get("vid_kultur"), u.get("naznachenie_plantatsii"),
                                     u.get("metod_sozdaniya"), u.get("primechaniya")))
    podrobno = _lesokultury_podrobno(conn).get(uchastok_id, {})
    zhurnal = [
        {"tip": tip, "data": data, "prizhivaemost_pct": prizh, "kolichestvo_na_ga": kol}
        for tip, data, prizh, kol in conn.execute(
            "SELECT tip, data, prizhivaemost_pct, kolichestvo_na_ga FROM lesokultury_meropriyatiya "
            "WHERE uchastok_id = ? ORDER BY data DESC, id DESC LIMIT 10", (uchastok_id,)
        ).fetchall()
    ]
    out = {**podrobno, **{k: v for k, v in base.items() if v not in (None, "")}}
    # телефон ждёт числа в этих полях и строки во всех остальных
    chisla = {"id", "ploshad", "prizhivaemost_pct", "kolichestvo_na_ga", "has_kontur", "vid_kultur_avto"}
    for k, v in list(out.items()):
        if k in chisla - {"id", "has_kontur", "vid_kultur_avto"}:
            try:
                out[k] = float(str(v).replace(",", "."))
            except (TypeError, ValueError):
                out.pop(k)
        elif k not in chisla:
            out[k] = str(v)
    for z in zhurnal:
        z["tip"], z["data"] = (str(z["tip"]) if z["tip"] is not None else None,
                               str(z["data"]) if z["data"] is not None else None)
    return {**out, "zhurnal": zhurnal}


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
    """Делянки со статусом работ для QGIS: свой контур лесосеки, если есть, иначе полигоны выделов."""
    _check_service_token(token)
    colors = {s["status"]: s["color"] for s in map_features.DELYANKA_STATUSES}
    wanted: dict = {}
    own = []
    for (item_id, d_id, nazvanie, kv, vd, lesn, status_rabot, ploshad, geom,
         vid_rubki_kod, mdo_raw_json, meropriyatiya, namechaemoe) in conn.execute(
        """SELECT i.id, d.id, d.nazvanie, i.kvartal, i.vydel, i.lesnichestvo, i.status_rabot, i.ploshad,
                  i.geom_geojson, i.vid_rubki_kod, i.mdo_raw_json, d.meropriyatiya, d.listok_namechaemoe_meropriyatie
           FROM delyanka_item i JOIN delyanka d ON d.id = i.delyanka_id"""
    ).fetchall():
        num = _num_for_lesnichestvo(lesn)
        if num is None or (lesnichestvo_num and num != str(lesnichestvo_num)):
            continue
        status = status_rabot or map_features.STATUS_WAITING
        props = {
            "item_id": item_id, "delyanka_id": d_id, "nazvanie": nazvanie,
            "kvartal": map_features.norm_id(kv), "vydel": map_features.norm_id(vd),
            "lesnichestvo": lesn, "status_rabot": status, "color": colors.get(status, "#9e9e9e"),
            "ploshad": ploshad,
            **vidy.vid_rubki_info(vid_rubki_kod, mdo_raw_json, meropriyatiya, namechaemoe),
        }
        if geom:
            try:
                own.append({"type": "Feature", "geometry": json.loads(geom), "properties": props})
                continue
            except (TypeError, ValueError):
                pass
        wanted.setdefault((num, props["kvartal"], props["vydel"]), []).append(props)
    result = _vydel_polygons(lesnichestvo_num, wanted) if wanted else {"type": "FeatureCollection", "features": []}
    result["features"].extend(own)
    return result


@router.get("/qgis/lesokultury.geojson")
def get_lesokultury_geojson_for_qgis(token: str, lesnichestvo_num: Optional[str] = None, conn=Depends(get_conn)):
    """Участки лесных культур для QGIS: свой контур участка, если загружен,
    иначе полигоны выделов."""
    _check_service_token(token)
    wanted: dict = {}
    own = []
    for u in map_features.lesokultury_for_map(conn, lesnichestvo_num):
        num = _num_for_lesnichestvo(u["lesnichestvo"])
        if num is None or (lesnichestvo_num and num != str(lesnichestvo_num)):
            continue
        if u.get("has_kontur"):
            geometry = u.pop("geometry", None)
            if geometry is not None:
                own.append({"type": "Feature", "geometry": geometry, "properties": u})
            continue
        wanted.setdefault((num, u["kvartal"], u["vydel"]), []).append(u)
    result = _vydel_polygons(lesnichestvo_num, wanted) if wanted else {"type": "FeatureCollection", "features": []}
    result["features"].extend(own)
    podrobno = _lesokultury_podrobno(conn)
    for f in result["features"]:
        f["properties"] = {**podrobno.get(f["properties"].get("id"), {}), **f["properties"]}
    return result


def _lesokultury_podrobno(conn) -> dict:
    """Характеристики участка для карточки в QGIS (плагин «Лесовод-мост»,
    кнопка «Что здесь»): способ создания, схема, густота, ТЛУ и последнее
    мероприятие из журнала (инвентаризация с приживаемостью и т.п.)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(lesokultury_uchastok)").fetchall()}
    want = [c for c in ("metod_sozdaniya", "sposob_obrabotki", "posadochnyy_material", "shema_mezhdu_ryadami",
                        "shema_v_ryadu", "gustota_posadki", "normativ_perevoda", "tlu", "kategoriya_ploshadi",
                        "vydel_staryy", "podvydel", "primechaniya") if c in cols]
    out: dict = {}
    for row in conn.execute(f"SELECT id, {', '.join(want) or 'NULL'} FROM lesokultury_uchastok").fetchall():
        d = dict(zip(want, row[1:]))
        mr, vr = d.pop("shema_mezhdu_ryadami", None), d.pop("shema_v_ryadu", None)
        if mr or vr:
            d["shema_posadki"] = f"{mr or '?'} × {vr or '?'} м"
        out[row[0]] = {k: v for k, v in d.items() if v not in (None, "")}
    for u_id, tip, data, prizh, kol, sostav in conn.execute(
        """SELECT m.uchastok_id, m.tip, m.data, m.prizhivaemost_pct, m.kolichestvo_na_ga, m.sostav_fakt
           FROM lesokultury_meropriyatiya m
           WHERE m.id = (SELECT m2.id FROM lesokultury_meropriyatiya m2 WHERE m2.uchastok_id = m.uchastok_id
                         ORDER BY m2.data DESC, m2.id DESC LIMIT 1)"""
    ).fetchall():
        d = out.setdefault(u_id, {})
        d["posl_meropriyatie"] = " ".join(str(x) for x in (tip, data) if x)
        if prizh is not None:
            d["prizhivaemost_pct"] = prizh
        if kol is not None:
            d["kolichestvo_na_ga"] = kol
        if sostav:
            d["sostav_fakt"] = sostav
    return out


class LesokulturyIzQgis(BaseModel):
    """Участок лесных культур, отмеченный в QGIS (плагин «Лесовод-мост»):
    контур в WGS84 и то, что ввели в окне плагина."""

    geometry: dict
    lesnichestvo_num: Optional[str] = None
    kvartal: str
    vydel: str = ""
    vid_kultur: Optional[str] = None
    god_sozdaniya: Optional[str] = None
    glavnaya_poroda: Optional[str] = None
    ploshad: Optional[float] = None
    primechaniya: Optional[str] = None


def _naiti_lesokultury(conn, lesnichestvo, kvartal, vydel, god, area):
    """Существующий участок культур на том же месте: квартал, общий выдел и
    тот же год создания (если год указан). Из нескольких — без контура и
    ближайший по площади."""
    from app.lesokultury_kniga import vydel_tokens
    from app.tekushchie_izmeneniya import _lesn_match, _norm, _year_of

    tokens = set(vydel_tokens(str(vydel or "")))
    kv = map_features.norm_id(kvartal)
    god_n = _year_of(god)
    if not tokens or not kv:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM lesokultury_uchastok LIMIT 0").description]
    found = []
    for r in conn.execute("SELECT * FROM lesokultury_uchastok WHERE kvartal = ?", (kv,)).fetchall():
        u = dict(zip(cols, r))
        if lesnichestvo and not _lesn_match(_norm(lesnichestvo), u.get("lesnichestvo")):
            continue
        if god_n and _year_of(u.get("god_sozdaniya")) != god_n:
            continue
        if tokens & set(vydel_tokens(str(u.get("vydel") or ""))):
            found.append(u)
    if not found:
        return None
    return min(found, key=lambda u: (bool(u.get("geom_geojson")), abs((u.get("ploshad") or 0) - (area or 0))))


@router.post("/qgis/lesokultury")
def create_lesokultury_from_qgis(body: LesokulturyIzQgis, token: str, conn=Depends(get_conn)):
    """Создаёт участок лесных культур со своим контуром — в ГИСлесхозе такого
    признака нет, поэтому л/к отмечают в QGIS, а хранятся они в «Лесоводе»."""
    _check_service_token(token)
    from shapely.geometry import shape

    import db as legacy_db
    from app import kontur as kontur_mod

    try:
        geom = shape(body.geometry)
        if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError
        geometry = kontur_mod._checked(geom)
    except kontur_mod.KonturError as exc:
        raise HTTPException(400, str(exc))
    except Exception:  # noqa: BLE001 — не GeoJSON-полигон
        raise HTTPException(400, "Нужен полигон GeoJSON в WGS84")
    try:
        vid = vidy.proverit_vid_kultur(body.vid_kultur)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    area = kontur_mod.area_ha(geometry)
    lesnichestvo = _lesnichestvo_name(body.lesnichestvo_num) if body.lesnichestvo_num else None
    # Участок на этом месте уже есть (из книги л/к или заведён на сайте) —
    # не заводим второй (он задвоит строки ведомостей), а даём ему контур.
    est = _naiti_lesokultury(conn, lesnichestvo, body.kvartal, body.vydel, body.god_sozdaniya, area)
    if est is not None:
        dop = {k: v for k, v in (("vid_kultur", vid), ("glavnaya_poroda", (body.glavnaya_poroda or "").strip()))
               if v and not str(est.get(k) or "").strip()}
        dop["geom_geojson"] = json.dumps(geometry, ensure_ascii=False)
        conn.execute(f"UPDATE lesokultury_uchastok SET {', '.join(f'{k} = ?' for k in dop)} WHERE id = ?",
                     (*dop.values(), est["id"]))
        conn.commit()
        return {"id": est["id"], "ploshad_kontura": area, "lesnichestvo": est.get("lesnichestvo") or lesnichestvo,
                "obnovlen": True}
    uchastok_id = legacy_db.create_lesokultury_uchastok(
        conn, lesnichestvo=lesnichestvo, kvartal=map_features.norm_id(body.kvartal),
        vydel=(body.vydel or "").strip(), ploshad=body.ploshad or area, vid_kultur=vid,
        god_sozdaniya=(body.god_sozdaniya or "").strip() or None,
        glavnaya_poroda=(body.glavnaya_poroda or "").strip() or None,
        primechaniya=(body.primechaniya or "").strip() or "Отмечено в QGIS",
    )
    conn.execute("UPDATE lesokultury_uchastok SET geom_geojson = ? WHERE id = ?",
                 (json.dumps(geometry, ensure_ascii=False), uchastok_id))
    conn.commit()
    return {"id": uchastok_id, "ploshad_kontura": area, "lesnichestvo": lesnichestvo}


# --------------------------------------------------------------------------- #
#   Делянка из QGIS (05.10.2026): как «Отметить как лесные культуры», только
#   выделенный полигон (лесосека ГИСлесхоза, выдел, свой контур) становится
#   контуром лесосеки делянки — уже заведённой на этом выделе или новой.
# --------------------------------------------------------------------------- #
def _delyanki_na_vydele(conn, lesnichestvo: Optional[str], kvartal: str, vydel: str) -> list:
    kv, vd = map_features.norm_id(kvartal), map_features.norm_id(vydel)
    out = []
    for (item_id, d_id, nazvanie, d_status, i_lesn, i_kv, i_vd, status_rabot, ploshad, geom,
         nomer, vid_kod) in conn.execute(
        """SELECT i.id, d.id, d.nazvanie, d.status, i.lesnichestvo, i.kvartal, i.vydel, i.status_rabot,
                  i.ploshad, i.geom_geojson, i.lesoseka_nomer, i.vid_rubki_kod
           FROM delyanka_item i JOIN delyanka d ON d.id = i.delyanka_id ORDER BY d.id DESC"""
    ).fetchall():
        if map_features.norm_id(i_kv) != kv or (vd and map_features.norm_id(i_vd) != vd):
            continue
        if lesnichestvo and i_lesn and not map_features.same_lesnichestvo(i_lesn, lesnichestvo):
            continue
        out.append({"item_id": item_id, "delyanka_id": d_id, "nazvanie": nazvanie, "status": d_status,
                    "arhiv": d_status == "архив", "status_rabot": status_rabot or map_features.STATUS_WAITING,
                    "kvartal": map_features.norm_id(i_kv), "vydel": map_features.norm_id(i_vd),
                    "ploshad": ploshad, "has_kontur": bool(geom), "lesoseka_nomer": nomer,
                    "vid_rubki_kod": vid_kod})
    # сначала рабочие, архивные — в конце
    return sorted(out, key=lambda r: r["arhiv"])


@router.get("/qgis/delyanki-na-vydele")
def get_delyanki_na_vydele_for_qgis(token: str, kvartal: str, vydel: str = "",
                                    lesnichestvo_num: Optional[str] = None, conn=Depends(get_conn)):
    """Делянки, уже заведённые на этом квартале/выделе — плагин предлагает
    привязать контур к одной из них или завести новую."""
    _check_service_token(token)
    lesnichestvo = _lesnichestvo_name(lesnichestvo_num) if lesnichestvo_num else None
    return _delyanki_na_vydele(conn, lesnichestvo, kvartal, vydel)


class DelyankaIzQgis(BaseModel):
    """Контур лесосеки из QGIS. item_id — привязать к этому выделу делянки;
    delyanka_id без item_id — добавить выдел в эту делянку (несколько
    полигонов одной делянкой); ни того ни другого — новая делянка."""

    geometry: dict
    lesnichestvo_num: Optional[str] = None
    kvartal: str
    vydel: str = ""
    item_id: Optional[int] = None
    delyanka_id: Optional[int] = None
    nazvanie: Optional[str] = None
    vid_rubki_kod: Optional[str] = None
    lesoseka_nomer: Optional[str] = None


def _qgis_polygon(geometry_in: dict) -> dict:
    from shapely.geometry import shape

    from app import kontur as kontur_mod

    try:
        geom = shape(geometry_in)
        if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError
        return kontur_mod._checked(geom)
    except kontur_mod.KonturError as exc:
        raise HTTPException(400, str(exc))
    except Exception:  # noqa: BLE001 — не GeoJSON-полигон
        raise HTTPException(400, "Нужен полигон GeoJSON в WGS84")


@router.post("/qgis/delyanka")
def create_delyanka_from_qgis(body: DelyankaIzQgis, token: str, conn=Depends(get_conn)):
    """Привязывает выделенный в QGIS полигон к делянке как её контур
    лесосеки (как загрузка «Контур лесосеки» на сайте) или заводит новую
    делянку с этим контуром (таксация выдела подтягивается сама, площадь —
    по контуру)."""
    _check_service_token(token)
    import delyanka as delyanka_store

    from app import kontur as kontur_mod

    geometry = _qgis_polygon(body.geometry)
    try:
        vid = vidy.proverit_vid_rubki(body.vid_rubki_kod)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    area = kontur_mod.area_ha(geometry)
    lesnichestvo = _lesnichestvo_name(body.lesnichestvo_num) if body.lesnichestvo_num else None
    kv, vd = map_features.norm_id(body.kvartal), map_features.norm_id(body.vydel)
    nomer = (body.lesoseka_nomer or "").strip() or None
    geom_json = json.dumps(geometry, ensure_ascii=False)

    if body.item_id is not None:
        row = conn.execute(
            """SELECT i.delyanka_id, d.nazvanie, i.ploshad, i.vid_rubki_kod, i.lesoseka_nomer, i.lesnichestvo
               FROM delyanka_item i JOIN delyanka d ON d.id = i.delyanka_id WHERE i.id = ?""",
            (body.item_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Выдел делянки не найден — обновите список в окне плагина")
        delyanka_id, nazvanie, ploshad, old_vid, old_nomer, i_lesn = row
        dop = {"geom_geojson": geom_json}
        if vid and not (old_vid or "").strip():
            dop["vid_rubki_kod"] = vid
        if nomer and not (old_nomer or "").strip():
            dop["lesoseka_nomer"] = nomer
        conn.execute(f"UPDATE delyanka_item SET {', '.join(f'{k} = ?' for k in dop)} WHERE id = ?",
                     (*dop.values(), body.item_id))
        conn.commit()
        warning = None
        try:
            own = float(str(ploshad).replace(",", "."))
        except (TypeError, ValueError):
            own = None
        if own and abs(own - area) > max(0.1, own * 0.1):
            warning = f"площадь контура {area} га, у лесосеки записано {own} га"
        return {"item_id": body.item_id, "delyanka_id": delyanka_id, "nazvanie": nazvanie,
                "ploshad_kontura": area, "warning": warning, "novaya": False}

    if not kv:
        raise HTTPException(400, "Нужен номер квартала")
    if body.delyanka_id is not None:
        d = conn.execute("SELECT nazvanie FROM delyanka WHERE id = ?", (body.delyanka_id,)).fetchone()
        if d is None:
            raise HTTPException(404, "Делянка не найдена")
        delyanka_id, nazvanie = body.delyanka_id, d[0]
        tax = delyanka_store._lookup_taxatsia(conn, kv, vd, lesnichestvo_hint=lesnichestvo) or {}
        poryadok = conn.execute("SELECT COALESCE(MAX(poryadok), 0) + 1 FROM delyanka_item WHERE delyanka_id = ?",
                                (delyanka_id,)).fetchone()[0]
        item_id = conn.execute(
            """INSERT INTO delyanka_item
                   (delyanka_id, poryadok, lesnichestvo, kvartal, vydel, sostav, vozrast, polnota, tip_lesa,
                    bonitet, proishozhdenie, kategoriya_lesov, zapas_na_ga)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (delyanka_id, poryadok, lesnichestvo or tax.get("lesnichestvo") or "", kv, vd, tax.get("sostav"),
             tax.get("vozrast"), tax.get("polnota"), tax.get("tip_lesa"), tax.get("bonitet"),
             tax.get("proishozhdenie"), tax.get("kategoriya_lesov"), tax.get("zapas_na_ga")),
        ).lastrowid
    else:
        nazvanie = (body.nazvanie or "").strip() or f"кв. {kv} выд. {vd or '—'} (QGIS)"
        delyanka_id = delyanka_store.create_delyanka_manual(conn, nazvanie, kv, vd, lesnichestvo)
        item_id = conn.execute("SELECT id FROM delyanka_item WHERE delyanka_id = ? ORDER BY id LIMIT 1",
                               (delyanka_id,)).fetchone()[0]
    # площадь лесосеки — по контуру, а не всего таксационного выдела
    conn.execute("UPDATE delyanka_item SET geom_geojson = ?, ploshad = ?, vid_rubki_kod = ?, lesoseka_nomer = ? "
                 "WHERE id = ?", (geom_json, str(area), vid, nomer, item_id))
    conn.commit()
    return {"item_id": item_id, "delyanka_id": delyanka_id, "nazvanie": nazvanie, "ploshad_kontura": area,
            "warning": None, "novaya": True}


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
