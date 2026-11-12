# -*- coding: utf-8 -*-
"""Соседние выдела и кварталы для абриса (11.11.2026, просьба Влада: «чтобы
и соседние выдела, как в QGIS»).

Редактор абриса (frontend/public/abris_tool.html) рисует в метрах UTM 35N
(EPSG:32635) — в той же системе, в которой лежат границы выделов и
кварталов сайта (map_vydela.geojson / map_kvartala.geojson, их присылает
плагин «Лесовод-мост»). Здесь из этих файлов вырезается окно вокруг
лесосеки и отдаётся редактору как есть, в метрах: полигоны выделов с
номерами и кварталы.

Чтение слоя лесничества кэшируется в памяти (forest_map._read_filtered_layer),
поэтому первое открытие абриса в лесничестве — несколько секунд, дальше
мгновенно.
"""
import os

MAX_OKNO_M = 6000   # больше не отдаём: абрис — это одна лесосека, а не лесничество
UTM = 32635
WGS = 4326


class SosediError(Exception):
    """Понятная человеку причина, почему соседей нет."""


def _rings(geom):
    """Полигон/мультиполигон → [[ [x, y], … ], …] (все кольца подряд)."""
    out = []
    for poly in getattr(geom, "geoms", [geom]):
        if poly.is_empty or not hasattr(poly, "exterior"):
            continue
        for ring in [poly.exterior, *poly.interiors]:
            out.append([[round(x, 2), round(y, 2)] for x, y in ring.coords])
    return out


def _norm(v):
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return "" if v is None else str(v).strip()


def okno(lch_num, minx, miny, maxx, maxy):
    """{"vydela": [{kv, vd, rings, cx, cy}], "kvartaly": [{kv, rings, cx, cy}]} в метрах UTM 35N."""
    from app import legacy_bridge  # noqa: F401
    import forest_map
    import geopandas as gpd
    from shapely.geometry import box

    if not lch_num:
        raise SosediError("у делянки не указано лесничество (или его нет в справочнике лесничеств карты)")
    if not (150_000 <= minx <= 900_000 and 5_600_000 <= miny <= 6_400_000):
        raise SosediError("контур не в метрах UTM 35N — соседей подобрать не по чему")
    if maxx - minx > MAX_OKNO_M or maxy - miny > MAX_OKNO_M:
        raise SosediError("слишком большое окно")
    for put, chto in ((forest_map.FOREST_MAP_VYDELA_GEOJSON, "выделов"), (forest_map.FOREST_MAP_KVARTALA_GEOJSON, "кварталов")):
        if not os.path.exists(put):
            raise SosediError(f"на сервере нет границ {chto} — отправьте их из QGIS (Лесовод-мост → «Отправить кварталы и выдела»)")

    ramka = gpd.GeoSeries([box(minx, miny, maxx, maxy)], crs=f"EPSG:{UTM}")
    w = ramka.to_crs(epsg=WGS).total_bounds
    out = {}
    for sloy, put, polya in (("vydela", forest_map.FOREST_MAP_VYDELA_GEOJSON, ("num_kv", "num_vd")),
                             ("kvartaly", forest_map.FOREST_MAP_KVARTALA_GEOJSON, ("num_kv",))):
        gdf = forest_map._read_filtered_layer(put, int(lch_num), UTM, WGS, simplify_tolerance=None)
        obekty = []
        if not gdf.empty:
            gdf = gdf.cx[w[0]:w[2], w[1]:w[3]]
        if not gdf.empty:
            gdf = gdf.to_crs(epsg=UTM)
            ramka_geom = ramka.iloc[0]
            for _, row in gdf.iterrows():
                geom = row.geometry
                if geom is None or geom.is_empty or not geom.intersects(ramka_geom):
                    continue
                tochka = geom.representative_point()
                o = {"kv": _norm(row.get(polya[0])), "rings": _rings(geom),
                     "cx": round(tochka.x, 2), "cy": round(tochka.y, 2), "ga": round(geom.area / 10000.0, 1)}
                if len(polya) > 1:
                    o["vd"] = _norm(row.get(polya[1]))
                obekty.append(o)
        out[sloy] = obekty
    return out
