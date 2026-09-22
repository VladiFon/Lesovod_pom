# -*- coding: utf-8 -*-
"""
Парсер "Ведомости материальной оценки лесосеки" (МДО), выгружаемой из АРМ ЛП3
в формате .rtf.

Извлекает: лесхоз, лесничество, квартал, выдел, номер лесосеки, разряд такс,
год лесоустройства, площадь (общая/эксплуатационная), дату лесосеки,
категорию лесов, тип леса, состав насаждения (по МДО), полноту, возраст,
вид/способ рубки, состояние насаждения, и главное - "Итого ликвида" по
лесосеке (=вырубаемый запас, м3), которое нужно для акта обследования.

МДО - это .rtf со всей структурой внутри ОДНОЙ большой таблицы (первая
таблица документа). Конвертируем rtf -> docx через LibreOffice (soffice),
затем читаем таблицу через python-docx (сохраняет кириллицу корректно,
в отличие от прямой конвертации в .txt).
"""
import re
import shutil
import subprocess
import sys
import tempfile
import os
from pathlib import Path

from docx import Document

import config

# ВАЖНО: раньше CONFIG_PATH считался от os.path.dirname(__file__) — то есть
# писался рядом с самим mdo_parser.py. После сборки в .exe этот модуль
# физически лежит внутри папки приложения; если программа установлена в
# место без прав на запись (например, Program Files), сохранение пути к
# soffice.exe там падало бы с PermissionError. config.APP_DIR — это папка
# самого exe (или main.py при запуске из исходников), куда программа и так
# пишет lesovod.db и "Готовые_документы" — установщик специально ставит
# программу в %LOCALAPPDATA%\Programs\Lesovod, чтобы туда всегда можно было
# писать без прав администратора.
CONFIG_PATH = os.path.join(config.APP_DIR, "soffice_path.txt")


def get_configured_soffice_path():
    if os.path.exists(CONFIG_PATH):
        p = open(CONFIG_PATH, encoding="utf-8").read().strip()
        if p and os.path.exists(p):
            return p
    return None


def set_configured_soffice_path(path):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(path.strip())


def clear_configured_soffice_path():
    """Убирает вручную заданный путь к soffice (кнопка "Сбросить" в
    Настройках) — после этого снова используется автопоиск _find_soffice()."""
    if os.path.exists(CONFIG_PATH):
        os.remove(CONFIG_PATH)


