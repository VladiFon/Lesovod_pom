# -*- coding: utf-8 -*-
"""Данные для карты мобильного приложения и QGIS-моста (28.09.2026):
раскраска выделов по видам работ отдельно от геометрии, статусы делянок,
поиск по кварталу/выделу/делянке/лесным культурам, история выдела,
метки рабочих и треки обмера.

Логика вынесена сюда, а не в forest_map.py: большая часть не требует
geopandas (цвета, поиск, история — чистый SQL), и роутеры map.py/bot.py
остаются тонкими."""
import json
import re
import sqlite3
from typing import Dict, Iterable, List, Optional

from app import legacy_bridge  # noqa: F401 — обязателен до import config
import config as legacy_config
import webext


# --------------------------------------------------------------------------- #
#   Лесничества: одно и то же лесничество пишут по-разному ("Оршанское",
#   "Оршанское лесничество", "оршанское "). Раньше сравнение шло строго по
#   тексту, и работа с "неправильным" названием не красила карту никогда.
# --------------------------------------------------------------------------- #
def _norm_lesnichestvo(value: Optional[str]) -> str:
    text = (value or "").strip().lower().replace("ё", "е")
    text = re.sub(r"\bлесничеств[оа]\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_lesnichestvo(value: Optional[str]) -> Optional[str]:
    """Название из LCH_MAP (ключ), если value — любое его написание или
    номер лесничества; иначе исходная строка без лишних пробелов."""
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return stripped
    for name, num in legacy_config.LCH_MAP.items():
        if str(num) == stripped:
            return name
    target = _norm_lesnichestvo(stripped)
    for name in legacy_config.LCH_MAP:
        if _norm_lesnichestvo(name) == target:
            return name
    return stripped


def lesnichestvo_name_for_num(lesnichestvo_num: Optional[str]) -> Optional[str]:
    if lesnichestvo_num is None or str(lesnichestvo_num).strip() == "":
        return None
    for name, num in legacy_config.LCH_MAP.items():
        if str(num) == str(lesnichestvo_num).strip():
            return name
    return None


def same_lesnichestvo(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a) and bool(b) and _norm_lesnichestvo(canonical_lesnichestvo(a)) == _norm_lesnichestvo(canonical_lesnichestvo(b))


def norm_id(value) -> str:
    """Тот же принцип, что forest_map._forest_map_norm_id: 140, 140.0 и
    '140' — один и тот же номер."""
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


# --------------------------------------------------------------------------- #
#   Раскраска выделов по видам работ (completed_works)
# --------------------------------------------------------------------------- #
WORK_CATEGORIES = [
    # (ключевое слово в tip_raboty, цвет, подпись) — порядок важен, как в
    # forest_map.FOREST_MAP_WORK_CATEGORIES ("Рубка ухода" — рубка).
    ("руб", "#ff4444", "Рубка"),
    ("осветл", "#ffeb3b", "Уход / осветление"),
    ("уход", "#ffeb3b", "Уход / осветление"),
    ("посад", "#4caf50", "Посадка / дополнение"),
    ("дополн", "#4caf50", "Посадка / дополнение"),
    ("культур", "#4caf50", "Посадка / дополнение"),
]
WORK_DEFAULT = ("#8bc34a", "Прочие работы")


def work_category(types: Iterable[str]):
    combined = " ".join(t or "" for t in types).lower()
    for keyword, color, label in WORK_CATEGORIES:
        if keyword in combined:
            return color, label
    return WORK_DEFAULT


def work_legend() -> List[dict]:
    seen, legend = set(), []
    for _kw, color, label in WORK_CATEGORIES:
        if label not in seen:
            seen.add(label)
            legend.append({"color": color, "label": label})
    legend.append({"color": WORK_DEFAULT[0], "label": WORK_DEFAULT[1]})
    return legend


def load_completed_works(conn, lesnichestvo_name: Optional[str]) -> Dict[tuple, List[dict]]:
    """{(кв, выд): [работы]} — по нормализованному названию лесничества."""
    rows = conn.execute(
        "SELECT kvartal, vydel, tip_raboty, ispolnitel_fio, data_vypolneniya, lesnichestvo, photo_path, id "
        "FROM completed_works WHERE kvartal IS NOT NULL AND vydel IS NOT NULL"
    ).fetchall()
    lookup: Dict[tuple, List[dict]] = {}
    for kvartal, vydel, tip, fio, data_vyp, lesn, photo_path, row_id in rows:
        if lesnichestvo_name and not same_lesnichestvo(lesn, lesnichestvo_name):
            continue
        # в отчётах выделы часто пишут списком "3,4" — красим каждый
        for vd in re.split(r"[,;\s]+", str(vydel)):
            key = (norm_id(kvartal), norm_id(vd))
            if not key[0] or not key[1]:
                continue
            lookup.setdefault(key, []).append({
                "id": row_id,
                "tip_raboty": (tip or "").strip(),
                "ispolnitel_fio": (fio or "").strip(),
                "data_vypolneniya": (data_vyp or "").strip(),
                "photo_path": photo_path,
            })
    return lookup


def work_colors(conn, lesnichestvo_num: str) -> dict:
    name = lesnichestvo_name_for_num(lesnichestvo_num)
    lookup = load_completed_works(conn, name) if name else {}
    items = []
    for (kv, vd), entries in lookup.items():
        types = sorted({e["tip_raboty"] for e in entries if e["tip_raboty"]})
        color, label = work_category(types)
        last = max((e["data_vypolneniya"] for e in entries), default="")
        items.append({"kvartal": kv, "vydel": vd, "color": color, "label": label,
                      "types": types, "last_date": last or None})
    return {"items": items, "legend": work_legend()}


# --------------------------------------------------------------------------- #
#   Статусы делянок
# --------------------------------------------------------------------------- #
STATUS_WAITING = "ожидает"
STATUS_IN_PROGRESS = "в работе"
STATUS_DONE = "выполнено"
DELYANKA_STATUSES = [
    {"status": STATUS_WAITING, "color": "#ff9800", "label": "Ожидает"},
    {"status": STATUS_IN_PROGRESS, "color": "#ffd600", "label": "В работе"},
    {"status": STATUS_DONE, "color": "#43a047", "label": "Выполнено"},
]


def mark_items_in_progress(conn, kvartal: Optional[str], vydels: Iterable[str],
                            lesnichestvo: Optional[str] = None, delyanka_id: Optional[int] = None) -> int:
    """Первая работа на выделе делянки переводит его из 'ожидает' в
    'в работе' ('выполнено' ставит лесничий на сайте — автоматически
    закрывать нельзя, отчёт не значит, что выдел закончен)."""
    kv = norm_id(kvartal)
    vds = {norm_id(v) for v in vydels if norm_id(v)}
    if not kv or not vds:
        return 0
    q = "SELECT id, kvartal, vydel, lesnichestvo FROM delyanka_item WHERE (status_rabot IS NULL OR status_rabot = ?)"
    params: list = [STATUS_WAITING]
    if delyanka_id is not None:
        q += " AND delyanka_id = ?"
        params.append(delyanka_id)
    changed = 0
    for item_id, i_kv, i_vd, i_lesn in conn.execute(q, params).fetchall():
        if norm_id(i_kv) != kv or norm_id(i_vd) not in vds:
            continue
        if lesnichestvo and i_lesn and not same_lesnichestvo(i_lesn, lesnichestvo):
            continue
        conn.execute("UPDATE delyanka_item SET status_rabot = ? WHERE id = ?", (STATUS_IN_PROGRESS, item_id))
        changed += 1
    return changed


# --------------------------------------------------------------------------- #
#   Поиск
# --------------------------------------------------------------------------- #
_KV_VD_PATTERNS = [
    re.compile(r"^\s*(?:кв\.?|квартал)?\s*(\d+)\s*(?:[/\-\s,]+|\s*(?:выд\.?|выдел)\s*)(\d+[а-яa-z]?)\s*$", re.I),
    re.compile(r"^\s*(?:кв\.?|квартал)\s*(\d+)\s*(?:выд\.?|выдел)\s*(\d+[а-яa-z]?)\s*$", re.I),
]
_KV_ONLY = re.compile(r"^\s*(?:кв\.?|квартал)?\s*(\d+)\s*$", re.I)


def parse_kv_vd(q: str):
    for pattern in _KV_VD_PATTERNS:
        m = pattern.match(q)
        if m:
            return m.group(1), m.group(2)
    m = _KV_ONLY.match(q)
    if m:
        return m.group(1), None
    return None, None


def search(conn, q: str, lesnichestvo_num: Optional[str] = None, limit: int = 20) -> List[dict]:
    """Результаты одним списком, у каждого type: kvartal | vydel |
    delyanka | lesokultury. Координаты не считаем — приложение само
    находит квартал в своих данных, а выдел — через
    GET /api/map/delyanka-location."""
    q = (q or "").strip()
    if not q:
        return []
    lesn_name = lesnichestvo_name_for_num(lesnichestvo_num)
    kv, vd = parse_kv_vd(q)
    results: List[dict] = []

    def in_lesn(value):
        return not lesn_name or not value or same_lesnichestvo(value, lesn_name)

    if kv and vd:
        results.append({"type": "vydel", "title": f"Квартал {kv}, выдел {vd}", "kvartal": kv, "vydel": vd,
                        "lesnichestvo": lesn_name})
    elif kv:
        results.append({"type": "kvartal", "title": f"Квартал {kv}", "kvartal": kv, "vydel": None,
                        "lesnichestvo": lesn_name})

    like = f"%{q.lower()}%"
    # Делянки: по названию, номеру билета, кв./выд.
    rows = conn.execute(
        """SELECT d.id, d.nazvanie, d.status, i.kvartal, i.vydel, i.lesnichestvo, i.status_rabot
           FROM delyanka d JOIN delyanka_item i ON i.delyanka_id = d.id
           ORDER BY d.id DESC"""
    ).fetchall()
    for d_id, nazvanie, d_status, i_kv, i_vd, i_lesn, status_rabot in rows:
        if not in_lesn(i_lesn):
            continue
        hit = (nazvanie or "").lower().find(q.lower()) >= 0 if not kv else (
            norm_id(i_kv) == kv and (vd is None or norm_id(i_vd) == vd.lower() or norm_id(i_vd) == vd)
        )
        if not hit:
            continue
        results.append({
            "type": "delyanka",
            "title": nazvanie or f"Делянка №{d_id}",
            "subtitle": f"кв. {norm_id(i_kv)}, выд. {norm_id(i_vd)} · {status_rabot or STATUS_WAITING}",
            "kvartal": norm_id(i_kv), "vydel": norm_id(i_vd), "lesnichestvo": i_lesn,
            "delyanka_id": d_id, "status_rabot": status_rabot or STATUS_WAITING,
        })

    # Лесные культуры: по породе, году, составу, кв./выд.
    rows = conn.execute(
        """SELECT id, kvartal, vydel, lesnichestvo, glavnaya_poroda, god_sozdaniya, sostav_formula, status, ploshad
           FROM lesokultury_uchastok WHERE status IS NULL OR status != 'списан'"""
    ).fetchall()
    for u_id, u_kv, u_vd, u_lesn, poroda, god, sostav, status, ploshad in rows:
        if not in_lesn(u_lesn):
            continue
        if kv:
            hit = (norm_id(u_kv) == kv and (vd is None or norm_id(u_vd) == vd)) or (
                vd is None and norm_id(god) == kv  # "2021" — ещё и год создания л/к
            )
        else:
            hay = " ".join(str(x or "") for x in (poroda, god, sostav, "лесные культуры л/к")).lower()
            hit = q.lower() in hay
        if not hit:
            continue
        results.append({
            "type": "lesokultury",
            "title": f"Л/к: {poroda or 'участок'} {god or ''}".strip(),
            "subtitle": f"кв. {norm_id(u_kv)}, выд. {norm_id(u_vd)}" + (f" · {ploshad} га" if ploshad else ""),
            "kvartal": norm_id(u_kv), "vydel": norm_id(u_vd), "lesnichestvo": u_lesn,
            "uchastok_id": u_id,
        })

    # Одинаковые делянки на нескольких выделах — оставляем по одной строке на кв./выд.
    unique, seen = [], set()
    for r in results:
        key = (r["type"], r.get("delyanka_id") or r.get("uchastok_id"), r["kvartal"], r["vydel"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique[:limit]


# --------------------------------------------------------------------------- #
#   Лесные культуры на карте
# --------------------------------------------------------------------------- #
def _lk_vydely(vd, chasti_json) -> List[str]:
    """Выделы участка: из частей по выделам, иначе из записи «1, 2, 9»."""
    try:
        parts = json.loads(chasti_json) if chasti_json else []
    except (TypeError, ValueError):
        parts = []
    from_parts = [norm_id(p.get("vydel")) for p in parts if isinstance(p, dict) and norm_id(p.get("vydel"))]
    if from_parts:
        return list(dict.fromkeys(from_parts))
    from app.lesokultury_kniga import vydel_tokens

    tokens = [norm_id(t) for t in vydel_tokens(str(vd or "")) if norm_id(t)]
    return tokens or ([norm_id(vd)] if norm_id(vd) else [])


def lesokultury_for_map(conn, lesnichestvo_num: Optional[str]) -> List[dict]:
    """Участки культур по выделам (участок в нескольких выделах — запись на
    каждый). has_kontur — у участка есть свой контур (geometry — только в
    первой его записи): тогда рисуется контур, а не весь выдел."""
    lesn_name = lesnichestvo_name_for_num(lesnichestvo_num)
    rows = conn.execute(
        """SELECT id, kvartal, vydel, lesnichestvo, glavnaya_poroda, god_sozdaniya, ploshad, status, sostav_formula,
                  chasti_json, geom_geojson, vid_kultur, naznachenie_plantatsii, metod_sozdaniya, primechaniya
           FROM lesokultury_uchastok WHERE status IS NULL OR status != 'списан'"""
    ).fetchall()
    from app import vidy

    out = []
    for (u_id, kv, vd, lesn, poroda, god, ploshad, status, sostav, chasti_json, geom,
         vid_kultur, naznachenie, metod, primechaniya) in rows:
        if lesn_name and lesn and not same_lesnichestvo(lesn, lesn_name):
            continue
        vydely = _lk_vydely(vd, chasti_json)
        if not norm_id(kv) or not vydely:
            continue
        try:
            geometry = json.loads(geom) if geom else None
        except (TypeError, ValueError):
            geometry = None
        for i, v in enumerate(vydely):
            item = {"id": u_id, "kvartal": norm_id(kv), "vydel": v, "lesnichestvo": lesn,
                    "glavnaya_poroda": poroda, "god_sozdaniya": god, "ploshad": ploshad,
                    "status": status, "sostav_formula": sostav, "has_kontur": geometry is not None,
                    **vidy.vid_kultur_info(vid_kultur, naznachenie, metod, primechaniya)}
            if i == 0 and geometry is not None:
                item["geometry"] = geometry
            out.append(item)
    return out


# --------------------------------------------------------------------------- #
#   История выдела — для карточки на карте
# --------------------------------------------------------------------------- #
def vydel_history(conn, lesnichestvo_num: Optional[str], kvartal: str, vydel: str) -> dict:
    lesn_name = lesnichestvo_name_for_num(lesnichestvo_num)
    kv, vd = norm_id(kvartal), norm_id(vydel)
    works = load_completed_works(conn, lesn_name).get((kv, vd), [])
    works = sorted(works, key=lambda e: e["data_vypolneniya"] or "", reverse=True)
    for w in works:
        w["has_photo"] = bool(w.pop("photo_path", None))

    lesokultury = [{k: v for k, v in u.items() if k != "geometry"}
                   for u in lesokultury_for_map(conn, lesnichestvo_num) if u["kvartal"] == kv and u["vydel"] == vd]
    meropriyatiya = []
    for u in lesokultury:
        for tip, data, prizh in conn.execute(
            "SELECT tip, data, prizhivaemost_pct FROM lesokultury_meropriyatiya WHERE uchastok_id=? ORDER BY data DESC",
            (u["id"],),
        ).fetchall():
            meropriyatiya.append({"uchastok_id": u["id"], "tip": tip, "data": data, "prizhivaemost_pct": prizh})

    delyanki = []
    for d_id, nazvanie, i_lesn, status_rabot, i_kv, i_vd in conn.execute(
        """SELECT d.id, d.nazvanie, i.lesnichestvo, i.status_rabot, i.kvartal, i.vydel
           FROM delyanka_item i JOIN delyanka d ON d.id = i.delyanka_id"""
    ).fetchall():
        if norm_id(i_kv) != kv or norm_id(i_vd) != vd:
            continue
        if lesn_name and i_lesn and not same_lesnichestvo(i_lesn, lesn_name):
            continue
        delyanki.append({"delyanka_id": d_id, "nazvanie": nazvanie, "status_rabot": status_rabot or STATUS_WAITING})

    return {"kvartal": kv, "vydel": vd, "works": works, "lesokultury": lesokultury,
            "meropriyatiya": meropriyatiya, "delyanki": delyanki}


# --------------------------------------------------------------------------- #
#   Метки рабочих (geo_notes)
# --------------------------------------------------------------------------- #
GEO_NOTE_CATEGORIES = [
    # код — то, что хранится в geo_notes.kategoriya; цвет — один и тот же
    # в приложении и в QGIS-стиле плагина.
    {"code": "zametka", "label": "Заметка", "color": "#df964e"},
    {"code": "vetroval", "label": "Ветровал / бурелом", "color": "#8d6e63"},
    {"code": "pozhar", "label": "Пожар / гарь", "color": "#e53935"},
    {"code": "samovolnaya_rubka", "label": "Самовольная рубка", "color": "#8e24aa"},
    {"code": "vrediteli", "label": "Вредители / болезни", "color": "#fb8c00"},
    {"code": "doroga", "label": "Плохая дорога / проезд", "color": "#546e7a"},
    {"code": "sklad", "label": "Склад / штабель", "color": "#1e88e5"},
    {"code": "granica", "label": "Граница / столб", "color": "#00897b"},
]
GEO_NOTE_CODES = {c["code"] for c in GEO_NOTE_CATEGORIES}


def author_fio_map(conn) -> Dict[str, str]:
    """telegram_id -> ФИО. Старые метки из Telegram-бота — через
    lesorub_directory (viber_id = telegram_id), метки из приложения
    ('app:<id>') — через sotrudniki."""
    fios = {}
    for viber_id, fio in conn.execute("SELECT viber_id, fio FROM lesorub_directory").fetchall():
        if viber_id and fio:
            fios[str(viber_id)] = fio
    try:
        for s_id, fio in conn.execute("SELECT id, fio FROM sotrudniki").fetchall():
            fios.setdefault(f"app:{s_id}", fio)
    except sqlite3.OperationalError:
        pass
    return fios


def list_geo_notes(conn, telegram_id: Optional[str] = None, sotrudnik_id: Optional[int] = None) -> List[dict]:
    """Метки для карты. telegram_id — только свои; sotrudnik_id — плюс
    чужие, которые этому сотруднику отправили и он их принял (у таких
    shared_from_fio/share_id заполнены: в приложении «Убрать с карты»
    вместо «Удалить»)."""
    q = ("SELECT id, telegram_id, lat, lon, note_text, photo_path, created_at, kategoriya "
         "FROM geo_notes WHERE lat IS NOT NULL AND lon IS NOT NULL")
    params: tuple = ()
    if telegram_id is not None:
        q += " AND telegram_id = ?"
        params = (telegram_id,)
    q += " ORDER BY id DESC"
    fios = author_fio_map(conn)
    out = []
    for note_id, tg, lat, lon, text, photo, created, kat in conn.execute(q, params).fetchall():
        out.append(_geo_note_dict(note_id, tg, lat, lon, text, photo, created, kat, fios))
    if telegram_id is not None and sotrudnik_id is not None:
        for share_id, from_fio, row in _accepted_shares(conn, sotrudnik_id, own=telegram_id):
            note = _geo_note_dict(*row, fios)
            note.update(share_id=share_id, shared_from_fio=from_fio)
            out.append(note)
    return out


def _geo_note_dict(note_id, tg, lat, lon, text, photo, created, kat, fios) -> dict:
    kat = kat if kat in GEO_NOTE_CODES else "zametka"
    return {"id": note_id, "telegram_id": tg, "lat": lat, "lon": lon, "note_text": text,
            "has_photo": bool(photo), "created_at": created, "kategoriya": kat,
            "author_fio": fios.get(str(tg)) if tg else None}


# --------------------------------------------------------------------------- #
#   Отправка меток другим сотрудникам (05.10.2026)
# --------------------------------------------------------------------------- #
# Метка остаётся одна (у автора), получателю создаётся «приглашение»:
# ожидает -> принята (метка появляется у него на карте) / отклонена.
# Автор удалил метку — исчезает и у получателей (ON DELETE CASCADE и явное
# удаление в delete_geo_note — в SQLite внешние ключи не всегда включены).
GEO_NOTE_SHARES_SCHEMA = """
CREATE TABLE IF NOT EXISTS geo_note_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER NOT NULL REFERENCES geo_notes(id) ON DELETE CASCADE,
    from_telegram_id TEXT,
    from_fio TEXT,
    to_sotrudnik_id INTEGER NOT NULL REFERENCES sotrudniki(id),
    komment TEXT,
    status TEXT NOT NULL DEFAULT 'ozhidaet',
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    otvet_at TEXT,
    UNIQUE (note_id, to_sotrudnik_id)
);
CREATE INDEX IF NOT EXISTS idx_geo_note_shares_to ON geo_note_shares(to_sotrudnik_id, status);
"""
SHARE_WAITING, SHARE_ACCEPTED, SHARE_DECLINED = "ozhidaet", "prinyata", "otklonena"

_NOTE_COLS = "n.id, n.telegram_id, n.lat, n.lon, n.note_text, n.photo_path, n.created_at, n.kategoriya"


def _accepted_shares(conn, sotrudnik_id: int, own: Optional[str] = None):
    rows = conn.execute(
        f"""SELECT s.id, s.from_fio, {_NOTE_COLS} FROM geo_note_shares s JOIN geo_notes n ON n.id = s.note_id
            WHERE s.to_sotrudnik_id = ? AND s.status = ? AND n.lat IS NOT NULL AND n.lon IS NOT NULL
            ORDER BY s.id DESC""",
        (sotrudnik_id, SHARE_ACCEPTED),
    ).fetchall()
    for r in rows:
        if own is not None and r[3] == own:
            continue  # своя метка, вернувшаяся по пересылке, — уже есть среди своих
        yield r[0], r[1], r[2:]


def coworkers(conn, except_sotrudnik_id: Optional[int] = None) -> List[dict]:
    """Кому можно отправить метку: все активные сотрудники с входом в приложение."""
    webext.apply_uvolneniya(conn)
    return [
        {"id": r[0], "fio": r[1], "dolzhnost": r[2], "uchastok": r[3]}
        for r in conn.execute(
            "SELECT id, fio, dolzhnost, uchastok FROM sotrudniki WHERE is_active = 1 ORDER BY fio"
        ).fetchall()
        if r[0] != except_sotrudnik_id
    ]


def share_geo_note(conn, note_id: int, from_telegram_id: Optional[str], from_fio: Optional[str],
                   to_ids: List[int], komment: Optional[str] = None) -> List[dict]:
    """Создаёт приглашения; повторная отправка тому же — снова «ожидает»
    (если он раньше отклонил или убрал метку). Возвращает
    [{"share_id", "to_sotrudnik_id", "fio", "novoe"}] — novoe=False, если
    метка у него уже принята (уведомлять не нужно)."""
    komment = (komment or "").strip()[:300] or None
    active = {r[0]: r[1] for r in conn.execute("SELECT id, fio FROM sotrudniki WHERE is_active = 1").fetchall()}
    out = []
    for to_id in dict.fromkeys(to_ids):
        if to_id not in active:
            raise ValueError(f"Сотрудник id={to_id} не найден или отключён")
        row = conn.execute("SELECT id, status FROM geo_note_shares WHERE note_id = ? AND to_sotrudnik_id = ?",
                           (note_id, to_id)).fetchone()
        if row and row[1] == SHARE_ACCEPTED:
            out.append({"share_id": row[0], "to_sotrudnik_id": to_id, "fio": active[to_id], "novoe": False})
            continue
        if row:
            conn.execute("UPDATE geo_note_shares SET status = ?, from_telegram_id = ?, from_fio = ?, komment = ?, "
                         "created_at = datetime('now', 'localtime'), otvet_at = NULL WHERE id = ?",
                         (SHARE_WAITING, from_telegram_id, from_fio, komment, row[0]))
            share_id = row[0]
        else:
            share_id = conn.execute(
                "INSERT INTO geo_note_shares (note_id, from_telegram_id, from_fio, to_sotrudnik_id, komment) "
                "VALUES (?, ?, ?, ?, ?)",
                (note_id, from_telegram_id, from_fio, to_id, komment),
            ).lastrowid
        out.append({"share_id": share_id, "to_sotrudnik_id": to_id, "fio": active[to_id], "novoe": True})
    conn.commit()
    return out


def incoming_shares(conn, sotrudnik_id: int, status: Optional[str] = SHARE_WAITING) -> List[dict]:
    q = (f"SELECT s.id, s.from_fio, s.komment, s.status, s.created_at, {_NOTE_COLS} "
         "FROM geo_note_shares s JOIN geo_notes n ON n.id = s.note_id WHERE s.to_sotrudnik_id = ?")
    params: list = [sotrudnik_id]
    if status:
        q += " AND s.status = ?"
        params.append(status)
    fios = author_fio_map(conn)
    out = []
    for share_id, from_fio, komment, st, created, *note in conn.execute(q + " ORDER BY s.id DESC", params).fetchall():
        out.append({"share_id": share_id, "from_fio": from_fio, "komment": komment, "status": st,
                    "shared_at": created, "note": _geo_note_dict(*note, fios)})
    return out


def answer_share(conn, share_id: int, sotrudnik_id: int, accept: bool) -> Optional[dict]:
    """Принять / отклонить (или убрать уже принятую с карты). None — нет
    такого приглашения у этого сотрудника."""
    row = conn.execute("SELECT note_id FROM geo_note_shares WHERE id = ? AND to_sotrudnik_id = ?",
                       (share_id, sotrudnik_id)).fetchone()
    if row is None:
        return None
    status = SHARE_ACCEPTED if accept else SHARE_DECLINED
    conn.execute("UPDATE geo_note_shares SET status = ?, otvet_at = datetime('now', 'localtime') WHERE id = ?",
                 (status, share_id))
    conn.commit()
    return {"share_id": share_id, "note_id": row[0], "status": status}


def share_visible_to(conn, note_id: int, sotrudnik_id: Optional[int]) -> bool:
    """Отправленная этому сотруднику метка (ожидает или принята) — можно смотреть фото."""
    if sotrudnik_id is None:
        return False
    return conn.execute(
        "SELECT 1 FROM geo_note_shares WHERE note_id = ? AND to_sotrudnik_id = ? AND status IN (?, ?)",
        (note_id, sotrudnik_id, SHARE_WAITING, SHARE_ACCEPTED),
    ).fetchone() is not None


def geo_note_photo_path(conn, note_id: int) -> Optional[tuple]:
    row = conn.execute("SELECT telegram_id, photo_path FROM geo_notes WHERE id=?", (note_id,)).fetchone()
    return row


# --------------------------------------------------------------------------- #
#   Треки обмера (обход по границе с GPS)
# --------------------------------------------------------------------------- #
TRACKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS mobile_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id TEXT,
    nazvanie TEXT,
    kvartal TEXT,
    vydel TEXT,
    lesnichestvo TEXT,
    ploshad_ga REAL,
    perimetr_m REAL,
    geom_geojson TEXT NOT NULL,
    note_text TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""


def ensure_schema(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(geo_notes)").fetchall()}
    if cols and "kategoriya" not in cols:
        conn.execute("ALTER TABLE geo_notes ADD COLUMN kategoriya TEXT")
    conn.executescript(TRACKS_SCHEMA)
    conn.executescript(GEO_NOTE_SHARES_SCHEMA)
    conn.commit()


def list_tracks(conn, telegram_id: Optional[str] = None) -> List[dict]:
    q = ("SELECT id, telegram_id, nazvanie, kvartal, vydel, lesnichestvo, ploshad_ga, perimetr_m, "
         "geom_geojson, note_text, created_at FROM mobile_tracks")
    params: tuple = ()
    if telegram_id is not None:
        q += " WHERE telegram_id = ?"
        params = (telegram_id,)
    q += " ORDER BY id DESC"
    fios = author_fio_map(conn)
    out = []
    for row in conn.execute(q, params).fetchall():
        (t_id, tg, nazvanie, kv, vd, lesn, ga, perim, geom, note, created) = row
        try:
            geometry = json.loads(geom)
        except (TypeError, ValueError):
            continue
        out.append({"id": t_id, "nazvanie": nazvanie, "kvartal": kv, "vydel": vd, "lesnichestvo": lesn,
                    "ploshad_ga": ga, "perimetr_m": perim, "geometry": geometry, "note_text": note,
                    "created_at": created, "author_fio": fios.get(str(tg)) if tg else None})
    return out
