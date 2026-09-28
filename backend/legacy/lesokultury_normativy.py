# -*- coding: utf-8 -*-
"""Норматив количества экземпляров и средней высоты деревьев главных
пород для чистых лесных культур на участках, подлежащих переводу в
покрытые лесом земли — приложение 18 к Положению о порядке
лесовосстановления и лесоразведения (постановление Минлесхоза
от 19.12.2016 N 80, в редакции от 24.03.2022 N 5, таблица не менялась
постановлением от 10.01.2024 N 14).

Используется как справочная таблица (единственный источник истины) для
проверки решения "перевести в покрытые лесом земли" — см.
check_normativ_perevoda() ниже. lesokultury_uchastok.normativ_perevoda
(старое свободное поле) остаётся как вспомогательная, вручную введённая
аннотация — эта таблица его не заменяет технически (поле никуда не
делось), но именно эта таблица считается достоверной при автоматической
проверке.

ВАЖНО про единицы измерения: kolichestvo_tys_ga в этой таблице — ТЫСЯЧИ
штук на гектар, как в оригинале приложения 18. Мобильная полевая
карточка (app/routers/lesokultury.py:FieldCardBase.kolichestvo_na_ga)
собирает количество в ШТУКАХ на гектар — перед сравнением с этой
таблицей значение нужно делить на 1000 (см. docstring
check_normativ_perevoda)."""

NORMATIVY_PEREVODA = [
    {
        "poroda_kod": "берез",
        "poroda_polnaya": "Береза повислая",
        "tipy_lesa": [
            {"tip_lesa": None, "kolichestvo_tys_ga": 3.0, "vysota_m": 1.6},
        ],
    },
    {
        "poroda_kod": "дуб",
        "poroda_polnaya": "Дуб черешчатый",
        "tipy_lesa": [
            {"tip_lesa": None, "kolichestvo_tys_ga": 3.0, "vysota_m": 0.9},
        ],
    },
    {
        "poroda_kod": "ель",
        "poroda_polnaya": "Ель европейская",
        "tipy_lesa": [
            {"tip_lesa": "Ельники брусничные, мшистые", "kolichestvo_tys_ga": 3.0, "vysota_m": 0.9},
            {"tip_lesa": "Ельники орляковые, папоротниковые, черничные, долгомошные и приручейно-травяные",
             "kolichestvo_tys_ga": 2.5, "vysota_m": 1.0},
            {"tip_lesa": "Ельники кисличные, снытевые, крапивные", "kolichestvo_tys_ga": 2.5, "vysota_m": 1.1},
        ],
    },
    {
        "poroda_kod": "клен",
        "poroda_polnaya": "Клен остролистный",
        "tipy_lesa": [
            {"tip_lesa": None, "kolichestvo_tys_ga": 3.0, "vysota_m": 1.6},
        ],
    },
    {
        "poroda_kod": "листвен",
        "poroda_polnaya": "Лиственница европейская",
        "tipy_lesa": [
            {"tip_lesa": None, "kolichestvo_tys_ga": 2.4, "vysota_m": 2.3},
        ],
    },
    {
        "poroda_kod": "лип",
        "poroda_polnaya": "Липа мелколистная",
        "tipy_lesa": [
            {"tip_lesa": None, "kolichestvo_tys_ga": 3.0, "vysota_m": 1.6},
        ],
    },
    {
        "poroda_kod": "ольх",
        "poroda_polnaya": "Ольха черная",
        "tipy_lesa": [
            {"tip_lesa": None, "kolichestvo_tys_ga": 2.0, "vysota_m": 3.0},
        ],
    },
    {
        "poroda_kod": "сосн",
        "poroda_polnaya": "Сосна обыкновенная",
        "tipy_lesa": [
            {"tip_lesa": "Сосняки лишайниковые", "kolichestvo_tys_ga": 3.3, "vysota_m": 0.9},
            {"tip_lesa": "Сосняки вересковые, брусничные, мшистые, долгомошные и багульниковые",
             "kolichestvo_tys_ga": 2.6, "vysota_m": 1.1},
            {"tip_lesa": "Сосняки черничные", "kolichestvo_tys_ga": 3.0, "vysota_m": 1.3},
            {"tip_lesa": "Сосняки орляковые и кисличные", "kolichestvo_tys_ga": 3.0, "vysota_m": 1.5},
        ],
    },
    {
        "poroda_kod": "ясен",
        "poroda_polnaya": "Ясень обыкновенный",
        "tipy_lesa": [
            {"tip_lesa": None, "kolichestvo_tys_ga": 3.0, "vysota_m": 1.6},
        ],
    },
]


def find_poroda(glavnaya_poroda):
    """Находит строку таблицы по свободному тексту главной породы участка
    (сравнение по вхождению podstroki, регистронезависимо — 'Сосна',
    'Сосна обыкновенная', 'сосна обыкн.' все находят строку 'сосн').
    Возвращает None, если порода не входит в приложение 18 (например,
    мягколиственные породы вроде осины/ивы там не нормируются)."""
    if not glavnaya_poroda:
        return None
    text = glavnaya_poroda.strip().lower()
    for row in NORMATIVY_PEREVODA:
        if row["poroda_kod"] in text:
            return row
    return None