def _registry_soffice_candidates():
    """Ищет soffice.exe через реестр Windows — обычный `Program Files`
    перебор (см. _find_soffice) промахивается мимо непривычных мест
    установки: LibreOffice, поставленный только для текущего пользователя
    (%LOCALAPPDATA%\\Programs\\LibreOffice — так ставит инсталлятор с
    флагом "только для меня"/при отсутствии прав администратора), диск не
    C:, или версия, для которой воображаемое имя папки "LibreOffice 7" не
    совпадает (в реальности ставится в "LibreOffice", без номера версии,
    начиная с 6.x). Реестр at LibreOffice сам прописывает свой путь
    установки — это самый надёжный источник, который не зависит от
    предположений о конкретном пути.

    Возвращает список путей-кандидатов (может быть пустым), ничего не
    бросает — на не-Windows или при любой ошибке чтения реестра просто
    возвращает []."""
    if not sys.platform.startswith("win"):
        return []
    try:
        import winreg
    except ImportError:
        return []

    candidates = []

    # 1) App Paths — то же самое место, которым пользуется "Открыть с
    #    помощью" в Проводнике; ключ создаётся почти любым инсталлятором
    #    LibreOffice (MSI и обычный exe) независимо от версии.
    app_paths_keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe"),
    ]
    for hive, subkey in app_paths_keys:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, None)  # (Default) = путь к exe
                if value:
                    candidates.append(value)
        except OSError:
            pass

    # 2) Собственный ключ LibreOffice с путём установки (UNO/Install/Path) —
    #    его пишет сам инсталлятор LibreOffice, версия зашита в имя подключа,
    #    поэтому перебираем все подключи вместо угадывания номера версии.
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for base in (r"SOFTWARE\LibreOffice\LibreOffice", r"SOFTWARE\WOW6432Node\LibreOffice\LibreOffice"):
            try:
                with winreg.OpenKey(hive, base) as parent_key:
                    i = 0
                    while True:
                        try:
                            version_subkey = winreg.EnumKey(parent_key, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            with winreg.OpenKey(parent_key, version_subkey + r"\UNO\InstallPath") as install_key:
                                install_path, _ = winreg.QueryValueEx(install_key, None)
                                if install_path:
                                    candidates.append(os.path.join(install_path, "program", "soffice.exe"))
                        except OSError:
                            pass
            except OSError:
                pass

    return candidates


def _find_soffice():
    """Ищет soffice, перебирая источники по надёжности убывания:
    1. вручную заданный путь (soffice_path.txt, см. Настройки → LibreOffice);
    2. портативная сборка, которую installer.iss кладёт рядом с exe;
    3. PATH;
    4. реестр Windows (см. _registry_soffice_candidates — покрывает и
       нестандартные места установки, и разные версии);
    5. типовые пути установки на Windows/macOS/Linux, включая пер-
       пользовательскую установку в %LOCALAPPDATA%\\Programs и любую папку
       вида "LibreOffice*" в Program Files (не только "LibreOffice"/
       "LibreOffice 7" — версии вроде "LibreOffice 24.8" не совпадали бы
       буквально ни с одним из старых двух вариантов)."""
    configured = get_configured_soffice_path()
    if configured:
        return configured

    # Портативная версия, которую installer.iss кладёт в
    # <APP_DIR>\LibreOfficePortable\ — так МДО читается "из коробки" без
    # отдельной установки LibreOffice пользователем. Точный путь внутри
    # распакованной LibreOfficePortable может отличаться на 1 подпапку в
    # зависимости от версии сборки PortableApps — проверьте после первой
    # сборки установщика и поправьте при необходимости.
    portable_candidate = os.path.join(
        config.APP_DIR, "LibreOfficePortable", "App", "libreoffice", "program", "soffice.exe"
    )
    if os.path.exists(portable_candidate):
        return portable_candidate

    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found

    for candidate in _registry_soffice_candidates():
        if candidate and os.path.exists(candidate):
            return candidate

    candidates = []
    if sys.platform.startswith("win"):
        program_dirs = []
        for envvar in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
            base = os.environ.get(envvar)
            if base:
                program_dirs.append(base)
        # Персональная установка (инсталлятор LibreOffice без прав
        # администратора ставит именно сюда) — реестр (см. выше) в этом
        # случае обычно тоже находит путь, но здесь — на случай, если
        # HKEY_CURRENT_USER по какой-то причине недоступен.
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            program_dirs.append(os.path.join(local_appdata, "Programs"))

        for base in program_dirs:
            # Имя папки версии зависит от инсталлятора ("LibreOffice",
            # "LibreOffice 7", "LibreOffice 24.8" и т.п.) — вместо того,
            # чтобы перечислять варианты вручную, ищем ЛЮБУЮ подпапку,
            # начинающуюся с "LibreOffice".
            try:
                for entry in os.listdir(base):
                    if entry.lower().startswith("libreoffice"):
                        candidates.append(os.path.join(base, entry, "program", "soffice.exe"))
            except OSError:
                pass
    elif sys.platform == "darwin":
        candidates.append("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    else:
        candidates += ["/usr/bin/soffice", "/usr/local/bin/soffice", "/opt/libreoffice/program/soffice"]
        # Snap/Flatpak — распространённый способ поставить LibreOffice на
        # современных дистрибутивах без ручной сборки из репозитория.
        candidates += ["/snap/bin/soffice", "/var/lib/flatpak/exports/bin/org.libreoffice.LibreOffice"]

    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def find_soffice():
    """Публичная обёртка над _find_soffice() — для использования из других
    модулей (экран "Настройки", диагностика), чтобы не обращаться напрямую
    к приватной функции."""
    return _find_soffice()


class SofficeNotFoundError(RuntimeError):
    pass


def check_soffice(path=None):
    """Диагностика для кнопки "🔍 Проверить" в Настройках: пытается
    реально запустить soffice (не только проверить, что файл существует —
    сам файл может быть повреждён, быть не той разрядности или требовать
    отсутствующих системных библиотек) и вернуть человекочитаемый
    результат.

    path=None — используем автопоиск (_find_soffice, с учётом уже
    сохранённого вручную пути); иначе проверяем именно указанный path, не
    трогая настройки — так пользователь может проверить путь ДО того, как
    сохранит его.

    Возвращает (ok: bool, message: str)."""
    soffice = path or _find_soffice()
    if not soffice:
        return False, "LibreOffice не найден автоматически. Укажите путь к soffice.exe/soffice вручную."
    if not os.path.exists(soffice):
        return False, f"Указанный путь не существует:\n{soffice}"

    try:
        result = subprocess.run(
            [soffice, "--version"], capture_output=True, timeout=20, check=False,
        )
    except OSError as e:
        return False, f"Не удалось запустить {soffice}:\n{e}"
    except subprocess.TimeoutExpired:
        return False, f"{soffice} запустился, но не ответил за 20 секунд."

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "ignore").strip()
        return False, f"{soffice} завершился с ошибкой (код {result.returncode}):\n{stderr or 'нет вывода'}"

    version_text = result.stdout.decode("utf-8", "ignore").strip() or "версия не определена"
    return True, f"Найден и работает: {soffice}\n{version_text}"


def _rtf_to_docx(rtf_path, workdir=None):
    """Конвертирует .rtf в .docx через LibreOffice headless, возвращает путь к .docx"""
    rtf_path = str(Path(rtf_path).resolve())
    outdir = workdir or tempfile.mkdtemp(prefix="mdo_")
    soffice = _find_soffice()
    if not soffice:
        raise SofficeNotFoundError(
            "Не найден LibreOffice (soffice). Если LibreOffice установлен, но программа "
            "всё равно его не находит — укажите путь к soffice.exe вручную на экране "
            "\"Настройки\" (раздел \"LibreOffice\"). Если LibreOffice не установлен, "
            "скачать можно бесплатно здесь: https://www.libreoffice.org/download/download/"
        )
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "docx", "--outdir", outdir, rtf_path],
            check=True, capture_output=True, timeout=60,
        )
    except FileNotFoundError:
        raise SofficeNotFoundError(
            "Не найден LibreOffice по указанному пути. Возможно, путь указан неверно."
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"LibreOffice не смог сконвертировать файл: {e.stderr.decode('utf-8', 'ignore')}")
    docx_name = Path(rtf_path).stem + ".docx"
    docx_path = os.path.join(outdir, docx_name)
    if not os.path.exists(docx_path):
        raise RuntimeError(f"Не удалось сконвертировать {rtf_path} в .docx")
    return docx_path


