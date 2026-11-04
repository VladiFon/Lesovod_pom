@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Пробный прогон. Не трогай мышь и клавиатуру, пока робот работает.
echo.
venv\Scripts\python egais_avto.py %*
echo.
type posledniy_rezultat.txt
pause
