# -*- coding: utf-8 -*-
"""Данные участка лесных культур для пробы рубок ухода.

Экран «Рубки ухода» ищет участок по кварталу/выделу в таксации, а участки
лесных культур живут отдельно (lesokultury_uchastok). Здесь — связка: по
кварталу/выделу пробы находим участки культур на этом выделе и собираем
из них то, что нужно шапке ведомости (состав, полнота, возраст, площадь),
с пометкой, откуда взято каждое значение.

Выдел участка культур сравнивается по всем местам, где он может быть
записан: vydel (в книге бывает «19,20,23»), старый выдел, подвыдел и части
участка по выделам (chasti_json). Списанные участки не предлагаются.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.lesokultury_kniga import vydel_tokens

TIP_PEREVOD = "Перевод в покрытые лесом земли"
STATUS_SPISAN = "списан"

# Поля шапки ведомости пробы, которые можно подтянуть из культур.
POLYA_FORMY = ("lesnichestvo", "sostav", "polnota", "vozrast", "ploshad_lesoseki")


def _s(value) -> str:
    return str(value or "").strip()


def _num(value) -> Optional[float]:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _god(text) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", str(text or ""))
    return int(m.group(0)) if m else None


def _chasti(raw) -> List[dict]:
    try:
        parts = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [p for p in parts if isinstance(p, dict)] if isinstance(parts, list) else []


def _norm_vydel(value) -> str:
    """«26» и «26.0» (Excel) — один выдел."""
    text = _s(value)
    return text[:-2] if text.endswith(".0") else text


def vydely_uchastka(u: dict) -> set:
    """Все выделы, в которые заходит участок культур."""
    out = set(vydel_tokens(_s(u.get("vydel"))))
    out |= set(vydel_tokens(_s(u.get("vydel_staryy"))))
    if _s(u.get("podvydel")):
        out.add(_s(u.get("podvydel")))
    for p in _chasti(u.get("chasti_json")):
        for key in ("vydel", "podvydel"):
            if _s(p.get(key)):
                out.add(_s(p.get(key)))
    return {_norm_vydel(v) for v in out if v}


def _lesn_match(target: str, own) -> bool:
    from app.tekushchie_izmeneniya import _lesn_match as match, _norm, resolve_lesnichestvo
    return match(_norm(resolve_lesnichestvo(target)), own)


def _uchastki(conn) -> List[dict]:
    cur = conn.execute("SELECT * FROM lesokultury_uchastok")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _meropriyatiya(conn, ids: List[int]) -> Dict[int, List[dict]]:
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    out: Dict[int, List[dict]] = {}
    for uid, tip, data, prizh, kol, sostav, dannye, created in conn.execute(
        "SELECT uchastok_id, tip, data, prizhivaemost_pct, kolichestvo_na_ga, sostav_fakt, dannye_json, created_at "
        f"FROM lesokultury_meropriyatiya WHERE uchastok_id IN ({marks}) ORDER BY id DESC",
        ids,
    ).fetchall():
        try:
            parsed = json.loads(dannye) if dannye else {}
        except (TypeError, ValueError):
            parsed = {}
        out.setdefault(uid, []).append({
            "tip": tip or "", "data": data or "", "prizhivaemost_pct": prizh,
            "kolichestvo_na_ga": kol, "sostav_fakt": sostav or "",
            "dannye": parsed if isinstance(parsed, dict) else {}, "created_at": created or "",
        })
    return out


def _ploshad_na_vydele(u: dict, vydel: str) -> Optional[float]:
    """Площадь участка культур на этом выделе: часть по chasti_json, если
    участок разбит по выделам, иначе вся площадь участка."""
    vydel = _norm_vydel(vydel)
    if vydel:
        for p in _chasti(u.get("chasti_json")):
            if vydel in (_norm_vydel(p.get("vydel")), _norm_vydel(p.get("podvydel"))) and _num(p.get("ploshad")):
                return _num(p.get("ploshad"))
    return _num(u.get("ploshad"))


def svodka(u: dict, mer: List[dict], vydel: str = "", god: Optional[int] = None) -> dict:
    """Что известно о культурах участка — для карточки на экране пробы.
    istochniki: поле -> откуда значение (чтобы человек видел, чему верить)."""
    god = god or datetime.now().year
    istochniki: Dict[str, str] = {}

    perevod = next((m for m in mer if m["tip"] == TIP_PEREVOD), None)
    taks = (perevod or {}).get("dannye", {}).get("taksatsiya") or {}
    inv = next((m for m in mer if "нвентаризац" in m["tip"]), None)
    uhod = next((m for m in mer if "уход" in m["tip"].lower()), None)

    perevod_god = _god((perevod or {}).get("data")) or _god((perevod or {}).get("created_at"))
    perevod_label = f"перевод {perevod_god} г." if perevod_god else "перевод"
    if taks.get("nomer_kartochki"):
        perevod_label += f", карточка №{taks['nomer_kartochki']}"

    sostav = _s(taks.get("sostav"))
    if sostav:
        istochniki["sostav"] = perevod_label
    elif inv and _s(inv["sostav_fakt"]):
        sostav = _s(inv["sostav_fakt"])
        istochniki["sostav"] = f"{inv['tip'].lower()} {inv['data']}".strip()
    elif _s(u.get("sostav_formula")):
        sostav = _s(u.get("sostav_formula"))
        istochniki["sostav"] = "состав культур при создании"

    polnota = _num(taks.get("polnota"))
    if polnota is not None:
        istochniki["polnota"] = perevod_label

    god_sozdaniya = _god(u.get("god_sozdaniya"))
    vozrast = None
    if _num(taks.get("vozrast")) is not None and perevod_god:
        vozrast = int(_num(taks["vozrast"])) + max(god - perevod_god, 0)
        istochniki["vozrast"] = f"{perevod_label} + {max(god - perevod_god, 0)} г."
    elif god_sozdaniya:
        vozrast = max(god - god_sozdaniya, 0)
        istochniki["vozrast"] = f"по году создания культур ({god_sozdaniya})"

    ploshad = _ploshad_na_vydele(u, vydel)
    if ploshad is not None:
        chasti = _chasti(u.get("chasti_json"))
        istochniki["ploshad"] = (f"часть участка на выделе {vydel}" if len(chasti) > 1 and vydel
                                 else "площадь участка культур")

    return {
        "id": u["id"],
        "lesnichestvo": _s(u.get("lesnichestvo")),
        "kvartal": _s(u.get("kvartal")),
        "vydel": _s(u.get("vydel")),
        "status": _s(u.get("status")) or "активен",
        "god_sozdaniya": _s(u.get("god_sozdaniya")),
        "metod_sozdaniya": _s(u.get("metod_sozdaniya")),
        "glavnaya_poroda": _s(u.get("glavnaya_poroda")),
        "sostav": sostav,
        "polnota": polnota,
        "vozrast": vozrast,
        "vysota": _num(taks.get("vysota")),
        "ploshad": ploshad,
        "ploshad_uchastka": _num(u.get("ploshad")),
        "gustota_posadki": _num(u.get("gustota_posadki")),
        "kolichestvo_na_ga": _num((inv or {}).get("kolichestvo_na_ga")),
        "prizhivaemost_pct": _num((inv or {}).get("prizhivaemost_pct")),
        "posledn_inventarizatsiya": f"{inv['tip']} {inv['data']}".strip() if inv else "",
        "posledn_uhod": f"{uhod['tip']} {uhod['data']}".strip() if uhod else "",
        "istochniki": istochniki,
    }


def podskazka(s: dict) -> Dict[str, Any]:
    """Значения для шапки ведомости пробы из сводки участка (только то,
    что известно)."""
    out = {
        "lesnichestvo": s.get("lesnichestvo") or None,
        "sostav": s.get("sostav") or None,
        "polnota": s.get("polnota"),
        "vozrast": s.get("vozrast"),
        "ploshad_lesoseki": s.get("ploshad"),
    }
    return {k: v for k, v in out.items() if v not in (None, "")}


def naiti(conn, kvartal: str, vydel: str = "", lesnichestvo: str = "",
          ids: Optional[List[int]] = None, god: Optional[int] = None) -> List[dict]:
    """Участки культур на квартале/выделе (или по списку id) со сводкой и
    подсказкой для формы. Сначала активные, потом переведённые;
    списанные — только если запрошены по id."""
    kvartal, vydel = _s(kvartal), _norm_vydel(vydel)
    try:
        uchastki = _uchastki(conn)
    except Exception:  # noqa: BLE001 — таблицы ещё нет
        return []
    if ids:
        wanted = set(ids)
        found = [u for u in uchastki if u["id"] in wanted]
    else:
        if not kvartal:
            return []
        found = [
            u for u in uchastki
            if _s(u.get("kvartal")) == kvartal
            and _s(u.get("status")) != STATUS_SPISAN
            and (not vydel or vydel in vydely_uchastka(u))
            and (not lesnichestvo or _lesn_match(lesnichestvo, u.get("lesnichestvo")))
        ]
    found.sort(key=lambda u: (_s(u.get("status")) not in ("", "активен"), -u["id"]))
    mer = _meropriyatiya(conn, [u["id"] for u in found])
    out = []
    for u in found:
        s = svodka(u, mer.get(u["id"], []), vydel or _s(u.get("vydel")), god)
        s["podskazka"] = podskazka(s)
        s["na_vydele"] = bool(vydel) and vydel in vydely_uchastka(u)
        out.append(s)
    return out


def zapolnit_pustye(conn, form: dict, kvartal: str, vydel: str, ids: List[int],
                    god: Optional[int] = None) -> dict:
    """Дописывает в пустые поля шапки пробы данные культур (для проб с
    телефона: там шапку не заполняют). Берётся первый участок, чей выдел
    совпадает с выделом пробы, иначе первый из выбранных. Возвращает
    form с ключом iz_lesokultur {поле: значение, uchastok_id} — что
    подставлено автоматически."""
    if not ids:
        return form
    found = naiti(conn, kvartal, vydel, ids=ids, god=god)
    if not found:
        return form
    best = next((s for s in found if s["na_vydele"]), found[0])
    pod = best["podskazka"]
    iz = dict(form.get("iz_lesokultur") or {})
    for key in POLYA_FORMY:
        if key in pod and form.get(key) in (None, ""):
            form[key] = pod[key]
            iz[key] = pod[key]
    if iz:
        iz["uchastok_id"] = best["id"]
        form["iz_lesokultur"] = iz
    return form
