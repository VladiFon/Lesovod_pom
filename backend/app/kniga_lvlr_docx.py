# -*- coding: utf-8 -*-
"""Печать вклейки в бумажную Книгу учёта площадей ЛВ и ЛР (Word).

Размеры — в миллиметрах, как в книге Влада: строка ровно 6 мм, ширины граф
из Настроек книги (по умолчанию — его замеры). Каждая часть разворота —
на своём листе А4 альбомном: часть 1 (графы 1–19) и часть 2 (графы 20–29).
Шапки нет (она уже в книге) — только узкая строка номеров граф, по ней удобно
приложить и отрезать. Печатать «Фактический размер / 100%», не «по размеру
страницы».
"""
import io
import math
from typing import Dict, List, Optional

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from app import kniga_lvlr as kn

STROKA_MM = 6.0
NOMERA_MM = 4.0
POLE_MM = 0.4      # отступ текста от линии слева/справа
PT_MM = 0.3528


def _shrift(tekst: str, shir_mm: float, vys_mm: float, bazovyy: float) -> float:
    """Самый крупный шрифт (от базового вниз), при котором текст влезает в клетку."""
    t = str(tekst or "")
    if not t:
        return bazovyy
    for pt in (bazovyy, 6.5, 6, 5.5, 5, 4.5, 4):
        if pt > bazovyy:
            continue
        sim_mm = 0.5 * pt * PT_MM               # средняя ширина буквы Arial/Times
        v_stroke = max(1, int((shir_mm - 2 * POLE_MM) / sim_mm))
        strok = max(1, int((vys_mm - 0.4) / (pt * PT_MM * 1.05)))
        # перенос по словам съедает часть строки — берём с запасом 15%
        if math.ceil(len(t) * 1.15 / v_stroke) <= strok:
            return pt
    return 4


def _granitsy(tbl, est: bool) -> None:
    tblPr = tbl._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for storona in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{storona}")
        e.set(qn("w:val"), "single" if est else "nil")
        if est:
            e.set(qn("w:sz"), "4")
            e.set(qn("w:space"), "0")
            e.set(qn("w:color"), "000000")
        b.append(e)
    tblPr.append(b)
    lay = OxmlElement("w:tblLayout")
    lay.set(qn("w:type"), "fixed")
    tblPr.append(lay)
    mar = OxmlElement("w:tblCellMar")
    for storona, mm in (("top", 0), ("bottom", 0), ("left", POLE_MM), ("right", POLE_MM)):
        e = OxmlElement(f"w:{storona}")
        e.set(qn("w:w"), str(int(mm * 56.7)))
        e.set(qn("w:type"), "dxa")
        mar.append(e)
    tblPr.append(mar)


def _tekst(cell, tekst: str, pt: float, bold=False) -> None:
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = p.paragraph_format
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(pt * 1.05)
    r = p.add_run(str(tekst or ""))
    r.font.size = Pt(pt)
    r.font.name = "Arial"
    r.bold = bold


def _list(doc, novyy: bool):
    if novyy:
        sec = doc.add_section()
    else:
        sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Mm(297), Mm(210)
    sec.left_margin = sec.right_margin = Mm(10)
    sec.top_margin = sec.bottom_margin = Mm(10)
    return sec


def _podpis(doc, tekst: str, pervyy: bool) -> None:
    p = doc.paragraphs[0] if pervyy and doc.paragraphs else doc.add_paragraph()
    r = p.add_run(tekst)
    r.font.size = Pt(7)
    r.font.name = "Arial"
    p.paragraph_format.space_after = Pt(2)


