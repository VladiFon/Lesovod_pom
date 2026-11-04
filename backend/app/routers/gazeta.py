# -*- coding: utf-8 -*-
"""«📰 Лесная правда» — газета недели в игровом виде (этап 2 по плану Влада
03.11.2026: «Давай делать по этапно»).

Собирается сама из того, что уже есть в базе, за неделю пн–вс (текущая —
по сегодня; сравнение с прошлой неделей за те же дни):
  передовица — заготовлено (приход ЕГАИС; наряды пишутся раз в месяц —
    Влад, 04.11.2026 — поэтому они только запасной источник), вывезено по ЕГАИС,
    человеко-дни по табелю;
  герои недели — очки rejting.poschitat за неделю, рывок к прошлой неделе,
    звено недели;
  лесоповал — где рубили (м³ по приходу ЕГАИС по делянкам), день-рекорд;
  вывозка — расход ЕГАИС, кто оформил, куда ушло;
  инспекция — акты недели, «розыск» (просроченные, только текущая неделя);
  огород — мероприятия лесокультур по дате мероприятия;
  почта — принятые отчёты (completed_works), заметки рабочих;
  анонсы — сроки заготовки/вывозки/акта на ближайшие 2 недели;
  анекдот недели.
Каждая рубрика считается отдельно и падает отдельно. Ничего не пишет."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401
from app.auth import get_current_user
from app.database import get_conn

router = APIRouter(prefix="/api/gazeta", tags=["gazeta"])

DNI = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

ANEKDOTY = [
    "— Сколько лесников нужно, чтобы вкрутить лампочку?\n— Ни одного: лампочка не в квартале, а значит не наша.",
    "Тракторист спрашивает мастера: «Куда трелевать?» Мастер: «Туда, где ЕГАИС потом найдёт».",
    "Лесничий приходит домой, жена спрашивает: «Как день?» — «Освидетельствовал. Сам себя. Годен».",
    "Новый рабочий спросил, где тут выдел 9. Ему показали на карту. Он до сих пор там — в выделе 9, а не на карте.",
    "— Почему акт опять просрочен?\n— Он не просрочен, он выдержанный. Как коньяк.",
    "Береза сказала сосне: «Ты чего такая колючая?» Сосна: «Меня по таксации в хвойные записали, что поделаешь».",
    "Бригадир: «Сегодня работаем без перекура». Бригада: «Тогда и пила без бензина».",
    "Звонок в лесничество: «У вас лось на дороге!» — «Это не наш, наш в табеле стоит».",
    "Лесовоз уехал, ЕГАИС ещё не знает. ЕГАИС узнает в 20:00 — робот расскажет.",
    "— Сколько кубов нарубили?\n— По нарядам 40, по ЕГАИС 38, по ощущениям 400.",
    "Комиссия пришла на делянку освидетельствовать. Делянка смотрит на комиссию и думает: «Ну, кто кого».",
    "Шишка упала на голову мастеру. Мастер записал в журнал: «Самосев. Естественное возобновление».",
    "Лучший антистресс в лесничестве — отметить в табеле всех за пять секунд кнопкой «Как в прошлый раз».",
    "— Вася, ты почему в отпуске на делянке?\n— Так в табеле написано «отпуск», а сердце — в лесу.",
    "Осветление — это когда берёза мешает ёлке, а мастер мешает берёзе.",
    "Лесник заблудился в лесу. Нашёлся по GPS в отчёте с телефона — сам себе прислал «я тут».",
    "Сказка на ночь для лесничего: «И сдали они все акты в срок, и жили долго и без колокольчика».",
    "Агроуход в третий год — это как третья чашка кофе: вроде не обязательно, но по норме надо.",
    "Мастер спросил у пилы: «Ты устала?» Пила: «Р-р-р». Записали как «работала».",
    "Кубатурник посчитал, бухгалтер пересчитал, ЕГАИС пересчитал пересчитанное. Лес не считал — он просто рос.",
]

PRAZDNIKI = {(1, 1): "С Новым годом!", (3, 8): "С 8 Марта, наши лесные красавицы!",
             (9, 21): "Скоро День работников леса — третье воскресенье сентября!",
             (2, 23): "С 23 Февраля, защитники леса!"}


def _d(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _r(v):
    return round(v or 0, 1)


def mn(n, f1, f2, f5):
    """Русское число: 1 акт, 2 акта, 5 актов."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f1
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f2
    return f5


