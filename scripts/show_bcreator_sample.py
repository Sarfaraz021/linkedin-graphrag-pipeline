#!/usr/bin/env python3
"""Print bCreator post acceptance snapshot from Neo4j (Changes 1–3 review)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.pipeline.config import get_settings
from backend.pipeline.neo4j_client import Neo4jClient

POST_ID = "7470802348391673856"


def main() -> None:
    settings = get_settings()
    with Neo4jClient(settings) as client:
        post = client.run(
            """
            MATCH (post:Post {id: $post_id})
            OPTIONAL MATCH (author:Person)-[:WROTE]->(post)
            RETURN post.id AS id,
                   post.category AS category,
                   post.categoryConfidence AS categoryConfidence,
                   post.categoryEvidence AS categoryEvidence,
                   left(post.content, 120) AS contentPreview,
                   author.name AS authorName
            """,
            {"post_id": POST_ID},
        )
        mentions = client.run(
            """
            MATCH (post:Post {id: $post_id})-[:MENTIONS]->(o:Organisation)
            RETURN o.name AS name, o.id AS id
            ORDER BY name
            """,
            {"post_id": POST_ID},
        )
        semantic_edges = client.run(
            """
            MATCH (a)-[r:SUPPORTED_BY|NOMINATED_FOR|SPONSORS|FOUNDED|INVESTED_IN|LISTED_IN]->(b)
            WHERE r.confidence_score IS NOT NULL
               OR r.source_post_url IS NOT NULL
               OR r.evidence_text IS NOT NULL
            RETURN labels(a)[0] AS fromLabel,
                   coalesce(a.name, head(a.name)) AS fromName,
                   type(r) AS rel,
                   labels(b)[0] AS toLabel,
                   coalesce(b.name, head(b.name)) AS toName,
                   r.confidence_score AS confidence,
                   r.source_post_url AS sourcePostUrl,
                   left(r.evidence_text, 80) AS evidence
            LIMIT 25
            """
        )
        labels = client.run(
            """
            MATCH (n)
            RETURN labels(n)[0] AS label, count(n) AS count
            ORDER BY count DESC
            LIMIT 20
            """
        )

    snapshot = {
        "post": post[0] if post else None,
        "organisation_mentions": mentions,
        "semantic_edges_with_provenance": semantic_edges,
        "node_counts": labels,
    }
    print(json.dumps(snapshot, indent=2, default=str))


if __name__ == "__main__":
    main()
