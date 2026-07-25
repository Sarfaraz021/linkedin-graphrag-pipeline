"""Stage 2 orchestration: backbone load + semantic enrichment."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.pipeline.backbone import load_backbone
from backend.pipeline.config import Settings, get_settings
from backend.pipeline.corpus import iter_corpus_for_posts
from backend.pipeline.extract import extract_semantic_graph_async
from backend.pipeline.io_load import iter_structured_posts
from backend.pipeline.neo4j_client import Neo4jClient
from backend.pipeline.resolve import reconcile_llm_post_stubs, run_entity_resolution


def load_all_posts(settings: Settings) -> list[dict[str, Any]]:
    return list(iter_structured_posts(settings.input_dir))


def run_backbone(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    posts = load_all_posts(settings)
    with Neo4jClient(settings) as client:
        client.ensure_schema()
        return load_backbone(client, posts)


def run_semantic_graph(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for semantic extraction")

    posts = load_all_posts(settings)
    corpus_items: list[tuple[str, str]] = []
    for post_id, _records, corpus_text in iter_corpus_for_posts(
        posts,
        settings.processed_dir,
        include_reactor_profiles=settings.include_reactor_profiles,
    ):
        corpus_items.append((post_id, corpus_text))

    with Neo4jClient(settings) as client:
        extraction_results = []
        post_stubs_merged = 0
        for post_id, corpus_text in corpus_items:
            result = asyncio.run(
                extract_semantic_graph_async(client, settings, post_id, corpus_text)
            )
            extraction_results.append(result)
            post_stubs_merged += reconcile_llm_post_stubs(client, post_id)
        resolution_stats = run_entity_resolution(client, settings)
        resolution_stats["llm_post_stubs_merged"] = post_stubs_merged

    return {
        "posts_processed": len(corpus_items),
        "extraction_runs": len(extraction_results),
        "resolution": resolution_stats,
    }


def run_all(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    backbone_stats = run_backbone(settings)
    semantic_stats = run_semantic_graph(settings)
    return {"backbone": backbone_stats, "semantic": semantic_stats}
