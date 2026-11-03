# -*- coding: utf-8 -*-
"""«Ждёт меня» — одна кнопка в шапке со списком того, что надо разобрать
(шаг 4 разбора 03.11.2026). Раньше неразобранное лежало в пяти местах:
отчёты с телефона, заметки, Разбор ЕГАИС, сроки актов, черновики делянок.

Каждая строка: {kod, count, title, hint, screen, params, tone}. Пустые
строки не отдаются. Каждый источник отказоустойчив по отдельности — старая
база без какой-то таблицы просто не даёт эту строку."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401
import webext

from app.auth import get_current_user
from app.database import get_conn

router = APIRouter(prefix="/api/zhdet", tags=["zhdet"])

SKORO_DNEY = 7


def _d(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _count(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchone()[0] or 0
    except Exception:  # noqa: BLE001 — таблицы может не быть в старой базе
        return 0


def sobrat(conn, user, segodnya=None):
    segodnya = segodnya or date.today()
    out = []

    def add(kod, count, title, hint, screen, params=None, tone="warning"):
        if count:
            out.append({"kod": kod, "count": count, "title": title, "hint": hint,
                        "screen": screen, "params": params or {}, "tone": tone})

    n = _count(conn, "SELECT COUNT(*) FROM raw_reports WHERE status='на проверке'")
    add("otchety", n, "Отчёты с телефона на проверке", "Одобрить или отклонить", "telefon", {"tab": "otchety"})

    n = _count(
        conn,
        "SELECT COUNT(*) FROM worker_notes WHERE is_read = 0 AND "
        "(recipient_sotrudnik_id IS NULL OR recipient_sotrudnik_id = ?)",
        (user.get("sotrudnik_id"),),
    )
    add("zametki", n, "Непрочитанные заметки рабочих", "Прочитать, ответить", "telefon", {"tab": "zametki"}, "info")

    if webext.has_permission(user, "raskhod.edit"):
        try:
            from app.routers import raskhod
            s = raskhod.egais_review_summary(user=user, conn=conn)
            n = (s.get("korrektirovki_new") or 0) + (s.get("sklady_problem") or 0) + (s.get("fls_prihod_new") or 0)
        except Exception:  # noqa: BLE001
            n = 0
        add("egais", n, "Разбор ЕГАИС", "Корректировки, склады без делянки, приход ФЛС", "raskhod", {"razbor": "1"})

    try:
        from app.routers import inspection
        spisok = inspection.list_inspection(conn=conn)
    except Exception:  # noqa: BLE001
        spisok = []
    prosr, skoro, zakryt = [], [], []
    for r in spisok:
        if r.get("zakryta"):
            continue
        if r.get("osvidetelstvovana"):
            zakryt.append(r)
            continue
        sroki = []
        if r.get("akt_po_ploshadi_do") and not r.get("akt_po_ploshadi_sostavlen"):
            sroki.append(_d(r["akt_po_ploshadi_do"]))
        if r.get("srok_osvidetelstvovaniya"):
            sroki.append(_d(r["srok_osvidetelstvovaniya"]))
        sroki = [s for s in sroki if s]
        if not sroki:
            continue
        srok = min(sroki)
        if srok < segodnya:
            prosr.append(r)
        elif srok <= segodnya + timedelta(days=SKORO_DNEY):
            skoro.append(r)

    def imena(rows):
        names = [r.get("nazvanie") or f"№{r['id']}" for r in rows[:3]]
        return ", ".join(names) + (f" и ещё {len(rows) - 3}" if len(rows) > 3 else "")

    add("akty_prosr", len(prosr), "Акты освидетельствования — срок прошёл", imena(prosr), "inspection",
        {"d": prosr[0]["id"]} if len(prosr) == 1 else {}, "danger")
    add("akty_skoro", len(skoro), f"Акты освидетельствования — срок в ближайшие {SKORO_DNEY} дн.", imena(skoro),
        "inspection", {"d": skoro[0]["id"]} if len(skoro) == 1 else {})
    add("zakryt", len(zakryt), "Освидетельствованы, но не закрыты", "Кнопка «Закрыть освидетельствованные» в Инспекции",
        "inspection", {}, "info")

    n = _count(conn, "SELECT COUNT(*) FROM delyanka WHERE status='черновик'")
    add("chernoviki", n, "Делянки-черновики без лесорубочного билета", "Внести билет — делянка станет активной",
        "plots", {}, "info")
    return out


@router.get("")
def zhdet_menya(user=Depends(get_current_user), conn=Depends(get_conn)):
    items = sobrat(conn, user)
    return {"total": sum(i["count"] for i in items), "items": items}
