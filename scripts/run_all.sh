#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

python3 scripts/01_load_backbone.py
python3 scripts/02_build_semantic_graph.py

echo "Stage 2 pipeline finished."
