#!/usr/bin/env bash
# Scrape N LinkedIn post URLs via HarvestAPI → structured JSON only.
# Output: linkedin scraper/output/structured/<postId>.json
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

MAX_URLS="${1:-20}"
SKIP_URLS="${2:-0}"
REFRESH="${REFRESH:-0}"   # set REFRESH=1 to re-scrape already-done posts

EXCEL="${EXCEL_PATH:-$ROOT/data/Urls/Linkedin saved posts.xlsx}"
SCRAPER_OUT="$ROOT/linkedin scraper/output"
LOG_FILE="$ROOT/data/scrape_batch_${MAX_URLS}.log"

mkdir -p "$SCRAPER_OUT" "$ROOT/data"

REFRESH_FLAG=""
if [[ "$REFRESH" == "1" ]]; then
  REFRESH_FLAG="--refresh"
fi

echo "=== Scrape batch: $MAX_URLS URLs (skip=$SKIP_URLS) ===" | tee "$LOG_FILE"
echo "Excel: $EXCEL" | tee -a "$LOG_FILE"
echo "Output: $SCRAPER_OUT/structured/" | tee -a "$LOG_FILE"
echo "Log: $LOG_FILE" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

python3 -u "linkedin scraper/main.py" \
  --api-key "${HARVEST_API_KEY:?HARVEST_API_KEY not set in .env}" \
  --excel "$EXCEL" \
  --output-dir "$SCRAPER_OUT" \
  --max-urls "$MAX_URLS" \
  --skip "$SKIP_URLS" \
  $REFRESH_FLAG \
  --enrich \
  --enrich-mode basic \
  2>&1 | tee -a "$LOG_FILE"

COUNT="$(find "$SCRAPER_OUT/structured" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
echo "" | tee -a "$LOG_FILE"
echo "=== Done: $COUNT structured JSON files in $SCRAPER_OUT/structured/ ===" | tee -a "$LOG_FILE"
