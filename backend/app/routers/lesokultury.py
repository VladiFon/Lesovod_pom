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
from app import kartochki_perevoda
from app import lesokultury_kniga
from app import vidy
import db as legacy_db

from app.auth import require_office_writer_or_master
from app.auth import get_current_user
from app.auth import require_permission
from app import korzina
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


def _proverit_vid_kultur(fields: Dict[str, Any]) -> None:
    if "vid_kultur" in fields:
        try:
            fields["vid_kultur"] = vidy.proverit_vid_kultur(fields["vid_kultur"])
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.post("/uchastki")
def create_uchastok(fields: Dict[str, Any], conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit"))):
    _proverit_vid_kultur(fields)
    uchastok_id = legacy_db.create_lesokultury_uchastok(conn, **fields)
    return {"id": uchastok_id}


@router.patch("/uchastki/{uchastok_id}")
def update_uchastok(uchastok_id: int, fields: Dict[str, Any], conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit"))):
    u = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
    if u is None:
        raise HTTPException(404, "Участок не найден")
    _proverit_vid_kultur(fields)
    legacy_db.update_lesokultury_uchastok(conn, uchastok_id, **fields)
    return {"ok": True}


@router.delete("/uchastki/{uchastok_id}")
def delete_uchastok(uchastok_id: int, conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit"))):
    u = legacy_db.get_lesokultury_uchastok(conn, uchastok_id)
    if u is None:
        raise HTTPException(404, "Участок не найден")
    nazvanie = f"Кв. {u.get('kvartal') or '—'} / Выд. {u.get('vydel') or '—'}" + (f", {u.get('god_sozdaniya')} г." if u.get("god_sozdaniya") else "")
    snap = korzina.snapshot_uchastok(conn, uchastok_id)
    korzina.polozhit(conn, "lesokultury_uchastok", uchastok_id, nazvanie,
                     snap, _user["login"])
    korzina.otvyazat(conn, snap)
    legacy_db.delete_lesokultury_uchastok(conn, uchastok_id)
    return {"ok": True, "v_korzine": True}


class ObedinitIn(BaseModel):
    lishnie: List[int]


# Не переносятся при объединении (служебные / собственные у каждого участка).
_NE_PERENOSIT = {"id", "created_at", "updated_at", "updated_by"}


@router.post("/uchastki/{uchastok_id}/obedinit")
def obedinit_uchastki(uchastok_id: int, body: ObedinitIn, conn=Depends(get_conn),
                      _user=Depends(require_permission("lesokultury.edit"))):
    """Участок заведён дважды (из книги и ещё раз вручную / из QGIS):
    пустые поля основного дополняются из лишних, их журнал мероприятий и
    ссылки (пробы, отчёты) и дописанное к строкам ведомостей переходят к
    основному, лишние удаляются."""
    lishnie = [i for i in dict.fromkeys(body.lishnie) if i != uchastok_id]
    if not lishnie:
        raise HTTPException(400, "Не указаны лишние участки")
    cols = [d[0] for d in conn.execute("SELECT * FROM lesokultury_uchastok LIMIT 0").description]

    def row(uid):
        r = conn.execute("SELECT * FROM lesokultury_uchastok WHERE id = ?", (uid,)).fetchone()
        if r is None:
            raise HTTPException(404, f"Участок №{uid} не найден")
        return dict(zip(cols, r))

    main = row(uchastok_id)
    for uid in lishnie:
        extra = row(uid)
        fill = {c: extra[c] for c in cols
                if c not in _NE_PERENOSIT and str(main.get(c) or "").strip() == "" and str(extra.get(c) or "").strip()}
        if fill:
            conn.execute(f"UPDATE lesokultury_uchastok SET {', '.join(f'{c} = ?' for c in fill)} WHERE id = ?",
                         (*fill.values(), uchastok_id))
            main.update(fill)
        conn.execute("UPDATE lesokultury_meropriyatiya SET uchastok_id = ? WHERE uchastok_id = ?", (uchastok_id, uid))
        for sql in ("UPDATE raw_reports SET lesokultury_uchastok_id = ? WHERE lesokultury_uchastok_id = ?",):
            try:
                conn.execute(sql, (uchastok_id, uid))
            except Exception:  # noqa: BLE001 — таблицы может не быть в старой базе
                pass
        try:
            for pid, ids_json in conn.execute(
                "SELECT id, lesokultury_uchastok_ids_json FROM uhody_proby WHERE lesokultury_uchastok_ids_json LIKE ?",
                (f"%{uid}%",),
            ).fetchall():
                ids = json.loads(ids_json or "[]")
                if uid in ids:
                    ids = list(dict.fromkeys(uchastok_id if i == uid else i for i in ids))
                    conn.execute("UPDATE uhody_proby SET lesokultury_uchastok_ids_json = ? WHERE id = ?",
                                 (json.dumps(ids), pid))
        except Exception:  # noqa: BLE001
            pass
        # Дописанное к строкам ведомостей переходит к основному участку, если
        # у него по той же строке своего нет (номер части тот же).
        try:
            for god, pril, klyuch in conn.execute(
                "SELECT god, prilozhenie, klyuch FROM tek_izm_popravki WHERE klyuch LIKE ?", (f"u{uid}:%",)
            ).fetchall():
                novyy = f"u{uchastok_id}:" + klyuch.split(":", 1)[1]
                if conn.execute("SELECT 1 FROM tek_izm_popravki WHERE god = ? AND prilozhenie = ? AND klyuch = ?",
                                (god, pril, novyy)).fetchone() is None:
                    conn.execute("UPDATE tek_izm_popravki SET klyuch = ? WHERE god = ? AND prilozhenie = ? AND klyuch = ?",
                                 (novyy, god, pril, klyuch))
            conn.execute("DELETE FROM tek_izm_popravki WHERE klyuch LIKE ?", (f"u{uid}:%",))
        except Exception:  # noqa: BLE001 — таблицы может ещё не быть
            pass
        conn.execute("DELETE FROM lesokultury_uchastok WHERE id = ?", (uid,))
    conn.commit()
    return {"ok": True, "id": uchastok_id, "udaleno": lishnie}


# --------------------------------------------------------------------------- #
#   Контур участка (схема-чертёж) — для карты вместо всего выдела
# --------------------------------------------------------------------------- #
def _kontur_row(conn, uchastok_id: int):
    row = conn.execute("SELECT ploshad, geom_geojson FROM lesokultury_uchastok WHERE id = ?",
                       (uchastok_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Участок не найден")
    return row


@router.get("/uchastki/{uchastok_id}/kontur")
def get_kontur(uchastok_id: int, conn=Depends(get_conn), _user=Depends(get_current_user)):
    """{"geometry": GeoJSON | null, "ploshad_kontura": га}."""
    _, geom = _kontur_row(conn, uchastok_id)
    if not geom:
        return {"geometry": None, "ploshad_kontura": None}
    from shapely.geometry import shape

    geometry = json.loads(geom)
    from app import kontur as kontur_mod
    import geopandas as gpd

    area = gpd.GeoSeries([shape(geometry)], crs="EPSG:4326").to_crs(kontur_mod.DEFAULT_METRIC_CRS).area.iloc[0]
    return {"geometry": geometry, "ploshad_kontura": round(float(area) / 10000.0, 2)}


@router.post("/uchastki/{uchastok_id}/kontur")
async def upload_kontur(uchastok_id: int, file: UploadFile = File(...), conn=Depends(get_conn),
                        _user=Depends(require_permission("lesokultury.edit"))):
    """Файл контура участка: GeoJSON, shp в .zip, KML или GPKG (из QGIS / GPS)."""
    from app import kontur as kontur_mod

    ploshad, _ = _kontur_row(conn, uchastok_id)
    try:
        geometry, area = kontur_mod.parse(await file.read(), file.filename or "")
    except kontur_mod.KonturError as exc:
        raise HTTPException(400, str(exc))
    conn.execute("UPDATE lesokultury_uchastok SET geom_geojson = ? WHERE id = ?",
                 (json.dumps(geometry, ensure_ascii=False), uchastok_id))
    conn.commit()
    try:
        own = float(str(ploshad).replace(",", "."))
    except (TypeError, ValueError):
        own = None
    warning = None
    if own and abs(own - area) > max(0.1, own * 0.1):
        warning = f"Площадь контура {area} га, у участка записано {own} га — проверьте"
    return {"ok": True, "ploshad_kontura": area, "warning": warning}


@router.delete("/uchastki/{uchastok_id}/kontur")
def delete_kontur(uchastok_id: int, conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit"))):
    _kontur_row(conn, uchastok_id)
    conn.execute("UPDATE lesokultury_uchastok SET geom_geojson = NULL WHERE id = ?", (uchastok_id,))
    conn.commit()
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
    korzina.avtokopiya(conn, "pered_knigoy_lk")
    plan = await _kniga_plan(conn, file, lesnichestvo, god_from, god_to, overrides)
    try:
        skip_keys = json.loads(skip) if skip else []
    except ValueError:
        raise HTTPException(400, "skip: ожидается JSON-список")
    return lesokultury_kniga.apply_import(conn, plan, lesnichestvo.strip(), skip_keys)


# --------------------------------------------------------------------------- #
#   Полевые карточки перевода в покрытые лесом земли (Word) -> таксация для
#   прил. 4 текущих изменений. См. app/kartochki_perevoda.py.
# --------------------------------------------------------------------------- #
async def _kartochki_plan(conn, file: UploadFile, god: int, lesnichestvo: str):
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(400, "Файл больше 50 МБ")
    try:
        cards = kartochki_perevoda.parse(data)
    except kartochki_perevoda.KartochkiError as exc:
        raise HTTPException(400, str(exc))
    return kartochki_perevoda.plan(conn, cards, god, lesnichestvo.strip())


@router.post("/kartochki-perevoda/preview")
async def kartochki_perevoda_preview(
    file: UploadFile = File(...),
    god: int = Form(...),
    lesnichestvo: str = Form(""),
    conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit")),
):
    """Разбор карточек и сверка с участками — В БАЗУ НЕ ПИШЕТ."""
    return await _kartochki_plan(conn, file, god, lesnichestvo)


@router.post("/kartochki-perevoda/apply")
async def kartochki_perevoda_apply(
    file: UploadFile = File(...),
    god: int = Form(...),
    lesnichestvo: str = Form(""),
    skip: Optional[str] = Form(None),
    conn=Depends(get_conn), _user=Depends(require_permission("lesokultury.edit")),
):
    """Та же сверка + запись таксации в переводы отчётного года. Повторная
    загрузка тех же карточек только перезаписывает те же значения."""
    korzina.avtokopiya(conn, "pered_kartochkami")
    plan = await _kartochki_plan(conn, file, god, lesnichestvo)
    try:
        skip_keys = json.loads(skip) if skip else []
    except ValueError:
        raise HTTPException(400, "skip: ожидается JSON-список")
    return kartochki_perevoda.apply(conn, plan, god, skip_keys)


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


class UchastokPolyaIn(BaseModel):
    """Поля участка, которые дописывают в лесу с телефона (для прил. 7
    ведомости текущих изменений). Не переданное (null) не меняется."""

    podvydel: Optional[str] = Field(default=None, max_length=20)
    metod_sozdaniya: Optional[str] = Field(default=None, max_length=100)
    sposob_obrabotki: Optional[str] = Field(default=None, max_length=100)
    shema_mezhdu_ryadami: Optional[float] = Field(default=None, gt=0, le=20)
    shema_v_ryadu: Optional[float] = Field(default=None, gt=0, le=20)
    gustota_posadki: Optional[float] = Field(default=None, gt=0, le=100000)
    posadochnyy_material: Optional[str] = Field(default=None, max_length=200)


@router.patch("/{uchastok_id}/polya")
def update_polya(
    uchastok_id: int,
    body: UchastokPolyaIn,
    conn=Depends(get_conn),
    user=Depends(require_office_writer_or_master),
):
    """Правка полей участка с телефона — мастеру не нужно право
    lesokultury.edit, но менять можно только эти поля (не статус,
    не квартал/выдел)."""
    if legacy_db.get_lesokultury_uchastok(conn, uchastok_id) is None:
        raise HTTPException(404, "Участок не найден")
    fields = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump().items() if v is not None}
    if fields:
        legacy_db.update_lesokultury_uchastok(conn, uchastok_id, **fields)
    return {"ok": True, "izmeneno": sorted(fields)}
