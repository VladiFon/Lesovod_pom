# -*- coding: utf-8 -*-
"""Режим «Квесты» (просьба Влада 03.11.2026) — отдельный игровой экран
рядом с обычным интерфейсом, ничего в обычном UI не меняет.

* Квесты дня = строки «Ждёт меня» (app/routers/zhdet.sobrat): danger —
  босс, warning — основной квест, info — побочный. Утром (при первом
  открытии за день) список запоминается в kvest_den; что пропало из
  «Ждёт меня» — считается выполненным и даёт XP. Галочку ставить не надо:
  сделал дело в обычном интерфейсе — квест закрылся сам.
* Свои квесты (kvest_svoi) — ручные дела с галочкой («позвонить в
  лесхоз»).
* Опыт за работу — задним числом из того, что уже лежит в базе: наряды,
  акты освидетельствования, сформированные документы, задачи календаря,
  пробы уходов, мероприятия лесокультур. Наряды и документы с
  updated_by/created_by засчитываются автору, у остальных автора в базе
  нет — они общие (идут всем, кто играет).

Ни одна строка обычных таблиц здесь не меняется."""
import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401

from app.auth import get_current_user
from app.database import get_conn
from app.routers import zhdet

router = APIRouter(prefix="/api/kvesty", tags=["kvesty"])

SCHEMA = """
CREATE TABLE IF NOT EXISTS kvest_den (
    user_id INTEGER NOT NULL,
    den TEXT NOT NULL,
    kod TEXT NOT NULL,
    tone TEXT,
    title TEXT,
    hint TEXT,
    screen TEXT,
    params TEXT,
    count0 INTEGER,
    count_now INTEGER,
    done_at TEXT,
    PRIMARY KEY (user_id, den, kod)
);
CREATE TABLE IF NOT EXISTS kvest_svoi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    srok TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    done_at TEXT,
    deleted INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_kvest_svoi_user ON kvest_svoi(user_id, deleted);
"""

# Опыт за квест по «весу» строки «Ждёт меня».
XP_KVEST = {"danger": 120, "warning": 50, "info": 20}
XP_SVOI = 20
XP_SVOI_LIMIT_DEN = 100  # свои квесты — не больше 100 XP в день, чтобы не фармить
STREAK_MIN_XP = 50

# Опыт за работу (из обычных таблиц). (ключ, подпись, XP, SQL дат, колонка автора или None)
ISTOCHNIKI = [
    ("akty", "Акт освидетельствования", 80,
     "SELECT date(created_at) d, COUNT(*) FROM osvidetelstvovanie_acts WHERE created_at >= ? GROUP BY d", None),
    ("naryady", "Наряд", 10,
     "SELECT date(created_at) d, COUNT(*) FROM raskhod_naryad WHERE created_at >= ? {avtor} GROUP BY d", "updated_by"),
    ("dokumenty", "Документ (лут)", 15,
     "SELECT date(created_at) d, COUNT(*) FROM documents WHERE status='готов' AND created_at >= ? {avtor} GROUP BY d",
     "created_by"),
    ("kalendar", "Задача календаря", 20,
     "SELECT date(completed_at) d, COUNT(*) FROM calendar_completions WHERE completed_at >= ? GROUP BY d", None),
    ("proby", "Проба уходов", 30,
     "SELECT date(completed_at) d, COUNT(*) FROM uhody_proby WHERE completed_at IS NOT NULL AND completed_at >= ? "
     "GROUP BY d", None),
    ("tabel", "Строка табеля", 2,
     "SELECT date(created_at) d, COUNT(*) FROM tabel_zapis WHERE created_at >= ? {avtor} GROUP BY d", "entered_by"),
    ("lesokultury", "Мероприятие лесокультур", 10,
     "SELECT date(created_at) d, COUNT(*) FROM lesokultury_meropriyatiya WHERE created_at >= ? GROUP BY d", None),
]
ISTORIYA_DNEY = 400

# Квест, который не закрыли, а он «перетёк» в более страшный — не выполнен.
PEREHOD = {"akty_skoro": "akty_prosr"}

# Названия квестов с приколами. Подсказку («что именно») берём из «Ждёт меня».
NAZVANIYA = {
    "akty_prosr": "👹 Босс: Просроченный Акт",
    "otsrochka": "🐉 Босс: Отсрочка-Злодей",
    "akty_skoro": "⏳ Акт горит — успей за неделю",
    "egais": "🧾 Разгрести завалы ЕГАИС",
    "otchety": "📱 Мастера ждут твоего «добро»",
    "zametki": "✉️ Почта из леса",
    "zakryt": "🔒 Захлопнуть освидетельствованные",
    "chernoviki": "📝 Черновики без билета грустят",
}

