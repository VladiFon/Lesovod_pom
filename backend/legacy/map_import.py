# -*- coding: utf-8 -*-
"""
Импорт самостоятельного слоя карты из QGIS (GeoJSON/Shapefile) или из
экспорта программы "Лесной страж" — рисуется на Живой карте отдельным,
независимым от делянок слоем и НИЧЕГО не создаёт в таблице delyanka.

Раньше (см. app/routers/delyanki.py, ныне удалено оттуда) тот же самый
файл, загруженный через "Импорт из QGIS", превращался в новые делянки —
по явному решению (см. чат) это оказалось неправильным сценарием: съёмка
из QGIS должна просто ЛЕЧЬ НА КАРТУ как обычный слой (как map_kvartala.
geojson/map_vydela.geojson), а делянки заводятся отдельно, как и раньше
(create_delyanka_manual — тап по карте, или create_delyanka_from_mdo —
импорт МДО).

Хранилище — таблица imported_map_layer (см. db.py:SCHEMA). batch_id
группирует все объекты одной загрузки одного файла, чтобы слой можно
было убрать с карты целиком одним действием (см. delete_import_batch).

Публичные функции:
    parse_uploaded_file(content, suffix) -> [{"geometry":…, "properties":…}]
    create_import_batch(conn, layer_name, lesnichestvo, features) -> dict
    list_import_layer_geojson(conn, lesnichestvo=None) -> FeatureCollection
    list_import_batches(conn, lesnichestvo=None) -> [...]
    delete_import_batch(conn, batch_id) -> int
"""
import json
import struct
from typing import Dict, List, Optional
from uuid import uuid4

# Варианты названий полей в атрибутах слоя, которые пробуем сопоставить с
# нашими полями — только для удобного отображения в списке слоёв/попапе на
# карте (kvartal/vydel/nazvanie отдельными колонками для быстрого поиска).
# Все исходные атрибуты в любом случае сохраняются целиком в
# properties_json — сопоставление ничего не теряет, если ни один вариант
# не найден.
_FIELD_ALIASES = {
    "nazvanie": ["nazvanie", "name", "название", "наименование", "title", "label", "delyanka", "uchastok"],
    "kvartal": ["kvartal", "квартал", "kv", "num_kv"],
    "vydel": ["vydel", "выдел", "vd", "num_vd"],
}


def _find_field(props: dict, keys: List[str]) -> Optional[str]:
    lower_map = {str(k).lower(): k for k in props.keys()}
    for candidate in keys:
        real_key = lower_map.get(candidate.lower())
        if real_key is not None and props[real_key] not in (None, ""):
            return props[real_key]
    return None


def _lesnoy_strazh_srid(geom_hex: Optional[str]) -> Optional[int]:
    """Вытаскивает SRID из HEX-строки EWKB (формат экспорта 'Лесной
    страж'). EWKB = обычный WKB + флаг 0x20000000 в type-слове + 4 байта
    SRID сразу за ним. Возвращает None, если строки нет/не распознана —
    тогда вызывающий код подставляет разумный дефолт (EPSG:32635, UTM
    35N — тот же, что зашит в этом конкретном экспорте)."""
    if not geom_hex:
        return None
    try:
        raw = bytes.fromhex(geom_hex)
        byte_order = raw[0]
        fmt = "<" if byte_order == 1 else ">"
        type_word = struct.unpack(fmt + "I", raw[1:5])[0]
        if type_word & 0x20000000:
            return struct.unpack(fmt + "I", raw[5:9])[0]
    except Exception:  # noqa: BLE001 — geom нужен только для SRID, не критичен
        return None
    return None


def _parse_lesnoy_strazh(data: dict) -> List[dict]:
    """Разбирает экспорт 'Лесной страж' (НЕ GeoJSON — свой JSON с ключами
    area/area_points, координатами точек контура в проекции, не WGS84) в
    список {"geometry": geojson-dict в WGS84, "properties": dict}. Один
    элемент area[] = один полигон. Контур строится по area_points[] с тем
    же area_uid, отсортированным по point_number. Битые лесосеки (меньше
    3 точек контура) молча пропускаются — не роняют весь импорт."""
    import geopandas as gpd
    from shapely.geometry import Polygon

    areas = data.get("area") or []
    if not isinstance(areas, list) or not areas:
        raise ValueError("В файле нет ни одной лесосеки (пустой или отсутствует массив 'area')")

    points_by_uid: Dict[str, List[dict]] = {}
    for p in (data.get("area_points") or []):
        points_by_uid.setdefault(p.get("area_uid"), []).append(p)

    features = []
    for entry in areas:
        uid = entry.get("uid")
        pts = sorted(points_by_uid.get(uid, []), key=lambda p: p.get("point_number", 0))
        if len(pts) < 3:
            continue
        ring = [(float(p["point_x"]), float(p["point_y"])) for p in pts]
        srid = _lesnoy_strazh_srid(entry.get("geom")) or 32635

        poly_src = Polygon(ring)
        if not poly_src.is_valid:
            poly_src = poly_src.buffer(0)
        gseries = gpd.GeoSeries([poly_src], crs=f"EPSG:{srid}")
        geom_wgs84 = gseries.to_crs("EPSG:4326").iloc[0]

        props = dict(entry)
        props.pop("geom", None)  # бинарный EWKB-хекс не нужен в атрибутах слоя
        features.append({"geometry": geom_wgs84.__geo_interface__, "properties": props})
    return features


