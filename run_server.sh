#!/bin/bash

# Resolve project root from the script's own location — works on any machine.
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR" || exit 1

# Safe env loading
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

PORT=${PORT:-8000}
WORKERS=${WORKERS:-1}

# Prefer the venv Python when present (important for systemd on production).
# Falls back to system python3 for local dev without a venv.
if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

if [ "${APP_ENV:-production}" = "development" ]; then
  "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
else
  "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers "$WORKERS"
fi