# Уровни — по классам возраста древостоя.
ZVANIYA = [
    "Шишка", "Всход", "Самосев", "Подрост", "Молодняк", "Жердняк", "Средневозрастный",
    "Приспевающий", "Спелый", "Перестойный 😎", "Вековой дуб", "Леший",
]

SHUTKI = [
    "Лес рубят — XP летят.",
    "Акт сам себя не составит. Проверено.",
    "ЕГАИС не спит, и ты не спи. Шутка, иди спать.",
    "Каждый наряд — это маленькая победа над бумагой.",
    "Просрочка — как клещ: лучше заметить сразу.",
    "Кубометр к кубометру — вот и делянка.",
    "Сегодня без боссов? Подозрительно тихо в лесу…",
]


def ensure(conn) -> None:
    conn.executescript(SCHEMA)


def _cena_urovnya(n):
    """XP, чтобы перейти с уровня n на n+1."""
    return 200 + 100 * n


def uroven(xp):
    n, ost = 1, xp
    while ost >= _cena_urovnya(n):
        ost -= _cena_urovnya(n)
        n += 1
    return {
        "n": n,
        "zvanie": ZVANIYA[min(n, len(ZVANIYA)) - 1],
        "xp_v_urovne": ost,
        "nado": _cena_urovnya(n),
    }


def _sync_den(conn, user_id, items, segodnya, now):
    """Запомнить квесты дня и отметить выполненные (пропавшие из «Ждёт меня»)."""
    den = segodnya.isoformat()
    seychas = {i["kod"]: i for i in items}
    # что было до этого обновления (для «перетёк в более страшный»)
    snimok = {r[0]: r[1] for r in conn.execute(
        "SELECT kod, count_now FROM kvest_den WHERE user_id=? AND den=?", (user_id, den)).fetchall()}
    for it in items:
        conn.execute(
            """INSERT INTO kvest_den (user_id, den, kod, tone, title, hint, screen, params, count0, count_now)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id, den, kod) DO UPDATE SET
                 count_now=excluded.count_now, hint=excluded.hint, tone=excluded.tone,
                 params=excluded.params, done_at=NULL""",
            (user_id, den, it["kod"], it["tone"], it["title"], it.get("hint") or "", it["screen"],
             json.dumps(it.get("params") or {}, ensure_ascii=False), it["count"], it["count"]),
        )
    rows = conn.execute(
        "SELECT kod, count0 FROM kvest_den WHERE user_id=? AND den=? AND done_at IS NULL", (user_id, den)
    ).fetchall()
    for kod, _count0 in rows:
        if kod in seychas:
            continue
        hud = PEREHOD.get(kod)
        if hud and hud in seychas and seychas[hud]["count"] > (snimok.get(hud) or 0):
            # не сделали, а стало хуже — квест провален, XP нет
            conn.execute("UPDATE kvest_den SET count_now=0, done_at='провален' WHERE user_id=? AND den=? AND kod=?",
                         (user_id, den, kod))
            continue
        conn.execute("UPDATE kvest_den SET count_now=0, done_at=? WHERE user_id=? AND den=? AND kod=?",
                     (now, user_id, den, kod))
    conn.commit()


def _xp_po_dnyam(conn, user, user_id, s_dnya):
    """{ 'YYYY-MM-DD': {xp, kvestov, istochniki: {kod: n}} }"""
    dni = {}

    def add(d, xp, kod=None, n=0, kvest=0):
        if not d:
            return
        x = dni.setdefault(d, {"xp": 0, "kvestov": 0, "istochniki": {}})
        x["xp"] += xp
        x["kvestov"] += kvest
        if kod:
            x["istochniki"][kod] = x["istochniki"].get(kod, 0) + n

    ot = s_dnya.isoformat()
    login = user.get("login")
    for kod, _podp, xp, sql, avtor in ISTOCHNIKI:
        params = [ot]
        if avtor:
            sql = sql.format(avtor=f"AND ({avtor} IS NULL OR {avtor} = '' OR {avtor} = ?)")
            params.append(login)
        try:
            for d, n in conn.execute(sql, params).fetchall():
                add(d, xp * n, kod, n)
        except Exception:  # noqa: BLE001 — таблицы может не быть в старой базе
            continue

    for den, tone, n in conn.execute(
        "SELECT den, tone, COUNT(*) FROM kvest_den WHERE user_id=? AND den >= ? AND done_at IS NOT NULL "
        "AND done_at != 'провален' GROUP BY den, tone", (user_id, ot)
    ).fetchall():
        add(den, XP_KVEST.get(tone, 20) * n, "kvesty", n, kvest=n)

    for d, n in conn.execute(
        "SELECT date(done_at) d, COUNT(*) FROM kvest_svoi WHERE user_id=? AND deleted=0 AND done_at >= ? GROUP BY d",
        (user_id, ot),
    ).fetchall():
        add(d, min(XP_SVOI * n, XP_SVOI_LIMIT_DEN), "svoi", n, kvest=n)
    return dni


