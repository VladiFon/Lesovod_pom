# -*- coding: utf-8 -*-
"""«🧑‍🌾 Карточки героев» — игровой вид экрана «Сотрудники» (этап 4 по
плану Влада 03.11.2026).

Карточка человека, как в игре: уровень и звание по очкам за всё время
(те же очки, что в «Рейтинге» — reyting.poschitat), класс по виду работ,
который он делает чаще всего, характеристики относительно команды (сила —
кубы за год, выносливость — дни в лесу за 60 дней, надёжность — задачи
плана, опыт — разных мест), навыки по видам работ, любимые места, лучший
напарник (с кем чаще всего в один день на одном месте по табелю), форма за
8 недель, место в рейтинге месяца, звено и ачивки (открытые и закрытые с
прогрессом). Ничего не пишет."""
from datetime import date, timedelta
import math

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401
from app.auth import get_current_user
from app.database import get_conn
from app.routers import reyting, tabel_igra

router = APIRouter(prefix="/api/geroi", tags=["geroi"])

ZVANIYA = [  # (с уровня, звание)
    (1, "Семечко"), (2, "Росток"), (3, "Саженец"), (4, "Подрост"), (5, "Молодняк"), (7, "Жердняк"),
    (9, "Средневозрастный"), (12, "Приспевающий"), (15, "Спелый"), (19, "Вековой дуб"),
]
KLASSY = [  # (кусок названия вида работ, класс)
    ("валк", "🪓 Вальщик"), ("трел", "🚜 Трелёвщик"), ("вывоз", "🚛 Возчик"), ("рубки ух", "✂️ Санитар леса"),
    ("культур", "🌱 Садовник леса"), ("восстан", "🌱 Садовник леса"), ("охран", "🛡 Страж леса"),
    ("заготов", "🪵 Заготовитель"),
]
OKNO_VYNOSLIVOSTI = 60
FORMA_NEDEL = 8


def uroven(ochki):
    lvl = int(math.sqrt(max(ochki, 0) / 25)) + 1
    nach = 25 * (lvl - 1) ** 2
    sled = 25 * lvl ** 2
    zv = [t for u, t in ZVANIYA if lvl >= u][-1]
    return {"uroven": lvl, "zvanie": zv, "ochki": ochki, "ot": nach, "do": sled,
            "pct": round((ochki - nach) / max(sled - nach, 1) * 100)}


def _klass(navyki, dolzhnost):
    if not navyki:
        return f"🧑‍🌾 {dolzhnost}" if dolzhnost else "🧑‍🌾 Новобранец"
    if len(navyki) >= 3 and navyki[2]["dni"] >= navyki[0]["dni"] * 0.6:
        return "🧰 Мастер на все руки"
    vid = (navyki[0]["vid"] or "").lower()
    for kusok, kl in KLASSY:
        if kusok in vid:
            return kl
    return f"🧑‍🌾 {navyki[0]['vid']}"


def _tabel(conn):
    """Все записи табеля «работал» с местом и видом работ."""
    out = {}
    for row in conn.execute(tabel_igra._ZAPIS_SQL + " WHERE tz.status = 'работал'").fetchall():
        z = tabel_igra._zapis(row)
        out.setdefault(z["sotrudnik_id"], []).append(z)
    return out


def _pervaya_zapis(conn):
    return {sid: d for sid, d in conn.execute("SELECT sotrudnik_id, MIN(data) FROM tabel_zapis GROUP BY sotrudnik_id")}


def _zadachi(conn):
    out = {}
    try:
        for sid, st, n in conn.execute("SELECT sotrudnik_id, status, COUNT(*) FROM work_plan GROUP BY sotrudnik_id, status"):
            x = out.setdefault(sid, {"vsego": 0, "vypolneno": 0})
            x["vsego"] += n
            if st == "выполнена":
                x["vypolneno"] += n
    except Exception:  # noqa: BLE001
        pass
    return out