# Форматы, которые LibreOffice headless умеет превращать в PDF "как есть" —
# используется предпросмотром документов (экран "Документы", TODO п.1.5).
# Список умышленно ограничен офисными форматами, которые реально
# генерируются программой (.docx/.xlsx) плюс их более старые варианты —
# не пытаемся конвертировать произвольные файлы, которые могут случайно
# попасть на диск.
PDF_CONVERTIBLE_EXTENSIONS = {".docx", ".doc", ".odt", ".rtf", ".xlsx", ".xls", ".ods"}


def convert_to_pdf(source_path, outdir):
    """Конвертирует source_path (.docx/.xlsx/...) в PDF через LibreOffice
    headless, кладёт результат в outdir и возвращает путь к получившемуся
    .pdf. Та же схема вызова soffice, что и в _rtf_to_docx — один и тот же
    бинарник просто попросили конвертировать в другой формат."""
    source_path = str(Path(source_path).resolve())
    ext = Path(source_path).suffix.lower()
    if ext not in PDF_CONVERTIBLE_EXTENSIONS:
        raise ValueError(f"Формат {ext or '(без расширения)'} не поддерживается предпросмотром")
    os.makedirs(outdir, exist_ok=True)
    soffice = _find_soffice()
    if not soffice:
        raise SofficeNotFoundError(
            "Не найден LibreOffice (soffice) — предпросмотр недоступен. Укажите путь к "
            "soffice.exe вручную на экране \"Настройки\" (раздел \"LibreOffice\") или "
            "установите LibreOffice: https://www.libreoffice.org/download/download/"
        )
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", outdir, source_path],
            check=True, capture_output=True, timeout=60,
        )
    except FileNotFoundError:
        raise SofficeNotFoundError(
            "Не найден LibreOffice по указанному пути. Возможно, путь указан неверно."
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"LibreOffice не смог сконвертировать файл: {e.stderr.decode('utf-8', 'ignore')}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("LibreOffice не ответил за 60 секунд при конвертации в PDF")
    pdf_name = Path(source_path).stem + ".pdf"
    pdf_path = os.path.join(outdir, pdf_name)
    if not os.path.exists(pdf_path):
        raise RuntimeError(f"Не удалось сконвертировать {source_path} в PDF")
    return pdf_path


def _first_nonempty_run(cells, start_idx):
    """Начиная с start_idx, находит подряд идущие ячейки с одним и тем же
    текстом (merged-ячейки в python-docx дублируют текст во всех физических
    ячейках объединения) и возвращает (значение, индекс_после_блока)."""
    val = cells[start_idx]
    j = start_idx
    while j < len(cells) and cells[j] == val:
        j += 1
    return val, j


def _parse_label_value_row(cells):
    """Строка вида ['лесной квартал №','лесной квартал №',...,'139','139',
    ', таксационный выдел №',...,'15',...] - чередование label/value блоков.
    Возвращает список (label, value) пар в порядке появления."""
    cells = [c.strip() for c in cells]
    result = []
    i = 0
    n = len(cells)
    while i < n:
        if not cells[i]:
            i += 1
            continue
        label, i = _first_nonempty_run(cells, i)
        while i < n and not cells[i]:
            i += 1
        if i < n:
            value, i = _first_nonempty_run(cells, i)
            result.append((label, value))
        else:
            result.append((label, ""))
    return result


NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _to_float(s):
    if s is None:
        return None
    m = NUM_RE.search(str(s).replace(",", "."))
    return float(m.group(0)) if m else None


def _dedup_cells_by_identity(cells):
    """Возвращает тексты подряд идущих ячеек docx, схлопывая ТОЛЬКО те, что
    физически являются одной и той же объединённой ячейкой (python-docx
    возвращает для каждой позиции такой ячейки один и тот же объект _Cell -
    см. docx.table._Row.cells / Table._cells). Пустые ячейки пропускаются.

    ВАЖНО: раньше дедупликация делалась по РАВЕНСТВУ ТЕКСТА соседних ячеек,
    а не по факту их объединения. Из-за этого у пород, где нет деловой
    древесины (крупная/средняя/мелкая = "-"), три отдельные (не объединённые)
    ячейки с одинаковым "-" ошибочно схлопывались в одну, набор чисел
    получался короче 9 значений, проверка `len(dedup) >= 9` не проходила -
    и порода (обычно та, где заготавливаются только дрова) вообще
    выпадала из poroda_volumes, а значит не попадала в учёт заготовки и
    лимиты объёмов. Дедуп по identity объекта ячейки такого не допускает."""
    result = []
    prev_cell = None
    for cell in cells:
        text = cell.text.strip()
        if not text:
            continue
        if prev_cell is not None and cell is prev_cell:
            prev_cell = cell
            continue
        result.append(text)
        prev_cell = cell
    return result


def _extract_poroda_volumes(rows_cells):
    """Извлекает объём по каждой породе из таблицы МДО:
    крупная, средняя, мелкая, деловая(итого), дровяная, итого ликвида,
    ликвид из кроны, неликвид, всего. Возвращает (dict, порядок пород).

    rows_cells - список строк таблицы в виде списков объектов _Cell docx
    (НЕ строк текста) - это нужно для корректной дедупликации объединённых
    ячеек по identity, см. _dedup_cells_by_identity."""
    result = {}
    order = []
    for row_cells in rows_cells:
        cells = [c.text.strip() for c in row_cells]
        if not cells or not cells[0]:
            continue
        label = cells[0].replace("\n", " ").strip()
        last_idx = None
        for i, c in enumerate(cells):
            if c == "куб. м":
                last_idx = i
        if last_idx is None:
            continue
        dedup = _dedup_cells_by_identity(row_cells[last_idx + 1:])
        if len(dedup) >= 9:
            vals = [_to_float(x) for x in dedup[:9]]
            result[label] = {
                "krupnaya": vals[0], "srednyaya": vals[1], "melkaya": vals[2],
                "delovaya_itogo": vals[3], "drovyanaya": vals[4],
                "itogo_likvida": vals[5], "likvid_iz_krony": vals[6],
                "nelikvid": vals[7], "vsego": vals[8],
            }
            if label not in order:
                order.append(label)
    return result, order


def parse_mdo(rtf_path):
    """Разбирает .rtf МДО, возвращает словарь с данными по лесосеке."""
    docx_path = _rtf_to_docx(rtf_path)
    doc = Document(docx_path)
    if not doc.tables:
        raise RuntimeError("В документе МДО не найдено таблиц - формат не распознан")

    main_table = doc.tables[0]
    rows_cells = [row.cells for row in main_table.rows]
    rows_text = [[c.text.strip() for c in row.cells] for row in main_table.rows]

    # собираем все label/value пары из первых ~9 строк (шапка лесосеки)
    header_pairs = {}
    order = []  # чтобы понимать последовательность повторяющихся label'ов типа "рубка леса"
    for row in rows_text[:10]:
        for label, value in _parse_label_value_row(row):
            key = label.strip().rstrip(":,").strip()
            if key and value:
                header_pairs.setdefault(key, value)
                order.append((key, value))

    def get(*labels, default=""):
        for l in labels:
            if l in header_pairs:
                return header_pairs[l]
        return default

    result = {
        "lesxoz": get("Юридическое лицо, ведущее лесное хозяйство (лесхоз)"),
        "lesnichestvo": get("лесничество"),
        "kvartal": get("лесной квартал №"),
        "vydel": get(", таксационный выдел №", "таксационный выдел №"),
        "lesoseka_nomer": get(", лесосека №", "лесосека №"),
        "razryad_taks": get(", разряд такс", "разряд такс"),
        "god_lesoustroystva": get(", лесоустройство", "лесоустройство"),
        "god_rubki": None,  # заполним ниже из первого числа после "лесосека"
        "ploshad_obshaya": get("года, площадь: общая", "площадь: общая"),
        "ploshad_ekspluatatsionnaya": get("га, эксплуатационная"),
        "data": get("га, дата"),
        "kategoriya_lesov": get("категория лесов"),
        "tip_lesa": get("тип леса"),
        "sostav": get(", состав насаждения", "состав насаждения"),
        "polnota": get(", полнота насаждения", "полнота насаждения"),
        "vozrast": get(", возраст насаждения", "возраст насаждения"),
        "vid_rubki": get("рубка леса"),
        "sposob_rubki": get(", вид рубки", "вид рубки"),
        "obosnovanie_rubki": get(", способ рубки", "способ рубки"),
        "vyborka_zapasa_pct": get("выборка запаса"),
        "sostoyanie_nasazhdeniya": get("%, состояние насаждения", "состояние насаждения"),
    }

    # год лесосеки/рубки - отдельная строка вида ['лесосека','лесосека','лесосека','лесосека','2026',...]
    for row in rows_text[:6]:
        cells = [c.strip() for c in row]
        for idx, c in enumerate(cells):
            if c == "лесосека" and idx + 1 < len(cells):
                # ищем следующее непустое значение, отличное от "лесосека"
                for v in cells[idx + 1:]:
                    if v and v != "лесосека":
                        result["god_rubki"] = v
                        break
                break
        if result["god_rubki"]:
            break

    # --- таблица объёмов по породам (начинается со строки, где в кол.0 "Древесная порода") ---
    header_row_idx = None
    for idx, row in enumerate(rows_text):
        if row and row[0].strip() == "Древесная порода":
            header_row_idx = idx
    itogo_likvida = None
    vseg = None
    if header_row_idx is not None:
        for idx, row in enumerate(rows_text[header_row_idx:], start=header_row_idx):
            if row and row[0].strip().replace("\n", " ").startswith("Итого по") and "куб" in "".join(row[1:14]):
                # это строка "Итого по лесосеке" / "куб. м" - собираем числа.
                # Дедуп по identity ячейки (не по равенству текста, см.
                # _dedup_cells_by_identity) - той же природы баг, что и в
                # _extract_poroda_volumes, мог занулять этот итог, если
                # на лесосеке вообще нет деловой ни по одной породе.
                dedup = _dedup_cells_by_identity(rows_cells[idx][13:])
                # порядок колонок: крупная,средняя,мелкая,итого(дел.),дровяная,ИтогоЛиквида,ЛиквидИзКроны,неликвид,всего
                if len(dedup) >= 9:
                    itogo_likvida = _to_float(dedup[5])
                    vseg = _to_float(dedup[8])
                break

    result["vyrubaemyy_zapas"] = itogo_likvida  # "Итого ликвида" по лесосеке, м3
    result["vsego_zapas"] = vseg                 # включая неликвид, м3

    poroda_volumes, poroda_order = _extract_poroda_volumes(rows_cells)
    result["poroda_volumes"] = poroda_volumes    # {порода: {krupnaya,...,vsego}}, вкл. "Итого по лесосеке"
    result["poroda_order"] = poroda_order        # порядок пород как в документе

    result["source_file"] = os.path.basename(rtf_path)
    return result


if __name__ == "__main__":
    import sys
    import json
    path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/Ведомость_МДО_2026_6_16_11_22_59.rtf"
    data = parse_mdo(path)
    print(json.dumps(data, ensure_ascii=False, indent=2))