def _zachten(x):
    return bool(x) and (x["kvestov"] > 0 or x["xp"] >= STREAK_MIN_XP)


def seriya(dni, segodnya):
    """Дней подряд с делом. Выходные серию не рвут; сегодня ещё не вечер —
    если сегодня пусто, считаем от вчера."""
    n = 0
    d = segodnya
    if not _zachten(dni.get(d.isoformat())):
        d -= timedelta(days=1)
    for _ in range(ISTORIYA_DNEY):
        x = dni.get(d.isoformat())
        if _zachten(x):
            n += 1
        elif d.weekday() < 5:
            break
        d -= timedelta(days=1)
    return n


def _achivki(conn, dni, items, ser, user_id):
    vsego = {}
    for x in dni.values():
        for k, n in x["istochniki"].items():
            vsego[k] = vsego.get(k, 0) + n
    svoi = vsego.get("svoi", 0)
    spisok = [
        ("pervaya", "Первая кровь", "Закрыт первый квест", vsego.get("kvesty", 0) + svoi >= 1),
        ("kolokolchik", "Чистый колокольчик", "«Ждёт меня» пуст", not items),
        ("akty10", "Актовый зал", "10 актов освидетельствования", vsego.get("akty", 0) >= 10),
        ("naryady100", "Нарядчик", "100 нарядов", vsego.get("naryady", 0) >= 100),
        ("dok50", "Бумажный тигр", "50 документов", vsego.get("dokumenty", 0) >= 50),
        ("seriya5", "Неделя огня", "5 рабочих дней подряд", ser >= 5),
        ("seriya20", "Месяц без прогулов", "20 рабочих дней подряд", ser >= 20),
        ("bossy", "Охотник на боссов", "Закрыто 5 боссов", _bossov(conn, user_id) >= 5),
        ("svoi10", "Сам себе начальник", "10 своих квестов", svoi >= 10),
        ("tabel500", "Табельщик", "500 строк табеля", vsego.get("tabel", 0) >= 500),
    ]
    return [{"kod": k, "title": t, "hint": h, "est": bool(e)} for k, t, h, e in spisok]


def _bossov(conn, user_id):
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM kvest_den WHERE user_id=? AND tone='danger' AND done_at IS NOT NULL "
            "AND done_at != 'провален'", (user_id,)).fetchone()[0]
    except Exception:  # noqa: BLE001
        return 0


def _kvest(row, xp_tone):
    kod, tone, title, hint, screen, params, count0, count_now, done_at = row
    vid = {"danger": "boss", "warning": "main"}.get(tone, "side")
    return {
        "id": f"z:{kod}",
        "kod": kod,
        "vid": vid,
        "title": NAZVANIYA.get(kod, title),
        "podpis": title,
        "hint": hint,
        "screen": screen,
        "params": json.loads(params or "{}"),
        "count0": count0,
        "count_now": count_now,
        "xp": xp_tone.get(tone, 20),
        "done": bool(done_at) and done_at != "провален",
        "proval": done_at == "провален",
    }


