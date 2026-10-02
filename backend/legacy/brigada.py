# -*- coding: utf-8 -*-
"""Бригады и назначения на делянки (экран "Распределение бригад").

Отвечает на вопрос "делянка заканчивается — кого куда двигать дальше":
  - brigada/brigada_sostav — лёгкая группировка sotrudniki с историей
    членства (см. докстринг BRIGADA_SOSTAV_SCHEMA в webext.py);
  - brigada_naznachenie — назначение бригады ИЛИ отдельного рабочего на
    делянку с диапазоном дат;
  - list_delyanki_dlya_raspredeleniya() — сигнал "делянка близка к
    завершению", посчитанный существующими функциями raskhod_v2
    (compute_sortiment_limit_fakt_totals/compute_ploshad_summary), теми
    же, что уже использует app/routers/inspection.py — здесь не
    дублируется расчёт, только пороги и агрегация по бригадам.

Стиль модуля — как у delyanka.py: простые функции, первым аргументом conn,
без классов."""
from datetime import date, datetime, timedelta

import raskhod_v2
from db import get_delyanka_sroki
import delyanka

# Пороги "делянка близка к завершению" — умолчания, принятые пользователем
# при планировании фичи (25.09.2026). Любое из трёх условий срабатывает
# независимо от остальных.
PCT_OSVOENIYA_LIMITA_PORIG = 85
PLOSHAD_OSTATOK_PCT_PORIG = 15
SROK_DNEI_PORIG = 14


def _parse_date(value):
    """Даты в этом приложении хранятся то "дд.мм.гггг" (delyanka.sroki_*
    вводятся вручную в форме), то "гггг-мм-дд" (data_nachala/data_okonchaniya
    новых таблиц ниже, вводятся через <input type="date">) — принимаем
    оба формата, как и app/routers/inspection.py:_parse_date."""
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _today_iso():
    return date.today().strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
#   Бригады и состав
# --------------------------------------------------------------------------- #
def list_brigady(conn):
    """Список бригад + текущий состав + текущее/следующее назначение."""
    cur = conn.execute("SELECT * FROM brigada ORDER BY id")
    cols = [d[0] for d in cur.description]
    brigady = [dict(zip(cols, r)) for r in cur.fetchall()]
    for b in brigady:
        b["sostav"] = get_brigada_sostav(conn, b["id"])
        naz = list_naznacheniya(conn, brigada_id=b["id"])
        b["tekushee_naznachenie"] = _pick_tekushee(naz)
        b["sleduyushee_naznachenie"] = _pick_sleduyushee(naz)
    return brigady


def get_brigada_sostav(conn, brigada_id):
    """Текущий состав бригады (data_vyhoda IS NULL) — список {id, fio,
    dolzhnost} по sotrudniki."""
    rows = conn.execute(
        """SELECT s.id, s.fio, s.dolzhnost
           FROM brigada_sostav bs JOIN sotrudniki s ON s.id = bs.sotrudnik_id
           WHERE bs.brigada_id = ? AND bs.data_vyhoda IS NULL
           ORDER BY s.fio""",
        (brigada_id,),
    ).fetchall()
    return [{"id": r[0], "fio": r[1], "dolzhnost": r[2]} for r in rows]


def create_brigada(conn, nazvanie, brigadir_sotrudnik_id=None):
    cur = conn.execute(
        "INSERT INTO brigada (nazvanie, brigadir_sotrudnik_id) VALUES (?, ?)",
        (nazvanie, brigadir_sotrudnik_id),
    )
    conn.commit()
    return cur.lastrowid


def update_brigada(conn, brigada_id, nazvanie=None, brigadir_sotrudnik_id=-1, is_active=None):
    """brigadir_sotrudnik_id=-1 — не менять (как delyanka_item_id в
    work_plan.update_work_plan_item), None — явно снять бригадира."""
    fields = {}
    if nazvanie is not None:
        fields["nazvanie"] = nazvanie
    if brigadir_sotrudnik_id != -1:
        fields["brigadir_sotrudnik_id"] = brigadir_sotrudnik_id
    if is_active is not None:
        fields["is_active"] = 1 if is_active else 0
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE brigada SET {set_clause} WHERE id=?", (*fields.values(), brigada_id))
    conn.commit()


