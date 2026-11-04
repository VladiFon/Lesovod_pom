# -*- coding: utf-8 -*-
"""«🏆 Рейтинг рабочих» (просьба Влада 03.11.2026: «рейтинг игровой, чтобы
был стимул у рабочих расти, смотреть с кем соперничают»).

Очки за период считаются только из того, что уже есть в базе:
  день в табеле со статусом «работал»         — OCHKI_DEN;
  м³ по нарядам — доля человека: объём наряда делянки за день делится
    поровну на всех, кто в этот день по табелю работал на этой делянке
    (у нас не бригада на делянке, а люди — см. tabel_igra);
  выполненная задача «Плана работ»             — OCHKI_ZADACHA;
  трелёвка, м³                                 — OCHKI_TRELEVKA за м³;
  «универсал» — 3+ разных вида работ           — OCHKI_UNIVERSAL разово.
Ничего не пишет. Для азарта, а не для зарплаты — так и подписано на экране."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401
from app.auth import get_current_user
from app.database import get_conn
from app.routers import tabel_igra

router = APIRouter(prefix="/api/reyting", tags=["reyting"])

OCHKI_DEN = 10
OCHKI_M3 = 1.0
OCHKI_ZADACHA = 5
OCHKI_TRELEVKA = 0.5
OCHKI_UNIVERSAL = 15
UNIVERSAL_VIDOV = 3
# «Отчёт за смену» с телефона (03.11.2026): уход/подготовка почвы — за га,
# вывозка населению — за м³, ремонт — за час. Напарникам — так же, как автору.
OCHKI_GA = 5
OCHKI_NASELENIYU = 0.5
OCHKI_REMONT_CHAS = 1

PERIODY = {"nedelya": "Неделя", "mesyac": "Месяц", "proshlyy": "Прошлый месяц", "god": "Год"}


def _d(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def granicy(period, segodnya):
    if period == "nedelya":
        ot = segodnya - timedelta(days=segodnya.weekday())
        return ot, segodnya, ot - timedelta(days=7), ot - timedelta(days=1)
    if period == "proshlyy":
        do = segodnya.replace(day=1) - timedelta(days=1)
        ot = do.replace(day=1)
        pdo = ot - timedelta(days=1)
        return ot, do, pdo.replace(day=1), pdo
    if period == "god":
        ot = segodnya.replace(month=1, day=1)
        return ot, segodnya, ot.replace(year=ot.year - 1), segodnya.replace(year=segodnya.year - 1)
    ot = segodnya.replace(day=1)
    pdo = ot - timedelta(days=1)
    return ot, segodnya, pdo.replace(day=1), pdo


def poschitat(conn, ot, do):
    """{sotrudnik_id: {dni, kuby, zadachi, trelevka, vidy, propuskov, ochki}}"""
    ot_s, do_s = ot.isoformat(), do.isoformat()
    out = {}

    def p(sid):
        return out.setdefault(sid, {"dni": 0, "kuby": 0.0, "zadachi": 0, "trelevka": 0.0, "vidy": set(), "propuskov": 0,
                                    "smena": 0.0})

    kto_gde = {}  # (data_iso, delyanka_id) -> [sid]
    for sid, data, status, did, vid in conn.execute(
        """SELECT tz.sotrudnik_id, tz.data, tz.status, di.delyanka_id, tz.vid_raboty_id
           FROM tabel_zapis tz LEFT JOIN delyanka_item di ON di.id = tz.delyanka_item_id
           WHERE tz.data >= ? AND tz.data <= ?""", (ot_s, do_s)).fetchall():
        x = p(sid)
        if status == "работал":
            x["dni"] += 1
            if vid:
                x["vidy"].add(vid)
            if did:
                kto_gde.setdefault((data, did), []).append(sid)
        elif status == "не работал":
            x["propuskov"] += 1

    nichyi = 0.0
    for did, data, v in conn.execute(
        """SELECT n.delyanka_id, n.data, COALESCE(SUM(p.obyom), 0)
           FROM raskhod_naryad n LEFT JOIN raskhod_pozitsiya p ON p.naryad_id = n.id GROUP BY n.id""").fetchall():
        dt = _d(data)
        if not dt or not (ot <= dt <= do) or not v:
            continue
        kto = kto_gde.get((dt.isoformat(), did))
        if not kto:
            nichyi += v
            continue
        for sid in kto:
            p(sid)["kuby"] += v / len(kto)

    try:
        for sid, n in conn.execute(
            "SELECT sotrudnik_id, COUNT(*) FROM work_plan WHERE status='выполнена' AND data >= ? AND data <= ? "
            "GROUP BY sotrudnik_id", (ot_s, do_s)).fetchall():
            p(sid)["zadachi"] += n
    except Exception:  # noqa: BLE001
        pass
    try:
        for sid, v in conn.execute(
            "SELECT sotrudnik_id, SUM(obyom) FROM trelevka WHERE date(created_at) >= ? AND date(created_at) <= ? "
            "GROUP BY sotrudnik_id", (ot_s, do_s)).fetchall():
            p(sid)["trelevka"] += v or 0
    except Exception:  # noqa: BLE001
        pass

    try:
        for oid, sid, vid, obyom, ga, chasy in conn.execute(
            "SELECT id, sotrudnik_id, vid, obyom, ga, chasy FROM otchet_smeny WHERE deleted=0 AND data >= ? AND data <= ?",
                (ot_s, do_s)).fetchall():
            o = (ga or 0) * OCHKI_GA if vid in ("uhod", "pochva", "posadka", "rubka_uhoda", "ochistka", "sanrubka") else (obyom or 0) * OCHKI_NASELENIYU if vid == "naseleniyu" \
                else (chasy or 0) * OCHKI_REMONT_CHAS if vid == "remont" else 0
            if not o:
                continue
            kto = {sid} | {r[0] for r in conn.execute("SELECT sotrudnik_id FROM otchet_smeny_uchastnik WHERE otchet_id=?", (oid,))}
            for s_ in kto:
                p(s_)["smena"] += o
    except Exception:  # noqa: BLE001 — таблицы ещё нет (отчётов за смену не было)
        pass

    for x in out.values():
        x["universal"] = len(x["vidy"]) >= UNIVERSAL_VIDOV
        x["vidov"] = len(x["vidy"])
        del x["vidy"]
        x["ochki_po"] = {
            "dni": x["dni"] * OCHKI_DEN,
            "kuby": round(x["kuby"] * OCHKI_M3),
            "zadachi": x["zadachi"] * OCHKI_ZADACHA,
            "trelevka": round(x["trelevka"] * OCHKI_TRELEVKA),
            "universal": OCHKI_UNIVERSAL if x["universal"] else 0,
            "smena": round(x["smena"]),
        }
        x["ochki"] = sum(x["ochki_po"].values())
        x["kuby"] = round(x["kuby"], 1)
        x["trelevka"] = round(x["trelevka"], 1)
        x["smena"] = round(x["smena"])
    return out, round(nichyi, 1)


def _mesta(rows):
    """Места с учётом ничьих: место = 1 + сколько людей набрали больше."""
    return {r["sotrudnik_id"]: 1 + sum(1 for x in rows if x["ochki"] > r["ochki"]) for r in rows}


def sobrat(conn, period="mesyac", segodnya=None):
    segodnya = segodnya or date.today()
    if period not in PERIODY:
        period = "mesyac"
    ot, do, pot, pdo = granicy(period, segodnya)
    lyudi = conn.execute("SELECT id, fio, dolzhnost FROM sotrudniki WHERE is_active=1 ORDER BY fio").fetchall()
    cur, nichyi = poschitat(conn, ot, do)
    prev, _ = poschitat(conn, pot, pdo)
    pusto = {"dni": 0, "kuby": 0.0, "zadachi": 0, "trelevka": 0.0, "vidov": 0, "universal": False, "propuskov": 0,
             "ochki": 0, "ochki_po": {}}

    rows = [{"sotrudnik_id": sid, "fio": fio, "dolzhnost": dolzh, **(cur.get(sid) or pusto)} for sid, fio, dolzh in lyudi]
    rows.sort(key=lambda r: (-r["ochki"], -r["dni"], r["fio"]))
    prev_rows = sorted(({"sotrudnik_id": sid, "ochki": (prev.get(sid) or {}).get("ochki", 0)} for sid, _f, _d2 in lyudi),
                       key=lambda r: -r["ochki"])
    prev_mesto = _mesta([r for r in prev_rows if r["ochki"] > 0])
    v_igre = [r for r in rows if r["ochki"] > 0]
    mesta = _mesta(v_igre)
    for r in v_igre:
        r["mesto"] = mesta[r["sotrudnik_id"]]
        pm = prev_mesto.get(r["sotrudnik_id"])
        r["bylo_mesto"] = pm
        r["sdvig"] = (pm - r["mesto"]) if pm else None
        vperedi = [x for x in v_igre if x["ochki"] > r["ochki"]]
        szadi = [x for x in v_igre if x["ochki"] < r["ochki"]]
        r["ravnye"] = [x["fio"] for x in v_igre if x["ochki"] == r["ochki"] and x is not r]
        if vperedi:
            r["sopernik"] = {"fio": vperedi[-1]["fio"], "otryv": vperedi[-1]["ochki"] - r["ochki"]}
        if szadi:
            r["dogonyaet"] = {"fio": szadi[0]["fio"], "otryv": r["ochki"] - szadi[0]["ochki"]}
        r["znachki"] = []

    def lider(key, znachok, title, min_val=0.01):
        if not v_igre:
            return
        top = max(r[key] for r in v_igre)
        if top >= min_val:
            for r in v_igre:
                if r[key] == top:
                    r["znachki"].append({"z": znachok, "title": title})

    for r in v_igre:
        if r["mesto"] == 1:
            r["znachki"].append({"z": "👑", "title": "Лидер периода"})
    lider("kuby", "🪵", "Больше всех кубов")
    lider("trelevka", "🚜", "Король трелёвки")
    lider("zadachi", "✅", "Больше всех задач из плана", 1)
    lider("vidov", "🧰", "Больше всех видов работ", UNIVERSAL_VIDOV)
    rabochih = sum(1 for k in range((do - ot).days + 1) if (ot + timedelta(days=k)).weekday() < 5)
    for r in v_igre:
        if r["propuskov"] == 0 and rabochih >= 5 and r["dni"] >= rabochih * 0.9:
            r["znachki"].append({"z": "🛡", "title": "Железный — без прогулов"})
    ryvok = [r for r in v_igre if r.get("sdvig") and r["sdvig"] >= 2]
    if ryvok:
        best = max(ryvok, key=lambda r: r["sdvig"])
        best["znachki"].append({"z": "🚀", "title": f"Рывок: +{best['sdvig']} мест"})

    # Звенья — среднее очков на человека, чтобы большое звено не выигрывало числом.
    po_id = {r["sotrudnik_id"]: r for r in rows}
    zvenya = []
    for z in tabel_igra.spisok_zvenev(conn):
        chleny = [po_id[s] for s in z["sostav"] if s in po_id]
        if not chleny:
            continue
        vsego = sum(c["ochki"] for c in chleny)
        zvenya.append({
            "id": z["id"], "nazvanie": z["nazvanie"], "emoji": z["emoji"], "chlenov": len(chleny),
            "ochki": vsego, "srednee": round(vsego / len(chleny)), "kuby": round(sum(c["kuby"] for c in chleny), 1),
            "sostav": [c["fio"] for c in chleny],
        })
    zvenya.sort(key=lambda z: -z["srednee"])

    return {
        "period": period, "periody": PERIODY,
        "ot": ot.isoformat(), "do": do.isoformat(),
        "reyting": v_igre,
        "v_zapase": [r for r in rows if r["ochki"] == 0],
        "zvenya": zvenya,
        "kuby_bez_lyudey": nichyi,
        "pravila": {
            "den": OCHKI_DEN, "m3": OCHKI_M3, "zadacha": OCHKI_ZADACHA, "trelevka": OCHKI_TRELEVKA,
            "universal": OCHKI_UNIVERSAL, "universal_vidov": UNIVERSAL_VIDOV,
            "ga": OCHKI_GA, "naseleniyu": OCHKI_NASELENIYU, "remont_chas": OCHKI_REMONT_CHAS,
        },
    }


@router.get("")
def reyting(period: str = "mesyac", user=Depends(get_current_user), conn=Depends(get_conn)):
    return sobrat(conn, period)
