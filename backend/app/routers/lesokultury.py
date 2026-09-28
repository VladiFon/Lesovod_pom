# -*- coding: utf-8 -*-
"""Роутер "Лесные культуры" (screens/lesokultury/) — оборачивает
db.*_lesokultury_* без изменения их внутренней логики."""
import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app import legacy_bridge  # noqa: F401
import db as legacy_db
import webext
import lesokultury_normativy
import kartochka_perevoda_generator

from app.auth import require_office_writer_or_master, require_permission
from app.database import get_conn, get_connection
from app.doc_tasks import new_task_dir, register_document

router = APIRouter(prefix="/api/lesokultury", tags=["lesokultury"])


@router.get("/uchastki")
def list_uchastki(
    include_spisannye: bool = False,
    god: Optional[str] = None,
    search: Optional[str] = None,
    conn=Depends(get_conn),
):
    return legacy_db.get_lesokultury_uchastki(
        conn, include_spisannye=include_spisannye, god=god, search=search,
    )


@router.get("/gody")
def list_gody(conn=Depends(get_conn)):
    """Различные годы создания культур, встречающиеся в базе — для
    выпадающего фильтра «Год» на экране (вместо свободного текста)."""
    return legacy_db.get_lesokultury_gody(conn)


@router.get("/tipy-lesa")
def list_tipy_lesa(glavnaya_poroda: str = ""):
    """Варианты «тип леса» (приложение 18) для главной породы — выпадающий
    список на форме участка; [] значит, что порода не нормируется или у неё
    единственный (безусловный) норматив — поле можно не заполнять."""
    return lesokultury_normativy.get_tipy_lesa_options(glavnaya_poroda)


@router.get("/uchastki/{uchastok_id}")
def get_uchastok(uchastok_id: int, conn=Depends(get_conn)):
    u = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
    if u is None:
        raise HTTPException(404, "Участок не найден")
    return u


@router.post("/uchastki")
def create_uchastok(fields: Dict[str, Any], user=Depends(require_permission("lesokultury.edit")),
                     conn=Depends(get_conn)):
    uchastok_id = legacy_db.create_lesokultury_uchastok(conn, **fields)
    return {"id": uchastok_id}


@router.patch("/uchastki/{uchastok_id}")
def update_uchastok(uchastok_id: int, fields: Dict[str, Any],
                     user=Depends(require_permission("lesokultury.edit")), conn=Depends(get_conn)):
    u = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
    if u is None:
        raise HTTPException(404, "Участок не найден")
    legacy_db.update_lesokultury_uchastok(conn, uchastok_id, **fields)
    webext.touch_updated_by(conn, "lesokultury_uchastok", uchastok_id, user["login"])
    return {"ok": True}


@router.delete("/uchastki/{uchastok_id}")
def delete_uchastok(uchastok_id: int, user=Depends(require_permission("lesokultury.edit")),
                     conn=Depends(get_conn)):
    u = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
    if u is None:
        raise HTTPException(404, "Участок не найден")
    legacy_db.delete_lesokultury_uchastok(conn, uchastok_id)
    return {"ok": True}


@router.get("/uchastki/{uchastok_id}/meropriyatiya")
def list_meropriyatiya(uchastok_id: int, conn=Depends(get_conn)):
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
    srednyaya_vysota_m: Optional[float] = None,
    user=Depends(require_permission("lesokultury.edit")),
    conn=Depends(get_conn),
):
    meropriyatie_id = legacy_db.add_lesokultury_meropriyatie(
        conn, uchastok_id, tip, data,
        prizhivaemost_pct=prizhivaemost_pct, kolichestvo_na_ga=kolichestvo_na_ga,
        sostav_fakt=sostav_fakt, primechaniya=primechaniya,
        srednyaya_vysota_m=srednyaya_vysota_m,
    )
    result = {"id": meropriyatie_id}
    # Норматив приложения 18 сравнивается только для инвентаризации на
    # перевод, и только когда с десктопа явно передали оба нужных числа
    # (пока на вебе нет структурированной формы проб/результатов, как в
    # мобильной карточке — только эти два свободных поля).
    if tip == TIP_PEREVOD_INVENTORY and kolichestvo_na_ga is not None and srednyaya_vysota_m is not None:
        uchastok = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
        if uchastok is not None:
            result["normativ_check"] = lesokultury_normativy.check_normativ_perevoda(
                uchastok.get("glavnaya_poroda"), uchastok.get("tip_lesa"),
                kolichestvo_na_ga / 1000, srednyaya_vysota_m,
            )
    return result


