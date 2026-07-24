"""Deterministic backbone: Person, Post, and social edges into Neo4j."""

from __future__ import annotations

import json
from typing import Any

from src.io_load import count_expected_backbone
from src.neo4j_client import Neo4jClient

RECORD_SEPARATOR = "\n---\n"


def _person_row(person_id: str, person: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": person_id,
        "name": person.get("name"),
        "headline": person.get("headline"),
        "linkedinUrl": person.get("url"),
        "location": person.get("location"),
        "country": person.get("country"),
        "currentCompany": person.get("currentCompany"),
        "connectionsCount": person.get("connectionsCount"),
        "followerCount": person.get("followerCount"),
        "openToWork": person.get("openToWork"),
        "avatarUrl": person.get("avatarUrl"),
        "source": "backbone",
    }


def _post_row(post: dict[str, Any]) -> dict[str, Any]:
    engagement = post.get("engagement") or {}
    breakdown = engagement.get("reactionBreakdown") or {}
    row: dict[str, Any] = {
        "id": post["id"],
        "url": post.get("url"),
        "shareUrl": post.get("shareUrl"),
        "postedAt": post.get("postedAt"),
        "content": post.get("content"),
        "reactionsTotal": engagement.get("reactionsTotal"),
        "commentsTotal": engagement.get("commentsTotal"),
        "sharesTotal": engagement.get("sharesTotal"),
        "reactionBreakdownJson": json.dumps(breakdown),
        "source": "backbone",
    }
    for reaction_type, count in breakdown.items():
        row[f"reactions_{reaction_type}"] = count
    return row


def _mention_rows(mentions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for mention in mentions:
        rows.append(
            {
                "mentionType": mention.get("type"),
                "id": mention.get("id"),
                "name": mention.get("name"),
                "url": mention.get("url"),
            }
        )
    return rows


def _comment_rows(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "personId": c.get("personId"),
            "commentId": c.get("id"),
            "commentary": c.get("text"),
            "createdAt": c.get("createdAt"),
            "commentUrl": c.get("url"),
            "reactionsOnComment": c.get("reactionsOnComment"),
        }
        for c in comments
        if c.get("personId")
    ]


def _reaction_rows(reactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "personId": r.get("personId"),
            "reactionType": r.get("type"),
            "reactionId": r.get("id"),
        }
        for r in reactions
        if r.get("personId")
    ]


def load_backbone_post(client: Neo4jClient, data: dict[str, Any]) -> dict[str, int]:
    """Idempotently MERGE one structured post into Neo4j. Returns expected counts."""
    post = data["post"]
    post_id = post["id"]
    people = data.get("people") or {}

    person_rows = [_person_row(pid, person) for pid, person in people.items()]
    if person_rows:
        client.run_write(
            """
            UNWIND $rows AS row
            MERGE (p:Person {id: row.id})
            SET p += row,
                p.updatedAt = datetime()
            """,
            {"rows": person_rows},
        )

    client.run_write(
        """
        MERGE (post:Post {id: $row.id})
        SET post += $row,
            post.updatedAt = datetime()
        """,
        {"row": _post_row(post)},
    )

    if post.get("authorId"):
        client.run_write(
            """
            MATCH (post:Post {id: $post_id})
            MATCH (author:Person {id: $author_id})
            MERGE (author)-[r:AUTHORED]->(post)
            SET r.updatedAt = datetime()
            """,
            {"post_id": post_id, "author_id": post["authorId"]},
        )

    comment_rows = _comment_rows(data.get("comments") or [])
    if comment_rows:
        client.run_write(
            """
            MATCH (post:Post {id: $post_id})
            UNWIND $rows AS row
            MATCH (p:Person {id: row.personId})
            MERGE (p)-[r:COMMENTED {commentId: row.commentId}]->(post)
            SET r.commentary = row.commentary,
                r.createdAt = row.createdAt,
                r.commentUrl = row.commentUrl,
                r.reactionsOnComment = row.reactionsOnComment,
                r.updatedAt = datetime()
            """,
            {"post_id": post_id, "rows": comment_rows},
        )

    reaction_rows = _reaction_rows(data.get("reactions") or [])
    if reaction_rows:
        client.run_write(
            """
            MATCH (post:Post {id: $post_id})
            UNWIND $rows AS row
            MATCH (p:Person {id: row.personId})
            MERGE (p)-[r:REACTED {type: row.reactionType}]->(post)
            SET r.reactionId = row.reactionId,
                r.updatedAt = datetime()
            """,
            {"post_id": post_id, "rows": reaction_rows},
        )

    mention_rows = _mention_rows(post.get("mentions") or [])
    for row in mention_rows:
        if row["mentionType"] == "company" and row.get("id"):
            client.run_write(
                """
                MATCH (post:Post {id: $post_id})
                MERGE (c:Company {id: $company_id})
                SET c.name = $name,
                    c.url = $url,
                    c.source = 'backbone',
                    c.updatedAt = datetime()
                MERGE (post)-[r:MENTIONS]->(c)
                SET r.updatedAt = datetime()
                """,
                {
                    "post_id": post_id,
                    "company_id": row["id"],
                    "name": row.get("name"),
                    "url": row.get("url"),
                },
            )
        elif row["mentionType"] == "person" and row.get("id"):
            client.run_write(
                """
                MATCH (post:Post {id: $post_id})
                MERGE (p:Person {id: $person_id})
                ON CREATE SET p.name = $name,
                              p.linkedinUrl = $url,
                              p.source = 'backbone'
                SET p.name = coalesce(p.name, $name),
                    p.linkedinUrl = coalesce(p.linkedinUrl, $url),
                    p.updatedAt = datetime()
                MERGE (post)-[r:MENTIONS]->(p)
                SET r.updatedAt = datetime()
                """,
                {
                    "post_id": post_id,
                    "person_id": row["id"],
                    "name": row.get("name"),
                    "url": row.get("url"),
                },
            )

    return count_expected_backbone(data)


def load_backbone(client: Neo4jClient, posts: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"authored": 0, "commented": 0, "reacted": 0, "mentions": 0, "people": 0, "posts": 0}
    for data in posts:
        counts = load_backbone_post(client, data)
        for key in totals:
            totals[key] += counts[key]
    return totals
