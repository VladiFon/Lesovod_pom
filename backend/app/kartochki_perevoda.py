# -*- coding: utf-8 -*-
"""
Полевые карточки инвентаризации лесных культур, переводимых в покрытые
лесом земли (Word, по карточке на участок) -> таксация для прил. 4
ведомостей текущих изменений.

Из карточки берётся:
  - п. 3–4 — квартал и выдел; в скобках — новый выдел по таксации
    («6,7,8,9 (30)»): он идёт в графу «Выдел (подвыдел)» прил. 4;
  - п. 7–8 — год закладки и площадь;
  - п. 11 «в пересчёте на 1 гектар» — количество и средняя высота по
    породам: высота главной породы, количество всех пород -> полнота по
    таблице молодняков (app/polnota.py);
  - п. 12б — состав, если участок переводится («—» — не переводится),
    п. 12д — площадь к списанию.
Возраст — отчётный год минус год закладки, диаметр в карточке не пишется:
у переводимых культур он всегда DIAMETR_SM.

Участок в базе ищется по кварталу, году закладки и выделу (старому или
новому); если таких несколько — по номеру карточки из книги л/к и площади.
Сначала предпросмотр (в базу не пишет), потом запись: таксация дописывается
в запись «Перевод в покрытые лесом земли» отчётного года (или такая запись
создаётся).
"""
import io
import json
import re
from typing import Dict, List, Optional

from app import polnota as polnota_mod
from app.lesokultury_kniga import vydel_tokens

TIP_PEREVOD = "Перевод в покрытые лесом земли"
STATUS_PEREVEDEN = "переведён"
DIAMETR_SM = 2

MESYACY = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8,
           "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}


class KartochkiError(Exception):
    """Ошибка, понятная человеку."""


def _num(text) -> Optional[float]:
    s = str(text or "").strip().replace(",", ".")
    if s.startswith("."):
        s = "0" + s
    try:
        return float(s)
    except ValueError:
        return None


def _uniq(cells: List[str]) -> List[str]:
    """Объединённые ячейки Word повторяются — оставляем по одной."""
    out: List[str] = []
    for c in cells:
        if not out or out[-1] != c:
            out.append(c)
    return out


def _data(text: str) -> str:
    """«22» сентября 2026 г. -> 22.09.2026."""
    m = re.search(r"(\d{1,2})\D+?([а-яё]+)\s+(\d{4})", text or "", re.I)
    if not m:
        return ""
    mes = next((n for k, n in MESYACY.items() if m.group(2).lower().startswith(k)), None)
    return f"{int(m.group(1)):02d}.{mes:02d}.{m.group(3)}" if mes else ""


def parse(data: bytes) -> List[dict]:
    from docx import Document

    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise KartochkiError("Не удалось открыть файл — нужен Word (.docx) с полевыми карточками") from exc
    cards: List[dict] = []
    cur: Optional[dict] = None
    for t in doc.tables:
        rows = [[c.text.strip() for c in r.cells] for r in t.rows]
        first = rows[0][0] if rows and rows[0] else ""
        if first.startswith("Полевая карточка"):
            nomer = next((c for c in rows[0][1:] if re.fullmatch(r"\d+", c)), "")
            cur = {"nomer": nomer, "porody": [], "reshenie": "", "sostav": ""}
            cards.append(cur)
            continue
        if cur is None:
            continue
        if first.startswith("1. Юридическое"):
            for r in rows:
                u = _uniq(r)
                k = u[0]
                if k.startswith("2. Лесничество") and len(u) > 1:
                    cur["lesnichestvo"] = u[1]
                elif k.startswith("3. Лесной квартал") and len(u) > 1:
                    cur["kvartal"] = u[1].strip()
                    v = u[3] if len(u) > 3 else ""
                    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", v)
                    cur["vydel"] = (m.group(1) if m else v).replace(" ", "")
                    cur["vydel_novyy"] = m.group(2).strip() if m else ""
                elif k.startswith("5. ТЛУ") and len(u) > 1:
                    cur["tlu"] = u[1]
                elif k.startswith("7. Год закладки") and len(u) > 1:
                    cur["god_zakladki"] = u[1].strip()
                    cur["ploshad"] = _num(u[3]) if len(u) > 3 else None
                elif k.startswith("9. Схема") and len(u) > 1:
                    cur["shema"] = u[1]
        elif first.startswith("Номер пробных"):
            section = ""
            for r in rows[2:]:
                if r[0]:
                    section = r[0]
                if section.startswith("В пересчете") and len(r) > 4 and r[2]:
                    cur["porody"].append({"poroda": r[2], "na_ga": _num(r[3]), "vysota": _num(r[4])})
        elif first.startswith("12. Заключение"):
            for r in rows:
                if r[0].startswith("б)"):
                    s = r[-1].strip()
                    cur["sostav"] = "" if s in ("—", "-", "–") or s.startswith("б)") else s
                elif r[0].startswith("в)"):
                    cur["meropriyatiya"] = r[0].split("рубки прочистки)")[-1].strip(" —")
                elif r[0].startswith("г)"):
                    cur["povtor"] = next((c for c in r if re.fullmatch(r"\d{4}", c)), "")
                elif r[0].startswith("д)"):
                    cur["spisat_ga"] = next((_num(c) for c in r[1:] if _num(c)), None)
        elif first.startswith("Председатель"):
            for r in rows:
                if "«" in r[0]:
                    cur["data"] = _data(r[0])
    for c in cards:
        c["reshenie"] = "перевод" if c["sostav"] else ("списание" if c.get("spisat_ga") else "не переводится")
    if not cards:
        raise KartochkiError("В файле не найдено полевых карточек перевода лесных культур")
    return cards


