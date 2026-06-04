#!/usr/bin/env bash
# DC&E Billing Audit - one-command start for macOS/Linux.
#   ./start.sh
# First run sets everything up; later runs just start the server.
set -e
cd "$(dirname "$0")"

PY=${PYTHON:-python3}

if [ ! -d .venv ]; then
  echo "Creating Python environment (first run only)..."
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing/updating dependencies..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "============================================================"
  echo "  Created .env from the template."
  echo "  Edit .env, fill in the EDW credentials/secret, then re-run."
  echo "============================================================"
  echo
  exit 0
fi

exec python run.py