def parse_uploaded_file(content: bytes, suffix: str) -> List[dict]:
    """Разбирает загруженный файл в список {"geometry":…, "properties":…}
    (геометрия всегда в WGS84/EPSG:4326). Поддерживает два формата — те
    же, что раньше умел /api/delyanki/import-geo:
      1. Экспорт 'Лесной страж' (JSON с ключом 'area') — см.
         _parse_lesnoy_strazh.
      2. GeoJSON/Shapefile — через geopandas.
    Кидает ValueError с понятным текстом при проблеме с самим файлом,
    ImportError — если на сервере не установлен geopandas (роутер сам
    решает, в какой HTTP-статус это завернуть)."""
    if suffix in (".json", ".geojson"):
        try:
            parsed = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("area"), list):
            return _parse_lesnoy_strazh(parsed)

    import geopandas as gpd
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / f"upload{suffix}"
        tmp_path.write_bytes(content)
        gdf = gpd.read_file(tmp_path)

    if gdf.empty:
        raise ValueError("В файле не найдено ни одного объекта (геометрии)")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf_wgs84 = gdf.to_crs("EPSG:4326")

    features = []
    for idx in range(len(gdf_wgs84)):
        geom = gdf_wgs84.geometry.iloc[idx]
        if geom is None or geom.is_empty:
            continue
        props = gdf_wgs84.iloc[idx].drop(labels="geometry").to_dict()
        # NaN/numpy-скаляры не сериализуются в JSON стандартным json.dumps —
        # приводим к обычным Python-типам (та же чистка, что и на слоях
        # кварталов/выделов, см. forest_map._gdf_to_geojson_dict).
        clean_props = {}
        for k, v in props.items():
            if isinstance(v, float) and v != v:  # NaN
                v = None
            elif hasattr(v, "item"):
                v = v.item()
            clean_props[k] = v
        features.append({"geometry": geom.__geo_interface__, "properties": clean_props})
    return features


# --------------------------------------------------------------------------- #
#   Хранение — таблица imported_map_layer, независимая от delyanka
# --------------------------------------------------------------------------- #

def create_import_batch(conn, layer_name: str, lesnichestvo: Optional[str],
                         features: List[dict]) -> dict:
    """Сохраняет весь список фич одной загрузки под общим batch_id — по
    нему слой потом можно убрать с карты целиком одним действием (см.
    delete_import_batch). Возвращает {"batch_id":…, "created": N}."""
    batch_id = uuid4().hex
    created = 0
    for feat in features:
        props = feat.get("properties") or {}
        nazvanie = _find_field(props, _FIELD_ALIASES["nazvanie"])
        kvartal = _find_field(props, _FIELD_ALIASES["kvartal"])
        vydel = _find_field(props, _FIELD_ALIASES["vydel"])
        conn.execute(
            """INSERT INTO imported_map_layer
                   (batch_id, layer_name, lesnichestvo, kvartal, vydel, nazvanie,
                    properties_json, geom_geojson, source_format)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                batch_id, layer_name, lesnichestvo,
                str(kvartal) if kvartal is not None else None,
                str(vydel) if vydel is not None else None,
                str(nazvanie) if nazvanie is not None else None,
                json.dumps(props, ensure_ascii=False),
                json.dumps(feat["geometry"], ensure_ascii=False),
                "geojson",
            ),
        )
        created += 1
    conn.commit()
    return {"batch_id": batch_id, "created": created}


def list_import_layer_geojson(conn, lesnichestvo: Optional[str] = None) -> dict:
    """FeatureCollection всех загруженных слоёв (или только одного
    лесничества) — для отдельного оверлея на Живой карте. Все исходные
    атрибуты фичи доступны в properties.raw (попап на карте показывает их
    как есть, без предположений о том, какие поля важны)."""
    q = """SELECT id, batch_id, layer_name, kvartal, vydel, nazvanie,
                  properties_json, geom_geojson, created_at
           FROM imported_map_layer"""
    params = ()
    if lesnichestvo:
        q += " WHERE lesnichestvo = ?"
        params = (lesnichestvo,)
    rows = conn.execute(q, params).fetchall()
    features = []
    for (item_id, batch_id, layer_name, kvartal, vydel, nazvanie,
         properties_json, geom_geojson, created_at) in rows:
        try:
            geometry = json.loads(geom_geojson)
        except (TypeError, ValueError):
            continue
        try:
            raw_props = json.loads(properties_json) if properties_json else {}
        except (TypeError, ValueError):
            raw_props = {}
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "item_id": item_id,
                "batch_id": batch_id,
                "layer_name": layer_name,
                "kvartal": kvartal,
                "vydel": vydel,
                "nazvanie": nazvanie,
                "created_at": created_at,
                "raw": raw_props,
            },
        })
    return {"type": "FeatureCollection", "features": features}


def list_import_batches(conn, lesnichestvo: Optional[str] = None) -> List[dict]:
    """Список загрузок (для панели управления слоями — показать что уже
    загружено и дать удалить одну загрузку целиком)."""
    q = """SELECT batch_id, layer_name, lesnichestvo, COUNT(*) as n_features,
                  MIN(created_at) as created_at
           FROM imported_map_layer"""
    params = ()
    if lesnichestvo:
        q += " WHERE lesnichestvo = ?"
        params = (lesnichestvo,)
    q += " GROUP BY batch_id ORDER BY created_at DESC"
    rows = conn.execute(q, params).fetchall()
    cols = ["batch_id", "layer_name", "lesnichestvo", "n_features", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def delete_import_batch(conn, batch_id: str) -> int:
    cur = conn.execute("DELETE FROM imported_map_layer WHERE batch_id = ?", (batch_id,))
    conn.commit()
    return cur.rowcount
