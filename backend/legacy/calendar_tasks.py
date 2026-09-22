# -*- coding: utf-8 -*-
"""
"Рабочий календарь" — задачи лесничего с разной периодичностью (разово,
раз в месяц/квартал/полгода/год, "сезонные"), чтобы не держать в голове,
что и когда нужно сдать/сделать. См. screens/calendar/.

КЛЮЧЕВАЯ ИДЕЯ: таблица calendar_tasks хранит только ШАБЛОН задачи
(название + правило периодичности), а НЕ список всех прошлых/будущих дат.
Конкретный "текущий" срок вычисляется на лету функцией compute_status() по
сегодняшней дате — благодаря этому повторяющаяся задача не требует ни
фоновой генерации будущих записей, ни очистки устаревших. Выполнение
конкретного периода фиксируется в calendar_completions по period_key
(строка YYYY-MM-DD того самого срока, который был закрыт) — как только
наступает следующий период с другим period_key, задача снова становится
невыполненной автоматически, без каких-либо действий по обслуживанию.

Типы периодичности (поле recurrence) и recurrence_config_json:
    once        {"date": "YYYY-MM-DD"}                       — разовая
    monthly     {"day": 5}                                    — N-го числа каждого месяца
    quarterly   {"months": [3,6,9,12], "day": 10}              — N-го числа месяцев из списка
    semiannual  {"months": [6,12], "day": 10}                  — N-го числа месяцев из списка
    annual      {"month": 1, "day": 20}                        — раз в год
    seasonal    {"start_month":4,"start_day":1,"end_month":5,"end_day":15}
                — сезонная работа: "срок" — конец окна (дедлайн), но также
                  видно, что сезон уже идёт (see status="in_season")

Если день (day) больше числа дней в конкретном месяце (например, 31 для
февраля) — используется последний день этого месяца (safe_date).
"""
import calendar
import json
import sqlite3
from datetime import date, timedelta

RECURRENCE_LABELS = {
    "once": "Разово",
    "monthly": "Ежемесячно",
    "quarterly": "Ежеквартально",
    "semiannual": "Раз в полгода",
    "annual": "Ежегодно",
    "seasonal": "Сезонная (диапазон дат)",
}

# Горизонт "скоро" для группировки в UI (дней вперёд от сегодня).
DUE_SOON_DAYS = 14

# Сколько последних выполненных периодов держать в разделе "Недавно
# выполнено" (по времени отметки, не по количеству задач).
RECENTLY_DONE_DAYS = 30


