@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Установка робота выгрузки ЕГАИС ===
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Не найден Python. Поставь Python 3.11+ с python.org,
  echo при установке отметь галочку "Add python.exe to PATH", и запусти меня снова.
  pause
  exit /b 1
)

if not exist venv (
  echo Создаю отдельное окружение venv...
  %PY% -m venv venv || (echo Не получилось создать venv & pause & exit /b 1)
)
echo Ставлю библиотеки...
venv\Scripts\python -m pip install --upgrade pip >nul
venv\Scripts\python -m pip install -r requirements.txt || (echo Ошибка установки библиотек & pause & exit /b 1)

if not exist nastroyki.ini copy nastroyki.primer.ini nastroyki.ini >nul

echo.
echo Сейчас откроется nastroyki.ini - впиши логин ЕГАИС и логин Лесовода, сохрани и закрой.
notepad nastroyki.ini

echo.
echo Сохраняю пароли в Диспетчер учётных данных Windows...
venv\Scripts\python egais_avto.py --nastroit || (pause & exit /b 1)

echo.
set "VREMYA=20:00"
set /p "VREMYA=Во сколько запускать каждый день? [Enter = 20:00]: "
schtasks /create /tn "Lesovod\Vygruzka EGAIS" /tr "\"%~dp0zapusk_po_raspisaniyu.bat\"" /sc daily /st %VREMYA% /it /f
if errorlevel 1 (
  echo Не получилось создать задачу. Запусти ustanovit.bat правой кнопкой "от имени администратора".
) else (
  echo Задача создана: каждый день в %VREMYA%. Видно в "Планировщик заданий" - папка Lesovod.
)
echo.
echo Теперь сделай пробный прогон: zapustit_seychas.bat
pause
