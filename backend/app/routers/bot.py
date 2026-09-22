# -*- coding: utf-8 -*-
"""
Роутер "Telegram-бот" — единая точка входа для всех HTTP-эндпоинтов,
которыми backend/legacy/telegram_bot.py пользуется ВМЕСТО прямых
`from db import ...`/`from raskhod import ...`/`from delyanka import ...`
(Этап 4 доработки, План, Блок 3 — "Telegram-бот на единый API", часть 3
"Замена импортов на HTTP-вызовы").

Все эндпоинты защищены `require_permission("bot.access")` — это действие
уже заведено в webext.PERMISSIONS = {"bot.access": ("admin", "bot")} на
Этапе 4/Блок 3/часть 2 (авторизация бота) специально под этот роутер: роль
"bot" не хранится в таблице users — это синтетический пользователь,
которого app/auth.py распознаёт по статическому токену процесса бота
(config.get_bot_service_token(), заголовок Authorization: Bearer ...);
admin тоже допущен, чтобы эндпоинты можно было дёрнуть руками из /docs при
отладке, не поднимая сам бот.

Подчасть 3.1 (сделано): регистрация рабочих в lesorub_directory —
GET/PUT /api/bot/workers/{telegram_id}. Раньше это делал telegram_bot.py
через прямой sqlite3.connect (get_db()/_save_registration) — см.
send_welcome/process_lesnichestvo_step в telegram_bot.py. Логика запросов
здесь — дословно то же самое (тот же SELECT/INSERT/UPDATE по viber_id),
просто вызывается теперь через HTTP, единой точкой правды для бота и
веб-фронтенда.

Подчасть 3.2 (эта правка): отчёты о работе — POST /api/bot/reports
(создание отчёта, раньше save_raw_report писала в raw_reports напрямую
через переданный из telegram_bot.py cursor) и GET /api/bot/reports/duplicate
(проверка на вероятный дубль перед сохранением, раньше
find_recent_duplicate_report из db.py вызывалась telegram_bot.py по месту
с тем же sqlite-соединением). Сама SQL-логика не менялась — INSERT перенесён
в legacy/db.py как новая функция save_raw_report(conn, ...) (раньше
одноимённая функция жила в telegram_bot.py и принимала cursor без
собственного commit — теперь коммитит сама, т.к. вызывается из отдельного
HTTP-запроса без общего вызывающего кода, которое сделало бы commit()
после), find_recent_duplicate_report — та же функция из db.py, что и
раньше, просто вызывается отсюда, а не из telegram_bot.py напрямую.
Фото рабочий по-прежнему передаёт боту через Telegram (bot.download_file),
и бот сохраняет их на диск сам (download_photo в telegram_bot.py — эта
часть не ходит в наш backend вообще, она про Telegram Bot API, поэтому
не переводится на HTTP); сюда, в раздел бота нашего API, попадает уже
готовый photo_path — тот же принцип, что screens/ai_log/ уже использует
для completed_works.photo_path (см. app/routers/ai_log.py: GET /photo
отдаёт файл по абсолютному пути, только если он числится в raw_reports
или completed_works).

Подчасть 3.3 (эта правка): поломки техники и служебные записки —
POST /api/bot/breakdowns (отчёт о поломке + сразу список telegram_id
лесничих для рассылки, раньше это были два отдельных прямых обращения к
db.py — save_breakdown_report и get_lesnichiy_telegram_ids — по общему
sqlite-соединению бота в process_breakdown_step), POST
/api/bot/breakdowns/{id}/notes (лесничий переносит поломку в служебные
записки — раньше add_sluzhebnaya_zametka_from_breakdown вызывалась прямо
из handle_breakdown_add_callback), GET /api/bot/zametki (список активных
записок — раньше list_active_sluzhebnye_zametki вызывалась прямо из
process_zametki_list) и POST /api/bot/zametki/{id}/complete (раньше
complete_sluzhebnaya_zametka вызывалась прямо из
handle_zametka_done_callback). В отличие от подчасти 3.2, здесь сама
SQL-логика никуда не переезжает — все пять функций (get_lesnichiy_
telegram_ids/save_breakdown_report/add_sluzhebnaya_zametka_from_breakdown/
list_active_sluzhebnye_zametki/complete_sluzhebnaya_zametka) и раньше жили
в legacy/db.py, а не в telegram_bot.py (в отличие от save_raw_report из
3.2) — этот роутер просто вызывает их вместо telegram_bot.py.

Подчасть 3.4 (эта правка): остатки на делянке/задачи/отмена отчёта —
GET /api/bot/delyanki (список делянок в квартале для inline-выбора при
запросе остатка — раньше get_active_delyanki_for_bot вызывалась напрямую
из process_balance_step), GET /api/bot/tasks и
POST /api/bot/tasks/{id}/complete (кнопка "Мои задачи" — раньше
get_tasks_for_bot/complete_task_for_bot вызывались напрямую из
handle_message/handle_taskdone_callback), GET /api/bot/raw-reports/last и
DELETE /api/bot/raw-reports/{id} (кнопка "Отменить последний отчёт" —
раньше get_last_raw_report_for_user/cancel_raw_report вызывались напрямую
из process_cancel_last_report(_confirm_step)). Как и в 3.3, сама
SQL-логика никуда не переезжала — все пять функций уже жили в
legacy/db.py, этот роутер просто их вызывает.

Таксационная карточка (get_vydel_card) в этот роутер НЕ добавлена —
прямой своп (аудит, находка "низкий риск"): process_taxation_step в
telegram_bot.py теперь ходит на уже существующий GET /api/taxation/vydel
(app/routers/taxation.py), который вызывает ровно ту же функцию/SQL.

get_remaining_volumes_for_bot (остаток лимита с ЕГАИС-сверкой) в этот
роутер тоже НЕ добавлена — сознательное решение части 3.4 (находка №1
аудита): эта функция в raskhod_v2.py (которым пользуется веб через
GET /api/raskhod/remaining) не делает сверку с ЕГАИС, в отличие от
legacy/raskhod.py (которым бот пользуется сейчас) — перевод на HTTP как
есть тихо потерял бы защиту от переруба. Выбран вариант "б" из двух
предложенных аудитом: бот продолжает вызывать
raskhod.get_remaining_volumes_for_bot(conn, ...) напрямую (см.
handle_balance_callback в telegram_bot.py) — единственное оставшееся
прямое обращение бота к БД после этой правки. Подробности — в
комментарии у соответствующего импорта в telegram_bot.py и в пункте 3.4
PLAN_DORABOTKI.

Остальные эндпоинты (гео-заметки, маршрутизация) добавит подчасть 3.5
плана — этим же файлом, новыми функциями в этом роутере.

Подчасть 3.5 (эта правка, последняя в Блоке 3): гео-заметки —
POST /api/bot/geo-notes (кнопка "📍 Добавить заметку на делянку" —
рабочий присылает геометку через скрепку Telegram, затем текст/фото как
комментарий; раньше это делала _save_geo_note(cursor, ...) в
telegram_bot.py напрямую в sqlite, без похода в db.py). В отличие от
остальных подчастей, здесь INSERT сделан прямо в этом роутере (по
образцу upsert_worker() из подчасти 3.1 выше), а не как новая функция в
legacy/db.py — таблица geo_notes однострочная (нет UPDATE/upsert-логики,
которую стоило бы держать отдельно от роутера), заводить под неё функцию
в db.py показалось лишним усложнением ради одного INSERT.

Маршрутизация сообщений (handle_message/handle_photo/handle_location) и
запуск бота (run_bot) новых эндпоинтов не потребовали — это была уже
готовая "склейка" предыдущих подчастей поверх HTTP-обёрток, которые уже
были в telegram_bot.py к моменту этой правки (подробности — в докстринге
save_geo_note() и run_bot() в telegram_bot.py). Часть 3.5 закрывает
Блок 3 плана целиком.
"""
import sqlite3
import uuid
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import db
import db as legacy_db
import raskhod_v2
import webext

