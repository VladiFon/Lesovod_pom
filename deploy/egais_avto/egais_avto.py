# -*- coding: utf-8 -*-
"""Робот вечерней выгрузки ЕГАИС → Лесовод.

Делает ровно то, что человек делает руками в программе ЕГАИС
(egais.belgosles.by, десктоп-клиент 1.0.x):

  1. запускает ЕГАИС (или берёт уже открытое окно) и входит по паролю;
  2. открывает «Склад → Реестр движения по складам»;
  3. ставит период «с 01.01 текущего года по сегодня» и проверяет, что он
     встал (ЕГАИС не даёт брать больше одного календарного года; в январе
     робот делает две выгрузки: весь прошлый год и январь текущего);
  4. проверяет фильтр «Тип документа» (Перевод в сортимент, Расход при
     реализации потребителю, Приход, Расход при внутреннем перемещении)
     и, если он сбился, выставляет заново;
  5. жмёт «Получить» (F7), ждёт, жмёт «Сформировать Excel» и забирает
     файл (диалог «Сохранить как», открывшийся Excel или новый файл в
     папке — что из этого сделает ЕГАИС, то и обработаем);
  6. проверяет файл (есть колонка «Тип документа», строк > 0);
  7. заливает его в Лесовод тем же импортом, что и кнопка на сайте
     (POST /api/raskhod/egais/import) и ждёт, пока сервер его разберёт.

Почему год целиком, а не «вчерашний день»: импорт в Лесовод идёт по
документам — повторная заливка ничего не задваивает, зато подтягивает
документы, которые в ЕГАИС поправили задним числом.

Запуск:
  python egais_avto.py              — обычный прогон (так зовёт Планировщик)
  python egais_avto.py --nastroit   — один раз: спросить пароли и сохранить
                                      их в «Диспетчер учётных данных» Windows
  python egais_avto.py --razvedka   — снять «рентген» открытого окна ЕГАИС
                                      (razvedka.txt + скрин) для доводки
  python egais_avto.py --bez-zagruzki — выгрузить файл, но в Лесовод не лить
  python egais_avto.py --proverka   — «доктор»: проверить расписание, сон,
                                      блокировку экрана, пароли, связь с
                                      Лесоводом → proverka.txt
  python egais_avto.py --raspisanie 20:00 — (пере)создать задачу Планировщика
                                      с правильными настройками

Что случилось в последний раз — posledniy_rezultat.txt (по шагам, с
советом «что делать»), история всех прогонов — logi\\istoriya.txt.
"""
import argparse
import configparser
import ctypes
import datetime as dt
import getpass
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

VERSIYA = "3.2.1"
PAPKA = Path(__file__).resolve().parent
NASTROYKI = PAPKA / "nastroyki.ini"
SOSTOYANIE = PAPKA / "sostoyanie.json"
KEYRING_SERVIS_EGAIS = "Lesovod-EGAIS"
KEYRING_SERVIS_LESOVOD = "Lesovod-site"
ZADACHA = r"Lesovod\Vygruzka EGAIS"   # задача в Планировщике заданий Windows
REZULTAT = PAPKA / "posledniy_rezultat.txt"
ISTORIYA = PAPKA / "logi" / "istoriya.txt"

# Типы документов, которые Влад отмечает руками (порядок = порядок в списке
# ЕГАИС, сверху вниз). Остальные пункты списка должны быть сняты.
TIPY_PO_UMOLCHANIYU = [
    "Перевод в сортимент",
    "Расход при реализации потребителю",
    "Приход",
    "Расход при внутреннем перемещении",
]
# Сколько пунктов всего в выпадающем списке «Тип документа» видно сверху -
# нам нужны только первые четыре, поэтому достаточно знать их позиции.
OTCHET = "Реестр движения по складам"

log = logging.getLogger("egais_avto")

# Что стоит упомянуть в колокольчике Лесовода, кроме цифр (заполняется по ходу прогона).
ZAMETKI = []


class Oshibka(Exception):
    """Понятная человеку ошибка — пишется в лог без трейсбэка."""


class OshibkaBezPovtora(Oshibka):
    """Ошибка, после которой начинать заново бессмысленно или вредно:
    экран заблокирован, ЕГАИС не принял пароль (ещё пара попыток — и учётку
    заблокируют), Лесовод недоступен (файл уже выгружен и лежит на диске)."""


# --------------------------------------------------------------------------- #
#   Шаги прогона: что сделано, на чём споткнулся и что с этим делать
# --------------------------------------------------------------------------- #
# Совет человеку на случай, если робот споткнулся на этом шаге.
SOVETY = {
    "Экран Windows": (
        "В момент запуска экран был заблокирован (Win+L, заставка с паролем, сон, отключённый RDP). "
        "Робот жмёт кнопки по-настоящему, ему нужен открытый рабочий стол — см. README, «ВАЖНО ПРО ЭКРАН». "
        "proverka.bat покажет, что именно включено."),
    "Вход в ЕГАИС": (
        "Открой ЕГАИС с ярлыка руками: если просит новый пароль — поменяй и запусти nastroit.bat; "
        "если ярлык другой — поправь yarlyk в nastroyki.ini."),
    "Вкладка «Реестр движения по складам»": (
        "Открой ЕГАИС на этой вкладке, запусти razvedka.bat и пришли razvedka.txt + картинку из logi."),
    "Период выборки": (
        "ЕГАИС принимает период только внутри одного календарного года. Робот ставит его сам "
        "(с 01.01 по сегодня) и проверяет. Если дата не встаёт — скорее всего ЕГАИС обновили и поле "
        "даты ведёт себя иначе: открой вкладку, запусти razvedka.bat и пришли razvedka.txt + скрин из logi."),
    "Тип документа": (
        "Посмотри скрин tip_dokumenta в logi: какие галочки стоят. Если в списке ЕГАИС поменялся "
        "порядок пунктов — пришли скрин раскрытого списка."),
    "Получить данные (F7)": (
        "Посмотри скрин в logi: какое окно показал ЕГАИС. Попробуй руками те же даты и «Получить» — "
        "если и руками не грузит, проблема на стороне ЕГАИС (сервер/интернет)."),
    "Файл Excel": (
        "Нажми в ЕГАИС «Сформировать Excel» руками и посмотри, куда он кладёт файл; добавь эту папку "
        "в papki_poiska в nastroyki.ini."),
    "Проверка файла": (
        "Открой файл из папки выгрузок и посмотри, тот ли это отчёт и есть ли строки."),
    "Заливка в Лесовод": (
        "Открой адрес Лесовода из nastroyki.ini в браузере на этом ПК. Не открывается — сервер выключен "
        "или сменился адрес. Пишет про сертификат — см. README про lesovod_root.crt. "
        "Пароль — nastroit.bat. Файл не пропал: его можно залить руками на сайте (Расход → Импорт ЕГАИС)."),
}


class Hod:
    """Журнал шагов прогона для posledniy_rezultat.txt и колокольчика."""

    def __init__(self):
        self.shagi = []        # [nazvanie, "ok"/"oshibka"/"propusk", detal]
        self.start = time.time()

    def shag(self, nazvanie):
        hod = self

        class _Shag:
            def __enter__(self_):
                hod.shagi.append([nazvanie, "idet", ""])
                log.info("── Шаг: %s", nazvanie)
                return self_

            def detal(self_, tekst):
                hod.shagi[-1][2] = tekst

            def __exit__(self_, et, e, tb):
                zap = hod.shagi[-1]
                if et is None:
                    zap[1] = "ok"
                else:
                    zap[1] = "oshibka"
                    zap[2] = str(e) if issubclass(et, Oshibka) else f"непредвиденная ошибка: {e!r}"
                return False
        return _Shag()

    def gde_upal(self):
        return next((s[0] for s in self.shagi if s[1] == "oshibka"), None)

    def otchet(self, ok, tekst_oshibki="", rezhim=""):
        dlit = int(time.time() - self.start)
        stroki = [f"Робот ЕГАИС v{VERSIYA} — {dt.datetime.now():%d.%m.%Y %H:%M:%S}"
                  + (f" ({rezhim})" if rezhim else "")]
        upal = self.gde_upal()
        if ok:
            stroki.append("ИТОГ: ✅ ВСЁ ПРОШЛО")
        elif upal:
            stroki.append(f"ИТОГ: ❌ ОШИБКА на шаге «{upal}»")
        else:
            stroki.append(f"ИТОГ: ❌ ОШИБКА: {tekst_oshibki}")
        stroki.append("")
        znak = {"ok": "✓", "oshibka": "✗", "idet": "…", "propusk": "–"}
        for nazv, st, detal in self.shagi:
            stroki.append(f"  {znak.get(st, '?')} {nazv}" + (f" — {detal}" if detal else ""))
        if upal and upal in SOVETY:
            stroki += ["", "ЧТО ДЕЛАТЬ:", "  " + SOVETY[upal]]
        stroki += ["", f"Длительность: {dlit // 60} мин {dlit % 60} с",
                   f"Подробный лог: logi\\{dt.date.today():%Y-%m}.log, скриншоты — там же.",
                   "Проверить расписание/сон/экран: proverka.bat"]
        return "\n".join(stroki) + "\n"


HOD = Hod()


def zapisat_istoriyu(ok, tekst):
    """Одна строка на прогон в logi\\istoriya.txt — видно, в какие дни робот
    вообще запускался (если строки за день нет — Планировщик его не звал)."""
    try:
        with open(ISTORIYA, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%d.%m.%Y %H:%M}  {'OK    ' if ok else 'ОШИБКА'}  {tekst}\n")
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
#   Настройки
# --------------------------------------------------------------------------- #
def zagruzit_nastroyki():
    cfg = configparser.ConfigParser(interpolation=None)  # в путях есть %USERPROFILE%
    if not NASTROYKI.exists():
        raise Oshibka(f"Нет файла настроек {NASTROYKI}. Скопируй nastroyki.primer.ini "
                      f"в nastroyki.ini и поправь адрес Лесовода.")
    cfg.read(NASTROYKI, encoding="utf-8-sig")  # Блокнот может дописать BOM
    return cfg


def parol(servis, login):
    import keyring
    p = keyring.get_password(servis, login)
    if not p:
        raise Oshibka(f"Не сохранён пароль для {servis} / {login}. "
                      f"Запусти nastroit.bat (python egais_avto.py --nastroit).")
    return p


def okno_paroley(egais_login, les_login, oshibka=""):
    """Окошко для паролей. В чёрном окне getpass ничего не показывает при
    вводе (даже звёздочек), и кажется, что печатать нельзя — поэтому
    нормальное окно с полями и точками."""
    import tkinter as tk
    from tkinter import ttk

    rez = {}
    root = tk.Tk()
    root.title("Робот ЕГАИС — пароли")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    fr = ttk.Frame(root, padding=16)
    fr.grid()
    ttk.Label(fr, text="Пароли сохранятся в «Диспетчер учётных данных» Windows,\n"
                       "в файлах их не будет.").grid(columnspan=2, sticky="w", pady=(0, 10))
    if oshibka:
        ttk.Label(fr, text=oshibka, foreground="red", wraplength=380).grid(
            columnspan=2, sticky="w", pady=(0, 10))
    polya = {}
    for nazv, login in (("egais", egais_login), ("lesovod", les_login)):
        if not login:
            continue
        ttk.Label(fr, text=f"Пароль {'ЕГАИС' if nazv == 'egais' else 'Лесовода'} "
                           f"для «{login}»:").grid(columnspan=2, sticky="w")
        e = ttk.Entry(fr, show="●", width=40)
        e.grid(columnspan=2, sticky="we", pady=(2, 10))
        polya[nazv] = e
    pokaz = tk.BooleanVar()

    def pereklyuchit():
        for e in polya.values():
            e.config(show="" if pokaz.get() else "●")

    ttk.Checkbutton(fr, text="Показать пароли", variable=pokaz,
                    command=pereklyuchit).grid(columnspan=2, sticky="w")
    oshibka_lbl = ttk.Label(fr, text="", foreground="red")
    oshibka_lbl.grid(columnspan=2, sticky="w")

    def sohranit(_=None):
        znach = {k: e.get() for k, e in polya.items()}
        if any(not v for v in znach.values()):
            oshibka_lbl.config(text="Заполни все поля.")
            return
        rez.update(znach)
        root.destroy()

    ttk.Button(fr, text="Сохранить", command=sohranit).grid(columnspan=2, pady=(10, 0))
    root.bind("<Return>", sohranit)
    next(iter(polya.values())).focus_force()
    root.mainloop()
    return rez


def egais_klyuch(cfg):
    """Имя, под которым пароль ЕГАИС лежит в Диспетчере учётных данных.
    Логин в окне ЕГАИС подставляется сам, поэтому в настройках он не обязателен."""
    return cfg.get("egais", "login", fallback="").strip() or "egais"


