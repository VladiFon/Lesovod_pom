@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo Выгрузка «Склады» и «Наличие продукции на складах» из ЕГАИС.
echo Не трогай мышь и клавиатуру, пока робот работает.
echo.
venv\Scripts\python egais_avto.py --sklady
echo.
type posledniy_rezultat.txt
echo.
if exist sklady_kolonki.txt type sklady_kolonki.txt
pause