def _tablica(doc, grafy: List[int], shiriny_sm: List[float], stroki: List[Dict[int, str]],
             nomera_graf: bool, setka: bool, bazovyy_pt: float, slit: List[tuple]) -> None:
    n_str = len(stroki) + (1 if nomera_graf else 0)
    tbl = doc.add_table(rows=n_str, cols=len(grafy))
    tbl.autofit = False
    _granitsy(tbl, setka)
    grid = tbl._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), shiriny_sm):
        gc.set(qn("w:w"), str(int(w * 10 * 56.7)))
    for i, row in enumerate(tbl.rows):
        zag = nomera_graf and i == 0
        row.height = Mm(NOMERA_MM if zag else STROKA_MM)
        row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        for j, cell in enumerate(row.cells):
            cell.width = Mm(shiriny_sm[j] * 10)
    if nomera_graf:
        for j, g in enumerate(grafy):
            _tekst(tbl.rows[0].cells[j], str(g), 5.5, bold=True)
    sdvig = 1 if nomera_graf else 0
    # Записи на 2–3 строки — клетки сливаются по вертикали.
    zanyato = set()
    for (s, k) in slit:
        for j in range(len(grafy)):
            verh = tbl.cell(s + sdvig, j)
            niz = tbl.cell(s + sdvig + k - 1, j)
            verh.merge(niz)
        zanyato.update(range(s + 1, s + k))
    vysota = {s: k for s, k in slit}
    for i, znach in enumerate(stroki):
        if i in zanyato:
            continue
        vys = STROKA_MM * vysota.get(i, 1)
        for j, g in enumerate(grafy):
            t = znach.get(g, "")
            if t:
                _tekst(tbl.cell(i + sdvig, j), t, _shrift(t, shiriny_sm[j] * 10, vys, bazovyy_pt))


def vkleyka(conn, razvorot: int, chast: str = "obe", stroka_s: int = 1, stroka_po: int = kn.STROK_NA_RAZVOROTE,
            nomera_graf: bool = True, setka: bool = True, tolko_ids: Optional[List[int]] = None) -> bytes:
    """Word-файл: часть 1 и/или часть 2 одного разворота, строки с..по."""
    n = kn.nastroyki(conn)
    stroka_s = max(1, min(stroka_s, kn.STROK_NA_RAZVOROTE))
    stroka_po = max(stroka_s, min(stroka_po, kn.STROK_NA_RAZVOROTE))
    kol = stroka_po - stroka_s + 1
    stroki: List[Dict[int, str]] = [{} for _ in range(kol)]
    slit = []
    for z in kn.zapisi(conn):
        if z["razvorot"] != razvorot or (tolko_ids and z["id"] not in tolko_ids):
            continue
        i = z["stroka"] - stroka_s
        if i < 0 or i >= kol:
            continue
        stroki[i] = {1: str(z["nomer"]), **z["grafy"]}
        k = min(int(z["strok"] or 1), kol - i)
        if k > 1:
            slit.append((i, k))
    doc = Document()
    chasti = [("1", kn.CHAST_1, n["shiriny_1"]), ("2", kn.CHAST_2, n["shiriny_2"])]
    if chast in ("1", "2"):
        chasti = [c for c in chasti if c[0] == chast]
    for idx, (nom, grafy, shir) in enumerate(chasti):
        _list(doc, novyy=idx > 0)
        _podpis(doc, f"Книга учёта площадей ЛВ и ЛР · разворот {razvorot} · часть {nom} "
                     f"(графы {grafy[0]}–{grafy[-1]}) · строки {stroka_s}–{stroka_po} · печатать 100%, "
                     f"ширина {sum(shir) * 10:g} мм", pervyy=idx == 0)
        _tablica(doc, grafy, shir, stroki, nomera_graf, setka, float(n["shrift_pt"]), slit)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def kalibrovka(conn) -> bytes:
    """Пробный лист: линейка 100 мм и пустая сетка обеих частей с ширинами
    граф — приложить к книге и проверить, что принтер не ужал масштаб."""
    n = kn.nastroyki(conn)
    doc = Document()
    _list(doc, novyy=False)
    _podpis(doc, "Проверка печати. Линия ниже должна быть ровно 100 мм. Если короче или длиннее — "
                 "в печати выключите «по размеру страницы» (масштаб 100%).", pervyy=True)
    lin = doc.add_table(rows=1, cols=1)
    lin.autofit = False
    _granitsy(lin, True)
    lin._tbl.tblGrid.findall(qn("w:gridCol"))[0].set(qn("w:w"), str(int(100 * 56.7)))
    lin.rows[0].height = Mm(3)
    lin.rows[0].height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    lin.rows[0].cells[0].width = Mm(100)
    for nom, grafy, shir in (("1", kn.CHAST_1, n["shiriny_1"]), ("2", kn.CHAST_2, n["shiriny_2"])):
        _podpis(doc, f"Часть {nom}: ширины граф, см", pervyy=False)
        stroki = [{g: f"{w:g}".replace(".", ",") for g, w in zip(grafy, shir)}] + [{} for _ in range(2)]
        _tablica(doc, grafy, shir, stroki, True, True, 6.0, [])
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
