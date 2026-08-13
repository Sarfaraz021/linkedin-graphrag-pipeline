"""Stage 2 orchestration: backbone load + semantic enrichment."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.pipeline.backbone import load_backbone
from backend.pipeline.classify import classify_and_persist_posts
from backend.pipeline.config import Settings, get_settings
from backend.pipeline.corpus import iter_corpus_for_posts
from backend.pipeline.entity_embed import embed_entities_async
from backend.pipeline.extract import extract_all_posts_async
from backend.pipeline.io_load import iter_structured_posts
from backend.pipeline.neo4j_client import Neo4jClient
from backend.pipeline.org_classify import (
    classify_and_persist_organisations,
    fix_merged_org_types,
)
from backend.pipeline.resolve import (
    fuzzy_resolve_semantic_entities_async,
    mark_resolved_semantic_nodes,
    reconcile_llm_person_stubs,
    reconcile_llm_post_stubs,
)


def load_all_posts(settings: Settings) -> list[dict[str, Any]]:
    return list(iter_structured_posts(settings.input_dir))


def run_backbone(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    posts = load_all_posts(settings)
    with Neo4jClient(settings) as client:
        client.ensure_schema()
        return load_backbone(client, posts)


async def _run_semantic_graph_async(
    client: Neo4jClient,
    settings: Settings,
    posts: list[dict[str, Any]],
    corpus_items: list[tuple[str, str, str]],
) -> dict[str, Any]:
    classification_results = classify_and_persist_posts(client, settings, posts)

    extraction_results = await extract_all_posts_async(
        client, settings, corpus_items
    )
    post_stubs_merged = 0
    for post_id, _, _ in corpus_items:
        post_stubs_merged += reconcile_llm_post_stubs(client, post_id)

    org_type_results = classify_and_persist_organisations(client, settings)

    person_merged = reconcile_llm_person_stubs(client)
    await fuzzy_resolve_semantic_entities_async(client, settings)
    mark_resolved_semantic_nodes(client)
    org_types_fixed = fix_merged_org_types(client)

    entities_embedded = await embed_entities_async(client, settings)

    return {
        "posts_processed": len(corpus_items),
        "classification": classification_results,
        "extraction_runs": len(extraction_results),
        "organisations_typed": len(org_type_results),
        "resolution": {
            "llm_person_stubs_merged": person_merged,
            "llm_post_stubs_merged": post_stubs_merged,
            "org_types_fixed_after_merge": org_types_fixed,
        },
        "entities_embedded": entities_embedded,
    }


def run_semantic_graph(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for semantic extraction")

    posts = load_all_posts(settings)
    post_urls = {
        p["post"]["id"]: p["post"].get("url") or p["post"].get("shareUrl") or ""
        for p in posts
    }
    corpus_items: list[tuple[str, str, str]] = []
    for post_id, _records, corpus_text in iter_corpus_for_posts(
        posts,
        settings.processed_dir,
        include_reactor_profiles=settings.include_reactor_profiles,
    ):
        corpus_items.append((post_id, corpus_text, post_urls.get(post_id, "")))

    with Neo4jClient(settings) as client:
        return asyncio.run(
            _run_semantic_graph_async(client, settings, posts, corpus_items)
        )


def run_all(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    backbone_stats = run_backbone(settings)
    semantic_stats = run_semantic_graph(settings)
    return {"backbone": backbone_stats, "semantic": semantic_stats}
