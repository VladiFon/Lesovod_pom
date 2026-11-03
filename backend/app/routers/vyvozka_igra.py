# -*- coding: utf-8 -*-
"""«🚛 Вывозка» — игровой вид экрана «Расход / ЕГАИС» (просьба Влада
03.11.2026: «теперь надо сделать про расход по ЕГАИС»).

Что лежит на складах делянок и успеют ли вывезти к сроку:
  на складе = приход ЕГАИС − расход ЕГАИС по складам делянки (склад → выдел
  только через resolve_egais_sklady, как во всём учёте ЕГАИС; повторный
  приход при внутреннем перемещении не считается — svodka_raskhod);
  темп вывозки = расход ЕГАИС за 14 дней до вчера в рабочий день;
  прогноз к сроку окончания вывозки.
Плюс «табло»: расход по дням за 2 недели, неделя к неделе, рекорд дня,
кто оформил больше расхода за месяц, куда ушло, разбор ЕГАИС («мусор»), и
последний отчёт робота вечерней выгрузки. Ничего не пишет."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401
from app import storonnyaya, svodka_raskhod
from app.auth import get_current_user
from app.database import get_conn

import delyanka as legacy_delyanka

router = APIRouter(prefix="/api/vyvozka-igra", tags=["vyvozka-igra"])

TEMP_DNEY = 14
GORIT_DNEY = 14
OSTATOK_MIN = 1.0   # м³ — меньше считаем «склад пуст»


def _d(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _rab(ot, do):
    n, d = 0, ot
    while d <= do:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def _razbor(conn):
    def count(table):
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE status='new'").fetchone()[0]
        except Exception:  # noqa: BLE001
            return 0
    import raskhod_v2 as legacy_raskhod
    try:
        sklady = sum(1 for i in legacy_raskhod.resolve_egais_sklady(conn).values()
                     if i["how"] in legacy_raskhod.SKLAD_HOWS_PROBLEM)
    except Exception:  # noqa: BLE001
        sklady = 0
    return {
        "korrektirovki": count("egais_korrektirovka_review"),
        "sklady": sklady,
        "fls": count("egais_fls_prihod_review"),
    }


def _robot(conn):
    try:
        r = conn.execute(
            "SELECT text, created_at FROM notifications WHERE event_type='egais_robot' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    except Exception:  # noqa: BLE001
        r = None
    return {"text": r[0], "created_at": r[1]} if r else None


def sobrat(conn, segodnya=None):
    segodnya = segodnya or date.today()
    vchera = segodnya - timedelta(days=1)
    ot_temp = vchera - timedelta(days=TEMP_DNEY - 1)
    rab_temp = max(_rab(ot_temp, vchera), 1)

    prihod = svodka_raskhod.egais_svodka(conn, "prihod")["rows"]
    raskhod = svodka_raskhod.egais_svodka(conn, "raskhod")["rows"]

    po_d = {}
    def acc(did):
        return po_d.setdefault(did, {"prihod": 0.0, "raskhod": 0.0, "raskhod_temp": 0.0,
                                     "delovaya": 0.0, "drova": 0.0, "posledniy": None})
    for r in prihod:
        if r["delyanka_id"]:
            a = acc(r["delyanka_id"])
            a["prihod"] += r["obyom"]
            if r["group"] in ("delovaya", "drova"):
                a[r["group"]] += r["obyom"]
    for r in raskhod:
        if r["delyanka_id"]:
            a = acc(r["delyanka_id"])
            a["raskhod"] += r["obyom"]
            if r["group"] in ("delovaya", "drova"):
                a[r["group"]] -= r["obyom"]
            dt = _d(r["data_iso"])
            if dt and ot_temp <= dt <= vchera:
                a["raskhod_temp"] += r["obyom"]
            if dt and (a["posledniy"] is None or dt > a["posledniy"]):
                a["posledniy"] = dt

    vse = {r["id"]: r for r in legacy_delyanka.list_delyanki(conn)}
    sroki = {did: (zag, vyv) for did, zag, vyv in conn.execute(
        "SELECT id, srok_okonchaniya_zagotovki, srok_okonchaniya_vyvozki FROM delyanka").fetchall()}
    ids = [did for did, r in vse.items() if r.get("status") == "активна" or (po_d.get(did) and
           po_d[did]["prihod"] - po_d[did]["raskhod"] >= OSTATOK_MIN)]
    chuzhie = storonnyaya.load(conn, ids)

    delyanki = []
    for did in ids:
        r = vse[did]
        a = po_d.get(did) or acc(did)
        na_sklade = round(max(a["prihod"] - a["raskhod"], 0.0), 1)
        temp = round(a["raskhod_temp"] / rab_temp, 1) if a["raskhod_temp"] > 0 else None
        srok = _d((sroki.get(did) or (None, None))[1])
        dni_do = (srok - segodnya).days if srok else None
        rab_do = _rab(segodnya, srok) if srok and srok >= segodnya else 0
        nado = round(na_sklade / temp, 1) if temp and na_sklade >= OSTATOK_MIN else None
        if a["prihod"] < OSTATOK_MIN:
            verdikt, ton = "Склад пуст — прихода по ЕГАИС ещё нет", "pusto"
        elif na_sklade < OSTATOK_MIN:
            verdikt, ton = "Склад вывезен подчистую 🧹", "ok"
        elif dni_do is not None and dni_do < 0:
            verdikt, ton = f"Срок вывозки прошёл {-dni_do} дн. назад, а лежит {na_sklade:g} м³", "bad"
        elif not temp:
            if dni_do is not None and dni_do <= GORIT_DNEY:
                verdikt, ton = f"Лежит {na_sklade:g} м³, никто не вывозит, до срока {dni_do} дн. 🔥", "bad"
            else:
                verdikt, ton = f"Лежит {na_sklade:g} м³, вывозки 2 недели не было", "idle"
        elif srok and nado <= rab_do:
            verdikt, ton = f"Успевают: ~{nado:g} раб. дн. при темпе, есть {rab_do} ✅", "ok"
        elif srok:
            verdikt, ton = f"Не успевают: надо ~{nado:g} раб. дн., есть {rab_do} — гони лесовозы", "bad"
        else:
            verdikt, ton = f"Вывезут за ~{nado:g} раб. дн. при нынешнем темпе", "idle"
        delyanki.append({
            "id": did, "nazvanie": r.get("nazvanie"), "status": r.get("status"),
            "prihod": round(a["prihod"], 1), "raskhod": round(a["raskhod"], 1), "na_sklade": na_sklade,
            "delovaya": round(max(a["delovaya"], 0), 1), "drova": round(max(a["drova"], 0), 1),
            "pct_vyvezeno": round(a["raskhod"] / a["prihod"] * 100) if a["prihod"] >= OSTATOK_MIN else None,
            "temp": temp, "srok_vyvozki": (sroki.get(did) or (None, None))[1], "dni_do": dni_do, "nado_dney": nado,
            "posledniy": a["posledniy"].strftime("%d.%m.%Y") if a["posledniy"] else None,
            "verdikt": verdikt, "ton": ton,
            "zagotovitel": storonnyaya.zagotovitel(chuzhie[did]) if did in chuzhie else None,
        })
    poryadok = {"bad": 0, "idle": 1, "ok": 2, "pusto": 3}
    delyanki.sort(key=lambda x: (poryadok[x["ton"]], -(x["na_sklade"] or 0)))

    # Табло: расход по дням (все склады, включая непривязанные) и рейтинги месяца.
    ot_tablo = segodnya - timedelta(days=27)
    dni = {}
    kto, kuda = {}, {}
    nach_mes = segodnya.replace(day=1)
    rekord = None
    po_vsem_dnyam = {}
    for r in raskhod:
        dt = _d(r["data_iso"])
        if not dt:
            continue
        po_vsem_dnyam[dt] = po_vsem_dnyam.get(dt, 0.0) + r["obyom"]
        if ot_tablo <= dt <= segodnya:
            dni[dt] = dni.get(dt, 0.0) + r["obyom"]
        if nach_mes <= dt <= segodnya:
            k = r["sotrudnik"] or "—"
            x = kto.setdefault(k, {"kto": k, "obyom": 0.0, "docs": set()})
            x["obyom"] += r["obyom"]
            x["docs"].add(r["nomer"])
            p = r["poluchatel"] or "—"
            kuda[p] = kuda.get(p, 0.0) + r["obyom"]
    if po_vsem_dnyam:
        d_rek = max(po_vsem_dnyam, key=po_vsem_dnyam.get)
        rekord = {"data": d_rek.strftime("%d.%m.%Y"), "obyom": round(po_vsem_dnyam[d_rek], 1)}
    po_dnyam = []
    d = ot_tablo
    while d <= segodnya:
        po_dnyam.append({"data": d.isoformat(), "obyom": round(dni.get(d, 0.0), 1), "vyhodnoy": d.weekday() >= 5})
        d += timedelta(days=1)
    pn = segodnya - timedelta(days=segodnya.weekday())
    eta = sum(v for k, v in dni.items() if k >= pn)
    proshlaya = sum(v for k, v in dni.items() if pn - timedelta(days=7) <= k < pn - timedelta(days=7) + (segodnya - pn) + timedelta(days=1))
    seriya = 0
    d = vchera
    while True:
        if d.weekday() < 5:
            if po_vsem_dnyam.get(d, 0) > 0:
                seriya += 1
            else:
                break
        d -= timedelta(days=1)
        if seriya > 400:
            break

    return {
        "segodnya": segodnya.isoformat(),
        "delyanki": delyanki,
        "itogo_na_skladah": round(sum(x["na_sklade"] for x in delyanki), 1),
        "po_dnyam": po_dnyam,
        "eta_nedelya": round(eta, 1),
        "proshlaya_nedelya": round(proshlaya, 1),
        "rekord": rekord,
        "seriya": seriya,
        "kto": sorted(({"kto": v["kto"], "obyom": round(v["obyom"], 1), "docs": len(v["docs"])} for v in kto.values()),
                      key=lambda x: -x["obyom"])[:8],
        "kuda": [{"kuda": k, "obyom": round(v, 1)} for k, v in sorted(kuda.items(), key=lambda kv: -kv[1])[:6]],
        "razbor": _razbor(conn),
        "robot": _robot(conn),
        "temp_dney": TEMP_DNEY,
    }


@router.get("")
def vyvozka(user=Depends(get_current_user), conn=Depends(get_conn)):
    return sobrat(conn)