def nastroit(cfg):
    import keyring
    egais_login = egais_klyuch(cfg)
    les_login = cfg.get("lesovod", "login", fallback="").strip()
    oshibka = ""
    egais_gotov = False
    while True:
        try:
            # при повторе (Лесовод не пустил) пароль ЕГАИС уже сохранён — не спрашиваем
            p = okno_paroley("" if egais_gotov else egais_login, les_login, oshibka)
        except Exception:  # noqa: BLE001 — нет tkinter: по-старому, в консоли
            print("(Пароль при вводе не отображается — это нормально, просто печатай и жми Enter)")
            p = {} if egais_gotov else {"egais": getpass.getpass(f"Пароль ЕГАИС для «{egais_login}»: ")}
            if les_login:
                p["lesovod"] = getpass.getpass(f"Пароль Лесовода для «{les_login}»: ")
        if not p and not (egais_gotov and not les_login):
            raise Oshibka("Окно закрыли без сохранения — пароли не записаны.")
        if not egais_gotov:
            keyring.set_password(KEYRING_SERVIS_EGAIS, egais_login, p["egais"])
            print(f"Пароль ЕГАИС для «{egais_login}» сохранён.")
            egais_gotov = True
        if not les_login:
            break
        keyring.set_password(KEYRING_SERVIS_LESOVOD, les_login, p["lesovod"])
        try:
            lesovod_login(cfg)  # сразу проверим, что пускает
            print("Лесовод: вход проверен, всё ок.")
            break
        except Exception as e:  # noqa: BLE001
            import requests
            if isinstance(e, requests.exceptions.SSLError):
                oshibka = ("Лесовод работает по https с собственным сертификатом Caddy, робот ему пока "
                           "не доверяет. Положи root.crt с сервера Лесовода в папку робота под именем "
                           "lesovod_root.crt (где его взять — в README) и нажми «Сохранить» ещё раз.")
            elif isinstance(e, requests.exceptions.ConnectionError):
                oshibka = (f"Не достучался до Лесовода по адресу {cfg.get('lesovod', 'url')}. "
                           f"Проверь url в nastroyki.ini и что сервер включён.")
            else:
                oshibka = f"Лесовод не пустил: {e}"
            print(oshibka)
    print("\nГотово. Теперь можно запускать zapustit_seychas.bat для пробы.")


# --------------------------------------------------------------------------- #
#   Проверки окружения
# --------------------------------------------------------------------------- #
def ekran_zablokirovan():
    """Робот жмёт кнопки по-настоящему, поэтому при заблокированном экране
    Windows (Win+L, заставка с паролем, отключённый RDP) у него нет рабочего
    стола — честно скажем об этом сразу, а не будем тыкать в пустоту."""
    user32 = ctypes.windll.user32
    DESKTOP_SWITCHDESKTOP = 0x0100
    h = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not h:
        return True
    ok = user32.SwitchDesktop(h)
    user32.CloseDesktop(h)
    return not ok


def skrin(imya):
    try:
        from PIL import ImageGrab
        put = PAPKA / "logi" / f"{dt.datetime.now():%Y-%m-%d_%H-%M-%S}_{imya}.png"
        ImageGrab.grab().save(put)
        log.info("Скриншот: %s", put)
        return put
    except Exception as e:  # noqa: BLE001
        log.warning("Скриншот не снялся: %s", e)


def ekranirovat(tekst):
    """pywinauto.send_keys считает +^%~(){}[] спецсимволами."""
    return "".join("{%s}" % c if c in "+^%~(){}[]" else c for c in tekst)


# --------------------------------------------------------------------------- #
#   ЕГАИС
# --------------------------------------------------------------------------- #
def okna_egais():
    from pywinauto import Desktop
    return [w for w in Desktop(backend="win32").windows(visible_only=True)
            if w.window_text().startswith("ЕГАИС")]


def glavnoe_okno():
    for w in okna_egais():
        if "Пользователь" in w.window_text():
            return w
    return None


def okno_vhoda():
    for w in okna_egais():
        if "Пользователь" not in w.window_text():
            return w
    return None


def zhdat(uslovie, sekund, shag=1.0, chto=""):
    konec = time.time() + sekund
    while time.time() < konec:
        r = uslovie()
        if r:
            return r
        time.sleep(shag)
    raise Oshibka(f"Не дождался: {chto} ({sekund} с)")


def _eto_knopka(c):
    """Кнопка окна-сообщения. В ЕГАИС это не только TButton: у окна
    «Информация» кнопка «OK» с зелёной галочкой — TBitBtn, в имени класса
    которой нет слова «button» (из-за этого v2.4 такие окна не видела и
    висела на них)."""
    k = c.class_name().lower()
    return "button" in k or "btn" in k


def _tekst_knopki(c):
    return c.window_text().replace("&", "").strip().lower()


def _tekst_iz_bufera(w):
    """Текст стандартного окна-сообщения Windows/Delphi копируется по Ctrl+C
    (у Delphi надпись — не окно, её иначе не прочитать)."""
    try:
        import win32clipboard
        from pywinauto.keyboard import send_keys
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.CloseClipboard()
        w.set_focus()
        send_keys("^c")
        time.sleep(0.4)
        win32clipboard.OpenClipboard()
        try:
            t = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        # формат Windows: «---\nЗаголовок\n---\nТекст\n---\nOK\n---»
        stroki = [x.strip() for x in str(t).splitlines() if x.strip() and set(x.strip()) != {"-"}]
        stroki = [x for x in stroki if x.lower() not in KNOPKI_OK and x != w.window_text().strip()]
        return " ".join(stroki)
    except Exception:  # noqa: BLE001
        return ""


def vsplyvshie_okna(pid):
    """Всплывшие окна-сообщения ЕГАИС (у которых есть кнопка OK/Ознакомлен/…):
    список словарей {okno, zagolovok, tekst, knopka}. Главное окно и окно
    входа (заголовок «ЕГАИС…») не считаются."""
    from pywinauto import Desktop
    out = []
    for w in Desktop(backend="win32").windows(visible_only=True):
        try:
            if w.process_id() != pid or w.window_text().startswith("ЕГАИС"):
                continue
            knopka, teksty = None, []
            for c in w.descendants():
                if _eto_knopka(c):
                    if knopka is None and _tekst_knopki(c) in KNOPKI_OK:
                        knopka = c
                    continue
                t = c.window_text().strip()
                if t:
                    teksty.append(t)
            if knopka is None:
                knopka = _knopka_po_pravilu(w, teksty)
            if knopka is None:
                continue  # выпадающие списки, подсказки и т.п.
            tekst = " ".join(teksty) or _tekst_iz_bufera(w)
            out.append({"okno": w, "zagolovok": w.window_text().strip(),
                        "tekst": tekst, "knopka": knopka})
        except Exception:  # noqa: BLE001
            pass
    return out


# Правила «незнакомых» окон: раздел [okna] в nastroyki.ini, строки вида
#   кусок текста или заголовка окна = текст кнопки
# Робот сам жмёт только OK/Ознакомлен/Закрыть. Если ЕГАИС вылез с окном, где
# надо выбрать (Да/Нет/Отмена), робот его НЕ трогает, а описывает в отчёте —
# и одной строкой в [okna] его можно научить, что жать в следующий раз.
PRAVILA_OKON = []


def zagruzit_pravila_okon(cfg):
    PRAVILA_OKON.clear()
    if cfg is not None and cfg.has_section("okna"):
        for kusok, knopka in cfg.items("okna"):
            if kusok.strip() and knopka.strip():
                PRAVILA_OKON.append((kusok.strip().lower(), knopka.replace("&", "").strip().lower()))


def _knopka_po_pravilu(w, teksty):
    if not PRAVILA_OKON:
        return None
    vse = (w.window_text() + " " + " ".join(teksty)).lower()
    for kusok, nado in PRAVILA_OKON:
        if kusok in vse:
            for c in w.descendants():
                if _eto_knopka(c) and _tekst_knopki(c) == nado:
                    log.info("Окно «%s»: по правилу [okna] жму «%s».", w.window_text(), nado)
                    return c
    return None


def opisat_okna(pid=None):
    """Что сейчас на экране у ЕГАИС: каждое видимое окно — заголовок, текст
    и кнопки. Нужен, когда робот споткнулся: по этому описанию видно, какое
    незнакомое окно вылезло, и можно дописать правило в [okna]."""
    from pywinauto import Desktop
    pidy = {pid} if pid else pidy_egais()
    out = []
    for w in Desktop(backend="win32").windows(visible_only=True):
        try:
            if w.process_id() not in pidy:
                continue
            knopki, teksty = [], []
            for c in w.descendants():
                t = c.window_text().strip()
                if not t:
                    continue
                if _eto_knopka(c):
                    knopki.append(c.window_text().replace("&", "").strip())
                elif len(teksty) < 6 and not w.window_text().startswith("ЕГАИС"):
                    teksty.append(t[:200])
            if w.window_text().startswith("ЕГАИС"):
                continue  # главное окно/вход — не «всплывшее»
            out.append(f"окно «{w.window_text().strip() or '(без заголовка)'}»"
                       + (f": {' '.join(teksty)[:300]}" if teksty else "")
                       + (f" [кнопки: {', '.join(knopki[:6])}]" if knopki else ""))
        except Exception:  # noqa: BLE001
            pass
    return out


# --------------------------------------------------------------------------- #
#   Живучесть (3.1): ЕГАИС всегда закрывается, а прогон начинается заново
# --------------------------------------------------------------------------- #
ZHIZN = {"sami": False, "pidy": set(), "byl_otkryt": False}


def pidy_egais():
    """Процессы ЕГАИС: по окнам «ЕГАИС…» + те, что робот уже видел в этом
    запуске (у зависшего процесса окна могут и не найтись)."""
    try:
        for w in okna_egais():
            ZHIZN["pidy"].add(w.process_id())
    except Exception:  # noqa: BLE001
        pass
    return set(ZHIZN["pidy"])


def _process_zhiv(pid):
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        kod = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(kod))
        ctypes.windll.kernel32.CloseHandle(h)
        return kod.value == 259  # STILL_ACTIVE
    except Exception:  # noqa: BLE001
        return False


KNOPKI_DA = ("да", "yes", "ok", "ок", "выход", "выйти", "закрыть")


def zakryt_egais(prichina=""):
    """Закрывает ЕГАИС ПОЛНОСТЬЮ: сначала по-хорошему (крестик + «Да» на
    вопрос «Выйти?»), через 10 секунд — снимает процесс. Возвращает True,
    если после этого ни одного процесса ЕГАИС не осталось."""
    pidy = pidy_egais()
    if not pidy:
        return True
    log.info("Закрываю ЕГАИС%s…", f" ({prichina})" if prichina else "")
    WM_CLOSE = 0x0010
    try:
        for w in okna_egais():
            ctypes.windll.user32.PostMessageW(w.handle, WM_CLOSE, 0, 0)
    except Exception:  # noqa: BLE001
        pass
    konec = time.time() + 10
    while time.time() < konec and any(_process_zhiv(p) for p in pidy):
        time.sleep(1)
        try:  # «Вы действительно хотите выйти?» → Да
            from pywinauto import Desktop
            for w in Desktop(backend="win32").windows(visible_only=True):
                if w.process_id() in pidy and not w.window_text().startswith("ЕГАИС"):
                    for c in w.descendants():
                        if _eto_knopka(c) and _tekst_knopki(c) in KNOPKI_DA:
                            c.click()
                            break
        except Exception:  # noqa: BLE001
            pass
    for p in pidy:
        if _process_zhiv(p):
            log.warning("ЕГАИС (процесс %s) сам не закрылся — снимаю.", p)
            try:
                subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"], capture_output=True, timeout=30)
            except Exception as e:  # noqa: BLE001
                log.warning("taskkill не сработал: %s", e)
    time.sleep(2)
    zhivye = [p for p in pidy if _process_zhiv(p)]
    if zhivye:
        log.error("ЕГАИС так и не закрылся (процессы %s).", zhivye)
        return False
    ZHIZN["pidy"].clear()
    log.info("ЕГАИС закрыт.")
    return True


def soobshcheniya_oshibok(pid):
    """Тексты всплывших окошек-сообщений самого ЕГАИС."""
    return [f"[{o['zagolovok']}] {o['tekst']}" for o in vsplyvshie_okna(pid)]


# Кнопки, которыми закрываются информационные окошки ЕГАИС при запуске
# («ВНИМАНИЕ! … заканчивается срок вывозки» → «Ознакомлен» и т.п.).
KNOPKI_OK = ("ознакомлен", "ok", "ок", "закрыть", "продолжить", "понятно")


def zakryt_okno(o, imya_skrina="preduprezhdenie_egais"):
    """Снимает скрин окна-сообщения, пишет его текст в лог и закрывает."""
    w = o["okno"]
    log.warning("ЕГАИС показал окно «%s»: %s", o["zagolovok"], (o["tekst"] or "(текст не прочитался)")[:500])
    try:
        w.set_focus()
    except Exception:  # noqa: BLE001
        pass
    skrin(imya_skrina)
    try:
        o["knopka"].click()
    except Exception:  # noqa: BLE001
        try:
            o["knopka"].click_input()
        except Exception:  # noqa: BLE001
            pass
    time.sleep(1)
    if okno_zhivo(w):
        from pywinauto.keyboard import send_keys
        try:
            w.set_focus()
        except Exception:  # noqa: BLE001
            pass
        send_keys("{ENTER}")  # кнопка и так в фокусе
        time.sleep(1)


