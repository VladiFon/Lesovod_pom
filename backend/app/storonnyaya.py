# -*- coding: utf-8 -*-
"""Сторонняя заготовка — общий признак делянки для всех экранов.

Делянка, документы на которую оформляет наш лесхоз, а рубит другая
организация (лесхоз, лесопункт). Раньше признак знала только Инспекция,
а Расход, Распределение бригад, дашборд и телефон считали такую делянку
нашей (анализ 03.11.2026). Теперь все они спрашивают этот модуль.

Кто пишет наряды на такую делянку (решение Влада 03.11.2026):
- "my"          — наряды заводим мы на сайте;
- "zagotovitel" — наряды пишет сам заготовитель (не в нашей программе).
На телефоне (и в табеле) сторонняя делянка видна только в первом случае:
там наряды пишет наш мастер (уточнение Влада 03.11.2026 06:47).

Факт для акта и % освоения: справка заготовителя, если в ней есть объёмы;
иначе — наряды, как у обычной делянки.

Хранится в delyanka.zagotovka_storonnyaya (0/1) и delyanka.storonnyaya_json
(столбцы добавляются здесь, схему legacy db.py не трогаем)."""
import json
from typing import Dict, Iterable, Optional

SORTIMENTY = ("KR", "SR", "ML", "DROVA", "HVOROST")
NARYADY_MY = "my"
NARYADY_ZAGOTOVITEL = "zagotovitel"
NARYADY = (NARYADY_MY, NARYADY_ZAGOTOVITEL)


def ensure_columns(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(delyanka)").fetchall()}
    changed = False
    for c, typ in (("zagotovka_storonnyaya", "INTEGER DEFAULT 0"), ("storonnyaya_json", "TEXT")):
        if c not in cols:
            conn.execute(f"ALTER TABLE delyanka ADD COLUMN {c} {typ}")
            changed = True
    if changed:
        conn.commit()


def num(v) -> float:
    try:
        return float(str(v).replace(",", ".").strip()) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _parse(js) -> dict:
    try:
        data = json.loads(js or "{}")
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if data.get("naryady") not in NARYADY:
        data["naryady"] = NARYADY_MY
    return data


def load(conn, ids: Optional[Iterable[int]] = None) -> Dict[int, dict]:
    """{delyanka_id: данные} только для делянок со сторонней заготовкой.
    ids=None — по всем делянкам."""
    ensure_columns(conn)
    if ids is None:
        rows = conn.execute(
            "SELECT id, storonnyaya_json FROM delyanka WHERE zagotovka_storonnyaya = 1").fetchall()
    else:
        ids = list(ids)
        if not ids:
            return {}
        out = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join("?" * len(chunk))
            for did, js in conn.execute(
                f"SELECT id, storonnyaya_json FROM delyanka WHERE id IN ({ph}) AND zagotovka_storonnyaya = 1",
                chunk,
            ).fetchall():
                out[did] = _parse(js)
        return out
    return {did: _parse(js) for did, js in rows}


def est_spravka(st: Optional[dict]) -> bool:
    """В справке заготовителя есть хоть один объём."""
    return bool(st) and any(num((st.get("fakt") or {}).get(k)) for k in SORTIMENTY)


def naryady_pishet_zagotovitel(st: Optional[dict]) -> bool:
    return bool(st) and st.get("naryady") == NARYADY_ZAGOTOVITEL


def vidna_nashim(st: Optional[dict]) -> bool:
    """Показывать ли делянку нашим людям (телефон, табель): своя — да,
    сторонняя — только если наряды по ней пишем мы."""
    return st is None or st.get("naryady") != NARYADY_ZAGOTOVITEL


def zagotovitel(st: Optional[dict]) -> str:
    return ((st or {}).get("zagotovitel") or "").strip() or "сторонняя организация"


def kratko(st: Optional[dict]) -> Optional[dict]:
    """Короткая сводка для списков (сайт, телефон): None — делянка наша."""
    if st is None:
        return None
    return {
        "zagotovitel": zagotovitel(st),
        "naryady": st.get("naryady") or NARYADY_MY,
        "est_spravka": est_spravka(st),
    }


def podpis(st: Optional[dict]) -> str:
    """« (рубит …)» для текстов уведомлений; пусто для своей делянки."""
    return f" (рубит {zagotovitel(st)})" if st is not None else ""
