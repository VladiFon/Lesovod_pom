@echo off
REM novyy_klient.bat <imya> <port> [izdanie] [nazvanie]
REM Sozdaet otdelnuyu kopiyu Lesovoda dlya klienta na etom zhe PK (04.11.2026):
REM   C:\lesovod\klienty\<imya>\.env        - nastroyki klienta
REM   C:\lesovod\klienty\<imya>\data\app     - EGO baza lesovod.db, blanki, karty
REM   C:\lesovod\klienty\<imya>\data\storage - ego fayly
REM i sluzhbu Windows LesovodKlient_<imya>. Kod i sayt - obshchie s vashim
REM lesnichestvom, poetomu obnovlenie stavitsya odin raz na vsekh
REM (perezapusk_vseh.bat). Zapuskat OT ADMINISTRATORA.
REM Primer:  novyy_klient.bat lesopunkt 8001 lesopunkt
REM Nazvanie organizacii po-russki napishite v Bloknote v fayl
REM C:\lesovod\klienty\<imya>\data\app\organizaciya.txt (UTF-8).
setlocal enabledelayedexpansion

set "IMYA=%~1"
set "PORT=%~2"
set "IZDANIE=%~3"
set "NAZVANIE=%~4"
if "%IMYA%"=="" goto USAGE
if "%PORT%"=="" goto USAGE
if "%IZDANIE%"=="" set "IZDANIE=lesopunkt"

set "NSSM=C:\lesovod\nssm\nssm.exe"
set "ROOT=C:\lesovod\klienty\%IMYA%"
set "SERVICE_NAME=LesovodKlient_%IMYA%"
set "MAIN_ENV=%~dp0.env"

if not exist "%NSSM%" (
    echo OSHIBKA: nssm.exe ne nayden: %NSSM%
    exit /b 1
)
if exist "%ROOT%\.env" (
    echo OSHIBKA: klient %IMYA% uzhe est: %ROOT%
    echo Udalit sluzhbu: %NSSM% remove %SERVICE_NAME% confirm
    exit /b 1
)

REM Otkuda brat blanki i karty - iz nastroek vashego lesnichestva.
set "SRC_APP=C:\lesovod\data\app"
set "SRC_RES="
if exist "%MAIN_ENV%" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%MAIN_ENV%") do (
        if "%%A"=="LESOVOD_APP_DIR" set "SRC_APP=%%B"
        if "%%A"=="LESOVOD_RESOURCE_DIR" set "SRC_RES=%%B"
    )
)
if "%SRC_RES%"=="" set "SRC_RES=%SRC_APP%\templates"

mkdir "%ROOT%\data\app\templates" 2>nul
mkdir "%ROOT%\data\storage" 2>nul
mkdir "%ROOT%\logs" 2>nul

echo Kopiruyu blanki i karty iz %SRC_RES% ...
robocopy "%SRC_RES%" "%ROOT%\data\app\templates" /e /njh /njs /nfl /ndl /np >nul
for %%F in (lch_map.json soffice_path.txt) do (
    if exist "%SRC_APP%\%%F" copy /y "%SRC_APP%\%%F" "%ROOT%\data\app\%%F" >nul
)
REM Portativnyy LibreOffice (chtenie MDO) - ne kopiruem 300 MB, a ukazyvaem put.
if not exist "%ROOT%\data\app\soffice_path.txt" if exist "%SRC_APP%\LibreOfficePortable\App\libreoffice\program\soffice.exe" (
    > "%ROOT%\data\app\soffice_path.txt" echo %SRC_APP%\LibreOfficePortable\App\libreoffice\program\soffice.exe
)

(
    echo # Kopiya Lesovoda dlya klienta "%IMYA%" ^(sozdana novyy_klient.bat^)
    echo LESOVOD_IZDANIE=%IZDANIE%
    echo LESOVOD_ORG_NAZVANIE=%NAZVANIE%
    echo LESOVOD_PORT=%PORT%
    echo LESOVOD_APP_DIR=%ROOT%\data\app
    echo LESOVOD_RESOURCE_DIR=%ROOT%\data\app\templates
    echo LESOVOD_DB_PATH=%ROOT%\data\app\lesovod.db
    echo LESOVOD_STORAGE_DIR=%ROOT%\data\storage
) > "%ROOT%\.env"

%NSSM% install %SERVICE_NAME% cmd.exe /c "\"%~dp0run_klient.bat\" \"%ROOT%\""
%NSSM% set %SERVICE_NAME% AppDirectory "%~dp0"
%NSSM% set %SERVICE_NAME% DisplayName "Lesovod - klient %IMYA% (%IZDANIE%)"
%NSSM% set %SERVICE_NAME% AppStdout "%ROOT%\logs\backend.out.log"
%NSSM% set %SERVICE_NAME% AppStderr "%ROOT%\logs\backend.err.log"
%NSSM% set %SERVICE_NAME% AppRotateFiles 1
%NSSM% set %SERVICE_NAME% AppRotateOnline 1
%NSSM% set %SERVICE_NAME% AppRotateBytes 10485760
%NSSM% set %SERVICE_NAME% Start SERVICE_AUTO_START
%NSSM% set %SERVICE_NAME% AppExit Default Restart
%NSSM% set %SERVICE_NAME% AppRestartDelay 5000
net start %SERVICE_NAME%

echo.
echo Gotovo. Klient %IMYA%: %ROOT%
echo Proverka: curl http://localhost:%PORT%/api/izdanie
echo Pervyy vkhod na ego sayt: admin / admin - srazu smenite parol.
echo Dalshe - dobavte adres klienta v Caddyfile (sm. Caddyfile.klient.primer)
echo i perezapustite Caddy: net stop LesovodCaddy ^&^& net start LesovodCaddy
exit /b 0

:USAGE
echo Ispolzovanie: novyy_klient.bat ^<imya^> ^<port^> [izdanie] [nazvanie]
echo Primer:       novyy_klient.bat lesopunkt 8001 lesopunkt "LP Dubrovka"
exit /b 1
