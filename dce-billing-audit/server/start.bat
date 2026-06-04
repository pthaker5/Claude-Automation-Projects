@echo off
REM DC&E Billing Audit - one-click start for Windows.
REM Double-click this file. First run sets everything up; later runs just start.
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py") || (set "PY=python")

if not exist ".venv" (
  echo Creating Python environment (first run only)...
  %PY% -m venv .venv
)
call ".venv\Scripts\activate.bat"

echo Installing/updating dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo  ============================================================
  echo   Created .env from the template.
  echo   Open .env in Notepad, fill in the EDW credentials/secret,
  echo   save it, then double-click start.bat again.
  echo  ============================================================
  echo.
  pause
  exit /b
)

python run.py
pause
