# -*- coding: utf-8 -*-
"""«Как работает сайт» — живая схема (Влад, 04.11.2026: «нарисовать схему
работы сайта, от чего что зависит, чтобы работник мог посмотреть, что
надо сделать»).

Сама схема (узлы, стрелки, пояснения) — на фронте (pages/Skhema.jsx).
Здесь только живые цифры для узлов: сколько делянок на каждом этапе,
сколько участков культур ждут инвентаризацию, сколько открытых проб, кто
сегодня отметился, сколько задач просрочено — и список «Ждёт меня».
Каждый счётчик отказоустойчив: нет таблицы — нет цифры."""
from datetime import date

from fastapi import APIRouter, Depends

from app import legacy_bridge  # noqa: F401
from app import raboty_sotrudnika as rs
from app.auth import require_office_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/skhema", tags=["skhema"])


def _odno(conn, sql, args=()):
    try:
        r = conn.execute(sql, args).fetchone()
        return r[0] if r else None
    except Exception:  # noqa: BLE001
        return None


def zhivye_cifry(conn, user):
    segodnya = date.today()
    sd = segodnya.isoformat()
    u = {}

    # делянки по этапам
    try:
        from app import etap
        rows = [{"id": r[0], "status": r[1]} for r in conn.execute("SELECT id, status FROM delyanka").fetchall()]
        po = {}
        for e in etap.etapy(conn, rows).values():
            po[e["kod"]] = po.get(e["kod"], 0) + 1
        for k, v in po.items():
            u[f"del_{k}"] = v
    except Exception:  # noqa: BLE001
        pass

    # ЕГАИС: когда последний раз грузили выгрузку
    imp = _odno(conn, "SELECT MAX(imported_at) FROM egais_snapshot")
    if imp:
        u["egais_imported_at"] = str(imp)[:16]
        try:
            dney = (segodnya - date.fromisoformat(str(imp)[:10])).days
            u["egais_dney"] = dney
        except ValueError:
            pass

    # лесные культуры
    if rs._est_tablica(conn, "lesokultury_uchastok"):
        akt = conn.execute(
            "SELECT id, god_sozdaniya FROM lesokultury_uchastok WHERE COALESCE(status,'активен') = 'активен'"
        ).fetchall()
        u["lk_aktivnyh"] = len(akt)
        bylo = {}
        if rs._est_tablica(conn, "lesokultury_meropriyatiya"):
            for uid, tip in conn.execute("SELECT uchastok_id, tip FROM lesokultury_meropriyatiya").fetchall():
                bylo.setdefault(uid, set()).add(tip)
        nado = 0
        for uid, god in akt:
            try:
                vozrast = segodnya.year - int(str(god).strip()[:4])
            except (TypeError, ValueError):
                continue
            tip = {1: "Инвентаризация 1-го года", 3: "Инвентаризация 3-го года"}.get(vozrast)
            if tip and tip not in bylo.get(uid, set()):
                nado += 1
        u["lk_inventarizaciya"] = nado
        u["lk_meropriyatiy_god"] = _odno(
            conn, "SELECT COUNT(*) FROM lesokultury_meropriyatiya WHERE substr(created_at,1,4)=?", (str(segodnya.year),))

    # рубки ухода
    if rs._est_tablica(conn, "uhody_proby"):
        u["proby_otkryty"] = _odno(conn, "SELECT COUNT(*) FROM uhody_proby WHERE completed_at IS NULL")
        u["proby_zakryty_god"] = _odno(
            conn, "SELECT COUNT(*) FROM uhody_proby WHERE completed_at IS NOT NULL AND substr(completed_at,1,4)=?",
            (str(segodnya.year),))

    # люди — сегодня
    u["lyudey"] = _odno(conn, "SELECT COUNT(*) FROM sotrudniki WHERE is_active=1")
    if rs._est_tablica(conn, "tabel_zapis"):
        u["tabel_segodnya"] = _odno(conn, "SELECT COUNT(*) FROM tabel_zapis WHERE data=?", (sd,))
    if rs._est_tablica(conn, "attendance_marks"):
        u["otmetok_segodnya"] = _odno(
            conn, "SELECT COUNT(DISTINCT sotrudnik_id) FROM attendance_marks WHERE substr(created_at,1,10)=?", (sd,))
    if rs._est_tablica(conn, "otchet_smeny"):
        u["smen_segodnya"] = _odno(conn, "SELECT COUNT(*) FROM otchet_smeny WHERE deleted=0 AND data=?", (sd,))
    if rs._est_tablica(conn, "work_plan"):
        u["zadach_aktivnyh"] = _odno(conn, "SELECT COUNT(*) FROM work_plan WHERE status='активна'")
        u["zadach_prosrocheno"] = _odno(conn, "SELECT COUNT(*) FROM work_plan WHERE status='активна' AND data < ?", (sd,))
    if rs._est_tablica(conn, "brigada"):
        u["brigad"] = _odno(conn, "SELECT COUNT(*) FROM brigada WHERE is_active=1")
    if rs._est_tablica(conn, "tehnika"):
        u["tehniki"] = _odno(conn, "SELECT COUNT(*) FROM tehnika WHERE aktivna=1")
    return {k: v for k, v in u.items() if v is not None}


@router.get("")
def skhema(user=Depends(require_office_or_master), conn=Depends(get_conn)):
    from app.routers import zhdet
    try:
        zh = zhdet.sobrat(conn, user)
    except Exception:  # noqa: BLE001
        zh = []
    return {"segodnya": date.today().isoformat(), "uzly": zhivye_cifry(conn, user),
            "zhdet": {i["kod"]: i for i in zh}, "zhdet_spisok": zh}
