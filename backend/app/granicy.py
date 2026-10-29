# -*- coding: utf-8 -*-
"""Границы кварталов и выделов из QGIS (кнопка «Отправить кварталы и
выделы в Лесовод» плагина «Лесовод-мост», 29.10.2026).

Живая карта на сайте и телефоне берёт границы из двух файлов в
RESOURCE_DIR — map_kvartala.geojson и map_vydela.geojson (см.
legacy/forest_map.py). Раньше после обновления карт в ГИСлесхозе их
приходилось выгружать из QGIS руками и подкладывать на сервер. Теперь
плагин шлёт слой сюда, а здесь:

* проверяем, что это полигоны в EPSG:32635 (forest_map считает исходные
  файлы именно такими — градусы WGS84 уехали бы «к чёрту на рога») и что
  у объектов есть num_lch / num_kv (/ num_vd у выделов);
* заменяем объекты только тех лесничеств, что пришли, — остальные
  лесничества из старого файла остаются как были (слой в QGIS бывает
  отфильтрован по одному лесничеству);
* старый файл сохраняем рядом копией (последние HRANIT_KOPIY штук), новый
  кладём атомарно — кэш forest_map привязан к mtime файла и сам
  перечитает его на следующем запросе, перезапуск не нужен.
"""
import gzip
import io
import json
import os
import shutil
import threading
import time

import forest_map

SLOI = {
    "kvartaly": (forest_map.FOREST_MAP_KVARTALA_GEOJSON, ("num_lch", "num_kv")),
    "vydela": (forest_map.FOREST_MAP_VYDELA_GEOJSON, ("num_lch", "num_kv", "num_vd")),
}
NAZVANIYA = {"kvartaly": "кварталов", "vydela": "выделов"}
HRANIT_KOPIY = 3
_ZAMOK = threading.Lock()  # два «Отправить» подряд не должны писать файл одновременно
MAKS_RAZMER = 400 * 1024 * 1024  # после распаковки

# Беларусь в UTM 35N (EPSG:32635): x ≈ 150…900 км, y ≈ 5 700…6 300 км.
# С запасом — лишь бы отличить метры от градусов и от чужой зоны.
_X_DIAPAZON = (0, 1_200_000)
_Y_DIAPAZON = (5_000_000, 7_000_000)


class GranicyError(ValueError):
    pass


def _chislo(value):
    """35 / "35" / 35.0 -> 35; "35а" остаётся текстом; пусто -> None."""
    if value is None:
        return None
    text = str(value).strip()
    if text in ("", "NULL"):
        return None
    try:
        f = float(text.replace(",", "."))
    except ValueError:
        return text
    return int(f) if f.is_integer() else text


def _pervaya_tochka(coords):
    while isinstance(coords, list) and coords and isinstance(coords[0], list):
        coords = coords[0]
    return coords if isinstance(coords, list) and len(coords) >= 2 else None


def razobrat(sloy: str, data: bytes) -> list:
    """Тело запроса (GeoJSON, можно gzip) -> список Feature с чистыми
    properties. Кидает GranicyError с текстом для человека."""
    if sloy not in SLOI:
        raise GranicyError(f"Неизвестный слой {sloy!r}: нужен kvartaly или vydela")
    if data[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                data = gz.read(MAKS_RAZMER + 1)
        except OSError as exc:
            raise GranicyError(f"Не удалось распаковать файл: {exc}")
    if len(data) > MAKS_RAZMER:
        raise GranicyError("Файл слишком большой")
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GranicyError(f"Это не GeoJSON: {exc}")
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
        raise GranicyError("Нужен GeoJSON FeatureCollection")

    polya = SLOI[sloy][1]
    out = []
    for i, f in enumerate(doc.get("features") or []):
        geom = (f or {}).get("geometry") or {}
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        props = f.get("properties") or {}
        chistye = {pole: _chislo(props.get(pole)) for pole in polya}
        if not isinstance(chistye["num_lch"], int):
            raise GranicyError(f"Объект №{i + 1}: нет номера лесничества (num_lch)")
        if chistye["num_kv"] is None:
            raise GranicyError(f"Объект №{i + 1}: нет номера квартала (num_kv)")
        tochka = _pervaya_tochka(geom.get("coordinates"))
        if tochka is None:
            continue
        x, y = tochka[0], tochka[1]
        if not (_X_DIAPAZON[0] < x < _X_DIAPAZON[1] and _Y_DIAPAZON[0] < y < _Y_DIAPAZON[1]):
            raise GranicyError(
                f"Координаты ({x:.4f}, {y:.4f}) не похожи на EPSG:32635 (UTM 35N, метры). "
                "Слой нужно отправлять в системе координат ГИСлесхоза — плагин делает это сам, "
                "обновите «Лесовод-мост»."
            )
        out.append({"type": "Feature", "properties": chistye, "geometry": geom})
    if not out:
        raise GranicyError("В слое нет ни одного полигона")
    return out


def _lesnichestvo(feature):
    return _chislo((feature.get("properties") or {}).get("num_lch"))


def _starye(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("features") or []
    except (OSError, ValueError):
        # битый старый файл — не повод не принять новый (копия всё равно останется)
        return []


def _ubrat_lishnie_kopii(path):
    papka, imya = os.path.split(path)
    stem = os.path.splitext(imya)[0]
    kopii = sorted(n for n in os.listdir(papka) if n.startswith(stem + "_") and n.endswith(".bak.geojson"))
    for n in kopii[:-HRANIT_KOPIY]:
        try:
            os.remove(os.path.join(papka, n))
        except OSError:
            pass


def sohranit(sloy: str, features: list) -> dict:
    """Заменяет в файле слоя пришедшие лесничества, остальные оставляет."""
    with _ZAMOK:
        return _sohranit(sloy, features)


def _sohranit(sloy, features):
    path = SLOI[sloy][0]
    novye_lesn = {}
    for f in features:
        num = _lesnichestvo(f)
        novye_lesn[num] = novye_lesn.get(num, 0) + 1

    ostavleno = {}
    itog = []
    for f in _starye(path):
        num = _lesnichestvo(f)
        if num in novye_lesn:
            continue
        ostavleno[num] = ostavleno.get(num, 0) + 1
        itog.append(f)
    itog.extend(features)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    vremennyy = path + ".novyy"
    with open(vremennyy, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": itog}, f, ensure_ascii=False, separators=(",", ":"))

    kopiya = None
    if os.path.exists(path):
        kopiya = f"{os.path.splitext(path)[0]}_{time.strftime('%Y%m%d_%H%M%S')}.bak.geojson"
        shutil.copy2(path, kopiya)
    os.replace(vremennyy, path)
    _ubrat_lishnie_kopii(path)

    return {
        "sloy": sloy,
        "obektov": len(features),
        "lesnichestva": {str(k): v for k, v in sorted(novye_lesn.items(), key=lambda kv: str(kv[0]))},
        "ostavleno_lesnichestv": {str(k): v for k, v in sorted(ostavleno.items(), key=lambda kv: str(kv[0]))},
        "kopiya": os.path.basename(kopiya) if kopiya else None,
    }


def progret(nums):
    """Сразу перечитать новый файл в кэш — первый открывший карту не ждёт."""
    import config as legacy_config

    try:
        forest_map.warm_layer_cache(legacy_config.DB_PATH, [int(n) for n in nums])
    except Exception:  # noqa: BLE001 — прогрев необязателен
        pass
