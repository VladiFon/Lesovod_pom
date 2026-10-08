# -*- coding: utf-8 -*-
"""Робот вечерней выгрузки ЕГАИС → Лесовод.

Делает ровно то, что человек делает руками в программе ЕГАИС
(egais.belgosles.by, десктоп-клиент 1.0.x):

  1. запускает ЕГАИС (или берёт уже открытое окно) и входит по паролю;
  2. открывает «Склад → Реестр движения по складам»;
  3. ставит период «с 01.01 текущего года по сегодня»;
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
import sys
import time
import traceback
from pathlib import Path

PAPKA = Path(__file__).resolve().parent
NASTROYKI = PAPKA / "nastroyki.ini"
SOSTOYANIE = PAPKA / "sostoyanie.json"
KEYRING_SERVIS_EGAIS = "Lesovod-EGAIS"
KEYRING_SERVIS_LESOVOD = "Lesovod-site"

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


class Oshibka(Exception):
    """Понятная человеку ошибка — пишется в лог без трейсбэка."""


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


def soobshcheniya_oshibok(pid):
    """Тексты всплывших окошек-сообщений (#32770) самого ЕГАИС."""
    from pywinauto import Desktop
    teksty = []
    for w in Desktop(backend="win32").windows(class_name="#32770", visible_only=True):
        try:
            if w.process_id() != pid:
                continue
            t = " ".join(c.window_text() for c in w.children() if c.window_text())
            teksty.append(f"[{w.window_text()}] {t}")
        except Exception:  # noqa: BLE001
            pass
    return teksty


# Кнопки, которыми закрываются информационные окошки ЕГАИС при запуске
# («ВНИМАНИЕ! … заканчивается срок вывозки» → «Ознакомлен» и т.п.).
KNOPKI_OK = ("ознакомлен", "ok", "ок", "закрыть", "продолжить", "понятно")


def zakryt_vsplyvashki(pid, zhdat_sek=0):
    """Закрывает всплывающие окна-предупреждения ЕГАИС, чтобы они не
    перекрывали работу. Перед закрытием снимает скрин — там бывает полезное
    (например, у какого разрешительного документа кончается срок вывозки),
    и пишет текст окна в лог. zhdat_sek — сколько ещё секунд ловить
    окошки, которые вылезают с задержкой (после входа)."""
    from pywinauto import Desktop

    zakryto = 0
    konec = time.time() + zhdat_sek
    while True:
        gl = glavnoe_okno()
        for w in Desktop(backend="win32").windows(visible_only=True):
            try:
                if w.process_id() != pid or (gl is not None and w.handle == gl.handle):
                    continue
                if w.window_text().startswith("ЕГАИС"):
                    continue  # окно входа/главное — не трогаем
                knopka = None
                for c in w.descendants():
                    if c.window_text().strip().lower() in KNOPKI_OK and "button" in c.class_name().lower():
                        knopka = c
                        break
                if knopka is None:
                    continue
                tekst = " | ".join(t for t in (c.window_text().strip() for c in w.descendants()) if t)
                log.warning("ЕГАИС показал окно «%s»: %s", w.window_text(), tekst[:500])
                w.set_focus()
                skrin("preduprezhdenie_egais")
                try:
                    knopka.click()
                except Exception:  # noqa: BLE001
                    knopka.click_input()
                time.sleep(1)
                if okno_zhivo(w):
                    from pywinauto.keyboard import send_keys
                    w.set_focus()
                    send_keys("{ENTER}")  # кнопка и так в фокусе
                    time.sleep(1)
                zakryto += 1
            except Exception:  # noqa: BLE001
                pass
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
        log.info("ЕГАИС уже открыт и вход выполнен — беру готовое окно.")
        zakryt_vsplyvashki(gl.process_id())
        return gl, False

    vh = okno_vhoda()
    if not vh:
        put = os.path.expandvars(cfg.get("egais", "yarlyk",
                                         fallback=r"%USERPROFILE%\Desktop\EGAIS.lnk"))
        if not Path(put).exists():
            raise Oshibka(f"Не нашёл ярлык/программу ЕГАИС: {put} (поправь yarlyk в nastroyki.ini)")
        log.info("Запускаю ЕГАИС: %s", put)
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
        raise Oshibka("Вход в ЕГАИС не удался. " + ("; ".join(oshibki) or "Окно не появилось."))
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


def postavit_period(gl, s, po):
    """«Операции за период с … по …» — два TcxDateEdit в одной строке,
    самой верхней среди видимых полей дат (по разведке: L497 и L673, T127)."""
    from pywinauto.keyboard import send_keys

    daty = [c for c in gl.descendants()
            if c.class_name() == "TcxDateEdit" and _na_ekrane(c)]
    if len(daty) >= 2:
        verh = min(c.rectangle().top for c in daty)
        stroka = sorted((c for c in daty if abs(c.rectangle().top - verh) < 8),
                        key=lambda c: c.rectangle().left)
        if len(stroka) >= 2:
            for pole, data in ((stroka[0], s), (stroka[1], po)):
                vvesti_datu(pole, data.strftime("%d.%m.%Y"))
            log.info("Период: %s — %s", s.strftime("%d.%m.%Y"), po.strftime("%d.%m.%Y"))
            return
    # Запасной путь: после открытия вкладки курсор стоит в «с» и дата
    # выделена — печатаем поверх. «по» по умолчанию = сегодня.
    log.info("Поля дат не нашлись — печатаю в активное поле «с».")
    send_keys("^a" + s.strftime("%d.%m.%Y") + "{TAB}")


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
        mouse.click(coords=(r.right - 10, (r.top + r.bottom) // 2))
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
        mouse.click(coords=(r.right + 13, (r.top + r.bottom) // 2))
        time.sleep(0.5)
        est = set()

    for prohod, sposob in enumerate(("клавиатура", "мышь", "мышь")):
        t = tekst()
        est, neznakomye = _indeksy_tipov(t)
        perekl = sorted(est ^ nuzhno)
        if not perekl and not neznakomye:
            log.info("Тип документа как надо: %s", t)
            return
        log.info("Тип документа «%s» — переключаю пункты %s (%s).", t, perekl, sposob)
        sp = otkryt()
        if sposob == "клавиатура":
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
    log.warning("Тип документа: не удалось отметить %s, еду с тем, что есть: «%s».", nehvataet, t)


def poluchit_dannye(gl, app_pid, minimum_sek, maksimum_sek):
    from pywinauto.keyboard import send_keys
    from pywinauto import Application

    zakryt_vsplyvashki(app_pid)
    gl.set_focus()
    knopka = next((c for c in gl.descendants() if c.class_name() == "TButton"
                   and c.window_text().startswith("Получить") and _na_ekrane(c)), None)
    if knopka is not None:
        knopka.click_input()
    else:
        send_keys("{F7}")
    log.info("Нажал «Получить», жду данные…")
    time.sleep(minimum_sek)
    # Пока ЕГАИС тянет 10+ тысяч строк, он грузит процессор — ждём, когда
    # успокоится. Сверху всё равно страхует проверка самого файла.
    try:
        app = Application(backend="win32").connect(process=app_pid)
        app.wait_cpu_usage_lower(threshold=3, timeout=maksimum_sek, usage_interval=2)
    except Exception as e:  # noqa: BLE001
        log.info("Не дождался тишины по процессору (%s) — иду дальше.", e)
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


def progon(cfg, bez_zagruzki=False):
    if ekran_zablokirovan():
        raise Oshibka("Экран Windows заблокирован — робот не может нажимать кнопки. "
                      "Отключи блокировку/заставку с паролем на этом ПК (см. README).")

    segodnya = dt.date.today()
    s = dt.date(segodnya.year, 1, 1)
    if segodnya.month == 1:  # в январе ещё правят прошлый год — берём и его
        s = dt.date(segodnya.year - 1, 1, 1)

    gl, zapuskali_sami = zapustit_i_voyti(cfg)
    pid = gl.process_id()
    otkryt_reestr(gl)
    postavit_period(gl, s, segodnya)
    tipy = [t.strip() for t in cfg.get("egais", "tipy_dokumentov",
                                        fallback=";".join(TIPY_PO_UMOLCHANIYU)).split(";") if t.strip()]
    proverit_tipy(gl, tipy)

    papka_vyg = Path(os.path.expandvars(cfg.get("obshchee", "papka_vygruzok", fallback=str(PAPKA / "vygruzki"))))
    kuda = papka_vyg / f"egais_reestr_{segodnya:%Y-%m-%d}.xlsx"
    papki_poiska = [os.path.expandvars(p.strip()) for p in cfg.get(
        "obshchee", "papki_poiska",
        fallback=r"%USERPROFILE%\Downloads;%USERPROFILE%\Documents;%USERPROFILE%\Desktop;%TEMP%").split(";")]

    strok = 0
    for popytka in (1, 2):
        poluchit_dannye(gl, pid, minimum_sek=15 * popytka, maksimum_sek=600)
        start = time.time()
        najat_excel(gl)
        zabrat_fayl(pid, kuda, start, papki_poiska, sekund=600)
        strok = proverit_fayl(kuda)
        log.info("Файл %s: %d строк.", kuda.name, strok)
        if strok > 0:
            break
        log.warning("Файл пустой — видимо, данные не успели загрузиться. Пробую ещё раз подольше.")
    if strok == 0:
        raise Oshibka("ЕГАИС дважды отдал пустой реестр.")

    st = sostoyanie()
    vchera = st.get("strok")
    if vchera and st.get("god") == s.year and strok < vchera * 0.8:
        log.warning("Строк стало заметно меньше, чем в прошлый раз (%d → %d). "
                    "Залью всё равно — импорт ничего не удаляет, но глянь глазами.", vchera, strok)

    itog = {}
    if not bez_zagruzki and cfg.get("lesovod", "login", fallback="").strip():
        itog = zalit_v_lesovod(cfg, kuda)
        log.info("Лесовод: строк в журнале %s, новых %s, заменено %s.",
                 itog.get("journal_rows_total"), itog.get("journal_rows_added"),
                 itog.get("journal_rows_replaced"))
    else:
        log.info("Заливка в Лесовод выключена — файл лежит в %s", kuda)

    SOSTOYANIE.write_text(json.dumps({"data": segodnya.isoformat(), "god": s.year, "strok": strok,
                                      "lesovod": itog}, ensure_ascii=False, indent=1), encoding="utf-8")

    # прибрать старые выгрузки
    hranit = cfg.getint("obshchee", "hranit_dney", fallback=30)
    for f in papka_vyg.glob("egais_reestr_*.xlsx"):
        if time.time() - f.stat().st_mtime > hranit * 86400:
            f.unlink(missing_ok=True)

    if zapuskali_sami and cfg.getboolean("egais", "zakryvat_posle", fallback=True):
        try:
            gl.close()
        except Exception:  # noqa: BLE001
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nastroit", action="store_true")
    ap.add_argument("--razvedka", action="store_true")
    ap.add_argument("--bez-zagruzki", action="store_true")
    a = ap.parse_args()

    (PAPKA / "logi").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(PAPKA / "logi" / f"{dt.date.today():%Y-%m}.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)])
    try:
        if a.razvedka:
            razvedka()
            return 0
        cfg = zagruzit_nastroyki()
        if a.nastroit:
            nastroit(cfg)
            return 0
        log.info("=== Выгрузка ЕГАИС: старт ===")
        progon(cfg, bez_zagruzki=a.bez_zagruzki)
        log.info("=== Выгрузка ЕГАИС: готово ===")
        (PAPKA / "posledniy_rezultat.txt").write_text(
            f"{dt.datetime.now():%d.%m.%Y %H:%M} — OK\n", encoding="utf-8")
        return 0
    except Oshibka as e:
        log.error("ОШИБКА: %s", e)
        tekst = str(e)
    except Exception:  # noqa: BLE001
        log.error("Непредвиденная ошибка:\n%s", traceback.format_exc())
        tekst = "непредвиденная ошибка, см. лог"
    (PAPKA / "posledniy_rezultat.txt").write_text(
        f"{dt.datetime.now():%d.%m.%Y %H:%M} — ОШИБКА: {tekst}\n", encoding="utf-8")
    return 1


if __name__ == "__main__":
    sys.exit(main())
