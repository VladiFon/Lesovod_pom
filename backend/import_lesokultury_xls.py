# -*- coding: utf-8 -*-
"""
Импорт участков лесных культур из "Книги производства л/к" (.xls, лист на
каждый год) в таблицу lesokultury_uchastok приложения lesovod.

Куда положить: рядом с папками app/ и legacy/ (т.е. в backend/), затем
запускать из backend/.

Использование:
    pip install xlrd --break-system-packages   # если ещё не установлен
    cd backend
    python import_lesokultury_xls.py --xls "/путь/Болбасовское.xls" --dry-run
    python import_lesokultury_xls.py --xls "/путь/Болбасовское.xls"

По умолчанию обрабатываются годы 2017–2026 (листы книги). База берётся из
той же переменной окружения, что и у сервера — LESOVOD_DB_PATH (см.
legacy/config.py); можно переопределить флагом --db.

Скрипт безопасно перезапускать: каждой добавленной записи в поле
"Примечания" дописывается служебная метка вида
"[импорт xls: 2019/07]" (год листа / № записи в листе), и перед вставкой
скрипт проверяет, нет ли уже участка с такой меткой — повторный запуск не
создаёт дублей.

СТРУКТУРА КОЛОНОК В ИСХОДНОМ ФАЙЛЕ РАЗНАЯ У РАЗНЫХ ЛЕТ (сдвиг на пару
столбцов у листов 2017/2018) — карта столбцов ниже подобрана и проверена
вручную по фактическим данным каждого листа (см. COLMAP/DEFAULT_MAP).
Перед боевым запуском обязательно проверьте вывод --dry-run на нескольких
записях по каждому году — особенно квартал/выдел/площадь.
"""
import argparse
import re
import sys
from pathlib import Path

try:
    import xlrd
except ImportError:
    sys.exit(
        "Не найден модуль xlrd. Установите: pip install xlrd --break-system-packages"
    )

# --- делаем backend/legacy доступной для import db / import config, как в app/legacy_bridge.py ---
LEGACY_DIR = Path(__file__).resolve().parent / "legacy"
if str(LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_DIR))

import db as legacy_db          # noqa: E402
import config as legacy_config  # noqa: E402


# --------------------------------------------------------------------------- #
#  Карта колонок (0-indexed) по годам.
#  Проверено на фактических строках данных каждого листа книги.
# --------------------------------------------------------------------------- #
DEFAULT_MAP = dict(kvartal=2, vydel=3, tlu=4, ploshad=5, ploshad_pokr=6,
                    sposob=7, posev=8, posadka=9, poroda=10,
                    block=[11, 12, 13], harakteristika=14)

COLMAP = {
    "2017.": dict(kvartal=2, vydel=3, tlu=6, ploshad=7, ploshad_pokr=8,
                  sposob=9, posev=10, posadka=11, poroda=12,
                  block=[13, 14], harakteristika=15),
    # 2018 и далее используют DEFAULT_MAP
}

ALL_YEARS = ["2017.", "2018 .", "2019", "2020", "2021", "2022", "2023",
             "2024", "2025", "2026"]

SOSTAV_HINT_RE = re.compile(r"\d[А-ЯЁ]")      # напр. "6Е4Б", "Е,8Е2Лп"
SCHEME_RE = re.compile(r"\d[.,]?\d*\s*[*xх]\s*\d")  # напр. "3,0*0,9"