from app.database import get_conn
from app.auth import get_current_user, require_permission
from app.paths import UPLOADS_DIR

router = APIRouter(prefix="/api/bot", tags=["bot"])

# Отчёт с теми же кварталом/выделами/типом работы от того же рабочего в
# пределах этого окна считается вероятным дублем — то же значение по
# умолчанию, что раньше было константой DEDUP_WINDOW_MINUTES в
# telegram_bot.py (там и осталось, просто передаётся сюда параметром
# window_minutes, если понадобится когда-нибудь его переопределить не
# трогая сам бот).
DEFAULT_DEDUP_WINDOW_MINUTES = 240


class WorkerUpsert(BaseModel):
    fio: str
    dolzhnost: str
    lesnichestvo: str


def _check_own_identity(user: dict, telegram_id: str) -> None:
    """Мобильное приложение (Фаза 6, доп. правка — найдено при подготовке к
    работе над мобильным приложением, не было отдельным пунктом плана):
    все эндпоинты этого роутера принимают telegram_id как обычный параметр
    запроса — для самого Telegram-бота (role="bot") это безопасно, бот
    один доверенный процесс на сервере, сам подставляющий telegram_id
    реального собеседника. Но role="worker" — это личный токен КОНКРЕТНОГО
    рабочего (worker_sessions, см. app/auth.py:get_worker_by_token), и до
    этой правки ничто не мешало ему подставить в запрос чужой
    telegram_id/app_identity и прочитать или изменить данные другого
    рабочего — токен проверял только "что это вообще рабочий", не "чьи
    данные он запрашивает". GET /api/bot/work-plan (Фаза 4) с самого начала
    сделан правильно — identity берёт из user["sotrudnik_id"], не из
    параметра запроса; эта функция подтягивает более старые telegram_id-
    эндпоинты (3.1–3.5) к тому же принципу, не переписывая их на
    sotrudnik_id (тем самым сломав совместимость с самим ботом, который
    по-прежнему шлёт настоящий telegram_id, а не app_identity).
    admin по-прежнему не ограничен — эндпоинты этого роутера остаются
    дёргаемыми руками из /docs при отладке под любым telegram_id."""
    if user.get("role") == "worker" and telegram_id != user.get("app_identity"):
        raise HTTPException(403, "Нельзя обращаться к данным другого пользователя")