def taksatsiya(card: dict, god: int) -> dict:
    """Таксация для прил. 4 из карточки."""
    sostav = card.get("sostav") or ""
    glavnaya = polnota_mod.glavnaya_poroda(sostav)
    porody = card.get("porody") or []
    gl = next((p for p in porody if p["poroda"] == glavnaya), None) or (porody[0] if porody else None)
    vsego = sum(p["na_ga"] or 0 for p in porody)
    tys = round(vsego / 1000, 2) if vsego else None
    poln, nizhe = polnota_mod.po_kolichestvu(tys, sostav, kultury=True)
    god_z = int(card["god_zakladki"]) if re.fullmatch(r"\d{4}", str(card.get("god_zakladki") or "")) else None
    out = {
        "nomer_kartochki": card.get("nomer") or "",
        "sostav": sostav,
        "vozrast": god - god_z if god_z else None,
        "vysota": gl["vysota"] if gl else None,
        "diametr": DIAMETR_SM,
        "polnota": poln,
        "kolichestvo_tys_na_ga": tys,
        "ploshad": card.get("ploshad"),
        # Выдел(ы) именно этого перевода по карточке: в книге строка участка
        # бывает склеена из нескольких («19,20,23,26,28»), а переводится 26.
        "vydel_kartochki": ", ".join(vydel_tokens(card.get("vydel") or "")),
    }
    if card.get("vydel_novyy"):
        out["podvydel"] = card["vydel_novyy"]
    if nizhe:
        out["polnota_nizhe_tablicy"] = True
    return {k: v for k, v in out.items() if v not in (None, "")}


def _uchastki(conn) -> List[dict]:
    cols = [d[0] for d in conn.execute("SELECT * FROM lesokultury_uchastok LIMIT 0").description]
    return [dict(zip(cols, r)) for r in conn.execute("SELECT * FROM lesokultury_uchastok").fetchall()]


def _perevody(conn) -> Dict[int, List[dict]]:
    out: Dict[int, List[dict]] = {}
    for mid, uid, data, dannye in conn.execute(
        "SELECT id, uchastok_id, data, dannye_json FROM lesokultury_meropriyatiya WHERE tip = ? ORDER BY id",
        (TIP_PEREVOD,),
    ).fetchall():
        try:
            parsed = json.loads(dannye) if dannye else {}
        except ValueError:
            parsed = {}
        out.setdefault(uid, []).append({"id": mid, "data": data or "", "dannye": parsed or {}})
    return out


def _god_of(text) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", str(text or ""))
    return int(m.group(0)) if m else None


