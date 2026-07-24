# LinkedIn → Knowledge Graph Pipeline

Two-stage pipeline: scrape LinkedIn posts (Stage 1), then load a hybrid knowledge graph into Neo4j with deterministic social structure plus LLM semantic enrichment (Stage 2).

```
Stage 1 (reference):  URLs → HarvestAPI → structured/<postId>.json
Stage 2 (this repo):  structured JSON → backbone MERGE + LLM extract/embed/resolve → Neo4j
```

## Architecture

**Deterministic backbone (authoritative)** — Person and Post nodes keyed on stable LinkedIn ids; social edges (`AUTHORED`, `COMMENTED`, `REACTED`, `MENTIONS`) loaded without LLM involvement.

**LLM semantic layer (enrichment)** — Entity extraction over post/comment/profile text for `Company`, `Award`, `Event`, `Topic`, `Skill`, `JobTitle`, `Location` and schema-defined relationships. Person/Post nodes are never created or merged by the LLM.

See `reference/neo4j_graphrag_docs.md` for the underlying neo4j-graphrag APIs.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in Neo4j + OpenAI credentials
```

**Prerequisites**

- Neo4j 5.24+ (local or Aura) with **APOC** for fuzzy entity resolution
- OpenAI API key for semantic extraction and embeddings
- Stage 1 output: copy `structured/*.json` into `data/raw/`

## Run

```bash
# Backbone only (no OpenAI calls)
python scripts/01_load_backbone.py

# Semantic layer (requires OPENAI_API_KEY)
python scripts/02_build_semantic_graph.py

# Full pipeline
bash scripts/run_all.sh
```

Both steps are idempotent — safe to re-run.

## Configuration

Environment variables (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection |
| `NEO4J_DATABASE` | `neo4j` | Target database |
| `OPENAI_API_KEY` | — | Required for semantic step |
| `LLM_MODEL` | `gpt-4o-mini` | Extraction model |
| `EMBED_MODEL` | `text-embedding-3-small` | Chunk embeddings |
| `CHUNK_RECORDS` | `30` | Records per LLM chunk |
| `CHUNK_OVERLAP` | `5` | Overlap between chunks |
| `INCLUDE_REACTOR_PROFILES` | `false` | Include reactor headlines in corpus |

YAML config for `SimpleKGPipeline` is in `config/kg_pipeline.yaml`.

## Tests

```bash
pytest tests/ -q
```

## Data governance

This project processes personal data. Read `GOVERNANCE.md` before production use.

## Reference

- `reference/linkedin_scraper/` — Stage 1 scraper (read-only; do not modify from Stage 2 work)
- `reference/neo4j_graphrag_docs.md` — Knowledge Graph Builder documentation