def set_brigada_sostav(conn, brigada_id, sotrudnik_ids, effective_date=None):
    """Заменяет состав бригады, сохраняя историю членства:
      - текущих участников ЭТОЙ бригады, не попавших в sotrudnik_ids,
        "выводит" (data_vyhoda = effective_date);
      - для sotrudnik_ids, кого сейчас нет в составе этой бригады: если
        человек состоит в ДРУГОЙ бригаде — закрывает ту членскую строку
        и открывает новую здесь; если нигде не состоит — просто открывает
        новую строку."""
    effective_date = effective_date or _today_iso()
    sotrudnik_ids = list(dict.fromkeys(sotrudnik_ids))  # без дублей, сохраняя порядок

    current = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT sotrudnik_id, id FROM brigada_sostav WHERE brigada_id=? AND data_vyhoda IS NULL",
            (brigada_id,),
        ).fetchall()
    }
    for sotrudnik_id, sostav_id in current.items():
        if sotrudnik_id not in sotrudnik_ids:
            conn.execute(
                "UPDATE brigada_sostav SET data_vyhoda=? WHERE id=?",
                (effective_date, sostav_id),
            )

    for sotrudnik_id in sotrudnik_ids:
        if sotrudnik_id in current:
            continue  # уже состоит в этой бригаде
        other_membership = conn.execute(
            """SELECT id FROM brigada_sostav
               WHERE sotrudnik_id=? AND data_vyhoda IS NULL AND brigada_id != ?""",
            (sotrudnik_id, brigada_id),
        ).fetchone()
        if other_membership:
            conn.execute(
                "UPDATE brigada_sostav SET data_vyhoda=? WHERE id=?",
                (effective_date, other_membership[0]),
            )
        conn.execute(
            "INSERT INTO brigada_sostav (brigada_id, sotrudnik_id, data_vstupleniya) VALUES (?, ?, ?)",
            (brigada_id, sotrudnik_id, effective_date),
        )
    conn.commit()


def get_sotrudnik_brigada_history(conn, sotrudnik_id):
    """История членства одного человека — для отчётности/зарплаты по
    периодам (явное решение при планировании фичи: история нужна)."""
    rows = conn.execute(
        """SELECT bs.id, bs.brigada_id, b.nazvanie, bs.data_vstupleniya, bs.data_vyhoda
           FROM brigada_sostav bs JOIN brigada b ON b.id = bs.brigada_id
           WHERE bs.sotrudnik_id = ?
           ORDER BY bs.data_vstupleniya DESC""",
        (sotrudnik_id,),
    ).fetchall()
    cols = ["id", "brigada_id", "brigada_nazvanie", "data_vstupleniya", "data_vyhoda"]
    return [dict(zip(cols, r)) for r in rows]