def _mesyacy_goda(conn, segodnya):
    """{sid: {"lider": n, "zheleznyy": n}} по месяцам этого года."""
    out = {}
    m = 1
    while m <= segodnya.month:
        ot = date(segodnya.year, m, 1)
        do = (date(segodnya.year + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        poln = do < segodnya
        do = min(do, segodnya)
        cur, _ = reyting.poschitat(conn, ot, do)
        top = max((x["ochki"] for x in cur.values()), default=0)
        rabochih = sum(1 for k in range((do - ot).days + 1) if (ot + timedelta(days=k)).weekday() < 5)
        for sid, x in cur.items():
            o = out.setdefault(sid, {"lider": 0, "zheleznyy": 0})
            if poln and top > 0 and x["ochki"] == top:
                o["lider"] += 1
            if poln and x["propuskov"] == 0 and x["dni"] >= rabochih * 0.9:
                o["zheleznyy"] += 1
        m += 1
    return out


def _achivki(k, starozhil_dney, mes):
    def a(kod, z, title, opis, tek, nado):
        return {"kod": kod, "z": z, "title": title, "opis": opis, "est": tek >= nado,
                "progress": min(round(tek / nado * 100), 100) if nado else 100, "tek": round(tek, 1), "nado": nado}
    return [
        a("sotnya", "🌳", "Сотня", "100 дней в лесу", k["dni"], 100),
        a("pyatisotka", "🌲", "Пятисотка", "500 дней в лесу", k["dni"], 500),
        a("kuby100", "🪵", "Сто кубов", "100 м³ по нарядам", k["kuby"], 100),
        a("kuby1000", "🏔", "Тысячник", "1000 м³ по нарядам", k["kuby"], 1000),
        a("zadachi", "✅", "Исполнительный", "10 выполненных задач плана", k["zadachi"], 10),
        a("trelevka", "🚜", "Тягач", "100 м³ трелёвки", k["trelevka"], 100),
        a("universal", "🧰", "Универсал", "3+ разных вида работ", k["vidov"], 3),
        a("lider", "👑", "Лидер месяца", "1-е место в рейтинге за месяц", mes.get("lider", 0), 1),
        a("zheleznyy", "🛡", "Железный", "месяц без прогулов", mes.get("zheleznyy", 0), 1),
        a("starozhil", "🎂", "Старожил", "год в табеле", starozhil_dney, 365),
    ]


def sobrat(conn, segodnya=None):
    segodnya = segodnya or date.today()
    lyudi = conn.execute("SELECT id, fio, dolzhnost FROM sotrudniki WHERE is_active=1 ORDER BY fio").fetchall()
    kariera, _ = reyting.poschitat(conn, date(2000, 1, 1), segodnya)
    god, _ = reyting.poschitat(conn, date(segodnya.year, 1, 1), segodnya)
    nedeli = []
    pn = segodnya - timedelta(days=segodnya.weekday())
    for i in range(FORMA_NEDEL - 1, -1, -1):
        ot = pn - timedelta(days=7 * i)
        cur, _ = reyting.poschitat(conn, ot, min(ot + timedelta(days=6), segodnya))
        nedeli.append((ot, cur))
    mesyac = reyting.sobrat(conn, "mesyac", segodnya)
    mesto_mes = {r["sotrudnik_id"]: r["mesto"] for r in mesyac["reyting"]}
    v_igre_mes = len(mesyac["reyting"])
    mes_goda = _mesyacy_goda(conn, segodnya)
    tabel = _tabel(conn)
    pervaya = _pervaya_zapis(conn)
    zadachi = _zadachi(conn)
    zvenya = tabel_igra.spisok_zvenev(conn)
    fio = {sid: f for sid, f, _d in lyudi}

    # Напарники: в один день на одном месте.
    mesta_dnya = {}
    for sid, zz in tabel.items():
        for z in zz:
            k = (z["delyanka_item_id"], z["lesokultury_uchastok_id"])
            if k != (None, None):
                mesta_dnya.setdefault((z["data"], k), set()).add(sid)
    naparniki = {}
    for gruppa in mesta_dnya.values():
        for a in gruppa:
            for b in gruppa:
                if a != b:
                    naparniki.setdefault(a, {}).setdefault(b, 0)
                    naparniki[a][b] += 1

    ot60 = (segodnya - timedelta(days=OKNO_VYNOSLIVOSTI)).isoformat()
    pusto = {"dni": 0, "kuby": 0.0, "zadachi": 0, "trelevka": 0.0, "vidov": 0, "propuskov": 0, "ochki": 0}
    karty = []
    for sid, f, dolzh in lyudi:
        k = kariera.get(sid) or pusto
        g = god.get(sid) or pusto
        zz = tabel.get(sid, [])
        vidy, mesta = {}, {}
        for z in zz:
            if z["vid_raboty"]:
                vidy[z["vid_raboty"]] = vidy.get(z["vid_raboty"], 0) + 1
            if z["mesto"]:
                m = mesta.setdefault(z["mesto"], {"mesto": z["mesto"], "dni": 0, "posledniy": z["data"]})
                m["dni"] += 1
                m["posledniy"] = max(m["posledniy"], z["data"])
        navyki = [{"vid": v, "dni": n} for v, n in sorted(vidy.items(), key=lambda kv: -kv[1])]
        posl = max(zz, key=lambda z: z["data"]) if zz else None
        np = naparniki.get(sid) or {}
        luchshiy = max(np, key=np.get) if np else None
        p = pervaya.get(sid)
        try:
            starozhil = (segodnya - date.fromisoformat(p)).days if p else 0
        except ValueError:
            starozhil = 0
        zd = zadachi.get(sid) or {"vsego": 0, "vypolneno": 0}
        karty.append({
            "id": sid, "fio": f, "dolzhnost": dolzh,
            **uroven(k["ochki"]),
            "klass": _klass(navyki, dolzh),
            "kariera": {"dni": k["dni"], "kuby": k["kuby"], "zadachi": k["zadachi"], "trelevka": k["trelevka"]},
            "god": {"dni": g["dni"], "kuby": g["kuby"], "ochki": g["ochki"]},
            "_syroe": {
                "sila": g["kuby"],
                "vynoslivost": sum(1 for z in zz if z["data"] >= ot60),
                "nadezhnost": round(zd["vypolneno"] / zd["vsego"] * 100) if zd["vsego"] else 0,
                "opyt": len(mesta),
            },
            "zadachi_plana": zd,
            "navyki": navyki[:5],
            "mesta": sorted(mesta.values(), key=lambda m: -m["dni"])[:5],
            "seychas": {"mesto": posl["mesto"], "vid": posl["vid_raboty"], "data": posl["data"]} if posl else None,
            "naparnik": {"fio": fio.get(luchshiy, "—"), "dney": np[luchshiy]} if luchshiy else None,
            "forma": [{"nedelya": ot.strftime("%d.%m"), "ochki": (cur.get(sid) or {}).get("ochki", 0)} for ot, cur in nedeli],
            "mesto_mesyaca": mesto_mes.get(sid), "v_igre_mesyaca": v_igre_mes,
            "zveno": next(({"nazvanie": z["nazvanie"], "emoji": z["emoji"]} for z in zvenya if sid in z["sostav"]), None),
            "achivki": _achivki(k, starozhil, mes_goda.get(sid, {})),
            "v_tabele_s": p,
        })

    # Характеристики — 0..100 относительно лучшего в команде.
    for kl in ("sila", "vynoslivost", "nadezhnost", "opyt"):
        mx = max((x["_syroe"][kl] for x in karty), default=0)
        for x in karty:
            x.setdefault("harakteristiki", {})[kl] = {
                "znach": x["_syroe"][kl], "pct": round(x["_syroe"][kl] / mx * 100) if mx else 0}
    for x in karty:
        del x["_syroe"]
        x["achivok"] = sum(1 for a in x["achivki"] if a["est"])
    karty.sort(key=lambda x: (-x["ochki"], x["fio"]))
    return {"segodnya": segodnya.isoformat(), "geroi": karty, "okno_vynoslivosti": OKNO_VYNOSLIVOSTI}


@router.get("")
def geroi(user=Depends(get_current_user), conn=Depends(get_conn)):
    return sobrat(conn)
