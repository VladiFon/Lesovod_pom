#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль 4: "Цифровой двойник леса" — интерактивная карта (folium + geopandas).

Вынесено из app.py, чтобы screens/live_map/ и другие экраны могли
использовать generate_forest_map()/get_sanitary_vydely() без импорта
из app.py — старого tkinter-модуля, который не входит в сборку
PySide6-приложения (в exe его нет, и импорт из него молча падал).

Публичные функции:
    generate_forest_map(db_path, target_lch_num, ...) — строит HTML-карту
        лесничества (folium) с подсветкой выполненных работ.
    get_sanitary_vydely(db_path, target_lch_num, ...) — список выделов
        с усыханием/короедом для слоя "Усыхание леса".

LCH_MAP по-прежнему берётся из config.py (там и было его настоящее
определение) — здесь только re-export для обратной совместимости, если
где-то импортируют LCH_MAP именно из forest_map.
"""

import os
import sqlite3
import sys
import tempfile

from config import LCH_MAP, RESOURCE_DIR

# Раньше здесь было os.path.dirname(os.path.abspath(__file__)) — работало
# только при запуске из исходников (python main.py). В собранном PyInstaller
# .exe модуль forest_map.py не лежит на диске как обычный файл (он упакован
# в архив PYZ), поэтому __file__ указывал не туда, где реально лежат
# map_kvartala.geojson/map_vydela.geojson - карта не находила данные.
# RESOURCE_DIR (см. config.py:_get_resource_dir) корректно учитывает
# sys._MEIPASS и в frozen-режиме, и при обычном запуске из исходников.
FOREST_MAP_DIR = RESOURCE_DIR
FOREST_MAP_KVARTALA_GEOJSON = os.path.join(FOREST_MAP_DIR, "map_kvartala.geojson")
FOREST_MAP_VYDELA_GEOJSON = os.path.join(FOREST_MAP_DIR, "map_vydela.geojson")
FOREST_MAP_OUTPUT_HTML = os.path.join(tempfile.gettempdir(), "forest_map.html")
FOREST_MAP_SOURCE_EPSG = 32635   # локальная метровая проекция исходных .geojson (UTM 35N)
FOREST_MAP_TARGET_EPSG = 4326    # WGS84 — то, что понимает folium (градусы)

# Допуск упрощения геометрии (в градусах WGS84, после перепроекции) —
# см. _read_filtered_layer(). ~0.00003° ≈ 3 м на широте Беларуси, контуры
# выделов визуально не меняются, а число точек в полигонах заметно падает,
# из-за чего folium/QWebEngineView рисуют карту заметно быстрее.
FOREST_MAP_SIMPLIFY_TOLERANCE = 0.00003

# In-process кэш уже отфильтрованных по лесничеству, перепроецированных и
# упрощённых слоёв — ключ (путь_к_файлу, mtime_файла, номер_лесничества).
# Самая дорогая часть generate_forest_map()/get_sanitary_vydely() — не сама
# сборка HTML (она лёгкая), а чтение и разбор исходных .geojson (55 МБ для
# выделов); пока приложение открыто и исходные файлы не менялись, повторные
# открытия карты одного и того же лесничества переиспользуют уже готовый
# GeoDataFrame вместо повторного парсинга всего файла с нуля. Кэш живёт
# только в памяти процесса (сбрасывается при перезапуске программы) — это
# осознанный компромисс простоты, а не персистентный кэш на диске.
_FOREST_MAP_LAYER_CACHE: dict = {}


def _scrub_broken_six_meta_path_importer() -> None:
    """Обход известной ошибки собранного PyInstaller .exe: "AttributeError:
    '_SixMetaPathImporter' object has no attribute '_path'".

    Пакет six при импорте (его тянут за собой зависимости geopandas/
    fiona/pyproj и/или folium/jinja2/branca) регистрирует в sys.meta_path
    свой importer для псевдо-пакета six.moves. У этого importer'а нет
    атрибута _path, который есть у обычных файловых finder'ов — а
    некоторый код в стеке geopandas/folium (поиск шаблонов jinja2 через
    PackageLoader, поиск драйверов GDAL/fiona и т.п.) при сборке в
    PyInstaller .exe перебирает sys.meta_path и обращается к ._path у
    КАЖДОГО finder'а без проверки, что он вообще есть — из-за чего падает
    именно на six. При обычном запуске "python main.py" (не из .exe)
    этот код не выполняется тем же путём, поэтому баг воспроизводится
    только в собранном установщике — вживую в исходниках его не увидеть.

    К моменту вызова этой функции (после всех импортов geopandas/pandas/
    folium в этом модуле) всё, что six.moves реально был нужен ЭТИМ
    библиотекам во время ИХ собственного импорта, уже отработало —
    дальше этот importer в sys.meta_path не нужен, поэтому его можно
    безопасно убрать. Функция идемпотентна и дешёвая — её нормально
    вызывать несколько раз подряд "на всякий случай" после каждого
    потенциально проблемного импорта."""
    try:
        sys.meta_path = [
            finder for finder in sys.meta_path
            if type(finder).__name__ != "_SixMetaPathImporter"
        ]
    except Exception:
        # Сама эта защита не должна ронять генерацию карты — если тут
        # что-то пойдёт не так, просто продолжаем как раньше.
        pass


def _read_filtered_layer(path, target_lch_num, source_epsg, target_epsg, simplify_tolerance=None):
    """Читает .geojson, оставляет только записи нужного лесничества
    (num_lch) и перепроецирует в target_epsg — с кэшированием результата
    в памяти процесса (см. _FOREST_MAP_LAYER_CACHE) и с двумя стратегиями
    фильтрации:

    1. Атрибутивный фильтр НА ЧТЕНИИ (``where=f"num_lch={target_lch_num}"``,
       поддерживается GDAL/fiona/pyogrio, на которые опирается geopandas) —
       не требует парсить в память все 55 МБ файла целиком, читается сразу
       нужный лесничество. Быстрее, но зависит от того, что колонка num_lch
       в файле хранится как число, а не как текст с иным форматированием.
    2. Если способ 1 не сработал (старая версия geopandas без поддержки
       ``where``, несовпадение типов колонки и т.п.) ИЛИ вернул пустой
       результат — используется прежний надёжный способ: читаем файл
       целиком и фильтруем через pandas (pd.to_numeric с coerce), как это
       было раньше. Так фильтрация на чтении — это ускорение, а не новая
       точка отказа: при любых проблемах с ней карта всё равно построится,
       просто без этого конкретного выигрыша в скорости.
    """
    import geopandas as gpd
    import pandas as pd
    _scrub_broken_six_meta_path_importer()

    mtime = os.path.getmtime(path)
    cache_key = (path, mtime, int(target_lch_num), simplify_tolerance)
    cached = _FOREST_MAP_LAYER_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()

    gdf = None
    try:
        candidate = gpd.read_file(path, where=f"num_lch = {int(target_lch_num)}")
        if not candidate.empty:
            gdf = candidate
    except Exception:
        # Атрибутивный фильтр не поддержан текущей версией geopandas/GDAL
        # для этого файла — тихо переходим к надёжному способу 2 ниже.
        gdf = None

    if gdf is None:
        full = gpd.read_file(path)
        if "num_lch" not in full.columns:
            raise RuntimeError(f"В файле {os.path.basename(path)} отсутствует колонка num_lch.")
        gdf = full[
            pd.to_numeric(full["num_lch"], errors="coerce").fillna(0).astype(int) == int(target_lch_num)
        ].copy()

    if not gdf.empty:
        gdf.set_crs(epsg=source_epsg, allow_override=True, inplace=True)
        gdf = gdf.to_crs(epsg=target_epsg)
        if simplify_tolerance:
            gdf["geometry"] = gdf["geometry"].simplify(simplify_tolerance, preserve_topology=True)

    # Кэшируем даже пустой результат (лесничества без данных) — иначе при
    # каждом повторном клике на несуществующий/пустой номер снова читался
    # бы весь файл. Старые записи кэша для того же файла с другим mtime
    # (файл переустановили/обновили) просто перестают совпадать по ключу
    # и будут вытеснены сборщиком мусора — специальную очистку не делаем,
    # т.к. в рамках одного запуска программы файлы границ не меняются.
    _FOREST_MAP_LAYER_CACHE[cache_key] = gdf
    return gdf.copy()


def _forest_map_norm_id(value):
    """Приводит значение атрибута/колонки БД к сравнимому строковому виду, чтобы
    140 (int из geojson), 140.0 (float) и '140' (str из TEXT-колонки БД) считались
    одинаковыми. Строковые составные обозначения (например, '4,5') не трогаем —
    только .strip(), чтобы не сломать нечисловые/составные номера выделов."""
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


# категории видов работ -> (ключевое слово в tip_raboty, цвет заливки, подпись для легенды).
# Порядок важен: проверяются по очереди, побеждает первое совпадение (поэтому "руб" стоит
# раньше "уход" — "Рубка ухода" должна закраситься красным, а не жёлтым).
FOREST_MAP_WORK_CATEGORIES = [
    ("руб", "#ff4444", "Рубка"),
    ("осветл", "#ffeb3b", "Уход / осветление"),
    ("уход", "#ffeb3b", "Уход / осветление"),
    ("посад", "#4caf50", "Посадка / дополнение"),
    ("дополн", "#4caf50", "Посадка / дополнение"),
]
FOREST_MAP_DEFAULT_COLOR = "#8bc34a"
FOREST_MAP_DEFAULT_LABEL = "Прочие работы"

FOREST_MAP_LEGEND_HTML = """
<div style="position: fixed; bottom: 30px; left: 30px; z-index: 9999;
            background: rgba(255,255,255,0.95); padding: 12px 16px; border-radius: 10px;
            border: 1px solid #bbb; box-shadow: 2px 2px 8px rgba(0,0,0,0.25);
            font-family: Arial, sans-serif; font-size: 13px; line-height: 1.7; color:#222;">
  <div style="font-weight:bold; margin-bottom:6px;">Легенда</div>
  <div><span style="display:inline-block;width:14px;height:14px;background:#ff4444;
       border:1px solid #999;margin-right:6px;vertical-align:middle;"></span>Рубка</div>
  <div><span style="display:inline-block;width:14px;height:14px;background:#ffeb3b;
       border:1px solid #999;margin-right:6px;vertical-align:middle;"></span>Уход / осветление</div>
  <div><span style="display:inline-block;width:14px;height:14px;background:#4caf50;
       border:1px solid #999;margin-right:6px;vertical-align:middle;"></span>Посадка / дополнение</div>
  <div><span style="display:inline-block;width:14px;height:14px;background:#8bc34a;
       border:1px solid #999;margin-right:6px;vertical-align:middle;"></span>Прочие работы</div>
  <div><span style="display:inline-block;width:14px;height:14px;background:transparent;
       border:1px solid #666;margin-right:6px;vertical-align:middle;"></span>Работы не проводились</div>
