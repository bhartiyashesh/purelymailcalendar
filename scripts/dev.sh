#!/usr/bin/env bash
# Run the FastAPI backend and Vite frontend together.
# Usage: ./scripts/dev.sh
# Stop with Ctrl-C; both children are killed on exit.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -d ".venv" ]; then
  echo "venv missing. Run: python3 -m venv .venv && .venv/bin/pip install -e '.[web]'"
  exit 1
fi

if [ ! -d "web/node_modules" ]; then
  echo "Installing web/ npm deps..."
  (cd web && npm install)
fi

cleanup() {
  trap - EXIT
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "API   -> http://127.0.0.1:8000"
echo "WEB   -> http://127.0.0.1:5173"
echo

.venv/bin/uvicorn calinvite_web.app:app --host 127.0.0.1 --port 8000 --reload &
API_PID=$!

(cd web && npm run dev -- --host 127.0.0.1 --port 5173) &
WEB_PID=$!

wait $API_PID $WEB_PID
