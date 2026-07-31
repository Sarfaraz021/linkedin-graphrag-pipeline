"""LLM semantic extraction and embeddings via neo4j-graphrag."""

from __future__ import annotations

import asyncio
from typing import Any

from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline
from backend.pipeline.chunking import RecordCountSplitter
from backend.pipeline.llm_factory import build_llm
from backend.pipeline.config import Settings
from backend.pipeline.neo4j_client import Neo4jClient
from backend.pipeline.schema import get_semantic_schema_dict

SEMANTIC_PROMPT = """Extract entities and relationships from LinkedIn post records for an FMCG / challenger-brand ecosystem graph.

Rules:
- Use client labels: Organisation (not Company), Brand, Retailer, Founder, Investor, Buyer,
  Category, Trend, Award, Event, Programme, Accelerator, Distributor, Location, Person.
- Person/Founder/Investor nodes MUST include name and url when a LinkedIn profile URL appears.
- Do NOT invent Person ids. Use name + url only for Person-like nodes.
- Do NOT extract MENTIONS or WROTE — those are loaded deterministically from structured data.
- For every relationship you infer, set properties:
  confidence_score (0-1), source_post_url, evidence_text (short quote from the text).
- Focus on awards, sponsors, organisations, brands, retailers, investors, programmes, events, categories.
- Example: Monique Anderson NOMINATED_FOR bCreator Talent Manager of the Year;
  bCreator (Organisation) SUPPORTED_BY ITV (Organisation as sponsor).

Text to analyze:
{text}
"""


def build_kg_pipeline(client: Neo4jClient, settings: Settings) -> SimpleKGPipeline:
    llm = build_llm(settings)
    embedder = OpenAIEmbeddings(
        model=settings.embed_model,
        api_key=settings.openai_api_key,
    )
    splitter = RecordCountSplitter(
        chunk_records=settings.chunk_records,
        chunk_overlap=settings.chunk_overlap,
    )
    return SimpleKGPipeline(
        llm=llm,
        driver=client.driver,
        embedder=embedder,
        schema=get_semantic_schema_dict(),
        from_file=False,
        text_splitter=splitter,
        perform_entity_resolution=False,
        on_error="IGNORE",
        prompt_template=SEMANTIC_PROMPT,
        neo4j_database=settings.neo4j_database,
    )


async def extract_semantic_graph_async(
    client: Neo4jClient,
    settings: Settings,
    post_id: str,
    corpus_text: str,
    post_url: str = "",
) -> Any:
    if not corpus_text.strip():
        return None
    pipeline = build_kg_pipeline(client, settings)
    metadata = {"postId": post_id, "source": "semantic_layer"}
    if post_url:
        metadata["postUrl"] = post_url
    return await pipeline.run_async(
        text=corpus_text,
        file_path=f"linkedin/post/{post_id}",
        document_metadata=metadata,
    )


def extract_semantic_graph(
    client: Neo4jClient,
    settings: Settings,
    post_id: str,
    corpus_text: str,
    post_url: str = "",
) -> Any:
    return asyncio.run(
        extract_semantic_graph_async(client, settings, post_id, corpus_text, post_url)
    )


async def extract_all_posts_async(
    client: Neo4jClient,
    settings: Settings,
    corpus_items: list[tuple[str, str, str]],
) -> list[Any]:
    results = []
    for post_id, corpus_text, post_url in corpus_items:
        result = await extract_semantic_graph_async(
            client, settings, post_id, corpus_text, post_url
        )
        results.append(result)
    return results
