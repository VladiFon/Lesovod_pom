# -*- coding: utf-8 -*-
"""
Делянка = один или несколько выделов, отведённых в рубку (обычно по одному
МДО на выдел). Хранит данные, вытянутые из МДО, сверенные/дополненные
таксацией, плюс вручную вводимые поля для акта обследования.
"""
import json
import os
import sqlite3

from mdo_parser import parse_mdo
from db import get_vydel_card
from config import RESOURCE_DIR
import akt_generator
import listok_generator
import tehkarta_generator

# Стандартные формулировки для типового случая (сплошная санитарная рубка
# из-за короеда-типографа) - подставляются по умолчанию при создании новой
# делянки, чтобы не вводить одно и то же каждый раз. При необходимости
# редактируются в интерфейсе (кнопка "Редактировать").
DEFAULT_AKT_FIELDS = {
    "prichiny": (
        "неблагоприятные погодные условия и последующее повреждение деревьев "
        "стволовыми вредителями (насаждение является очагом стволовых "
        "вредителей), а также наличие единичного ветровала-бурелома."
    ),
    "vrediteli": "короед-типограф",
    "meropriyatiya": (
        "сплошная санитарная рубка в связи с утратой лесным насаждением "
        "биологической устойчивости и снижением полноты ниже предела, "
        "установленного пунктом 20 Санитарных правил в лесах Республики Беларусь."
    ),
    "polnota_zhivyh": "0.5",
    "preduprezhdenie": "лесопатологический мониторинг и при необходимости - ВСР или уборка захламленности.",
    "krasnaya_kniga_meropriyatiya": "нет.",
}


def _lookup_taxatsia(conn, kvartal, vydel, lesnichestvo_hint=None):
    """Достаёт запас на га (x10, см. описание формата) и подстраховочно
    состав/возраст/полноту/тип леса/бонитет/происхождение из своей БД
    таксации. Возвращает dict или None, если выдел не найден."""
    card = get_vydel_card(conn, kvartal, vydel, lesnichestvo_name=lesnichestvo_hint)
    if not card:
        return None
    zapas_raw = card.get("zapas_na_ga") or ""
    zapas_na_ga = None
    try:
        zapas_na_ga = float(zapas_raw.replace(",", ".")) * 10 if zapas_raw else None
    except ValueError:
        pass
    return {
        "zapas_na_ga": zapas_na_ga,
        "sostav": card.get("formula_sostava", ""),
        "vozrast": card["sostav"][0]["vozrast"] if card.get("sostav") else "",
        "polnota": card.get("polnota", ""),
        "tip_lesa": card.get("tip_lesa", ""),
        "bonitet": card.get("bonitet", ""),
        "kategoriya_lesov": card.get("kategoriya_lesov", ""),
        "proishozhdenie": "искусств." if card.get("lesnye_kultury") else "ест.",
        "lesnichestvo": card.get("lesnichestvo", "").strip(),
    }


