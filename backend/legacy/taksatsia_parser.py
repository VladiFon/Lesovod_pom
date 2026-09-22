#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
taksatsia_parser.py — гибридный парсер таксационных описаний (DOS-выгрузка -> Word).

КЛЮЧЕВАЯ ИДЕЯ (проверено на всём файле):
    Таблица в исходнике — не "плавающий" текст, а печать с ФИКСИРОВАННОЙ шириной колонок
    (72 символа на строку). Пустые поля (например, отсутствующая группа возраста)
    остаются пустыми НА СВОЁМ МЕСТЕ, а не сдвигают соседние колонки.
    => парсим срезами по символам (см. COLS), а не split()'ом.
    Единственное исключение — колонка "Ярус": обычные значения (1..9) стоят в [6:8],
    но двузначные спецкоды (13) начинаются на 1 символ левее, поэтому берём окно [5:8].

Каждый выдел описывается ДВУМЯ физическими строками (A и B) + произвольным числом
дополнительных строк (порода №3+, ярусы 4/6/9/13, свободный текст: Подлесок, ПТГ-NN,
Целевая порода, Повреждение, Культуры, Выполнено, Рекреац.харак-ка и т.д.)

Философия: "человек в цикле". Парсер не пытается угадать на 100% — там, где уверенности
нет, пишет предположение + флаг для ручной проверки в колонке "флаг_проверки", плюс
исходные сырые строки в "сырая_строка_A"/"сырая_строка_B", чтобы можно было свериться
с оригиналом одним взглядом.
"""

from __future__ import annotations
import re
import sys
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

try:
    import docx
except ImportError:
    print("Нужен python-docx: pip install python-docx --break-system-packages", file=sys.stderr)
    raise

# ---------------------------------------------------------------------------
# 1. Фиксированная сетка колонок (символьные срезы), выверено по шапке таблицы
#    'Выд. :Яр:Сос- :Воз:H,:Д,:Кл: Тип :Бон: G:З/га: по :Т:Сух:Зах: Хозрас-'
#    'Площ :  :тав  :раст м:см:Гр: ТЛУ :Пол:  :З/вд:пор.: :Ед.:о/л:поряжения'
# ---------------------------------------------------------------------------
COLS = {
    'num':    (0, 5),    # Выдел№ (строка A) / Площадь, га (строка B)
    'yarus':  (5, 8),    # Ярус (окно расширено на 1 символ влево под двузначные спецкоды "13")
    'sostav': (9, 14),   # Состав: доля+порода (A: 1-я порода; B: 2-я; доп.строки: 3-я+)
    'vozr':   (15, 18),  # Возраст, лет
    'h':      (19, 21),  # H, м
    'd':      (22, 24),  # Д, см
    'kl':     (25, 27),  # Класс возраста (A, 'Кл') / Группа возраста (B, 'Гр') -- два значения друг под другом
    'tip':    (28, 33),  # Тип леса, буквенный код (A, напр. КИС) / ТЛУ-эдафотоп (B, напр. Д2)
    'bon':    (34, 37),  # Бонитет (A) / Полнота (B, либо % приживаемости у несомкн. культур)
    'g':      (38, 40),  # G — сумма площадей сечений
    'zga':    (41, 45),  # Запас на га (A) / Запас на выделе, суммарно (B)
    'po':     (46, 50),  # "по" — доп. значение (текущий прирост/др.)
    't':      (51, 52),  # Т (товарность/текущий прирост, см. письмо пользователя)
    'suh':    (53, 56),  # Сухостой
    'zah':    (57, 60),  # Захламлённость
    'hoz':    (61, 72),  # Начало текста хозраспоряжений (редко занято на самой строке A/B)
}
ROW_WIDTH = 72

# объединённый список: ответ пользователя + справочник "Расшифровка" (Болбасовское л-во).
# Это МЯГКАЯ проверка (soft warning) — не входящий в список код не отбрасывается, просто помечается флагом.
# объединённый список: ответ пользователя + справочник "Расшифровка" (Болбасовское л-во).
# Это МЯГКАЯ проверка (soft warning) — не входящий в список код не отбрасывается, просто помечается флагом.
_FOREST_TYPES_BASE = {
    'КИС', 'МШ', 'ЧЕР', 'ВР', 'ВЕР', 'ОР', 'ПАП', 'СН', 'ДОЛ', 'ОС', 'ОС.СФ',
    'БАГ', 'ЗЛ', 'ПР', 'КР', 'СНТ', 'ЛОБ', 'ДМ', 'ПО', 'ЛШ', 'БР', 'ПР.ТР',
    'СФ', 'ЛУГ', 'ПР.ПМ', 'ТАВ', 'Б.Р', 'ОС.ТР', 'БОЛ.П', 'ПШ.СФ', 'КАС', 'ИВ', 'ЗМ',
}
# в исходнике встречается и точка, и дефис как разделитель составных кодов (ОС.СФ / ОС-СФ) — учитываем оба
FOREST_TYPES = set(_FOREST_TYPES_BASE)
for _t in _FOREST_TYPES_BASE:
    if '.' in _t:
        FOREST_TYPES.add(_t.replace('.', '-'))

EDAPHOTOPE_RE = re.compile(r'^[АВСД]\d$')

NONFOREST_CATEGORIES = [
    'Просеки квартальные', 'Дорога', 'Болото', 'Пашня', 'Усадьба',
    'ЛЭП', 'Канал', 'Трасса', 'Прочие трассы', 'Водоем', 'Пастбище', 'Пески',
    'Иные земли', 'Неиспользуемые земли', 'Река', 'Ручей', 'Пруд',
    'Овраг', 'Поляна ландшафтная', 'Кормовое поле', 'Газопровод',
]

PENDING_LABELS = {
    'Лесные культуpы', 'Лесные культуры',
    'Несомкнувшиеся лесные культуpы', 'Несомкнувшиеся лесные культуры',
    'Насажд.с культурами, перешедшими под полог',
    'Насажд.с несомкн.л/к, создан.при реконстр.',
    'Погибшее насаждение',
    'Прогалина',
}

# известная проблема DOS-шрифтов: латинские гомоглифы вместо кириллицы
HOMOGLYPHS = str.maketrans({
    'K': 'К', 'H': 'Н', 'C': 'С', 'P': 'Р', 'O': 'О', 'A': 'А', 'E': 'Е', 'M': 'М', 'T': 'Т', 'X': 'Х',
    'k': 'к', 'h': 'н', 'c': 'с', 'p': 'р', 'o': 'о', 'a': 'а', 'e': 'е', 'm': 'м', 't': 'т', 'x': 'х',
})

RE_DIVIDER = re.compile(r'^-{10,}$')
RE_EQUALS = re.compile(r'^={10,}$')
RE_KVARTAL = re.compile(r'квартал\s+(\d+)', re.IGNORECASE)
RE_CATEGORY = re.compile(r'^\s*Категория лесов:\s*(.+?)\s*$')
RE_SUBCATEGORY = re.compile(r'^\s*Подкатегория лесов:\s*(.+?)\s*$')
RE_VYRUBKA = re.compile(r'^Вырубка\s+\d{4}\s+года.*пней на га')
RE_NONFOREST = re.compile(
    r'^\s{0,4}(\d{1,3})\s+(' + '|'.join(re.escape(c) for c in NONFOREST_CATEGORIES) + r')\s*$'
)
RE_INT_ONLY = re.compile(r'^\d{1,3}$')
RE_DECIMAL = re.compile(r'^\d{1,3}[.,]\d$')

FREE_TEXT_PREFIXES = (
    'Подлесок:', 'Подpост:', 'Подрост:', 'ПТГ-', 'Целевая порода',
    'Повpеждение:', 'Повреждение:', 'Культуpы:', 'Культуры:', 'Выполнено:',
    'Рекpеац.хаpак-ка:', 'Рекреац.харак-ка:', 'Одновременно относится к:',
    'Запрещены', 'запр.', 'Запр.', 'принято в лесхоз', 'Врем.изб.увл.почвы',
    'ОРЛ:', 'класс сан.оценки', '2-й класс', '3-й класс', 'шиpина', 'ширина',
    'низинное', 'верховое', 'переходное',
)


def sl(line: str, key: str) -> str:
    """Символьный срез фиксированной колонки (безопасно для коротких строк)."""
    a, b = COLS[key]
    if len(line) < b:
        return line[a:] if len(line) > a else ''
    return line[a:b]


def parse_num(s: str):
    """'23' -> 23 ; '0,7' -> 0.7 ; '-' -> 0.0 (явный ноль) ; '' -> None (не измерялось)."""
    s = s.strip()
    if not s:
        return None
    if s == '-':
        return 0.0
    s = s.replace(',', '.')
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None  # аномалия — не число там, где ожидали число


def get_yarus(line: str) -> Optional[int]:
    """Ярус: обычно [6:8] (1 цифра), но двузначные спецкоды (13) съезжают в [5:8]."""
    window = line[5:8] if len(line) >= 8 else line[5:]
    window = window.strip()
    if not window:
        return None
    m = re.match(r'^(\d{1,2})', window)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# 2. Извлечение текста docx
# ---------------------------------------------------------------------------
def extract_lines(path: str) -> list[str]:
    doc = docx.Document(path)
    return [p.text for p in doc.paragraphs]


# ---------------------------------------------------------------------------
# 3. Модель записи (выдел / нелесной объект)
# ---------------------------------------------------------------------------
@dataclass
class Record:
    лесхоз: Optional[str] = None
    лесничество: Optional[str] = None
    квартал: Optional[str] = None
    категория_лесов: Optional[str] = None
    подкатегория_лесов: Optional[str] = None
    выдел: Optional[int] = None
    тип_объекта: str = 'Лес'
    площадь_га: Optional[float] = None
    ярус: Optional[int] = None
    состав: str = ''
    возраст_лет: Optional[int] = None
    высота_м: Optional[float] = None
    диаметр_см: Optional[float] = None
    класс_возраста: Optional[float] = None
    группа_возраста: Optional[float] = None
    тип_леса: Optional[str] = None
    тлу_эдафотоп: Optional[str] = None
    тип_тлу: Optional[str] = None
    бонитет: Optional[str] = None
    полнота: Optional[float] = None
    приживаемость_pct: Optional[float] = None
    g_a: Optional[float] = None
    g_b: Optional[float] = None
    запас_на_га: Optional[float] = None
    запас_на_выделе: Optional[float] = None
    по_a: Optional[float] = None
    т_a: Optional[float] = None
    сух_a: Optional[float] = None
    зах_a: Optional[float] = None
    по_b: Optional[float] = None
    т_b: Optional[float] = None
    сух_b: Optional[float] = None
    зах_b: Optional[float] = None
    доп_ярусы: list = field(default_factory=list)   # подрост/сухостой (яр 6/9/13) как отдельные строки
    доп_породы: list = field(default_factory=list)  # 3-я+ порода состава
    заметки: list = field(default_factory=list)      # свободный текст (Подлесок, ПТГ, Культуры, ...)
    сырая_строка_A: str = ''
    сырая_строка_B: str = ''
    флаг_проверки: str = ''

    def flag(self, msg: str):
        self.флаг_проверки = (self.флаг_проверки + '; ' if self.флаг_проверки else '') + msg


# ---------------------------------------------------------------------------
# 4. Основной парсер
# ---------------------------------------------------------------------------
def parse(lines: list[str]) -> list[Record]:
    records: list[Record] = []
    cur: Optional[Record] = None

    leshoz = None
    lesnichestvo = None
    kvartal = None
    category = None
    subcategory = None
    pending_label = None
    skip_block = False  # внутри "Итого ..." / "Запас сырорастущего леса" — глотаем агрегаты

    def flush():
        nonlocal cur
        if cur is not None:
            # склеиваем состав из главной + доп. пород
            parts = [cur.состав] if cur.состав else []
            parts += cur.доп_породы
            cur.состав = ''.join(p.strip() for p in parts if p.strip())
            if cur.тип_объекта == 'Лес' and not cur.состав:
                # подстраховка: скорее всего это нераспознанная нелесная категория земель
                cur.flag("Пустой состав у типа 'Лес' — похоже на неизвестную категорию нелесных земель")
            records.append(cur)
        cur = None

    for raw in lines:
        if raw is None:
            continue
        line = raw.translate(HOMOGLYPHS)
        stripped = line.strip()
        if not stripped:
            continue

        # --- служебные строки, не относящиеся к данным ---
        if RE_DIVIDER.match(stripped):
            continue
        if 'ТАКСАЦИОННОЕ ОПИСАНИЕ' in stripped or 'Т А К С А Ц И О Н Н О Е' in stripped:
            continue
        if 'лесхоз' in stripped.lower() and 'лесничество' in stripped.lower():
            m = re.match(r'^(.+?лесхоз)\s+(.+?лесничество)', stripped)
            if m:
                leshoz, lesnichestvo = m.group(1).strip(), m.group(2).strip()
            continue
        mk = RE_KVARTAL.search(stripped)
        if mk and 'квартал' == stripped.split()[0].lower() or (mk and len(stripped) < 60 and 'лесхоз' not in stripped.lower()):
            kvartal = mk.group(1)
            continue
        if RE_EQUALS.match(stripped):
            continue
        if stripped.startswith('Выд.') and ':' in stripped:
            continue
        if stripped.startswith('Площ') and ':' in stripped and 'тав' in stripped:
            continue

        mc = RE_CATEGORY.match(line)
        if mc:
            flush()
            category = mc.group(1)
            subcategory = None
            continue
        ms = RE_SUBCATEGORY.match(line)
        if ms:
            subcategory = ms.group(1)
            continue

        if 'Итого по кварталу' in stripped or 'Итого по категории лесов' in stripped or \
           'Запас сырорастущего леса' in stripped:
            flush()
            skip_block = True
            continue
        if skip_block:
            # агрегатные строки после "Итого"/"Запас" — либо чисто числовые, либо "С 387,Е 333,..."
            if re.match(r'^[\d\s.,\-]+$', stripped) or re.match(r'^([А-ЯЁ]{1,4}\s*\d+,?\s*)+$', stripped):
                continue
            skip_block = False  # эта строка уже нормальные данные — обрабатываем ниже

        # --- лейблы-заголовки перед выделом ---
        if stripped in PENDING_LABELS or RE_VYRUBKA.match(stripped):
            flush()
            pending_label = stripped
            continue

        # --- нелесной объект (Дорога/Болото/...) — своя, "не по сетке" раскладка ---
        mnf = RE_NONFOREST.match(line)
        if mnf:
            flush()
            cur = Record(лесхоз=leshoz, лесничество=lesnichestvo, квартал=kvartal,
                         категория_лесов=category, подкатегория_лесов=subcategory,
                         выдел=int(mnf.group(1)), тип_объекта=mnf.group(2),
                         сырая_строка_A=raw)
            pending_label = None
            continue

        # --- строка A: начало нового обычного выдела (Выдел№ в колонке num) ---
        num_field = sl(line, 'num').strip()
        if RE_INT_ONLY.match(num_field):
            flush()
            cur = Record(лесхоз=leshoz, лесничество=lesnichestvo, квартал=kvartal,
                         категория_лесов=category, подкатегория_лесов=subcategory,
                         выдел=int(num_field),
                         тип_объекта=(pending_label if pending_label else 'Лес'),
                         сырая_строка_A=raw)
            pending_label = None
            cur.ярус = get_yarus(line)
            cur.состав = sl(line, 'sostav').strip()
            cur.возраст_лет = parse_num(sl(line, 'vozr'))
            cur.высота_м = parse_num(sl(line, 'h'))
            cur.диаметр_см = parse_num(sl(line, 'd'))
            cur.класс_возраста = parse_num(sl(line, 'kl'))
            tip = sl(line, 'tip').strip()
            cur.тип_леса = tip or None
            if tip and tip not in FOREST_TYPES:
                cur.flag(f"Неизвестный код типа леса: '{tip}'")
            cur.бонитет = sl(line, 'bon').strip() or None
            cur.g_a = parse_num(sl(line, 'g'))
            cur.запас_на_га = parse_num(sl(line, 'zga'))
            cur.по_a = parse_num(sl(line, 'po'))
            cur.т_a = parse_num(sl(line, 't'))
            cur.сух_a = parse_num(sl(line, 'suh'))
            cur.зах_a = parse_num(sl(line, 'zah'))
            if cur.ярус == 4 and cur.возраст_лет and cur.возраст_лет > 15:
                cur.flag("Ярус=4 (несомкн.культуры), но возраст>15 — проверить")
            continue

        # --- строка B: продолжение (Площадь, 2-я порода, ТЛУ, Полнота, Запас/выд) ---
        num_field_b = sl(line, 'num').strip()
        yarus_here = get_yarus(line)
        if RE_DECIMAL.match(num_field_b) and yarus_here is None and cur is not None:
            cur.сырая_строка_B = raw
            cur.площадь_га = parse_num(num_field_b)
            sost2 = sl(line, 'sostav').strip()
            if sost2:
                cur.доп_породы.append(sost2)
            # если у второй породы указаны собственные возр/H/Д — сохраняем в заметки (бонус)
            v2, h2, d2 = parse_num(sl(line, 'vozr')), parse_num(sl(line, 'h')), parse_num(sl(line, 'd'))
            if v2 or h2 or d2:
                cur.заметки.append(f"[{sost2}] возр={v2} H={h2} Д={d2}")
            cur.группа_возраста = parse_num(sl(line, 'kl'))
            tlu = sl(line, 'tip').strip()
            cur.тлу_эдафотоп = tlu or None
            if tlu and not EDAPHOTOPE_RE.match(tlu):
                cur.flag(f"ТЛУ '{tlu}' не похож на эдафотоп (буква+цифра)")
            bon_field = sl(line, 'bon').strip()
            if cur.ярус == 4:
                # у несомкнувшихся культур в слоте "Полнота" стоит % приживаемости (см. письмо)
                cur.приживаемость_pct = parse_num(bon_field)
                cur.полнота = None
            else:
                cur.полнота = parse_num(bon_field)
                cur.запас_на_выделе = parse_num(sl(line, 'zga'))
            cur.g_b = parse_num(sl(line, 'g'))
            if cur.ярус != 4:
                cur.по_b = parse_num(sl(line, 'po'))
                cur.т_b = parse_num(sl(line, 't'))
                cur.сух_b = parse_num(sl(line, 'suh'))
                cur.зах_b = parse_num(sl(line, 'zah'))
            if cur.тип_леса and cur.тлу_эдафотоп:
                cur.тип_тлу = f"{cur.тип_леса} {cur.тлу_эдафотоп}"
            elif cur.тип_леса or cur.тлу_эдафотоп:
                cur.тип_тлу = cur.тип_леса or cur.тлу_эдафотоп
            continue

        # --- доп. ярус (подрост/сухостой/сохранённый ярус: 6, 9, 13) внутри уже открытого выдела ---
        if not num_field_b and yarus_here is not None and cur is not None:
            sost = sl(line, 'sostav').strip()
            cur.доп_ярусы.append({
                'ярус': yarus_here,
                'состав': sost,
                'возраст': parse_num(sl(line, 'vozr')),
                'h': parse_num(sl(line, 'h')),
                'd': parse_num(sl(line, 'd')),
                'запас_га': parse_num(sl(line, 'zga')),
                'raw': raw,
            })
            continue

        # --- доп. порода (3-я и далее строка состава, без номера выдела и без яруса) ---
        sost_extra = sl(line, 'sostav').strip()
        if not num_field_b and yarus_here is None and sost_extra and cur is not None:
            cur.доп_породы.append(sost_extra)
            v3, h3, d3 = parse_num(sl(line, 'vozr')), parse_num(sl(line, 'h')), parse_num(sl(line, 'd'))
            if v3 or h3 or d3:
                cur.заметки.append(f"[{sost_extra}] возр={v3} H={h3} Д={d3}")
            continue

        # --- всё остальное — свободный текст (Подлесок, ПТГ-NN, Целевая порода, Повреждение, ...) ---
        if cur is not None:
            cur.заметки.append(stripped)
        # если cur is None — «осиротевшая» строка (маловероятно), молча пропускаем

    flush()
    return records


# ---------------------------------------------------------------------------
# 5. Экспорт
# ---------------------------------------------------------------------------
CORE_FIELDS = [
    'лесничество', 'квартал', 'категория_лесов', 'подкатегория_лесов',
    'выдел', 'тип_объекта', 'площадь_га',
    'состав', 'ярус', 'возраст_лет', 'высота_м', 'диаметр_см',
    'класс_возраста', 'группа_возраста', 'тип_леса', 'тлу_эдафотоп', 'тип_тлу',
    'бонитет', 'полнота', 'приживаемость_pct',
    'g_a', 'g_b', 'запас_на_га', 'запас_на_выделе',
    'по_a', 'т_a', 'сух_a', 'зах_a', 'по_b', 'т_b', 'сух_b', 'зах_b',
    'заметки', 'флаг_проверки', 'сырая_строка_A', 'сырая_строка_B',
]


def to_rows(records: list[Record]) -> list[dict]:
    out = []
    for r in records:
        d = {}
        for f in CORE_FIELDS:
            v = getattr(r, f)
            if f == 'заметки':
                v = ' | '.join(v)
            d[f] = v
        if r.доп_ярусы:
            d['доп_ярусы'] = ' | '.join(
                f"яр{x['ярус']}:{x['состав']}(возр{x['возраст']},H{x['h']},Д{x['d']},Зга{x['запас_га']})"
                for x in r.доп_ярусы
            )
        else:
            d['доп_ярусы'] = ''
        out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', help='путь к .docx с таксационным описанием')
    ap.add_argument('-o', '--out', default='taksatsia_output.csv', help='выходной CSV')
    args = ap.parse_args()

    lines = extract_lines(args.input)
    records = parse(lines)
    rows = to_rows(records)

    import csv
    fieldnames = CORE_FIELDS + ['доп_ярусы']
    with open(args.out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    n_flagged = sum(1 for r in records if r.флаг_проверки)
    print(f"Разобрано записей: {len(records)}; из них с флагом на проверку: {n_flagged}")
    print(f"Сохранено: {args.out}")


if __name__ == '__main__':
    main()