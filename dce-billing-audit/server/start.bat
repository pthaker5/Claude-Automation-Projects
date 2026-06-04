@echo off
setlocal enableextensions
title DC&E Billing Audit
REM One-click start for Windows. The window stays open so you can read any error.
pushd "%~dp0"

echo ============================================================
echo   DC^&E Billing Audit - setup ^& start
echo   Folder: %CD%
echo ============================================================
echo.

REM ---- find a Python interpreter ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY (
  echo [ERROR] Python was not found on this PC.
  echo Install Python 3 from https://www.python.org/downloads/
  echo and tick "Add Python to PATH" during install, then run START.bat again.
  echo.
  pause & popd & exit /b 1
)
echo Using Python: %PY%
echo.

REM ---- create the virtual environment (first run only) ----
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment ^(first run only^)...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Could not create the virtual environment.
    pause & popd & exit /b 1
  )
)
set "VENV_PY=.venv\Scripts\python.exe"

REM ---- install dependencies (uses the venv's python directly; no activate) ----
echo Installing/updating dependencies ^(first run can take a minute^)...
"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Dependency install failed - see the messages above.
  pause & popd & exit /b 1
)
echo.

REM ---- first-run .env ----
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo ------------------------------------------------------------
  echo  Created .env from the template. Set EDW_SERVER / EDW_DB to
  echo  your SQL server, then run START.bat again.
  echo ------------------------------------------------------------
  pause & popd & exit /b 0
)

echo Launching server...  ^(open http://localhost:5100 in your browser^)
echo Press Ctrl+C in this window to stop.
echo.
"%VENV_PY%" run.py

echo.
echo Server stopped.
pause
popd
endlocal
