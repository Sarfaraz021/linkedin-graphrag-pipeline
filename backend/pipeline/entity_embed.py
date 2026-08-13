"""Embed resolved semantic entities (Organisation/Brand/Award/Event/Programme/...)
so retrieval can do vector search over entity identity, not just chunk text."""

from __future__ import annotations

import asyncio

from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings

from backend.pipeline.config import Settings
from backend.pipeline.neo4j_client import Neo4jClient

BATCH_SIZE = 64


def _coerce_scalar(value: object | None) -> str | None:
    # apoc.refactor.mergeNodes(properties: 'combine') turns a scalar property into a
    # list when fuzzy-resolved duplicates disagree (e.g. two name spellings); take
    # the longest variant defensively so embedding text is never a raw Python list.
    if isinstance(value, list):
        strs = [v for v in value if isinstance(v, str) and v]
        return max(strs, key=len) if strs else None
    return value if isinstance(value, str) and value else None


def _entity_text(name: str, labels: list[str], org_type: str | list[str] | None) -> str:
    label_str = " ".join(l for l in labels if l not in ("__Entity__", "Resolved"))
    name = _coerce_scalar(name) or ""
    org_type = _coerce_scalar(org_type)
    parts = [label_str, name]
    if org_type:
        parts.append(f"(orgType: {org_type})")
    return " ".join(p for p in parts if p)


async def _embed_batch(embedder: OpenAIEmbeddings, texts: list[str]) -> list[list[float]]:
    return await asyncio.gather(*(embedder.async_embed_query(t) for t in texts))


async def embed_entities_async(client: Neo4jClient, settings: Settings) -> int:
    """Embed every :__Entity__ node with a name into entity_embedding. Idempotent."""
    embedder = OpenAIEmbeddings(model=settings.embed_model, api_key=settings.openai_api_key)
    rows = client.run(
        """
        MATCH (n:__Entity__)
        WHERE n.name IS NOT NULL AND n.name <> ''
        RETURN elementId(n) AS id, n.name AS name, labels(n) AS labels, n.orgType AS orgType
        """
    )
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        texts = [_entity_text(row["name"], row["labels"], row.get("orgType")) for row in batch]
        vectors = await _embed_batch(embedder, texts)  # concurrent, not sequential
        write_rows = [
            {"id": row["id"], "vector": vector, "text": text}
            for row, vector, text in zip(batch, vectors, texts)
        ]
        client.run_write(
            """
            UNWIND $rows AS row
            MATCH (n) WHERE elementId(n) = row.id
            SET n.entity_embedding = row.vector,
                n.entity_embedding_text = row.text
            """,
            {"rows": write_rows},
        )
        total += len(batch)
    return total


def embed_entities(client: Neo4jClient, settings: Settings) -> int:
    """Sync wrapper for CLI/script use. Do NOT call from inside a running event
    loop (e.g. from pipeline._run_semantic_graph_async) — use embed_entities_async."""
    return asyncio.run(embed_entities_async(client, settings))
