@echo off
REM install_service.bat — Блок 4, пункт 2 (автозапуск на Windows).
REM Запускать один раз, от имени администратора (nssm install требует
REM прав на регистрацию службы).
REM
REM nssm скачать: https://nssm.cc/download — распаковать, положить
REM nssm.exe, например, в C:\lesovod\nssm\nssm.exe (поправьте путь ниже,
REM если положили в другое место).

set "NSSM=C:\lesovod\nssm\nssm.exe"
set "SERVICE_NAME=LesovodBackend"
set "RUN_SCRIPT=%~dp0run_server.bat"
set "LOG_DIR=C:\lesovod\logs"

if not exist "%NSSM%" (
    echo ОШИБКА: nssm.exe не найден по пути %NSSM%
    echo Скачайте с https://nssm.cc/download и поправьте путь в начале
    echo этого файла.
    exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Служба запускает не python напрямую, а run_server.bat рядом с этим
REM файлом — так подхватывается deploy\.env (см. пункт 5 плана) без
REM того, чтобы прописывать переменные в самой службе через nssm.
%NSSM% install %SERVICE_NAME% cmd.exe /c "\"%RUN_SCRIPT%\""
%NSSM% set %SERVICE_NAME% AppDirectory "%~dp0"
%NSSM% set %SERVICE_NAME% DisplayName "Lesovod — backend (FastAPI/uvicorn)"
%NSSM% set %SERVICE_NAME% Description "Цифровой помощник лесовода — API-сервер. Настройки — в deploy\.env рядом со службой."

REM Логи: nssm сам пишет stdout/stderr процесса в файлы, с ротацией по
REM размеру — без этого uvicorn печатает только в консоль, которой у
REM службы нет.
%NSSM% set %SERVICE_NAME% AppStdout "%LOG_DIR%\backend.out.log"
%NSSM% set %SERVICE_NAME% AppStderr "%LOG_DIR%\backend.err.log"
%NSSM% set %SERVICE_NAME% AppRotateFiles 1
%NSSM% set %SERVICE_NAME% AppRotateOnline 1
%NSSM% set %SERVICE_NAME% AppRotateBytes 10485760

REM Автозапуск при загрузке Windows + автоперезапуск при падении
REM процесса (пункт 2 плана — "с автоперезапуском при сбое").
%NSSM% set %SERVICE_NAME% Start SERVICE_AUTO_START
%NSSM% set %SERVICE_NAME% AppExit Default Restart
%NSSM% set %SERVICE_NAME% AppRestartDelay 5000
REM Если backend падает быстрее, чем раз в 90 сек несколько раз подряд —
REM скорее всего, конфигурация сломана (не найден venv, не тот путь к
REM базе), а не разовый сбой; nssm сам увеличивает паузу между попытками
REM по нарастающей (throttling) — поведение по умолчанию, отдельно не
REM настраивается этим скриптом.

echo.
echo Служба %SERVICE_NAME% установлена. Перед запуском:
echo   1. Проверьте, что deploy\.env заполнен (см. .env.example).
echo   2. Проверьте, что venv создан и зависимости поставлены
echo      (backend\venv\Scripts\pip install -r requirements.txt).
echo Запуск:  net start %SERVICE_NAME%
echo Логи:    %LOG_DIR%\backend.out.log / backend.err.log
echo Удаление службы (если понадобится): %NSSM% remove %SERVICE_NAME% confirm

REM Телеграм-бот удалён (28.09.2026): отчёты идут только из мобильного
REM приложения. Если на сервере осталась старая служба LesovodBot —
REM останавливаем и удаляем её (ошибки, если её нет, не страшны).
net stop LesovodBot >nul 2>&1
%NSSM% remove LesovodBot confirm >nul 2>&1
