# -*- coding: utf-8 -*-
"""Роутер "Лесные культуры" (screens/lesokultury/) — оборачивает
db.*_lesokultury_* без изменения их внутренней логики."""
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator

from app import legacy_bridge  # noqa: F401
from app import lesokultury_kniga
import db as legacy_db

from app.auth import require_office_writer_or_master
from app.auth import get_current_user
from app.auth import require_permission
from app.database import get_conn

router = APIRouter(prefix="/api/lesokultury", tags=["lesokultury"])


@router.get("/uchastki")
def list_uchastki(
    include_spisannye: bool = False,
    god: Optional[str] = None,
    search: Optional[str] = None,
    conn=Depends(get_conn), _user=Depends(get_current_user),
):
    return legacy_db.get_lesokultury_uchastki(
        conn, include_spisannye=include_spisannye, god=god, search=search,
    )


@router.get("/gody")
def list_gody(conn=Depends(get_conn), _user=Depends(get_current_user)):
    """Различные годы создания культур, встречающиеся в базе — для
    выпадающего фильтра «Год» на экране (вместо свободного текста)."""
    return legacy_db.get_lesokultury_gody(conn)


@router.get("/uchastki/{uchastok_id}")
def get_uchastok(uchastok_id: int, conn=Depends(get_conn), _user=Depends(get_current_user)):
    u = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
    if u is None:
        raise HTTPException(404, "Участок не найден")
    return u


