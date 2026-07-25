"""LLM semantic extraction and embeddings via neo4j-graphrag."""

from __future__ import annotations

import asyncio
from typing import Any

from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline
from neo4j_graphrag.llm import OpenAILLM

from backend.pipeline.chunking import RecordCountSplitter
from backend.pipeline.config import Settings
from backend.pipeline.neo4j_client import Neo4jClient
from backend.pipeline.schema import get_semantic_schema_dict

SEMANTIC_PROMPT = """Extract entities and relationships from LinkedIn post records.

Rules:
- Person nodes MUST include both name and url when a LinkedIn profile URL appears in the text.
- Do NOT invent Person ids. Use name + url only for Person nodes.
- Do NOT extract MENTIONS relationships — those are loaded separately.
- Focus on companies, awards, events, topics, skills, job titles, and locations from free text.
- Prefer relationships defined in the schema patterns.

Text to analyze:
{text}
"""


def build_kg_pipeline(client: Neo4jClient, settings: Settings) -> SimpleKGPipeline:
    llm = OpenAILLM(
        model_name=settings.llm_model,
        api_key=settings.openai_api_key,
        model_params={"temperature": 0},
    )
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
) -> Any:
    if not corpus_text.strip():
        return None
    pipeline = build_kg_pipeline(client, settings)
    return await pipeline.run_async(
        text=corpus_text,
        file_path=f"linkedin/post/{post_id}",
        document_metadata={"postId": post_id, "source": "semantic_layer"},
    )


def extract_semantic_graph(
    client: Neo4jClient,
    settings: Settings,
    post_id: str,
    corpus_text: str,
) -> Any:
    return asyncio.run(
        extract_semantic_graph_async(client, settings, post_id, corpus_text)
    )


async def extract_all_posts_async(
    client: Neo4jClient,
    settings: Settings,
    corpus_items: list[tuple[str, str]],
) -> list[Any]:
    results = []
    for post_id, corpus_text in corpus_items:
        result = await extract_semantic_graph_async(
            client, settings, post_id, corpus_text
        )
        results.append(result)
    return results