def _fetch_worker_row(conn, telegram_id: str):
    return conn.execute(
        "SELECT viber_id, fio, dolzhnost, lesnichestvo "
        "FROM lesorub_directory WHERE viber_id = ?",
        (telegram_id,),
    ).fetchone()


def _row_to_worker_dict(row) -> dict:
    viber_id, fio, dolzhnost, lesnichestvo = row
    return {
        "viber_id": viber_id,
        "fio": fio,
        "dolzhnost": dolzhnost,
        "lesnichestvo": lesnichestvo,
    }


@router.get("/workers/{telegram_id}")
def get_worker(
    telegram_id: str,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Профиль рабочего из lesorub_directory по telegram_id (viber_id), или
    404, если он ещё не регистрировался — тем же признаком, каким
    send_welcome в telegram_bot.py раньше отличал нового пользователя от
    уже известного (там — `if user is None`, здесь — статус 404)."""
    _check_own_identity(user, telegram_id)
    row = _fetch_worker_row(conn, telegram_id)
    if row is None:
        raise HTTPException(404, "Рабочий не зарегистрирован")
    return _row_to_worker_dict(row)


@router.put("/workers/{telegram_id}")
def upsert_worker(
    telegram_id: str,
    payload: WorkerUpsert,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Upsert по viber_id — то же самое, что раньше делала
    `_save_registration(cursor, ...)` в telegram_bot.py напрямую в sqlite:
    UPDATE, если запись уже есть (например, у уже работавшего бота
    дозаполняется недостающая должность/лесничество после обновления —
    см. send_welcome), иначе INSERT новой записи."""
    _check_own_identity(user, telegram_id)
    exists = conn.execute(
        "SELECT 1 FROM lesorub_directory WHERE viber_id = ?", (telegram_id,)
    ).fetchone()
    if exists:
        conn.execute(
            "UPDATE lesorub_directory SET fio = ?, dolzhnost = ?, lesnichestvo = ? "
            "WHERE viber_id = ?",
            (payload.fio, payload.dolzhnost, payload.lesnichestvo, telegram_id),
        )
    else:
        conn.execute(
            "INSERT INTO lesorub_directory (viber_id, fio, dolzhnost, lesnichestvo) "
            "VALUES (?, ?, ?, ?)",
            (telegram_id, payload.fio, payload.dolzhnost, payload.lesnichestvo),
        )
    conn.commit()
    row = _fetch_worker_row(conn, telegram_id)
    return _row_to_worker_dict(row)


# ------------------------------------------------------------- отчёты о работе ---
class RawReportIn(BaseModel):
    telegram_id: str
    tip_raboty: str
    kvartal: Optional[str] = None
    vydels: Optional[List[str]] = None
    photo_path: Optional[str] = None
    opisanie: Optional[str] = None


def _duplicate_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "kvartal": row["kvartal"],
        "vydels": row["vydels"],
        "tip_raboty": row["tip_raboty"],
        "data_soobscheniya": row["data_soobscheniya"],
    }