def create_delyanka_from_mdo(conn, rtf_paths, nazvanie=None, ask_vydel=None):
    """Создаёт новую делянку, разбирая один или несколько файлов МДО (.rtf),
    сверяя каждый выдел с таксацией. Возвращает id созданной делянки.

    Если в МДО в поле "выдел" указано несколько выделов сразу (например,
    "14, 15" или "14/15"), для поиска в таксации нужен ровно один номер —
    пользователю предлагается выбрать "главный" выдел диалоговым окном.
    Полный исходный перечень выделов при этом сохраняется без изменений
    в mdo["vydel"] и, соответственно, в delyanka_item.vydel — он нужен
    целиком для актов и других генерируемых документов.

    ask_vydel: необязательный callback(text, title) -> str, который должен
        показать диалог и вернуть введённое значение (или "" при отмене).
        ОБЯЗАТЕЛЕН при вызове из фонового потока (см. screens/plots/:
        MDOWorker) — раньше здесь напрямую создавался ctk.CTkInputDialog
        (customtkinter/Tkinter), а Tkinter в принципе нельзя дёргать ни из
        какого потока, кроме главного - при попытке падало с
        "RuntimeError: main thread is not in main loop". MDOWorker передаёт
        сюда свой собственный ask_vydel, который безопасно, через
        Qt.BlockingQueuedConnection, просит ГЛАВНЫЙ поток показать
        QInputDialog и дожидается ответа. Если ask_vydel не передан (например,
        при запуске этого модуля напрямую, см. блок __main__ ниже) —
        используется старый Tkinter-диалог как запасной вариант, это
        безопасно ТОЛЬКО при вызове из главного потока."""
    import re

    # выдел считается "составным", если в строке есть запятая, слеш, плюс
    # или союз "и" (например: "14, 15", "14/15", "14+15", "14 и 15")
    MULTI_VYDEL_RE = re.compile(r"[,/+]|\bи\b", re.IGNORECASE)
    FIRST_NUMBER_RE = re.compile(r"\d+")

    items = []
    for rtf_path in rtf_paths:
        mdo = parse_mdo(rtf_path)
        vydel_str = str(mdo.get("vydel", ""))

        # дефолт на случай отмены диалога или отсутствия запятых в строке
        default_match = FIRST_NUMBER_RE.search(vydel_str)
        main_vydel = default_match.group() if default_match else vydel_str

        if MULTI_VYDEL_RE.search(vydel_str):
            text = (
                f"Документ: {rtf_path}\n"
                f"Указано несколько выделов: {vydel_str}\n"
                "Введите номер ГЛАВНОГО выдела (для загрузки таксации):"
            )
            title = "Выбор главного выдела"
            if ask_vydel is not None:
                user_input = ask_vydel(text, title)
            else:
                import customtkinter as ctk
                dialog = ctk.CTkInputDialog(text=text, title=title)
                user_input = dialog.get_input()
            if user_input and user_input.strip():
                main_vydel = user_input.strip()
            # если пользователь нажал "Отмена" или оставил поле пустым —
            # main_vydel остаётся дефолтным (первое найденное число)

        tax = _lookup_taxatsia(conn, mdo.get("kvartal"), main_vydel, mdo.get("lesnichestvo"))

        item = {
            "lesxoz": mdo.get("lesxoz", ""),
            "lesnichestvo": mdo.get("lesnichestvo") or (tax or {}).get("lesnichestvo", ""),
            "kvartal": mdo.get("kvartal", ""),
            "vydel": mdo.get("vydel", ""),  # исходная строка целиком, не перезаписываем
            "lesoseka_nomer": mdo.get("lesoseka_nomer", ""),
            "kategoriya_lesov": mdo.get("kategoriya_lesov") or (tax or {}).get("kategoriya_lesov", ""),
            "ploshad": mdo.get("ploshad_ekspluatatsionnaya") or mdo.get("ploshad_obshaya", ""),
            "zapas_na_ga": (tax or {}).get("zapas_na_ga"),
            "vyrubaemyy_zapas": mdo.get("vyrubaemyy_zapas"),
            "proishozhdenie": (tax or {}).get("proishozhdenie", "ест."),
            "sostav": mdo.get("sostav") or (tax or {}).get("sostav", ""),
            "vozrast": mdo.get("vozrast") or (tax or {}).get("vozrast", ""),
            "polnota": mdo.get("polnota") or (tax or {}).get("polnota", ""),
            "tip_lesa": (tax or {}).get("tip_lesa") or mdo.get("tip_lesa", ""),
            "bonitet": (tax or {}).get("bonitet", ""),
            "krasnaya_kniga": "-",
            "mdo_source_file": mdo.get("source_file", ""),
            "mdo_raw_json": json.dumps(mdo, ensure_ascii=False),
            "_taxatsia_found": tax is not None,
        }
        items.append(item)

    if nazvanie is None:
        first = items[0]
        nazvanie = f"кв.{first['kvartal']}/выд.{first['vydel']}"
        # Номер лесосеки - главный признак различения делянок с одинаковым
        # кварталом/выделом (в одном выделе за разные годы/этапы может быть
        # несколько разных лесосек) - без него в списке делянок такие
        # записи выглядели бы неотличимо друг от друга.
        if first.get("lesoseka_nomer"):
            nazvanie += f", лесосека №{first['lesoseka_nomer']}"
        if len(items) > 1:
            nazvanie += f" +{len(items) - 1}"

    cur = conn.execute(
        """INSERT INTO delyanka (nazvanie, chleny_json, prichiny, vrediteli, meropriyatiya,
                                  polnota_zhivyh, preduprezhdenie, krasnaya_kniga_meropriyatiya)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            nazvanie, json.dumps([], ensure_ascii=False),
            DEFAULT_AKT_FIELDS["prichiny"], DEFAULT_AKT_FIELDS["vrediteli"],
            DEFAULT_AKT_FIELDS["meropriyatiya"], DEFAULT_AKT_FIELDS["polnota_zhivyh"],
            DEFAULT_AKT_FIELDS["preduprezhdenie"], DEFAULT_AKT_FIELDS["krasnaya_kniga_meropriyatiya"],
        ),
    )
    delyanka_id = cur.lastrowid

    for idx, it in enumerate(items):
        conn.execute(
            """INSERT INTO delyanka_item
               (delyanka_id, poryadok, lesxoz, lesnichestvo, kvartal, vydel, lesoseka_nomer,
                kategoriya_lesov, ploshad, zapas_na_ga, vyrubaemyy_zapas, proishozhdenie,
                sostav, vozrast, polnota, tip_lesa, bonitet, krasnaya_kniga,
                mdo_source_file, mdo_raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                delyanka_id, idx, it["lesxoz"], it["lesnichestvo"], it["kvartal"], it["vydel"],
                it["lesoseka_nomer"], it["kategoriya_lesov"], it["ploshad"], it["zapas_na_ga"],
                it["vyrubaemyy_zapas"], it["proishozhdenie"], it["sostav"], it["vozrast"],
                it["polnota"], it["tip_lesa"], it["bonitet"], it["krasnaya_kniga"],
                it["mdo_source_file"], it["mdo_raw_json"],
            ),
        )
    conn.commit()

    not_found = [it["kvartal"] + "/" + it["vydel"] for it in items if not it["_taxatsia_found"]]
    return delyanka_id, not_found