# --------------------------------------------------------------------------- #
#   Полевые карточки с телефона (мастер / пом. лесничего / лесничий)
#   Пишут в ТЕ ЖЕ таблицы, что показывает экран "Лесные культуры":
#   журнал lesokultury_meropriyatiya и статус lesokultury_uchastok.status.
# --------------------------------------------------------------------------- #
TIP_INVENTORY = {1: "Инвентаризация 1-го года", 3: "Инвентаризация 3-го года"}
TIP_PEREVOD_INVENTORY = "Инвентаризация на перевод"
TIP_PEREVOD = "Перевод в покрытые лесом земли"  # на вебе переводит статус в "переведён"
STATUS_PEREVEDEN = "переведён"
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


class PerevodIn(FieldCardBase):
    god: Optional[Literal[1, 3]] = None  # для перевода необязателен
    # Решение — ручной выбор человека; норматив (приложение 18) сервер НЕ
    # проверяет: этих таблиц в системе нет.
    reshenie: Literal["перевести", "не переводить", "доработать"]


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


def _find_glavnaya_poroda_result(rezultaty: List[RezultatIn], glavnaya_poroda: Optional[str]) -> Optional[RezultatIn]:
    """Находит строку результатов обследования (rezultaty), соответствующую
    главной породе участка (сравнение подстрокой, регистронезависимо) — её
    средняя высота идёт в сверку с нормативом приложения 18. None, если
    порода участка не задана или не найдена среди результатов."""
    if not glavnaya_poroda:
        return None
    target = glavnaya_poroda.strip().lower()
    if not target:
        return None
    for r in rezultaty:
        poroda = r.poroda.strip().lower()
        if poroda and (poroda in target or target in poroda):
            return r
    return None


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

    # Средняя высота — берётся из результата обследования по главной породе
    # участка (для сверки с нормативом приложения 18, см. lesokultury_normativy.py);
    # сохраняется в журнал независимо от tip, пригодится и для паспорта участка.
    glavnaya_rezultat = _find_glavnaya_poroda_result(body.rezultaty, uchastok.get("glavnaya_poroda"))
    srednyaya_vysota_m = glavnaya_rezultat.srednyaya_vysota if glavnaya_rezultat else None

    normativ_check = None
    if tip == TIP_PEREVOD_INVENTORY:
        kolichestvo_tys_na_ga = body.kolichestvo_na_ga / 1000 if body.kolichestvo_na_ga is not None else None
        normativ_check = lesokultury_normativy.check_normativ_perevoda(
            uchastok.get("glavnaya_poroda"), uchastok.get("tip_lesa"),
            kolichestvo_tys_na_ga, srednyaya_vysota_m,
        )

    meropriyatie_id = legacy_db.add_lesokultury_meropriyatie(
        conn, uchastok_id, tip, data,
        prizhivaemost_pct=calc["prizhivaemost_pct"],
        kolichestvo_na_ga=body.kolichestvo_na_ga,
        sostav_fakt=body.sostav_fakt,
        primechaniya=_summary_text(body, calc, reshenie),
        dannye=dannye, sotrudnik_id=sotrudnik_id,
        srednyaya_vysota_m=srednyaya_vysota_m,
    )

    status = uchastok["status"]
    perevod_id = None
    if reshenie == "перевести":
        # То же, что делает веб при добавлении мероприятия «Перевод в покрытые
        # лесом земли»: запись в журнал + статус участка «переведён». Норматив
        # приложения 18 — только предупреждение (normativ_check выше), решение
        # "перевести" остаётся полностью за комиссией/пользователем.
        perevod_id = legacy_db.add_lesokultury_meropriyatie(
            conn, uchastok_id, TIP_PEREVOD, data,
            primechaniya=f"По инвентаризации на перевод (запись №{meropriyatie_id})",
            sotrudnik_id=sotrudnik_id,
        )
        legacy_db.update_lesokultury_uchastok(conn, uchastok_id, status=STATUS_PEREVEDEN)
        status = STATUS_PEREVEDEN

    return {
        "id": meropriyatie_id,
        "perevod_id": perevod_id,
        "tip": tip,
        "data": data,
        "status_uchastka": status,
        "normativ_check": normativ_check,
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
    запись «Перевод в покрытые лесом земли» и статус участка «переведён»
    (как на вебе, без дополнительного подтверждения); «не переводить» /
    «доработать» — статус не меняется. Соответствие нормативу
    (приложение 18) сервер не проверяет — решение только ручное."""
    return _record_field_card(conn, uchastok_id, user, body, TIP_PEREVOD_INVENTORY, body.reshenie)


# --------------------------------------------------------------------------- #
#   Документы: "Карточка перевода" (приложение 19)
# --------------------------------------------------------------------------- #
class PodpisantIn(BaseModel):
    dolzhnost: str = ""
    fio: str = ""


class KartochkaPerevodaIn(BaseModel):
    """Ручные поля печатной формы — источника данных для них в базе нет
    (см. Этап 1 плана)."""

    meropriyatie_id: Optional[int] = None
    yuridicheskoe_litso: str = ""
    shema_smesheniya: str = ""
    razmeshenie_v_ryadah_m: str = ""
    mezhdu_ryadami_m: str = ""
    zaklyuchenie_a: str = ""
    zaklyuchenie_b: str = ""
    zaklyuchenie_v: str = ""
    zaklyuchenie_g: str = ""
    zaklyuchenie_d: str = ""
    predsedatel: Optional[PodpisantIn] = None
    chleny: List[PodpisantIn] = Field(default_factory=list)
    data_akta: str = ""


def _run_generate_kartochka_perevoda(task_id: str, uchastok_id: int, body: dict, created_by: Optional[str]):
    conn = get_connection()
    task_dir = new_task_dir(task_id)
    try:
        webext.set_task_running(conn, task_id)
        uchastok = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
        if uchastok is None:
            raise ValueError(f"Участок {uchastok_id} не найден")
        meropriyatie_id = body.pop("meropriyatie_id", None)
        if meropriyatie_id:
            meropriyatie = legacy_db.get_lesokultury_meropriyatie(conn, meropriyatie_id)
        else:
            meropriyatie = legacy_db.get_latest_lesokultury_perevod_meropriyatie(conn, uchastok_id)
        if meropriyatie is None:
            raise ValueError(
                "Нет записи журнала «Инвентаризация на перевод» с данными полевой карточки — "
                "печатать карточку не из чего."
            )
        output_path = task_dir / f"Kartochka_perevoda_{uchastok_id}.docx"
        path = kartochka_perevoda_generator.generate_kartochka_perevoda(
            uchastok, meropriyatie, str(output_path), **body
        )
        doc_id = register_document(
            conn, "lesokultury_kartochka_perevoda", None, path,
            created_by=created_by, lesokultury_uchastok_id=uchastok_id,
        )
        webext.set_task_done(conn, task_id, result={"document_ids": [doc_id]})
    except Exception as e:  # noqa: BLE001
        register_document(
            conn, "lesokultury_kartochka_perevoda", None, "",
            created_by=created_by, status="ошибка", error_text=str(e),
            lesokultury_uchastok_id=uchastok_id,
        )
        webext.set_task_error(conn, task_id, str(e))
    finally:
        conn.close()


@router.post("/uchastki/{uchastok_id}/documents/kartochka-perevoda")
def generate_kartochka_perevoda(
    uchastok_id: int,
    body: KartochkaPerevodaIn,
    background_tasks: BackgroundTasks,
    user=Depends(require_permission("documents.generate")),
    conn=Depends(get_conn),
):
    uchastok = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
    if uchastok is None:
        raise HTTPException(404, "Участок не найден")
    task_id = webext.create_task(conn, "generate_kartochka_perevoda")
    background_tasks.add_task(
        _run_generate_kartochka_perevoda, task_id, uchastok_id, body.model_dump(), user["login"],
    )
    return {"task_id": task_id}