def plan(conn, cards: List[dict], god: int, lesnichestvo: str = "") -> dict:
    from app.tekushchie_izmeneniya import _lesn_match, _norm

    uchastki = _uchastki(conn)
    perevody = _perevody(conn)
    target = _norm(lesnichestvo)
    rows = []
    for i, c in enumerate(cards):
        kv = str(c.get("kvartal") or "").strip()
        tokens = set(vydel_tokens(c.get("vydel") or "")) | set(vydel_tokens(c.get("vydel_novyy") or ""))
        god_z = str(c.get("god_zakladki") or "")
        cand = [
            u for u in uchastki
            if str(u.get("kvartal") or "").strip() == kv
            and str(u.get("god_sozdaniya") or "")[:4] == god_z
            and (not target or _lesn_match(target, u.get("lesnichestvo")))
            and tokens & (set(vydel_tokens(str(u.get("vydel") or ""))) | set(vydel_tokens(str(u.get("vydel_staryy") or ""))))
        ]
        kak = ""
        if len(cand) > 1 and c.get("nomer"):
            po_nomeru = [u for u in cand if any(
                str((p["dannye"].get("taksatsiya") or {}).get("nomer_kartochki") or "") == c["nomer"]
                for p in perevody.get(u["id"], []))]
            if len(po_nomeru) == 1:
                cand, kak = po_nomeru, "по номеру карточки"
        if len(cand) > 1 and c.get("ploshad") is not None:
            po_ploshadi = [u for u in cand if abs((u.get("ploshad") or 0) - c["ploshad"]) < 0.05]
            if len(po_ploshadi) == 1:
                cand, kak = po_ploshadi, "по площади"
        problemy = []
        if not cand:
            problemy.append("участок не найден в «Лесокультурах»")
        elif len(cand) > 1:
            problemy.append("подходит несколько участков: " + ", ".join(
                f"№{u['id']} выд. {u.get('vydel')} {u.get('ploshad')} га" for u in cand))
        u = cand[0] if len(cand) == 1 else None
        t = taksatsiya(c, god) if c["reshenie"] == "перевод" else {}
        if t.get("polnota_nizhe_tablicy"):
            problemy.append(f"деревьев {t.get('kolichestvo_tys_na_ga')} тыс./га — ниже таблицы полноты, "
                            f"поставлено {t.get('polnota')}")
        est_perevod = bool(u and [p for p in perevody.get(u["id"], []) if _god_of(p["data"]) == god])
        rows.append({
            "key": str(i),
            "nomer": c.get("nomer") or "",
            "kvartal": kv,
            "vydel": c.get("vydel") or "",
            "vydel_novyy": c.get("vydel_novyy") or "",
            "god_zakladki": god_z,
            "ploshad": c.get("ploshad"),
            "reshenie": c["reshenie"],
            "taksatsiya": t,
            "data": c.get("data") or "",
            "uchastok_id": u["id"] if u else None,
            "uchastok": f"№{u['id']}: кв. {u.get('kvartal')} выд. {u.get('vydel')}, {u.get('ploshad')} га" if u else "",
            "kak_nayden": kak or ("по выделу" if u else ""),
            "est_perevod": est_perevod,
            "problemy": problemy,
        })
    perevod = [r for r in rows if r["reshenie"] == "перевод"]
    summary = {
        "vsego": len(rows),
        "perevod": len(perevod),
        "spisanie": sum(1 for r in rows if r["reshenie"] == "списание"),
        "ne_perevoditsya": sum(1 for r in rows if r["reshenie"] == "не переводится"),
        "naydeno": sum(1 for r in perevod if r["uchastok_id"]),
        "ne_naydeno": sum(1 for r in perevod if not r["uchastok_id"]),
        "nizhe_tablicy": sum(1 for r in perevod if r["taksatsiya"].get("polnota_nizhe_tablicy")),
    }
    return {"summary": summary, "rows": rows}


def apply(conn, plan_: dict, god: int, skip: List[str]) -> dict:
    """Дописывает таксацию из карточек в переводы отчётного года (или
    заводит перевод, если его нет). Остальные поля записи не трогаются."""
    import db as legacy_db

    perevody = _perevody(conn)
    obnovleno = sozdano = propushcheno = 0
    skip_set = set(skip or [])
    for r in plan_["rows"]:
        if r["reshenie"] != "перевод" or not r["uchastok_id"]:
            continue
        if r["key"] in skip_set:
            propushcheno += 1
            continue
        uid = r["uchastok_id"]
        t = dict(r["taksatsiya"])
        est = [p for p in perevody.get(uid, []) if _god_of(p["data"]) == god]
        if est:
            p = est[-1]
            dannye = dict(p["dannye"])
            old = dict(dannye.get("taksatsiya") or {})
            old.pop("polnota_nizhe_tablicy", None)
            old.update(t)
            dannye["taksatsiya"] = old
            dannye["kartochka"] = f"полевая карточка №{r['nomer']}" if r["nomer"] else "полевая карточка"
            conn.execute("UPDATE lesokultury_meropriyatiya SET dannye_json = ?, sostav_fakt = COALESCE(NULLIF(sostav_fakt, ''), ?) "
                         "WHERE id = ?", (json.dumps(dannye, ensure_ascii=False), t.get("sostav") or "", p["id"]))
            obnovleno += 1
        else:
            legacy_db.add_lesokultury_meropriyatie(
                conn, uid, TIP_PEREVOD, r["data"] or str(god),
                sostav_fakt=t.get("sostav") or "",
                primechaniya=f"Из полевой карточки №{r['nomer']}" if r["nomer"] else "Из полевой карточки",
                dannye={"taksatsiya": t, "kartochka": f"полевая карточка №{r['nomer']}"},
            )
            legacy_db.update_lesokultury_uchastok(conn, uid, status=STATUS_PEREVEDEN)
            sozdano += 1
    conn.commit()
    return {"obnovleno": obnovleno, "sozdano": sozdano, "propushcheno": propushcheno}
