#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_URL="http://127.0.0.1:8000"
UI_URL="http://127.0.0.1:5173"
API_PID=""
UI_PID=""

cleanup() {
  echo ""
  echo "Shutting down..."
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "$UI_PID" ]] && kill "$UI_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Activate venv when present
if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

if ! command -v python3 >/dev/null; then
  echo "Error: python3 not found. Create a venv and install requirements first."
  exit 1
fi

if ! python3 -c "import uvicorn, fastapi" 2>/dev/null; then
  echo "Error: Python deps missing. Run: pip install -r requirements.txt"
  exit 1
fi

if ! command -v npm >/dev/null; then
  echo "Error: npm not found. Install Node.js to run the frontend."
  exit 1
fi

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  (cd "$ROOT/frontend" && npm install)
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  LinkedIn Graph Intelligence — Demo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Starting API  → $API_URL"
python3 "$ROOT/scripts/start_api.py" &
API_PID=$!

echo -n "Waiting for API"
for _ in $(seq 1 40); do
  if curl -sf "$API_URL/api/health" >/dev/null 2>&1; then
    echo " ✓"
    break
  fi
  echo -n "."
  sleep 0.25
done

if ! curl -sf "$API_URL/api/health" >/dev/null 2>&1; then
  echo ""
  echo "Error: API did not start. Check Neo4j/OpenAI settings in .env"
  exit 1
fi

echo "Starting UI   → $UI_URL"
(cd "$ROOT/frontend" && npm run dev) &
UI_PID=$!

echo ""
echo "Ready. Open $UI_URL"
echo "Press Ctrl+C to stop both servers."
echo ""

wait
