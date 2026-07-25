#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "Starting API on http://127.0.0.1:8000"
python3 scripts/start_api.py &
API_PID=$!

echo "Starting frontend on http://127.0.0.1:5173"
(cd frontend && npm run dev) &
UI_PID=$!

trap 'kill $API_PID $UI_PID 2>/dev/null' EXIT
wait
