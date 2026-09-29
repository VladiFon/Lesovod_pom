# -*- coding: utf-8 -*-
"""Роутер «Текущие изменения» — ведомости по приказу Минлесхоза №130
(см. app/tekushchie_izmeneniya.py): предпросмотр всех приложений, ручные
строки и Word по шаблону."""
import json
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app import tekushchie_izmeneniya as ti
from app.auth import get_current_user, require_office_writer_or_master
from app.database import get_conn

router = APIRouter(prefix="/api/tekushchie-izmeneniya", tags=["tekushchie-izmeneniya"])

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _check_god(god: int) -> None:
    if not 2000 <= god <= 2100:
        raise HTTPException(400, "Год — четыре цифры, например 2026")


def _svodnaya_rows(svod: dict) -> list:
    """Прил. 2 для экрана: [{stroka, nazvanie, ploshad, kolichestvo}]."""
    from docx import Document

    labels = {}
    try:
        doc = Document(str(ti.TEMPLATE_PATH))
        table = ti._tables_by_prilozhenie(doc).get(2)
        if table is not None:
            labels = {i: r.cells[0].text.strip() for i, r in enumerate(table.rows)}
    except Exception:  # noqa: BLE001 — подписи не главное
        pass
    return [
        {"stroka": n, "nazvanie": labels.get(n, f"строка {n}"), "ploshad": ti.fmt(area) if count else "",
         "kolichestvo": count}
        for n, (area, count) in sorted(svod.items())
    ]


@router.get("")
def preview(
    god: int,
    lesnichestvo: str = "",
    conn=Depends(get_conn), _user=Depends(get_current_user),
):
    """Строки всех приложений за год, замечания (чего не хватает) и сводная прил. 2."""
    _check_god(god)
    lesnichestvo = ti.resolve_lesnichestvo(lesnichestvo)
    data = ti.build(conn, god, lesnichestvo)
    return {
        "god": god,
        "lesnichestvo": lesnichestvo,
        "svodnaya": _svodnaya_rows(data["svodnaya"]),
        "diagnostika": ti.diagnostika(conn, god, lesnichestvo),
        "dubli": data.get("dubli", []),
        "prilozheniya": [
            {"nomer": n, "title": ti.TITLES[n], "columns": ti.COLUMNS[n], "istochnik": ti.ISTOCHNIKI.get(n, ""),
             "rows": data[n]["rows"], "keys": data[n]["keys"], "pustye": data[n]["pustye"],
             "popravleno": data[n]["popravleno"], "chasti_info": data[n].get("chasti_info", {}),
             "warnings": data[n]["warnings"], "uchastki": data[n]["uchastki"],
             "avto": data[n]["avto"], "ruchnye": data[n]["ruchnye"]}
            for n in ti.NOMERA
        ],
    }


class RuchnayaIn(BaseModel):
    god: int
    lesnichestvo: str = ""
    prilozhenie: int
    values: List[str]


class RuchnayaPatch(BaseModel):
    values: List[str]


def _clean_values(prilozhenie: int, values: List[str]) -> str:
    if prilozhenie not in ti.COLUMNS:
        raise HTTPException(400, "Нет такого приложения")
    cols = len(ti.COLUMNS[prilozhenie])
    clean = [str(v or "").strip() for v in values][:cols]
    if not any(clean):
        raise HTTPException(400, "Строка пустая")
    return json.dumps(clean + [""] * (cols - len(clean)), ensure_ascii=False)


@router.post("/ruchnye")
def add_ruchnaya(body: RuchnayaIn, conn=Depends(get_conn), _user=Depends(require_office_writer_or_master)):
    """Строка, введённая вручную, в любое приложение (3–15)."""
    _check_god(body.god)
    ti.ensure_table(conn)
    cur = conn.execute(
        "INSERT INTO tek_izm_ruchnye (god, lesnichestvo, prilozhenie, znacheniya_json) VALUES (?, ?, ?, ?)",
        (body.god, ti.resolve_lesnichestvo(body.lesnichestvo), body.prilozhenie, _clean_values(body.prilozhenie, body.values)),
    )
    conn.commit()
    return {"id": cur.lastrowid}


@router.patch("/ruchnye/{row_id}")
def edit_ruchnaya(row_id: int, body: RuchnayaPatch, conn=Depends(get_conn),
                  _user=Depends(require_office_writer_or_master)):
    ti.ensure_table(conn)
    row = conn.execute("SELECT prilozhenie FROM tek_izm_ruchnye WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Строка не найдена")
    conn.execute("UPDATE tek_izm_ruchnye SET znacheniya_json = ? WHERE id = ?",
                 (_clean_values(row[0], body.values), row_id))
    conn.commit()
    return {"ok": True}