def zakryt_vsplyvashki(pid, zhdat_sek=0):
    """Закрывает всплывающие окна-предупреждения ЕГАИС, чтобы они не
    перекрывали работу. Перед закрытием снимает скрин — там бывает полезное
    (например, у какого разрешительного документа кончается срок вывозки),
    и пишет текст окна в лог. zhdat_sek — сколько ещё секунд ловить
    окошки, которые вылезают с задержкой (после входа). Заодно убирает
    окно, оставшееся висеть с прошлого раза (например, «Информация» о
    слишком большом периоде)."""
    zakryto = 0
    konec = time.time() + zhdat_sek
    while True:
        for o in vsplyvshie_okna(pid):
            ZAMETKI.append(f"ЕГАИС показал «{o['zagolovok']}» (скрин в logi на ПК робота)")
            zakryt_okno(o)
            zakryto += 1
        if time.time() >= konec:
            return zakryto
        time.sleep(1)


def okno_zhivo(w):
    """Окно ещё существует и видно. У обёрток pywinauto нет .exists() (он
    есть только у WindowSpecification) — спрашиваем Windows напрямую."""
    try:
        return bool(ctypes.windll.user32.IsWindow(w.handle)) and \
            bool(ctypes.windll.user32.IsWindowVisible(w.handle))
    except Exception:  # noqa: BLE001
        return False


def ustoychivoe_okno():
    """Окно входа (или сразу главное), которое живёт хотя бы 2 секунды. При
    запуске ЕГАИС иногда мелькает промежуточное окошко с тем же заголовком
    (обновление/заставка) — если схватить его, через миг «недопустимый
    дескриптор окна» (WinError 1400, ПК Влада 08.10)."""
    w = okno_vhoda() or glavnoe_okno()
    if w is None:
        return None
    time.sleep(2)
    try:
        if okno_zhivo(w):
            return w
    except Exception:  # noqa: BLE001
        pass
    return None


def zapustit_i_voyti(cfg):
    from pywinauto.keyboard import send_keys

    gl = glavnoe_okno()
    if gl:
        ZHIZN["byl_otkryt"] = True
        log.info("ЕГАИС уже открыт и вход выполнен — беру готовое окно.")
        zakryt_vsplyvashki(gl.process_id())
        return gl, False

    vh = okno_vhoda()
    if not vh:
        put = os.path.expandvars(cfg.get("egais", "yarlyk",
                                         fallback=r"%USERPROFILE%\Desktop\EGAIS.lnk"))
        if not Path(put).exists():
            raise OshibkaBezPovtora(f"Не нашёл ярлык/программу ЕГАИС: {put} (поправь yarlyk в nastroyki.ini)")
        log.info("Запускаю ЕГАИС: %s", put)
        ZHIZN["sami"] = True
        os.startfile(put)  # noqa: S606 — .lnk тоже открывается
        vh = zhdat(ustoychivoe_okno, 180, chto="окно входа ЕГАИС")
        if "Пользователь" in vh.window_text():
            zakryt_vsplyvashki(vh.process_id(), zhdat_sek=15)
            return vh, True

    pw = parol(KEYRING_SERVIS_EGAIS, egais_klyuch(cfg))
    if not okno_zhivo(vh):  # пока ждали, окно сменилось — берём актуальное
        vh = zhdat(ustoychivoe_okno, 60, chto="окно входа ЕГАИС")
        if "Пользователь" in vh.window_text():
            zakryt_vsplyvashki(vh.process_id(), zhdat_sek=15)
            return vh, True
    vh.set_focus()
    time.sleep(0.5)

    # Логин ЕГАИС подставляет сам, а курсор сразу стоит в поле «Пароль» —
    # логин не трогаем. Поле пароля ищем по стилю ES_PASSWORD, чтобы точно
    # печатать туда, даже если фокус куда-то сбежал.
    pole_parol = None
    for c in vh.descendants():
        try:
            if "edit" in c.class_name().lower() and c.has_style(0x20):  # ES_PASSWORD
                pole_parol = c
                break
        except Exception:  # noqa: BLE001
            pass

    if pole_parol is not None:
        pole_parol.set_focus()
        if hasattr(pole_parol, "set_edit_text"):  # у cx-полей Delphi этого метода нет
            pole_parol.set_edit_text("")
        pole_parol.type_keys(ekranirovat(pw), with_spaces=True, set_foreground=True)
    else:
        # как на скрине: курсор после запуска сразу стоит в поле «Пароль»
        log.info("Поле пароля не нашлось как Edit — печатаю в активное поле.")
        send_keys(ekranirovat(pw), with_spaces=True)
    send_keys("{ENTER}")
    log.info("Пароль введён, жду главное окно…")

    pid = vh.process_id()
    try:
        gl = zhdat(glavnoe_okno, 180, chto="главное окно ЕГАИС после входа")
    except Oshibka:
        oshibki = soobshcheniya_oshibok(pid)
        skrin("vhod")
        if oshibki:  # ЕГАИС сам сказал «нет» (пароль?) — второй раз не ломимся
            raise OshibkaBezPovtora("Вход в ЕГАИС не удался. " + "; ".join(oshibki))
        raise Oshibka("Вход в ЕГАИС не удался. Окно не появилось.")
    # предупреждения вылезают через пару секунд после входа — ловим их
    zakryt_vsplyvashki(pid, zhdat_sek=15)
    return gl, True


def otkryt_reestr(gl):
    """Открывает вкладку «Реестр движения по складам» (если ещё не открыта)."""
    from pywinauto.keyboard import send_keys

    zakryt_vsplyvashki(gl.process_id())
    gl.set_focus()
    if gl.get_show_state() != 3:  # 3 = развёрнуто
        gl.maximize()
    time.sleep(1)

    if _vkladka_otkryta(gl):
        log.info("Вкладка «%s» уже открыта.", OTCHET)
        return

    # 1) настоящее дерево Windows (TTreeView)
    for c in gl.descendants():
        # В ЕГАИС 1.0.43 меню — TdxDBTreeView: это обычный SysTreeView32
        # внутри, поэтому оборачиваем его в TreeViewWrapper вручную.
        if "treeview" in c.class_name().lower():
            try:
                from pywinauto.controls.common_controls import TreeViewWrapper
                tv = TreeViewWrapper(c.handle)
                punkt = None
                for koren in tv.roots():
                    if koren.text().strip() != "Склад":
                        continue
                    koren.expand()
                    for el in koren.children():
                        if el.text().strip() == OTCHET:
                            punkt = el
                            break
                if punkt is None:
                    log.info("В дереве меню не нашёл «Склад → %s».", OTCHET)
                    continue
                punkt.ensure_visible()
                punkt.select()
                punkt.click_input(double=True)
                time.sleep(3)
                if not _vkladka_otkryta(gl):
                    send_keys("{ENTER}")  # на случай, если открывается по Enter
                    time.sleep(3)
                if _vkladka_otkryta(gl):
                    log.info("Открыл отчёт через дерево меню.")
                    return
            except Exception as e:  # noqa: BLE001
                log.info("Дерево не дало открыть пункт: %s", e)

    # 2) строка «Текст для поиска…» над деревом: печатаем название, Enter
    for c in gl.descendants():
        try:
            if "edit" in c.class_name().lower() and c.rectangle().top < gl.rectangle().top + 120:
                c.click_input()
                c.set_edit_text("")
                send_keys(ekranirovat(OTCHET), with_spaces=True)
                time.sleep(1.5)
                send_keys("{DOWN}{ENTER}")
                time.sleep(3)
                if _vkladka_otkryta(gl):
                    log.info("Открыл отчёт через поиск по меню.")
                    return
                break
        except Exception:  # noqa: BLE001
            pass

    skrin("menyu")
    raise Oshibka(f"Не смог открыть «{OTCHET}». Запусти razvedka.bat при открытом ЕГАИС "
                  f"и пришли razvedka.txt — подстрою под твою версию программы.")


