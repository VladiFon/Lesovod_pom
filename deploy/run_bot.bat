@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "ENV_FILE=%SCRIPT_DIR%.env"
set "BACKEND_DIR=C:\lesovod\backend"
set "VENV_PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"
set "BOT_SCRIPT=%BACKEND_DIR%\legacy\telegram_bot.py"

if not exist "%ENV_FILE%" goto NOENV

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if not "%%A"=="" (
        set "%%A=%%B"
        echo [run_bot] %%A zadana iz .env
    )
)
goto CHECKPY

:NOENV
echo [run_bot] VNIMANIE: .env ne nayden, ispolzuyu nastroyki po umolchaniyu

:CHECKPY
if not exist "%VENV_PYTHON%" (
    echo [run_bot] OSHIBKA: ne nayden %VENV_PYTHON%
    exit /b 1
)

if not exist "%BOT_SCRIPT%" (
    echo [run_bot] OSHIBKA: ne nayden %BOT_SCRIPT%
    exit /b 1
)

if not defined LESOVOD_TELEGRAM_BOT_TOKEN (
    echo [run_bot] VNIMANIE: LESOVOD_TELEGRAM_BOT_TOKEN ne zadan v .env
)
if not defined LESOVOD_BOT_SERVICE_TOKEN (
    echo [run_bot] VNIMANIE: LESOVOD_BOT_SERVICE_TOKEN ne zadan v .env
)

cd /d "%BACKEND_DIR%\legacy"
"%VENV_PYTHON%" "%BOT_SCRIPT%"
