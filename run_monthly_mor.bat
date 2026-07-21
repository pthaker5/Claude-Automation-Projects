@echo off
REM ============================================================
REM   Akzo MOR -- One-Click Monthly Generator
REM ============================================================
REM   USAGE:
REM     - Drop the fresh Claims twbx in this folder:
REM         Claims and Complaints*.twbx
REM       (Tender data is now pulled directly from CL709 SQL --
REM        no more Tender twbx unpacking needed.)
REM     - (Optional) Edit narrative_<YYYY-MM>.yaml for this month's prose
REM         (if no narrative file exists, narrative_example.yaml is used)
REM     - Double-click this .bat
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM --- Determine report month (default = previous calendar month) ---
if "%~1"=="" (
    REM Compute "last month" using PowerShell -- handles year rollover
    for /f "delims=" %%i in ('powershell -Command "(Get-Date).AddMonths(-1).ToString('yyyy-MM')"') do set REPORT_MONTH=%%i
) else (
    set REPORT_MONTH=%~1
)

echo.
echo ============================================================
echo   Akzo MOR Generator
echo   Report month: !REPORT_MONTH!
echo ============================================================
echo.

REM --- Verify Python is on PATH ---
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python not found on PATH
    echo   Install Python or open a Python-enabled shell first.
    pause
    exit /b 1
)

REM --- Auto-unpack Claims .twbx if its hyper extract is missing ---
call :unpack_twbx "Claims and Complaints Dashboard*.twbx" claims_unpacked

REM --- Locate the Claims hyper file ---
set CLAIMS_HYPER=
for /f "delims=" %%f in ('dir /b /s /o-s "claims_unpacked\*.hyper" 2^>nul') do (
    if "!CLAIMS_HYPER!"=="" set CLAIMS_HYPER=%%f
)
if "!CLAIMS_HYPER!"=="" (
    echo ERROR: No claims .hyper file found.  Did the unpack fail?
    pause & exit /b 1
)
echo Claims hyper: !CLAIMS_HYPER!

REM --- Pick the narrative file: prefer month-specific, fall back to default ---
set NARRATIVE_ARG=
if exist "narrative_!REPORT_MONTH!.yaml" (
    set NARRATIVE_ARG=--narrative "narrative_!REPORT_MONTH!.yaml"
    echo Narrative:    narrative_!REPORT_MONTH!.yaml
) else if exist "narrative.yaml" (
    set NARRATIVE_ARG=--narrative "narrative.yaml"
    echo Narrative:    narrative.yaml
) else (
    echo Narrative:    (auto-detect from script folder)
)

REM --- Ensure output folder exists ---
if not exist "reports" mkdir reports

REM --- Run the report generator ---
echo.
echo ----- Running report generator -----
python akzo_mor_full_report.py ^
    --report-month !REPORT_MONTH! ^
    --claims-hyper "!CLAIMS_HYPER!" ^
    --output-dir reports ^
    !NARRATIVE_ARG!

if errorlevel 1 (
    echo.
    echo ============================================================
    echo   FAILED -- see error above
    echo ============================================================
    pause
    exit /b 1
)

REM --- Open the generated HTML in the default browser ---
echo.
echo ============================================================
echo   SUCCESS  --  opening report
echo ============================================================
start "" "reports\Akzo_MOR_Full_!REPORT_MONTH!.html"
exit /b 0


REM ============================================================
REM   Subroutine: unpack a .twbx if its hyper extract doesn't exist yet
REM ============================================================
:unpack_twbx
set "PATTERN=%~1"
set "DEST=%~2"
REM Always re-unpack to pick up fresh .twbx data
if exist "%DEST%" rmdir /S /Q "%DEST%"
REM Find the first matching .twbx
set "TWBX="
for /f "delims=" %%f in ('dir /b "%PATTERN%" 2^>nul') do (
    if "!TWBX!"=="" set "TWBX=%%f"
)
if "!TWBX!"=="" (
    echo WARNING: No file matching %PATTERN% found.  Skipping unpack of %DEST%.
    exit /b 0
)
echo Unpacking !TWBX! -^> %DEST%\
powershell -Command "Copy-Item '!TWBX!' '%TEMP%\unpack.zip' -Force; Expand-Archive -Path '%TEMP%\unpack.zip' -DestinationPath '%DEST%' -Force; Remove-Item '%TEMP%\unpack.zip'"
exit /b 0