def _safe_date(year: int, month: int, day: int) -> date:
    """date(), но день сверх числа дней в месяце (31 для месяца с 30-ю и
    т.п.) обрезается до последнего дня месяца — иначе задача с "day": 31
    падала бы с ValueError в месяцах короче."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _config(task: dict) -> dict:
    raw = task.get("recurrence_config_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _candidate_dates(recurrence: str, config: dict, year_from: int, year_to: int) -> list[date]:
    """Список дат-сроков для данного правила периодичности в диапазоне лет
    [year_from, year_to] включительно — окно в 1 год до и 1 год после
    сегодняшнего достаточно, чтобы гарантированно найти и ближайший
    прошедший, и ближайший будущий срок (в т.ч. на стыке декабря/января)."""
    dates: list[date] = []

    if recurrence == "once":
        raw = config.get("date")
        if raw:
            try:
                y, m, d = (int(x) for x in raw.split("-"))
                dates.append(date(y, m, d))
            except (ValueError, TypeError):
                pass
        return dates

    if recurrence == "monthly":
        day = int(config.get("day", 1))
        for year in range(year_from, year_to + 1):
            for month in range(1, 13):
                dates.append(_safe_date(year, month, day))
        return dates

    if recurrence in ("quarterly", "semiannual"):
        default_months = [3, 6, 9, 12] if recurrence == "quarterly" else [6, 12]
        months = config.get("months") or default_months
        day = int(config.get("day", 10))
        for year in range(year_from, year_to + 1):
            for month in months:
                dates.append(_safe_date(year, int(month), day))
        return dates

    if recurrence == "annual":
        month = int(config.get("month", 1))
        day = int(config.get("day", 1))
        for year in range(year_from, year_to + 1):
            dates.append(_safe_date(year, month, day))
        return dates

    if recurrence == "seasonal":
        # "Срок" сезонной задачи — конец окна (дедлайн); начало окна нужно
        # отдельно только для статуса "сезон уже идёт" (см. compute_status).
        end_month = int(config.get("end_month", 5))
        end_day = int(config.get("end_day", 1))
        for year in range(year_from, year_to + 1):
            dates.append(_safe_date(year, end_month, end_day))
        return dates

    return dates


def compute_status(task: dict, completions: set[str], today: date | None = None) -> dict:
    """Вычисляет для ОДНОЙ задачи её текущее состояние на дату today
    (по умолчанию — реальное "сегодня"): ближайший актуальный срок,
    просрочена ли она, выполнен ли он уже.

    completions — множество period_key (строк "YYYY-MM-DD"), для которых
    по этой задаче уже есть отметка о выполнении (calendar_completions);
    передаётся снаружи, чтобы не дёргать БД по разу на задачу.

    Возвращает dict:
        due_date       — date текущего/следующего срока (или None для
                          разовой уже выполненной задачи — дальше сроков нет)
        period_key     — due_date в виде "YYYY-MM-DD" (ключ для отметки)
        is_done         — есть ли отметка о выполнении именно для этого periода
        state           — "overdue" | "due_today" | "due_soon" | "upcoming" |
                          "done" (разовая, выполненная, следующего срока нет)
        in_season       — только для recurrence="seasonal": сегодня внутри
                          окна [start, end] текущего года (даже если сам
                          дедлайн ещё не наступил)
    """
    if today is None:
        today = date.today()

    recurrence = task.get("recurrence", "once")
    config = _config(task)

    candidates = sorted(_candidate_dates(recurrence, config, today.year - 1, today.year + 1))

    # Задачу не считаем просроченной за периоды ДО того, как она вообще
    # была создана — иначе повторяющаяся задача, добавленная сегодня,
    # немедленно показалась бы "просроченной с прошлого квартала", хотя
    # её физически не существовало и выполнить её тогда было нельзя.
    created_raw = task.get("created_at")
    if created_raw:
        try:
            created_date = date.fromisoformat(str(created_raw)[:10])
            candidates = [d for d in candidates if d >= created_date]
        except ValueError:
            pass

    in_season = False
    if recurrence == "seasonal":
        start_month = int(config.get("start_month", 4))
        start_day = int(config.get("start_day", 1))
        season_start = _safe_date(today.year, start_month, start_day)
        season_end = _safe_date(today.year, int(config.get("end_month", 5)), int(config.get("end_day", 1)))
        if season_start <= season_end:
            in_season = season_start <= today <= season_end
        else:
            # Сезон, переходящий через Новый год (например, ноябрь–март) —
            # редкий случай для лесного хозяйства, но на всякий случай.
            in_season = today >= season_start or today <= season_end

    past_due = [d for d in candidates if d <= today and str(d) not in completions]
    if past_due:
        due_date = max(past_due)
    else:
        future_due = [d for d in candidates if d > today]
        due_date = min(future_due) if future_due else None

    if due_date is None:
        return {
            "due_date": None, "period_key": None, "is_done": True,
            "state": "done", "in_season": in_season,
        }

    period_key = str(due_date)
    is_done = period_key in completions

    if is_done:
        state = "done"
    elif due_date < today:
        state = "overdue"
    elif due_date == today:
        state = "due_today"
    elif due_date <= today + timedelta(days=DUE_SOON_DAYS):
        state = "due_soon"
    else:
        state = "upcoming"

    return {
        "due_date": due_date, "period_key": period_key, "is_done": is_done,
        "state": state, "in_season": in_season,
    }


# --------------------------------------------------------------------------- #
#   CRUD
# --------------------------------------------------------------------------- #
def list_tasks(conn: sqlite3.Connection, include_inactive: bool = False) -> list[dict]:
    """Возвращает задачи вместе с вычисленным текущим статусом (см.
    compute_status) — то, что напрямую нужно экрану для отрисовки списка."""
    query = "SELECT id, title, description, category, recurrence, recurrence_config_json, active, created_at FROM calendar_tasks"
    if not include_inactive:
        query += " WHERE active = 1"
    query += " ORDER BY id DESC"
    rows = conn.execute(query).fetchall()
    cols = ["id", "title", "description", "category", "recurrence", "recurrence_config_json", "active", "created_at"]
    tasks = [dict(zip(cols, r)) for r in rows]

    completions_by_task: dict[int, set[str]] = {}
    for task_id, period_key in conn.execute("SELECT task_id, period_key FROM calendar_completions"):
        completions_by_task.setdefault(task_id, set()).add(period_key)

    today = date.today()
    for task in tasks:
        status = compute_status(task, completions_by_task.get(task["id"], set()), today)
        task.update(status)

    return tasks


def get_task(conn: sqlite3.Connection, task_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, title, description, category, recurrence, recurrence_config_json, active, created_at "
        "FROM calendar_tasks WHERE id = ?", (task_id,),
    ).fetchone()
    if row is None:
        return None
    cols = ["id", "title", "description", "category", "recurrence", "recurrence_config_json", "active", "created_at"]
    return dict(zip(cols, row))


def create_task(conn: sqlite3.Connection, title: str, description: str, category: str,
                 recurrence: str, recurrence_config: dict) -> int:
    cur = conn.execute(
        "INSERT INTO calendar_tasks (title, description, category, recurrence, recurrence_config_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (title.strip(), description.strip(), category.strip(), recurrence,
         json.dumps(recurrence_config, ensure_ascii=False)),
    )
    conn.commit()
    return cur.lastrowid


def update_task(conn: sqlite3.Connection, task_id: int, title: str, description: str, category: str,
                 recurrence: str, recurrence_config: dict) -> None:
    conn.execute(
        "UPDATE calendar_tasks SET title=?, description=?, category=?, recurrence=?, recurrence_config_json=? "
        "WHERE id=?",
        (title.strip(), description.strip(), category.strip(), recurrence,
         json.dumps(recurrence_config, ensure_ascii=False), task_id),
    )
    conn.commit()


def delete_task(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("DELETE FROM calendar_completions WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM calendar_tasks WHERE id = ?", (task_id,))
    conn.commit()


def set_task_active(conn: sqlite3.Connection, task_id: int, active: bool) -> None:
    """Пауза повторяющейся задачи (например, отпуск/декрет) без удаления
    истории отметок о выполнении — в отличие от delete_task."""
    conn.execute("UPDATE calendar_tasks SET active = ? WHERE id = ?", (1 if active else 0, task_id))
    conn.commit()


def mark_done(conn: sqlite3.Connection, task_id: int, period_key: str, note: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO calendar_completions (task_id, period_key, note) VALUES (?, ?, ?)",
        (task_id, period_key, note.strip()),
    )
    conn.commit()


def unmark_done(conn: sqlite3.Connection, task_id: int, period_key: str) -> None:
    """Снять отметку о выполнении текущего периода — на случай, если
    отметили по ошибке."""
    conn.execute(
        "DELETE FROM calendar_completions WHERE task_id = ? AND period_key = ?",
        (task_id, period_key),
    )
    conn.commit()


def count_needs_attention(conn: sqlite3.Connection) -> int:
    """Сколько активных задач сейчас просрочены или наступают сегодня —
    используется бейджем уведомлений в шапке приложения (см. main.py:
    TopBar.refresh_notifications), суммируется с количеством отчётов "на
    проверке"."""
    try:
        tasks = list_tasks(conn)
    except sqlite3.OperationalError:
        return 0
    return sum(1 for t in tasks if t["state"] in ("overdue", "due_today"))
