# -*- coding: utf-8 -*-
"""Пробные площади на карте (26.10.2026).

По правилам техническая приёмка, инвентаризация 1-го и 3-го года лесных
культур проходят на ОДНОЙ И ТОЙ ЖЕ пробе. Чтобы её не терять, пробу ставят
с телефона (точка GPS, усреднённая по нескольким замерам, + форма границы),
она хранится здесь, на сервере (не на телефоне), и видна всем: на карте
приложения, в QGIS и в карточке участка культур на сайте.

Проба привязывается к участку лесных культур (lesokultury_uchastok):
явно — выбором в приложении, иначе сервер ищет участок сам (свой контур
участка, в который попала точка, затем участок на этом кв./выд.).
Полевая карточка инвентаризации с телефона ссылается на пробу
(dannye_json.proby[].karta_proba_id) — так у пробы складывается история
учётов, а у следующего учёта — подсказка «та же проба, что в прошлый раз».

Граница хранится готовым полигоном (geom_geojson) и параметрами формы:
круг (радиус), прямоугольник (длина × ширина, азимут длинной стороны) или
контур, обойдённый по GPS. Полигон для круга/прямоугольника строит сервер —
одинаково для телефона, QGIS и сайта.

Удаление мягкое (udalena = 1): проба — опорная точка на годы, случайное
«Удалить» не должно стирать её насовсем."""
import json
import math
import re
from typing import Dict, Iterable, List, Optional, Tuple

from app import map_features

EARTH_RADIUS_M = 6_371_008.8
FORMY = ("krug", "pryamougolnik", "kontur")
FORMA_LABELS = {"krug": "круг", "pryamougolnik": "прямоугольник", "kontur": "обход по GPS"}

# Этапы, которые по правилам идут на одной пробе — в этом порядке.
ETAPY = ("Техническая приёмка", "Инвентаризация 1-го года", "Инвентаризация 3-го года")

SCHEMA = """
CREATE TABLE IF NOT EXISTS karta_proby (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nomer TEXT,
    uchastok_id INTEGER REFERENCES lesokultury_uchastok(id),
    lesnichestvo TEXT,
    kvartal TEXT,
    vydel TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    forma TEXT NOT NULL DEFAULT 'krug',
    radius_m REAL,
    dlina_m REAL,
    shirina_m REAL,
    azimut REAL,
    ploshad_m2 REAL,
    geom_geojson TEXT,
    tochnost_m REAL,
    orientir TEXT,
    photo_path TEXT,
    sozdal_identity TEXT,
    sozdal_sotrudnik_id INTEGER,
    sozdal_fio TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT,
    udalena INTEGER NOT NULL DEFAULT 0,
    udalil_fio TEXT,
    udalena_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_karta_proby_uchastok ON karta_proby(uchastok_id);
CREATE INDEX IF NOT EXISTS idx_karta_proby_kv ON karta_proby(kvartal, vydel);
"""

_COLS = ("id", "nomer", "uchastok_id", "lesnichestvo", "kvartal", "vydel", "lat", "lon", "forma",
         "radius_m", "dlina_m", "shirina_m", "azimut", "ploshad_m2", "geom_geojson", "tochnost_m",
         "orientir", "photo_path", "sozdal_identity", "sozdal_sotrudnik_id", "sozdal_fio",
         "created_at", "updated_at")


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# --------------------------------------------------------------------------- #
#   Геометрия — локальная равнопромежуточная проекция вокруг центра пробы.
#   На масштабе пробы (метры) ошибка ничтожна по сравнению с GPS.
# --------------------------------------------------------------------------- #
def _m_per_deg(lat: float) -> Tuple[float, float]:
    m_lat = math.pi * EARTH_RADIUS_M / 180.0
    return m_lat, m_lat * math.cos(math.radians(lat))


def _offset(lat: float, lon: float, east_m: float, north_m: float) -> List[float]:
    m_lat, m_lon = _m_per_deg(lat)
    return [round(lon + east_m / m_lon, 8), round(lat + north_m / m_lat, 8)]


