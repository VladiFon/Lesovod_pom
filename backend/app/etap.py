# -*- coding: utf-8 -*-
"""Этап делянки — один бейдж для всех списков сайта (шаг 4 разбора 03.11.2026).

В базе у делянки три статуса (черновик / активна / архив), а жизнь у неё
длиннее. Этап считается из того, что уже есть:

    chernovik  Черновик            — импорт МДО, билета ещё нет
    v_rabote   В работе            — активна, площадь по нарядам не пройдена
    dorublena  Дорублена           — площадь пройдена (наряды или справка
                                     заготовителя), акта ещё нет
    osvid      Освидетельствована  — есть акт, но делянка ещё не закрыта
    zakryta    Закрыта             — архив

«Дорублена» — тот же расчёт, что в Инспекции (_ploshad_po_naryadam), чтобы
бейдж и срок акта в Инспекции не расходились."""
from typing import Dict, Iterable, Optional

ETAPY = {
    "chernovik": "Черновик",
    "v_rabote": "В работе",
    "dorublena": "Дорублена",
    "osvid": "Освидетельствована",
    "zakryta": "Закрыта",
}


def etapy(conn, delyanki: Iterable[dict]) -> Dict[int, dict]:
    """{id: {"kod", "label", "ploshad_zakryta", "akt_do"}} для делянок
    (нужны поля id и status)."""
    from app import storonnyaya
    from app.routers import inspection
    import db as legacy_db
    import raskhod_v2

    delyanki = list(delyanki)
    out: Dict[int, dict] = {}
    aktivnye = [d for d in delyanki if d.get("status") == "активна"]
    ids = [d["id"] for d in aktivnye]
    acts = legacy_db.list_osvidetelstvovanie_acts_batch(conn, ids) if ids else {}
    ploshadi = {}
    if ids:
        st = storonnyaya.load(conn, ids)
        zamena = {did: [(inspection._parse_date((s.get("spravka_data") or "").strip()),
                         storonnyaya.num(s.get("ploshad_fakt")))]
                  for did, s in st.items() if storonnyaya.num(s.get("ploshad_fakt"))}
        ploshadi = inspection._ploshad_po_naryadam(
            conn, aktivnye, raskhod_v2.get_delyanka_items_batch(conn, ids), acts, zamena)
    for d in delyanki:
        status = d.get("status")
        pl = ploshadi.get(d["id"]) or {}
        if status == "черновик":
            kod = "chernovik"
        elif status == "архив":
            kod = "zakryta"
        elif acts.get(d["id"]):
            kod = "osvid"
        elif pl.get("ploshad_zakryta"):
            kod = "dorublena"
        else:
            kod = "v_rabote"
        out[d["id"]] = {
            "kod": kod,
            "label": ETAPY[kod],
            "ploshad_zakryta": pl.get("ploshad_zakryta"),
            "akt_do": pl.get("akt_po_ploshadi_do") if kod == "dorublena" else None,
        }
    return out


def odna(conn, delyanka_id: int) -> Optional[dict]:
    row = conn.execute("SELECT id, status FROM delyanka WHERE id=?", (delyanka_id,)).fetchone()
    if not row:
        return None
    return etapy(conn, [{"id": row[0], "status": row[1]}]).get(row[0])
