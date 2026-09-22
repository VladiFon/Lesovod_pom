# -*- coding: utf-8 -*-
"""Роутер "Авторизация" — логин/логаут/текущий пользователь и (для admin)
управление учётками. Появляется на Этапе 2 плана переноса в веб вместе с
таблицами users/sessions в legacy/webext.py.

Пока ни один из роутеров Этапа 1 не требует токен (см. комментарий в
app/auth.py) — эти эндпоинты можно уже сейчас проверить через curl/Postman
или /docs, а обязательным для остальных экранов авторизация станет по мере
Этапа 4."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import legacy_bridge  # noqa: F401 — обязателен до import webext
import webext

from app.database import get_conn
from app.auth import get_current_user, require_permission

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Фиксированный список должностей рабочих — от него зависит, какое меню
# показывает мобильное приложение (см. WorkerRole на стороне мобильного
# клиента). Раньше dolzhnost было произвольной строкой ("Тракторист на
# вывозке леса" и т.п.), и мобильному приложению приходилось нечётко
# сопоставлять текст с ролью — теперь /docs и веб-форма (экран "Сотрудники",
# frontend/src/pages/Sotrudniki.jsx) предлагают ровно эти варианты (FastAPI
# сам публикует их как enum в OpenAPI-схеме этого поля), мобильный клиент
# сравнивает точно.
#
# Список заменён на актуальные названия должностей (было 7 грубых
# значений вроде "Тракторист"/"Мастер" — по решению пользователя заменены
# на точные, см. историю чата). ВАЖНО: это отдельный список от
# config.DOLZHNOSTI (legacy/config.py) — тот управляет меню Telegram-бота
# (get_menu_for_dolzhnost) через ДРУГУЮ таблицу (lesorub_directory,
# регистрация через Telegram), его сознательно не трогали — рабочие,
# заведённые через мобильное приложение (create_sotrudnik), и так не
# полностью совпадали с ним и до этой правки (см. соответствующий
# докстринг в config.py).
Dolzhnost = Literal[
    "Лесовод",
    "Машинист трелевочной (лесозаготовительной (Форвардер)) машины",
    "Мастер леса",
    "Тракторист на подготовке лесосек, трелевке и вывозке леса",
    "Лесоруб",
    "Вальщик леса",
    "Водитель автомобиля",
    "Помощник лесничего",
    "Лесничий",
]


class LoginIn(BaseModel):
    login: str
    password: str


class CreateUserIn(BaseModel):
    login: str
    password: str
    fio: Optional[str] = ""
    role: str = "viewer"


class SetRoleIn(BaseModel):
    role: str


class SetActiveIn(BaseModel):
    is_active: bool


class SetPasswordIn(BaseModel):
    password: str


class WorkerLoginIn(BaseModel):
    login: str
    pin: str


class CreateWorkerIn(BaseModel):
    login: str
    pin: str
    fio: str
    dolzhnost: Dolzhnost
    uchastok: Optional[str] = ""


@router.post("/login")
def login(body: LoginIn, conn=Depends(get_conn)):
    user = webext.authenticate_user(conn, body.login, body.password)
    if user is None:
        raise HTTPException(401, "Неверный логин или пароль, либо учётная запись отключена")
    token, expires_at = webext.create_session(conn, user["id"])
    return {"token": token, "expires_at": expires_at, "user": user}


@router.post("/logout")
def logout(user=Depends(get_current_user), conn=Depends(get_conn)):
    # get_current_user уже подтвердил, что токен валиден — достаточно найти
    # его повторно нельзя (мы не пронесли сырой токен через зависимость),
    # поэтому логаут по факту удаляет все сессии текущего пользователя.
    # Для логаута именно "этого устройства" фронтенду проще держать токен и
    # звать DELETE-эндпоинт с ним напрямую — не требуется на Этапе 2.
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    conn.commit()
    return {"ok": True}


@router.get("/me")
def me(user=Depends(get_current_user)):
    return user


# --------------------------------------------------------------------------- #
#   Управление пользователями — только admin (webext.PERMISSIONS["users.manage"])
# --------------------------------------------------------------------------- #
@router.get("/users")
def list_users(user=Depends(require_permission("users.manage")), conn=Depends(get_conn)):
    return webext.list_users(conn)


@router.post("/users")
def create_user(body: CreateUserIn, user=Depends(require_permission("users.manage")),
                 conn=Depends(get_conn)):
    if webext.get_user_by_login(conn, body.login) is not None:
        raise HTTPException(409, "Пользователь с таким логином уже существует")
    try:
        user_id = webext.create_user(conn, body.login, body.password, body.fio, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return webext.get_user_by_id(conn, user_id)


@router.patch("/users/{user_id}/role")
def set_user_role(user_id: int, body: SetRoleIn, user=Depends(require_permission("users.manage")),
                   conn=Depends(get_conn)):
    try:
        webext.set_user_role(conn, user_id, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.patch("/users/{user_id}/active")
def set_user_active(user_id: int, body: SetActiveIn,
                     user=Depends(require_permission("users.manage")), conn=Depends(get_conn)):
    webext.set_user_active(conn, user_id, body.is_active)
    return {"ok": True}


@router.patch("/users/{user_id}/password")
def set_user_password(user_id: int, body: SetPasswordIn,
                       user=Depends(require_permission("users.manage")), conn=Depends(get_conn)):
    """Блок 1 плана доработки, п.6: форма смены пароля в Settings.jsx
    зовёт этот эндпоинт — в первую очередь для смены пароля admin/admin,
    созданного ensure_bootstrap_admin() при первом запуске."""
    if len(body.password) < 4:
        raise HTTPException(400, "Пароль слишком короткий (минимум 4 символа)")
    try:
        webext.set_user_password(conn, user_id, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


# --------------------------------------------------------------------------- #
#   Рабочие (мобильное приложение) — Фаза 6 плана доработки.
#   Отдельная учётная система от users выше (роли admin/lesovod/viewer им
#   не подходят — см. комментарий у webext.SOTRUDNIKI_SCHEMA). Управление
#   учётками рабочих — только admin, тот же принцип, что и для users.
# --------------------------------------------------------------------------- #
@router.post("/workers")
def create_worker(body: CreateWorkerIn, user=Depends(require_permission("users.manage")),
                   conn=Depends(get_conn)):
    """Заводит рабочего (логин + PIN) — временная замена экрана
    "Справочник сотрудников" (Фаза 1 плана доработки) до тех пор, пока он
    не появится в Settings.jsx: пока это /docs. PIN — короткий цифровой
    код, не полноценный пароль (рабочие вводят его на телефоне в лесу)."""
    if len(body.pin) < 4:
        raise HTTPException(400, "PIN слишком короткий (минимум 4 символа)")
    try:
        worker_id = webext.create_sotrudnik(
            conn, body.login, body.pin, body.fio, body.dolzhnost, body.uchastok,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"id": worker_id}


@router.get("/workers")
def list_workers(user=Depends(require_permission("users.manage")), conn=Depends(get_conn)):
    return webext.list_sotrudniki(conn)


@router.patch("/workers/{worker_id}/active")
def set_worker_active(worker_id: int, body: SetActiveIn,
                       user=Depends(require_permission("users.manage")), conn=Depends(get_conn)):
    webext.set_sotrudnik_active(conn, worker_id, body.is_active)
    return {"ok": True}


@router.post("/worker-login")
def worker_login(body: WorkerLoginIn, conn=Depends(get_conn)):
    """Вход рабочего в мобильном приложении — логин + PIN вместо
    Telegram. Ответ намеренно похож на POST /api/auth/login (token,
    expires_at, user-подобный объект) — мобильному клиенту не нужно знать
    отдельный формат ради того, что за экраном логина стоит другая
    таблица в БД."""
    worker = webext.authenticate_sotrudnik(conn, body.login, body.pin)
    if worker is None:
        raise HTTPException(401, "Неверный логин или PIN, либо учётная запись отключена")
    token, expires_at = webext.create_worker_session(conn, worker["id"])
    # app_identity — тот самый синтетический viber_id (см.
    # webext.create_sotrudnik), которым нужно подставляться как
    # telegram_id в остальные эндпоинты /api/bot/* (отчёты/поломки/
    # гео-заметки) — они пока принимают его query-параметром, отдельная
    # доработка "не доверять параметру, брать identity из токена" (см.
    # план мобильного приложения, открытый пункт) сделана только для
    # новых /api/bot/work-plan* эндпоинтов ниже.
    worker["app_identity"] = f"app:{worker['id']}"
    return {"token": token, "expires_at": expires_at, "worker": worker}
