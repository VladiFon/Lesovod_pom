# -*- coding: utf-8 -*-
"""«🧭 Путь делянки» — игровой вид экрана «Делянки» (этап 3 по плану Влада
03.11.2026).

Каждая делянка идёт по дороге из шести станций:
  📋 МДО       — делянка заведена (импорт МДО / создана);
  🎫 Билет     — есть номер лесорубочного билета;
  🪓 Рубка     — площадь пройдена по нарядам (или справкой заготовителя),
                 прогресс = % освоения по нарядам, срок = срок заготовки;
  🚛 Вывозка   — склад делянки по ЕГАИС пуст (приход − расход < 1 м³),
                 прогресс = % вывезенного, срок = срок вывозки;
  📜 Акт       — есть акт освидетельствования, срок — как в Инспекции;
  🏁 Закрыта   — делянка в архиве.
Станции считаются теми же функциями, что Инспекция (list_inspection) и
«Вывозка» (svodka_raskhod.egais_svodka), чтобы цифры не расходились.
«Стоит N дней» — от последнего события по делянке (наряд, расход ЕГАИС, акт,
билет, создание). Ничего не пишет."""
from datetime import date, datetime

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401
from app import storonnyaya, svodka_raskhod
from app.auth import get_current_user
from app.database import get_conn

import delyanka as legacy_delyanka

router = APIRouter(prefix="/api/put-delyanki", tags=["put-delyanki"])

STANCII = [
    ("mdo", "📋", "МДО"),
    ("bilet", "🎫", "Билет"),
    ("rubka", "🪓", "Рубка"),
    ("vyvozka", "🚛", "Вывозка"),
    ("akt", "📜", "Акт"),
    ("zakryta", "🏁", "Закрыта"),
]
ZASTRYALA_DNEY = 14
OSTATOK_MIN = 1.0
GORIT_DNEY = 14


