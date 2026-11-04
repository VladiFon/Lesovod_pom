# -*- coding: utf-8 -*-
"""«🗺 Фронт работ» — игровой вид экрана «Распределение бригад» (просьба
Влада 03.11.2026).

Важно от Влада: бригады у нас НЕ сидят на одной делянке — бригада
работает на разных делянках, а пара-тройка людей всё время вместе и
делает разное. Поэтому «кто где» берётся НЕ из назначений бригад, а из
табеля (последняя запись каждого человека за неделю), а план на день —
обычные задачи «Плана работ» (work_plan) с делянкой: перетащил звено или
человека на делянку — каждому задача на выбранный день, она же уходит
мастеру на телефон.

Для каждой активной делянки: остаток м³ (как в «Отсрочке»: лимит − большее
из нарядов и ЕГАИС), темп по нарядам за 14 дней (м³ в рабочий день),
прогноз «успеют к сроку заготовки или нет». Ничего в обычных таблицах
здесь не пишется — запись идёт через POST/DELETE /api/work-plan/."""
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from app import legacy_bridge  # noqa: F401
from app import storonnyaya
from app.auth import get_current_user
from app.database import get_conn
from app.routers import otsrochka, tabel_igra

router = APIRouter(prefix="/api/front-rabot", tags=["front-rabot"])

TEMP_DNEY = 14      # окно для темпа по нарядам
KTO_GDE_DNEY = 7    # «кто где» — последняя запись табеля за столько дней
GORIT_DNEY = 14     # делянка без людей и срок ближе — горит


