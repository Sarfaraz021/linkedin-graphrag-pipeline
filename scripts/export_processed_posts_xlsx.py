#!/usr/bin/env python3
"""Export clean processed post JSON from data/raw to a single Excel summary."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from backend.pipeline.config import get_settings  # noqa: E402
from backend.pipeline.io_load import iter_structured_posts  # noqa: E402
from backend.pipeline.neo4j_client import Neo4jClient  # noqa: E402

DEFAULT_INPUT = ROOT / "data" / "raw"
DEFAULT_OUTPUT = ROOT / "data" / "processed_posts_summary.xlsx"

COLUMNS = [
    "post_id",
    "linkedin_url",
    "share_url",
    "posted_at",
    "category",
    "author_name",
    "author_linkedin_url",
    "author_headline",
    "author_company",
    "post_content",
    "reactions_total",
    "comments_total",
    "shares_total",
    "mentions_companies",
    "mentions_people",
    "unique_people_count",
    "commenters_count",
    "reactors_count",
    "in_neo4j",
]


def _join_names(mentions: list[dict], mtype: str) -> str:
    names = [m.get("name", "") for m in mentions if m.get("type") == mtype and m.get("name")]
    return "; ".join(names)


def _row_from_post(data: dict, category: str | None, in_neo4j: bool) -> dict:
    post = data["post"]
    people = data.get("people") or {}
    author = people.get(post.get("authorId") or "", {})
    engagement = post.get("engagement") or {}
    mentions = post.get("mentions") or []

    return {
        "post_id": post.get("id", ""),
        "linkedin_url": post.get("url", ""),
        "share_url": post.get("shareUrl", ""),
        "posted_at": post.get("postedAt", ""),
        "category": category or "",
        "author_name": author.get("name", ""),
        "author_linkedin_url": author.get("url", ""),
        "author_headline": author.get("headline", ""),
        "author_company": author.get("currentCompany", ""),
        "post_content": post.get("content", ""),
        "reactions_total": engagement.get("reactionsTotal", 0),
        "comments_total": engagement.get("commentsTotal", 0),
        "shares_total": engagement.get("sharesTotal", 0),
        "mentions_companies": _join_names(mentions, "company"),
        "mentions_people": _join_names(mentions, "person"),
        "unique_people_count": len(people),
        "commenters_count": len(data.get("comments") or []),
        "reactors_count": len(data.get("reactions") or []),
        "in_neo4j": in_neo4j,
    }


def _neo4j_post_meta() -> tuple[dict[str, str], set[str]]:
    settings = get_settings()
    try:
        with Neo4jClient(settings) as client:
            rows = client.run(
                "MATCH (p:Post) RETURN p.id AS id, p.category AS category"
            )
            categories = {r["id"]: r.get("category") or "" for r in rows}
            return categories, set(categories)
    except Exception:
        return {}, set()


def export_posts(
    input_dir: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
) -> Path:
    categories, neo4j_ids = _neo4j_post_meta()
    rows = []
    for data in iter_structured_posts(input_dir):
        post_id = data["post"]["id"]
        rows.append(
            _row_from_post(
                data,
                category=categories.get(post_id),
                in_neo4j=post_id in neo4j_ids,
            )
        )

    rows.sort(key=lambda r: r.get("posted_at") or "")
    df = pd.DataFrame(rows, columns=COLUMNS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False, sheet_name="Processed Posts")
    return output_path


def main() -> None:
    out = export_posts()
    print(f"Exported {len(pd.read_excel(out))} posts -> {out}")


if __name__ == "__main__":
    main()
