#!/usr/bin/env bash
# One-command start for macOS/Linux:  ./start.sh
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  DC&E Billing Audit - setup & start"
echo "  Folder: $(pwd)"
echo "============================================================"

PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[ERROR] python3 not found. Install Python 3 and re-run." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment (first run only)..."
  "$PY" -m venv .venv
fi
VENV_PY=.venv/bin/python

echo "Installing/updating dependencies..."
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "------------------------------------------------------------"
  echo "  Created .env from the template. Set EDW_SERVER / EDW_DB to"
  echo "  your SQL server, then re-run ./start.sh"
  echo "------------------------------------------------------------"
  exit 0
fi

echo "Launching server... (open http://localhost:5100)"
exec "$VENV_PY" run.py