def create_delyanki_from_mdo_batch(conn, rtf_paths, ask_vydel=None):
    """Создаёт ОТДЕЛЬНУЮ делянку для КАЖДОГО файла МДО из списка — в отличие
    от create_delyanka_from_mdo(), которая объединяет всю пачку rtf_paths в
    ОДНУ делянку с несколькими выделами. Это и есть штатный сценарий
    "перетащил/выбрал сразу несколько МДО" (кнопка "📥 Импорт МДО" и
    drag-and-drop в screens/plots/): раньше вся пачка ошибочно уходила в
    одну делянку.

    ask_vydel прокидывается в create_delyanka_from_mdo() как есть — если
    среди пачки несколько файлов содержат составной выдел ("14, 15" и т.п.),
    диалог будет показан по очереди для каждого такого файла.

    Если один из файлов не разбирается (испорченный .rtf, не найден бланк
    и т.п.) — это не должно ронять всю пачку: ошибка по нему запоминается
    в errors, а остальные файлы обрабатываются дальше.

    Возвращает (results, errors):
        results — список (rtf_path, delyanka_id, not_found_list)
        errors  — список (rtf_path, текст_ошибки)
    """
    results = []
    errors = []
    for rtf_path in rtf_paths:
        try:
            delyanka_id, not_found = create_delyanka_from_mdo(conn, [rtf_path], ask_vydel=ask_vydel)
            results.append((rtf_path, delyanka_id, not_found))
        except Exception as e:  # noqa: BLE001 — один битый МДО не должен блокировать всю пачку
            errors.append((rtf_path, str(e)))
    return results, errors


