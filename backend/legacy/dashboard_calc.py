# -*- coding: utf-8 -*-
"""Qt-свободная копия расчётов карточки "Погода в лесу" для дашборда
(TODO п.1.6, Блок 5 PLAN_DORABOTKI): перевод направления ветра в текст и
оценка класса пожарной опасности по температуре/влажности.

Источник — screens/dashboard/helpers.py в десктопном проекте
(_wind_direction_to_text/_compute_fire_danger). Тот файл сам по себе давно
не тянет PySide6 (см. его докстринг — тоже вычищен в рамках этого же
пункта TODO), но живёт в отдельном дереве десктоп-приложения, которое не
поставляется вместе с backend. Здесь — построчная копия той же логики,
без каких-либо внешних зависимостей, чтобы app/routers/dashboard.py мог
импортировать её напрямую, без хрупкого try/except ImportError на
недоступный в окружении сервера модуль (см. правки в dashboard.py)."""


_WIND_DIR_NAMES = (
    "С", "ССВ", "СВ", "ВСВ", "В", "ВЮВ", "ЮВ", "ЮЮВ",
    "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ", "З", "ЗСЗ", "СЗ", "ССЗ",
)


def _wind_direction_to_text(degrees):
    """Градусы направления ветра (0-360) -> короткое русское сокращение
    ("СЗ", "ЮВ" и т.п.). None, если данных нет или они некорректны."""
    if degrees is None:
        return None
    try:
        deg = float(degrees) % 360
    except (TypeError, ValueError):
        return None
    idx = int((deg + 11.25) // 22.5) % len(_WIND_DIR_NAMES)
    return _WIND_DIR_NAMES[idx]


def _compute_fire_danger(temperature, humidity):
    """Оценивает класс пожарной опасности (1-5) по температуре (°C) и
    относительной влажности (%) — та же упрощённая эвристика, что и в
    десктопной версии (см. docstring оригинала в
    screens/dashboard/helpers.py)."""
    if temperature is None or humidity is None:
        return 1, "Малая пожароопасность"
    try:
        t = float(temperature)
        h = float(humidity)
    except (TypeError, ValueError):
        return 1, "Малая пожароопасность"

    if t > 30 and h < 30:
        return 5, "Чрезвычайная пожароопасность"
    if t > 25 and h < 40:
        return 4, "Высокая пожароопасность"
    if t > 20 and h < 50:
        return 3, "Средняя пожароопасность"
    if t >= 15 and h < 70:
        return 2, "Небольшая пожароопасность"
    return 1, "Малая пожароопасность"
