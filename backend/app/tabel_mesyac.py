# -*- coding: utf-8 -*-
"""Табель за месяц (разбор сайта 09.11.2026, шаг 2).

Раньше табель был только «по дню»: посмотреть месяц целиком, отдать его в
бухгалтерию или распечатать было нельзя. Здесь — сетка «люди × числа»
из той же таблицы tabel_zapis (одна запись на человека за день), массовое
заполнение («протянул мышкой») и выгрузка в Excel по образцу формы Т-13:
буквенные коды, часы, итоги дней и часов.

Массовое заполнение меняет только СТАТУС дня: если на этот день уже было
записано место работы (делянка/культуры/проба) и вид работы, они остаются,
кроме случая, когда статус — не «работал» (тогда место очищается: в отпуске
человек на делянке не был).
"""
import calendar
from datetime import date, datetime
from io import BytesIO

from app.putevye import prazdnik

# Коды как в форме Т-13 (Я — явка, Б — больничный, ОТ — отпуск, В — выходной,
# К — командировка, НН — неявка). «Ремонт» в Т-13 нет — РМ.
KODY = {
    "работал": "Я",
    "не работал": "НН",
    "больничный": "Б",
    "отпуск": "ОТ",
    "выходной": "В",
    "ремонт": "РМ",
    "командировка": "К",
}
CHASOV_V_DEN = 8
RABOCHIE = ("работал", "командировка", "ремонт")


def _ym(ym):
    y, m = (int(x) for x in str(ym).split("-")[:2])
    if not (2000 <= y <= 2100 and 1 <= m <= 12):
        raise ValueError("Месяц в виде ГГГГ-ММ")
    return y, m


def dni_mesyaca(ym):
    y, m = _ym(ym)
    n = calendar.monthrange(y, m)[1]
    out = []
    for d in range(1, n + 1):
        dt = date(y, m, d)
        pr = prazdnik(dt)
        out.append({
            "den": d,
            "data": dt.isoformat(),
            "nedelya": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][dt.weekday()],
            "vyhodnoy": dt.weekday() >= 5 or bool(pr),
            "prazdnik": pr,
        })
    return out


def get_mesyac(conn, ym):
    y, m = _ym(ym)
    dni = dni_mesyaca(ym)
    pervyy, posledniy = dni[0]["data"], dni[-1]["data"]
    lyudi = conn.execute(
        "SELECT id, fio, dolzhnost FROM sotrudniki WHERE is_active=1 "
        "OR id IN (SELECT sotrudnik_id FROM tabel_zapis WHERE data BETWEEN ? AND ?) "
        "ORDER BY fio COLLATE NOCASE",
        (pervyy, posledniy),
    ).fetchall()
    zapisi = conn.execute(
        "SELECT sotrudnik_id, data, status, delyanka_item_id, lesokultury_uchastok_id, uhody_proba_id "
        "FROM tabel_zapis WHERE data BETWEEN ? AND ?",
        (pervyy, posledniy),
    ).fetchall()
    po_lyudyam = {}
    for sid, d, st, di, lk, pr in zapisi:
        po_lyudyam.setdefault(sid, {})[str(int(d[8:10]))] = {
            "status": st,
            "kod": KODY.get(st, "?"),
            "mesto": bool(di or lk or pr),
        }
    segodnya = date.today().isoformat()
    out = []
    for sid, fio, dolzh in lyudi:
        dni_ch = po_lyudyam.get(sid, {})
        itogo = {"yavki": 0, "chasov": 0, "bolnichnyy": 0, "otpusk": 0, "nn": 0, "vyhodnye": 0, "pusto": 0}
        for dd in dni:
            z = dni_ch.get(str(dd["den"]))
            if not z:
                # «не заполнено» — только прошедшие будни, будущее ещё рано
                if not dd["vyhodnoy"] and dd["data"] <= segodnya:
                    itogo["pusto"] += 1
                continue
            st = z["status"]
            if st in RABOCHIE:
                itogo["yavki"] += 1
                itogo["chasov"] += CHASOV_V_DEN
            elif st == "больничный":
                itogo["bolnichnyy"] += 1
            elif st == "отпуск":
                itogo["otpusk"] += 1
            elif st == "не работал":
                itogo["nn"] += 1
            elif st == "выходной":
                itogo["vyhodnye"] += 1
        out.append({"id": sid, "fio": fio, "dolzhnost": dolzh or "", "dni": dni_ch, "itogo": itogo})
    rabochih = sum(1 for d in dni if not d["vyhodnoy"])
    return {"ym": f"{y:04d}-{m:02d}", "dni": dni, "rabochih_dney": rabochih, "lyudi": out, "kody": KODY}


