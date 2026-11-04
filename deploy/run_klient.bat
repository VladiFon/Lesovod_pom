@echo off
REM run_klient.bat <papka klienta> - zapusk kopii servera dlya klienta
REM (lesopunkt i t.p., 04.11.2026). Kod obshchiy (C:\lesovod\backend),
REM baza i nastroyki - svoi, iz <papka>\.env. Sozdaetsya novyy_klient.bat,
REM sluzhbu zapuskaet NSSM - vruchnuyu etot fayl zapuskat ne nuzhno.
setlocal enabledelayedexpansion

set "KLIENT_DIR=%~1"
if "%KLIENT_DIR%"=="" (
    echo [run_klient] OSHIBKA: ukazhite papku klienta, naprimer C:\lesovod\klienty\lesopunkt
    exit /b 1
)
set "ENV_FILE=%KLIENT_DIR%\.env"
set "BACKEND_DIR=C:\lesovod\backend"
set "VENV_PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"

if not exist "%ENV_FILE%" (
    echo [run_klient] OSHIBKA: net %ENV_FILE%
    exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if not "%%A"=="" set "%%A=%%B"
)
if not defined LESOVOD_PORT (
    echo [run_klient] OSHIBKA: v %ENV_FILE% ne zadan LESOVOD_PORT
    exit /b 1
)
if not exist "%VENV_PYTHON%" (
    echo [run_klient] OSHIBKA: ne nayden %VENV_PYTHON%
    exit /b 1
)

echo [run_klient] %KLIENT_DIR%  izdanie=%LESOVOD_IZDANIE%  port=%LESOVOD_PORT%
cd /d "%BACKEND_DIR%"
REM Tolko 127.0.0.1: snaruzhi klient zakhodit cherez Caddy (svoy adres).
"%VENV_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port %LESOVOD_PORT%
