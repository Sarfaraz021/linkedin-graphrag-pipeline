#!/usr/bin/env bash
# End-to-end: scrape N URLs → copy structured JSON → backbone → semantic graph → summary
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

load_env_var() {
  local key="$1"
  local val
  val="$(grep -E "^${key}=" "$ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r')"
  if [[ -n "$val" ]]; then
    export "$key=$val"
  fi
}

load_env_var HARVEST_API_KEY
load_env_var OPENAI_API_KEY
load_env_var ANTHROPIC_API_KEY
load_env_var NEO4J_URI
load_env_var NEO4J_USER
load_env_var NEO4J_PASSWORD
load_env_var NEO4J_DATABASE

MAX_URLS="${1:-20}"
SKIP_URLS="${2:-0}"

EXCEL="${EXCEL_PATH:-$ROOT/data/Urls/Linkedin saved posts.xlsx}"
SCRAPER_OUT="$ROOT/linkedin scraper/output"
STRUCTURED_DIR="$SCRAPER_OUT/structured"
RAW_DIR="$ROOT/data/raw"
PROCESSED_DIR="$ROOT/data/processed"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "=== E2E batch: $MAX_URLS URLs (skip=$SKIP_URLS) ==="
echo "Excel: $EXCEL"
echo "Scraper output: $SCRAPER_OUT"
echo "Pipeline input: $RAW_DIR"

mkdir -p "$SCRAPER_OUT" "$RAW_DIR" "$PROCESSED_DIR"

echo ""
echo "--- Stage 1: Scraping (HarvestAPI) ---"
python3 "linkedin scraper/main.py" \
  --api-key "${HARVEST_API_KEY:?HARVEST_API_KEY not set in .env}" \
  --excel "$EXCEL" \
  --output-dir "$SCRAPER_OUT" \
  --max-urls "$MAX_URLS" \
  --skip "$SKIP_URLS" \
  --refresh \
  --enrich \
  --enrich-mode basic

STRUCTURED_COUNT="$(find "$STRUCTURED_DIR" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$STRUCTURED_COUNT" -eq 0 ]]; then
  echo "ERROR: No structured JSON files in $STRUCTURED_DIR"
  exit 1
fi

echo ""
echo "--- Sync structured JSON → data/raw ---"
rm -f "$RAW_DIR"/*.json
cp "$STRUCTURED_DIR"/*.json "$RAW_DIR"/
echo "Copied $(ls -1 "$RAW_DIR"/*.json | wc -l | tr -d ' ') files to $RAW_DIR"

echo ""
echo "--- Stage 2a: Backbone load ---"
python3 scripts/01_load_backbone.py

echo ""
echo "--- Stage 2b: Classification + semantic extraction ---"
python3 scripts/02_build_semantic_graph.py

echo ""
echo "--- Summary ---"
python3 scripts/e2e_batch_summary.py

echo ""
echo "=== E2E batch complete ==="