def zapolnit(conn, ym, sotrudnik_ids, dni, status, entered_by):
    """Поставить статус людям на выбранные числа месяца. status="" — стереть."""
    y, m = _ym(ym)
    if status and status not in KODY:
        raise ValueError(f"Неизвестный статус: {status}")
    n = calendar.monthrange(y, m)[1]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sdelano = 0
    for sid in sotrudnik_ids:
        if not conn.execute("SELECT 1 FROM sotrudniki WHERE id=?", (sid,)).fetchone():
            raise ValueError(f"Сотрудник id={sid} не найден")
        for d in dni:
            d = int(d)
            if not 1 <= d <= n:
                continue
            data = date(y, m, d).isoformat()
            if not status:
                conn.execute("DELETE FROM tabel_zapis WHERE sotrudnik_id=? AND data=?", (sid, data))
                sdelano += 1
                continue
            est = conn.execute("SELECT id FROM tabel_zapis WHERE sotrudnik_id=? AND data=?", (sid, data)).fetchone()
            if est:
                if status in RABOCHIE:
                    conn.execute("UPDATE tabel_zapis SET status=?, entered_by=?, updated_at=? WHERE id=?",
                                 (status, entered_by, now, est[0]))
                else:
                    conn.execute(
                        "UPDATE tabel_zapis SET status=?, delyanka_item_id=NULL, lesokultury_uchastok_id=NULL, "
                        "uhody_proba_id=NULL, entered_by=?, updated_at=? WHERE id=?",
                        (status, entered_by, now, est[0]))
            else:
                conn.execute(
                    "INSERT INTO tabel_zapis (sotrudnik_id, data, status, kommentariy, entered_by, created_at, updated_at) "
                    "VALUES (?, ?, ?, '', ?, ?, ?)",
                    (sid, data, status, entered_by, now, now))
            sdelano += 1
    conn.commit()
    return sdelano


MESYACY = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
           "сентябрь", "октябрь", "ноябрь", "декабрь"]


def xlsx(conn, ym, organizaciya=""):
    """Табель за месяц в Excel по образцу Т-13: строка кодов и строка часов
    на человека, итоги. Возвращает bytes."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    t = get_mesyac(conn, ym)
    y, m = _ym(ym)
    dni = t["dni"]
    wb = Workbook()
    ws = wb.active
    ws.title = f"{MESYACY[m - 1]} {y}"
    thin = Side(style="thin", color="999999")
    rama = Border(left=thin, right=thin, top=thin, bottom=thin)
    centr = Alignment(horizontal="center", vertical="center", wrap_text=True)
    seryy = PatternFill("solid", fgColor="EDEDED")
    zhir = Font(bold=True)

    ws["A1"] = "ТАБЕЛЬ учёта рабочего времени"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"{organizaciya + ' · ' if organizaciya else ''}за {MESYACY[m - 1]} {y} г. · рабочих дней по календарю: {t['rabochih_dney']}"
    ws["A3"] = "Я — явка (8 ч), В — выходной, Б — больничный, ОТ — отпуск, К — командировка, НН — неявка, РМ — ремонт техники"
    ws["A3"].font = Font(size=9, color="555555")

    shapka = 5
    kol_dney = 4
    ws.cell(shapka, 1, "№")
    ws.cell(shapka, 2, "Ф.И.О.")
    ws.cell(shapka, 3, "Должность")
    ws.cell(shapka, 4, "")
    for i, d in enumerate(dni):
        c = ws.cell(shapka, kol_dney + 1 + i, d["den"])
        if d["vyhodnoy"]:
            c.fill = seryy
    itogi = ["Дней явок", "Часов", "Больн.", "Отпуск", "Неявки"]
    k0 = kol_dney + 1 + len(dni)
    for j, h in enumerate(itogi):
        ws.cell(shapka, k0 + j, h)
    for c in ws[shapka]:
        c.font = zhir
        c.alignment = centr
        c.border = rama

    r = shapka + 1
    for n, ch in enumerate(t["lyudi"], 1):
        ws.cell(r, 1, n)
        ws.cell(r, 2, ch["fio"])
        ws.cell(r, 3, ch["dolzhnost"])
        ws.cell(r, 4, "код")
        ws.cell(r + 1, 4, "часы")
        for i, d in enumerate(dni):
            z = ch["dni"].get(str(d["den"]))
            kod = z["kod"] if z else ""
            ws.cell(r, kol_dney + 1 + i, kod)
            ws.cell(r + 1, kol_dney + 1 + i, CHASOV_V_DEN if z and z["status"] in RABOCHIE else None)
            if d["vyhodnoy"]:
                ws.cell(r, kol_dney + 1 + i).fill = seryy
                ws.cell(r + 1, kol_dney + 1 + i).fill = seryy
        it = ch["itogo"]
        for j, v in enumerate([it["yavki"], it["chasov"], it["bolnichnyy"], it["otpusk"], it["nn"]]):
            ws.cell(r, k0 + j, v)
            ws.merge_cells(start_row=r, start_column=k0 + j, end_row=r + 1, end_column=k0 + j)
        for col in (1, 2, 3):
            ws.merge_cells(start_row=r, start_column=col, end_row=r + 1, end_column=col)
        for rr in (r, r + 1):
            for c in ws[rr][: k0 + len(itogi) - 1]:
                c.border = rama
                c.alignment = centr
        ws.cell(r, 2).alignment = Alignment(horizontal="left", vertical="center")
        r += 2

    ws.cell(r + 1, 2, "Табель составил: ______________________")
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 5
    for i in range(len(dni)):
        ws.column_dimensions[get_column_letter(kol_dney + 1 + i)].width = 3.6
    for j in range(len(itogi)):
        ws.column_dimensions[get_column_letter(k0 + j)].width = 7
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.freeze_panes = ws.cell(shapka + 1, kol_dney + 1)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