</div>
"""


def _forest_map_category(entries):
    """Определяет (цвет, подпись) категории по совокупности tip_raboty на выделе."""
    combined = " ".join((e.get("tip_raboty") or "") for e in entries).lower()
    for keyword, color, label in FOREST_MAP_WORK_CATEGORIES:
        if keyword in combined:
            return color, label
    return FOREST_MAP_DEFAULT_COLOR, FOREST_MAP_DEFAULT_LABEL


def _forest_map_load_completed_works(db_path, target_lch_name):
    """Читает completed_works и возвращает {(квартал, выдел): [записи]}, где каждая
    запись — dict с tip_raboty / ispolnitel_fio / data_vypolneniya (для попапа и категорий).

    target_lch_name — название лесничества (ключ LCH_MAP), которым фильтруется выборка.
    Кварталы и выделы нумеруются заново в каждом лесничестве, поэтому без фильтра по
    lesnichestvo одинаковые номера квартала/выдела в разных лесничествах "склеивались"
    и работы одного лесничества дублировались на карте другого."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT kvartal, vydel, tip_raboty, ispolnitel_fio, data_vypolneniya "
            "FROM completed_works WHERE kvartal IS NOT NULL AND vydel IS NOT NULL "
            "AND lesnichestvo = ?",
            (target_lch_name,),
        ).fetchall()
    finally:
        conn.close()

    lookup = {}
    for kvartal, vydel, tip_raboty, fio, data_vyp in rows:
        key = (_forest_map_norm_id(kvartal), _forest_map_norm_id(vydel))
        if not key[0] or not key[1]:
            continue
        entry = {
            "tip_raboty": (tip_raboty or "").strip(),
            "ispolnitel_fio": (fio or "").strip(),
            "data_vypolneniya": (data_vyp or "").strip(),
        }
        entries = lookup.setdefault(key, [])
        if entry not in entries:
            entries.append(entry)
    return lookup