def _vkladka_otkryta(gl):
    listy = [c for c in gl.descendants() if c.class_name() == "TcxTabSheet"]
    if listy:  # вкладок может быть несколько (Склады, Наличие…) — нужна именно наша и активная
        return any(OTCHET in c.window_text() and c.is_visible() for c in listy)
    for c in gl.descendants():
        try:
            if "datee" in c.class_name().lower():  # поля даты есть только на вкладке отчёта
                return True
            if OTCHET in c.window_text() and "tab" in c.class_name().lower():
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _sortirovat_po_mestu(kontroly):
    return sorted(kontroly, key=lambda c: (c.rectangle().top // 10, c.rectangle().left))


def _na_ekrane(c):
    """ЕГАИС держит часть полей формы за краем экрана (координаты 1491+ и
    даже 10293+) — нам нужны только реально видимые."""
    r = c.rectangle()
    shir = ctypes.windll.user32.GetSystemMetrics(0)
    return c.is_visible() and 0 <= r.left < shir and r.width() > 0


def vvesti_datu(pole, nado):
    """Ввод даты в TcxDateEdit (поле с маской __.__.____). Ctrl+A там не
    выделяет всё (на ПК Влада после Ctrl+A+ввода вышло «08.09.2010»), поэтому
    пробуем по очереди несколько способов и после каждого читаем, что
    реально встало в поле."""
    from pywinauto.keyboard import send_keys

    if pole.window_text().strip() == nado:
        return
    vnutr = (pole.children() or [pole])[0]
    cifry = nado.replace(".", "")
    sposoby = [
        ("Home+Shift+End и ввод", lambda: send_keys("{HOME}+{END}" + nado)),
        ("Home и цифры поверх маски", lambda: send_keys("{HOME}" + cifry)),
        ("Home и дата поверх маски", lambda: send_keys("{HOME}" + nado)),
        ("текст напрямую в поле", lambda: vnutr.set_edit_text(nado)),
        ("Delete по символам и цифры", lambda: send_keys("{HOME}" + "{DELETE}" * 10 + "{HOME}" + cifry)),
    ]
    stalo = ""
    for imya, sdelat in sposoby:
        vnutr.click_input()
        time.sleep(0.2)
        try:
            sdelat()
        except Exception as e:  # noqa: BLE001
            log.info("Способ «%s» не применим: %s", imya, e)
            continue
        time.sleep(0.2)
        send_keys("{TAB}")
        time.sleep(0.6)
        stalo = pole.window_text().strip()
        if stalo == nado:
            log.info("Дата %s введена (способ: %s).", nado, imya)
            return
        log.info("Способ «%s» не сработал: в поле «%s».", imya, stalo)
    skrin("data")
    raise Oshibka(f"Дата не встала: нужно {nado}, в поле «{stalo}».")


def periody(segodnya):
    """Какие периоды выгружать. ЕГАИС не даёт брать больше одного
    календарного года («Период выборки данных должен быть в пределах одного
    календарного года»), поэтому в январе, когда ещё правят прошлый год,
    это ДВЕ выгрузки: весь прошлый год и с 01.01 по сегодня. (v2.4 в
    январе ставила 01.01 прошлого года — сегодня одним куском, и ЕГАИС бы
    это не пропустил.)"""
    tekushchiy = (dt.date(segodnya.year, 1, 1), segodnya)
    if segodnya.month == 1:
        g = segodnya.year - 1
        return [(dt.date(g, 1, 1), dt.date(g, 12, 31)), tekushchiy]
    return [tekushchiy]


def _data_iz_polya(t):
    try:
        return dt.datetime.strptime(t.strip()[:10], "%d.%m.%Y").date()
    except (ValueError, AttributeError):
        return None


def _polya_perioda(gl):
    """«Операции за период с … по …» — два TcxDateEdit в одной строке,
    самой верхней среди видимых полей дат (по разведке: L497 и L673, T127)."""
    daty = [c for c in gl.descendants()
            if c.class_name() == "TcxDateEdit" and _na_ekrane(c)]
    if len(daty) < 2:
        return None
    verh = min(c.rectangle().top for c in daty)
    stroka = sorted((c for c in daty if abs(c.rectangle().top - verh) < 8),
                    key=lambda c: c.rectangle().left)
    return stroka[:2] if len(stroka) >= 2 else None


def proverit_period_v_okne(gl, s, po):
    """Читает, что реально стоит в полях периода, и не пускает дальше, если
    это не то, что нужно, или период шире календарного года (иначе ЕГАИС
    на «Получить» покажет окно «Информация» и ничего не выгрузит)."""
    polya = _polya_perioda(gl)
    if not polya:
        skrin("period")
        raise Oshibka("Не нашёл поля «Операции за период с … по …» на вкладке.")
    t_s, t_po = (p.window_text().strip() for p in polya)
    d_s, d_po = _data_iz_polya(t_s), _data_iz_polya(t_po)
    log.info("В окне ЕГАИС период: «%s» — «%s».", t_s, t_po)
    if d_s is None or d_po is None:
        skrin("period")
        raise Oshibka(f"В полях периода не даты: «{t_s}» — «{t_po}».")
    if d_s.year != d_po.year or d_s > d_po:
        skrin("period")
        raise Oshibka(f"Период «{t_s} — {t_po}» ЕГАИС не примет (больше одного календарного года). "
                      f"Нужно было {s:%d.%m.%Y} — {po:%d.%m.%Y}.")
    if (d_s, d_po) != (s, po):
        skrin("period")
        raise Oshibka(f"В полях встал период «{t_s} — {t_po}», а нужен {s:%d.%m.%Y} — {po:%d.%m.%Y}.")


def postavit_period(gl, s, po):
    if s.year != po.year:  # защита от самого себя: ЕГАИС такое не примет
        raise Oshibka(f"Внутренняя ошибка: период {s:%d.%m.%Y} — {po:%d.%m.%Y} шире года.")
    polya = _polya_perioda(gl)
    if not polya:
        skrin("period")
        raise Oshibka("Не нашёл поля «Операции за период с … по …» на вкладке "
                      "(раньше робот в этом случае печатал «вслепую» — и мог поставить ерунду).")
    # Сначала «по», потом «с»: тогда ни в какой момент «с» не оказывается
    # позже «по» (например, когда в «по» с прошлого раза стоит 31.12 прошлого года).
    for pole, data in ((polya[1], po), (polya[0], s)):
        vvesti_datu(pole, data.strftime("%d.%m.%Y"))
    time.sleep(0.5)
    proverit_period_v_okne(gl, s, po)
    log.info("Период: %s — %s", s.strftime("%d.%m.%Y"), po.strftime("%d.%m.%Y"))


# Пункты выпадающего списка «Тип документа» сверху вниз (по скрину Влада).
VSE_TIPY = [
    "Перевод в сортимент",
    "Расход при реализации потребителю",
    "Приход",
    "Расход при внутреннем перемещении",
    "Расход для собственного потребления",
    "Расход для переработки",
    "Расход при реализации на экспорт",
    "Замена бирки",
    "Корректировка остатков",
    "Расход для автоматизированной переработки",
]


def _indeksy_tipov(t):
    """Текст поля («Перевод;Приход;…») → номера пунктов списка и то, что не
    узнали. ЕГАИС в поле сокращает «Перевод в сортимент» до «Перевод»."""
    est, neznakomye = set(), []
    for ch in (x.strip() for x in t.split(";")):
        if not ch:
            continue
        if ch in VSE_TIPY:
            est.add(VSE_TIPY.index(ch))
            continue
        kandidaty = [i for i, v in enumerate(VSE_TIPY) if v.startswith(ch)]
        if len(kandidaty) == 1 or (kandidaty and ch == "Перевод"):
            est.add(kandidaty[0])
        else:
            neznakomye.append(ch)
    return est, neznakomye


def proverit_tipy(gl, tipy):
    """Фильтр «Тип документа». ЕГАИС не помнит галочки между запусками,
    поэтому каждый раз сверяем текст поля с нужным набором и переключаем
    только расходящиеся пункты: сначала клавиатурой (стрелки + пробел), не
    вышло — мышкой по строкам списка (строка ~15 px, по скрину)."""
    from pywinauto.keyboard import send_keys
    import pywinauto.mouse as mouse

    kombo = [c for c in gl.descendants()
             if c.class_name() == "TcxCheckComboBox" and _na_ekrane(c)]
    if not kombo:
        log.info("Поле «Тип документа» не нашлось — оставляю как есть.")
        return
    pole = _sortirovat_po_mestu(kombo)[0]
    r = pole.rectangle()
    nuzhno = {VSE_TIPY.index(t) for t in tipy if t in VSE_TIPY}

    def tekst():
        t = pole.window_text()
        for ch in pole.children():
            t = t or ch.window_text()
        return (t or "").strip()

    def okna_processa():
        from pywinauto import Desktop
        out = {}
        for w in Desktop(backend="win32").windows(visible_only=True):
            try:
                if w.process_id() == gl.process_id():
                    out[w.handle] = w
            except Exception:  # noqa: BLE001
                pass
        return out

    def otkryt():
        """Открыть выпадающий список. Список — отдельное окно ЕГАИС, поэтому
        узнаём его как новое окно процесса после клика по стрелке ▼. (Раньше
        клик по полю уже открывал список, а Alt+Down следом закрывал его —
        отсюда «не встал первый пункт».)"""
        do = okna_processa()
        # Внутри поля справа две кнопки: ▼ (≈33 px от края) и ластик (≈12 px)
        # — раньше робот попадал в ластик и стирал галочки (ПК Влада 08.10).
        # Кликаем в текстовую часть: она сама открывает список.
        mouse.click(coords=(r.left + 60, (r.top + r.bottom) // 2))
        time.sleep(0.8)
        novye = [w for h, w in okna_processa().items() if h not in do]
        if not novye:
            send_keys("%{DOWN}")
            time.sleep(0.8)
            novye = [w for h, w in okna_processa().items() if h not in do]
        sp = novye[0] if novye else None
        log.info("Список типов %s.", f"открыт ({sp.class_name()} {sp.rectangle()})" if sp else "не виден")
        return sp

    t = tekst()
    est, neznakomye = _indeksy_tipov(t)
    if neznakomye:
        log.info("В поле незнакомые пункты %s — очищаю ластиком.", neznakomye)
        mouse.click(coords=(r.right - 12, (r.top + r.bottom) // 2))  # ластик внутри поля
        time.sleep(0.5)
        est = set()

    def spisok_lb(sp):
        """Внутри выпадашки DevExpress обычно настоящий LISTBOX Windows —
        тогда точные координаты строк и их тексты берём у самого списка."""
        from pywinauto.controls.win32_controls import ListBoxWrapper
        if sp is None:
            return None, []
        kandidaty = [sp] + list(sp.descendants())
        log.info("Окна выпадашки: %s", [(c.class_name(), str(c.rectangle())) for c in kandidaty][:10])
        for c in kandidaty:
            try:
                lb = ListBoxWrapper(c.handle)
                teksty = lb.item_texts()
                if any("Приход" in t for t in teksty):
                    return lb, teksty
            except Exception:  # noqa: BLE001
                pass
        return None, []

    # мышь первой: по логу 08.10 клики по строкам (верх списка + 9 + 15·i)
    # попадают точно, а список DevExpress не настоящий LISTBOX
    for prohod, sposob in enumerate(("мышь", "мышь", "клавиатура")):
        t = tekst()
        est, neznakomye = _indeksy_tipov(t)
        perekl = sorted(est ^ nuzhno)
        if not perekl and not neznakomye:
            log.info("Тип документа как надо: %s", t)
            return
        log.info("Тип документа «%s» — переключаю пункты %s (%s).", t, perekl, sposob)
        sp = otkryt()
        if sposob == "список":
            lb, teksty = spisok_lb(sp)
            if lb is None:
                log.info("Внутри выпадашки нет обычного списка Windows — пробую клавиатурой.")
                send_keys("{ESC}")
                time.sleep(0.5)
                continue
            log.info("Пункты списка: %s", teksty)
            for i in perekl:
                nomer = next((n for n, t in enumerate(teksty) if t.strip() == VSE_TIPY[i]), None)
                if nomer is None:
                    log.info("В списке нет пункта «%s».", VSE_TIPY[i])
                    continue
                rr = lb.item_rect(nomer)
                # клик по квадратику-галочке слева в строке
                lb.click_input(coords=(rr.left + 8, (rr.top + rr.bottom) // 2))
                time.sleep(0.3)
        elif sposob == "клавиатура":
            send_keys("{HOME}")
            time.sleep(0.2)
            tek = 0
            for i in perekl:
                send_keys("{DOWN}" * (i - tek))
                send_keys("{SPACE}")
                time.sleep(0.2)
                tek = i
        else:
            for i in perekl:
                verh = sp.rectangle().top if sp is not None else r.bottom
                mouse.click(coords=(r.left + 9, verh + 9 + 15 * i))
                time.sleep(0.3)
        send_keys("{ENTER}")
        time.sleep(0.8)

    t = tekst()
    est, neznakomye = _indeksy_tipov(t)
    lishnie = est - nuzhno
    if lishnie or neznakomye:
        skrin("tip_dokumenta")
        raise Oshibka(f"В «Тип документа» стоят лишние пункты: «{t}» — выгрузка была бы неверной.")
    nehvataet = [VSE_TIPY[i] for i in sorted(nuzhno - est)]
    skrin("tip_dokumenta")
    # Без «Перевода в сортимент» Влад разрешил ехать (08.10), без остальных —
    # нет: выгрузка вышла бы почти пустой (как с одним «Переводом» — 42 строки).
    if set(nehvataet) - {"Перевод в сортимент"}:
        raise Oshibka(f"Не удалось отметить в «Тип документа»: {nehvataet} (стоит «{t}»).")
    log.warning("Тип документа: не удалось отметить %s, еду с тем, что есть: «%s».", nehvataet, t)
    ZAMETKI.append(f"без типа «{', '.join(nehvataet)}»")


def _otvechaet(hwnd, ms=1000):
    """Окно обрабатывает сообщения (не «Не отвечает»)."""
    rez = ctypes.c_ulong()
    return bool(ctypes.windll.user32.SendMessageTimeoutW(
        hwnd, 0, 0, 0, 0x0002, ms, ctypes.byref(rez)))  # WM_NULL, SMTO_ABORTIFHUNG


def _kursor_zanyat():
    """Курсор «песочные часы» / «стрелка с часиками» над окном ЕГАИС."""
    class CURSORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("flags", ctypes.c_uint),
                    ("hCursor", ctypes.c_void_p), ("x", ctypes.c_long), ("y", ctypes.c_long)]
    ci = CURSORINFO()
    ci.cbSize = ctypes.sizeof(CURSORINFO)
    if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci)):
        return False
    user32 = ctypes.windll.user32
    user32.LoadCursorW.restype = ctypes.c_void_p
    zanyatye = {user32.LoadCursorW(None, 32514), user32.LoadCursorW(None, 32650)}  # IDC_WAIT, IDC_APPSTARTING
    return ci.hCursor in zanyatye


def poluchit_dannye(gl, app_pid, minimum_sek, maksimum_sek):
    """Жмём «Получить» и ждём, пока ЕГАИС реально загрузит документы. На
    ПК Влада загрузка 10+ тыс. строк идёт долго, и робот жал Excel раньше —
    выходил пустой файл. Считаем, что загрузка закончилась, когда несколько
    проверок подряд (≈15 с): окно отвечает, кнопка «Получить» снова
    доступна и курсор над таблицей — не «песочные часы»."""
    from pywinauto.keyboard import send_keys
    import pywinauto.mouse as mouse

    zakryt_vsplyvashki(app_pid)
    gl.set_focus()
    knopka = next((c for c in gl.descendants() if c.class_name() == "TButton"
                   and c.window_text().startswith("Получить") and _na_ekrane(c)), None)
    if knopka is not None:
        knopka.click_input()
    else:
        send_keys("{F7}")
    log.info("Нажал «Получить», жду данные (не меньше %d с)…", minimum_sek)
    start = time.time()

    # мышь над таблицей — чтобы по курсору было видно, что ЕГАИС занят
    tabl = next((c for c in gl.descendants() if c.class_name() == "TcxGridSite" and _na_ekrane(c)), None)
    if tabl is not None:
        r = tabl.rectangle()
        mouse.move(coords=((r.left + r.right) // 2, (r.top + r.bottom) // 2))

    stabilno = 0
    while time.time() - start < maksimum_sek:
        time.sleep(3)
        # Окно-сообщение во время загрузки = ЕГАИС отказался грузить
        # (например, «Период выборки данных должен быть в пределах одного
        # календарного года»). v2.4 его не видела и ждала впустую, а потом
        # жала Excel в пустую таблицу.
        okna = vsplyvshie_okna(app_pid)
        if okna:
            for o in okna:
                zakryt_okno(o, "okno_posle_poluchit")
            o = okna[0]
            tekst = o["tekst"] or "(текст окна не прочитался — см. скрин okno_posle_poluchit в logi)"
            if "период" in tekst.lower():
                raise Oshibka(f"ЕГАИС не принял период: «{tekst}». Робот закрыл это окно.")
            raise Oshibka(f"После «Получить» ЕГАИС показал окно «{o['zagolovok']}»: {tekst}")
        try:
            gotov = (_otvechaet(gl.handle)
                     and (knopka is None or knopka.is_enabled())
                     and not _kursor_zanyat())
        except Exception:  # noqa: BLE001
            gotov = False
        stabilno = stabilno + 1 if gotov else 0
        if time.time() - start >= minimum_sek and stabilno >= 5:
            log.info("Данные загрузились за %d с.", time.time() - start)
            break
    else:
        log.warning("ЕГАИС грузит дольше %d с — пробую выгружать что есть.", maksimum_sek)
    time.sleep(2)
    zakryt_vsplyvashki(app_pid)


def najat_excel(gl):
    """Кнопка «Сформировать Excel» — последняя иконка на панели вкладки
    (TdxBarControl «MainBar», по разведке L292–R451, T75–B99). Это панель
    DevExpress, у её кнопок нет своих окон, поэтому: сначала ищем иконку
    на экране по картинке ikonka_excel.png, не нашли — жмём в последнюю
    кнопку панели по её координатам."""
    import pyautogui
    poz = None
    for kwargs in ({"confidence": 0.8}, {}):
        try:
            poz = pyautogui.locateCenterOnScreen(str(PAPKA / "ikonka_excel.png"), **kwargs)
        except Exception:  # noqa: BLE001 — не нашёл / нет opencv
            poz = None
        if poz:
            break
    if poz:
        pyautogui.click(poz)
        log.info("Нажал Excel по картинке в точке %s.", poz)
        return

    paneli = [c for c in gl.descendants() if c.class_name() == "TdxBarControl"
              and c.window_text() == "MainBar" and _na_ekrane(c)]
    if paneli:
        r = paneli[0].rectangle()
        x, y = r.right - 13, (r.top + r.bottom) // 2
        pyautogui.click(x, y)
        log.info("Нажал Excel как последнюю кнопку панели (%d, %d).", x, y)
        return
    skrin("net_knopki_excel")
    raise Oshibka("Не нашёл кнопку «Сформировать Excel» на экране.")


def dozhdatsya_excel(xl, wb, maks_sek=1200):
    """ЕГАИС заполняет книгу Excel построчно (10+ тысяч строк — это минуты),
    и если сохранить сразу, выходит пустая шапка (ПК Влада 08.10). Ждём,
    пока число строк перестанет расти три проверки подряд и Excel скажет,
    что свободен. Пока ЕГАИС пишет, Excel может отклонять наши запросы
    («вызов отклонён») — это нормально, просто пробуем ещё раз."""
    konec = time.time() + maks_sek
    proshloe, stabilno = -1, 0
    while time.time() < konec:
        time.sleep(3)
        try:
            ws = wb.Worksheets(1)
            strok = ws.UsedRange.Rows.Count
            shapka = str(ws.Cells(1, 1).Value or "")
            gotov = bool(xl.Ready)
        except Exception:  # noqa: BLE001 — Excel занят записью
            stabilno = 0
            continue
        if strok == proshloe and strok > 1 and shapka and gotov:
            stabilno += 1
            if stabilno >= 3:
                log.info("Excel: %d строк, запись закончилась.", strok)
                return
        else:
            stabilno = 0
            if strok != proshloe:
                log.info("Excel: уже %d строк…", strok)
        proshloe = strok
    raise Oshibka("ЕГАИС так и не дописал книгу Excel за 20 минут.")


def zabrat_fayl(pid, kuda, start, papki_poiska, sekund):
    """Ждём, что сделает ЕГАИС после кнопки Excel, и забираем файл:
    а) диалог «Сохранить как» — вписываем наш путь;
    б) открылся Excel с новой книгой — сохраняем её через Excel;
    в) появился новый .xlsx в одной из папок — копируем."""
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys

    kuda.parent.mkdir(parents=True, exist_ok=True)
    if kuda.exists():
        kuda.unlink()
    konec = time.time() + sekund
    while time.time() < konec:
        # а) «Сохранить как»
        for w in Desktop(backend="win32").windows(class_name="#32770", visible_only=True):
            try:
                if w.process_id() != pid:
                    continue
                edits = [c for c in w.descendants() if c.class_name() == "Edit" and c.is_visible()]
                if not edits:
                    continue
                log.info("Появился диалог «%s» — сохраняю в %s", w.window_text(), kuda)
                edits[0].set_edit_text(str(kuda))
                w.set_focus()
                send_keys("{ENTER}")
                zhdat(lambda: kuda.exists() and kuda.stat().st_size > 0, 300, chto="сохранение файла")
                time.sleep(3)  # дописывает
                return kuda
            except Oshibka:
                raise
            except Exception:  # noqa: BLE001
                pass

        # б) Excel
        try:
            import win32com.client
            xl = win32com.client.GetActiveObject("Excel.Application")
            for wb in xl.Workbooks:
                if not wb.Path:  # несохранённая книга = только что выгруженная
                    log.info("ЕГАИС открыл выгрузку прямо в Excel — жду, пока допишет строки…")
                    dozhdatsya_excel(xl, wb)
                    xl.DisplayAlerts = False
                    wb.SaveAs(str(kuda), 51)  # 51 = .xlsx
                    wb.Close(False)
                    if xl.Workbooks.Count == 0:
                        xl.Quit()
                    return kuda
        except Exception:  # noqa: BLE001
            pass

        # в) новый файл в папке
        for papka in papki_poiska:
            try:
                for f in Path(papka).glob("*.xls*"):
                    if f.stat().st_mtime >= start and not f.name.startswith("~$"):
                        time.sleep(3)
                        log.info("ЕГАИС сохранил файл сам: %s", f)
                        shutil.copy2(f, kuda)
                        return kuda
            except Exception:  # noqa: BLE001
                pass
        time.sleep(2)

    skrin("net_fayla")
    raise Oshibka("После кнопки Excel файл так и не появился.")


def proverit_fayl(put):
    import openpyxl
    wb = openpyxl.load_workbook(put, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    shapka = [str(h or "").strip() for h in next(it, [])]
    if not any("тип документа" in h.lower() for h in shapka):
        raise Oshibka(f"В файле нет колонки «Тип документа» — похоже, выгрузился не тот отчёт. "
                      f"Шапка: {shapka[:8]}")
    strok = sum(1 for r in it if any(v is not None for v in r))
    wb.close()
    return strok


# --------------------------------------------------------------------------- #
#   Лесовод
# --------------------------------------------------------------------------- #
def _http(cfg):
    """Сессия requests к Лесоводу. Caddy в локалке отдаёт https со своим
    внутренним сертификатом (tls internal), которого Python не знает. Чтобы
    не выключать проверку, доверяем ровно корневому сертификату Caddy:
    файл lesovod_root.crt рядом со скриптом (или путь в sertifikat_ca в
    [lesovod]). Без файла — сертификаты из хранилища Windows (truststore)."""
    import requests
    ses = requests.Session()
    put = cfg.get("lesovod", "sertifikat_ca", fallback="").strip()
    put = Path(os.path.expandvars(put)) if put else PAPKA / "lesovod_root.crt"
    if put.exists():
        ses.verify = str(put)
    else:
        try:
            import truststore
            truststore.inject_into_ssl()
        except Exception:  # noqa: BLE001
            pass
    return ses


def lesovod_login(cfg):
    ses = _http(cfg)
    url = cfg.get("lesovod", "url").rstrip("/")
    login = cfg.get("lesovod", "login").strip()
    r = ses.post(f"{url}/api/auth/login",
                      json={"login": login, "password": parol(KEYRING_SERVIS_LESOVOD, login)},
                      timeout=30)
    if r.status_code != 200:
        raise Oshibka(f"Лесовод не пустил ({r.status_code}): {r.text[:200]}")
    return r.json()["token"]


def zalit_v_lesovod(cfg, put):
    import requests
    url = cfg.get("lesovod", "url").rstrip("/")
    token = lesovod_login(cfg)
    ses = _http(cfg)
    h = {"Authorization": f"Bearer {token}"}
    with open(put, "rb") as f:
        r = ses.post(f"{url}/api/raskhod/egais/import", headers=h, timeout=300,
                          files={"file": (put.name, f,
                                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    if r.status_code != 200:
        raise Oshibka(f"Лесовод не принял файл ({r.status_code}): {r.text[:300]}")
    task_id = r.json()["task_id"]
    log.info("Файл принят Лесоводом, разбирается (задача %s)…", task_id)
    konec = time.time() + 1800
    while time.time() < konec:
        t = ses.get(f"{url}/api/tasks/{task_id}", headers=h, timeout=30).json()
        if t.get("status") == "done":
            try:
                ses.post(f"{url}/api/auth/logout", headers=h, timeout=10)
            except Exception:  # noqa: BLE001
                pass
            return t.get("result") or {}
        if t.get("status") == "error":
            raise Oshibka(f"Лесовод не смог разобрать файл: {t.get('error_text')}")
        time.sleep(5)
    raise Oshibka("Лесовод разбирает файл дольше 30 минут — проверь на сайте.")


def zalit_s_povtorami(cfg, put, popytok=3):
    """Лесовод мог моргнуть (перезапуск, сеть) — пробуем залить несколько раз
    с паузой. Не вышло — это уже не повод гонять ЕГАИС заново: файл лежит."""
    posl = None
    for n in range(1, popytok + 1):
        try:
            return zalit_v_lesovod(cfg, put)
        except Oshibka as e:
            posl = e
        except Exception as e:  # noqa: BLE001 — сеть, таймаут, кривой ответ
            posl = Oshibka(f"Лесовод не отвечает: {e}")
        log.warning("Заливка в Лесовод, попытка %d из %d: %s", n, popytok, posl)
        if n < popytok:
            time.sleep(60 * n)
    raise OshibkaBezPovtora(f"{posl} Файл выгружен и лежит здесь: {put}")


# --------------------------------------------------------------------------- #
#   Склады и наличие продукции (3.2): «Склад → Склады» и «Склад → Наличие
#   продукции на складах». По разведке ПК Влада 11.11.2026 (ЕГАИС 1.0.43.12):
#   формы TfrmStorages и TfrmStorageBalance, на каждой своя «Получить F7»
#   и панель MainBar с иконкой Excel.
# --------------------------------------------------------------------------- #
DOP_OTCHETY = [
    # ключ, пункт меню «Склад → …», класс формы вкладки, имя файла
    ("sklady", "Склады", "TfrmStorages", "egais_sklady"),
    ("nalichie", "Наличие продукции на складах", "TfrmStorageBalance", "egais_nalichie"),
]


def _forma(gl, klass):
    """Форма вкладки, если вкладка открыта И активна (видна)."""
    for c in gl.descendants():
        try:
            if c.class_name() == klass and c.is_visible():
                return c
        except Exception:  # noqa: BLE001
            pass
    return None


def otkryt_vkladku(gl, punkt_menyu, klass):
    """Открывает (или делает активной) вкладку из ветки меню «Склад»."""
    from pywinauto.keyboard import send_keys
    zakryt_vsplyvashki(gl.process_id())
    gl.set_focus()
    if gl.get_show_state() != 3:
        gl.maximize()
    time.sleep(1)
    f = _forma(gl, klass)
    if f is not None:
        return f
    for c in gl.descendants():
        if "treeview" not in c.class_name().lower():
            continue
        try:
            from pywinauto.controls.common_controls import TreeViewWrapper
            tv = TreeViewWrapper(c.handle)
            for koren in tv.roots():
                if koren.text().strip() != "Склад":
                    continue
                koren.expand()
                for el in koren.children():
                    if el.text().strip() == punkt_menyu:
                        el.ensure_visible()
                        el.select()
                        el.click_input(double=True)
                        time.sleep(3)
                        if _forma(gl, klass) is None:
                            send_keys("{ENTER}")
                            time.sleep(3)
                        break
        except Exception as e:  # noqa: BLE001
            log.info("Дерево не дало открыть «%s»: %s", punkt_menyu, e)
        f = _forma(gl, klass)
        if f is not None:
            return f
    skrin("menyu_" + klass)
    raise Oshibka(f"Не смог открыть «Склад → {punkt_menyu}».")


def ochistit_datu_otkrytiya(forma):
    """«Склады»: поле «Дата открытия с» должно быть ПУСТЫМ — иначе склады,
    открытые в прошлые годы (а на них лежит лес), в выборку не попадут.
    Поле — самый левый TcxDateEdit формы (правее него «по» = сегодня)."""
    import pyautogui
    from pywinauto.keyboard import send_keys
    polya = sorted((c for c in forma.descendants() if c.class_name() == "TcxDateEdit" and _na_ekrane(c)),
                   key=lambda c: c.rectangle().left)
    if len(polya) < 2:
        raise Oshibka("На вкладке «Склады» не нашёл поля «Дата открытия с … по …».")
    pole = polya[0]

    def pusto():
        return not any(ch.isdigit() for ch in pole.window_text())

    if pusto():
        return "и так пусто"
    bylo = pole.window_text().strip()
    vnutr = (pole.children() or [pole])[0]
    r = pole.rectangle()
    sposoby = [
        ("Home+Shift+End, Delete", lambda: (vnutr.click_input(), send_keys("{HOME}+{END}{DELETE}{TAB}"))),
        ("ластик в поле", lambda: pyautogui.click(r.right - 11, (r.top + r.bottom) // 2)),
        ("Delete по символам", lambda: (vnutr.click_input(), send_keys("{HOME}" + "{DELETE}" * 10 + "{TAB}"))),
    ]
    for imya, sdelat in sposoby:
        try:
            sdelat()
        except Exception as e:  # noqa: BLE001
            log.info("Очистка даты, способ «%s» не применим: %s", imya, e)
            continue
        time.sleep(0.7)
        if pusto():
            log.info("«Дата открытия с» очищена (было %s, способ: %s).", bylo, imya)
            return f"стёр {bylo}"
        log.info("Очистка даты, способ «%s» не сработал: в поле «%s».", imya, pole.window_text())
    skrin("data_otkrytiya")
    raise Oshibka(f"Не смог стереть «Дата открытия с» на вкладке «Склады» (в поле «{pole.window_text().strip()}»).")


def poluchit_na_vkladke(gl, forma, pid, minimum_sek=8, maksimum_sek=900):
    """«Получить F7» на конкретной вкладке и ожидание загрузки."""
    import pywinauto.mouse as mouse
    zakryt_vsplyvashki(pid)
    knopka = next((c for c in forma.descendants() if c.class_name() == "TButton"
                   and c.window_text().startswith("Получить") and _na_ekrane(c)), None)
    if knopka is None:
        raise Oshibka("На вкладке не нашёл кнопку «Получить».")
    knopka.click_input()
    start = time.time()
    tabl = next((c for c in forma.descendants() if c.class_name() == "TcxGridSite" and _na_ekrane(c)), None)
    if tabl is not None:
        r = tabl.rectangle()
        mouse.move(coords=((r.left + r.right) // 2, (r.top + r.bottom) // 2))
    stabilno = 0
    while time.time() - start < maksimum_sek:
        time.sleep(2)
        okna = vsplyvshie_okna(pid)
        if okna:
            for o in okna:
                zakryt_okno(o, "okno_posle_poluchit")
            o = okna[0]
            raise Oshibka(f"После «Получить» ЕГАИС показал окно «{o['zagolovok']}»: "
                          f"{o['tekst'] or '(текст не прочитался, см. скрин в logi)'}")
        try:
            gotov = _otvechaet(gl.handle) and knopka.is_enabled() and not _kursor_zanyat()
        except Exception:  # noqa: BLE001
            gotov = False
        stabilno = stabilno + 1 if gotov else 0
        if time.time() - start >= minimum_sek and stabilno >= 4:
            return int(time.time() - start)
    log.warning("ЕГАИС грузит дольше %d с — выгружаю что есть.", maksimum_sek)
    return int(time.time() - start)


def najat_excel_na_vkladke(forma):
    """Иконка Excel на панели MainBar ИМЕННО этой вкладки: ищем картинку
    только в полосе панели (на «Складах» Excel — не последняя кнопка)."""
    import pyautogui
    panel = next((c for c in forma.descendants() if c.class_name() == "TdxBarControl"
                  and c.window_text() == "MainBar" and _na_ekrane(c)), None)
    if panel is None:
        raise Oshibka("Не нашёл панель кнопок вкладки (MainBar).")
    r = panel.rectangle()
    oblast = (max(r.left - 4, 0), max(r.top - 4, 0), r.width() + 8, r.height() + 8)
    for kwargs in ({"confidence": 0.8}, {"confidence": 0.7}, {}):
        try:
            poz = pyautogui.locateCenterOnScreen(str(PAPKA / "ikonka_excel.png"), region=oblast, **kwargs)
        except Exception:  # noqa: BLE001
            poz = None
        if poz:
            pyautogui.click(poz)
            log.info("Нажал Excel по картинке в точке %s.", poz)
            return
    skrin("net_knopki_excel")
    raise Oshibka("Не нашёл иконку Excel на панели вкладки.")


def opisat_fayl(put, strok_primera=3):
    """Сколько строк в файле и что в нём за колонки (шапка + пример)."""
    import openpyxl
    wb = openpyxl.load_workbook(put, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    nachalo, strok = [], 0
    for r in ws.iter_rows(values_only=True):
        if not any(v is not None and str(v).strip() for v in r):
            continue
        strok += 1
        if len(nachalo) < 1 + strok_primera:
            nachalo.append(["" if v is None else str(v).strip() for v in r])
    wb.close()
    return max(strok - 1, 0), nachalo


def progon_sklady(cfg):
    """Выгрузка «Склады» и «Наличие продукции на складах» в папку выгрузок.
    Фильтры не трогаем — берём как ЕГАИС подставил сам (твоё подразделение,
    активные склады, наличие на сегодня)."""
    with HOD.shag("Экран Windows"):
        if ekran_zablokirovan():
            raise OshibkaBezPovtora("Экран Windows заблокирован — робот не может нажимать кнопки.")
    with HOD.shag("Вход в ЕГАИС") as sh:
        gl, sami = zapustit_i_voyti(cfg)
        sh.detal("открыл и вошёл" if sami else "ЕГАИС уже был открыт")
    pid = gl.process_id()
    ZHIZN["pidy"].add(pid)
    papka_vyg = Path(os.path.expandvars(cfg.get("obshchee", "papka_vygruzok", fallback=str(PAPKA / "vygruzki"))))
    papki_poiska = [os.path.expandvars(p.strip()) for p in cfg.get(
        "obshchee", "papki_poiska",
        fallback=r"C:\EGAIS\Temp;%USERPROFILE%\Downloads;%USERPROFILE%\Documents;%USERPROFILE%\Desktop;%TEMP%").split(";")]
    segodnya = dt.date.today()
    opisanie = [f"Робот ЕГАИС v{VERSIYA} — что лежит в выгрузках складов, {dt.datetime.now():%d.%m.%Y %H:%M}", ""]
    itogi = []
    for klyuch, punkt, klass, imya in DOP_OTCHETY:
        kuda = papka_vyg / f"{imya}_{segodnya:%Y-%m-%d}.xlsx"
        with HOD.shag(f"Вкладка «{punkt}»"):
            forma = otkryt_vkladku(gl, punkt, klass)
        if klyuch == "sklady":
            with HOD.shag("«Склады»: дата открытия пустая (все годы)") as sh:
                sh.detal(ochistit_datu_otkrytiya(forma))
        with HOD.shag(f"«{punkt}»: получить данные") as sh:
            sek = poluchit_na_vkladke(gl, forma, pid)
            sh.detal(f"загрузка {sek} с")
        with HOD.shag(f"«{punkt}»: файл Excel") as sh:
            start = time.time()
            najat_excel_na_vkladke(forma)
            zabrat_fayl(pid, kuda, start, papki_poiska, sekund=600)
            strok, nachalo = opisat_fayl(kuda)
            sh.detal(f"{strok} строк → {kuda}")
            if strok == 0:
                ZAMETKI.append(f"«{punkt}»: файл пустой")
        opisanie.append(f"=== {punkt}: {strok} строк, файл {kuda.name}")
        for i, r in enumerate(nachalo):
            opisanie.append(("КОЛОНКИ: " if i == 0 else f"строка {i}: ") + " | ".join(r))
        opisanie.append("")
        itogi.append({"klyuch": klyuch, "strok": strok, "fayl": str(kuda)})
    (PAPKA / "sklady_kolonki.txt").write_text("\n".join(opisanie), encoding="utf-8")
    log.info("Колонки выгрузок записал в sklady_kolonki.txt")
    return itogi


# --------------------------------------------------------------------------- #
#   Разведка
# --------------------------------------------------------------------------- #
def razvedka():
    gl = glavnoe_okno() or okno_vhoda()
    if not gl:
        raise Oshibka("Открой ЕГАИС (лучше сразу на вкладке «Реестр движения по складам») "
                      "и запусти разведку ещё раз.")
    gl.set_focus()
    out = PAPKA / "razvedka.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"Окно: {gl.window_text()!r} класс {gl.class_name()} {gl.rectangle()}\n")
        f.write(f"Экран: {ctypes.windll.user32.GetSystemMetrics(0)}x"
                f"{ctypes.windll.user32.GetSystemMetrics(1)}\n\n")
        for c in gl.descendants():
            try:
                f.write(f"{c.class_name():40} {c.rectangle()!s:30} {c.window_text()[:80]!r}\n")
            except Exception as e:  # noqa: BLE001
                f.write(f"?? {e}\n")
    skrin("razvedka")
    print(f"Готово: {out} — пришли этот файл и картинку из папки logi.")


# --------------------------------------------------------------------------- #
#   Основной прогон
# --------------------------------------------------------------------------- #
def sostoyanie():
    try:
        return json.loads(SOSTOYANIE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _strok_v_proshlyy_raz(st, god):
    po_godam = st.get("strok_po_godam") or {}
    if str(god) in po_godam:
        return po_godam[str(god)]
    return st.get("strok") if st.get("god") == god else None  # формат v2.4


def progon(cfg, bez_zagruzki=False):
    with HOD.shag("Экран Windows"):
        if ekran_zablokirovan():
            raise OshibkaBezPovtora("Экран Windows заблокирован — робот не может нажимать кнопки.")

    segodnya = dt.date.today()
    with HOD.shag("Вход в ЕГАИС") as sh:
        gl, zapuskali_sami = zapustit_i_voyti(cfg)
        sh.detal("открыл и вошёл" if zapuskali_sami else "ЕГАИС уже был открыт")
    pid = gl.process_id()
    ZHIZN["pidy"].add(pid)
    with HOD.shag("Вкладка «Реестр движения по складам»"):
        otkryt_reestr(gl)

    tipy = [t.strip() for t in cfg.get("egais", "tipy_dokumentov",
                                        fallback=";".join(TIPY_PO_UMOLCHANIYU)).split(";") if t.strip()]
    papka_vyg = Path(os.path.expandvars(cfg.get("obshchee", "papka_vygruzok", fallback=str(PAPKA / "vygruzki"))))
    papki_poiska = [os.path.expandvars(p.strip()) for p in cfg.get(
        "obshchee", "papki_poiska",
        fallback=r"C:\EGAIS\Temp;%USERPROFILE%\Downloads;%USERPROFILE%\Documents;%USERPROFILE%\Desktop;%TEMP%").split(";")]
    zhdat_min = cfg.getint("egais", "zhdat_dannye_sek", fallback=45)
    zalivat = not bez_zagruzki and cfg.get("lesovod", "login", fallback="").strip()

    st = sostoyanie()
    po_godam = dict(st.get("strok_po_godam") or {})
    itogi = []
    for s, po in periody(segodnya):
        metka = f"{s:%d.%m.%Y} — {po:%d.%m.%Y}"
        log.info("=== Период %s ===", metka)
        with HOD.shag("Период выборки") as sh:
            postavit_period(gl, s, po)
            sh.detal(metka)
        with HOD.shag("Тип документа") as sh:
            proverit_tipy(gl, tipy)
            sh.detal("как надо")

        imya = (f"egais_reestr_{segodnya:%Y-%m-%d}.xlsx" if po == segodnya
                else f"egais_reestr_{s.year}_ves_god.xlsx")
        kuda = papka_vyg / imya
        proshlyy = _strok_v_proshlyy_raz(st, s.year)
        strok = 0
        for popytka in (1, 2):
            with HOD.shag("Получить данные (F7)") as sh:
                t0 = time.time()
                poluchit_dannye(gl, pid, minimum_sek=zhdat_min * popytka, maksimum_sek=1200)
                sh.detal(f"загрузка {int(time.time() - t0)} с" + (", попытка 2" if popytka == 2 else ""))
            with HOD.shag("Файл Excel") as sh:
                start = time.time()
                najat_excel(gl)
                zabrat_fayl(pid, kuda, start, papki_poiska, sekund=600)
                sh.detal(str(kuda))
            with HOD.shag("Проверка файла") as sh:
                strok = proverit_fayl(kuda)
                sh.detal(f"{strok} строк" + (f" (в прошлый раз {proshlyy})" if proshlyy else ""))
                log.info("Файл %s: %d строк.", kuda.name, strok)
                if strok == 0 and popytka == 2:
                    raise Oshibka("ЕГАИС дважды отдал пустой реестр.")
            if strok > 0 and not (proshlyy and strok < proshlyy * 0.5):
                break
            log.warning("В файле %d строк (в прошлый раз %s) — видимо, ЕГАИС не успел загрузить "
                        "документы. Пробую ещё раз и жду подольше.", strok, proshlyy)

        if proshlyy and strok < proshlyy * 0.8:
            log.warning("Строк заметно меньше, чем в прошлый раз (%d → %d). "
                        "Залью всё равно — импорт ничего не удаляет, но глянь глазами.", proshlyy, strok)
            ZAMETKI.append(f"строк заметно меньше, чем в прошлый раз ({proshlyy} → {strok})")

        itog = {}
        if zalivat:
            with HOD.shag("Заливка в Лесовод") as sh:
                itog = zalit_s_povtorami(cfg, kuda)
                sh.detal(f"новых {itog.get('journal_rows_added', 0)}, "
                         f"обновлено {itog.get('journal_rows_replaced', 0)}")
            log.info("Лесовод: строк в журнале %s, новых %s, заменено %s.",
                     itog.get("journal_rows_total"), itog.get("journal_rows_added"),
                     itog.get("journal_rows_replaced"))
        else:
            HOD.shagi.append(["Заливка в Лесовод", "propusk", f"выключена — файл лежит в {kuda}"])
            log.info("Заливка в Лесовод выключена — файл лежит в %s", kuda)
        po_godam[str(s.year)] = strok
        itogi.append({"god": s.year, "period": metka, "strok": strok, **itog})

    posledniy = itogi[-1]
    SOSTOYANIE.write_text(json.dumps({
        "data": segodnya.isoformat(), "versiya": VERSIYA,
        "god": posledniy["god"], "strok": posledniy["strok"],  # как в v2.4
        "strok_po_godam": po_godam, "itogi": itogi,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # прибрать старые выгрузки
    hranit = cfg.getint("obshchee", "hranit_dney", fallback=30)
    for f in papka_vyg.glob("egais_reestr_*.xlsx"):
        if time.time() - f.stat().st_mtime > hranit * 86400:
            f.unlink(missing_ok=True)

    return itogi


# --------------------------------------------------------------------------- #
#   Расписание (Планировщик заданий Windows)
# --------------------------------------------------------------------------- #
def _zapustit(komanda, kodirovka="cp866", timeout=60, tolko_stdout=False):
    """Запустить консольную команду Windows и вернуть (код, вывод)."""
    try:
        r = subprocess.run(komanda, capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # PowerShell сыплет в stderr служебный «#< CLIXML» (прогресс загрузки
        # модулей) — для JSON его нельзя смешивать с ответом (ПК Влада 04.11)
        vyvod = (r.stdout if tolko_stdout and r.stdout.strip() else r.stdout + r.stderr).decode(
            kodirovka, errors="replace")
        return r.returncode, vyvod.strip()
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def _powershell(skript, timeout=60):
    """Скрипт PowerShell через -EncodedCommand: так кавычки внутри скрипта
    не ломаются при передаче через командную строку Windows."""
    import base64
    kod = base64.b64encode(("[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue';" + skript)
                           .encode("utf-16-le")).decode("ascii")
    return _zapustit(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                      "-EncodedCommand", kod], kodirovka="utf-8", timeout=timeout, tolko_stdout=True)


def xml_zadachi(vremya, polzovatel, bat, papka, segodnya=None):
    """XML задачи Планировщика. По сравнению с v2.4 (schtasks /sc daily /it)
    включено то, из-за чего задача молча не стартует:
      - StartWhenAvailable: ПК в 20:00 был выключен/спал — запустится, как
        только включат (раньше просто пропускал день);
      - WakeToRun: будит ПК из сна к 20:00;
      - DisallowStartIfOnBatteries/StopIfGoingOnBatteries = false: по
        умолчанию Windows НЕ запускает задачу от батареи (ноутбук, ИБП);
      - ExecutionTimeLimit 2 ч: зависший прогон снимется, и следующий не
        будет пропущен из-за «уже выполняется»;
      - InteractiveToken: робот работает на рабочем столе вошедшего
        пользователя (жмёт кнопки), без пароля Windows в задаче."""
    from xml.sax.saxutils import escape
    segodnya = segodnya or dt.date.today()
    chas, minuta = (int(x) for x in vremya.split(":"))
    nachalo = f"{segodnya:%Y-%m-%d}T{chas:02d}:{minuta:02d}:00"
    e = escape
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Робот вечерней выгрузки ЕГАИС → Лесовод (v{VERSIYA}). Итог: {e(str(REZULTAT))}</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{nachalo}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{e(polzovatel)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"{e(str(bat))}"</Command>
      <WorkingDirectory>{e(str(papka))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def sozdat_raspisanie(vremya):
    vremya = (vremya or "20:00").strip()
    try:
        chas, minuta = (int(x) for x in vremya.split(":"))
        assert 0 <= chas < 24 and 0 <= minuta < 60
    except Exception:  # noqa: BLE001
        raise Oshibka(f"Время «{vremya}» не понял — пиши как 20:00.")
    vremya = f"{chas:02d}:{minuta:02d}"
    polzovatel = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\")
    put = PAPKA / "zadacha.xml"
    put.write_text(xml_zadachi(vremya, polzovatel, PAPKA / "zapusk_po_raspisaniyu.bat", PAPKA),
                   encoding="utf-16")
    kod, vyvod = _zapustit(["schtasks", "/create", "/tn", ZADACHA, "/xml", str(put), "/f"])
    if kod != 0:
        raise Oshibka(f"Планировщик не принял задачу (код {kod}): {vyvod}\n"
                      f"Попробуй запустить raspisanie.bat правой кнопкой → «Запуск от имени администратора».")
    print(f"Задача «{ZADACHA}» создана: каждый день в {vremya}, от пользователя {polzovatel}.")
    print("  ✓ если ПК в это время выключен или спит — запустится сразу, как его включат/разбудят;")
    print("  ✓ будит ПК из сна; ✓ работает и от батареи; ✓ зависший прогон снимается через 2 часа.")
    print("  ! Windows должна быть залогинена и экран НЕ заблокирован (см. README).")
    print("Проверить всё разом: proverka.bat")


# --------------------------------------------------------------------------- #
#   «Доктор»: почему робот не запускается / не работает
# --------------------------------------------------------------------------- #
KODY_PLANIROVSHCHIKA = {
    0x0: "успешно",
    0x1: "робот закончил с ошибкой — смотри posledniy_rezultat.txt",
    0x2: "не найден файл запуска — папку робота переместили? Запусти raspisanie.bat из новой папки",
    0x41300: "готова к запуску",
    0x41301: "выполняется прямо сейчас",
    0x41302: "задача отключена",
    0x41303: "ещё ни разу не запускалась",
    0x41306: "прервана (остановили вручную или превысила лимит времени)",
    0x8004131F: "прошлый прогон ещё шёл — новый пропущен",
    0x800710E0: "Windows отказалась запускать: не выполнены условия (батарея, не вошёл пользователь…)",
    0x80070002: "не найден файл запуска — папку робота переместили? Запусти raspisanie.bat из новой папки",
    0xC000013A: "окно робота закрыли крестиком / Ctrl+C",
}


def razobrat_kod(kod):
    try:
        kod = int(kod) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return f"код {kod}"
    return f"{KODY_PLANIROVSHCHIKA.get(kod, 'неизвестный код')} (0x{kod:X})"


def _xml_nastroyki_zadachi(xml_tekst):
    import xml.etree.ElementTree as ET
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.fromstring(xml_tekst.encode("utf-16") if xml_tekst.lstrip().startswith("<?xml")
                         and "UTF-16" in xml_tekst[:100] else xml_tekst.encode("utf-8"))

    def znach(put):
        el = root.find(put, ns)
        return el.text.strip() if el is not None and el.text else None

    return {
        "batareya_zapret": znach("t:Settings/t:DisallowStartIfOnBatteries"),
        "batareya_stop": znach("t:Settings/t:StopIfGoingOnBatteries"),
        "kogda_dostupno": znach("t:Settings/t:StartWhenAvailable"),
        "budit": znach("t:Settings/t:WakeToRun"),
        "vhod": znach("t:Principals/t:Principal/t:LogonType"),
        "polzovatel": znach("t:Principals/t:Principal/t:UserId"),
        "komanda": znach("t:Actions/t:Exec/t:Command"),
        "start": znach("t:Triggers/t:CalendarTrigger/t:StartBoundary"),
        "vklyuchena": znach("t:Settings/t:Enabled"),
        "tolko_prostoy": znach("t:Settings/t:RunOnlyIfIdle"),
    }


def proverit_zadachu(punkty):
    """Задача в Планировщике: есть ли, когда запускалась, чем кончилось,
    и нет ли настроек, из-за которых Windows её молча не запускает."""
    papka_z, imya_z = ZADACHA.rsplit("\\", 1)
    skript = (f"$t=Get-ScheduledTask -TaskPath '\\{papka_z}\\' -TaskName '{imya_z}' -ErrorAction SilentlyContinue;"
              "if(-not $t){'{\"est\":false}';exit};"
              "$i=$t|Get-ScheduledTaskInfo;"
              "$f={param($d) if($d -and $d.Year -gt 2000){$d.ToString('dd.MM.yyyy HH:mm')}else{''}};"
              "[ordered]@{est=$true;sostoyanie=\"$($t.State)\";posledniy=(& $f $i.LastRunTime);"
              "kod=[int64]$i.LastTaskResult;sleduyushchiy=(& $f $i.NextRunTime);"
              "propuskov=$i.NumberOfMissedRuns;"
              f"xml=(Export-ScheduledTask -TaskPath '\\{papka_z}\\' -TaskName '{imya_z}')}}|ConvertTo-Json -Compress")
    kod, vyvod = _powershell(skript)
    try:
        # raw_decode: берём первый JSON-объект и не спотыкаемся о хвост после него
        d, _ = json.JSONDecoder().raw_decode(vyvod[vyvod.index("{"):])
    except Exception as e:  # noqa: BLE001
        punkty.append((False, "Задача в Планировщике",
                       f"не смог прочитать ({e}); PowerShell ответил: {vyvod[:200]} … {vyvod[-200:]}"))
        return
    if not d.get("est"):
        punkty.append((False, "Задача в Планировщике",
                       f"задачи «{ZADACHA}» НЕТ — поэтому робот и не запускается сам. Запусти raspisanie.bat."))
        return
    sost = d.get("sostoyanie")
    punkty.append((sost != "Disabled", "Задача в Планировщике",
                   f"есть, состояние: {sost}" + (" — ОТКЛЮЧЕНА, включи или запусти raspisanie.bat"
                                                  if sost == "Disabled" else "")))
    punkty.append((None, "Последний запуск по расписанию",
                   f"{d.get('posledniy') or 'не было'} → {razobrat_kod(d.get('kod'))}"))
    punkty.append((bool(d.get("sleduyushchiy")), "Следующий запуск",
                   d.get("sleduyushchiy") or "не запланирован!"))
    if d.get("propuskov"):
        punkty.append((False, "Пропущенные запуски",
                       f"{d['propuskov']} — в это время ПК был выключен/спал, а задача не умеет "
                       f"«догонять». Запусти raspisanie.bat (новая задача догоняет)."))
    try:
        n = _xml_nastroyki_zadachi(d.get("xml") or "")
    except Exception as e:  # noqa: BLE001
        punkty.append((None, "Настройки задачи", f"не разобрал XML: {e}"))
        return
    nado_peresozdat = False
    if n["batareya_zapret"] != "false":
        punkty.append((False, "Запуск от батареи",
                       "ЗАПРЕЩЁН (так Windows делает по умолчанию) — если ПК ноутбук или на ИБП, "
                       "в 20:00 задача молча не стартует."))
        nado_peresozdat = True
    if n["kogda_dostupno"] != "true":
        punkty.append((False, "Догонять пропущенный запуск",
                       "выключено — если в 20:00 ПК выключен или спит, день просто пропадает."))
        nado_peresozdat = True
    if n["budit"] != "true":
        punkty.append((None, "Будить ПК из сна", "выключено"))
        nado_peresozdat = True
    if n["vhod"] and n["vhod"] != "InteractiveToken":
        punkty.append((False, "Режим входа",
                       f"{n['vhod']} — робот запустится без рабочего стола и не сможет жать кнопки. "
                       f"Нужно «только для вошедшего пользователя»."))
        nado_peresozdat = True
    if n["polzovatel"]:
        tek = os.environ.get("USERNAME", "")
        ok = tek.lower() in n["polzovatel"].lower()
        punkty.append((ok, "Пользователь задачи", n["polzovatel"] + ("" if ok else
                       f" — а сейчас ты вошёл как {tek}: задача ждёт входа ДРУГОГО пользователя!")))
        nado_peresozdat |= not ok
    if n["komanda"]:
        put = n["komanda"].strip('"')
        est = Path(os.path.expandvars(put)).exists()
        punkty.append((est, "Файл запуска", put + ("" if est else " — ТАКОГО ФАЙЛА НЕТ (папку переместили?)")))
        nado_peresozdat |= not est
    if nado_peresozdat:
        punkty.append((False, "Совет", "запусти raspisanie.bat — он пересоздаст задачу с правильными настройками."))

    # журнал Планировщика (по умолчанию в Windows часто выключен)
    kod, vyvod = _powershell(
        "Get-WinEvent -LogName 'Microsoft-Windows-TaskScheduler/Operational' -MaxEvents 2000 "
        f"-ErrorAction SilentlyContinue | Where-Object {{$_.Message -like '*{imya_z}*'}} | "
        "Select-Object -First 8 | ForEach-Object { $_.TimeCreated.ToString('dd.MM HH:mm') + '  ' + "
        "($_.Message -split [char]10)[0] }", timeout=90)
    if vyvod.strip():
        punkty.append((None, "Журнал Планировщика (последние события)", "\n      " + vyvod.replace("\n", "\n      ")))
    else:
        punkty.append((None, "Журнал Планировщика",
                       "пуст или выключен (Планировщик заданий → справа «Включить журнал всех заданий»)."))


def proverit_son_i_ekran(punkty):
    kod, vyvod = _zapustit(["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"])
    import re
    hexy = re.findall(r":\s*(0x[0-9a-fA-F]+)\s*$", vyvod, flags=re.M)
    if len(hexy) >= 2:
        ot_seti, ot_batarei = (int(x, 16) for x in hexy[-2:])
        if ot_seti == 0:
            punkty.append((True, "Сон ПК (от сети)", "никогда — хорошо"))
        else:
            punkty.append((None, "Сон ПК (от сети)",
                           f"через {ot_seti // 60} мин простоя. Задача теперь будит ПК, но после сна "
                           f"Windows может спросить пароль — тогда робот не сможет работать. "
                           f"Надёжнее: Электропитание → «Переводить в спящий режим»: Никогда."))
    else:
        punkty.append((None, "Сон ПК", "не смог узнать (powercfg)"))
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as k:
            def rv(n):
                try:
                    return str(winreg.QueryValueEx(k, n)[0])
                except OSError:
                    return ""
            if rv("ScreenSaveActive") == "1" and rv("ScreenSaverIsSecure") == "1":
                punkty.append((False, "Заставка с паролем",
                               f"включена (через {int(rv('ScreenSaveTimeOut') or 0) // 60} мин) — к 20:00 экран "
                               f"будет заблокирован. Сними «Начинать с экрана входа в систему»."))
            else:
                punkty.append((True, "Заставка с паролем", "нет — хорошо"))
    except Exception as e:  # noqa: BLE001
        punkty.append((None, "Заставка", f"не смог проверить: {e}"))
    zabl = ekran_zablokirovan()
    punkty.append((not zabl, "Экран сейчас", "заблокирован" if zabl else "открыт"))


def proverit_ostalnoe(cfg, punkty):
    put = os.path.expandvars(cfg.get("egais", "yarlyk", fallback=r"%USERPROFILE%\Desktop\EGAIS.lnk"))
    punkty.append((Path(put).exists(), "Ярлык ЕГАИС", put + ("" if Path(put).exists() else " — НЕ НАЙДЕН")))
    try:
        import keyring
        ok = bool(keyring.get_password(KEYRING_SERVIS_EGAIS, egais_klyuch(cfg)))
        punkty.append((ok, "Пароль ЕГАИС", "сохранён" if ok else "НЕ сохранён — nastroit.bat"))
    except Exception as e:  # noqa: BLE001
        punkty.append((False, "Пароль ЕГАИС", f"не проверить: {e}"))
    if cfg.get("lesovod", "login", fallback="").strip():
        try:
            lesovod_login(cfg)
            punkty.append((True, "Лесовод", f"{cfg.get('lesovod', 'url')} — вход проверен"))
        except Exception as e:  # noqa: BLE001
            punkty.append((False, "Лесовод", f"{cfg.get('lesovod', 'url')} — {e}"))
    else:
        punkty.append((None, "Лесовод", "логин не указан — робот только скачивает файл"))


def _hvost(put, n):
    try:
        return put.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:  # noqa: BLE001
        return []


def doktor(cfg):
    punkty = [(None, "Робот", f"v{VERSIYA}, папка {PAPKA}, Python {sys.version.split()[0]}")]
    for f in (proverit_zadachu, proverit_son_i_ekran):
        try:
            f(punkty)
        except Exception as e:  # noqa: BLE001
            punkty.append((None, f.__name__, f"проверка упала: {e}"))
    if cfg is not None:
        proverit_ostalnoe(cfg, punkty)

    znak = {True: "✓", False: "✗", None: "·"}
    stroki = [f"ПРОВЕРКА РОБОТА ЕГАИС — {dt.datetime.now():%d.%m.%Y %H:%M}", ""]
    stroki += [f"  {znak[ok]} {nazv}: {detal}" for ok, nazv, detal in punkty]
    problem = sum(1 for ok, *_ in punkty if ok is False)
    stroki += ["", f"Проблем: {problem}" + (" — всё в порядке." if not problem else " (строки с ✗)."), ""]
    stroki.append("Когда Планировщик звал робота (logi\\zapuski.log):")
    stroki += ["  " + x for x in _hvost(PAPKA / "logi" / "zapuski.log", 8)] or ["  ни разу (файла нет)"]
    stroki.append("")
    stroki.append("Последние прогоны (logi\\istoriya.txt):")
    stroki += ["  " + x for x in _hvost(ISTORIYA, 8)] or ["  пока нет"]
    stroki.append("")
    stroki.append("Последний итог (posledniy_rezultat.txt):")
    stroki += ["  " + x for x in _hvost(REZULTAT, 30)] or ["  пока нет"]
    tekst = "\n".join(stroki) + "\n"
    (PAPKA / "proverka.txt").write_text(tekst, encoding="utf-8")
    print(tekst)
    print(f"Сохранено в {PAPKA / 'proverka.txt'} — можно прислать этот файл.")


# --------------------------------------------------------------------------- #
#   Предупреждение перед запуском по расписанию
# --------------------------------------------------------------------------- #
def preduprezhdenie(sekund=30):
    """Окошко «Через 30 с робот начнёт выгрузку ЕГАИС» — чтобы не
    перехватил мышь у человека, который в это время работает за ПК.
    Никто не нажал — робот стартует сам. Возвращает "start" или "propusk"."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:  # noqa: BLE001
        return "start"
    rez = {"v": "start"}
    try:
        root = tk.Tk()
        root.title("Робот ЕГАИС")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        fr = ttk.Frame(root, padding=18)
        fr.grid()
        ttk.Label(fr, text="🤖 Робот начинает вечернюю выгрузку ЕГАИС → Лесовод",
                  font=("Segoe UI", 11, "bold")).grid(columnspan=2, sticky="w")
        ttk.Label(fr, text="Минут 5–15 он будет сам двигать мышь и жать кнопки —\n"
                           "в это время не трогай мышь и клавиатуру.").grid(columnspan=2, sticky="w", pady=(6, 10))
        ostalos = tk.IntVar(value=sekund)
        lbl = ttk.Label(fr, text="")
        lbl.grid(columnspan=2, sticky="w", pady=(0, 10))

        def vybor(v):
            rez["v"] = v
            root.destroy()

        ttk.Button(fr, text="Начать сейчас", command=lambda: vybor("start")).grid(row=3, column=0, sticky="we")
        ttk.Button(fr, text="Пропустить сегодня", command=lambda: vybor("propusk")).grid(
            row=3, column=1, sticky="we", padx=(8, 0))

        def tik():
            v = ostalos.get()
            if v <= 0:
                vybor("start")
                return
            lbl.config(text=f"Старт через {v} с…")
            ostalos.set(v - 1)
            root.after(1000, tik)

        tik()
        root.mainloop()
    except Exception:  # noqa: BLE001 — нет рабочего стола и т.п.
        return "start"
    return rez["v"]


# --------------------------------------------------------------------------- #
#   Один робот за раз
# --------------------------------------------------------------------------- #
_ZAMOK = None


def vzyat_zamok():
    """Не даём запуститься второму роботу, пока идёт первый (ручной прогон
    + расписание одновременно передрались бы за мышь)."""
    global _ZAMOK
    try:
        import msvcrt
        f = open(PAPKA / "robot.lock", "a+")
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        _ZAMOK = f
        return True
    except ImportError:
        return True
    except OSError:
        return False


def soobshchit_v_lesovod(cfg, ok, tekst):
    """Итог прогона — в колокольчик Лесовода (POST /api/raskhod/egais/robot-otchet).
    Best effort: если Лесовод недоступен (или старая версия сервера без
    этого адреса), просто пишем в лог — выгрузка от этого не ломается."""
    if cfg is None or not cfg.get("lesovod", "login", fallback="").strip():
        return
    try:
        url = cfg.get("lesovod", "url").rstrip("/")
        ses = _http(cfg)
        h = {"Authorization": f"Bearer {lesovod_login(cfg)}"}
        r = ses.post(f"{url}/api/raskhod/egais/robot-otchet", headers=h, timeout=30,
                     json={"ok": ok, "text": tekst})
        if r.status_code == 404:
            log.info("Сервер Лесовода ещё без колокольчика для робота (нужно обновление сервера).")
        elif r.status_code != 200:
            log.warning("Колокольчик Лесовода не принял итог (%s): %s", r.status_code, r.text[:200])
        else:
            log.info("Итог отправлен в колокольчик Лесовода.")
        try:
            ses.post(f"{url}/api/auth/logout", headers=h, timeout=10)
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        log.warning("Не смог отправить итог в Лесовод: %s", e)


def _tekst_uspeha(itogi):
    chasti = []
    for it in itogi:
        ch = f"{it['strok']} строк"
        if "journal_rows_added" in it:
            ch += f", новых в журнале {it.get('journal_rows_added', 0)}, обновлено {it.get('journal_rows_replaced', 0)}"
        if len(itogi) > 1:
            ch = f"{it['god']}: " + ch
        chasti.append(ch)
    return f"Выгрузка ЕГАИС {dt.date.today():%d.%m}: " + "; ".join(chasti) + "."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nastroit", action="store_true")
    ap.add_argument("--razvedka", action="store_true")
    ap.add_argument("--bez-zagruzki", action="store_true")
    ap.add_argument("--sklady", action="store_true",
                    help="выгрузить «Склады» и «Наличие продукции на складах» в папку выгрузок")
    ap.add_argument("--proverka", action="store_true", help="проверить расписание, сон, экран, пароли")
    ap.add_argument("--raspisanie", nargs="?", const="20:00", metavar="ЧЧ:ММ",
                    help="(пере)создать задачу Планировщика")
    ap.add_argument("--po-raspisaniyu", action="store_true", help="так зовёт Планировщик")
    a = ap.parse_args()

    for potok in (sys.stdout, sys.stderr):  # ✓ ✗ и эмодзи в консоли/файле
        try:
            potok.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    (PAPKA / "logi").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(PAPKA / "logi" / f"{dt.date.today():%Y-%m}.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)])

    cfg = None
    try:
        if a.razvedka:
            razvedka()
            return 0
        if a.raspisanie:
            sozdat_raspisanie(a.raspisanie)
            return 0
        if a.proverka:
            try:
                cfg = zagruzit_nastroyki()
            except Oshibka as e:
                print(f"✗ {e}")
            doktor(cfg)
            return 0
        cfg = zagruzit_nastroyki()
        if a.nastroit:
            nastroit(cfg)
            return 0
    except Oshibka as e:
        log.error("ОШИБКА: %s", e)
        return 1

    rezhim = "по расписанию" if a.po_raspisaniyu else "запуск вручную"
    if not vzyat_zamok():
        log.warning("Робот уже работает (другой прогон не закончился) — этот запуск пропускаю.")
        zapisat_istoriyu(True, "пропуск: предыдущий прогон ещё идёт")
        return 0
    log.info("=== Выгрузка ЕГАИС v%s: старт (%s) ===", VERSIYA, rezhim)

    if a.po_raspisaniyu and cfg.getint("obshchee", "preduprezhdat_sek", fallback=30) > 0:
        if preduprezhdenie(cfg.getint("obshchee", "preduprezhdat_sek", fallback=30)) == "propusk":
            log.info("Человек нажал «Пропустить сегодня».")
            REZULTAT.write_text(f"Робот ЕГАИС v{VERSIYA} — {dt.datetime.now():%d.%m.%Y %H:%M}\n"
                                f"ИТОГ: ⏭ пропущено — нажали «Пропустить сегодня».\n", encoding="utf-8")
            zapisat_istoriyu(True, "пропущено кнопкой «Пропустить сегодня»")
            soobshchit_v_lesovod(cfg, True, f"⏭ Выгрузка ЕГАИС {dt.date.today():%d.%m} пропущена "
                                            f"вручную (кнопка «Пропустить сегодня»).")
            return 0

    global HOD
    zagruzit_pravila_okon(cfg)
    popytok = max(1, cfg.getint("obshchee", "popytok", fallback=3))
    zakryvat = cfg.getboolean("egais", "zakryvat_posle", fallback=True)
    ok, tekst, proshlye = False, "", []
    for popytka in range(1, popytok + 1):
        if popytka > 1:
            HOD = Hod()
            log.info("=== Попытка %d из %d: начинаю с чистого листа ===", popytka, popytok)
        povtoryat = True
        try:
            if a.sklady:
                itogi = progon_sklady(cfg)
                tekst = "Склады ЕГАИС выгружены: " + "; ".join(
                    f"{Path(i['fayl']).name} — {i['strok']} строк" for i in itogi) + ". Колонки — в sklady_kolonki.txt."
            else:
                itogi = progon(cfg, bez_zagruzki=a.bez_zagruzki)
                tekst = _tekst_uspeha(itogi)
            ok = True
            if ZAMETKI:
                tekst += " " + "; ".join(dict.fromkeys(ZAMETKI)) + "."
            if popytka > 1:
                tekst += f" Получилось с попытки {popytka} (до этого: {'; '.join(proshlye)})."
            log.info("=== Выгрузка ЕГАИС: готово ===")
        except OshibkaBezPovtora as e:
            log.error("ОШИБКА: %s", e)
            tekst, povtoryat = str(e), False
        except Oshibka as e:
            log.error("ОШИБКА: %s", e)
            tekst = str(e)
        except Exception:  # noqa: BLE001
            log.error("Непредвиденная ошибка:\n%s", traceback.format_exc())
            tekst = "непредвиденная ошибка, подробности в логе"
            skrin("nepredvidennaya")
        if ok:
            break
        # что было на экране в момент падения — в лог и в отчёт
        try:
            okna = opisat_okna()
        except Exception:  # noqa: BLE001
            okna = []
        if okna:
            skrin("okna_pri_oshibke")
            log.warning("На экране у ЕГАИС: %s", " | ".join(okna))
            tekst += " На экране было: " + " | ".join(okna)[:600] + "."
        proshlye.append(f"попытка {popytka} — шаг «{HOD.gde_upal() or '?'}»")
        if not povtoryat or popytka == popytok:
            break
        # заново: ЕГАИС закрываем целиком (и зависший, и «уже открытый») и стартуем с нуля
        zakryt_egais("перезапуск после ошибки")
        ZHIZN["sami"] = True
        time.sleep(15 * popytka)

    # ЕГАИС после робота не должен оставаться висеть: закрываем, если робот
    # открывал его сам (в том числе после перезапуска) — и при успехе, и при ошибке
    if ZHIZN["sami"] and zakryvat:
        try:
            if not zakryt_egais("конец прогона"):
                ZAMETKI.append("ЕГАИС не удалось закрыть")
                tekst += " ЕГАИС не удалось закрыть — закрой руками."
        except Exception as e:  # noqa: BLE001
            log.warning("Закрытие ЕГАИС: %s", e)
    if not ok and len(proshlye) > 1:
        tekst += f" Пробовал {len(proshlye)} раза: {'; '.join(proshlye)}."

    otchet = HOD.otchet(ok, tekst, rezhim)
    REZULTAT.write_text(otchet, encoding="utf-8")
    log.info("Итог:\n%s", otchet)
    upal = HOD.gde_upal()
    zapisat_istoriyu(ok, tekst if ok else f"шаг «{upal or '?'}»: {tekst}")
    if not a.bez_zagruzki and not a.sklady:
        if ok:
            soobshchit_v_lesovod(cfg, True, tekst)
        else:
            shag = f" на шаге «{upal}»" if upal else ""
            soobshchit_v_lesovod(cfg, False, f"Выгрузка ЕГАИС {dt.date.today():%d.%m} не удалась{shag}: {tekst}"
                                             f" Подробно — posledniy_rezultat.txt на ПК робота.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
