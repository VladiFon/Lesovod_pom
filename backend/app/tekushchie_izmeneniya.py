# -*- coding: utf-8 -*-
"""
Ведомости текущих изменений (приказ Минлесхоза №130 от 10.06.2026) из
«Лесных культур»: прил. 4 (перевод в покрытые лесом земли), прил. 7
(культуры, созданные в отчётном году) и прил. 14 (списание — перевод из
одного вида земель в другой).

Строки собираются из участков и журнала мероприятий; Word заполняется по
шаблону лесничества «Таблицы … ЗАПОЛНЯТЬ ЗДЕСЬ.docx» (лежит в
app/shablony/, можно прислать свой): остальные приложения и шапки шаблона
не трогаются, в них меняются только год и дата заполнения.

Участок культур часто заходит в несколько таксационных выделов и в каждом
становится своим подвыделом — тогда в ведомости по строке на выдел. Такие
части задаются на участке (chasti_json: [{vydel, podvydel, ploshad}]);
если их нет и выдел один, строка берётся из самого участка.
"""
import copy
import datetime as dt
import io
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app import legacy_bridge  # noqa: F401
from app.lesokultury_kniga import vydel_tokens

TEMPLATE_PATH = Path(__file__).resolve().parent / "shablony" / "tekushchie_izmeneniya.docx"

TIP_PEREVOD = "Перевод в покрытые лесом земли"
TIP_SPISANIE = "Списание"
TIPY_PRIZHIVAEMOSTI = ("Инвентаризация 1-го года", "Техническая приёмка")

# Заголовки столбцов — как в формах приказа (для предпросмотра на сайте).
COLUMNS = {
    4: ["Кв.", "Выдел (подвыдел) по лесоустройству", "Площадь, га", "Выдел (подвыдел)", "Площадь, га",
        "Состав", "Возраст, лет", "Высота, м", "Диаметр, см", "Полнота"],
    7: ["Кв.", "Выдел по лесоустройству", "Площадь, га", "Выдел (подвыдел)", "Площадь, га",
        "Метод, способ создания", "Состав", "Обработка почвы", "Между рядами, м", "В ряду, м",
        "Количество, шт/га", "Приживаемость, %"],
    14: ["Кв.", "Выдел", "Площадь, га", "Вид земель", "Состав", "Возраст, лет", "Высота, м",
         "Диаметр, см", "Полнота", "Тип леса", "Причина перевода"],
}
TITLES = {
    4: "Прил. 4 — несомкнувшиеся лесные культуры, переведённые в покрытые лесом земли",
    7: "Прил. 7 — лесные культуры, созданные в отчётном году",
    14: "Прил. 14 — участки, переведённые из одного вида земель в другой (списание культур)",
}


class TIError(Exception):
    """Ошибка, понятная человеку (показывается на сайте как есть)."""


# --------------------------------------------------------------------------- #
#   Сбор строк
# --------------------------------------------------------------------------- #
def _norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower().replace("ё", "е")


def _year_of(text) -> Optional[int]:
    found = re.findall(r"(?:19|20)\d{2}", str(text or ""))
    return int(found[-1]) if found else None


