# -*- coding: utf-8 -*-
"""
УСТАРЕЛО, оставлено только для истории/отката — больше нигде не
импортируется.

Изначально это был приблизительный агрегатор поверх корневого raskhod.py
(на момент написания screens/raskhod/balance.py не был доступен). Теперь,
когда реальный screens/raskhod/balance.py перенесён в
legacy/raskhod_v2.py, роутеры (app/routers/inspection.py,
app/routers/raskhod.py) используют настоящие
raskhod_v2.compute_sortiment_totals_multi/compute_sortiment_limit_fakt_totals
вместо этого файла. Можно удалить, если не нужен как референс.
"""
import raskhod  # noqa: E402 — доступен через app.legacy_bridge (см. вызывающие роутеры)

SORTIMENTS = ("KR", "SR", "ML", "DROVA", "HVOROST")


def compute_sortiment_totals_multi(conn, items):
    """Для spravka_generator.generate_spravka(): {порода: {KR,SR,ML,DROVA,HVOROST}}
    — суммарный ФАКТ (наряды) по всем item'ам делянки, порода —
    canonical_poroda() (единый ключ МДО/ЕГАИС)."""
    totals: dict[str, dict[str, float]] = {}
    for item in items:
        naryady = raskhod.list_naryady(conn, item["id"])
        for naryad in naryady:
            for pos in naryad.get("pozitsii", []):
                poroda = raskhod.canonical_poroda(pos.get("poroda"))
                sortiment = pos.get("sortiment")
                obyom = pos.get("obyom") or 0
                if not poroda or sortiment not in SORTIMENTS:
                    continue
                bucket = totals.setdefault(poroda, {s: 0.0 for s in SORTIMENTS})
                bucket[sortiment] += float(obyom)
    return totals


def compute_sortiment_limit_fakt_totals(conn, items):
    """Для osvidetelstvovanie_generator.generate_akt_osvidetelstvovaniya():
    {"KR": {"limit":, "fakt":}, "SR": {...}, "ML": {...}, "DROVA": {...}}
    — суммарный лимит (из МДО, get_limits) и суммарный факт (наряды) по
    ВСЕМ выделам и породам делянки, по каждому из 4 деловых сортиментов."""
    result = {s: {"limit": 0.0, "fakt": 0.0} for s in ("KR", "SR", "ML", "DROVA")}
    for item in items:
        limits = raskhod.get_limits(item)
        for poroda, by_sortiment in limits.items():
            for s in ("KR", "SR", "ML", "DROVA"):
                result[s]["limit"] += float(by_sortiment.get(s) or 0)
        naryady = raskhod.list_naryady(conn, item["id"])
        for naryad in naryady:
            for pos in naryad.get("pozitsii", []):
                sortiment = pos.get("sortiment")
                if sortiment in result:
                    result[sortiment]["fakt"] += float(pos.get("obyom") or 0)
    return result
