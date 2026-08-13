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

Return result as JSON using exactly this format (this is the only output — no markdown, no
commentary, no backticks, no text before or after the JSON object):
{{"nodes": [ {{"id": "0", "label": "Person", "properties": {{"name": "John"}} }}],
"relationships": [{{"type": "FOUNDED", "start_node_id": "0", "end_node_id": "1", "properties": {{"confidence_score": 0.9, "source_post_url": "...", "evidence_text": "..."}} }}] }}
Assign a unique string id to each node and reuse it in relationships. Property names must be
enclosed in double quotes. The JSON object must not be wrapped in a list.

Rules:
- Use client labels: Organisation (not Company), Brand, Retailer, Founder, Investor, Buyer,
  Category, Trend, Award, Event, Programme, Accelerator, Distributor, Location, Person.
- Person/Founder/Investor nodes MUST include name and url when a LinkedIn profile URL appears.
- Do NOT invent Person ids. Use name + url only for Person-like nodes.
- Do NOT extract MENTIONS or WROTE — those are loaded deterministically from structured data.
- For every relationship you infer, set properties:
  confidence_score (0-1), source_post_url, evidence_text (short quote from the text).
- Focus on awards, sponsors, organisations, brands, retailers, investors, programmes, events, categories.

MONEY RELATIONSHIPS — these are NOT interchangeable. Pick exactly the one the text supports:
- SPONSORS: an organisation pays to be associated with (headline/backs/sponsors) an
  Award/Event/Programme. This is marketing spend, NOT funding a business.
- INVESTED_IN: an Investor puts equity capital into a Brand/Organisation for an ownership stake.
- FUNDS: an organisation gives grant/non-equity money directly to a Brand/Organisation
  (no award/event attached, no equity taken).
- SUPPORTED_BY: non-financial support only — mentorship, visibility, endorsement, platform.
Never emit more than one of these for the same fact, and never use SUPPORTED_BY or SPONSORS
to describe money changing hands.

Example patterns (illustrative ONLY — these entity names, brand placeholders, and quotes are
NOT real and must NEVER appear in your output; only extract facts that are literally present
in the "Text to analyze" section below):
- "<Org A> as headline sponsors" of "<Award/Event name>" -> <Org A> (Organisation) -[SPONSORS]->
  <Award/Event name> (Award/Event). Do NOT also emit FUNDS/INVESTED_IN for <Org A> — sponsoring
  is not funding a business. (Real case: ITV sponsoring bCreator is SPONSORS, and ITV must never
  be tagged as a funder or investor.)
- "<Org B> gave us a £<amount> grant, no equity taken" -> <Org B> (Organisation) -[FUNDS]->
  [the brand] (Brand).
- "<Investor C> led our seed round" / "closed our funding round with backing from <Investor C>"
  -> <Investor C> (Investor) -[INVESTED_IN]-> [the brand] (Brand).
If a post mentions raising money (e.g. "closed our SEIS/seed round") but does not name a
specific investor/funder organisation, do NOT invent one — extract only what is named.

LABELLING RULE for SPONSORS targets: SPONSORS only connects an Organisation to an Award,
Event, or Programme — never to another Organisation. If the sponsored thing is a named award
programme or ceremony (e.g. "bCreator", "the Sephora Prize", any "X Awards"), label THAT node
as Award (not Organisation), even if its name looks like a company/brand name. Getting this
label wrong silently drops the whole SPONSORS fact.

CRITICAL: evidence_text must be an exact substring copied from the "Text to analyze" section
below, never from these example patterns. Never invent, assume, or reuse an organisation name,
amount, or quote that does not literally appear in the text you are extracting from.

Text to analyze:
{text}
"""


SEMANTIC_RELATIONSHIP_TYPES = {
    "FOUNDED", "WORKS_AT", "LISTED_IN", "SUPPORTED_BY", "OPERATES_IN",
    "INVESTED_IN", "FUNDS", "BASED_IN", "NOMINATED_FOR", "SPONSORS",
    "RUNS", "PARTICIPATED_IN",
}


def _semantic_edge_count(result: Any) -> int | None:
    """None means unknown (don't retry); a real pipeline result always has this shape."""
    try:
        rel_per_type = result.result["writer"]["metadata"]["statistics"]["rel_per_type"]
    except (AttributeError, KeyError, TypeError):
        return None
    return sum(v for k, v in rel_per_type.items() if k in SEMANTIC_RELATIONSHIP_TYPES)


def _delete_document_and_chunks(client: Neo4jClient, file_path: str) -> None:
    client.run_write(
        """
        MATCH (d:Document {path: $path})
        OPTIONAL MATCH (d)<-[:FROM_DOCUMENT]-(c:Chunk)
        DETACH DELETE d, c
        """,
        {"path": file_path},
    )


def build_kg_pipeline(client: Neo4jClient, settings: Settings) -> SimpleKGPipeline:
    # json_mode is required here: without it the model sometimes answers in prose/
    # markdown instead of strict JSON on long/complex chunks, and neo4j-graphrag's
    # extractor silently drops that chunk's relationships ("LLM response has
    # improper format", swallowed internally — not surfaced even with on_error="RAISE").
    llm = build_llm(settings, json_mode=True)
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
    _retry: bool = True,
) -> Any:
    if not corpus_text.strip():
        return None
    pipeline = build_kg_pipeline(client, settings)
    file_path = f"linkedin/post/{post_id}"
    metadata = {"postId": post_id, "source": "semantic_layer"}
    if post_url:
        metadata["postUrl"] = post_url
    result = await pipeline.run_async(
        text=corpus_text,
        file_path=file_path,
        document_metadata=metadata,
    )
    # neo4j-graphrag's on_error="IGNORE" silently drops a chunk's relationships when
    # the LLM's JSON response fails schema validation (no exception, no log by
    # default) — this is genuine LLM output-format variance even at temperature=0,
    # not a schema bug. Retry once if a substantial post yielded zero semantic
    # edges; clean up the partial Document/Chunk nodes first so the retry is a
    # clean re-run rather than accumulating duplicates.
    edge_count = _semantic_edge_count(result)
    if _retry and edge_count == 0 and len(corpus_text) > 500:
        _delete_document_and_chunks(client, file_path)
        return await extract_semantic_graph_async(
            client, settings, post_id, corpus_text, post_url, _retry=False
        )
    return result


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