def _forest_map_popup_html(num_kv, num_vd, entries):
    """Собирает HTML-табличку попапа для одного выдела."""
    parts = [
        '<div style="font-family:Arial,sans-serif;font-size:13px;min-width:220px;">',
        f'<div style="font-weight:bold;font-size:14px;margin-bottom:6px;">'
        f'Квартал {num_kv} / Выдел {num_vd}</div>',
    ]
    if entries:
        parts.append('<table style="border-collapse:collapse;width:100%;">')
        for e in entries:
            tip = e["tip_raboty"] or "—"
            fio = e["ispolnitel_fio"] or "—"
            date = e["data_vypolneniya"] or "—"
            parts.append(
                '<tr style="border-top:1px solid #ddd;">'
                f'<td style="padding:4px 0 0 0;">🛠️&nbsp;<b>{tip}</b></td></tr>'
                '<tr><td style="padding:0 0 6px 0;color:#555;">'
                f"👤&nbsp;{fio}&nbsp;&nbsp;·&nbsp;&nbsp;📅&nbsp;{date}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append('<div style="color:#888;">Работы не проводились</div>')
    parts.append("</div>")
    return "".join(parts)


def _forest_map_load_geo_notes(db_path):
    """Читает geo_notes (гео-заметки, присланные рабочими прямо с точки на
    местности — см. telegram_bot.py handle_location/_pending_geo) и
    возвращает список dict-ов с полями lat/lon/note_text/photo_path/
    created_at. В отличие от completed_works, geo_notes НЕ фильтруются по
    лесничеству: заметка привязана к точным координатам, а не к
    квартал/выделу, поэтому лесничество ей не нужно — она и так попадёт
    в правильное место на карте благодаря координатам."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT lat, lon, note_text, photo_path, created_at FROM geo_notes "
            "WHERE lat IS NOT NULL AND lon IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    notes = []
    for lat, lon, note_text, photo_path, created_at in rows:
        try:
            notes.append(
                {
                    "lat": float(lat),
                    "lon": float(lon),
                    "note_text": (note_text or "").strip(),
                    "photo_path": (photo_path or "").strip(),
                    "created_at": (created_at or "").strip(),
                }
            )
        except (TypeError, ValueError):
            # координаты не смогли привестись к числу — пропускаем
            # заметку, а не роняем построение всей карты
            continue
    return notes


def _forest_map_geo_note_popup_html(note):
    """Собирает HTML попапа для одной гео-заметки: дата, текст заметки и,
    если есть photo_path, встроенная картинка. Путь к фото передаётся
    в folium как file:// URL — так браузер, открывающий локальный HTML
    карты, может подгрузить файл напрямую с диска."""
    parts = ['<div style="font-family:Arial,sans-serif;font-size:13px;min-width:200px;">']
    parts.append('<div style="font-weight:bold;font-size:14px;margin-bottom:6px;">📍 Гео-заметка</div>')

    if note["created_at"]:
        parts.append(f'<div style="color:#555;margin-bottom:4px;">📅&nbsp;{note["created_at"]}</div>')

    if note["note_text"]:
        parts.append(f'<div style="margin-bottom:6px;">{note["note_text"]}</div>')
    else:
        parts.append('<div style="color:#888;margin-bottom:6px;">Без текстового комментария</div>')

    photo_path = note["photo_path"]
    if photo_path and os.path.exists(photo_path):
        photo_url = "file:///" + os.path.abspath(photo_path).replace(os.sep, "/")
        parts.append(
            f'<img src="{photo_url}" style="max-width:220px;max-height:220px;'
            'border-radius:6px;display:block;" />'
        )

    parts.append("</div>")
    return "".join(parts)


# ключевые слова, по которым в свободном тексте гео-заметки (geo_notes.note_text)
# распознаётся сигнал об усыхании/санитарном неблагополучии выдела. Отдельной
# таблицы под санитарное состояние в БД пока нет — рабочие на местности присылают
# такие сигналы как обычную гео-заметку с телефона/планшета (см. telegram_bot.py),
# поэтому источник данных для слоя карты — этот же geo_notes.
FOREST_MAP_SANITARY_KEYWORDS = [
    "короед", "усых", "усохш", "санитар", "вредител", "болезн", "ветровал", "бурелом",
]


def get_sanitary_vydely(db_path, target_lch_num, vydela_path=FOREST_MAP_VYDELA_GEOJSON):
    """Данные для слоя "Усыхание леса" на живой карте (см. LiveMapScreen).

    Берёт geo_notes (гео-заметки с координатами, присланные рабочими прямо с точки
    на местности — см. _forest_map_load_geo_notes), отбирает те, чей note_text
    похож на сигнал об усыхании/короеде/санитарном неблагополучии
    (FOREST_MAP_SANITARY_KEYWORDS), и для каждой такой точки пытается определить
    квартал/выдел — тем же пространственным способом (точка внутри полигона),
    что и generate_forest_map(): geopandas читает map_vydela.geojson, фильтрует
    по num_lch и ищет полигон, содержащий координаты заметки.

    Возвращает список dict: {"kvartal", "vydel", "prichina", "lat", "lon"}.
    kvartal/vydel могут оказаться пустыми строками (если geopandas не установлен,
    файл границ выделов не найден, либо точка не попала ни в один полигон) — это
    не ошибка: сама запись всё равно возвращается, и слой карты сможет поставить
    маркер по lat/lon даже без точной привязки к выделу."""
    notes = _forest_map_load_geo_notes(db_path)
    matches = [
        n for n in notes
        if any(keyword in n["note_text"].lower() for keyword in FOREST_MAP_SANITARY_KEYWORDS)
    ]
    if not matches:
        return []

    def _without_geometry():
        return [
            {
                "kvartal": "",
                "vydel": "",
                "prichina": n["note_text"] or "Усыхание",
                "lat": n["lat"],
                "lon": n["lon"],
            }
            for n in matches
        ]

    try:
        from shapely.geometry import Point
    except ImportError:
        # Без geopandas/shapely не можем определить квартал/выдел по точке —
        # отдаём заметки как есть, слой карты поставит маркеры по координатам.
        return _without_geometry()

    if not os.path.exists(vydela_path):
        return _without_geometry()

    # Геометрия НЕ упрощается (в отличие от generate_forest_map) — здесь
    # она используется для точного пространственного теста "точка внутри
    # полигона" (contains), и даже небольшое упрощение контура может
    # сдвинуть границу настолько, что заметка у самой кромки выдела
    # ошибочно попадёт мимо. Кэш (_read_filtered_layer) всё равно ускоряет
    # повторные вызовы за счёт фильтрации по num_lch на чтении.
    try:
        gdf_vydela_wgs84 = _read_filtered_layer(
            vydela_path, target_lch_num, FOREST_MAP_SOURCE_EPSG, FOREST_MAP_TARGET_EPSG,
        )
    except Exception:
        return _without_geometry()

    if gdf_vydela_wgs84.empty:
        return _without_geometry()

    results = []
    for note in matches:
        point = Point(note["lon"], note["lat"])
        num_kv, num_vd = "", ""
        hit = gdf_vydela_wgs84[gdf_vydela_wgs84.contains(point)]
        if not hit.empty:
            row = hit.iloc[0]
            num_kv = _forest_map_norm_id(row.get("num_kv"))
            num_vd = _forest_map_norm_id(row.get("num_vd"))
        results.append(
            {
                "kvartal": num_kv,
                "vydel": num_vd,
                "prichina": note["note_text"] or "Усыхание",
                "lat": note["lat"],
                "lon": note["lon"],
            }
        )
    return results


def get_delyanka_location(target_lch_num, kvartal, vydel, vydela_path=FOREST_MAP_VYDELA_GEOJSON):
    """Мобильное приложение (Фаза 6): координаты ОДНОЙ делянки по
    квартал/выдел/лесничество — центроид её полигона в map_vydela.geojson.

    В отличие от get_map_layer_geojson() (GET /api/map/vydela), не
    гоняет клиенту весь слой лесничества — экран "Карта" в приложении
    просит только точку для одной конкретной делянки (см.
    GET /api/map/delyanka-location в app/routers/map.py). Использует ту
    же кэширующую фильтрацию _read_filtered_layer, что и остальная живая
    карта, поэтому не заводит собственный, отдельный способ читать
    map_vydela.geojson.

    Возвращает {"lat": float, "lon": float, "kvartal": str, "vydel": str}
    либо None, если geopandas не установлен, файл не найден, либо такой
    квартал/выдел не нашёлся в слое — это НЕ исключение (в отличие от
    get_map_layer_geojson), т.к. отсутствие координат у одной делянки не
    должно ронять весь экран, только прятать кнопку "Маршрут" на нём.
    """
    try:
        gdf = _read_filtered_layer(
            vydela_path, target_lch_num, FOREST_MAP_SOURCE_EPSG, FOREST_MAP_TARGET_EPSG,
        )
    except Exception:
        return None
    if gdf.empty or "num_kv" not in gdf.columns or "num_vd" not in gdf.columns:
        return None

    target_kv, target_vd = _forest_map_norm_id(kvartal), _forest_map_norm_id(vydel)
    match = gdf[
        (gdf["num_kv"].map(_forest_map_norm_id) == target_kv)
        & (gdf["num_vd"].map(_forest_map_norm_id) == target_vd)
    ]
    if match.empty:
        return None

    centroid = match.iloc[0].geometry.centroid
    return {"lat": centroid.y, "lon": centroid.x, "kvartal": target_kv, "vydel": target_vd}


def generate_forest_map(
    db_path,
    target_lch_num,
    kvartala_path=FOREST_MAP_KVARTALA_GEOJSON,
    vydela_path=FOREST_MAP_VYDELA_GEOJSON,
    output_path=FOREST_MAP_OUTPUT_HTML,
):
    """Строит интерактивную HTML-карту леса: границы кварталов + выделов, с категорийной
    подсветкой выделов по типу выполненных работ (completed_works), HTML-легендой,
    попапами по клику, поиском по номеру квартала и постоянными подписями кварталов.
    target_lch_num — номер лесничества (num_lch), которым фильтруются оба слоя перед
    отрисовкой: это резко снижает число полигонов, передаваемых в folium, и убирает
    лаги интерфейса при отрисовке карты целого лесхоза.
    Возвращает путь к сохранённому .html. geopandas/folium импортируются лениво (внутри
    функции), чтобы отсутствие этих пакетов не мешало запуску всего приложения."""
    try:
        import folium
        from folium.plugins import Search
        _scrub_broken_six_meta_path_importer()
    except ImportError as e:
        raise RuntimeError(
            "Для карты леса нужны пакеты geopandas и folium.\n"
            "Установите их: pip install geopandas folium\n\n"
            f"({e})"
        )

    if not os.path.exists(kvartala_path):
        raise FileNotFoundError(f"Не найден файл границ кварталов: {kvartala_path}")
    if not os.path.exists(vydela_path):
        raise FileNotFoundError(f"Не найден файл границ выделов: {vydela_path}")

    # --- читаем geojson: фильтр по num_lch применяется НА ЧТЕНИИ (если
    # поддержано установленной версией geopandas/GDAL), а не после загрузки
    # всего файла в память — для map_vydela.geojson (55 МБ, вся база
    # выделов лесхоза) это резко сокращает время открытия карты. Геометрия
    # кварталов дополнительно упрощается (см. FOREST_MAP_SIMPLIFY_TOLERANCE)
    # — контуры визуально не меняются, но folium/QWebEngineView рисуют
    # карту заметно быстрее. Результат кэшируется в памяти процесса на
    # время работы программы (см. _read_filtered_layer) — повторное
    # открытие карты того же лесничества не читает файл заново. ---
    try:
        gdf_kvartala = _read_filtered_layer(
            kvartala_path, target_lch_num, FOREST_MAP_SOURCE_EPSG, FOREST_MAP_TARGET_EPSG,
            simplify_tolerance=FOREST_MAP_SIMPLIFY_TOLERANCE,
        )
        gdf_vydela = _read_filtered_layer(
            vydela_path, target_lch_num, FOREST_MAP_SOURCE_EPSG, FOREST_MAP_TARGET_EPSG,
            simplify_tolerance=FOREST_MAP_SIMPLIFY_TOLERANCE,
        )
    except ImportError as e:
        raise RuntimeError(
            "Для карты леса нужны пакеты geopandas и folium.\n"
            "Установите их: pip install geopandas folium\n\n"
            f"({e})"
        )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Не удалось прочитать файлы границ: {e}")

    if gdf_kvartala.empty or gdf_vydela.empty:
        raise RuntimeError(
            f"Нет данных для лесничества № {target_lch_num} в файлах границ.\n"
            "Проверьте значения num_lch в geojson."
        )

    # --- данные о выполненных работах, с безопасным сравнением TEXT (БД) <-> INT (geojson) ---
    # LCH_MAP хранит соответствие "название лесничества" -> num_lch; чтобы отфильтровать
    # completed_works по lesnichestvo (текстовое поле в БД), находим обратное соответствие.
    target_lch_name_matches = [k for k, v in LCH_MAP.items() if v == int(target_lch_num)]
    if not target_lch_name_matches:
        raise RuntimeError(
            f"Лесничество № {target_lch_num} не найдено в LCH_MAP — проверьте соответствие номеров."
        )
    target_lch_name = target_lch_name_matches[0]
    completed_lookup = _forest_map_load_completed_works(db_path, target_lch_name)

    def _vydel_tooltip(row):
        num_kv, num_vd = row.get("num_kv"), row.get("num_vd")
        text = f"Квартал: {num_kv}, Выдел: {num_vd}"
        entries = completed_lookup.get((_forest_map_norm_id(num_kv), _forest_map_norm_id(num_vd)))
        if entries:
            _color, label = _forest_map_category(entries)
            types = sorted({e["tip_raboty"] for e in entries if e["tip_raboty"]})
            text += f"<br>Статус: Выполнено ({', '.join(types) if types else label})"
        return text

    gdf_vydela = gdf_vydela.copy()
    gdf_vydela["tooltip_text"] = gdf_vydela.apply(_vydel_tooltip, axis=1)
    gdf_vydela["popup_html"] = gdf_vydela.apply(
        lambda row: _forest_map_popup_html(
            row.get("num_kv"), row.get("num_vd"),
            completed_lookup.get((_forest_map_norm_id(row.get("num_kv")), _forest_map_norm_id(row.get("num_vd")))),
        ),
        axis=1,
    )

    def _vydel_style(feature):
        props = feature.get("properties", {})
        key = (_forest_map_norm_id(props.get("num_kv")), _forest_map_norm_id(props.get("num_vd")))
        entries = completed_lookup.get(key)
        if entries:
            color, _label = _forest_map_category(entries)
            return {"fillColor": color, "fillOpacity": 0.65, "color": "#333333", "weight": 1}
        return {"fillColor": "#00ff00", "fillOpacity": 0.0, "color": "#666666", "weight": 1}

    # --- карта, отцентрированная и вписанная по границам данных ---
    minx, miny, maxx, maxy = gdf_vydela.total_bounds
    center = [(miny + maxy) / 2, (minx + maxx) / 2]
    fmap = folium.Map(location=center, tiles="OpenStreetMap", control_scale=True)
    fmap.fit_bounds([[miny, minx], [maxy, maxx]])

    kvartala_layer = folium.GeoJson(
        gdf_kvartala,
        name="Кварталы",
        style_function=lambda feature: {
            "fillColor": "#000000", "fillOpacity": 0.0, "color": "black", "weight": 2,
        },
        tooltip=folium.GeoJsonTooltip(fields=["num_kv"], aliases=["Квартал:"]),
    ).add_to(fmap)

    folium.GeoJson(
        gdf_vydela,
        name="Выдела",
        style_function=_vydel_style,
        tooltip=folium.GeoJsonTooltip(fields=["tooltip_text"], aliases=[""], labels=False, sticky=True),
        popup=folium.GeoJsonPopup(fields=["popup_html"], aliases=[""], labels=False),
    ).add_to(fmap)

    # --- постоянные подписи номеров кварталов по центроидам полигонов ---
    labels_fg = folium.FeatureGroup(name="Номера кварталов", show=True)
    for _, row in gdf_kvartala.iterrows():
        centroid = row.geometry.centroid
        folium.map.Marker(
            [centroid.y, centroid.x],
            icon=folium.DivIcon(
                html=(
                    '<div style="font-size:13px;font-weight:bold;color:#111;'
                    'text-shadow:1px 1px 2px #fff,-1px -1px 2px #fff,1px -1px 2px #fff,-1px 1px 2px #fff;">'
                    f'{row.get("num_kv")}</div>'
                ),
            ),
        ).add_to(labels_fg)
    labels_fg.add_to(fmap)

    # --- гео-заметки рабочих (см. telegram_bot.py handle_location/_pending_geo):
    # точки на местности с текстовым комментарием и/или фото, не привязанные
    # к конкретному кварталу/выделу — в отличие от слоя "Выдела" выше,
    # координаты geo_notes не фильтруются по лесничеству, но на карту
    # конкретного лесничества и так попадут только точки в его границах ---
    geo_notes_fg = folium.FeatureGroup(name="Гео-заметки", show=True)
    for note in _forest_map_load_geo_notes(db_path):
        folium.Marker(
            location=[note["lat"], note["lon"]],
            icon=folium.Icon(color="red", icon="info-sign"),
            popup=folium.Popup(_forest_map_geo_note_popup_html(note), max_width=260),
            tooltip="📍 Гео-заметка",
        ).add_to(geo_notes_fg)
    geo_notes_fg.add_to(fmap)

    # --- поиск по номеру квартала (центрирует и приближает карту к найденному кварталу) ---
    Search(
        layer=kvartala_layer,
        search_label="num_kv",
        placeholder="Поиск по номеру квартала…",
        collapsed=False,
        search_zoom=15,
        position="topleft",
    ).add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    fmap.get_root().html.add_child(folium.Element(FOREST_MAP_LEGEND_HTML))

    # Ещё раз на всякий случай — именно здесь (fmap.save()) jinja2 в первый
    # раз реально ЧИТАЕТ файлы шаблонов folium с диска (PackageLoader),
    # это самое вероятное место падения "_SixMetaPathImporter" в .exe.
    _scrub_broken_six_meta_path_importer()
    fmap.save(output_path)
    return output_path


# --------------------------------------------------------------------------- #
#   Блок 2 доработки (PLAN_DORABOTKI.md) — bbox-стриминг для react-leaflet.
#
#   generate_forest_map() выше НЕ трогали: он остаётся рабочим fallback'ом
#   (кнопка "Экспорт в HTML" на фронтенде) для тех, кому нужен один
#   самодостаточный HTML-файл карты (например, отправить по почте /
#   открыть без сервера). Живая карта (LiveMap.jsx) теперь получает те же
#   исходные .geojson по частям — только то, что попадает в bbox текущего
#   вида карты, а не весь файл целиком (map_vydela.geojson — 56 МБ на
#   лесхоз, отдавать это браузеру одним куском на каждое открытие экрана
#   не вариант).
#
#   Переиспользуем весь пайплайн _read_filtered_layer() (фильтр по
#   num_lch на чтении + перепроецирование + кэш в памяти процесса) —
#   разница только в том, что после него добавляется:
#     1. упрощение геометрии с допуском, подобранным под zoom (чем дальше
#        отдалена карта, тем грубее контур — иначе браузер захлебнётся
#        полигонами по всей области, см. AUDIT.md и сам план);
#     2. обрезка по bbox текущего вида (GeoDataFrame.cx[...] — работает по
#        уже отфильтрованному по лесничеству, а значит на порядок меньшему
#        набору строк, поэтому это дёшево даже без спатиального индекса);
#     3. (только для выделов) подсветка по категории выполненных работ —
#        то же самое, что _vydel_style()/_vydel_category() делают для
#        HTML-карты, но здесь результат кладётся в свойства GeoJSON
#        (status_color/status_label), а не в inline-стиль folium, чтобы
#        стилизацией занимался Leaflet на фронтенде.
# --------------------------------------------------------------------------- #

# Пороги upper-bound по zoom → допуск упрощения в градусах WGS84 (тот же
# порядок величины, что и FOREST_MAP_SIMPLIFY_TOLERANCE выше, только с
# более грубыми ступенями на дальних масштабах). Список отсортирован по
# убыванию порога — берётся первый порог, который >= запрошенному zoom.
# Ступени, а не плавная функция от zoom, — сознательно: так на кэш
# _read_filtered_layer (ключ включает simplify_tolerance) приходится не
# больше 4 разных допусков на лесничество, а не по одному на каждый
# промежуточный уровень зума, которым Leaflet заваливает бы бэкенд.
_MAP_ZOOM_SIMPLIFY_STEPS = [
    (17, 0.0),        # близкий масштаб — геометрия без упрощения
    (15, 0.00004),    # ~4 м допуска
    (13, 0.00012),    # ~12 м допуска
    (11, 0.0003),     # ~30 м допуска
    (0, 0.0007),      # весь лесхоз целиком — самый грубый контур
]


def _tolerance_for_zoom(zoom):
    """zoom=None (клиент не прислал) — берём допуск как для дальнего
    масштаба (самый безопасный вариант по объёму данных)."""
    if zoom is None:
        return _MAP_ZOOM_SIMPLIFY_STEPS[-1][1]
    try:
        zoom = float(zoom)
    except (TypeError, ValueError):
        return _MAP_ZOOM_SIMPLIFY_STEPS[-1][1]
    for threshold, tolerance in _MAP_ZOOM_SIMPLIFY_STEPS:
        if zoom >= threshold:
            return tolerance
    return _MAP_ZOOM_SIMPLIFY_STEPS[-1][1]


def parse_map_bbox(bbox):
    """Разбирает bbox вида "minLon,minLat,maxLon,maxLat" (именно в таком
    порядке шлёт Leaflet: LatLngBounds.toBBoxString()). Возвращает
    (minx, miny, maxx, maxy) или None, если bbox не передан. Кидает
    ValueError с понятным текстом при некорректном формате — роутер
    превращает это в HTTP 400."""
    if not bbox:
        return None
    parts = bbox.split(",")
    if len(parts) != 4:
        raise ValueError("bbox должен быть строкой вида minLon,minLat,maxLon,maxLat")
    try:
        minx, miny, maxx, maxy = (float(p) for p in parts)
    except ValueError:
        raise ValueError("bbox должен содержать 4 числа через запятую")
    if minx > maxx or miny > maxy:
        raise ValueError("bbox некорректен: min не может быть больше max")
    return minx, miny, maxx, maxy


# Знаков после запятой в координатах на выходе — 6 (~11 см на широте
# Беларуси). Ускорение "того что есть", а не новая точка отказа: само
# упрощение под zoom (_tolerance_for_zoom) уже режет точки с точностью в
# единицы-десятки метров, поэтому округление до 11 см ничего не меняет
# ни визуально, ни для расчётов площади/местоположения — но заметно
# уменьшает вес JSON (лишние 10-12 незначащих цифр на каждую координату)
# и время его сборки/парсинга на фронте при каждом перемещении/зуме карты.
_OUTPUT_COORD_PRECISION = 6


def _round_coords(coords):
    """Рекурсивно округляет вложенный список координат GeoJSON (Point/
    LineString/Polygon/Multi*) до _OUTPUT_COORD_PRECISION знаков — не
    трогает структуру, просто уменьшает число значащих цифр в каждом
    числе."""
    if not coords:
        return coords
    if isinstance(coords[0], (list, tuple)):
        return [_round_coords(c) for c in coords]
    return [round(c, _OUTPUT_COORD_PRECISION) for c in coords]


def _gdf_to_geojson_dict(gdf, columns):
    """Собирает FeatureCollection вручную (а не через gdf.to_json()/
    __geo_interface__), чтобы: 1) отдавать в properties только нужные
    колонки (для 56-мегабайтного слоя выделов лишние атрибуты из
    исходного .geojson — заметная экономия трафика при стриминге по
    bbox на каждое движение карты); 2) подчистить NaN/numpy-скаляры,
    которые иначе попадают в JSON как невалидный литерал NaN и ломают
    JSON.parse на стороне браузера; 3) округлить координаты (см.
    _round_coords) — тот же выигрыш в весе ответа, что и от zoom-
    упрощения, но по весу JSON, а не по числу точек."""
    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        props = {}
        for col in columns:
            val = row.get(col)
            if isinstance(val, float) and val != val:  # NaN
                val = None
            elif hasattr(val, "item"):  # numpy.int64/float64 -> python
                val = val.item()
            props[col] = val
        geo_interface = geom.__geo_interface__
        geometry = {
            "type": geo_interface["type"],
            "coordinates": _round_coords(geo_interface["coordinates"]),
        }
        features.append({"type": "Feature", "geometry": geometry, "properties": props})
    return {"type": "FeatureCollection", "features": features}


def get_map_layer_geojson(
    db_path,
    target_lch_num,
    layer,
    bbox=None,
    zoom=None,
    kvartala_path=FOREST_MAP_KVARTALA_GEOJSON,
    vydela_path=FOREST_MAP_VYDELA_GEOJSON,
):
    """Возвращает GeoJSON (dict) для одного из двух слоёв живой карты,
    обрезанный по bbox и упрощённый под zoom — то, что зовут
    GET /api/map/kvartaly и GET /api/map/vydela (app/routers/map.py).

    layer: "kvartaly" | "vydela".
    bbox: строка "minLon,minLat,maxLon,maxLat" или None (тогда отдаётся
        весь слой лесничества — например, для печати/экспорта; на живой
        карте фронтенд всегда шлёт bbox текущего вида).
    zoom: текущий zoom карты (см. _tolerance_for_zoom) — на что не похоже
        по имени, но тоже необязательный параметр.

    Для слоя "vydela" дополнительно считает status_color/status_label —
    то же самое сопоставление с completed_works, что и в
    generate_forest_map()/_vydel_style(), только результат уходит в
    properties GeoJSON, а не в inline style HTML-карты.
    """
    if layer not in ("kvartaly", "vydela"):
        raise ValueError(f"Неизвестный слой карты: {layer!r}")

    if not os.path.exists(kvartala_path):
        raise FileNotFoundError(f"Не найден файл границ кварталов: {kvartala_path}")
    if not os.path.exists(vydela_path):
        raise FileNotFoundError(f"Не найден файл границ выделов: {vydela_path}")

    path = kvartala_path if layer == "kvartaly" else vydela_path
    tolerance = _tolerance_for_zoom(zoom)

    gdf = _read_filtered_layer(
        path, target_lch_num, FOREST_MAP_SOURCE_EPSG, FOREST_MAP_TARGET_EPSG,
        simplify_tolerance=tolerance,
    )

    if "num_kv" not in gdf.columns:
        raise RuntimeError(f"В файле {os.path.basename(path)} отсутствует колонка num_kv.")
    if layer == "vydela" and "num_vd" not in gdf.columns:
        raise RuntimeError(f"В файле {os.path.basename(path)} отсутствует колонка num_vd.")

    bounds = parse_map_bbox(bbox)
    if bounds is not None and not gdf.empty:
        minx, miny, maxx, maxy = bounds
        gdf = gdf.cx[minx:maxx, miny:maxy]

    if layer == "kvartaly":
        return _gdf_to_geojson_dict(gdf, ["num_kv"])

    # --- слой "Выдела" — та же категоризация по completed_works, что и
    # на HTML-карте (см. _vydel_style/_forest_map_category выше) ---
    gdf = gdf.copy()
    target_lch_name_matches = [k for k, v in LCH_MAP.items() if str(v) == str(int(target_lch_num))]
    completed_lookup = (
        _forest_map_load_completed_works(db_path, target_lch_name_matches[0])
        if target_lch_name_matches else {}
    )

    def _status_color(row):
        key = (_forest_map_norm_id(row.get("num_kv")), _forest_map_norm_id(row.get("num_vd")))
        entries = completed_lookup.get(key)
        if entries:
            color, _label = _forest_map_category(entries)
            return color
        return None  # нет данных — фронтенд рисует нейтральный контур без заливки

    def _status_label(row):
        key = (_forest_map_norm_id(row.get("num_kv")), _forest_map_norm_id(row.get("num_vd")))
        entries = completed_lookup.get(key)
        if not entries:
            return None
        types = sorted({e["tip_raboty"] for e in entries if e["tip_raboty"]})
        _color, label = _forest_map_category(entries)
        return ", ".join(types) if types else label

    if not gdf.empty:
        gdf["status_color"] = gdf.apply(_status_color, axis=1)
        gdf["status_label"] = gdf.apply(_status_label, axis=1)
    else:
        gdf["status_color"] = []
        gdf["status_label"] = []

    return _gdf_to_geojson_dict(gdf, ["num_kv", "num_vd", "status_color", "status_label"])


def warm_layer_cache(db_path, lesnichestva_nums=None):
    """Прогревает _FOREST_MAP_LAYER_CACHE заранее (при старте backend'а —
    см. app/main.py:on_startup), а не только по первому реальному
    запросу с Живой карты. Ускоряет "то, что есть" (см. чат) — сама
    стратегия (упрощение под zoom + in-process кэш) не меняется, просто
    самый частый случай (карта только что открыта, zoom = дефолтный)
    больше не читает и не упрощает 55 МБ geojson на глазах у первого
    открывшего карту пользователя после каждого перезапуска backend'а.

    lesnichestva_nums: явный список num_lch для прогрева — по умолчанию
    все, что есть в LCH_MAP (обычно счёт на единицы-десятки, не проблема
    прогреть все сразу).

    Выполняется синхронно — вызывающий код (app/main.py) запускает эту
    функцию в фоновом потоке, чтобы не задерживать старт сервера. Любая
    ошибка (нет файлов, нет geopandas и т.п.) не должна ронять запуск —
    поэтому все исключения на уровне одного лесничества/слоя гасятся
    здесь же, а не всплывают наверх.
    """
    nums = lesnichestva_nums or list(LCH_MAP.values())
    # DEFAULT_MAP_ZOOM во фронтенде (LiveMap.jsx) = 12 -> _tolerance_for_zoom
    # даёт грубую ступень (для zoom >= 11) — тот самый "первый вид карты",
    # который иначе прогревался бы только по факту первого открытия.
    warm_tolerance = _tolerance_for_zoom(12)
    for num in nums:
        for path in (FOREST_MAP_KVARTALA_GEOJSON, FOREST_MAP_VYDELA_GEOJSON):
            try:
                if os.path.exists(path):
                    _read_filtered_layer(
                        path, num, FOREST_MAP_SOURCE_EPSG, FOREST_MAP_TARGET_EPSG,
                        simplify_tolerance=warm_tolerance,
                    )
            except Exception:  # noqa: BLE001 — прогрев кэша необязателен, не должен мешать старту
                pass
