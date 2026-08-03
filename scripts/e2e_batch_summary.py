#!/usr/bin/env python3
"""Print summary stats after an e2e batch run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.pipeline.config import get_settings
from backend.pipeline.neo4j_client import Neo4jClient


def main() -> None:
    settings = get_settings()
    raw_count = len(list(settings.input_dir.glob("*.json")))

    with Neo4jClient(settings) as client:
        labels = client.run(
            """
            MATCH (n)
            RETURN labels(n)[0] AS label, count(n) AS count
            ORDER BY count DESC
            LIMIT 15
            """
        )
        posts = client.run(
            """
            MATCH (p:Post)
            RETURN p.id AS id,
                   p.category AS category,
                   p.categoryConfidence AS confidence
            ORDER BY p.id
            LIMIT 50
            """
        )
        rels = client.run(
            """
            MATCH ()-[r]->()
            RETURN type(r) AS rel, count(r) AS count
            ORDER BY count DESC
            LIMIT 15
            """
        )
        categories = client.run(
            """
            MATCH (p:Post)
            WHERE p.category IS NOT NULL
            RETURN p.category AS category, count(p) AS count
            ORDER BY count DESC
            """
        )

    summary = {
        "structured_files_in_raw": raw_count,
        "node_counts": labels,
        "relationship_counts": rels,
        "post_categories": categories,
        "classified_posts_sample": posts[:20],
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
