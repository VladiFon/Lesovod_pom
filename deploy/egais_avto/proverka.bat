@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Проверяю расписание, сон, экран, пароли и связь с Лесоводом (до минуты)...
echo.
venv\Scripts\python egais_avto.py --proverka
echo.
echo Если что-то непонятно - пришли файл proverka.txt из этой папки.
pause
