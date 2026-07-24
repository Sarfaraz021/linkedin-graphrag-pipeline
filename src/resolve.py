"""Entity resolution: reconcile LLM stubs and merge semantic duplicates."""

from __future__ import annotations

import asyncio
import re
import unicodedata

from neo4j_graphrag.experimental.components.resolver import FuzzyMatchResolver

from src.config import Settings
from src.neo4j_client import Neo4jClient
from src.schema import SEMANTIC_NODE_LABELS

RESOLVED_LABEL = "Resolved"


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("'", "").replace("'", "").replace("`", "")
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(text.split())


def reconcile_llm_post_stubs(client: Neo4jClient, post_id: str) -> int:
    """Merge LLM Post stubs into the backbone Post for this post id."""
    rows = client.run(
        """
        MATCH (stub:Post:__Entity__)
        WHERE stub.id IS NULL
        MATCH (target:Post {id: $post_id})
        RETURN elementId(stub) AS stubId, elementId(target) AS targetId
        LIMIT 50
        """,
        {"post_id": post_id},
    )
    merged = 0
    for row in rows:
        _merge_stub_into_target(client, row["stubId"], row["targetId"])
        merged += 1
    return merged


def _merge_stub_into_target(client: Neo4jClient, stub_id: str, target_id: str) -> None:
    try:
        client.run_write(
            """
            MATCH (stub) WHERE elementId(stub) = $stub_id
            MATCH (target) WHERE elementId(target) = $target_id
            WITH collect(stub) + collect(target) AS nodes
            CALL apoc.refactor.mergeNodes(nodes, {properties: 'combine', mergeRels: true})
            YIELD node
            RETURN node
            """,
            {"stub_id": stub_id, "target_id": target_id},
        )
    except Exception:
        client.run_write(
            """
            MATCH (stub) WHERE elementId(stub) = $stub_id
            MATCH (target) WHERE elementId(target) = $target_id
            WITH stub, target
            OPTIONAL MATCH (stub)-[r]->(n)
            FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END |
              MERGE (target)-[nr:type(r)]->(n)
              SET nr += properties(r)
            )
            WITH stub, target
            OPTIONAL MATCH (n)-[r]->(stub)
            FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END |
              MERGE (n)-[nr:type(r)]->(target)
              SET nr += properties(r)
            )
            WITH stub
            DELETE stub
            """,
            {"stub_id": stub_id, "target_id": target_id},
        )


def reconcile_llm_person_stubs(client: Neo4jClient) -> int:
    """Merge __Entity__ Person stubs into backbone Person nodes by url or scoped name."""
    rows = client.run(
        """
        MATCH (stub:Person:__Entity__)
        WHERE stub.id IS NULL
        RETURN elementId(stub) AS stubId, stub.name AS name,
               coalesce(stub.url, stub.linkedinUrl) AS url
        """
    )
    merged = 0
    for row in rows:
        stub_id = row["stubId"]
        url = row.get("url")
        name = row.get("name")
        backbone = None

        if url:
            matches = client.run(
                """
                MATCH (p:Person)
                WHERE p.id IS NOT NULL
                  AND p.linkedinUrl = $url
                RETURN elementId(p) AS id
                LIMIT 1
                """,
                {"url": url},
            )
            backbone = matches[0]["id"] if matches else None

        if not backbone and name:
            norm = normalize_name(name)
            matches = client.run(
                """
                MATCH (p:Person)
                WHERE p.id IS NOT NULL AND p.name IS NOT NULL
                RETURN elementId(p) AS id, p.name AS name
                """,
            )
            for candidate in matches:
                if normalize_name(candidate["name"]) == norm:
                    backbone = candidate["id"]
                    break

        if not backbone:
            continue

        _merge_stub_into_target(client, stub_id, backbone)
        merged += 1
    return merged


def mark_resolved_semantic_nodes(client: Neo4jClient) -> None:
    for label in SEMANTIC_NODE_LABELS:
        client.run_write(
            f"""
            MATCH (n:{label}:__Entity__)
            WHERE NOT n:{RESOLVED_LABEL}
            SET n:{RESOLVED_LABEL} = true
            """
        )


async def fuzzy_resolve_semantic_entities_async(
    client: Neo4jClient,
    settings: Settings,
) -> None:
    filter_query = f"WHERE NOT entity:{RESOLVED_LABEL}"
    for label in SEMANTIC_NODE_LABELS:
        label_filter = f"{filter_query} AND '{label}' IN labels(entity)"
        resolver = FuzzyMatchResolver(
            driver=client.driver,
            filter_query=label_filter,
            resolve_properties=["name"],
            similarity_threshold=settings.fuzzy_similarity_threshold,
            neo4j_database=settings.neo4j_database,
        )
        try:
            await resolver.run()
        except Exception as exc:
            if "apoc" in str(exc).lower():
                raise RuntimeError(
                    "FuzzyMatchResolver requires APOC (apoc.refactor.mergeNodes). "
                    "Install APOC or use Neo4j Aura."
                ) from exc
            raise
        client.run_write(
            f"""
            MATCH (n:{label}:__Entity__)
            SET n:{RESOLVED_LABEL} = true
            """
        )


def run_entity_resolution(client: Neo4jClient, settings: Settings) -> dict[str, int]:
    person_merged = reconcile_llm_person_stubs(client)
    asyncio.run(fuzzy_resolve_semantic_entities_async(client, settings))
    mark_resolved_semantic_nodes(client)
    return {"llm_person_stubs_merged": person_merged}