def _d(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _f(d):
    return d.strftime("%d.%m.%Y") if d else None


def _naryady(conn):
    """{delyanka_id: (pervyy, posledniy)} — даты нарядов."""
    out = {}
    for did, data in conn.execute("SELECT delyanka_id, data FROM raskhod_naryad").fetchall():
        dt = _d(data)
        if not dt:
            continue
        a, b = out.get(did, (dt, dt))
        out[did] = (min(a, dt), max(b, dt))
    return out


def _egais(conn):
    """{delyanka_id: {prihod, raskhod, pervyy, posledniy}} — по складам делянки."""
    out = {}
    for napr in ("prihod", "raskhod"):
        for r in svodka_raskhod.egais_svodka(conn, napr)["rows"]:
            did = r.get("delyanka_id")
            if not did:
                continue
            x = out.setdefault(did, {"prihod": 0.0, "raskhod": 0.0, "pervyy": None, "posledniy": None})
            x[napr] += r["obyom"] or 0
            dt = _d(r.get("data_iso"))
            if napr == "raskhod" and dt:
                x["pervyy"] = min(x["pervyy"] or dt, dt)
                x["posledniy"] = max(x["posledniy"] or dt, dt)
    return out


def _srok(dt, segodnya):
    if not dt:
        return None
    return {"data": _f(dt), "dney": (dt - segodnya).days}


def odna(r, nar, eg, segodnya, sozdana=None):
    """Дорога одной делянки. r — строка list_inspection (или черновика)."""
    zakryta = r.get("status") == "архив"
    akt = bool(r.get("osvidetelstvovana"))
    chuzhaya = bool(r.get("storonnyaya"))
    st = {}

    sozd = _d(r.get("created_at")) or sozdana
    st["mdo"] = {"done": True, "data": _f(sozd)}

    bilet_d = _d(r.get("data_lesorubochnogo_bileta"))
    bilet = bool(r.get("nomer_lesorubochnogo_bileta")) or r.get("status") in ("активна", "архив")
    st["bilet"] = {"done": bilet, "data": _f(bilet_d),
                   "info": f"№ {r['nomer_lesorubochnogo_bileta']}" if r.get("nomer_lesorubochnogo_bileta") else None}

    n1, n2 = nar or (None, None)
    pz = _d(r.get("ploshad_zakryta"))
    pct_r = r.get("pct_osvoeniya_naryad")
    rubka_done = bool(pz or r.get("po_spravke") or akt or zakryta)
    st["rubka"] = {
        "done": rubka_done, "data": _f(pz or (n2 if rubka_done else None)), "nachalo": _f(n1),
        "pct": 100 if rubka_done and not pct_r else pct_r,
        "srok": None if rubka_done else _srok(_d(r.get("srok_okonchaniya_zagotovki")), segodnya),
        "info": f"рубит {storonnyaya.zagotovitel(r['storonnyaya'])}" if chuzhaya and isinstance(r.get("storonnyaya"), dict) else None,
    }

    e = eg or {}
    prihod, raskhod = e.get("prihod", 0.0), e.get("raskhod", 0.0)
    lezhit = max(prihod - raskhod, 0.0)
    vyv_done = zakryta or akt or (prihod >= OSTATOK_MIN and lezhit < OSTATOK_MIN and rubka_done)
    st["vyvozka"] = {
        "done": vyv_done, "data": _f(e.get("posledniy")) if vyv_done else None, "nachalo": _f(e.get("pervyy")),
        "pct": round(raskhod / prihod * 100) if prihod >= OSTATOK_MIN else (100 if vyv_done else None),
        "lezhit": round(lezhit, 1) if prihod >= OSTATOK_MIN else None,
        "srok": None if vyv_done else _srok(_d(r.get("srok_okonchaniya_vyvozki")), segodnya),
    }

    akt_d = _d(r.get("posledniy_akt_data"))
    srok_akta = [x for x in (_d(r.get("akt_po_ploshadi_do")) if not r.get("akt_po_ploshadi_sostavlen") else None,
                             _d(r.get("srok_osvidetelstvovaniya"))) if x]
    st["akt"] = {"done": akt or zakryta, "data": _f(akt_d),
                 "srok": None if (akt or zakryta) else _srok(min(srok_akta) if srok_akta else None, segodnya)}

    st["zakryta"] = {"done": zakryta, "data": None}

    tekushchaya = next((k for k, _e, _t in STANCII if not st[k]["done"]), None)
    sobytiya = [x for x in (sozd, bilet_d, n2, e.get("posledniy"), akt_d, pz) if x]
    posl = max(sobytiya) if sobytiya else None
    stoit = (segodnya - posl).days if posl and not zakryta else None
    nachalo = min(sobytiya) if sobytiya else None

    # Тревога: самый просроченный срок любой непройденной станции, иначе
    # ближайший срок текущей станции.
    nazv = {a: t for a, _e, t in STANCII}
    prosr = [(st[k]["srok"]["dney"], k) for k, _e, _t in STANCII
             if not st[k]["done"] and st[k].get("srok") and st[k]["srok"]["dney"] < 0]
    gorit = None
    if prosr:
        dn, k = min(prosr)
        gorit = f"{nazv[k]}: срок прошёл {-dn} дн. назад"
    elif tekushchaya and st[tekushchaya].get("srok") and st[tekushchaya]["srok"]["dney"] <= GORIT_DNEY:
        gorit = f"{nazv[tekushchaya]}: до срока {st[tekushchaya]['srok']['dney']} дн."

    if zakryta:
        ton = "done"
    elif gorit and "прошёл" in gorit:
        ton = "bad"
    elif gorit or (stoit is not None and stoit >= ZASTRYALA_DNEY):
        ton = "warn"
    else:
        ton = "ok"

    return {
        "id": r["id"], "nazvanie": r.get("nazvanie"), "status": r.get("status"),
        "stancii": st, "tekushchaya": tekushchaya,
        "proydeno": sum(1 for k, _e, _t in STANCII if st[k]["done"]),
        "stoit": stoit, "posledneye": _f(posl), "gorit": gorit, "ton": ton,
        "zastryala": stoit is not None and stoit >= ZASTRYALA_DNEY,
        "put_dney": (akt_d - nachalo).days if zakryta and akt_d and nachalo and akt_d >= nachalo else None,
        "chuzhaya": chuzhaya, "otsrochek": r.get("otsrochek") or 0,
    }


def sobrat(conn, segodnya=None):
    from app.routers import inspection
    segodnya = segodnya or date.today()
    rf = conn.row_factory
    rows = inspection.list_inspection(conn=conn)
    conn.row_factory = rf
    ids = {r["id"] for r in rows}
    for d in legacy_delyanka.list_delyanki(conn):
        if d.get("status") == "черновик" and d["id"] not in ids:
            rows.append({"id": d["id"], "nazvanie": d.get("nazvanie"), "status": "черновик",
                         "created_at": d.get("created_at"),
                         "nomer_lesorubochnogo_bileta": d.get("nomer_lesorubochnogo_bileta"),
                         "data_lesorubochnogo_bileta": d.get("data_lesorubochnogo_bileta")})
    conn.row_factory = rf
    nar = _naryady(conn)
    try:
        eg = _egais(conn)
    except Exception:  # noqa: BLE001
        eg = {}
    conn.row_factory = rf

    vse = [odna(r, nar.get(r["id"]), eg.get(r["id"]), segodnya) for r in rows]
    # Закрытые — только за этот год (по дате акта), чтобы дорога не росла бесконечно.
    v_puti, finish = [], []
    for x in vse:
        if x["status"] == "архив":
            d = _d(x["stancii"]["akt"]["data"])
            if not d or d.year == segodnya.year:
                finish.append(x)
        else:
            v_puti.append(x)
    poryadok = {"bad": 0, "warn": 1, "ok": 2}
    v_puti.sort(key=lambda x: (poryadok.get(x["ton"], 3), -(x["stoit"] or 0), x["proydeno"]))
    finish.sort(key=lambda x: (x["put_dney"] is None, x["put_dney"] or 0))
    po_st = {k: 0 for k, _e, _t in STANCII}
    for x in v_puti:
        if x["tekushchaya"]:
            po_st[x["tekushchaya"]] += 1
    speed = [x for x in finish if x["put_dney"] is not None]
    return {
        "segodnya": segodnya.isoformat(),
        "stancii": [{"kod": k, "emoji": e, "title": t, "delyanok": po_st[k]} for k, e, t in STANCII],
        "v_puti": v_puti,
        "finish": finish,
        "zastryali": sum(1 for x in v_puti if x["zastryala"]),
        "goryat": sum(1 for x in v_puti if x["ton"] == "bad"),
        "rekord": {"nazvanie": speed[0]["nazvanie"], "dney": speed[0]["put_dney"]} if speed else None,
        "srednij_put": round(sum(x["put_dney"] for x in speed) / len(speed)) if speed else None,
        "zastryala_dney": ZASTRYALA_DNEY,
    }


@router.get("")
def put_delyanki(user=Depends(get_current_user), conn=Depends(get_conn)):
    return sobrat(conn)
