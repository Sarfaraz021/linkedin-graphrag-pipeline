#!/usr/bin/env python3
"""Load deterministic backbone into Neo4j."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.pipeline.pipeline import run_backbone  # noqa: E402


def main() -> None:
    stats = run_backbone()
    print("Backbone load complete:", stats)


if __name__ == "__main__":
    main()