# --------------------------------------------------------------------------- #
#   Назначения на делянку
# --------------------------------------------------------------------------- #
def create_naznachenie(conn, delyanka_id, data_nachala, data_okonchaniya=None,
                        brigada_id=None, sotrudnik_id=None, kommentariy=None,
                        created_by=None, close_current_for_brigada=True):
    if bool(brigada_id) == bool(sotrudnik_id):
        raise ValueError("Укажите ровно одно: brigada_id ИЛИ sotrudnik_id")

    if close_current_for_brigada and brigada_id:
        _close_current_naznacheniya(conn, brigada_id=brigada_id, before_date=data_nachala)
    if close_current_for_brigada and sotrudnik_id:
        _close_current_naznacheniya(conn, sotrudnik_id=sotrudnik_id, before_date=data_nachala)

    cur = conn.execute(
        """INSERT INTO brigada_naznachenie
               (brigada_id, sotrudnik_id, delyanka_id, data_nachala, data_okonchaniya,
                kommentariy, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (brigada_id, sotrudnik_id, delyanka_id, data_nachala, data_okonchaniya,
         kommentariy, created_by),
    )
    conn.commit()
    return cur.lastrowid


def _close_current_naznacheniya(conn, brigada_id=None, sotrudnik_id=None, before_date=None):
    """Укорачивает дату окончания всех ещё не закрытых назначений этой
    бригады/рабочего до дня перед началом нового — это и есть действие
    "переместить бригаду". Status намеренно не меняется (см. комментарий
    в теле функции)."""
    data_okonchaniya = None
    if before_date:
        d = _parse_date(before_date)
        if d:
            data_okonchaniya = (d - timedelta(days=1)).strftime("%Y-%m-%d")

    where = "brigada_id=?" if brigada_id else "sotrudnik_id=?"
    value = brigada_id if brigada_id else sotrudnik_id
    # Намеренно НЕ трогаем status здесь — только укорачиваем дату
    # окончания. Если проставить status='завершено' сразу же, назначение
    # перестало бы считаться "текущим" (_pick_tekushee) ещё ДО реального
    # дня перевода — бригада на бумаге уезжает с делянки раньше, чем на
    # самом деле. "Завершено" — это отдельное, явное действие лесничего
    # ("Завершить работу здесь", update_naznachenie(status='завершено')),
    # а не побочный эффект планирования следующего шага.
    conn.execute(
        f"""UPDATE brigada_naznachenie
            SET data_okonchaniya=COALESCE(?, data_okonchaniya)
            WHERE {where} AND status NOT IN ('завершено', 'отменено')""",
        (data_okonchaniya, value),
    )


def list_naznacheniya(conn, delyanka_id=None, brigada_id=None, sotrudnik_id=None,
                       status=None, date_from=None, date_to=None):
    q = "SELECT * FROM brigada_naznachenie WHERE 1=1"
    params = []
    if delyanka_id is not None:
        q += " AND delyanka_id=?"
        params.append(delyanka_id)
    if brigada_id is not None:
        q += " AND brigada_id=?"
        params.append(brigada_id)
    if sotrudnik_id is not None:
        q += " AND sotrudnik_id=?"
        params.append(sotrudnik_id)
    if status is not None:
        q += " AND status=?"
        params.append(status)
    if date_from is not None:
        q += " AND (data_okonchaniya IS NULL OR data_okonchaniya >= ?)"
        params.append(date_from)
    if date_to is not None:
        q += " AND data_nachala <= ?"
        params.append(date_to)
    q += " ORDER BY data_nachala"
    cur = conn.execute(q, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_naznachenie(conn, naznachenie_id):
    row = conn.execute("SELECT * FROM brigada_naznachenie WHERE id=?", (naznachenie_id,)).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM brigada_naznachenie WHERE id=?", (naznachenie_id,)).description]
    return dict(zip(cols, row))


def update_naznachenie(conn, naznachenie_id, status=None, data_nachala=None,
                        data_okonchaniya=None, kommentariy=None):
    fields = {}
    if status is not None:
        fields["status"] = status
    if data_nachala is not None:
        fields["data_nachala"] = data_nachala
    if data_okonchaniya is not None:
        fields["data_okonchaniya"] = data_okonchaniya
    if kommentariy is not None:
        fields["kommentariy"] = kommentariy
    if not fields:
        return
    fields["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE brigada_naznachenie SET {set_clause} WHERE id=?",
        (*fields.values(), naznachenie_id),
    )
    conn.commit()


def delete_naznachenie(conn, naznachenie_id):
    conn.execute("DELETE FROM brigada_naznachenie WHERE id=?", (naznachenie_id,))
    conn.commit()


def _is_open(naznachenie):
    """Не отменено и не закрыто вручную явным действием ("Завершить работу
    здесь") — status='отменено'/'завершено' исключают запись из подбора
    "текущее"/"следующее" независимо от дат. Остальные статусы
    (запланировано/активно) — просто разные степени "ещё не закрыто
    вручную", решает дата."""
    return naznachenie["status"] not in ("завершено", "отменено")


def _pick_tekushee(naznacheniya):
    """Из списка назначений (одной бригады/рабочего ИЛИ одной делянки)
    выбирает "текущее" — незакрытое, чья дата начала уже наступила, а дата
    окончания (если задана) ещё не прошла. Специально НЕ опирается только
    на status='активно': _close_current_naznacheniya() при "переместить
    бригаду" лишь укорачивает data_okonchaniya планируемого перевода, не
    трогая status, — иначе назначение мгновенно переставало бы считаться
    текущим ещё до фактического дня перевода."""
    today = _today_iso()
    current = [
        n for n in naznacheniya
        if _is_open(n) and n["data_nachala"] <= today
        and (not n["data_okonchaniya"] or n["data_okonchaniya"] >= today)
    ]
    if not current:
        return None
    return max(current, key=lambda n: n["data_nachala"])


def _pick_sleduyushee(naznacheniya, exclude_delyanka_id=None):
    """Ближайшее ещё не начавшееся незакрытое назначение (опционально
    исключая текущую делянку — чтобы не принять "текущее" за "следующее")."""
    today = _today_iso()
    upcoming = [
        n for n in naznacheniya
        if _is_open(n) and n["data_nachala"] > today
        and (exclude_delyanka_id is None or n["delyanka_id"] != exclude_delyanka_id)
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda n: n["data_nachala"])


# --------------------------------------------------------------------------- #
#   Сигнал "делянка близка к завершению"
# --------------------------------------------------------------------------- #
def _is_zavershaetsya(pct_osvoeniya_limita, pct_ploshad_ostatka, dni_do_sroka):
    if pct_osvoeniya_limita is not None and pct_osvoeniya_limita >= PCT_OSVOENIYA_LIMITA_PORIG:
        return True
    if pct_ploshad_ostatka is not None and pct_ploshad_ostatka <= PLOSHAD_OSTATOK_PCT_PORIG:
        return True
    if dni_do_sroka is not None and dni_do_sroka <= SROK_DNEI_PORIG:
        return True
    return False


def list_delyanki_dlya_raspredeleniya(conn):
    """Для каждой активной делянки — сигнал завершения + текущее
    назначение (кто там сейчас) + следующее назначение ЭТОЙ бригады/
    рабочего (куда они поедут дальше, если уже запланировано)."""
    delyanki = delyanka.list_delyanki(conn, status="активна")
    # % освоения — как в карточке «Освоение делянки» (большее из наряда и
    # ЕГАИС), иначе бригада «не видит», что делянка уже дорублена по ЕГАИС.
    osvoenie = raskhod_v2.compute_osvoenie_batch(conn, [d["id"] for d in delyanki])
    result = []
    for d in delyanki:
        _, items = delyanka.get_delyanka_full(conn, d["id"])

        pct_osvoeniya_limita = (osvoenie.get(d["id"]) or {}).get("pct")
        pct_ploshad_ostatka = None
        if items:

            ploshad_delyanki_sum = 0.0
            ploshad_ostatok_sum = 0.0
            for it in items:
                summ = raskhod_v2.compute_ploshad_summary(conn, it, it["id"])
                ploshad_delyanki_sum += summ["ploshad_delyanki"]
                ploshad_ostatok_sum += summ["ploshad_ostatok"]
            if ploshad_delyanki_sum:
                pct_ploshad_ostatka = round(ploshad_ostatok_sum / ploshad_delyanki_sum * 100, 1)

        srok_zagotovki, srok_vyvozki = get_delyanka_sroki(conn, d["id"])
        dni_do_sroka = None
        vyvozka_dt = _parse_date(srok_vyvozki)
        if vyvozka_dt:
            dni_do_sroka = (vyvozka_dt.date() - date.today()).days

        naz_zdes = list_naznacheniya(conn, delyanka_id=d["id"])
        tekushee = _pick_tekushee(naz_zdes)

        sleduyushee = None
        if tekushee:
            naz_brigady = list_naznacheniya(
                conn,
                brigada_id=tekushee.get("brigada_id"),
                sotrudnik_id=tekushee.get("sotrudnik_id"),
            )
            sleduyushee = _pick_sleduyushee(naz_brigady, exclude_delyanka_id=d["id"])

        result.append({
            **d,
            "pct_osvoeniya_limita": pct_osvoeniya_limita,
            "osvoenie_level": (osvoenie.get(d["id"]) or {}).get("level"),
            "pct_ploshad_ostatka": pct_ploshad_ostatka,
            "srok_okonchaniya_zagotovki": srok_zagotovki,
            "srok_okonchaniya_vyvozki": srok_vyvozki,
            "tekushee_naznachenie": tekushee,
            "sleduyushee_naznachenie": sleduyushee,
            "is_zavershaetsya": _is_zavershaetsya(pct_osvoeniya_limita, pct_ploshad_ostatka, dni_do_sroka),
        })
    return result


def count_zavershayutsya_bez_naznacheniya(conn):
    """Для бейджа на дашборде: сколько делянок близки к завершению, но у
    их текущей бригады/рабочего нет ещё запланированного следующего шага."""
    rows = list_delyanki_dlya_raspredeleniya(conn)
    return sum(1 for r in rows if r["is_zavershaetsya"] and not r["sleduyushee_naznachenie"])