def create_delyanka_manual(conn, nazvanie, kvartal, vydel, lesnichestvo=None):
    """Мобильное приложение / карта (Фаза 6 плана доработки): создаёт
    делянку из одного выдела БЕЗ импорта MDO — рабочий/лесничий отмечает
    выдел прямо на карте (тап по полигону в WebView-карте приложения даёт
    kvartal/vydel/lesnichestvo из свойств feature), в отличие от
    create_delyanka_from_mdo() выше не парсит .rtf и не спрашивает
    пользователя про несколько кандидатов главного выдела — сразу один
    конкретный выдел.

    Таксационные поля (sostav/vozrast/polnota/tip_lesa/bonitet/ploshad и
    т.п.) подтягиваются автоматически через _lookup_taxatsia() — той же
    функцией, которой пользуется MDO-импорт, чтобы делянка, заведённая с
    телефона, ничем не отличалась от заведённой через импорт файла.

    Возвращает id новой делянки (delyanka.id)."""
    taxatsia = _lookup_taxatsia(conn, kvartal, vydel, lesnichestvo_hint=lesnichestvo) or {}
    lesnichestvo_final = lesnichestvo or taxatsia.get("lesnichestvo") or ""

    cur = conn.execute(
        "INSERT INTO delyanka (nazvanie, status) VALUES (?, 'черновик')",
        (nazvanie,),
    )
    delyanka_id = cur.lastrowid
    conn.execute(
        """INSERT INTO delyanka_item
               (delyanka_id, poryadok, lesnichestvo, kvartal, vydel,
                ploshad, sostav, vozrast, polnota, tip_lesa, bonitet,
                proishozhdenie, kategoriya_lesov, zapas_na_ga)
           VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            delyanka_id, lesnichestvo_final, kvartal, vydel,
            taxatsia.get("ploshad"), taxatsia.get("sostav"), taxatsia.get("vozrast"),
            taxatsia.get("polnota"), taxatsia.get("tip_lesa"), taxatsia.get("bonitet"),
            taxatsia.get("proishozhdenie"), taxatsia.get("kategoriya_lesov"),
            taxatsia.get("zapas_na_ga"),
        ),
    )
    conn.commit()
    return delyanka_id


def create_delyanka_from_geometry(conn, nazvanie, geom_geojson, kvartal=None,
                                   vydel=None, lesnichestvo=None, ploshad=None,
                                   raw_json=None):
    """Импорт из QGIS (Этап "Импорт делянок", app/routers/delyanki.py:
    import_delyanka_geometries): один полигон/мультиполигон из
    выгруженного файла → одна новая делянка с одним delyanka_item.

    В отличие от create_delyanka_manual() выше — geom_geojson обязателен
    (собственный контур делянки, не контур выдела из map_vydela.geojson),
    а kvartal/vydel НЕобязательны: слой из QGIS может не нести таких
    атрибутов вообще. Если kvartal/vydel всё же переданы (найдены среди
    атрибутов feature при импорте), таксация подтягивается тем же
    _lookup_taxatsia(), что и в create_delyanka_manual — если нет, поля
    таксации остаются пустыми, их можно дозаполнить в карточке делянки
    вручную позже.

    Сопоставления с уже существующими делянками НЕТ (по явному решению —
    импорт всегда создаёт новые делянки "с нуля", не пытаясь угадать,
    какая существующая делянка соответствует какому полигону).

    geom_geojson — строка с JSON-объектом geometry (не Feature), уже в
    EPSG:4326 (lon/lat) — reprojection делает вызывающий код (роутер) на
    основе CRS исходного файла.

    raw_json — необработанный исходный объект (например, элемент area[]
    из экспорта "Лесной страж", см. app/routers/delyanki.py:
    _import_lesnoy_strazh) сохраняется как есть в mdo_raw_json — то же
    поле, что и для MDO-импорта, просто источник другой; ничего в схеме
    менять не пришлось.

    Возвращает id новой делянки (delyanka.id)."""
    taxatsia = {}
    if kvartal and vydel:
        taxatsia = _lookup_taxatsia(conn, kvartal, vydel, lesnichestvo_hint=lesnichestvo) or {}
    lesnichestvo_final = lesnichestvo or taxatsia.get("lesnichestvo") or ""
    ploshad_final = ploshad if ploshad is not None else taxatsia.get("ploshad")

    cur = conn.execute(
        "INSERT INTO delyanka (nazvanie, status) VALUES (?, 'черновик')",
        (nazvanie,),
    )
    delyanka_id = cur.lastrowid
    conn.execute(
        """INSERT INTO delyanka_item
               (delyanka_id, poryadok, lesnichestvo, kvartal, vydel,
                ploshad, sostav, vozrast, polnota, tip_lesa, bonitet,
                proishozhdenie, kategoriya_lesov, zapas_na_ga, geom_geojson,
                mdo_raw_json)
           VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            delyanka_id, lesnichestvo_final, kvartal, vydel,
            ploshad_final, taxatsia.get("sostav"), taxatsia.get("vozrast"),
            taxatsia.get("polnota"), taxatsia.get("tip_lesa"), taxatsia.get("bonitet"),
            taxatsia.get("proishozhdenie"), taxatsia.get("kategoriya_lesov"),
            taxatsia.get("zapas_na_ga"), geom_geojson, raw_json,
        ),
    )
    conn.commit()
    return delyanka_id