def sobrat(conn, user, segodnya=None, now=None):
    ensure(conn)
    segodnya = segodnya or date.today()
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_id = user.get("id") or 0
    items = zhdet.sobrat(conn, user, segodnya)
    _sync_den(conn, user_id, items, segodnya, now)

    kvesty = [_kvest(r, XP_KVEST) for r in conn.execute(
        "SELECT kod, tone, title, hint, screen, params, count0, count_now, done_at FROM kvest_den "
        "WHERE user_id=? AND den=? ORDER BY CASE tone WHEN 'danger' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, kod",
        (user_id, segodnya.isoformat()),
    ).fetchall()]

    svoi = [
        {"id": r[0], "title": r[1], "srok": r[2], "done": bool(r[3]), "done_at": r[3], "xp": XP_SVOI}
        for r in conn.execute(
            "SELECT id, title, srok, done_at FROM kvest_svoi WHERE user_id=? AND deleted=0 AND "
            "(done_at IS NULL OR date(done_at) = ?) ORDER BY done_at IS NOT NULL, COALESCE(srok, '9999'), id",
            (user_id, segodnya.isoformat()),
        ).fetchall()
    ]

    dni = _xp_po_dnyam(conn, user, user_id, segodnya - timedelta(days=ISTORIYA_DNEY))
    xp_vsego = sum(x["xp"] for x in dni.values())
    ser = seriya(dni, segodnya)
    nedelya = []
    for i in range(6, -1, -1):
        d = segodnya - timedelta(days=i)
        x = dni.get(d.isoformat())
        nedelya.append({"den": d.isoformat(), "xp": x["xp"] if x else 0, "zachten": _zachten(x),
                        "vyhodnoy": d.weekday() >= 5})

    try:
        lut = [
            {"id": r[0], "doc_type": r[1], "file_name": r[2], "created_at": r[3], "delyanka_id": r[4]}
            for r in conn.execute(
                "SELECT id, doc_type, file_name, created_at, delyanka_id FROM documents WHERE status='готов' "
                "AND created_at >= ? AND (created_by IS NULL OR created_by = '' OR created_by = ?) "
                "ORDER BY created_at DESC LIMIT 8",
                ((segodnya - timedelta(days=7)).isoformat(), user.get("login")),
            ).fetchall()
        ]
    except Exception:  # noqa: BLE001
        lut = []

    segodnya_x = dni.get(segodnya.isoformat()) or {"xp": 0, "istochniki": {}}
    podpisi = {k: p for k, p, *_ in ISTOCHNIKI}
    podpisi.update({"kvesty": "Квесты «Ждёт меня»", "svoi": "Свои квесты"})
    return {
        "den": segodnya.isoformat(),
        "xp": xp_vsego,
        "uroven": uroven(xp_vsego),
        "segodnya_xp": segodnya_x["xp"],
        "segodnya_za_chto": [
            {"kod": k, "title": podpisi.get(k, k), "n": n} for k, n in segodnya_x["istochniki"].items()
        ],
        "seriya": ser,
        "nedelya": nedelya,
        "kvesty": kvesty,
        "svoi": svoi,
        "lut": lut,
        "achivki": _achivki(conn, dni, items, ser, user_id),
        "shutka": SHUTKI[segodnya.toordinal() % len(SHUTKI)],
        "pravila": {
            "kvest": XP_KVEST, "svoi": XP_SVOI, "svoi_limit": XP_SVOI_LIMIT_DEN,
            "rabota": [{"kod": k, "title": p, "xp": xp} for k, p, xp, *_ in ISTOCHNIKI],
            "seriya_min_xp": STREAK_MIN_XP,
        },
    }


@router.get("")
def kvesty(user=Depends(get_current_user), conn=Depends(get_conn)):
    return sobrat(conn, user)


class SvoyIn(BaseModel):
    title: str
    srok: Optional[str] = None


def _moy(conn, user, kid):
    row = conn.execute("SELECT id FROM kvest_svoi WHERE id=? AND user_id=? AND deleted=0",
                       (kid, user.get("id") or 0)).fetchone()
    if not row:
        raise HTTPException(404, "Квест не найден")


@router.post("/svoi")
def dobavit(body: SvoyIn, user=Depends(get_current_user), conn=Depends(get_conn)):
    ensure(conn)
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "Напиши, что надо сделать")
    cur = conn.execute("INSERT INTO kvest_svoi (user_id, title, srok) VALUES (?,?,?)",
                       (user.get("id") or 0, title[:200], (body.srok or None)))
    conn.commit()
    return {"id": cur.lastrowid}


@router.post("/svoi/{kid}/done")
def otmetit(kid: int, done: bool = True, user=Depends(get_current_user), conn=Depends(get_conn)):
    ensure(conn)
    _moy(conn, user, kid)
    conn.execute("UPDATE kvest_svoi SET done_at=? WHERE id=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S") if done else None, kid))
    conn.commit()
    return {"ok": True}


@router.delete("/svoi/{kid}")
def udalit(kid: int, user=Depends(get_current_user), conn=Depends(get_conn)):
    ensure(conn)
    _moy(conn, user, kid)
    conn.execute("UPDATE kvest_svoi SET deleted=1 WHERE id=?", (kid,))
    conn.commit()
    return {"ok": True}
