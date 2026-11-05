@echo off
REM perezapusk_vseh.bat - posle obnovleniya: perezapustit vash server
REM (LesovodBackend) i vse kopii klientov (LesovodKlient_*) odnim razom.
REM Zapuskat OT ADMINISTRATORA.
setlocal enabledelayedexpansion

set "SPISOK=LesovodBackend"
for /f "tokens=2 delims=: " %%S in ('sc query state^= all ^| findstr /b /c:"SERVICE_NAME: LesovodKlient_"') do (
    set "SPISOK=!SPISOK! %%S"
)

for %%S in (%SPISOK%) do (
    echo [perezapusk] %%S
    net stop %%S >nul 2>&1
    net start %%S
)
echo.
echo Gotovo. Proverka vashego: curl http://localhost:8000/api/health