def list_delyanka_geometries(conn, lesnichestvo=None):
    """Собственные контуры делянок (не выделов) для отрисовки на карте —
    только те delyanka_item, у которых geom_geojson заполнен (то есть
    пришли через import-geo). Возвращает список словарей, готовых
    завернуть в FeatureCollection на уровне роутера."""
    q = """SELECT i.id, i.delyanka_id, d.nazvanie, i.status_rabot,
                  i.kvartal, i.vydel, i.lesnichestvo, i.ploshad, i.geom_geojson
           FROM delyanka_item i JOIN delyanka d ON d.id = i.delyanka_id
           WHERE i.geom_geojson IS NOT NULL AND i.geom_geojson != ''"""
    params = ()
    if lesnichestvo:
        q += " AND i.lesnichestvo = ?"
        params = (lesnichestvo,)
    rows = conn.execute(q, params).fetchall()
    cols = ["item_id", "delyanka_id", "nazvanie", "status_rabot",
            "kvartal", "vydel", "lesnichestvo", "ploshad", "geom_geojson"]
    return [dict(zip(cols, r)) for r in rows]


def list_delyanka_items_for_map(conn):
    """Мобильная/веб-карта: облегчённый список 'где уже есть делянка' —
    только kvartal/vydel/lesnichestvo/delyanka_id/nazvanie/status_rabot по
    каждому выделу, без остальных ~30 полей delyanka/delyanka_item (их не
    нужно тащить только чтобы подсветить полигон на карте). Экран карты
    сверяет каждый показанный на карте выдел (num_kv/num_vd из geojson) с
    этим списком по kvartal+vydel и красит найденные совпадения иначе,
    чем свободные выделы — см. GET /api/delyanki/for-map."""
    rows = conn.execute(
        """SELECT i.kvartal, i.vydel, i.lesnichestvo, i.delyanka_id, d.nazvanie, i.status_rabot
           FROM delyanka_item i JOIN delyanka d ON d.id = i.delyanka_id"""
    ).fetchall()
    cols = ["kvartal", "vydel", "lesnichestvo", "delyanka_id", "nazvanie", "status_rabot"]
    return [dict(zip(cols, r)) for r in rows]


def list_delyanki(conn, status=None):
    """status=None (по умолчанию) — все делянки, как раньше (экран
    "Делянки" сам показывает/прячет архив чекбоксом). Передайте
    status="активна", чтобы получить только делянки, прошедшие активацию
    (см. activate_delyanka) — так фильтруют расход и акты освидетельствования,
    куда черновики попадать не должны."""
    q = """SELECT d.id, d.nazvanie, d.status, d.created_at,
                  COUNT(i.id) as n_items,
                  GROUP_CONCAT(DISTINCT i.kategoriya_lesov) as kategorii
           FROM delyanka d LEFT JOIN delyanka_item i ON i.delyanka_id = d.id"""
    params = ()
    if status is not None:
        q += " WHERE d.status = ?"
        params = (status,)
    q += " GROUP BY d.id ORDER BY d.id DESC"
    rows = conn.execute(q, params).fetchall()
    cols = ["id", "nazvanie", "status", "created_at", "n_items", "kategorii"]
    return [dict(zip(cols, r)) for r in rows]


def get_delyanka_full(conn, delyanka_id):
    _ensure_abris_column(conn)
    row = conn.execute("SELECT * FROM delyanka WHERE id=?", (delyanka_id,)).fetchone()
    if not row:
        return None, []
    cols = [d[0] for d in conn.execute("SELECT * FROM delyanka WHERE id=?", (delyanka_id,)).description]
    delyanka = dict(zip(cols, row))
    delyanka["chleny"] = json.loads(delyanka.get("chleny_json") or "[]")
    # Члены комиссии Акта готовности лесосеки (вкладка "Техкарта" в UI) —
    # хранятся в gotovnost_komissiya_json, отдаём под ключом tehkarta_chleny,
    # под которым их ждёт _load_plot_form() в pyside_app.py.
    delyanka["tehkarta_chleny"] = json.loads(delyanka.get("gotovnost_komissiya_json") or "[]")

    item_rows = conn.execute(
        "SELECT * FROM delyanka_item WHERE delyanka_id=? ORDER BY poryadok", (delyanka_id,)
    ).fetchall()
    item_cols = [d[0] for d in conn.execute(
        "SELECT * FROM delyanka_item WHERE delyanka_id=? ORDER BY poryadok", (delyanka_id,)
    ).description]
    items = [dict(zip(item_cols, r)) for r in item_rows]
    return delyanka, items