def _pct(a, b):
    if not b:
        return None
    return round((a - b) / b * 100)


def granicy(nedelya, segodnya):
    """(pn, do, prosh_pn, prosh_do, tekushchaya). Будущее не открываем."""
    d = _d(nedelya) or segodnya
    if d > segodnya:
        d = segodnya
    pn = d - timedelta(days=d.weekday())
    vs = pn + timedelta(days=6)
    tek = vs >= segodnya
    do = min(vs, segodnya)
    return pn, do, pn - timedelta(days=7), do - timedelta(days=7), tek


def _naryady_po_dnyam(conn):
    """[(date, delyanka_id, m3)] — объём каждого наряда."""
    out = []
    for did, data, v in conn.execute(
        """SELECT n.delyanka_id, n.data, COALESCE(SUM(p.obyom), 0)
           FROM raskhod_naryad n LEFT JOIN raskhod_pozitsiya p ON p.naryad_id = n.id GROUP BY n.id""").fetchall():
        dt = _d(data)
        if dt and v:
            out.append((dt, did, v))
    return out


def _prihod_po_dnyam(rows):
    """[(date, delyanka_id, m3)] из прихода ЕГАИС (заготовка поступила на склад)."""
    out = []
    for r in rows:
        dt = _d(r.get("data_iso"))
        if dt and r.get("obyom"):
            out.append((dt, r.get("delyanka_id"), r["obyom"]))
    return out


def _nazvaniya(conn):
    return {i: n for i, n in conn.execute("SELECT id, nazvanie FROM delyanka").fetchall()}


def _tabel(conn, ot, do):
    st = {}
    for status, n in conn.execute(
        "SELECT status, COUNT(*) FROM tabel_zapis WHERE data >= ? AND data <= ? GROUP BY status",
            (ot.isoformat(), do.isoformat())).fetchall():
        st[status] = n
    return st


def _peredovica(conn, g, naryady, raskhod):
    pn, do, ppn, pdo, _tek = g
    kuby = sum(v for dt, _did, v in naryady if pn <= dt <= do)
    kuby_p = sum(v for dt, _did, v in naryady if ppn <= dt <= pdo)
    vyv = sum(r["obyom"] for r in raskhod if (dt := _d(r["data_iso"])) and pn <= dt <= do)
    vyv_p = sum(r["obyom"] for r in raskhod if (dt := _d(r["data_iso"])) and ppn <= dt <= pdo)
    t = _tabel(conn, pn, do)
    tp = _tabel(conn, ppn, pdo)
    return {
        "kuby": _r(kuby), "kuby_prosh": _r(kuby_p), "kuby_pct": _pct(kuby, kuby_p),
        "vyvezeno": _r(vyv), "vyvezeno_prosh": _r(vyv_p), "vyvezeno_pct": _pct(vyv, vyv_p),
        "chelovekodni": t.get("работал", 0), "chelovekodni_prosh": tp.get("работал", 0),
        "bolnichnyh": t.get("больничный", 0), "otpusk": t.get("отпуск", 0), "progulov": t.get("не работал", 0),
    }


def _geroi(conn, g):
    from app.routers import reyting
    pn, do, ppn, pdo, _tek = g
    cur, _ = reyting.poschitat(conn, pn, do)
    prev, _ = reyting.poschitat(conn, ppn, pdo)
    fio = {i: f for i, f in conn.execute("SELECT id, fio FROM sotrudniki").fetchall()}
    rows = sorted(({"sid": s, "fio": fio.get(s, "—"), **x} for s, x in cur.items() if x["ochki"] > 0),
                  key=lambda r: (-r["ochki"], -r["kuby"], r["fio"]))
    top = [{"fio": r["fio"], "ochki": r["ochki"], "kuby": r["kuby"], "dni": r["dni"], "zadachi": r["zadachi"],
            "trelevka": r["trelevka"], "universal": r["universal"]} for r in rows[:3]]
    ryvok = None
    for r in rows:
        bylo = (prev.get(r["sid"]) or {}).get("ochki", 0)
        rost = r["ochki"] - bylo
        if bylo and rost > 0 and (ryvok is None or rost > ryvok["rost"]):
            ryvok = {"fio": r["fio"], "rost": rost, "bylo": bylo, "stalo": r["ochki"]}
    zvenya = []
    from app.routers import tabel_igra
    for z in tabel_igra.spisok_zvenev(conn):
        chleny = [cur[s]["ochki"] for s in z["sostav"] if s in cur]
        if chleny:
            zvenya.append({"nazvanie": z["nazvanie"], "emoji": z["emoji"],
                           "srednee": round(sum(chleny) / len(z["sostav"]))})
    zvenya.sort(key=lambda z: -z["srednee"])
    nichya = [r["fio"] for r in rows if rows and r["ochki"] == rows[0]["ochki"]]
    return {"top": top, "ryvok": ryvok, "nichya": nichya if len(nichya) > 1 else [], "zveno": zvenya[0] if zvenya and zvenya[0]["srednee"] > 0 else None,
            "igrokov": len(rows)}