def krug(lat: float, lon: float, radius_m: float, n: int = 36) -> dict:
    ring = [_offset(lat, lon, radius_m * math.sin(2 * math.pi * i / n), radius_m * math.cos(2 * math.pi * i / n))
            for i in range(n)]
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def pryamougolnik(lat: float, lon: float, dlina_m: float, shirina_m: float, azimut: float) -> dict:
    """Центр — середина прямоугольника; длина — вдоль азимута (0 — север)."""
    a = math.radians(azimut or 0.0)
    ux, uy = math.sin(a), math.cos(a)  # вдоль длины (восток, север)
    vx, vy = uy, -ux  # поперёк
    hl, hw = dlina_m / 2.0, shirina_m / 2.0
    ring = [_offset(lat, lon, sx * hl * ux + sy * hw * vx, sx * hl * uy + sy * hw * vy)
            for sx, sy in ((1, 1), (1, -1), (-1, -1), (-1, 1))]
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def kontur(points: List[List[float]]) -> dict:
    ring = [[round(p[0], 8), round(p[1], 8)] for p in points]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def ploshad_m2(geometry: dict) -> float:
    ring = geometry["coordinates"][0]
    lat0 = sum(p[1] for p in ring) / len(ring)
    lon0 = ring[0][0]
    m_lat, m_lon = _m_per_deg(lat0)
    pts = [((p[0] - lon0) * m_lon, (p[1] - lat0) * m_lat) for p in ring]
    s = sum(pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1] for i in range(len(pts) - 1))
    return round(abs(s) / 2.0, 1)


def ploshad_formy(forma: str, geometry: dict, radius_m=None, dlina_m=None, shirina_m=None) -> float:
    """Площадь пробы, м²: круг и прямоугольник — точно по размерам (полигон
    круга — 36-угольник, он чуть меньше), обход — по контуру."""
    if forma == "krug" and radius_m:
        return round(math.pi * radius_m * radius_m, 1)
    if forma == "pryamougolnik" and dlina_m and shirina_m:
        return round(dlina_m * shirina_m, 1)
    return ploshad_m2(geometry)


