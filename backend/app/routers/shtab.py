# -*- coding: utf-8 -*-
"""«🏰 Штаб» — игровой вид Дашборда (03.11.2026): одна «карта мира» со
сводкой всех игровых экранов — уровень и квесты дня, перекличка сегодня,
фронт работ на следующий рабочий день, охота на акты, вывозка, огород
уходов. Каждый блок считается теми же функциями, что его экран, и падает
отдельно (ошибка одного блока не валит штаб). Ничего не пишет, кроме того,
что пишет kvesty.sobrat (снимок квестов дня)."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401
from app.auth import get_current_user
from app.database import get_conn

router = APIRouter(prefix="/api/shtab", tags=["shtab"])

MUSHKA_DNEY = 14


def _d(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _sled_rab_den(d):
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _igrok(conn, user):
    from app.routers import kvesty
    k = kvesty.sobrat(conn, user)
    otkrytye = [q for q in k["kvesty"] if not q["done"] and not q["proval"]]
    poryadok = {"boss": 0, "main": 1, "side": 2}
    otkrytye.sort(key=lambda q: poryadok.get(q["vid"], 3))
    return {
        "uroven": k["uroven"], "xp": k["xp"], "segodnya_xp": k["segodnya_xp"], "seriya": k["seriya"],
        "shutka": k["shutka"], "nedelya": k["nedelya"],
        "kvesty": otkrytye[:5], "kvestov_otkryto": len(otkrytye),
        "kvestov_sdelano": sum(1 for q in k["kvesty"] if q["done"]),
        "svoi_otkryto": sum(1 for s in k["svoi"] if not s["done"]),
    }


def _pereklichka(conn, segodnya):
    vsego = conn.execute("SELECT COUNT(*) FROM sotrudniki WHERE is_active=1").fetchone()[0]
    otmecheno = conn.execute(
        "SELECT COUNT(DISTINCT tz.sotrudnik_id) FROM tabel_zapis tz JOIN sotrudniki s ON s.id = tz.sotrudnik_id "
        "WHERE s.is_active=1 AND tz.data = ?", (segodnya.isoformat(),)).fetchone()[0]
    rabotali = conn.execute(
        "SELECT COUNT(DISTINCT sotrudnik_id) FROM tabel_zapis WHERE data = ? AND status='работал'",
        (segodnya.isoformat(),)).fetchone()[0]
    return {"vsego": vsego, "otmecheno": otmecheno, "rabotali": rabotali, "vyhodnoy": segodnya.weekday() >= 5}


def _front(conn, segodnya):
    from app.routers import front_rabot
    data = _sled_rab_den(segodnya).isoformat()
    f = front_rabot.sobrat(conn, data)
    v_plane = sum(1 for l in f["lyudi"] if l["plan"])
    return {
        "data": data, "delyanok": len(f["delyanki"]),
        "gorit": sum(1 for x in f["delyanki"] if x["ton"] == "bad"),
        "gorit_imena": [x["nazvanie"] for x in f["delyanki"] if x["ton"] == "bad"][:3],
        "v_plane": v_plane, "lyudey": len(f["lyudi"]),
    }


def _ohota(conn, segodnya):
    from app.routers import inspection
    ushla = mushka = kapkan = trofei = 0
    imena = []
    for r in inspection.list_inspection(conn=conn):
        if r.get("zakryta"):
            d = _d(r.get("posledniy_akt_data"))
            if r.get("osvidetelstvovana") and d and d.year == segodnya.year:
                trofei += 1
            continue
        if r.get("osvidetelstvovana"):
            kapkan += 1
            continue
        sroki = []
        if r.get("akt_po_ploshadi_do") and not r.get("akt_po_ploshadi_sostavlen"):
            sroki.append(_d(r["akt_po_ploshadi_do"]))
        if r.get("srok_osvidetelstvovaniya"):
            sroki.append(_d(r["srok_osvidetelstvovaniya"]))
        sroki = [s for s in sroki if s]
        if not sroki:
            continue
        dni = (min(sroki) - segodnya).days
        if dni < 0:
            ushla += 1
            imena.append(r.get("nazvanie"))
        elif dni <= MUSHKA_DNEY:
            mushka += 1
    return {"ushla": ushla, "mushka": mushka, "kapkan": kapkan, "trofei": trofei, "ushla_imena": imena[:3]}


def _vyvozka(conn):
    from app.routers import vyvozka_igra
    v = vyvozka_igra.sobrat(conn)
    return {
        "na_skladah": v["itogo_na_skladah"], "eta_nedelya": v["eta_nedelya"], "proshlaya_nedelya": v["proshlaya_nedelya"],
        "gorit": sum(1 for x in v["delyanki"] if x["ton"] == "bad"),
        "gorit_imena": [x["nazvanie"] for x in v["delyanki"] if x["ton"] == "bad"][:3],
        "musor": sum(v["razbor"].values()), "robot": v["robot"], "po_dnyam": v["po_dnyam"][-14:],
    }


def _ogorod(conn, segodnya):
    from app.routers import uhody_igra
    sezon = uhody_igra.po_umolchaniyu(segodnya)
    it = uhody_igra.sobrat(conn, sezon)["itogo"]
    return {"sezon": sezon, **it}


def sobrat(conn, user, segodnya=None):
    segodnya = segodnya or date.today()
    out = {"segodnya": segodnya.isoformat()}
    rf = conn.row_factory
    for kl, fn in (
        ("igrok", lambda: _igrok(conn, user)),
        ("pereklichka", lambda: _pereklichka(conn, segodnya)),
        ("front", lambda: _front(conn, segodnya)),
        ("ohota", lambda: _ohota(conn, segodnya)),
        ("vyvozka", lambda: _vyvozka(conn)),
        ("ogorod", lambda: _ogorod(conn, segodnya)),
    ):
        try:
            conn.row_factory = rf
            out[kl] = fn()
        except Exception as e:  # noqa: BLE001
            out[kl] = None
            out.setdefault("oshibki", {})[kl] = str(e)[:200]
    return out


@router.get("")
def shtab(user=Depends(get_current_user), conn=Depends(get_conn)):
    return sobrat(conn, user)
