# -*- coding: utf-8 -*-
"""Лесные дороги (12.11.2026, редизайн приложения, этап 5).

Мастера, помощники лесничего и лесничий рисуют на телефоне лесные дороги:
грунтовки, лежнёвки, зимники и волоки — и отмечают, кто по ним проедет
(легковая, УАЗ, лесовоз, только трактор). Дороги общие: их видят все в
приложении, по ним телефон строит маршрут «по лесным дорогам, а не по
прямой». На сайте карты нет (решение Влада), для QGIS — слой
/api/map/qgis/dorogi.geojson.

Линия хранится как GeoJSON LineString ([[lon, lat], ...]). Удаление мягкое
(udalena = 1), как у проб: дорогу рисовали полдня, случайное «Удалить» не
должно стирать её насовсем."""
import json
import math
from typing import Iterable, List, Optional

EARTH_RADIUS_M = 6_371_008.8

TIPY = ("gruntovka", "lezhnevka", "zimnik", "volok")
TIP_LABELS = {"gruntovka": "Грунтовка", "lezhnevka": "Лежнёвка", "zimnik": "Зимник", "volok": "Волок"}
PROEZD = ("legkovaya", "uaz", "lesovoz", "traktor")
PROEZD_LABELS = {"legkovaya": "Легковая", "uaz": "УАЗ", "lesovoz": "Лесовоз", "traktor": "Трактор"}

MAX_TOCHEK = 5000

SCHEMA = """
CREATE TABLE IF NOT EXISTS lesnye_dorogi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazvanie TEXT,
    tip TEXT NOT NULL DEFAULT 'gruntovka',
    proezd TEXT,
    geom_geojson TEXT NOT NULL,
    dlina_m REAL,
    lesnichestvo TEXT,
    kommentariy TEXT,
    sozdal_identity TEXT,
    sozdal_sotrudnik_id INTEGER,
    sozdal_fio TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT,
    izmenil_fio TEXT,
    udalena INTEGER NOT NULL DEFAULT 0,
    udalil_fio TEXT,
    udalena_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_lesnye_dorogi_udalena ON lesnye_dorogi(udalena);
"""

_COLS = ("id", "nazvanie", "tip", "proezd", "geom_geojson", "dlina_m", "lesnichestvo", "kommentariy",
         "sozdal_sotrudnik_id", "sozdal_fio", "created_at", "updated_at", "izmenil_fio")


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))


def dlina(tochki: List[List[float]]) -> float:
    return sum(distance_m(a[0], a[1], b[0], b[1]) for a, b in zip(tochki, tochki[1:]))


def proverit_tochki(tochki: Optional[Iterable]) -> List[List[float]]:
    """[[lon, lat], ...] → чистый список; ошибки — ValueError с понятным текстом."""
    if not tochki:
        raise ValueError("Нужны точки дороги")
    out: List[List[float]] = []
    for p in tochki:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise ValueError("Точка дороги — пара [долгота, широта]")
        lon, lat = float(p[0]), float(p[1])
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("Координаты точки вне диапазона")
        if out and out[-1][0] == lon and out[-1][1] == lat:
            continue
        out.append([round(lon, 7), round(lat, 7)])
    if len(out) < 2:
        raise ValueError("В дороге должно быть хотя бы две разные точки")
    if len(out) > MAX_TOCHEK:
        raise ValueError(f"Слишком много точек (больше {MAX_TOCHEK})")
    return out


def proverit_tip(tip: Optional[str]) -> str:
    tip = (tip or "gruntovka").strip().lower()
    if tip not in TIPY:
        raise ValueError("Тип дороги: грунтовка, лежнёвка, зимник или волок")
    return tip


def proverit_proezd(proezd: Optional[Iterable[str]], tip: str) -> List[str]:
    """Кто проедет. Не указали — по типу: волок только трактор, остальное — УАЗ и трактор."""
    if proezd is None:
        return ["traktor"] if tip == "volok" else ["uaz", "traktor"]
    out = []
    for p in proezd:
        p = (p or "").strip().lower()
        if p not in PROEZD:
            raise ValueError("Кто проедет: легковая, УАЗ, лесовоз или трактор")
        if p not in out:
            out.append(p)
    if not out:
        raise ValueError("Отметьте, кто проедет по дороге")
    return out


def _row(row) -> dict:
    d = dict(zip(_COLS, row))
    geom = json.loads(d.pop("geom_geojson") or "{}")
    d["tochki"] = geom.get("coordinates") or []
    d["proezd"] = [p for p in (d.get("proezd") or "").split(",") if p]
    d["tip_label"] = TIP_LABELS.get(d["tip"], d["tip"])
    d["proezd_labels"] = [PROEZD_LABELS.get(p, p) for p in d["proezd"]]
    return d


def spisok(conn) -> List[dict]:
    rows = conn.execute(
        f"SELECT {', '.join(_COLS)} FROM lesnye_dorogi WHERE udalena = 0 ORDER BY id"
    ).fetchall()
    return [_row(r) for r in rows]


def odna(conn, doroga_id: int) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {', '.join(_COLS)} FROM lesnye_dorogi WHERE id = ? AND udalena = 0", (doroga_id,)
    ).fetchone()
    return _row(row) if row else None


def geom_json(tochki: List[List[float]]) -> str:
    return json.dumps({"type": "LineString", "coordinates": tochki}, ensure_ascii=False)


def geojson(conn) -> dict:
    """Слой для QGIS: линии с типом, проездом и автором в свойствах."""
    features = []
    for d in spisok(conn):
        tochki = d.pop("tochki")
        d["proezd"] = ", ".join(d.pop("proezd_labels"))
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": tochki}, "properties": d})
    return {"type": "FeatureCollection", "features": features}