@router.get("/reports/duplicate")
def check_duplicate_report(
    telegram_id: str,
    tip_raboty: str,
    kvartal: Optional[str] = None,
    vydels: Optional[str] = None,
    window_minutes: int = DEFAULT_DEDUP_WINDOW_MINUTES,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Проверка перед сохранением отчёта: не отправлял ли этот же рабочий
    точно такой же отчёт (кв/выд/тип работы) недавно и ещё не проверенный
    лесничим (см. process_report_photo_step в telegram_bot.py). `vydels` —
    список номеров выделов через запятую (как их ввёл рабочий), может
    отсутствовать (например, для "Другая работа", где кварталом/выделом
    отчёт вообще не сопровождается — но туда этот эндпоинт и не вызывается,
    см. докстринг process_other_work_photo_step).
    Возвращает {"duplicate": null}, если совпадений нет, иначе
    {"duplicate": {...}} с данными найденного отчёта — тем же смыслом,
    каким раньше был возврат None/строки из find_recent_duplicate_report
    в db.py (сама функция не изменилась, вызывается отсюда).

    find_recent_duplicate_report обращается к колонкам результата по имени
    (row["data_soobscheniya"] и т.п.) — раньше это работало, потому что
    telegram_bot.py сам открывал соединение с conn.row_factory =
    sqlite3.Row (см. get_db() там). Depends(get_conn) из app/database.py
    отдаёт соединение с row_factory по умолчанию (обычные кортежи) — общий
    для всех роутеров, менять его глобально ради одного вызова рискованно
    (сломало бы позиционную распаковку в других роутерах). Выставляем
    row_factory только на этом соединении, локально для этого запроса —
    conn отсюда больше никуда не передаётся."""
    _check_own_identity(user, telegram_id)
    vydels_list = [v.strip() for v in (vydels or "").split(",") if v.strip()]
    conn.row_factory = sqlite3.Row
    duplicate = legacy_db.find_recent_duplicate_report(
        conn, telegram_id, kvartal, vydels_list, tip_raboty, window_minutes,
    )
    return {"duplicate": _duplicate_row_to_dict(duplicate) if duplicate is not None else None}


@router.post("/reports")
def create_report(
    payload: RawReportIn,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Кладёт отчёт рабочего в буферную таблицу raw_reports на проверку
    лесничим (экран "Журнал ИИ") — раньше это делала save_raw_report в
    telegram_bot.py напрямую через sqlite cursor, теперь — HTTP-эндпоинт,
    вызывающий ту же (перенесённую в db.py) функцию. ФИО берём не из тела
    запроса, а из lesorub_directory по telegram_id — тот же профиль, что
    уже возвращает GET /api/bot/workers/{telegram_id}, чтобы не полагаться
    на возможно устаревшее значение fio, которое бот держит в памяти
    диалога с прошлого шага опроса."""
    _check_own_identity(user, payload.telegram_id)
    worker = _fetch_worker_row(conn, payload.telegram_id)
    if worker is None:
        raise HTTPException(404, "Рабочий не зарегистрирован")
    fio = _row_to_worker_dict(worker)["fio"]

    report_id = legacy_db.save_raw_report(
        conn,
        payload.telegram_id,
        fio,
        payload.kvartal,
        payload.vydels,
        payload.tip_raboty,
        payload.photo_path,
        payload.opisanie,
    )
    return {
        "id": report_id,
        "ispolnitel_fio": fio,
        "kvartal": payload.kvartal,
        "vydels": payload.vydels,
        "tip_raboty": payload.tip_raboty,
        "photo_path": payload.photo_path,
        "opisanie": payload.opisanie,
    }


# ------------------------------------------------- поломки и служебные записки ---
class BreakdownIn(BaseModel):
    telegram_id: str
    detail_text: str
    photo_path: Optional[str] = None


@router.post("/breakdowns")
def create_breakdown(
    payload: BreakdownIn,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Кнопка '⚠️ Поломка' (тракторист/харвестерщик) — раньше
    process_breakdown_step в telegram_bot.py делала это как два прямых
    вызова db.py (save_breakdown_report, затем get_lesnichiy_telegram_ids)
    по одному sqlite-соединению; здесь — один HTTP-запрос, возвращающий
    сразу оба результата, т.к. боту нужны они оба немедленно (id — для
    callback_data кнопки "Добавить в служебные записки", список id —
    чтобы разослать уведомление). fio/dolzhnost, как и в
    POST /api/bot/reports, берём не из тела запроса, а из
    lesorub_directory по telegram_id — тот же принцип: не полагаться на
    значение, которое бот держит в памяти диалога."""
    _check_own_identity(user, payload.telegram_id)
    worker = _fetch_worker_row(conn, payload.telegram_id)
    if worker is None:
        raise HTTPException(404, "Рабочий не зарегистрирован")
    profile = _row_to_worker_dict(worker)

    breakdown_id = legacy_db.save_breakdown_report(
        conn,
        payload.telegram_id,
        profile["fio"],
        profile["dolzhnost"],
        payload.detail_text,
        payload.photo_path,
    )
    lesnichiy_ids = legacy_db.get_lesnichiy_telegram_ids(conn)
    # Уведомление в системе (колокольчик) — рядом с Telegram-рассылкой, не
    # вместо неё: рассылку по lesnichiy_telegram_ids по-прежнему делает
    # бот; здесь запись для веба/мобильного приложения (общая, всем
    # руководителям).
    webext.notify(
        conn, "breakdown",
        f"Поломка: {profile['fio']} ({profile['dolzhnost']}) — {payload.detail_text}",
        related_id=breakdown_id,
    )
    return {
        "id": breakdown_id,
        "fio": profile["fio"],
        "dolzhnost": profile["dolzhnost"],
        "lesnichiy_telegram_ids": lesnichiy_ids,
    }


@router.post("/breakdowns/{breakdown_id}/notes")
def convert_breakdown_to_note(
    breakdown_id: int,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Лесничий нажал inline-кнопку 'Добавить в служебные записки' под
    уведомлением о поломке — раньше handle_breakdown_add_callback в
    telegram_bot.py вызывала add_sluzhebnaya_zametka_from_breakdown(conn,
    ...) напрямую. Возвращает {"zametka_id": null}, если поломка с таким
    id не найдена или уже была обработана раньше (двойное нажатие
    несколькими лесничими одновременно) — тем же смыслом, что раньше был
    у возврата None из add_sluzhebnaya_zametka_from_breakdown, и тем же
    принципом "ожидаемый исход — не HTTP-ошибка", что уже используется в
    GET /api/bot/reports/duplicate (там тоже {"duplicate": null} вместо
    404/409): боту не нужно различать "не найдена" и "уже добавлена" —
    в обоих случаях он просто сообщает лесничему, что кнопка уже
    недействительна.

    add_sluzhebnaya_zametka_from_breakdown обращается к результату
    SELECT по имени колонки (row["dolzhnost"] и т.п.) — тот же нюанс, что
    и в check_duplicate_report (см. её докстринг): Depends(get_conn) не
    выставляет row_factory=sqlite3.Row, выставляем локально, только на
    этом соединении."""
    conn.row_factory = sqlite3.Row
    zametka_id = legacy_db.add_sluzhebnaya_zametka_from_breakdown(conn, breakdown_id)
    return {"zametka_id": zametka_id}


def _zametka_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "text": row["text"],
        "source": row["source"],
        "ispolnitel_fio": row["ispolnitel_fio"],
        "telegram_id": row["telegram_id"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


@router.get("/zametki")
def list_zametki(
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Кнопка 'Служебные заметки' у лесничего — раньше process_zametki_list
    в telegram_bot.py вызывала list_active_sluzhebnye_zametki(conn)
    напрямую. Та же необходимость row_factory=sqlite3.Row, что и в
    convert_breakdown_to_note выше — здесь она нужна ещё и для того,
    чтобы читать колонки по имени в самом роутере при сборке ответа
    (обращение по индексу было бы хрупким к порядку колонок SELECT *)."""
    conn.row_factory = sqlite3.Row
    rows = legacy_db.list_active_sluzhebnye_zametki(conn)
    return [_zametka_row_to_dict(row) for row in rows]


@router.post("/zametki/{zametka_id}/complete")
def complete_zametka(
    zametka_id: int,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Инлайн-кнопка '✅ выполнено' под заметкой — раньше
    handle_zametka_done_callback вызывала complete_sluzhebnaya_zametka(conn,
    ...) напрямую. {"done": false} значит "уже закрыта раньше или не
    найдена" (rowcount == 0) — row_factory здесь не нужен, функция
    возвращает bool по cursor.rowcount, не читает колонки по имени."""
    done = legacy_db.complete_sluzhebnaya_zametka(conn, zametka_id)
    return {"done": done}


# ------------------------------------------- делянки в квартале (запрос остатка) ---
@router.get("/delyanki")
def list_active_delyanki(
    kvartal: str,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Список делянок (уникальные пары выдел + номер лесосеки) в квартале
    для inline-кнопок выбора при запросе остатка — раньше
    process_balance_step в telegram_bot.py вызывала
    get_active_delyanki_for_bot(conn, kvartal) напрямую по общему
    sqlite-соединению бота. Тот же нюанс row_factory, что и в
    check_duplicate_report/convert_breakdown_to_note выше:
    get_active_delyanki_for_bot читает поля по имени в вызывающем коде
    бота (row["vydel"]/row["lesoseka_nomer"]), выставляем sqlite3.Row
    локально."""
    conn.row_factory = sqlite3.Row
    rows = legacy_db.get_active_delyanki_for_bot(conn, kvartal)
    return [
        {"vydel": row["vydel"], "lesoseka_nomer": row["lesoseka_nomer"]}
        for row in rows
    ]


@router.get("/remaining")
def get_remaining(
    kvartal: str,
    vydel: str,
    lesoseka: Optional[str] = None,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Остаток лимита по делянке (кнопка '📊 Остатки' у бота, будущий
    аналог у мобильного приложения) — HTTP-обёртка над
    raskhod_v2.get_remaining_volumes_grouped_for_bot(), которой раньше
    здесь намеренно не было (см. докстринг модуля выше, подчасть 3.4 —
    "единственное оставшееся прямое обращение к БД"): причина отказа была
    в том, что get_remaining_volumes_for_bot в raskhod_v2.py на тот момент
    не делал сверку с ЕГАИС, в отличие от версии, которой пользовался бот
    напрямую через sqlite. Эта причина больше не действует — при починке
    падения бота (raskhod.py оказался перезаписан чужим роутером, находка
    того же дня) заодно восстановили сверку с ЕГАИС именно в
    get_remaining_volumes_grouped_for_bot(), так что прямое обращение к
    БД в telegram_bot.py (handle_balance_callback) теперь можно без потери
    функциональности заменить на этот эндпоинт — сам telegram_bot.py пока
    не трогали, чтобы не смешивать это с работой над мобильным
    приложением; переключить его на HTTP — отдельная маленькая правка на
    будущее, не блокирующая мобильное приложение.

    Возвращает ровно то же, что и сама функция: found/item_ids/grouped/
    last_update/egais_imported_at — grouped уже разложен по
    порода → деловая|дрова → limit/fakt_naryad/fakt_egais/ostatok_safe
    (см. докстринг get_remaining_volumes_grouped_for_bot в raskhod_v2.py),
    мобильное приложение строит из этого свой собственный экран, а не
    переиспользует текстовый формат _format_remaining_reply из бота."""
    result = raskhod_v2.get_remaining_volumes_grouped_for_bot(conn, kvartal, vydel, lesoseka)
    return result


# ------------------------------------------------------------------------ задачи ---
def _task_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "opisanie": row["opisanie"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


@router.get("/tasks")
def list_tasks(
    telegram_id: str,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Кнопка '📋 Мои задачи' — раньше handle_message в telegram_bot.py
    вызывала get_tasks_for_bot(conn, telegram_id) напрямую. Тот же нюанс
    row_factory, что и выше — get_tasks_for_bot возвращает строки как
    sqlite3.Row, если у соединения выставлен соответствующий row_factory
    (см. её докстринг в db.py), а вызывающий код (здесь и раньше в боте)
    читает opisanie/created_at по имени колонки."""
    _check_own_identity(user, telegram_id)
    conn.row_factory = sqlite3.Row
    rows = legacy_db.get_tasks_for_bot(conn, telegram_id)
    return [_task_row_to_dict(row) for row in rows]


@router.post("/tasks/{task_id}/complete")
def complete_task(
    task_id: int,
    telegram_id: str,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Инлайн-кнопка '✅ <задача>' — раньше handle_taskdone_callback в
    telegram_bot.py вызывала complete_task_for_bot(conn, ...) напрямую.
    telegram_id — query-параметр, та же проверка владения задачей, что и
    раньше (WHERE telegram_id=? внутри самого UPDATE в
    complete_task_for_bot, не только здесь) — рабочий не может закрыть
    чужую задачу, даже подобрав/угадав task_id. {"done": false} значит
    "уже закрыта раньше, не найдена или принадлежит другому telegram_id"
    — row_factory здесь не нужен, complete_task_for_bot возвращает bool по
    cursor.rowcount, как и complete_zametka выше. Проверка WHERE
    telegram_id=? в самой complete_task_for_bot защищает только "не тот
    task_id" — она не мешает рабочему подставить ЧУЖОЙ telegram_id и этим
    закрыть чужую задачу; отдельно от неё _check_own_identity() ниже не
    даёт role="worker" действовать не от своего app_identity вообще."""
    _check_own_identity(user, telegram_id)
    done = legacy_db.complete_task_for_bot(conn, task_id, telegram_id)
    return {"done": done}


# ---------------------------------------------- отмена последнего отчёта (raw_reports) ---
def _raw_report_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "kvartal": row["kvartal"],
        "vydels": row["vydels"],
        "tip_raboty": row["tip_raboty"],
        "data_soobscheniya": row["data_soobscheniya"],
    }


@router.get("/raw-reports/last")
def get_last_raw_report(
    telegram_id: str,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Последний отчёт этого рабочего, ещё не проверенный лесничим (кнопка
    '↩️ Отменить последний отчёт') — раньше process_cancel_last_report в
    telegram_bot.py вызывала get_last_raw_report_for_user(conn, ...)
    напрямую по общему sqlite-соединению бота. Возвращает
    {"report": null}, если отменять нечего — тот же принцип "ожидаемый
    исход — не HTTP-ошибка", что уже используется в
    GET /api/bot/reports/duplicate (3.2) и
    POST /api/bot/breakdowns/{id}/notes (3.3). Тот же нюанс row_factory,
    что и в остальных эндпоинтах этого роутера — get_last_raw_report_
    for_user читает результат по имени колонки."""
    _check_own_identity(user, telegram_id)
    conn.row_factory = sqlite3.Row
    row = legacy_db.get_last_raw_report_for_user(conn, telegram_id)
    return {"report": _raw_report_row_to_dict(row) if row is not None else None}


@router.delete("/raw-reports/{report_id}")
def delete_raw_report(
    report_id: int,
    telegram_id: str,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Удаляет отчёт по кнопке '↩️ Отменить последний отчёт', только если
    он принадлежит telegram_id и ещё не проверен лесничим (status='на
    проверке') — раньше это делала cancel_raw_report(conn, ...), вызванная
    напрямую из process_cancel_last_report_confirm_step. telegram_id —
    query-параметр (не тело запроса, DELETE его обычно не несёт) — та же
    проверка владения, что раньше была внутри самой cancel_raw_report.
    Возвращает {"cancelled": false, "photo_path": null}, если отчёт не
    найден, принадлежит другому telegram_id или уже проверен лесничим —
    тот же принцип "ожидаемый исход — не HTTP-ошибка", что и в остальных
    эндпоинтах этого роутера; photo_path (может быть null, если фото не
    было) возвращается, чтобы бот мог удалить файл с диска сам, как и
    раньше. Тот же нюанс row_factory — cancel_raw_report читает
    row["photo_path"] по имени колонки."""
    _check_own_identity(user, telegram_id)
    conn.row_factory = sqlite3.Row
    photo_path = legacy_db.cancel_raw_report(conn, report_id, telegram_id)
    if photo_path is False:
        return {"cancelled": False, "photo_path": None}
    return {"cancelled": True, "photo_path": photo_path or None}


# ------------------------------------------------------------------ гео-заметки ---
class GeoNoteIn(BaseModel):
    telegram_id: str
    lat: float
    lon: float
    note_text: Optional[str] = None
    photo_path: Optional[str] = None


@router.post("/geo-notes")
def create_geo_note(
    payload: GeoNoteIn,
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Кнопка '📍 Добавить заметку на делянку' — рабочий присылает геометку
    через скрепку Telegram (handle_location в telegram_bot.py запоминает
    координаты в памяти процесса, в _pending_geo), затем следующим
    сообщением текст или фото как комментарий к этой точке
    (handle_message/handle_photo). Раньше это сохраняла
    _save_geo_note(cursor, ...) прямо в telegram_bot.py, по общему
    sqlite-соединению бота (get_db()), без собственного commit — коммитил
    вызывающий код. Здесь — один HTTP-запрос, INSERT сделан прямо в этом
    роутере (не как новая функция в legacy/db.py, см. докстринг модуля
    выше) — таблица однострочная, отдельной функции под неё в db.py не
    заводили.

    В отличие от worker/report/breakdown-эндпоинтов выше, telegram_id
    здесь не проверяется на регистрацию — то же поведение, что было у
    _save_geo_note раньше (она тоже ничего не проверяла, а
    handle_message/handle_photo и так уже требуют, чтобы координаты
    были в _pending_geo, куда попасть можно только приславши локацию
    ПОСЛЕ регистрации — регистрация неявно проверяется на уровне того,
    что рабочему вообще показана клавиатура с кнопкой геозаметки, см.
    get_menu_for_dolzhnost). Не найденный telegram_id просто создаст
    строку в geo_notes без соответствующей записи в lesorub_directory —
    как и раньше при прямом INSERT, это не новая проблема этой правки.
    Проверка регистрации отсутствует намеренно (см. выше) — но
    _check_own_identity() всё равно нужна отдельно: она не про
    регистрацию, а про то, что role="worker" не может подписать заметку
    чужим telegram_id, даже если этот telegram_id не зарегистрирован
    вовсе."""
    _check_own_identity(user, payload.telegram_id)
    conn.execute(
        "INSERT INTO geo_notes (telegram_id, lat, lon, note_text, photo_path) "
        "VALUES (?, ?, ?, ?, ?)",
        (payload.telegram_id, payload.lat, payload.lon, payload.note_text, payload.photo_path),
    )
    conn.commit()
    note_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {"id": note_id}


# ------------------------------------------------------------ фото (мобильное приложение) ---
@router.post("/photo")
def upload_photo(
    file: UploadFile = File(...),
    user=Depends(require_permission("bot.access")),
):
    """Загрузка фото напрямую с телефона — то, чего у Telegram-бота не
    было (см. докстринг модуля выше, подчасть 3.2): бот получает фото
    через Telegram Bot API и сам кладёт готовый photo_path на диск, а
    мобильному клиенту неоткуда взять Telegram, поэтому файл прилетает
    сюда как обычная multipart-загрузка (тот же принцип, что уже
    используется в POST /api/delyanki/items/{id}/abris).

    Возвращает photo_path — его нужно подставить строкой в
    POST /api/bot/reports / /breakdowns / /geo-notes, они его не
    интерпретируют, только сохраняют путь в БД (см. их докстринги в этом
    файле) — эндпоинт загрузки специально отделён от создания самого
    отчёта, чтобы не переписывать уже готовые/протестированные
    create_report/create_breakdown/create_geo_note."""
    suffix = Path(file.filename or "").suffix or ".jpg"
    dest_dir = UPLOADS_DIR / "mobile_photos"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{uuid.uuid4().hex}{suffix}"
    with open(dest_path, "wb") as f:
        f.write(file.file.read())
    return {"photo_path": str(dest_path)}


# ------------------------------------------------------- задачи (work_plan, мобильное) ---
def _work_plan_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "data": row["data"],
        "zadacha": row["zadacha"],
        "status": row["status"],
        "created_at": row["created_at"],
        "kvartal": row["kvartal"],
        "vydel": row["vydel"],
        "lesnichestvo": row["lesnichestvo"],
    }


class CreateWorkPlanIn(BaseModel):
    sotrudnik_id: int
    data: str  # дата задачи, формат "ГГГГ-ММ-ДД"
    zadacha: str
    delyanka_item_id: Optional[int] = None


@router.post("/work-plan")
def create_work_plan(
    body: CreateWorkPlanIn,
    conn=Depends(get_conn),
    user=Depends(require_permission("work_plan.edit")),
):
    """Постановка задачи рабочему — только admin/lesovod (см.
    PERMISSIONS["work_plan.edit"]). Временно единственный способ завести
    задачу (кроме прямого SQL): полноценный экран планирования в вебе —
    Фаза 4 плана доработки, отдельным шагом."""
    try:
        work_plan_id = webext.create_work_plan_item(
            conn, body.sotrudnik_id, body.data, body.zadacha, body.delyanka_item_id,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"id": work_plan_id}


@router.get("/work-plan")
def list_work_plan(
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    """Версия 'Моих задач' на основе work_plan (Фаза 4 плана доработки —
    богаче старой tasks: привязана к делянке). В отличие от GET /tasks
    выше, identity рабочего берётся из его собственного токена
    (user["sotrudnik_id"]), а не из query-параметра — чужие задачи
    прочитать нельзя, даже подобрав id. Доступно и admin — тогда
    HTTPException ниже (у admin нет sotrudnik_id), это ожидаемо: этот
    эндпоинт для рабочих, а не для отладки из /docs (для отладки
    используйте POST /api/auth/worker-login, как обычный рабочий)."""
    if user.get("role") != "worker":
        raise HTTPException(403, "Доступно только учётным записям рабочих (worker-login)")
    rows = webext.get_work_plan_for_sotrudnik(conn, user["sotrudnik_id"])
    return [_work_plan_row_to_dict(row) for row in rows]


@router.post("/work-plan/{work_plan_id}/complete")
def complete_work_plan(
    work_plan_id: int,
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    if user.get("role") != "worker":
        raise HTTPException(403, "Доступно только учётным записям рабочих (worker-login)")
    done = webext.complete_work_plan_item(conn, work_plan_id, user["sotrudnik_id"])
    return {"done": done}


# ------------------------------------------------------- отметка времени/присутствия ---
def _attendance_row_to_dict(row) -> Optional[dict]:
    if row is None:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "lat": row["lat"],
        "lon": row["lon"],
        "created_at": row["created_at"],
    }


class AttendanceMarkIn(BaseModel):
    status: Literal["работаю", "не работаю", "больничный"]
    lat: Optional[float] = None
    lon: Optional[float] = None


@router.post("/attendance")
def create_attendance_mark(
    body: AttendanceMarkIn,
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    """Раздел 3.6 плана мобильного приложения — рабочий отмечает
    "Работаю"/"Не работаю"/"Больничный" разово (не постоянное слежение
    весь день), с геометкой в момент отметки, если телефон её отдал.
    Identity — из токена (user["sotrudnik_id"]), тем же способом, что и
    у work-plan выше, а не параметром из тела запроса: рабочий не должен
    иметь возможность отметиться от чужого имени."""
    if user.get("role") != "worker":
        raise HTTPException(403, "Доступно только учётным записям рабочих (worker-login)")
    mark_id = webext.create_attendance_mark(conn, user["sotrudnik_id"], body.status, body.lat, body.lon)
    return {"id": mark_id}


@router.get("/attendance/latest")
def get_latest_attendance_mark(
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    """Последняя отметка текущего рабочего — мобильное приложение зовёт
    это при открытии экрана "Отметка времени", чтобы показать уже
    выбранным тот статус, который рабочий отмечал последним, а не пустую
    форму каждый раз. null, если рабочий вообще ни разу не отмечался."""
    if user.get("role") != "worker":
        raise HTTPException(403, "Доступно только учётным записям рабочих (worker-login)")
    row = webext.get_latest_attendance_mark(conn, user["sotrudnik_id"])
    return _attendance_row_to_dict(row)


# ------------------------------------------------------- заметки рабочего начальнику ---
class WorkerNoteIn(BaseModel):
    text: str
    # NULL — общая заметка (видят все руководители); иначе id из
    # GET /api/bot/recipients — видит только этот человек.
    recipient_sotrudnik_id: Optional[int] = None


@router.get("/recipients")
def list_note_recipients(
    conn=Depends(get_conn),
    user=Depends(require_permission("bot.access")),
):
    """Кому рабочий может адресовать заметку (экран выбора получателя в
    мобильном приложении): активные мастер леса / помощник лесничего /
    лесничий (config.DOLZHNOSTI_MASTER_URODNYA). Только id, ФИО, должность."""
    return webext.list_recipients(conn)


@router.post("/notes")
def create_worker_note(
    body: WorkerNoteIn,
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    """Односторонняя лента "рабочий -> мастер", не переписка: рабочий
    только отправляет текст, ответа обратно ему в мобильное приложение не
    предусмотрено (мастер читает и отмечает прочитанным в веб-версии, см.
    GET/PATCH /api/notes). Identity — из токена (user["sotrudnik_id"]),
    тем же способом, что и у attendance/work-plan выше, а не параметром из
    тела запроса."""
    if user.get("role") != "worker":
        raise HTTPException(403, "Доступно только учётным записям рабочих (worker-login)")
    try:
        note_id = webext.create_worker_note(
            conn, user["sotrudnik_id"], body.text, body.recipient_sotrudnik_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # Только адресная заметка создаёт уведомление (общая видна в ленте
    # заметок и без него); самому себе не уведомляем.
    if body.recipient_sotrudnik_id is not None and body.recipient_sotrudnik_id != user["sotrudnik_id"]:
        webext.notify(
            conn, "note", f"Заметка от {user['fio']}: {body.text.strip()}",
            related_id=note_id, recipient_sotrudnik_id=body.recipient_sotrudnik_id,
        )
    return {"id": note_id}


# ------------------------------------------------------------------ трелёвка ---
class TrelevkaIn(BaseModel):
    otkuda: str
    kuda: str
    obyom: float
    delyanka_item_id: Optional[int] = None


@router.post("/trelevka")
def create_trelevka(
    body: TrelevkaIn,
    conn=Depends(get_conn),
    user=Depends(require_permission("trelevka.submit")),
):
    """Тракторист записывает рейс трелёвки: откуда/куда/объём, делянка —
    по желанию (NULL, если трактор работает не по конкретной делянке).
    Identity — из токена (user["sotrudnik_id"]), тем же способом, что у
    work-plan/attendance/notes, а не из тела запроса. Право trelevka.submit
    — на всю роль worker (должность на сервере не проверяется)."""
    if user.get("role") != "worker":
        raise HTTPException(403, "Доступно только учётным записям рабочих (worker-login)")
    try:
        trelevka_id = webext.create_trelevka(
            conn, user["sotrudnik_id"], body.otkuda, body.kuda, body.obyom, body.delyanka_item_id,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    webext.notify(
        conn, "trelevka",
        f"Трелёвка: {user['fio']} — {body.otkuda.strip()} → {body.kuda.strip()}, {body.obyom:g} м³",
        related_id=trelevka_id,
    )
    return {"id": trelevka_id}
