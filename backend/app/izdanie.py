# -*- coding: utf-8 -*-
"""«Издание» сервера — для какой организации запущена эта копия Лесовода.

Просьба Влада 04.11.2026: первый клиент — лесопункт (только заготовка:
без документов на делянки, акта, QGIS, лесокультур). Решили не делать
общую базу на всех (мультитенантность), а запускать отдельную копию
сервера со своей базой на клиента. Код один, издание задаётся в .env:

    LESOVOD_IZDANIE=lesopunkt          (по умолчанию lesnichestvo)
    LESOVOD_ORG_NAZVANIE=ЛП «Дубровка» (необязательно — подпись в шапке)

Название по-русски удобнее положить в APP_DIR/organizaciya.txt (UTF-8,
одна строка): cmd.exe читает .env в своей кодировке и ломает кириллицу.

Что делает издание:
- GET /api/izdanie (без входа) — сайт и телефон строят по нему меню:
  какие экраны спрятать, какие профессии в «Отчёте за смену»;
- закрывает API разделов, которых у издания нет (403), чтобы спрятанный
  экран нельзя было открыть по старой ссылке;
- у лесопункта сервер не прогревает при старте слой выделов (≈55 МБ) —
  копия на том же ПК почти не ест память, пока ей не пользуются.

Лесничество (издание по умолчанию) работает ровно как раньше.
"""
import os

LESNICHESTVO = "lesnichestvo"
LESOPUNKT = "lesopunkt"

IZDANIYA = {
    LESNICHESTVO: {
        "nazvanie": "Лесничество",
        # ключи экранов сайта (App.jsx READY_SCREENS), которых нет в меню
        "skryt_ekrany": [],
        # префиксы API, закрытые для этого издания
        "zakryt_api": [],
        # профессии «Отчёта за смену» (None — как в smena.VIDY_PROFESSII)
        "professii": None,
    },
    LESOPUNKT: {
        "nazvanie": "Лесопункт",
        "skryt_ekrany": [
            # документооборот лесничества по делянке
            "inspection", "documents", "raspredelenie",
            # лес: таксация, лесокультуры, рубки ухода, ведомости
            "taxation", "forestry", "uhody", "tek_izm",
            # схема сайта описывает дорожки лесничества
            "skhema",
        ],
        "zakryt_api": [
            "/api/tekushchie-izmeneniya",
            "/api/taxation",
            "/api/lesokultury",
            "/api/uhody",
            "/api/uhody-igra",
            "/api/hvorost",
            "/api/map/qgis",
        ],
        # вальщик, тракторист на вывозке, харвестерщик
        "professii": {
            "valshik": {"title": "Вальщик", "vidy": ["rubka_gp", "remont", "drugoe"]},
            "traktorist": {"title": "Тракторист на вывозке", "vidy": ["trelevka", "remont"]},
            "harvester": {"title": "Харвестерщик", "vidy": ["harvester", "remont"]},
        },
    },
}


def tekushchee() -> str:
    """Код издания из LESOVOD_IZDANIE; неизвестное значение — лесничество
    (опечатка в .env не должна прятать экраны у живого клиента)."""
    kod = (os.environ.get("LESOVOD_IZDANIE") or "").strip().lower()
    return kod if kod in IZDANIYA else LESNICHESTVO


def _organizaciya():
    imya = (os.environ.get("LESOVOD_ORG_NAZVANIE") or "").strip()
    if imya:
        return imya
    try:
        import config as legacy_config
        with open(os.path.join(legacy_config.APP_DIR, "organizaciya.txt"), encoding="utf-8-sig") as f:
            return f.readline().strip() or None
    except (OSError, ImportError, UnicodeDecodeError):
        return None


def opisanie() -> dict:
    kod = tekushchee()
    iz = IZDANIYA[kod]
    return {
        "izdanie": kod,
        "nazvanie": iz["nazvanie"],
        "organizaciya": _organizaciya(),
        "skryt_ekrany": list(iz["skryt_ekrany"]),
        "professii": iz["professii"],
    }


def api_zakryt(path: str) -> bool:
    """Путь запроса относится к разделу, которого нет у издания?"""
    for p in IZDANIYA[tekushchee()]["zakryt_api"]:
        if path == p or path.startswith(p + "/"):
            return True
    return False


def lesnichestvo() -> bool:
    return tekushchee() == LESNICHESTVO
