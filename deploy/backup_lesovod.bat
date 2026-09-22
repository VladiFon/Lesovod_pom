@echo off
setlocal enabledelayedexpansion
REM backup_lesovod.bat — Блок 4, пункт 4.
REM Регистрируется в Планировщике заданий Windows на ежедневный запуск,
REM например в 23:30 (после рабочего дня):
REM   schtasks /create /tn "LesovodBackup" /tr "C:\lesovod\deploy\backup_lesovod.bat" ^
REM     /sc daily /st 23:30 /ru SYSTEM
REM (запустить одной строкой, без переносов ^ выше — они только для
REM читаемости в этом комментарии).

set "SCRIPT_DIR=%~dp0"
set "ENV_FILE=%SCRIPT_DIR%.env"
set "BACKEND_DIR=C:\lesovod\backend"
set "VENV_PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"

REM Куда складывать обычные бэкапы (БД + документы) — общедоступная (в
REM смысле "видна другим админам/расшарена в сеть") папка для бэкапов ок.
set "BACKUP_DIR=C:\lesovod\backups"

REM Секреты (secrets.json — ключи Gemini/OpenRouter, токен Telegram-бота
REM в открытом виде, см. legacy/secrets_store.py) бэкапятся ОТДЕЛЬНО, в
REM другую папку — не кладите её в то же место, что шарите для обычных
REM бэкапов, и ограничьте к ней доступ (NTFS-права только для
REM администратора). По умолчанию — подпапка на том же диске, но НЕ
REM внутри BACKUP_DIR:
set "SECRETS_BACKUP_DIR=C:\lesovod\backups-secrets"

REM Читаем .env, чтобы узнать реальные пути к базе/данным/секретам —
REM тот же формат, что читает run_server.bat.
if not exist "%ENV_FILE%" (
    echo [backup] ОШИБКА: %ENV_FILE% не найден, не знаю пути к данным.
    exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if not "%%A"=="" set "%%A=%%B"
)

if not defined LESOVOD_DB_PATH (
    echo [backup] ОШИБКА: LESOVOD_DB_PATH не задан в .env
    exit /b 1
)
if not defined LESOVOD_STORAGE_DIR (
    echo [backup] ОШИБКА: LESOVOD_STORAGE_DIR не задан в .env
    exit /b 1
)
if not defined LESOVOD_APP_DIR (
    echo [backup] ОШИБКА: LESOVOD_APP_DIR не задан в .env
    exit /b 1
)

REM Папка с датой в имени — пункт 4 плана дословно.
for /f "tokens=2-4 delims=.- " %%a in ("%date%") do set "DATE_STAMP=%%c-%%b-%%a"
set "TIME_STAMP=%time::=-%"
set "TIME_STAMP=%TIME_STAMP: =0%"
set "STAMP=%DATE_STAMP%_%TIME_STAMP:~0,8%"
set "DEST=%BACKUP_DIR%\%STAMP%"

mkdir "%DEST%" 2>nul
mkdir "%SECRETS_BACKUP_DIR%" 2>nul

echo [backup] %STAMP% — начало

REM 1. База данных — через sqlite3 backup API (python), а не простое
REM    копирование файла: в WAL-режиме (см. app/database.py) рядом с
REM    lesovod.db есть lesovod.db-wal/-shm с ещё не влитыми в основной
REM    файл изменениями — обычный copy их не подхватит и может дать
REM    бэкап без части последних записей. sqlite3 .backup делает
REM    консистентный снимок прямо во время работы backend'а, без
REM    остановки службы.
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" "%LESOVOD_DB_PATH%" "%DEST%\lesovod.db"
    if errorlevel 1 (
        echo [backup] ОШИБКА при бэкапе базы, см. вывод выше.
    ) else (
        echo [backup] База скопирована: %DEST%\lesovod.db
    )
) else (
    echo [backup] venv python не найден ^(%VENV_PYTHON%^), fallback — простое копирование файла.
    echo [backup] ВНИМАНИЕ: при активной WAL-записи такой бэкап может быть неполным.
    copy /y "%LESOVOD_DB_PATH%" "%DEST%\lesovod.db" >nul
)

REM 2. Документы (сгенерированные акты/листки/техкарты, загруженные
REM    абрисы) — просто копия дерева файлов.
if exist "%LESOVOD_STORAGE_DIR%" (
    xcopy "%LESOVOD_STORAGE_DIR%" "%DEST%\storage\" /e /i /q /y >nul
    echo [backup] storage скопирован: %DEST%\storage
) else (
    echo [backup] LESOVOD_STORAGE_DIR не найден, пропущено: %LESOVOD_STORAGE_DIR%
)

REM 3. secrets.json — ОТДЕЛЬНО, в защищённую папку, не в общий BACKUP_DIR
REM    (см. комментарий у SECRETS_BACKUP_DIR выше). Если решите, что
REM    секреты вообще не нужно бэкапить сюда (например, они и так
REM    зарегистрированы в реальном секрет-менеджере — см. README.md
REM    backend'а, раздел про secrets_store.py) — просто удалите этот блок.
set "SECRETS_FILE=%LESOVOD_APP_DIR%\secrets.json"
if exist "%SECRETS_FILE%" (
    copy /y "%SECRETS_FILE%" "%SECRETS_BACKUP_DIR%\secrets_%STAMP%.json" >nul
    echo [backup] secrets.json скопирован отдельно: %SECRETS_BACKUP_DIR%\secrets_%STAMP%.json
) else (
    echo [backup] secrets.json не найден, пропущено ^(это нормально, если ключи не задавались^).
)

REM 3б. Этап 4, Блок 3/часть 2 — deploy\.env теперь тоже содержит секрет
REM     (LESOVOD_BOT_SERVICE_TOKEN, LESOVOD_TELEGRAM_BOT_TOKEN), не только
REM     пути — та же защищённая папка, что и secrets.json, тем же принципом.
if exist "%ENV_FILE%" (
    copy /y "%ENV_FILE%" "%SECRETS_BACKUP_DIR%\env_%STAMP%.txt" >nul
    echo [backup] .env скопирован отдельно: %SECRETS_BACKUP_DIR%\env_%STAMP%.txt
)

REM 4. Хвост — не копим бэкапы бесконечно: оставляем последние 14
REM    дневных папок в BACKUP_DIR, старые удаляем. secrets-бэкапы
REM    удаляются по той же логике, отдельным циклом.
set "KEEP_DAYS=14"
forfiles /p "%BACKUP_DIR%" /d -%KEEP_DAYS% /c "cmd /c if @isdir==TRUE rmdir /s /q @path" 2>nul
forfiles /p "%SECRETS_BACKUP_DIR%" /d -%KEEP_DAYS% /c "cmd /c del @path" 2>nul

echo [backup] %STAMP% — готово
