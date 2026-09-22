@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "ENV_FILE=%SCRIPT_DIR%.env"
set "BACKEND_DIR=C:\lesovod\backend"
set "VENV_PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"

if not exist "%ENV_FILE%" goto NOENV

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if not "%%A"=="" (
        set "%%A=%%B"
        echo [run_server] %%A zadana iz .env
    )
)
goto CHECKPY

:NOENV
echo [run_server] VNIMANIE: .env ne nayden, ispolzuyu nastroyki po umolchaniyu

:CHECKPY
if not exist "%VENV_PYTHON%" (
    echo [run_server] OSHIBKA: ne nayden %VENV_PYTHON%
    echo [run_server] Sozdayte venv: cd %BACKEND_DIR% ^&^& python -m venv venv
    exit /b 1
)

set "PORT_ARG=8000"
if defined LESOVOD_PORT set "PORT_ARG=%LESOVOD_PORT%"

cd /d "%BACKEND_DIR%"
"%VENV_PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT_ARG%