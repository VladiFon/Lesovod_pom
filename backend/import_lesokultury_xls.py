# -*- coding: utf-8 -*-
"""
Загрузка книги производства лесных культур (.xls/.xlsx, по листу на год) в
«Лесные культуры» из командной строки.

То же самое делает кнопка «Загрузить книгу л/к» на сайте (раздел «Лесные
культуры»): разбор и сверка с базой живут в app/lesokultury_kniga.py, этот
скрипт только вызывает их. Удобно, если сайт недоступен.

Использование (из папки backend/):
    python import_lesokultury_xls.py --xls "Болбасовское.xls" --lesnichestvo Болбасовское --dry-run
    python import_lesokultury_xls.py --xls "Болбасовское.xls" --lesnichestvo Болбасовское

По умолчанию берутся годы 2017–2026. База — та же, что у сервера
(LESOVOD_DB_PATH, см. legacy/config.py). Повторный запуск дублей не создаёт:
каждый участок помнит лист и строку книги (поле «Источник»), а участки,
загруженные прежней версией этого скрипта, узнаются по метке
«[импорт xls: …]» в примечаниях.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import get_connection, init_db  # noqa: E402
from app import lesokultury_kniga  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Загрузка книги л/к в «Лесные культуры»")
    ap.add_argument("--xls", required=True, help="файл книги (.xls или .xlsx)")
    ap.add_argument("--lesnichestvo", help="лесничество (по умолчанию — имя файла)")
    ap.add_argument("--god-from", type=int, default=2017)
    ap.add_argument("--god-to", type=int, default=2026)
    ap.add_argument("--dry-run", action="store_true", help="только показать, в базу не писать")
    args = ap.parse_args()

    path = Path(args.xls)
    lesnichestvo = (args.lesnichestvo or path.stem).strip()
    init_db()
    conn = get_connection()
    try:
        sheets = lesokultury_kniga.open_book(path.read_bytes(), path.name)
        rows = lesokultury_kniga.parse_book(sheets, args.god_from, args.god_to)
        plan = lesokultury_kniga.plan_import(conn, rows, lesnichestvo)
    except lesokultury_kniga.KnigaError as exc:
        sys.exit(str(exc))

    s = plan["summary"]
    print(f"Лесничество: {lesnichestvo}, годы {args.god_from}–{args.god_to}")
    print(f"Участков в книге: {s['vsego']} ({s['ploshad']} га): новых {s['novyh']}, "
          f"уже в базе {s['est_v_baze']}, с замечаниями {s['s_problemami']}")
    for r in plan["rows"]:
        if r["problemy"]:
            print(f"  лист {r['list']}, стр. {r['stroka']}: кв. {r['kvartal']} выд. {r['vydel']} — "
                  + "; ".join(r["problemy"]))
    if args.dry_run:
        print("Пробный запуск: в базу ничего не записано.")
        return
    result = lesokultury_kniga.apply_import(conn, plan, lesnichestvo)
    conn.commit()
    print(f"Создано участков: {result['sozdano']}, дополнено: {result['obnovleno']}, "
          f"записей в журнал: {result['zapisey_v_zhurnal']}, пропущено: {result['propushcheno']}")


if __name__ == "__main__":
    main()