def update_delyanka_fields(conn, delyanka_id, **fields):
    """Обновляет текстовые поля делянки (прочие поля акта, состав комиссии и т.п.)."""
    if "chleny" in fields:
        fields["chleny_json"] = json.dumps(fields.pop("chleny"), ensure_ascii=False)
    if "gotovnost_komissiya" in fields:
        fields["gotovnost_komissiya_json"] = json.dumps(fields.pop("gotovnost_komissiya"), ensure_ascii=False)
    if "tehkarta_chleny" in fields:
        # Члены комиссии Акта готовности лесосеки (вкладка "Техкарта" в UI) —
        # хранятся в том же столбце, что уже читает generate_tehkarty_for_delyanka()
        # как gotovnost_komissiya, чтобы не заводить дублирующую колонку.
        fields["gotovnost_komissiya_json"] = json.dumps(fields.pop("tehkarta_chleny"), ensure_ascii=False)
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE delyanka SET {set_clause} WHERE id=?", (*fields.values(), delyanka_id))
    conn.commit()


def update_delyanka_item(conn, item_id, **fields):
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE delyanka_item SET {set_clause} WHERE id=?", (*fields.values(), item_id))
    conn.commit()


def delete_delyanka(conn, delyanka_id):
    """Безвозвратно удаляет делянку вместе со всеми выделами и связанными
    с ними данными. В БД нет ON DELETE CASCADE, поэтому чистим вручную
    строго снизу вверх — сначала "листья", потом родителей:

      1. raskhod_pozitsiya — позиции нарядов (Модуль 3 "Учёт заготовки",
         raskhod.py), привязаны к наряду через naryad_id.
      2. raskhod_naryad — сами наряды, привязаны к выделу через item_id.
      3. delyanka_item — сами выделы удаляемой делянки.
      4. delyanka — сама делянка."""
    item_ids = [
        row[0] for row in conn.execute(
            "SELECT id FROM delyanka_item WHERE delyanka_id=?", (delyanka_id,)
        ).fetchall()
    ]

    if item_ids:
        item_placeholders = ", ".join("?" for _ in item_ids)
        naryad_ids = [
            row[0] for row in conn.execute(
                f"SELECT id FROM raskhod_naryad WHERE item_id IN ({item_placeholders})",
                item_ids,
            ).fetchall()
        ]
        if naryad_ids:
            naryad_placeholders = ", ".join("?" for _ in naryad_ids)
            conn.execute(
                f"DELETE FROM raskhod_pozitsiya WHERE naryad_id IN ({naryad_placeholders})",
                naryad_ids,
            )
            conn.execute(
                f"DELETE FROM raskhod_naryad WHERE id IN ({naryad_placeholders})",
                naryad_ids,
            )

    conn.execute("DELETE FROM delyanka_item WHERE delyanka_id=?", (delyanka_id,))
    conn.execute("DELETE FROM delyanka WHERE id=?", (delyanka_id,))
    conn.commit()


def archive_delyanka(conn, delyanka_id):
    """Переводит делянку в статус 'архив'. Данные никуда не пропадают —
    делянка просто перестаёт показываться на главном экране PlotsScreen,
    пока лесничий не включит чекбокс "Показывать архивные"."""
    conn.execute("UPDATE delyanka SET status=? WHERE id=?", ("архив", delyanka_id))
    conn.commit()


def activate_delyanka(conn, delyanka_id, nomer_bileta, data_bileta):
    """Переводит делянку (обычно заведённую импортом МДО, где статус по
    умолчанию 'черновик' — см. DEFAULT в db.py) в статус 'активна'. Только
    делянки в этом статусе участвуют в расходе и других рабочих экранах
    (см. status= фильтр в list_delyanki). Номер/дата лесорубочного билета
    обязательны — это и есть смысл активации: без них делянку нельзя пускать
    в работу. Оба поля заодно используются osvidetelstvovanie_generator.py
    при генерации акта освидетельствования (delyanka.get("nomer_..."))."""
    nomer_bileta = (nomer_bileta or "").strip()
    data_bileta = (data_bileta or "").strip()
    if not nomer_bileta or not data_bileta:
        raise ValueError("Укажите номер и дату лесорубочного билета")
    conn.execute(
        "UPDATE delyanka SET status=?, nomer_lesorubochnogo_bileta=?, data_lesorubochnogo_bileta=? WHERE id=?",
        ("активна", nomer_bileta, data_bileta, delyanka_id),
    )
    conn.commit()


