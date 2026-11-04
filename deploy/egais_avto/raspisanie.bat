@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Расписание робота ЕГАИС ===
echo Пересоздаю задачу в Планировщике с правильными настройками
echo (догоняет пропущенный запуск, будит ПК, работает от батареи).
echo.
set "VREMYA=20:00"
set /p "VREMYA=Во сколько запускать каждый день? [Enter = 20:00]: "
venv\Scripts\python egais_avto.py --raspisanie %VREMYA%
echo.
pause