def _centroid(points: List[List[float]]) -> Tuple[float, float]:
    pts = points[:-1] if len(points) > 1 and points[0] == points[-1] else points
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def _ring_contains(ring, lat: float, lon: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def _geometry_contains(geometry: dict, lat: float, lon: float) -> bool:
    if not geometry:
        return False
    if geometry.get("type") == "Polygon":
        polys = [geometry.get("coordinates") or []]
    elif geometry.get("type") == "MultiPolygon":
        polys = geometry.get("coordinates") or []
    else:
        return False
    for poly in polys:
        if poly and _ring_contains(poly[0], lat, lon) and not any(_ring_contains(h, lat, lon) for h in poly[1:]):
            return True
    return False


def postroit(forma: str, lat: Optional[float], lon: Optional[float], radius_m=None, dlina_m=None,
             shirina_m=None, azimut=None, tochki=None) -> dict:
    """Полигон границы + центр по параметрам формы. ValueError — что не так."""
    if forma not in FORMY:
        raise ValueError("Форма пробы: круг, прямоугольник или обход")
    if forma == "kontur":
        pts = [p for p in (tochki or []) if len(p) >= 2 and -180 <= p[0] <= 180 and -90 <= p[1] <= 90]
        if len(pts) < 3:
            raise ValueError("Для обхода нужно минимум 3 точки")
        if len(pts) > 5000:
            raise ValueError("Слишком много точек")
        geometry = kontur(pts)
        if lat is None or lon is None:
            lat, lon = _centroid(geometry["coordinates"][0])
        return {"geometry": geometry, "lat": lat, "lon": lon}
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Нужны координаты центра пробы")
    if forma == "krug":
        if not radius_m or not (0.3 <= radius_m <= 200):
            raise ValueError("Радиус круга — от 0,3 до 200 м")
        return {"geometry": krug(lat, lon, radius_m), "lat": lat, "lon": lon}
    if not dlina_m or not shirina_m or not (0.3 <= dlina_m <= 500 and 0.3 <= shirina_m <= 500):
        raise ValueError("Длина и ширина прямоугольника — от 0,3 до 500 м")
    return {"geometry": pryamougolnik(lat, lon, dlina_m, shirina_m, azimut or 0.0), "lat": lat, "lon": lon}


# --------------------------------------------------------------------------- #
#   Привязка к участку лесных культур
# --------------------------------------------------------------------------- #
def _uchastki(conn) -> List[dict]:
    cur = conn.execute("SELECT * FROM lesokultury_uchastok WHERE status IS NULL OR status != 'списан'")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def naiti_uchastok(conn, lat: float, lon: float, kvartal: Optional[str], vydel: Optional[str],
                   lesnichestvo: Optional[str]) -> Optional[int]:
    """Сначала — участок, в собственный контур которого попала точка; затем —
    участок на этом кв./выд. (самый свежий, активные раньше переведённых)."""
    from app.uhody_lesokultury import vydely_uchastka

    try:
        uchastki = _uchastki(conn)
    except Exception:  # noqa: BLE001 — таблицы ещё нет
        return None
    for u in sorted(uchastki, key=lambda u: -u["id"]):
        try:
            geometry = json.loads(u.get("geom_geojson") or "null")
        except (TypeError, ValueError):
            geometry = None
        if geometry and _geometry_contains(geometry, lat, lon):
            return u["id"]
    kv, vd = map_features.norm_id(kvartal), map_features.norm_id(vydel)
    if not kv or not vd:
        return None
    found = [
        u for u in uchastki
        if map_features.norm_id(u.get("kvartal")) == kv and vd in vydely_uchastka(u)
        and (not lesnichestvo or not u.get("lesnichestvo") or map_features.same_lesnichestvo(lesnichestvo, u.get("lesnichestvo")))
    ]
    found.sort(key=lambda u: ((u.get("status") or "активен") != "активен", -u["id"]))
    return found[0]["id"] if found else None


def sleduyushchiy_nomer(conn, uchastok_id: Optional[int], kvartal: Optional[str], vydel: Optional[str]) -> str:
    """Номер по порядку на участке (или на кв./выд., если участка нет)."""
    if uchastok_id:
        rows = conn.execute("SELECT nomer FROM karta_proby WHERE uchastok_id = ? AND udalena = 0", (uchastok_id,)).fetchall()
    else:
        rows = conn.execute("SELECT nomer FROM karta_proby WHERE kvartal = ? AND vydel = ? AND udalena = 0",
                            (kvartal or "", vydel or "")).fetchall()
    nums = [int(m.group()) for (n,) in rows if n and (m := re.match(r"\d+", str(n)))]
    return str(max(nums) + 1 if nums else 1)


# --------------------------------------------------------------------------- #
#   Чтение: проба + участок + этапы учёта
# --------------------------------------------------------------------------- #
def _row_dict(row) -> dict:
    return dict(zip(_COLS, row))


def _uchastok_info(conn, ids: Iterable[int]) -> Dict[int, dict]:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    q = ("SELECT id, kvartal, vydel, lesnichestvo, god_sozdaniya, glavnaya_poroda, ploshad, status "
         f"FROM lesokultury_uchastok WHERE id IN ({','.join('?' * len(ids))})")
    return {r[0]: {"id": r[0], "kvartal": r[1], "vydel": r[2], "lesnichestvo": r[3], "god_sozdaniya": r[4],
                   "glavnaya_poroda": r[5], "ploshad": r[6], "status": r[7]}
            for r in conn.execute(q, ids).fetchall()}


def _zhurnal(conn, ids: Iterable[int]) -> Dict[int, List[dict]]:
    ids = [i for i in set(ids) if i]
    out: Dict[int, List[dict]] = {}
    if not ids:
        return out
    q = ("SELECT id, uchastok_id, tip, data, prizhivaemost_pct, dannye_json FROM lesokultury_meropriyatiya "
         f"WHERE uchastok_id IN ({','.join('?' * len(ids))}) ORDER BY id")
    for m_id, u_id, tip, data, pct, dannye_json in conn.execute(q, ids).fetchall():
        proby_ids = set()
        if dannye_json:
            try:
                dannye = json.loads(dannye_json) or {}
                proby_ids = {p.get("karta_proba_id") for p in dannye.get("proby") or [] if isinstance(p, dict)}
            except (TypeError, ValueError, AttributeError):
                pass
        out.setdefault(u_id, []).append({"id": m_id, "tip": (tip or "").strip(), "data": data,
                                         "prizhivaemost_pct": pct, "proby": proby_ids})
    return out


def _etapy(zhurnal: List[dict], proba_id: int) -> List[dict]:
    """Тех. приёмка / инвентаризация 1-го и 3-го года: последняя запись
    каждого этапа на участке и была ли она сделана на этой пробе."""
    out = []
    for tip in ETAPY:
        zapisi = [z for z in zhurnal if z["tip"].casefold() == tip.casefold()]
        last = zapisi[-1] if zapisi else None
        out.append({"tip": tip, "data": last["data"] if last else None,
                    "prizhivaemost_pct": last["prizhivaemost_pct"] if last else None,
                    "vypolneno": last is not None,
                    "na_probe": any(proba_id in z["proby"] for z in zapisi)})
    return out


def _sobrat(conn, rows: List[dict]) -> List[dict]:
    u_ids = [r["uchastok_id"] for r in rows]
    info = _uchastok_info(conn, u_ids)
    zhurnal = _zhurnal(conn, u_ids)
    fios = map_features.author_fio_map(conn)
    out = []
    for r in rows:
        try:
            geometry = json.loads(r["geom_geojson"]) if r["geom_geojson"] else None
        except (TypeError, ValueError):
            geometry = None
        z = zhurnal.get(r["uchastok_id"], [])
        istoriya = [{"id": m["id"], "tip": m["tip"], "data": m["data"], "prizhivaemost_pct": m["prizhivaemost_pct"]}
                    for m in z if r["id"] in m["proby"]]
        out.append({
            "id": r["id"], "nomer": r["nomer"], "uchastok_id": r["uchastok_id"],
            "uchastok": info.get(r["uchastok_id"]),
            "lesnichestvo": r["lesnichestvo"], "kvartal": r["kvartal"], "vydel": r["vydel"],
            "lat": r["lat"], "lon": r["lon"], "forma": r["forma"], "forma_label": FORMA_LABELS.get(r["forma"], r["forma"]),
            "radius_m": r["radius_m"], "dlina_m": r["dlina_m"], "shirina_m": r["shirina_m"], "azimut": r["azimut"],
            "ploshad_m2": r["ploshad_m2"], "geometry": geometry, "tochnost_m": r["tochnost_m"],
            "orientir": r["orientir"], "has_photo": bool(r["photo_path"]),
            "photo_url": f"/api/proby/{r['id']}/photo" if r["photo_path"] else None,
            "avtor_fio": r["sozdal_fio"] or fios.get(str(r["sozdal_identity"])),
            "sozdal_sotrudnik_id": r["sozdal_sotrudnik_id"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
            "istoriya": istoriya, "etapy": _etapy(z, r["id"]) if r["uchastok_id"] else [],
        })
    return out


def spisok(conn, lesnichestvo_num: Optional[str] = None, uchastok_id: Optional[int] = None) -> List[dict]:
    q = f"SELECT {', '.join(_COLS)} FROM karta_proby WHERE udalena = 0"
    params: list = []
    if uchastok_id is not None:
        q += " AND uchastok_id = ?"
        params.append(uchastok_id)
    rows = [_row_dict(r) for r in conn.execute(q + " ORDER BY id", params).fetchall()]
    lesn_name = map_features.lesnichestvo_name_for_num(lesnichestvo_num)
    if lesn_name:
        rows = [r for r in rows if not r["lesnichestvo"] or map_features.same_lesnichestvo(r["lesnichestvo"], lesn_name)]
    return _sobrat(conn, rows)


def odna(conn, proba_id: int) -> Optional[dict]:
    row = conn.execute(f"SELECT {', '.join(_COLS)} FROM karta_proby WHERE id = ? AND udalena = 0", (proba_id,)).fetchone()
    return _sobrat(conn, [_row_dict(row)])[0] if row else None


def photo_path(conn, proba_id: int) -> Optional[str]:
    row = conn.execute("SELECT photo_path FROM karta_proby WHERE id = ? AND udalena = 0", (proba_id,)).fetchone()
    return row[0] if row else None


def geojson(conn) -> dict:
    """Для QGIS: полигоны границ с подписью «П{номер}» и этапами учёта."""
    features = []
    for p in spisok(conn):
        if not p["geometry"]:
            continue
        u = p["uchastok"] or {}
        etapy = "; ".join(f"{e['tip']}: {e['data'] or '—'}{' (на этой пробе)' if e['na_probe'] else ''}"
                          for e in p["etapy"] if e["vypolneno"])
        features.append({
            "type": "Feature",
            "geometry": p["geometry"],
            "properties": {
                "id": p["id"], "nomer": p["nomer"], "podpis": f"П{p['nomer'] or ''}",
                "kvartal": p["kvartal"], "vydel": p["vydel"], "uchastok_id": p["uchastok_id"],
                "uchastok": " ".join(str(x) for x in (u.get("glavnaya_poroda"), u.get("god_sozdaniya")) if x) or None,
                "forma": p["forma_label"], "ploshad_m2": p["ploshad_m2"], "tochnost_m": p["tochnost_m"],
                "orientir": p["orientir"], "avtor_fio": p["avtor_fio"], "created_at": p["created_at"],
                "lat": p["lat"], "lon": p["lon"], "etapy": etapy or None,
            },
        })
    return {"type": "FeatureCollection", "features": features}