def _lesopoval(conn, g, naryady):
    pn, do, *_ = g
    names = _nazvaniya(conn)
    po_d, po_dnyam = {}, {}
    for dt, did, v in naryady:
        if pn <= dt <= do:
            po_d[did] = po_d.get(did, 0.0) + v
            po_dnyam[dt] = po_dnyam.get(dt, 0.0) + v
    dni = []
    d = pn
    while d <= pn + timedelta(days=6):
        dni.append({"den": DNI[d.weekday()], "obyom": _r(po_dnyam.get(d, 0)), "budushchee": d > do})
        d += timedelta(days=1)
    rek = max(po_dnyam, key=po_dnyam.get) if po_dnyam else None
    return {
        "delyanki": [{"nazvanie": names.get(did, f"#{did}"), "obyom": _r(v)}
                     for did, v in sorted(po_d.items(), key=lambda kv: -kv[1])[:5]],
        "dni": dni,
        "rekord": {"den": f"{DNI[rek.weekday()]} {rek.strftime('%d.%m')}", "obyom": _r(po_dnyam[rek])} if rek else None,
    }


def _vyvozka(g, raskhod):
    pn, do, *_ = g
    kto, kuda, dni = {}, {}, {}
    for r in raskhod:
        dt = _d(r["data_iso"])
        if not dt or not (pn <= dt <= do):
            continue
        kto[r["sotrudnik"] or "—"] = kto.get(r["sotrudnik"] or "—", 0.0) + r["obyom"]
        kuda[r["poluchatel"] or "—"] = kuda.get(r["poluchatel"] or "—", 0.0) + r["obyom"]
        dni[dt] = dni.get(dt, 0.0) + r["obyom"]
    top = lambda m: [{"kto": k, "obyom": _r(v)} for k, v in sorted(m.items(), key=lambda kv: -kv[1])[:3]]  # noqa: E731
    rek = max(dni, key=dni.get) if dni else None
    return {"kto": top(kto), "kuda": top(kuda), "dney_s_vyvozkoy": len(dni),
            "rekord": {"den": f"{DNI[rek.weekday()]} {rek.strftime('%d.%m')}", "obyom": _r(dni[rek])} if rek else None}


def _inspekciya(conn, g, segodnya):
    pn, do, _ppn, _pdo, tek = g
    names = _nazvaniya(conn)
    akty = []
    for did, ad in conn.execute("SELECT delyanka_id, act_date FROM osvidetelstvovanie_acts").fetchall():
        dt = _d(ad)
        if dt and pn <= dt <= do:
            akty.append({"nazvanie": names.get(did, f"#{did}"), "data": dt.strftime("%d.%m")})
    rozysk = []
    if tek:
        from app.routers import shtab
        o = shtab._ohota(conn, segodnya)
        rozysk = o["ushla_imena"]
        return {"akty": akty, "rozysk": rozysk, "rozysk_vsego": o["ushla"], "mushka": o["mushka"]}
    return {"akty": akty, "rozysk": [], "rozysk_vsego": None, "mushka": None}