def _ensure_abris_column(conn):
    """abris_image_path хранит путь к PNG абриса, нарисованного во встроенном
    редакторе (abris_tool.html) и переданного через мост QWebChannel в
    pyside_app.py (см. AbrisBridge.receive_image). Добавляется миграцией
    "на лету", чтобы не трогать db.py и не терять данные на уже
    существующих базах."""
    try:
        conn.execute("ALTER TABLE delyanka_item ADD COLUMN abris_image_path TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # колонка уже есть — миграция уже применялась раньше


def save_abris_image(conn, item_id, image_path):
    """Привязывает сохранённый PNG абриса к конкретному выделу делянки
    (delyanka_item.id). Вызывается AbrisBridge из pyside_app.py сразу после
    того, как пользователь нажал "Сохранить в приложение" в abris_tool.html.
    Именно это поле потом читает tehkarta_generator.py как
    item.get("abris_image_path")."""
    _ensure_abris_column(conn)
    update_delyanka_item(conn, item_id, abris_image_path=image_path)


def list_komissiya_presets(conn):
    rows = conn.execute("SELECT * FROM komissiya_preset ORDER BY nazvanie").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM komissiya_preset ORDER BY nazvanie").description]
    presets = [dict(zip(cols, r)) for r in rows]
    for p in presets:
        p["chleny"] = json.loads(p.get("chleny_json") or "[]")
    return presets


def get_komissiya_preset(conn, preset_id):
    row = conn.execute("SELECT * FROM komissiya_preset WHERE id=?", (preset_id,)).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM komissiya_preset WHERE id=?", (preset_id,)).description]
    preset = dict(zip(cols, row))
    preset["chleny"] = json.loads(preset.get("chleny_json") or "[]")
    return preset


def save_komissiya_preset(conn, nazvanie, **fields):
    """Создаёт или обновляет (по названию) сохранённый состав комиссии."""
    if "chleny" in fields:
        fields["chleny_json"] = json.dumps(fields.pop("chleny"), ensure_ascii=False)
    cols = ["nazvanie"] + list(fields.keys())
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields.keys())
    conn.execute(
        f"""INSERT INTO komissiya_preset ({", ".join(cols)}) VALUES ({placeholders})
            ON CONFLICT(nazvanie) DO UPDATE SET {updates}""",
        (nazvanie, *fields.values()),
    )
    conn.commit()


def delete_komissiya_preset(conn, preset_id):
    conn.execute("DELETE FROM komissiya_preset WHERE id=?", (preset_id,))
    conn.commit()


def list_listok_komissiya_presets(conn):
    rows = conn.execute("SELECT * FROM listok_komissiya_preset ORDER BY nazvanie").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM listok_komissiya_preset ORDER BY nazvanie").description]
    return [dict(zip(cols, r)) for r in rows]


def save_listok_komissiya_preset(conn, nazvanie, **fields):
    cols = ["nazvanie"] + list(fields.keys())
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields.keys())
    conn.execute(
        f"""INSERT INTO listok_komissiya_preset ({", ".join(cols)}) VALUES ({placeholders})
            ON CONFLICT(nazvanie) DO UPDATE SET {updates}""",
        (nazvanie, *fields.values()),
    )
    conn.commit()


def delete_listok_komissiya_preset(conn, preset_id):
    conn.execute("DELETE FROM listok_komissiya_preset WHERE id=?", (preset_id,))
    conn.commit()


def list_tehkarta_komissiya_presets(conn):
    rows = conn.execute("SELECT * FROM tehkarta_komissiya_preset ORDER BY nazvanie").fetchall()
    cols = [d[0] for d in conn.execute(
        "SELECT * FROM tehkarta_komissiya_preset ORDER BY nazvanie"
    ).description]
    presets = [dict(zip(cols, r)) for r in rows]
    for p in presets:
        p["tehkarta_chleny"] = json.loads(p.get("tehkarta_chleny_json") or "[]")
    return presets


def save_tehkarta_komissiya_preset(conn, nazvanie, **fields):
    """Создаёт или обновляет (по названию) сохранённый пресет Техкарты
    (составитель / мастер леса / бригадир / члены комиссии Акта готовности)."""
    if "tehkarta_chleny" in fields:
        fields["tehkarta_chleny_json"] = json.dumps(fields.pop("tehkarta_chleny"), ensure_ascii=False)
    cols = ["nazvanie"] + list(fields.keys())
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields.keys())
    conn.execute(
        f"""INSERT INTO tehkarta_komissiya_preset ({", ".join(cols)}) VALUES ({placeholders})
            ON CONFLICT(nazvanie) DO UPDATE SET {updates}""",
        (nazvanie, *fields.values()),
    )
    conn.commit()


def delete_tehkarta_komissiya_preset(conn, preset_id):
    conn.execute("DELETE FROM tehkarta_komissiya_preset WHERE id=?", (preset_id,))
    conn.commit()


