@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Так робота зовёт Планировщик заданий. Каждый вызов отмечается в
rem logi\zapuski.log ещё ДО Python: если строки за день нет — Планировщик
rem робота вообще не запускал (смотри proverka.bat).
set PYTHONIOENCODING=utf-8
if not exist logi mkdir logi
echo %date% %time:~0,8%  Планировщик запустил робота >> logi\zapuski.log
if not exist venv\Scripts\python.exe (
  echo %date% %time:~0,8%  ОШИБКА: нет venv\Scripts\python.exe - запусти ustanovit.bat >> logi\zapuski.log
  echo %date% %time:~0,8% - ОШИБКА: нет Python-окружения робота, запусти ustanovit.bat > posledniy_rezultat.txt
  exit /b 2
)
venv\Scripts\python egais_avto.py --po-raspisaniyu > logi\konsol_poslednego_zapuska.txt 2>&1
set KOD=%errorlevel%
echo %date% %time:~0,8%  робот закончил, код %KOD% (0 = ок, 1 = ошибка - см. posledniy_rezultat.txt) >> logi\zapuski.log
exit /b %KOD%