def _ogorod(conn, g):
    pn, do, *_ = g
    po_tipu, uchastki = {}, []
    for tip, data, kv, vd in conn.execute(
        """SELECT m.tip, m.data, u.kvartal, u.vydel FROM lesokultury_meropriyatiya m
           LEFT JOIN lesokultury_uchastok u ON u.id = m.uchastok_id""").fetchall():
        dt = _d(data)
        if dt and pn <= dt <= do:
            po_tipu[tip] = po_tipu.get(tip, 0) + 1
            if len(uchastki) < 6:
                uchastki.append(f"кв.{kv} выд.{vd}")
    return {"po_tipu": [{"tip": k, "n": v} for k, v in sorted(po_tipu.items(), key=lambda kv: -kv[1])],
            "uchastki": uchastki, "vsego": sum(po_tipu.values())}


def _pochta(conn, g):
    pn, do, *_ = g
    raboty, kto = 0, {}
    for data, fio in conn.execute("SELECT data_vypolneniya, ispolnitel_fio FROM completed_works").fetchall():
        dt = _d(data)
        if dt and pn <= dt <= do:
            raboty += 1
            kto[fio or "—"] = kto.get(fio or "—", 0) + 1
    zametok = conn.execute("SELECT COUNT(*) FROM worker_notes WHERE date(created_at) >= ? AND date(created_at) <= ?",
                           (pn.isoformat(), do.isoformat())).fetchone()[0]
    best = max(kto, key=kto.get) if kto else None
    return {"rabot": raboty, "zametok": zametok, "pisatel": {"fio": best, "n": kto[best]} if best else None}


def _anonsy(conn, g, segodnya):
    _pn, _do, _ppn, _pdo, tek = g
    if not tek:
        return []
    do = segodnya + timedelta(days=14)
    out = []
    for nazv, zag, vyv, st in conn.execute(
            "SELECT nazvanie, srok_okonchaniya_zagotovki, srok_okonchaniya_vyvozki, status FROM delyanka").fetchall():
        if st != "активна":
            continue
        for s, chto in ((zag, "кончается срок заготовки"), (vyv, "кончается срок вывозки")):
            dt = _d(s)
            if dt and segodnya <= dt <= do:
                out.append({"data": dt, "text": f"{nazv}: {chto}"})
    try:
        from app.routers import inspection
        for r in inspection.list_inspection(conn=conn):
            if r.get("zakryta") or r.get("osvidetelstvovana"):
                continue
            for k in ("akt_po_ploshadi_do", "srok_osvidetelstvovaniya"):
                dt = _d(r.get(k))
                if dt and segodnya <= dt <= do:
                    out.append({"data": dt, "text": f"{r.get('nazvanie')}: последний день для акта"})
                    break
    except Exception:  # noqa: BLE001
        pass
    out.sort(key=lambda x: x["data"])
    return [{"data": f"{DNI[x['data'].weekday()]} {x['data'].strftime('%d.%m')}",
             "dney": (x["data"] - segodnya).days, "text": x["text"]} for x in out[:8]]


def _zagolovki(o):
    """Главный заголовок и подзаголовки — из самых заметных фактов недели."""
    z = []
    p = o.get("peredovica") or {}
    if p:
        if p["kuby"] and p["kuby_pct"] is not None and p["kuby_pct"] >= 15:
            z.append(f"Пилы раскалились: {p['kuby']:g} м³ за неделю — на {p['kuby_pct']}% больше прошлой!")
        elif p["kuby"] and p["kuby_pct"] is not None and p["kuby_pct"] <= -15:
            z.append(f"Лес выдохнул: нарубили {p['kuby']:g} м³, на {-p['kuby_pct']}% меньше прошлой недели")
        elif p["kuby"]:
            z.append(f"Ровный ход: {p['kuby']:g} м³ за неделю")
    ins = o.get("inspekciya") or {}
    if ins.get("rozysk_vsego"):
        n = ins["rozysk_vsego"]
        z.insert(0, f"Срочно в номер: {n} {mn(n, 'делянка сбежала', 'делянки сбежали', 'делянок сбежали')} от акта!")
    if ins.get("akty"):
        n = len(ins["akty"])
        z.append(f"Комиссия не дремлет: {n} {mn(n, 'акт', 'акта', 'актов')} за неделю")
    ge = o.get("geroi") or {}
    if ge.get("nichya"):
        o_ = ge["top"][0]["ochki"]
        z.append(f"Ничья на вершине: {', '.join(ge['nichya'][:4])} — по {o_} {mn(o_, 'очку', 'очка', 'очков')}")
    elif ge.get("top"):
        o_ = ge["top"][0]["ochki"]
        z.append(f"Герой недели — {ge['top'][0]['fio']}: {o_} {mn(o_, 'очко', 'очка', 'очков')}")
    if p and p.get("vyvezeno"):
        z.append(f"Лесовозы увезли {p['vyvezeno']:g} м³ по ЕГАИС")
    og = o.get("ogorod") or {}
    if og.get("vsego"):
        n = og["vsego"]
        z.append(f"В огороде уходов {n} {mn(n, 'мероприятие', 'мероприятия', 'мероприятий')} — молодняк доволен")
    if not z:
        z.append("Тишина в лесу: на этой неделе в базе пусто. Лес растёт сам — но газете нужны новости!")
    return z


