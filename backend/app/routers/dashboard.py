#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app/routers/dashboard.py — backend для экрана "Дашборд" (Этап 4, второй
переписанный экран после "Настроек").

Референс функциональности: screens/dashboard/screen.py + helpers.py +
widgets.py + weather_worker.py (десктоп). По требованию Этапа 1 (п.2)
логика НЕ переписывается — только оборачивается: те же SQL-запросы, та
же арифметика перерубов/плана-факта/пожарной опасности, что и в
PySide6-версии, просто вызываются из HTTP-эндпоинта, а не из Qt showEvent.

Эндпоинты:
    GET  /api/dashboard/summary         — метрики + таблица "Активные
                                           делянки" + лента "ИИ-аналитика"
                                           + график "Обзор заготовки" +
                                           текущая погода, ОДНИМ запросом
                                           (десктоп тоже строит все секции
                                           Главного экрана за один проход
                                           по открытому соединению — см.
                                           DashboardScreen.load_metrics()).
    POST /api/dashboard/harvest-plan    — задать план заготовки на месяц
                                           (замена диалога
                                           styled_get_item/styled_get_double
                                           из DashboardScreen._handle_set_plan);
                                           возвращает пересчитанный график.
    POST /api/dashboard/weather/refresh — запросить свежую погоду с
                                           Open-Meteo и сохранить в БД
                                           (замена WeatherWorker: тот же
                                           URL и расчёт класса пожарной
                                           опасности, но синхронно внутри
                                           запроса — поход в Open-Meteo
                                           укладывается в 10с, отдельный
                                           BackgroundTasks + опрос статуса
                                           из Этапа 1 п.4 для него избыточны).

──────────────────────────────────────────────────────────────────────
ОКРУЖЕНИЕ (см. AUDIT.md, Этап 0):

1. Этот файл написан самодостаточным: сам открывает sqlite3-соединение с
   PRAGMA WAL/busy_timeout (Этап 2). Если у вас уже есть общий deps.py с
   get_db()/аутентификацией — замените _connect()/добавьте Depends(get_db)
   ниже, чтобы не дублировать логику соединения между роутерами.
   Подключить роутер в app/main.py:
       from app.routers import dashboard
       app.include_router(dashboard.router)

2. compute_items_totals/get_delyanka_items/_fmt_m3 (для расчёта перерубов
   в ленте "ИИ-аналитика") и _compute_fire_danger/_wind_direction_to_text
   (для карточки погоды) — TODO п.1.6 (Блок 5 PLAN_DORABOTKI): раньше
   импортировались напрямую из десктопных screens/raskhod/balance.py и
   screens/dashboard/helpers.py в try/except ImportError с продублированным
   вручную кодом-заглушкой на случай отсутствия PySide6/screens/ на
   сервере. Теперь оба файла-источника сами вычищены от Qt-зависимостей
   (см. их докстринги), а backend использует свои собственные Qt-свободные
   копии той же логики — legacy/raskhod_v2.py (уже существовал, содержит
   compute_items_totals/get_delyanka_items/_fmt_m3 один в один) и новый
   legacy/dashboard_calc.py (_compute_fire_danger/_wind_direction_to_text).
   Никакого try/except и дублирования кода-заглушки больше не нужно —
   backend не зависит ни от PySide6, ни от наличия дерева screens/ рядом.
