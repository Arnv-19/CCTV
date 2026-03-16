#!/bin/bash
# Run the SkyCCTVAI FastAPI server from the project root
cd "$(dirname "$0")"

# Load environment variables
[ -f .env ] && export $(grep -v '^#' .env | xargs)

PORT=${PORT:-8000}
WORKERS=${WORKERS:-1}

# Prefer project venv Python tools when present.
UVICORN_BIN="uvicorn"
if [ -x ".venv/bin/uvicorn" ]; then
  UVICORN_BIN=".venv/bin/uvicorn"
fi

if [ "${APP_ENV:-production}" = "development" ]; then
  # Dev: single worker with hot-reload
  "$UVICORN_BIN" app.main:app --host 0.0.0.0 --port "$PORT" --reload
else
  # Production: no reload, configurable workers
  "$UVICORN_BIN" app.main:app --host 0.0.0.0 --port "$PORT" --workers "$WORKERS"
fi
