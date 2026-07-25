#!/usr/bin/env python3
"""Build LLM semantic graph layer in Neo4j."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.pipeline.pipeline import run_semantic_graph  # noqa: E402


def main() -> None:
    stats = run_semantic_graph()
    print("Semantic graph build complete:", stats)


if __name__ == "__main__":
    main()