"""

import datetime
import json
import sqlite3
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import db/config
from app.auth import require_permission
from app.auth import get_current_user
from app.database import get_connection as _connect
from db import (
    get_current_weather,
    update_current_weather,
    set_harvest_plan,
    get_harvest_plan,
)

# См. примечание 2 выше — Qt-свободные копии, backend больше не зависит
# от PySide6/дерева screens/.
from raskhod_v2 import _fmt_m3, compute_osvoenie_batch
from dashboard_calc import _compute_fire_danger, _wind_direction_to_text
import brigada


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Те же координаты по умолчанию, что в screens/dashboard/screen.py
# (Беларусь/Оршанский регион) — вынести в /api/settings при появлении
# индивидуальных координат для конкретного лесничества.
DEFAULT_LATITUDE = 54.5
DEFAULT_LONGITUDE = 30.4

_MONTH_ABBR = (
    "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
)


def _last_n_months(n: int) -> tuple[list[str], list[str]]:
    """1-в-1 копия HarvestChartWidget._last_n_months (widgets.py) — не
    импортируется напрямую по той же причине, что и в примечании 2 выше
    (класс — QWidget), логика координат месяцев Qt не использует."""
    today = datetime.date.today()
    year, month = today.year, today.month
    pairs = []
    for _ in range(n):
        pairs.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    pairs.reverse()
    keys = [f"{y:04d}-{m:02d}" for y, m in pairs]
    labels = [_MONTH_ABBR[m - 1] for _, m in pairs]
    return keys, labels


class HarvestPlanIn(BaseModel):
    period: str  # "YYYY-MM"
    value: float


@router.get("/summary")
def get_summary():
    """Один запрос на весь экран — метрики, таблица делянок, ИИ-лента,
    график и погода. Каждая секция отказоустойчива по отдельности (как
    и в load_metrics() десктопа): если конкретной таблицы в БД ещё нет,
    соответствующая часть ответа просто возвращает "нулевые" значения,
    а не роняет весь эндпоинт."""
    conn = _connect()
    try:
        return {
            "metrics": _build_metrics(conn),
            "plots": _build_plots_table(conn),
            "insights": _build_ai_insights(conn),
            "chart": _build_harvest_chart(conn),
            "weather": get_current_weather(conn),
        }
    finally:
        conn.close()


def _build_metrics(conn: sqlite3.Connection) -> dict:
    # «В работе» — только активные делянки; черновики (импорт МДО без
    # билета) считаются отдельно, иначе цифра расходилась со списком.
    try:
        delyanki_count = conn.execute("SELECT COUNT(*) FROM delyanka WHERE status = 'активна'").fetchone()[0]
        chernoviki_count = conn.execute("SELECT COUNT(*) FROM delyanka WHERE status = 'черновик'").fetchone()[0]
    except sqlite3.OperationalError:
        delyanki_count = chernoviki_count = 0

    try:
        completed_count = conn.execute("SELECT COUNT(*) FROM completed_works").fetchone()[0]
    except sqlite3.OperationalError:
        completed_count = 0

    try:
        volume_row = conn.execute("SELECT SUM(obyom) FROM raskhod_pozitsiya").fetchone()
        volume = volume_row[0] if volume_row and volume_row[0] is not None else 0
    except sqlite3.OperationalError:
        volume = 0

    try:
        ai_queue_count = conn.execute(
            "SELECT COUNT(*) FROM raw_reports WHERE status='на проверке'"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        ai_queue_count = 0
    ai_queue_count = ai_queue_count or 0

    # Заготовлено по ЕГАИС — по активным делянкам, тем же расчётом, что
    # карточка «Освоение делянки» (наряды выше — по журналу расхода).
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM delyanka WHERE status = 'активна'")]
        osv = compute_osvoenie_batch(conn, ids)
        egais_vals = [o["fakt_egais"] for o in osv.values() if o.get("fakt_egais") is not None]
        volume_egais = sum(egais_vals) if egais_vals else None
    except Exception:  # noqa: BLE001 — секция отказоустойчива, как и остальные
        volume_egais = None

    return {
        "delyanki_count": delyanki_count or 0,
        "chernoviki_count": chernoviki_count or 0,
        "volume_egais_m3": volume_egais,
        "volume_egais_m3_fmt": _fmt_m3(volume_egais) if volume_egais is not None else None,
        "completed_count": completed_count or 0,
        "volume_m3": volume or 0,
        "volume_m3_fmt": _fmt_m3(volume),
        "ai_queue_count": ai_queue_count,
        "ai_queue_alert": ai_queue_count > 0,
    }


def _build_plots_table(conn: sqlite3.Connection) -> list[dict]:
    """1-в-1 с _load_plots_table(): последние 5 неархивных делянок."""
    try:
        rows = conn.execute(
            "SELECT id, nazvanie, status, created_at FROM delyanka "
            "WHERE status != 'архив' ORDER BY id DESC LIMIT 5"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    return [
        {"id": r[0], "nazvanie": r[1] or "—", "status": r[2] or "—", "created_at": r[3] or "—"}
        for r in rows
    ]


def _build_ai_insights(conn: sqlite3.Connection) -> list[dict]:
    """1-в-1 с _refresh_ai_insights(): перерубы (top-3 по величине
    превышения) → отчёты в очереди на проверке → 2 последних акта →
    "критичных событий нет", если ничего из этого не нашлось."""
    entries: list[dict] = []

    try:
        delyanka_rows = conn.execute(
            "SELECT id, nazvanie FROM delyanka WHERE status = 'активна'"
        ).fetchall()
    except sqlite3.OperationalError:
        delyanka_rows = []

    # Переруб и «подходит к лимиту» — по тому же освоению, что карточка
    # «Освоение делянки» (большее из наряда и ЕГАИС), с теми же порогами
    # 90 / 100 / 110 %. Раньше здесь сравнивались только наряды с лимитом,
    # и при перерубе по ЕГАИС дашборд писал «Перерубов не найдено».
    try:
        osvoenie = compute_osvoenie_batch(conn, [r[0] for r in delyanka_rows])
    except sqlite3.OperationalError:
        osvoenie = {}
    nazvaniya = {r[0]: r[1] for r in delyanka_rows}
    flagged = [
        (nazvaniya[d], o) for d, o in osvoenie.items()
        if o.get("pct") is not None and o["level"] in ("vnimanie", "preduprezhdenie", "pererub")
    ]
    flagged.sort(key=lambda row: row[1]["pct"], reverse=True)

    for nazvanie, o in flagged[:5]:
        pct = o["pct"]
        if o["level"] == "pererub":
            title = f"Переруб: «{nazvanie or '—'}» — {pct:.0f}% лимита"
            description = (f"Допуск +10% превышен на {-o['mozhno_do_110']:.1f} м³. "
                           "Остановите заготовку и проверьте документы.")
            severity = "critical"
        elif o["level"] == "preduprezhdenie":
            title = f"Лимит выбран: «{nazvanie or '—'}» — {pct:.0f}%"
            description = f"До 110% можно заготовить не больше {max(o['mozhno_do_110'], 0):.1f} м³."
            severity = "warning"
        else:
            title = f"Подходит к лимиту: «{nazvanie or '—'}» — {pct:.0f}%"
            description = f"До 100% осталось {max(o['mozhno_do_100'], 0):.1f} м³."
            severity = "warning"
        entries.append({
            "category": "Освоение",
            "timestamp": "сейчас",
            "title": title,
            "description": description,
            "severity": severity,
        })

    try:
        pending_brigady = brigada.count_zavershayutsya_bez_naznacheniya(conn)
    except Exception:  # noqa: BLE001 — та же защита, что и у остальных секций insights
        pending_brigady = 0

    if pending_brigady:
        n10, n100 = pending_brigady % 10, pending_brigady % 100
        if n10 == 1 and n100 != 11:
            delyanka_word, blizki_word = "делянка", "близка"
        elif 2 <= n10 <= 4 and not (12 <= n100 <= 14):
            delyanka_word, blizki_word = "делянки", "близки"
        else:
            delyanka_word, blizki_word = "делянок", "близки"
        entries.append({
            "category": "Бригады",
            "timestamp": "сейчас",
            "title": f"{pending_brigady} {delyanka_word} {blizki_word} к завершению без плана бригады",
            "description": (
                "Откройте «Распределение бригад», чтобы назначить, куда "
                "направить освобождающиеся бригады."
            ),
            "severity": "warning",
        })

    try:
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM raw_reports WHERE status = ?", ("на проверке",)
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pending_count = 0
    pending_count = pending_count or 0

    if pending_count > 0:
        entries.append({
            "category": "Проверка",
            "timestamp": "сейчас",
            "title": f"На проверке {pending_count} отчёт(ов)",
            "description": (
                "Есть необработанные отчёты рабочих. Откройте Журнал ИИ, "
                "чтобы подтвердить или отклонить их."
            ),
            "severity": "warning",
        })

    try:
        recent_acts = conn.execute(
            "SELECT lesnichestvo, data_vypolneniya FROM completed_works "
            "ORDER BY id DESC LIMIT 2"
        ).fetchall()
    except sqlite3.OperationalError:
        recent_acts = []

    for lesnichestvo, data_vypolneniya in recent_acts:
        entries.append({
            "category": "Акты",
            "timestamp": str(data_vypolneniya or "—"),
            "title": f"Создан акт выполненных работ ({lesnichestvo or '—'})",
            "description": "Новый акт зафиксирован в журнале выполненных работ.",
            "severity": "info",
        })

    if not entries:
        entries.append({
            "category": "Статус",
            "timestamp": "сейчас",
            "title": "Критичных событий нет",
            "description": "Делянок у лимита, отчётов в очереди и новых актов нет.",
            "severity": "info",
        })

    return entries


def _build_harvest_chart(conn: sqlite3.Connection) -> dict:
    """1-в-1 с HarvestChartWidget.update_chart_data(), но возвращает
    абсолютные план/факт по месяцам (не проценты от максимума — в
    QPainter нормировка была нужна только для paintEvent, на фронте её
    сделает сам компонент графика)."""
    month_keys, month_labels = _last_n_months(6)

    plan_by_month = {key: 0.0 for key in month_keys}
    fact_by_month = {key: 0.0 for key in month_keys}

    try:
        saved_plan = get_harvest_plan(conn, month_keys)
    except sqlite3.OperationalError:
        saved_plan = {}
    for year_month, value in (saved_plan or {}).items():
        if year_month in plan_by_month:
            plan_by_month[year_month] = value or 0.0

    try:
        rows = conn.execute(
            "SELECT strftime('%Y-%m', n.data) AS ym, SUM(p.obyom) "
            "FROM raskhod_pozitsiya p JOIN raskhod_naryad n ON p.naryad_id = n.id "
            "WHERE n.data IS NOT NULL GROUP BY ym"
        ).fetchall()
        for year_month, total in rows:
            if year_month in fact_by_month:
                fact_by_month[year_month] = total or 0.0
    except sqlite3.OperationalError:
        pass

    return {
        "months": month_labels,
        "periods": month_keys,
        "plan": [plan_by_month[k] for k in month_keys],
        "fact": [fact_by_month[k] for k in month_keys],
        "total_plan": sum(plan_by_month.values()),
        "total_fact": sum(fact_by_month.values()),
    }


@router.post("/harvest-plan")
def post_harvest_plan(body: HarvestPlanIn, _user=Depends(require_permission("delyanka.edit"))):
    """Замена диалога "✏️ Задать план на месяц" (styled_get_item +
    styled_get_double в DashboardScreen._handle_set_plan) — период и
    значение приходят уже выбранными с фронта, здесь только сохранение
    + пересчитанный график в ответе, чтобы фронту не делать второй
    запрос."""
    conn = _connect()
    try:
        try:
            set_harvest_plan(conn, body.period, body.value)
        except sqlite3.OperationalError as exc:
            raise HTTPException(status_code=500, detail=f"Не удалось сохранить план: {exc}")
        return _build_harvest_chart(conn)
    finally:
        conn.close()


_WEATHER_URL_TEMPLATE = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,relative_humidity_2m,"
    "wind_speed_10m,wind_direction_10m"
)


@router.post("/weather/refresh")
def refresh_weather(_user=Depends(get_current_user)):
    """Синхронный аналог WeatherWorker.run(): тот же URL Open-Meteo и та
    же формула класса пожарной опасности, но выполняется в теле
    HTTP-запроса вместо QThread — кнопка "🔄" на фронте просто ждёт
    ответ (см. примечание в шапке файла про то, почему это не
    BackgroundTasks)."""
    url = _WEATHER_URL_TEMPLATE.format(lat=DEFAULT_LATITUDE, lon=DEFAULT_LONGITUDE)
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            raw = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Не удалось подключиться к сервису погоды: {exc}"
        )

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Некорректный ответ сервиса погоды: {exc}")

    current = payload.get("current")
    if not isinstance(current, dict):
        raise HTTPException(
            status_code=502, detail="Сервис погоды вернул ответ без данных 'current'."
        )

    temperature = current.get("temperature_2m")
    humidity = current.get("relative_humidity_2m")
    wind_speed = current.get("wind_speed_10m")
    wind_direction_deg = current.get("wind_direction_10m")

    fire_class, fire_text = _compute_fire_danger(temperature, humidity)
    data = {
        "temperature": temperature,
        "humidity": humidity,
        "wind_speed": wind_speed,
        "wind_dir": _wind_direction_to_text(wind_direction_deg),
        "fire_danger_class": fire_class,
        "fire_danger_text": fire_text,
    }

    conn = _connect()
    try:
        update_current_weather(conn, data)
        return get_current_weather(conn)
    finally:
        conn.close()