def sobrat(conn, nedelya=None, segodnya=None):
    segodnya = segodnya or date.today()
    g = granicy(nedelya, segodnya)
    pn, do, ppn, pdo, tek = g
    out = {
        "nedelya": pn.isoformat(), "ot": pn.strftime("%d.%m.%Y"), "do": do.strftime("%d.%m.%Y"),
        "do_vs": (pn + timedelta(days=6)).strftime("%d.%m.%Y"),
        "nomer": pn.isocalendar()[1], "god": pn.year, "tekushchaya": tek,
        "pred": (pn - timedelta(days=7)).isoformat(), "sled": None if tek else (pn + timedelta(days=7)).isoformat(),
        "anekdot": ANEKDOTY[(pn.isocalendar()[1] + pn.year) % len(ANEKDOTY)],
        "prazdnik": next((t for (m, d), t in PRAZDNIKI.items()
                          if any((pn + timedelta(days=k)).month == m and (pn + timedelta(days=k)).day == d
                                 for k in range(7))), None),
    }
    rf = conn.row_factory
    try:
        naryady = _naryady_po_dnyam(conn)
    except Exception as e:  # noqa: BLE001
        naryady = []
        out.setdefault("oshibki", {})["naryady"] = str(e)[:200]
    try:
        from app import svodka_raskhod
        conn.row_factory = rf
        raskhod = svodka_raskhod.egais_svodka(conn, "raskhod")["rows"]
    except Exception as e:  # noqa: BLE001
        raskhod = []
        out.setdefault("oshibki", {})["egais"] = str(e)[:200]
    # Заготовка по дням: наряды у Влада пишутся в последний день месяца
    # одним разом — по ним неделя пустая, а потом всплеск. Берём приход
    # ЕГАИС; наряды — только если прихода за эти две недели нет совсем.
    zagotovka, istochnik = naryady, "наряды"
    try:
        conn.row_factory = rf
        prihod = _prihod_po_dnyam(svodka_raskhod.egais_svodka(conn, "prihod")["rows"])
        if any(ppn <= dt <= do for dt, _did, _v in prihod):
            zagotovka, istochnik = prihod, "ЕГАИС"
    except Exception as e:  # noqa: BLE001
        out.setdefault("oshibki", {})["egais_prihod"] = str(e)[:200]
    out["istochnik_zagotovki"] = istochnik
    for kl, fn in (
        ("peredovica", lambda: _peredovica(conn, g, zagotovka, raskhod)),
        ("geroi", lambda: _geroi(conn, g)),
        ("lesopoval", lambda: _lesopoval(conn, g, zagotovka)),
        ("vyvozka", lambda: _vyvozka(g, raskhod)),
        ("inspekciya", lambda: _inspekciya(conn, g, segodnya)),
        ("ogorod", lambda: _ogorod(conn, g)),
        ("pochta", lambda: _pochta(conn, g)),
        ("anonsy", lambda: _anonsy(conn, g, segodnya)),
    ):
        try:
            conn.row_factory = rf
            out[kl] = fn()
        except Exception as e:  # noqa: BLE001
            out[kl] = None
            out.setdefault("oshibki", {})[kl] = str(e)[:200]
    conn.row_factory = rf
    out["zagolovki"] = _zagolovki(out)
    return out


@router.get("")
def gazeta(nedelya: str = "", user=Depends(get_current_user), conn=Depends(get_conn)):
    return sobrat(conn, nedelya or None)