def fmt(value) -> str:
    """Число без лишних нулей: 4421.0 -> «4421», 0.60 -> «0.6»; текст как есть."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        text = f"{float(value):.3f}".rstrip("0").rstrip(".")
        return text if text != "-0" else "0"
    return str(value).strip()


def _cap(text) -> str:
    text = str(text or "").strip()
    return text[:1].upper() + text[1:] if text else ""


def _num(value) -> Optional[float]:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _taxation_ploshad(conn, lesnichestvo: str) -> Dict[Tuple[str, str], str]:
    """{(квартал, выдел): площадь по лесоустройству} для лесничества."""
    target = _norm(lesnichestvo)
    try:
        rows = conn.execute(
            "SELECT l.name, k.nomer, v.nomer, v.ploshad FROM vydel v "
            "JOIN kvartal k ON k.id = v.kvartal_id JOIN lesnichestvo l ON l.id = k.lesnichestvo_id"
        ).fetchall()
    except Exception:  # noqa: BLE001 — таблиц таксации может не быть
        return {}
    result = {}
    for name, kv, vd, pl in rows:
        n = _norm(name)
        if target and n != target and target not in n and n not in target:
            continue
        result[(str(kv).strip(), str(vd).strip())] = fmt(_num(pl)) if _num(pl) is not None else str(pl or "")
    return result


def _uchastki(conn, lesnichestvo: str) -> List[dict]:
    conn_rows = conn.execute("SELECT * FROM lesokultury_uchastok ORDER BY id").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM lesokultury_uchastok LIMIT 0").description]
    target = _norm(lesnichestvo)
    out = []
    for row in conn_rows:
        u = dict(zip(cols, row))
        own = _norm(u.get("lesnichestvo"))
        if target and own and own != target and target not in own and own not in target:
            continue
        out.append(u)
    return out


def _meropriyatiya(conn) -> Dict[int, List[dict]]:
    rows = conn.execute(
        "SELECT uchastok_id, tip, data, prizhivaemost_pct, sostav_fakt, primechaniya, dannye_json, id "
        "FROM lesokultury_meropriyatiya ORDER BY id"
    ).fetchall()
    result: Dict[int, List[dict]] = {}
    for uid, tip, data, pct, sostav, prim, dannye, mid in rows:
        try:
            parsed = json.loads(dannye) if dannye else {}
        except ValueError:
            parsed = {}
        result.setdefault(uid, []).append({
            "id": mid, "tip": tip, "data": data, "prizhivaemost_pct": pct,
            "sostav_fakt": sostav or "", "primechaniya": prim or "", "dannye": parsed or {},
        })
    return result


def chasti(u: dict) -> List[dict]:
    """Части участка по выделам: [{vydel, podvydel, ploshad}]. Без заданных
    частей — одна часть из самого участка (для нескольких выделов — по
    части на выдел, площадь не известна)."""
    raw = u.get("chasti_json")
    if raw:
        try:
            parts = json.loads(raw)
        except ValueError:
            parts = []
        clean = [
            {"vydel": str(p.get("vydel") or "").strip(), "podvydel": str(p.get("podvydel") or "").strip(),
             "ploshad": _num(p.get("ploshad"))}
            for p in parts if isinstance(p, dict) and (p.get("vydel") or p.get("podvydel"))
        ]
        if clean:
            return clean
    tokens = vydel_tokens(str(u.get("vydel") or ""))
    if len(tokens) <= 1:
        return [{"vydel": tokens[0] if tokens else "", "podvydel": str(u.get("podvydel") or "").strip(),
                 "ploshad": _num(u.get("ploshad"))}]
    return [{"vydel": t, "podvydel": "", "ploshad": None} for t in tokens]


def _mesto(u: dict) -> str:
    return f"кв. {u.get('kvartal') or '—'} выд. {u.get('vydel') or '—'}"


def _chasti_warning(u: dict, parts: List[dict]) -> Optional[str]:
    if len(parts) > 1 and any(p["ploshad"] is None for p in parts):
        return (f"{_mesto(u)}: участок в нескольких выделах — укажите на участке части по выделам "
                "(подвыдел и площадь в каждом)")
    return None


def build(conn, god: int, lesnichestvo: str = "") -> dict:
    """Строки прил. 4, 7, 14 за год: {4: {"rows": [[...]], "warnings": [...]}, ...}."""
    taxation = _taxation_ploshad(conn, lesnichestvo)
    mer = _meropriyatiya(conn)
    result = {n: {"rows": [], "warnings": [], "uchastki": 0} for n in (4, 7, 14)}

    for u in _uchastki(conn, lesnichestvo):
        kv = str(u.get("kvartal") or "").strip()
        parts = chasti(u)
        journal = mer.get(u["id"], [])

        # --- Прил. 7: создан в отчётном году
        if _year_of(u.get("god_sozdaniya")) == god:
            res = result[7]
            res["uchastki"] += 1
            pct = next((m["prizhivaemost_pct"] for m in reversed(journal)
                        if m["tip"] in TIPY_PRIZHIVAEMOSTI and m["prizhivaemost_pct"] is not None), None)
            missing = [name for name, val in (
                ("способ обработки почвы", u.get("sposob_obrabotki")),
                ("схема посадки", u.get("shema_mezhdu_ryadami") and u.get("shema_v_ryadu")),
                ("подвыдел", all(p["podvydel"] for p in parts)),
                ("приживаемость (инвентаризация 1-го года)", pct is not None),
            ) if not val]
            if missing:
                res["warnings"].append(f"{_mesto(u)}: не заполнено — " + ", ".join(missing))
            warn = _chasti_warning(u, parts)
            if warn:
                res["warnings"].append(warn)
            for p in parts:
                res["rows"].append([
                    kv, p["vydel"], taxation.get((kv, p["vydel"]), ""),
                    p["podvydel"] or p["vydel"], fmt(p["ploshad"]),
                    _cap(u.get("metod_sozdaniya")), u.get("sostav_formula") or "",
                    _cap(u.get("sposob_obrabotki")), fmt(u.get("shema_mezhdu_ryadami")),
                    fmt(u.get("shema_v_ryadu")), fmt(u.get("gustota_posadki")), fmt(pct),
                ])

        # --- Прил. 4: перевод в отчётном году
        perevod = [m for m in journal if m["tip"] == TIP_PEREVOD and _year_of(m["data"]) == god]
        if perevod:
            m = perevod[-1]
            t = m["dannye"].get("taksatsiya") or {}
            res = result[4]
            res["uchastki"] += 1
            missing = [name for name, key in (("возраст", "vozrast"), ("высота", "vysota"),
                                              ("диаметр", "diametr"), ("полнота", "polnota"))
                       if t.get(key) in (None, "")]
            if missing:
                res["warnings"].append(f"{_mesto(u)}: в таксации при переводе нет — " + ", ".join(missing))
            warn = _chasti_warning(u, parts)
            if warn:
                res["warnings"].append(warn)
            sostav = t.get("sostav") or m["sostav_fakt"] or u.get("sostav_formula") or ""
            one = len(parts) == 1
            for p in parts:
                old = p["podvydel"] or p["vydel"]
                res["rows"].append([
                    kv, old, fmt(p["ploshad"]),
                    (t.get("podvydel") if one and t.get("podvydel") else old),
                    fmt(_num(t.get("ploshad")) if one and t.get("ploshad") else p["ploshad"]),
                    sostav, fmt(t.get("vozrast")), fmt(t.get("vysota")),
                    fmt(t.get("diametr")), fmt(t.get("polnota")),
                ])

        # --- Прил. 14: списание в отчётном году
        spisanie = [m for m in journal if m["tip"] == TIP_SPISANIE and _year_of(m["data"]) == god]
        if spisanie:
            m = spisanie[-1]
            d = m["dannye"]
            res = result[14]
            res["uchastki"] += 1
            if not d.get("vid_zemel"):
                res["warnings"].append(f"{_mesto(u)}: не указан вид земель после списания")
            warn = _chasti_warning(u, parts)
            if warn:
                res["warnings"].append(warn)
            prichina = d.get("prichina") or m["primechaniya"] or ""
            akt = " ".join(x for x in (
                f"акт №{d['akt_nomer']}" if d.get("akt_nomer") else "",
                f"от {d['akt_data']}" if d.get("akt_data") else "",
            ) if x)
            for p in parts:
                res["rows"].append([
                    kv, p["podvydel"] or p["vydel"], fmt(p["ploshad"]), d.get("vid_zemel") or "",
                    "", "", "", "", "", "", "; ".join(x for x in (prichina, akt) if x),
                ])

    for n in result:
        result[n]["rows"].sort(key=lambda r: (_sort_num(r[0]), _sort_num(r[1])))
    return result


def _sort_num(text) -> tuple:
    parts = re.findall(r"\d+", str(text))
    return tuple(int(x) for x in parts) or (10 ** 9,)


# --------------------------------------------------------------------------- #
#   Word
# --------------------------------------------------------------------------- #
def _para_text(p) -> str:
    return "".join(r.text for r in p.runs)


def _set_para_text(p, text: str) -> None:
    runs = p.runs
    if runs:
        runs[0].text = text
        for r in runs[1:]:
            r._element.getparent().remove(r._element)
    else:
        p.add_run(text)


def _set_cell(cell, text: str) -> None:
    paras = cell.paragraphs
    for extra in paras[1:]:
        extra._element.getparent().remove(extra._element)
    _set_para_text(paras[0], text)


def _is_data_row(row) -> bool:
    first = row.cells[0].text.strip()
    return first == "" or bool(re.fullmatch(r"\d+([.,]\d+)?", first))


def _fill_table(table, rows: List[List[str]], min_rows: int = 3) -> None:
    trs = table.rows
    data_idx = next((i for i, r in enumerate(trs) if _is_data_row(r)), len(trs))
    proto = copy.deepcopy((trs[data_idx] if data_idx < len(trs) else trs[-1])._tr)
    for r in list(trs)[data_idx:]:
        r._tr.getparent().remove(r._tr)
    for values in rows or [[""] * len(table.columns)] * min_rows:
        tr = copy.deepcopy(proto)
        table._tbl.append(tr)
        row = table.rows[-1]
        for i, cell in enumerate(row.cells):
            _set_cell(cell, values[i] if i < len(values) else "")


def _tables_by_prilozhenie(doc) -> Dict[int, object]:
    """Таблица каждого приложения — по ближайшему выше абзацу «Приложение N»."""
    from docx.table import Table
    result = {}
    current = None
    for el in doc.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = "".join(t.text or "" for t in el.iter() if t.tag.endswith("}t"))
            m = re.search(r"Приложение\s+(\d+)\s*$", text.strip()) or re.match(r"^\s*Приложение\s+(\d+)\b", text)
            if m and "к Инструкции" not in text:
                current = int(m.group(1))
        elif tag == "tbl" and current is not None and current not in result:
            result[current] = Table(el, doc._body)
    return result


def _update_headers(doc, god: int, data_zapolneniya: str) -> None:
    for p in doc.paragraphs:
        text = _para_text(p)
        new = re.sub(r"(текущих изменений за\s*)(?:19|20)\d{2}", lambda m: f"{m.group(1)}{god}", text)
        new = re.sub(r"(Дата заполнения[_\s]*)\d{2}\.\d{2}\.\d{4}", lambda m: f"{m.group(1)}{data_zapolneniya}", new)
        new = re.sub(r"(на 01\.01\.)(?:19|20)\d{2}", lambda m: f"{m.group(1)}{god}", new)
        if new != text:
            _set_para_text(p, new)


def make_docx(data: dict, god: int, template: Optional[bytes] = None,
              data_zapolneniya: Optional[str] = None) -> bytes:
    from docx import Document

    try:
        doc = Document(io.BytesIO(template) if template else str(TEMPLATE_PATH))
    except Exception as exc:  # noqa: BLE001
        raise TIError(f"Не удалось открыть шаблон Word: {exc}")
    tables = _tables_by_prilozhenie(doc)
    missing = [n for n in data if n not in tables]
    if missing:
        raise TIError("В шаблоне не найдены таблицы приложений: " + ", ".join(str(n) for n in missing))
    for n, part in data.items():
        _fill_table(tables[n], part["rows"])
    _update_headers(doc, god, data_zapolneniya or dt.date.today().strftime("%d.%m.%Y"))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