def _d(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _rabochih_dney(ot, do):
    """Рабочих (пн–пт) дней с ot по do включительно."""
    n, d = 0, ot
    while d <= do:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def temp_po_naryadam(conn, ids, segodnya):
    """{delyanka_id: м³ в рабочий день} по нарядам за TEMP_DNEY дней,
    заканчивая вчерашним днём (сегодняшние наряды обычно ещё не внесены, а
    план бывает на завтра — будущие дни темп не должны разбавлять)."""
    segodnya = min(segodnya, date.today()) - timedelta(days=1)
    ot = segodnya - timedelta(days=TEMP_DNEY)
    obyom = {}
    for did, data, v in conn.execute(
        """SELECT n.delyanka_id, n.data, COALESCE(SUM(p.obyom), 0)
           FROM raskhod_naryad n LEFT JOIN raskhod_pozitsiya p ON p.naryad_id = n.id
           GROUP BY n.id"""
    ).fetchall():
        if did not in ids:
            continue
        dd = _d(data)
        if dd and ot < dd <= segodnya:
            obyom[did] = obyom.get(did, 0.0) + (v or 0)
    dney = max(_rabochih_dney(ot + timedelta(days=1), segodnya), 1)
    return {did: round(v / dney, 1) for did, v in obyom.items() if v > 0}


def kto_gde(conn, data):
    """Последняя запись «работал» каждого человека за KTO_GDE_DNEY дней до
    даты (не включая её): {sotrudnik_id: {data, delyanka_item_id, ...}}."""
    ot = (_d(data) - timedelta(days=KTO_GDE_DNEY)).isoformat()
    rows = conn.execute(
        """SELECT tz.sotrudnik_id, tz.data, tz.status, tz.delyanka_item_id, tz.lesokultury_uchastok_id,
                  di.delyanka_id, v.nazvanie
           FROM tabel_zapis tz
           JOIN (SELECT sotrudnik_id sid, MAX(data) md FROM tabel_zapis
                 WHERE data >= ? AND data < ? GROUP BY sotrudnik_id) last
             ON last.sid = tz.sotrudnik_id AND last.md = tz.data
           LEFT JOIN delyanka_item di ON di.id = tz.delyanka_item_id
           LEFT JOIN vidy_rabot v ON v.id = tz.vid_raboty_id""",
        (ot, data),
    ).fetchall()
    return {
        r[0]: {"data": r[1], "status": r[2], "delyanka_item_id": r[3], "lesokultury_uchastok_id": r[4],
               "delyanka_id": r[5], "vid_raboty": r[6]}
        for r in rows
    }


def sobrat(conn, data):
    segodnya = _d(data)
    if not segodnya:
        raise HTTPException(400, "Дата в формате ГГГГ-ММ-ДД")
    rows = conn.execute(
        "SELECT id, nazvanie, srok_okonchaniya_zagotovki, srok_okonchaniya_vyvozki FROM delyanka WHERE status='активна'"
    ).fetchall()
    chuzhie = storonnyaya.load(conn, {r[0] for r in rows})
    rows = [r for r in rows if storonnyaya.vidna_nashim(chuzhie.get(r[0]))]
    ids = {r[0] for r in rows}
    ost = otsrochka._ostatki(conn, list(ids)) if ids else {}
    temp = temp_po_naryadam(conn, ids, segodnya)

    items = {}
    for iid, did, kv, vd in conn.execute("SELECT id, delyanka_id, kvartal, vydel FROM delyanka_item ORDER BY poryadok, id"):
        if did in ids:
            items.setdefault(did, []).append({"item_id": iid, "label": f"кв.{kv or '—'} выд.{vd or '—'}"})

    lyudi = {
        r[0]: {"sotrudnik_id": r[0], "fio": r[1], "dolzhnost": r[2]}
        for r in conn.execute("SELECT id, fio, dolzhnost FROM sotrudniki WHERE is_active=1 ORDER BY fio").fetchall()
    }
    gde = kto_gde(conn, data)
    plan = {}
    for wid, sid, iid, did, zad, st in conn.execute(
        """SELECT wp.id, wp.sotrudnik_id, wp.delyanka_item_id, di.delyanka_id, wp.zadacha, wp.status
           FROM work_plan wp LEFT JOIN delyanka_item di ON di.id = wp.delyanka_item_id
           WHERE wp.data = ?""",
        (data,),
    ).fetchall():
        plan.setdefault(sid, []).append({"id": wid, "delyanka_id": did, "item_id": iid, "zadacha": zad, "status": st})

    delyanki = []
    for did, naz, srok_z, srok_v in rows:
        o = ost.get(did) or {}
        t = temp.get(did)
        srok = _d(srok_z) or _d(srok_v)
        dni_do = (srok - segodnya).days if srok else None
        rab_do = _rabochih_dney(segodnya, srok) if srok and srok >= segodnya else 0
        nado_dney = round(o["ostatok"] / t, 1) if t and o.get("ostatok") else None
        bylo = [sid for sid, g in gde.items() if g.get("delyanka_id") == did and g.get("status") == "работал"]
        v_plane = [sid for sid, pl in plan.items() if any(p["delyanka_id"] == did for p in pl)]
        if o.get("limit") and (o.get("ostatok") or 0) < otsrochka.OSTATOK_MIN_M3:
            verdikt, ton = "Дорублена 🎉", "ok"
        elif dni_do is not None and dni_do < 0:
            verdikt, ton = f"Срок заготовки прошёл {-dni_do} дн. назад — нужна отсрочка", "bad"
        elif not bylo and not v_plane:
            if dni_do is not None and dni_do <= GORIT_DNEY:
                verdikt, ton = f"Никого нет, а до срока {dni_do} дн. 🔥", "bad"
            else:
                verdikt, ton = "Свободна — людей нет", "idle"
        elif nado_dney is None:
            verdikt, ton = "Темп пока неизвестен — нет нарядов за 2 недели", "idle"
        elif srok and nado_dney <= rab_do:
            verdikt, ton = f"Успевают: надо ~{nado_dney:g} раб. дн., есть {rab_do} ✅", "ok"
        elif srok:
            verdikt, ton = f"Не успевают: надо ~{nado_dney:g} раб. дн., есть {rab_do} — добавь людей", "bad"
        else:
            verdikt, ton = f"Осталось ~{nado_dney:g} раб. дн. при нынешнем темпе", "idle"
        pct = round(o["fakt"] / o["limit"] * 100) if o.get("limit") else None
        delyanki.append({
            "id": did, "nazvanie": naz, "vydely": o.get("vydely") or ", ".join(i["label"] for i in items.get(did, [])),
            "items": items.get(did, []), "limit": o.get("limit"), "fakt": o.get("fakt"), "ostatok": o.get("ostatok"),
            "pct": pct, "srok": srok_z or srok_v, "dni_do": dni_do, "temp": t, "nado_dney": nado_dney,
            "bylo": sorted(bylo), "v_plane": sorted(v_plane), "verdikt": verdikt, "ton": ton,
            "zagotovitel": storonnyaya.zagotovitel(chuzhie[did]) if did in chuzhie else None,
        })
    poryadok = {"bad": 0, "ok": 1, "idle": 2}
    delyanki.sort(key=lambda x: (poryadok[x["ton"]], x["dni_do"] if x["dni_do"] is not None else 9999))

    for sid, l in lyudi.items():
        g = gde.get(sid)
        l["gde"] = g
        l["plan"] = plan.get(sid, [])
    return {
        "data": data,
        "delyanki": delyanki,
        "lyudi": list(lyudi.values()),
        "zvenya": tabel_igra.spisok_zvenev(conn),
        "temp_dney": TEMP_DNEY,
    }


@router.get("")
def front(data: str = "", user=Depends(get_current_user), conn=Depends(get_conn)):
    if not data:
        d = date.today() + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        data = d.isoformat()
    return sobrat(conn, data)