# --------------------------------------------------------------------------- #
#  Разбор
# --------------------------------------------------------------------------- #
def clean_num(v):
    if v == "" or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def clean_text(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else str(v)
    return str(v).strip()


def classify_block(vals):
    """Классифицирует значения блока 'схема размещения/густота/состав' —
    возвращает (sostav_formula, gustota, [доп. текст для примечаний])."""
    sostav = None
    gustota = None
    extra = []
    for v in vals:
        if v is None or v == "":
            continue
        if isinstance(v, (int, float)):
            if gustota is None:
                gustota = float(v)
            else:
                extra.append(f"доп.значение: {clean_text(v)}")
            continue
        text = str(v).strip()
        if not text:
            continue
        if SCHEME_RE.search(text):
            extra.append(f"схема размещения: {text}")
        elif SOSTAV_HINT_RE.search(text):
            sostav = text
        else:
            extra.append(text)
    return sostav, gustota, extra


def parse_sheet(wb, year_name, lesnichestvo):
    s = wb.sheet_by_name(year_name)
    cmap = COLMAP.get(year_name, DEFAULT_MAP)
    year = year_name.strip().rstrip(".").strip()
    records = []
    for r in range(6, s.nrows):
        kvartal_raw = s.cell_value(r, cmap["kvartal"])
        ploshad = clean_num(s.cell_value(r, cmap["ploshad"]))
        if kvartal_raw in ("", None) or ploshad is None or ploshad <= 0:
            continue

        vydel = clean_text(s.cell_value(r, cmap["vydel"]))
        tlu = clean_text(s.cell_value(r, cmap["tlu"]))
        sposob = clean_text(s.cell_value(r, cmap["sposob"]))
        posev = clean_num(s.cell_value(r, cmap["posev"]))
        posadka = clean_num(s.cell_value(r, cmap["posadka"]))
        poroda = clean_text(s.cell_value(r, cmap["poroda"]))
        block_vals = [s.cell_value(r, c) for c in cmap["block"] if c < s.ncols]
        sostav, gustota, extra = classify_block(block_vals)
        harakteristika_raw = s.cell_value(r, cmap["harakteristika"])
        harakteristika = clean_text(harakteristika_raw)
        opisanie = clean_text(s.cell_value(r, 1))
        nomer = clean_text(s.cell_value(r, 0))

        if posadka:
            metod = "посадка"
        elif posev:
            metod = "посев"
        else:
            metod = ""

        prim_parts = []
        if opisanie:
            prim_parts.append(f"исх.данные: {opisanie}")
        if sposob:
            prim_parts.append(f"обработка почвы: {sposob}")
        if harakteristika:
            # харакеристика материала иногда ошибочно занесена числом —
            # подписываем нейтрально, чтобы не приписывать ей ложный смысл
            if isinstance(harakteristika_raw, (int, float)):
                prim_parts.append(f"доп.значение: {harakteristika}")
            else:
                prim_parts.append(f"материал: {harakteristika}")
        prim_parts.extend(extra)
        # используем номер строки листа (r), а не "№ п/п" из файла — эта
        # колонка бывает не заполнена (напр. лист 2020), а r всегда уникален
        tag = f"[импорт xls: {year}/стр.{r + 1}]"
        prim_parts.append(tag)

        records.append(dict(
            lesnichestvo=lesnichestvo,
            kvartal=clean_text(kvartal_raw),
            vydel=vydel,
            ploshad=ploshad,
            kategoriya_ploshadi=None,
            tlu=tlu,
            god_sozdaniya=year,
            metod_sozdaniya=metod,
            glavnaya_poroda=poroda,
            sostav_formula=sostav,
            gustota_posadki=gustota,
            normativ_perevoda=None,
            primechaniya="; ".join(prim_parts),
            _tag=tag,
        ))
    return records


# --------------------------------------------------------------------------- #
#  Импорт в БД
# --------------------------------------------------------------------------- #
def already_imported(conn, tag):
    row = conn.execute(
        "SELECT id FROM lesokultury_uchastok WHERE primechaniya LIKE ? LIMIT 1",
        (f"%{tag}%",),
    ).fetchone()
    return row is not None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xls", required=True, help="путь к файлу .xls")
    ap.add_argument("--years", default=",".join(ALL_YEARS),
                     help="список листов через запятую (по умолчанию 2017–2026)")
    ap.add_argument("--lesnichestvo", default="Болбасовское",
                     help="значение поля 'Лесничество' (по умолчанию 'Болбасовское')")
    ap.add_argument("--db", default=None,
                     help="путь к базе (по умолчанию берётся из config.DB_PATH / LESOVOD_DB_PATH)")
    ap.add_argument("--dry-run", action="store_true",
                     help="только показать, что будет импортировано, без записи в БД")
    args = ap.parse_args()

    db_path = args.db or legacy_config.DB_PATH
    years = [y.strip() for y in args.years.split(",") if y.strip()]

    wb = xlrd.open_workbook(args.xls, formatting_info=False)

    all_records = []
    for year_name in years:
        try:
            recs = parse_sheet(wb, year_name, args.lesnichestvo)
        except Exception as e:
            print(f"!! Лист '{year_name}': ошибка разбора — {e}")
            continue
        print(f"Лист {year_name}: найдено {len(recs)} записей")
        all_records.extend(recs)

    print(f"\nВсего к обработке: {len(all_records)} записей")
    print(f"База: {db_path}")

    if args.dry_run:
        print("\n--dry-run: запись в БД НЕ выполняется. Примеры первых 5 записей:")
        for rec in all_records[:5]:
            rec = dict(rec)
            rec.pop("_tag", None)
            print(" ", rec)
        return

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    created, skipped = 0, 0
    for rec in all_records:
        tag = rec.pop("_tag")
        if already_imported(conn, tag):
            skipped += 1
            continue
        legacy_db.create_lesokultury_uchastok(conn, **rec)
        created += 1

    conn.close()
    print(f"\nГотово: создано {created}, пропущено (уже импортированы) {skipped}")


if __name__ == "__main__":
    main()
