# -*- coding: utf-8 -*-
"""Фотолента делянки (разбор сайта 09.11.2026, шаг 6).

Фото, которые рабочие присылали с делянки, лежали в трёх местах: отчёты с
телефона/бота (raw_reports), выполненные работы (completed_works) и метки
на карте (geo_notes). Здесь — одной лентой, новые сверху: по кварталу и
выделу делянки, а метки — если точка внутри своего контура лесосеки.
"""
import json
import urllib.parse


def _norm(v):
    s = str(v or "").strip().lower()
    return s.lstrip("0") or s


def _vydely(text):
    return {_norm(x.split(".")[0]) for x in str(text or "").replace(";", ",").replace(" ", ",").split(",") if x.strip()}


def _v_poligone(lon, lat, geom):
    """Точка в полигоне/мультиполигоне GeoJSON (лучом, без библиотек)."""
    try:
        g = json.loads(geom) if isinstance(geom, str) else geom
    except (TypeError, ValueError):
        return False
    polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates", []) if g.get("type") == "MultiPolygon" else []
    for poly in polys:
        ring = poly[0] if poly else []
        inside = False
        for i in range(len(ring)):
            x1, y1 = ring[i][:2]
            x2, y2 = ring[i - 1][:2]
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-12) + x1:
                inside = not inside
        if inside:
            return True
    return False


def foto_delyanki(conn, delyanka_id, limit=60):
    items = conn.execute(
        "SELECT kvartal, vydel, geom_geojson FROM delyanka_item WHERE delyanka_id=?", (delyanka_id,)).fetchall()
    mesta = {(_norm(kv), _norm(vd)) for kv, vd, _g in items}
    kontury = [g for _kv, _vd, g in items if g]
    out = []

    def na_delyanke(kv, vydely):
        return any((_norm(kv), v) in mesta for v in vydely)

    try:
        for rid, kv, vd, data, fio, tip, opis, path in conn.execute(
            "SELECT id, kvartal, vydel, data_vypolneniya, ispolnitel_fio, tip_raboty, opisanie, photo_path "
            "FROM completed_works WHERE photo_path IS NOT NULL AND photo_path <> ''"
        ).fetchall():
            if na_delyanke(kv, _vydely(vd)):
                out.append({"kogda": data or "", "kto": fio or "", "chto": tip or "", "podpis": opis or "",
                            "otkuda": "работа", "path": f"/map/completed-work/{rid}/photo"})
    except Exception:  # noqa: BLE001 — старая база без таблицы
        pass
    try:
        for kv, vds, data, fio, tip, text, path in conn.execute(
            "SELECT kvartal, vydels, data_soobscheniya, ispolnitel_fio, tip_raboty, raw_text, photo_path "
            "FROM raw_reports WHERE photo_path IS NOT NULL AND photo_path <> ''"
        ).fetchall():
            if na_delyanke(kv, _vydely(vds)):
                out.append({"kogda": data or "", "kto": fio or "", "chto": tip or "отчёт", "podpis": (text or "")[:140],
                            "otkuda": "отчёт", "path": "/ai-log/photo?path=" + urllib.parse.quote(path)})
    except Exception:  # noqa: BLE001
        pass
    if kontury:
        try:
            for nid, lat, lon, text, data in conn.execute(
                "SELECT id, lat, lon, note_text, created_at FROM geo_notes "
                "WHERE photo_path IS NOT NULL AND photo_path <> '' AND lat IS NOT NULL"
            ).fetchall():
                if any(_v_poligone(lon, lat, g) for g in kontury):
                    out.append({"kogda": data or "", "kto": "", "chto": "метка", "podpis": text or "",
                                "otkuda": "метка", "path": f"/bot/geo-notes/{nid}/photo"})
        except Exception:  # noqa: BLE001
            pass

    def klyuch(x):
        s = str(x["kogda"])[:10]
        if len(s) == 10 and s[2] == ".":
            s = f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
        return s

    out.sort(key=klyuch, reverse=True)
    return out[:limit]
