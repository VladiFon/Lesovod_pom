# -*- coding: utf-8 -*-
"""
Собственный контур участка лесных культур или лесосеки: файл из QGIS /
GPS — GeoJSON (.geojson/.json), shp в .zip, .kml, .gpkg или JSON «Лесного
стража» — приводится к одному полигону WGS84 (EPSG:4326) и хранится в
geom_geojson (lesokultury_uchastok, delyanka_item). На карте (сайт,
телефон, QGIS) объект тогда рисуется своим контуром, а не всем
таксационным выделом; абрис делянки открывается с этим контуром.

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
    elif suffix not in (".geojson", ".json", ".kml", ".gpkg", ".gpx"):
        raise KonturError("Нужен файл контура: .geojson, .json, .kml, .gpx, .gpkg или shp в .zip")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"kontur{suffix}"
        path.write_bytes(content)
        try:
            if suffix == ".gpx":
                return _read_gpx(gpd, str(path))
            return gpd.read_file(f"zip://{path}" if suffix == ".zip" else str(path))
        except Exception as exc:  # noqa: BLE001
            raise KonturError("Не удалось прочитать файл контура — сохраните его из QGIS как GeoJSON "
                              f"или shp (в .zip). Подробности: {str(exc)[:200]}")


def _read_gpx(gpd, path):
    """GPX навигатора: треки и маршруты (обход границы) — линии; замкнём их
    в полигон ниже (_v_poligony)."""
    import pandas as pd

    chasti = []
    for layer in ("tracks", "routes"):
        try:
            g = gpd.read_file(path, layer=layer)
        except Exception:  # noqa: BLE001 — слоя нет в файле
            continue
        if not g.empty:
            chasti.append(g[["geometry"] + [c for c in ("name", "desc") if c in g.columns]])
    if not chasti:
        raise KonturError("В GPX нет ни трека, ни маршрута — обойдите границу с записью трека")
    return gpd.GeoDataFrame(pd.concat(chasti, ignore_index=True), crs=chasti[0].crs)


def _v_poligony(gdf):
    """Полигоны файла; если их нет — линии (трек GPX, линия KML) с 3+
    точками замыкаем в полигон (обход границы делянки навигатором)."""
    from shapely.geometry import LineString, MultiLineString, Polygon
    from shapely.ops import unary_union

    def conv(g):
        if g is None or g.is_empty:
            return None
        if g.geom_type in ("Polygon", "MultiPolygon"):
            return g
        if isinstance(g, MultiLineString):
            g = LineString([c for part in g.geoms for c in part.coords])
        if isinstance(g, LineString) and len(g.coords) >= 3:
            p = Polygon(list(g.coords))
            return p if p.is_valid else p.buffer(0)
        if g.geom_type == "GeometryCollection":
            polys = [conv(x) for x in g.geoms]
            polys = [x for x in polys if x is not None]
            return unary_union(polys) if polys else None
        return None

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    poly = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if not poly.empty:
        # есть настоящие полигоны — линии (визиры, дороги) не трогаем
        return poly
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.apply(conv)
    return gdf[gdf.geometry.notna()]


def _s_crs(gdf):
    """Система координат: из файла; нет её — по числам (метры = UTM 35N)."""
    minx, miny, maxx, maxy = gdf.total_bounds
    metric = max(abs(minx), abs(maxx)) > 180 or max(abs(miny), abs(maxy)) > 90
    if gdf.crs is None or (metric and gdf.crs.is_geographic):
        gdf = gdf.set_crs(DEFAULT_METRIC_CRS if metric else "EPSG:4326", allow_override=True)
    return gdf


# Как в файлах из QGIS / ГИСлесхоза называют квартал, выдел, лесосеку.
_POLYA = {
    "kvartal": ("num_kv", "kvartal", "kv", "kvart", "квартал", "кв", "quarter"),
    "vydel": ("num_vd", "vydel", "vd", "vyd", "выдел", "выд", "compartmen"),
    "lesoseka_nomer": ("num_les", "lesoseka", "lesoseka_nomer", "nomer", "num", "лесосека", "номер", "number"),
    "nazvanie": ("name", "nazvanie", "название", "descr", "desc"),
}


def _ugadat(props: dict) -> dict:
    low = {str(k).strip().lower(): v for k, v in (props or {}).items()}
    out = {}
    for pole, imena in _POLYA.items():
        for imya in imena:
            v = low.get(imya)
            if v not in (None, "") and str(v).strip() not in ("", "None", "nan"):
                v = str(v).strip()
                if v.endswith(".0") and v[:-2].isdigit():
                    v = v[:-2]
                out[pole] = v
                break
    return out


def razobrat(content: bytes, filename: str, limit: int = 200) -> list:
    """Файл из QGIS / от лесничества -> все контуры по отдельности:
    [{"geometry" WGS84, "ploshad" га, "kvartal", "vydel", "lesoseka_nomer",
    "nazvanie", "svoystva"}] — для «Новая делянка из файла» (лесопункт,
    05.11.2026): человек отмечает нужные и поправляет кв/выд."""
    if not content:
        raise KonturError("Файл пустой")
    if len(content) > MAX_BYTES:
        raise KonturError("Файл больше 20 МБ")
    strazh = _lesnoy_strazh(content, filename)
    if strazh is not None:
        geometry, ha = strazh
        return [{"geometry": geometry, "ploshad": ha, "svoystva": {}}]
    gdf = _read(content, filename)
    gdf = _v_poligony(gdf)
    if gdf.empty:
        raise KonturError("В файле нет контуров — нужны замкнутые полигоны или трек обхода границы")
    gdf = _s_crs(gdf)
    metric = gdf.to_crs(DEFAULT_METRIC_CRS)
    wgs = gdf.to_crs("EPSG:4326")
    out = []
    for i in range(min(len(wgs), limit)):
        geom = wgs.geometry.iloc[i]
        if not geom.is_valid:
            geom = geom.buffer(0)
        props = {}
        for k, v in wgs.iloc[i].drop(labels="geometry").to_dict().items():
            if isinstance(v, float) and v != v:
                v = None
            elif hasattr(v, "item"):
                v = v.item()
            props[str(k)] = v if isinstance(v, (int, float, str, bool)) or v is None else str(v)
        try:
            g = _checked(geom)
        except KonturError:
            continue
        out.append({"geometry": g, "ploshad": round(float(metric.geometry.iloc[i].area) / 10000.0, 2),
                    "svoystva": props, **_ugadat(props)})
    if not out:
        raise KonturError("Контуры оказались не в Беларуси — проверьте систему координат файла (нужна WGS84 или UTM 35N)")
    return out


def parse(content: bytes, filename: str) -> Tuple[dict, float]:
    """-> (geometry GeoJSON в WGS84, площадь, га)."""
    if not content:
        raise KonturError("Файл пустой")
    if len(content) > MAX_BYTES:
        raise KonturError("Файл больше 20 МБ — нужен только контур участка")
    strazh = _lesnoy_strazh(content, filename)
    if strazh is not None:
        return strazh
    gdf = _read(content, filename)
    gdf = _v_poligony(gdf)
    if gdf.empty:
        raise KonturError("В файле нет полигонов — нужен замкнутый контур участка")
    # Без системы координат (GeoJSON тогда читается как WGS84) — по числам:
    # больше 180/90 — это метры, UTM 35N.
    minx, miny, maxx, maxy = gdf.total_bounds
    metric = max(abs(minx), abs(maxx)) > 180 or max(abs(miny), abs(maxy)) > 90
    if gdf.crs is None or (metric and gdf.crs.is_geographic):
        gdf = gdf.set_crs(DEFAULT_METRIC_CRS if metric else "EPSG:4326", allow_override=True)
    metric_gdf = gdf.to_crs(DEFAULT_METRIC_CRS)
    ha = float(metric_gdf.geometry.union_all().area) / 10000.0
    geom = gdf.to_crs("EPSG:4326").geometry.union_all()
    if not geom.is_valid:
        geom = geom.buffer(0)
    return _checked(geom), round(ha, 2)


def _checked(geom) -> dict:
    minx, miny, maxx, maxy = geom.bounds
    if not (20 <= minx <= 40 and 45 <= miny <= 60):
        raise KonturError("Контур оказался не в Беларуси — проверьте систему координат файла (нужна WGS84 или UTM 35N)")
    from shapely.geometry import mapping

    return json.loads(json.dumps(mapping(geom)))


def _lesnoy_strazh(content: bytes, filename: str):
    """JSON «Лесного стража» / абриса (area + area_points в UTM) -> как parse()."""
    if Path((filename or "").lower()).suffix not in (".json", ".geojson", ""):
        return None
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not (isinstance(data, dict) and isinstance(data.get("area"), list)):
        return None
    import map_import  # legacy, путь добавляет app.legacy_bridge
    from shapely.geometry import shape
    from shapely.ops import unary_union

    try:
        features = map_import._parse_lesnoy_strazh(data)
    except ValueError as exc:
        raise KonturError(str(exc))
    if not features:
        raise KonturError("В файле нет контура — у лесосеки меньше трёх точек")
    geom = unary_union([shape(f["geometry"]) for f in features])
    if not geom.is_valid:
        geom = geom.buffer(0)
    return _checked(geom), area_ha(json.loads(json.dumps(geom.__geo_interface__)))


def area_ha(geometry: dict) -> float:
    """Площадь контура WGS84, га (считается в UTM 35N)."""
    import geopandas as gpd
    from shapely.geometry import shape

    area = gpd.GeoSeries([shape(geometry)], crs="EPSG:4326").to_crs(DEFAULT_METRIC_CRS).area.iloc[0]
    return round(float(area) / 10000.0, 2)


def to_abris(geometry: dict, meta: dict) -> dict:
    """Контур WGS84 -> данные для абриса (формат «Лесного стража»:
    area/area_data/area_points, точки в метрах UTM 35N). Берётся внешнее
    кольцо самого большого полигона; привязка — первая точка."""
    import geopandas as gpd
    from shapely.geometry import shape

    geom = gpd.GeoSeries([shape(geometry)], crs="EPSG:4326").to_crs(DEFAULT_METRIC_CRS).iloc[0]
    poly = max(getattr(geom, "geoms", [geom]), key=lambda g: g.area)
    coords = list(poly.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    uid = f"lesovod-{meta.get('item_id', '')}"
    area = {"uid": uid, "area": round(poly.area / 10000.0, 2)}
    area.update({k: v for k, v in meta.items() if v not in (None, "")})
    return {
        "area": [area],
        "area_data": [{"area_uid": uid, "table_type": 0, "coord_type": 0,
                       "binding_point_x": str(coords[0][0]), "binding_point_y": str(coords[0][1]),
                       "magnetic_inclination": 0.0}],
        "area_points": [{"area_uid": uid, "point_number": i, "point_x": str(x), "point_y": str(y),
                         "point_type": "Лесосека"} for i, (x, y) in enumerate(coords)],
    }
