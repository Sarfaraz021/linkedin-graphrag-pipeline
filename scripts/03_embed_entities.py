#!/usr/bin/env python3
"""Embed resolved semantic entities for entity-level vector search. Idempotent, re-runnable."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline.config import get_settings
from backend.pipeline.entity_embed import embed_entities
from backend.pipeline.neo4j_client import Neo4jClient


def main() -> None:
    settings = get_settings()
    with Neo4jClient(settings) as client:
        client.ensure_schema()
        count = embed_entities(client, settings)
        print(f"Embedded {count} entities into entity_embedding.")


if __name__ == "__main__":
    main()
