#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# TutorConnect — one-shot launcher.
#
#   ./scripts/run.sh              start the platform on http://127.0.0.1:8000
#   PORT=9000 ./scripts/run.sh    start on another port
#   ./scripts/run.sh --reseed     wipe + re-seed the database, then start
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

if [ ! -f ".env" ]; then
  echo "[run] No .env found — copying .env.example (edit it before deploying)."
  cp .env.example .env
fi

if ! "$PYTHON" -c "import fastapi, uvicorn, sqlalchemy" >/dev/null 2>&1; then
  echo "[run] Installing dependencies from requirements.txt …"
  "$PYTHON" -m pip install --quiet -r requirements.txt
fi

exec "$PYTHON" scripts/serve.py --host "$HOST" --port "$PORT" "$@"