def get_tipy_lesa_options(glavnaya_poroda):
    """Список вариантов "тип леса" для выпадающего списка на форме участка,
    в зависимости от главной породы — [] если порода не найдена в таблице
    или у неё только один (безусловный) норматив (tip_lesa=None везде)."""
    row = find_poroda(glavnaya_poroda)
    if row is None:
        return []
    options = [t["tip_lesa"] for t in row["tipy_lesa"] if t["tip_lesa"]]
    return options


def check_normativ_perevoda(glavnaya_poroda, tip_lesa, kolichestvo_tys_na_ga, srednyaya_vysota_m):
    """Сверяет фактические данные инвентаризации с официальным нормативом
    (приложение 18). Только предупреждение/подсказка — решение о переводе
    остаётся за комиссией, эта функция ничего не блокирует.

    kolichestvo_tys_na_ga — В ТЫСЯЧАХ штук на гектар (не в штуках — см.
    докстринг модуля про единицы измерения, вызывающий код обязан
    привести значение сам).

    Возвращает:
      {"naideno": bool,               # порода вообще есть в приложении 18
       "poroda_polnaya": str | None,
       "trebuetsya_vybor_tipa_lesa": bool,  # у породы несколько нормативов
                                             # (сосна/ель) и tip_lesa не передан/не найден
       "trebuemoe_kolichestvo_tys_ga": float | None,
       "trebuemaya_vysota_m": float | None,
       "sootvetstvuet_kolichestvo": bool | None,
       "sootvetstvuet_vysota": bool | None,
       "sootvetstvuet": bool | None,   # оба условия одновременно
       "predupredzhenie": str | None}
    """
    row = find_poroda(glavnaya_poroda)
    if row is None:
        return {
            "naideno": False, "poroda_polnaya": None,
            "trebuetsya_vybor_tipa_lesa": False,
            "trebuemoe_kolichestvo_tys_ga": None, "trebuemaya_vysota_m": None,
            "sootvetstvuet_kolichestvo": None, "sootvetstvuet_vysota": None,
            "sootvetstvuet": None,
            "predupredzhenie": (
                f"Порода «{glavnaya_poroda}» не входит в норматив приложения 18 — "
                "автоматическая проверка недоступна, решение принимается комиссией."
            ),
        }

    tipy = row["tipy_lesa"]
    if len(tipy) == 1:
        norma = tipy[0]
        trebuetsya_vybor = False
    else:
        norma = next((t for t in tipy if t["tip_lesa"] == tip_lesa), None)
        if norma is None:
            return {
                "naideno": True, "poroda_polnaya": row["poroda_polnaya"],
                "trebuetsya_vybor_tipa_lesa": True,
                "trebuemoe_kolichestvo_tys_ga": None, "trebuemaya_vysota_m": None,
                "sootvetstvuet_kolichestvo": None, "sootvetstvuet_vysota": None,
                "sootvetstvuet": None,
                "predupredzhenie": (
                    f"Для «{row['poroda_polnaya']}» норматив зависит от типа леса — "
                    "укажите тип леса участка, чтобы проверить соответствие."
                ),
            }
        trebuetsya_vybor = False

    sootvetstvuet_kolichestvo = (
        kolichestvo_tys_na_ga is not None and kolichestvo_tys_na_ga >= norma["kolichestvo_tys_ga"]
    )
    sootvetstvuet_vysota = (
        srednyaya_vysota_m is not None and srednyaya_vysota_m >= norma["vysota_m"]
    )
    both_known = kolichestvo_tys_na_ga is not None and srednyaya_vysota_m is not None
    sootvetstvuet = (sootvetstvuet_kolichestvo and sootvetstvuet_vysota) if both_known else None

    predupredzhenie = None
    if both_known and not sootvetstvuet:
        parts = []
        if not sootvetstvuet_kolichestvo:
            parts.append(f"количество ({kolichestvo_tys_na_ga:g} тыс.шт/га) ниже норматива ({norma['kolichestvo_tys_ga']:g})")
        if not sootvetstvuet_vysota:
            parts.append(f"средняя высота ({srednyaya_vysota_m:g} м) ниже норматива ({norma['vysota_m']:g} м)")
        predupredzhenie = "Не соответствует нормативу перевода: " + "; ".join(parts) + "."

    return {
        "naideno": True, "poroda_polnaya": row["poroda_polnaya"],
        "trebuetsya_vybor_tipa_lesa": trebuetsya_vybor,
        "trebuemoe_kolichestvo_tys_ga": norma["kolichestvo_tys_ga"],
        "trebuemaya_vysota_m": norma["vysota_m"],
        "sootvetstvuet_kolichestvo": sootvetstvuet_kolichestvo,
        "sootvetstvuet_vysota": sootvetstvuet_vysota,
        "sootvetstvuet": sootvetstvuet,
        "predupredzhenie": predupredzhenie,
    }
