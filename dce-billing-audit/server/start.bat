@echo off
setlocal
REM One-click start for Windows. Written without parenthesized if-blocks so it
REM survives folder names that contain "&" (e.g. "DC&E Billing Audit").
cd /d "%~dp0"

echo ============================================================
echo   DC^&E Billing Audit - setup and start
echo ============================================================
echo.

REM ---- locate Python ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if defined PY goto gotpy
where python >nul 2>nul && set "PY=python"
if defined PY goto gotpy
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if defined PY goto gotpy
goto nopy
:gotpy
echo Using Python: %PY%

REM ---- create venv (first run only) ----
if exist ".venv\Scripts\python.exe" goto havevenv
echo Creating virtual environment, first run only...
%PY% -m venv .venv
:havevenv
set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto novenv

REM ---- dependencies ----
echo Installing/updating dependencies, first run can take a minute...
"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail

REM ---- first-run .env ----
if exist ".env" goto run
copy ".env.example" ".env" >nul
echo.
echo Created .env from the template. Set EDW_SERVER / EDW_DB, then run START.bat again.
goto end

:run
echo.
echo Open http://localhost:5100 in your browser.  Press Ctrl+C here to stop.
echo.
"%VENV_PY%" run.py
goto end

:nopy
echo [ERROR] Python not found. Install Python 3 from https://www.python.org/downloads/
echo and tick "Add Python to PATH", then run START.bat again.
goto end

:novenv
echo [ERROR] Could not create the virtual environment. See messages above.
goto end

:pipfail
echo [ERROR] Dependency install failed. See messages above.
goto end

:end
echo.
pause
