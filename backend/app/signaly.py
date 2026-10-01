# -*- coding: utf-8 -*-
"""Оповещения сервера (анализ удобства 01.10.2026): раньше процент
освоения и сроки было видно, только если сам откроешь нужный экран.

- Освоение делянки перешло 90 / 100 / 110 % лимита — тот же расчёт, что
  «Освоение делянки» (raskhod_v2.compute_osvoenie_batch).
- До окончания заготовки, вывозки и до срока освидетельствования (вывозка
  + 30 дней) осталось 14 и 3 дня, и когда срок прошёл.

Уведомление общее (recipient NULL): его видят лесничий на сайте
(колокольчик) и мастера/бригадиры в приложении. Каждое — один раз: что
уже отправлено, помнит таблица signal_sent. Проверка идёт в фоне
(main.py) и сразу после импорта ЕГАИС / сохранения наряда."""
import threading
import time
from datetime import date, datetime, timedelta

from app import legacy_bridge  # noqa: F401
import raskhod_v2
import webext

SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_sent (
    kind TEXT NOT NULL,
    obj_id INTEGER NOT NULL,
    klyuch TEXT NOT NULL,
    sent_at TEXT DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (kind, obj_id, klyuch)
);
"""

POROGI = (90, 100, 110)
SROKI_DNEI = (14, 3)
INTERVAL_SEK = 15 * 60
_lock = threading.Lock()


def _parse(value):
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _uzhe(conn, kind, obj_id, klyuch):
    return conn.execute(
        "SELECT 1 FROM signal_sent WHERE kind=? AND obj_id=? AND klyuch=?", (kind, obj_id, str(klyuch))
    ).fetchone() is not None


def _otmetit(conn, kind, obj_id, klyuch):
    conn.execute("INSERT OR IGNORE INTO signal_sent (kind, obj_id, klyuch) VALUES (?, ?, ?)",
                 (kind, obj_id, str(klyuch)))


def _m3(v):
    return f"{v:.1f}".replace(".", ",")


def _pct(v):
    return (f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}".replace(".", ",")) + "%"


def proverit_osvoenie(conn, delyanki):
    osv = raskhod_v2.compute_osvoenie_batch(conn, [d for d, _ in delyanki])
    sozdano = 0
    for did, nazvanie in delyanki:
        o = osv.get(did) or {}
        pct = o.get("pct")
        if pct is None:
            continue
        # Только самый высокий из ещё не отправленных порогов (делянка,
        # сразу загруженная на 105%, не получает три уведомления подряд).
        dostignuty = [p for p in POROGI if (pct > p if p == 110 else pct >= p)]
        novye = [p for p in dostignuty if not _uzhe(conn, "osvoenie", did, p)]
        if not novye:
            continue
        porog = max(novye)
        if porog == 110:
            text = f"Переруб: «{nazvanie}» — освоено {_pct(pct)} лимита (больше 110%)."
        elif porog == 100:
            text = (f"Лимит выбран: «{nazvanie}» — {_pct(pct)}. До 110% можно ещё "
                    f"{_m3(max(o.get('mozhno_do_110') or 0, 0))} м³.")
        else:
            text = (f"Подходит к лимиту: «{nazvanie}» — {_pct(pct)}. До 100% — "
                    f"{_m3(max(o.get('mozhno_do_100') or 0, 0))} м³, до 110% — "
                    f"{_m3(max(o.get('mozhno_do_110') or 0, 0))} м³.")
        for p in dostignuty:
            _otmetit(conn, "osvoenie", did, p)
        conn.commit()
        webext.notify(conn, "osvoenie", text, related_id=did)
        sozdano += 1
    return sozdano


def proverit_sroki(conn, segodnya=None):
    segodnya = segodnya or date.today()
    rows = conn.execute(
        "SELECT id, nazvanie, srok_okonchaniya_zagotovki, srok_okonchaniya_vyvozki "
        "FROM delyanka WHERE status = 'активна'"
    ).fetchall()
    sozdano = 0
    for did, nazvanie, zag, vyv in rows:
        vyv_d = _parse(vyv)
        sroki = [
            ("zagotovka", "окончание заготовки", _parse(zag)),
            ("vyvozka", "окончание вывозки", vyv_d),
            ("osvid", "освидетельствование", vyv_d + timedelta(days=30) if vyv_d else None),
        ]
        for kod, chto, srok in sroki:
            if srok is None:
                continue
            dney = (srok - segodnya).days
            if dney < 0:
                klyuch = "prosrocheno"
                text = f"Срок прошёл: «{nazvanie}» — {chto} было до {srok:%d.%m.%Y}."
            else:
                pod = [n for n in SROKI_DNEI if dney <= n]
                if not pod:
                    continue
                klyuch = str(min(pod))
                text = f"Через {dney} дн. ({srok:%d.%m.%Y}) — {chto}: «{nazvanie}»."
            obj = f"{kod}:{klyuch}:{srok.isoformat()}"
            if _uzhe(conn, "srok", did, obj):
                continue
            _otmetit(conn, "srok", did, obj)
            conn.commit()
            webext.notify(conn, "srok", text, related_id=did)
            sozdano += 1
    return sozdano


def proverit(conn):
    """Одна проверка всего. Ошибка не должна ронять импорт/наряд, из
    которого её позвали, — тогда просто ничего не отправим."""
    if not _lock.acquire(blocking=False):
        return 0
    try:
        conn.executescript(SCHEMA)
        delyanki = conn.execute("SELECT id, nazvanie FROM delyanka WHERE status = 'активна'").fetchall()
        return proverit_osvoenie(conn, delyanki) + proverit_sroki(conn)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Проверка оповещений не удалась: {exc}")
        return 0
    finally:
        _lock.release()


def zapustit_fon(get_connection):
    def loop():
        time.sleep(20)
        while True:
            try:
                conn = get_connection()
                try:
                    proverit(conn)
                finally:
                    conn.close()
            except Exception as exc:  # noqa: BLE001
                print(f"❌ Фоновая проверка оповещений: {exc}")
            time.sleep(INTERVAL_SEK)

    threading.Thread(target=loop, daemon=True, name="signaly").start()
