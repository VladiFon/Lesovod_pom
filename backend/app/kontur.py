# -*- coding: utf-8 -*-
"""
Контур (схема-чертёж) участка лесных культур: файл из QGIS / GPS —
GeoJSON (.geojson/.json), shp в .zip или .kml — приводится к одному
полигону WGS84 (EPSG:4326) и хранится в lesokultury_uchastok.geom_geojson.
На карте (телефон, QGIS) участок тогда рисуется своим контуром, а не
всем таксационным выделом.

Система координат берётся из файла; если её нет — по числам: градусы
считаются WGS84, метры — UTM 35N (EPSG:32635, как в таксации РБ).
"""
import io
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Tuple


class KonturError(Exception):
    """Ошибка, понятная человеку (показывается на сайте как есть)."""


DEFAULT_METRIC_CRS = "EPSG:32635"
MAX_BYTES = 20 * 1024 * 1024


def _read(content: bytes, filename: str):
    import geopandas as gpd

    name = (filename or "").lower()
    suffix = Path(name).suffix or ".geojson"
    if suffix == ".zip":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if not any(n.lower().endswith(".shp") for n in z.namelist()):
                raise KonturError("В архиве нет .shp — нужен shp вместе с .shx/.dbf/.prj")
    elif suffix not in (".geojson", ".json", ".kml", ".gpkg"):
        raise KonturError("Нужен файл контура: .geojson, .json, .kml, .gpkg или shp в .zip")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"kontur{suffix}"
        path.write_bytes(content)
        try:
            return gpd.read_file(f"zip://{path}" if suffix == ".zip" else str(path))
        except Exception as exc:  # noqa: BLE001
            raise KonturError("Не удалось прочитать файл контура — сохраните его из QGIS как GeoJSON "
                              f"или shp (в .zip). Подробности: {str(exc)[:200]}")


def parse(content: bytes, filename: str) -> Tuple[dict, float]:
    """-> (geometry GeoJSON в WGS84, площадь, га)."""
    if not content:
        raise KonturError("Файл пустой")
    if len(content) > MAX_BYTES:
        raise KonturError("Файл больше 20 МБ — нужен только контур участка")
    gdf = _read(content, filename)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if gdf.empty:
        raise KonturError("В файле нет полигонов — нужен замкнутый контур участка")
    # Без системы координат (GeoJSON тогда читается как WGS84) — по числам:
    # больше 180/90 — это метры, UTM 35N.
    minx, miny, maxx, maxy = gdf.total_bounds
    metric = max(abs(minx), abs(maxx)) > 180 or max(abs(miny), abs(maxy)) > 90
    if gdf.crs is None or (metric and gdf.crs.is_geographic):
        gdf = gdf.set_crs(DEFAULT_METRIC_CRS if metric else "EPSG:4326", allow_override=True)
    metric_gdf = gdf.to_crs(DEFAULT_METRIC_CRS)
    area_ha = float(metric_gdf.geometry.union_all().area) / 10000.0
    geom = gdf.to_crs("EPSG:4326").geometry.union_all()
    if not geom.is_valid:
        geom = geom.buffer(0)
    minx, miny, maxx, maxy = geom.bounds
    if not (20 <= minx <= 40 and 45 <= miny <= 60):
        raise KonturError("Контур оказался не в Беларуси — проверьте систему координат файла (нужна WGS84 или UTM 35N)")
    from shapely.geometry import mapping

    return json.loads(json.dumps(mapping(geom))), round(area_ha, 2)