def generate_akt_for_delyanka(conn, delyanka_id, templates_dir=None, output_path=None):
    templates_dir = templates_dir or RESOURCE_DIR
    delyanka, items = get_delyanka_full(conn, delyanka_id)
    if not delyanka:
        raise ValueError(f"Делянка {delyanka_id} не найдена")
    if not items:
        raise ValueError("В делянке нет ни одного выдела")
    return akt_generator.generate_akt(delyanka, items, templates_dir=templates_dir, output_path=output_path)


def generate_listki_for_delyanka(conn, delyanka_id, templates_dir=None, output_dir="."):
    """Генерирует листок сигнализации для КАЖДОГО выдела делянки (один
    листок = один выдел, т.к. бланк описывает одно место обнаружения).
    Возвращает список путей к созданным файлам."""
    templates_dir = templates_dir or RESOURCE_DIR
    delyanka, items = get_delyanka_full(conn, delyanka_id)
    if not delyanka:
        raise ValueError(f"Делянка {delyanka_id} не найдена")
    if not items:
        raise ValueError("В делянке нет ни одного выдела")

    extra_fields = {
        "obnaruzhil_data": delyanka.get("listok_obnaruzhil_data", ""),
        "obnaruzhil_dolzhnost": delyanka.get("listok_obnaruzhil_dolzhnost", ""),
        "obnaruzhil_fio": delyanka.get("listok_obnaruzhil_fio", ""),
        "proveril_data": delyanka.get("listok_proveril_data", ""),
        "proveril_dolzhnost": delyanka.get("listok_proveril_dolzhnost") or listok_generator.DEFAULT_PROVERIL_DOLZHNOST,
        "proveril_fio": delyanka.get("listok_proveril_fio", ""),
        "namechaemoe_meropriyatie": delyanka.get("listok_namechaemoe_meropriyatie") or listok_generator.DEFAULT_NAMECHAEMOE_MEROPRIYATIE,
        "reshenie_data": delyanka.get("listok_reshenie_data", ""),
        "reshenie_dolzhnost": delyanka.get("listok_reshenie_dolzhnost", ""),
        "reshenie_fio": delyanka.get("listok_reshenie_fio", ""),
        "zaklyuchenie_text": delyanka.get("listok_zaklyuchenie_text", ""),
    }

    paths = []
    for it in items:
        out_path = os.path.join(
            output_dir, f"Листок_сигнализации_кв{it['kvartal']}_выд{it['vydel']}.xlsx"
        )
        p = listok_generator.generate_listok(
            it, extra_fields=extra_fields, templates_dir=templates_dir, output_path=out_path
        )
        paths.append(p)
    return paths


def _item_with_poroda_volumes(it):
    """Достаёт poroda_volumes/poroda_order из сохранённого сырого МДО (JSON) для данного item."""
    it = dict(it)
    raw = it.get("mdo_raw_json")
    if raw:
        try:
            mdo = json.loads(raw)
            it["poroda_volumes"] = mdo.get("poroda_volumes", {})
            it["poroda_order"] = mdo.get("poroda_order", [])
        except (json.JSONDecodeError, TypeError):
            it["poroda_volumes"] = {}
            it["poroda_order"] = []
    else:
        it["poroda_volumes"] = {}
        it["poroda_order"] = []
    return it


def generate_tehkarty_for_delyanka(conn, delyanka_id, output_dir=".", templates_dir=None):
    templates_dir = templates_dir or RESOURCE_DIR
    """Генерирует технологическую карту (+ акт готовности лесосеки как
    вторую часть того же файла) для КАЖДОГО выдела делянки.
    Возвращает список путей к созданным файлам."""
    delyanka, items = get_delyanka_full(conn, delyanka_id)
    if not delyanka:
        raise ValueError(f"Делянка {delyanka_id} не найдена")
    if not items:
        raise ValueError("В делянке нет ни одного выдела")

    delyanka = dict(delyanka)
    delyanka["gotovnost_komissiya"] = json.loads(delyanka.get("gotovnost_komissiya_json") or "[]")

    paths = []
    for it in items:
        it_full = _item_with_poroda_volumes(it)
        out_path = os.path.join(
            output_dir, f"Техкарта_кв{it['kvartal']}_выд{it['vydel']}.docx"
        )
        p = tehkarta_generator.generate_tehkarta(delyanka, it_full, out_path, templates_dir=templates_dir)
        paths.append(p)
    return paths