@router.delete("/ruchnye/{row_id}")
def delete_ruchnaya(row_id: int, conn=Depends(get_conn), _user=Depends(require_office_writer_or_master)):
    ti.ensure_table(conn)
    conn.execute("DELETE FROM tek_izm_ruchnye WHERE id = ?", (row_id,))
    conn.commit()
    return {"ok": True}


class PopravkaIn(BaseModel):
    god: int
    lesnichestvo: str = ""
    prilozhenie: int
    klyuch: str
    values: List[str]


@router.put("/popravki")
def save_popravka(body: PopravkaIn, conn=Depends(get_conn), _user=Depends(require_office_writer_or_master)):
    """Дописать недостающее в автоматическую строку (хранятся только
    изменённые графы; пустые значения по сравнению с исходными — тоже)."""
    _check_god(body.god)
    try:
        ti.save_popravka(conn, body.god, body.prilozhenie, body.klyuch, body.values,
                         ti.resolve_lesnichestvo(body.lesnichestvo))
    except ti.TIError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.delete("/popravki")
def delete_popravka(god: int, prilozhenie: int, klyuch: str, conn=Depends(get_conn),
                    _user=Depends(require_office_writer_or_master)):
    """Вернуть строку к автоматическим значениям."""
    ti.ensure_popravki(conn)
    conn.execute("DELETE FROM tek_izm_popravki WHERE god = ? AND prilozhenie = ? AND klyuch = ?",
                 (god, prilozhenie, klyuch))
    conn.commit()
    return {"ok": True}


class ChastIn(BaseModel):
    vydel: str = ""
    podvydel: str = ""
    ploshad: Optional[float] = None


class ChastiIn(BaseModel):
    istochnik: str  # "u" — участок лесных культур, "d" — выдел делянки
    id: int
    chasti: List[ChastIn]


@router.put("/chasti")
def save_chasti(body: ChastiIn, conn=Depends(get_conn), _user=Depends(require_office_writer_or_master)):
    """Разбивка участка культур / выдела делянки по таксационным выделам —
    пишется в сам участок/выдел (chasti_json), пустой список убирает разбивку."""
    table = {"u": "lesokultury_uchastok", "d": "delyanka_item"}.get(body.istochnik)
    if table is None:
        raise HTTPException(400, "Неизвестный источник")
    chasti = [
        {"vydel": c.vydel.strip(), "podvydel": c.podvydel.strip(), "ploshad": c.ploshad}
        for c in body.chasti if c.vydel.strip() or c.podvydel.strip()
    ]
    if any(c["ploshad"] is not None and c["ploshad"] < 0 for c in chasti):
        raise HTTPException(400, "Площадь не может быть отрицательной")
    if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (body.id,)).fetchone() is None:
        raise HTTPException(404, "Не найдено")
    conn.execute(f"UPDATE {table} SET chasti_json = ? WHERE id = ?",
                 (json.dumps(chasti, ensure_ascii=False) if chasti else None, body.id))
    conn.commit()
    return {"ok": True}


@router.post("/docx")
async def docx(
    god: int = Form(...),
    lesnichestvo: str = Form(""),
    data_zapolneniya: str = Form(""),
    ploshad_nachalo: str = Form(""),
    ploshad_konec: str = Form(""),
    shablon: Optional[UploadFile] = File(None),
    conn=Depends(get_conn), _user=Depends(get_current_user),
):
    """Word по шаблону ведомостей: заполняются таблицы прил. 2–15, в шапках
    меняются год и дата заполнения, в прил. 1 — общая площадь. shablon —
    свой «Таблицы … ЗАПОЛНЯТЬ ЗДЕСЬ.docx» (если не прислан — встроенный)."""
    _check_god(god)
    template = await shablon.read() if shablon is not None else None
    lesnichestvo = ti.resolve_lesnichestvo(lesnichestvo)
    data = ti.build(conn, god, lesnichestvo)
    try:
        content = ti.make_docx(data, god, template or None, data_zapolneniya.strip() or None,
                               ploshad_nachalo, ploshad_konec)
    except ti.TIError as exc:
        raise HTTPException(400, str(exc))
    name = f"Текущие изменения {god}" + (f" {lesnichestvo.strip()}" if lesnichestvo.strip() else "") + ".docx"
    return Response(
        content,
        media_type=DOCX_TYPE,
        headers={"Content-Disposition": f"attachment; filename=\"tekushchie_izmeneniya_{god}.docx\"; "
                                        f"filename*=UTF-8''{quote(name)}"},
    )
