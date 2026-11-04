@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Открой ЕГАИС на вкладке "Реестр движения по складам", потом нажми любую клавишу.
pause >nul
venv\Scripts\python egais_avto.py --razvedka
pause