@router.post("/uchastki")
def create_uchastok(fields: Dict[str, Any], conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit"))):
    uchastok_id = legacy_db.create_lesokultury_uchastok(conn, **fields)
    return {"id": uchastok_id}


@router.patch("/uchastki/{uchastok_id}")
def update_uchastok(uchastok_id: int, fields: Dict[str, Any], conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit"))):
    u = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
    if u is None:
        raise HTTPException(404, "Участок не найден")
    legacy_db.update_lesokultury_uchastok(conn, uchastok_id, **fields)
    return {"ok": True}


@router.delete("/uchastki/{uchastok_id}")
def delete_uchastok(uchastok_id: int, conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit"))):
    u = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
    if u is None:
        raise HTTPException(404, "Участок не найден")
    legacy_db.delete_lesokultury_uchastok(conn, uchastok_id)
    return {"ok": True}


@router.get("/uchastki/{uchastok_id}/meropriyatiya")
def list_meropriyatiya(uchastok_id: int, conn=Depends(get_conn), _user=Depends(get_current_user)):
    return legacy_db.list_lesokultury_meropriyatiya(conn, uchastok_id)


@router.post("/uchastki/{uchastok_id}/meropriyatiya")
def add_meropriyatie(
    uchastok_id: int,
    tip: str,
    data: str,
    prizhivaemost_pct: Optional[float] = None,
    kolichestvo_na_ga: Optional[float] = None,
    sostav_fakt: str = "",
    primechaniya: str = "",
    dannye: Optional[Dict[str, Any]] = Body(None, embed=True),
    conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit")),
):
    """dannye (необязательно, в теле запроса) — поля мероприятия для
    ведомостей текущих изменений: у «Перевода» {"taksatsiya": {nomer_kartochki,
    ploshad, podvydel, sostav, vozrast, vysota, diametr, polnota}}, у
    «Доращивания» {"do_goda"}, у «Списания» {"prichina", "akt_nomer",
    "akt_data", "vid_zemel"}."""
    meropriyatie_id = legacy_db.add_lesokultury_meropriyatie(
        conn, uchastok_id, tip, data,
        prizhivaemost_pct=prizhivaemost_pct, kolichestvo_na_ga=kolichestvo_na_ga,
        sostav_fakt=sostav_fakt, primechaniya=primechaniya, dannye=dannye,
    )
    return {"id": meropriyatie_id}


# --------------------------------------------------------------------------- #
#   Загрузка «Книги производства л/к» (.xls/.xlsx): предпросмотр, потом запись
# --------------------------------------------------------------------------- #
async def _kniga_plan(conn, file: UploadFile, lesnichestvo: str, god_from: int, god_to: int, overrides: Optional[str]):
    if not lesnichestvo.strip():
        raise HTTPException(400, "Укажите лесничество")
    content = await file.read()
    try:
        sheets = lesokultury_kniga.open_book(content, file.filename or "")
        rows = lesokultury_kniga.parse_book(sheets, god_from, god_to)
        return lesokultury_kniga.plan_import(
            conn, rows, lesnichestvo.strip(), lesokultury_kniga.parse_overrides(overrides)
        )
    except lesokultury_kniga.KnigaError as exc:
        raise HTTPException(400, str(exc))


@router.post("/import-kniga/preview")
async def import_kniga_preview(
    file: UploadFile = File(...),
    lesnichestvo: str = Form(...),
    god_from: int = Form(2017),
    god_to: int = Form(2100),
    overrides: Optional[str] = Form(None),
    conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit")),
):
    """Разбор книги и сверка с базой — В БАЗУ НЕ ПИШЕТ. overrides — JSON
    {ключ строки: выдел}, если выдел в книге записан неверно."""
    plan = await _kniga_plan(conn, file, lesnichestvo, god_from, god_to, overrides)
    return {"summary": plan["summary"], "rows": lesokultury_kniga.public_rows(plan["rows"])}


@router.post("/import-kniga/apply")
async def import_kniga_apply(
    file: UploadFile = File(...),
    lesnichestvo: str = Form(...),
    god_from: int = Form(2017),
    god_to: int = Form(2100),
    overrides: Optional[str] = Form(None),
    skip: Optional[str] = Form(None),
    conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit")),
):
    """Та же сверка + запись. skip — JSON-список ключей строк, которые не
    загружать. Повторная загрузка той же книги дублей не создаёт."""
    plan = await _kniga_plan(conn, file, lesnichestvo, god_from, god_to, overrides)
    try:
        skip_keys = json.loads(skip) if skip else []
    except ValueError:
        raise HTTPException(400, "skip: ожидается JSON-список")
    return lesokultury_kniga.apply_import(conn, plan, lesnichestvo.strip(), skip_keys)


# --------------------------------------------------------------------------- #
#   Полевые карточки с телефона (мастер / пом. лесничего / лесничий)
#   Пишут в ТЕ ЖЕ таблицы, что показывает экран "Лесные культуры":
#   журнал lesokultury_meropriyatiya и статус lesokultury_uchastok.status.
# --------------------------------------------------------------------------- #
TIP_INVENTORY = {1: "Инвентаризация 1-го года", 3: "Инвентаризация 3-го года"}
TIP_PEREVOD_INVENTORY = "Инвентаризация на перевод"
TIP_PEREVOD = "Перевод в покрытые лесом земли"  # на вебе переводит статус в "переведён"
TIP_DORASHCHIVANIE = "Доращивание"
TIP_SPISANIE = "Списание"  # на вебе переводит статус в "списан"
STATUS_PEREVEDEN = "переведён"
STATUS_SPISAN = "списан"
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


class ProbaRowIn(BaseModel):
    """Таблица проб — подписи столбцов из руководства АРМ «Лесовосстановление»:
    «Номер пробы», «Размер пробы» (единица размера в руководстве не указана —
    сервер хранит число как есть)."""

    nomer: str = Field(min_length=1, max_length=50)
    razmer: float = Field(gt=0)

    @field_validator("nomer")
    @classmethod
    def _strip_nomer(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Номер пробы не может быть пустым")
        return v


class RezultatIn(BaseModel):
    """Результаты обследования. Обязательны порода, высажено, прижилось —
    без них не посчитать приживаемость. Остальное (средняя высота) —
    по усмотрению разработки: в руководстве состав полей формы дан только
    рисунком, которого у нас нет."""

    poroda: str = Field(min_length=1, max_length=100)
    vysazheno: int = Field(gt=0)
    prizhilos: int = Field(ge=0)
    srednyaya_vysota: Optional[float] = Field(default=None, ge=0)

    @field_validator("poroda")
    @classmethod
    def _strip_poroda(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Порода не может быть пустой")
        return v

    @model_validator(mode="after")
    def _prizhilos_le_vysazheno(self):
        if self.prizhilos > self.vysazheno:
            raise ValueError(f"«{self.poroda}»: прижилось ({self.prizhilos}) больше, чем высажено ({self.vysazheno})")
        return self


class FieldCardBase(BaseModel):
    data: Optional[str] = None  # "ДД.ММ.ГГГГ"; по умолчанию сегодня
    proby: List[ProbaRowIn] = Field(min_length=1)
    rezultaty: List[RezultatIn] = Field(min_length=1)
    # Как и на вебе (форма мероприятия) — вводятся человеком, не считаются:
    # для количества на 1 га нужна единица размера пробы, которой нет в источнике.
    kolichestvo_na_ga: Optional[float] = Field(default=None, ge=0)
    sostav_fakt: str = ""
    primechaniya: str = ""

    @field_validator("data")
    @classmethod
    def _check_date(cls, v):
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not DATE_RE.match(v):
            raise ValueError("Дата в формате ДД.ММ.ГГГГ")
        try:
            datetime.strptime(v, "%d.%m.%Y")
        except ValueError:
            raise ValueError("Такой даты не существует")
        return v

    @model_validator(mode="after")
    def _unique(self):
        nomera = [p.nomer.casefold() for p in self.proby]
        if len(set(nomera)) != len(nomera):
            raise ValueError("Номера проб не должны повторяться")
        porody = [r.poroda.casefold() for r in self.rezultaty]
        if len(set(porody)) != len(porody):
            raise ValueError("Каждая порода в результатах — одной строкой")
        return self


class InventarizatsiyaIn(FieldCardBase):
    god: Literal[1, 3]


class TaksatsiyaIn(BaseModel):
    """Таксация участка при переводе в покрытые лесом земли — колонки
    прил. 4 ведомости текущих изменений (приказ Минлесхоза №130)."""

    nomer_kartochki: str = Field(default="", max_length=50)
    ploshad: Optional[float] = Field(default=None, gt=0)
    podvydel: str = Field(default="", max_length=20)
    sostav: str = Field(default="", max_length=50)
    vozrast: Optional[int] = Field(default=None, ge=0, le=200)
    vysota: Optional[float] = Field(default=None, ge=0, le=60)
    diametr: Optional[float] = Field(default=None, ge=0, le=100)
    polnota: Optional[float] = Field(default=None, ge=0, le=1.5)


class PerevodIn(FieldCardBase):
    god: Optional[Literal[1, 3]] = None  # для перевода необязателен
    # Решение — ручной выбор человека; норматив (приложение 18) сервер НЕ
    # проверяет: этих таблиц в системе нет.
    reshenie: Literal["перевести", "не переводить", "доработать", "доращивание", "списать"]
    taksatsiya: Optional[TaksatsiyaIn] = None  # для «перевести»
    do_goda: Optional[int] = Field(default=None, ge=2000, le=2100)  # для «доращивание»
    prichina_spisaniya: str = Field(default="", max_length=500)  # для «списать»

    @model_validator(mode="after")
    def _decision_fields(self):
        if self.reshenie == "списать" and not self.prichina_spisaniya.strip():
            raise ValueError("Укажите причину списания")
        return self


def _calc_prizhivaemost(rezultaty: List[RezultatIn]) -> dict:
    """Приживаемость = прижившиеся ÷ высаженные × 100 — общая и по породам."""
    total_v = sum(r.vysazheno for r in rezultaty)
    total_p = sum(r.prizhilos for r in rezultaty)
    return {
        "vysazheno": total_v,
        "prizhilos": total_p,
        "prizhivaemost_pct": round(total_p / total_v * 100, 1),
        "po_porodam": [
            {"poroda": r.poroda, "vysazheno": r.vysazheno, "prizhilos": r.prizhilos,
             "prizhivaemost_pct": round(r.prizhilos / r.vysazheno * 100, 1)}
            for r in rezultaty
        ],
    }


def _summary_text(body: FieldCardBase, calc: dict, reshenie: Optional[str]) -> str:
    """Читаемая сводка для колонки «Примечания» журнала: экран «Лесные
    культуры» показывает только её (структурные данные лежат в dannye_json)."""
    porody = "; ".join(
        f"{p['poroda']} {p['prizhilos']}/{p['vysazheno']} ({p['prizhivaemost_pct']}%)" for p in calc["po_porodam"]
    )
    parts = [f"Проб: {len(body.proby)}", f"Результаты: {porody}"]
    if reshenie:
        parts.append(f"Решение: {reshenie}")
    text = ". ".join(parts) + "."
    if body.primechaniya.strip():
        text += f" {body.primechaniya.strip()}"
    return text


def _record_field_card(conn, uchastok_id: int, user: dict, body: FieldCardBase, tip: str, reshenie: Optional[str]) -> dict:
    uchastok = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
    if uchastok is None:
        raise HTTPException(404, "Участок не найден")
    if uchastok["status"] != "активен":
        raise HTTPException(409, f"Участок уже «{uchastok['status']}» — записи с телефона принимаются только по активным")

    calc = _calc_prizhivaemost(body.rezultaty)
    data = body.data or datetime.now().strftime("%d.%m.%Y")
    dannye = {
        "god": body.god,
        "proby": [p.model_dump() for p in body.proby],
        "rezultaty": [r.model_dump() for r in body.rezultaty],
        "itogo": {k: calc[k] for k in ("vysazheno", "prizhilos", "prizhivaemost_pct")},
        "reshenie": reshenie,
    }
    # identity — из токена, как везде; у офисного логина sotrudnik_id нет
    sotrudnik_id = user.get("sotrudnik_id") if user.get("role") == "worker" else None

    meropriyatie_id = legacy_db.add_lesokultury_meropriyatie(
        conn, uchastok_id, tip, data,
        prizhivaemost_pct=calc["prizhivaemost_pct"],
        kolichestvo_na_ga=body.kolichestvo_na_ga,
        sostav_fakt=body.sostav_fakt,
        primechaniya=_summary_text(body, calc, reshenie),
        dannye=dannye, sotrudnik_id=sotrudnik_id,
    )

    status = uchastok["status"]
    perevod_id = None
    source = f"По инвентаризации на перевод (запись №{meropriyatie_id})"
    if reshenie == "перевести":
        # То же, что делает веб при добавлении мероприятия «Перевод в покрытые
        # лесом земли»: запись в журнал + статус участка «переведён».
        taks = body.taksatsiya.model_dump() if getattr(body, "taksatsiya", None) else {}
        if not taks.get("sostav") and body.sostav_fakt.strip():
            taks["sostav"] = body.sostav_fakt.strip()
        perevod_id = legacy_db.add_lesokultury_meropriyatie(
            conn, uchastok_id, TIP_PEREVOD, data,
            sostav_fakt=taks.get("sostav") or "",
            primechaniya=source,
            dannye={"taksatsiya": taks} if taks else None,
            sotrudnik_id=sotrudnik_id,
        )
        legacy_db.update_lesokultury_uchastok(conn, uchastok_id, status=STATUS_PEREVEDEN)
        status = STATUS_PEREVEDEN
    elif reshenie == "доращивание":
        do_goda = getattr(body, "do_goda", None)
        perevod_id = legacy_db.add_lesokultury_meropriyatie(
            conn, uchastok_id, TIP_DORASHCHIVANIE, data,
            primechaniya=source + (f"; до {do_goda} г." if do_goda else ""),
            dannye={"do_goda": do_goda},
            sotrudnik_id=sotrudnik_id,
        )
    elif reshenie == "списать":
        prichina = body.prichina_spisaniya.strip()
        perevod_id = legacy_db.add_lesokultury_meropriyatie(
            conn, uchastok_id, TIP_SPISANIE, data,
            primechaniya=f"{source}; причина: {prichina}",
            dannye={"prichina": prichina},
            sotrudnik_id=sotrudnik_id,
        )
        legacy_db.update_lesokultury_uchastok(conn, uchastok_id, status=STATUS_SPISAN)
        status = STATUS_SPISAN

    return {
        "id": meropriyatie_id,
        "perevod_id": perevod_id,
        "tip": tip,
        "data": data,
        "status_uchastka": status,
        **calc,
    }


@router.post("/{uchastok_id}/inventarizatsiya")
def create_inventarizatsiya(
    uchastok_id: int,
    body: InventarizatsiyaIn,
    conn=Depends(get_conn),
    user=Depends(require_office_writer_or_master),
):
    """Полевая карточка инвентаризации (1-й или 3-й год): таблица проб +
    результаты обследования. Приживаемость считается на сервере, статус
    участка не меняется (как и при ручной записи на вебе)."""
    return _record_field_card(conn, uchastok_id, user, body, TIP_INVENTORY[body.god], None)


@router.post("/{uchastok_id}/perevod")
def create_perevod(
    uchastok_id: int,
    body: PerevodIn,
    conn=Depends(get_conn),
    user=Depends(require_office_writer_or_master),
):
    """Полевая карточка перевода: то же + решение человека. «перевести» —
    запись «Перевод в покрытые лесом земли» (с таксацией для прил. 4, если
    передана) и статус участка «переведён» (как на вебе, без дополнительного
    подтверждения); «доращивание» — запись «Доращивание» (до какого года),
    статус не меняется; «списать» — запись «Списание» с причиной и статус
    «списан»; «не переводить» / «доработать» — статус не меняется. Соответствие нормативу
    (приложение 18) сервер не проверяет — решение только ручное."""
    return _record_field_card(conn, uchastok_id, user, body, TIP_PEREVOD_INVENTORY, body.reshenie)
