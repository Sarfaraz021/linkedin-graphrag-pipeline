# LinkedIn → Knowledge Graph Pipeline

Two-stage pipeline plus a demo chat UI: scrape LinkedIn posts, load a hybrid knowledge graph into Neo4j, then query it in natural language.

```
Stage 1 (reference):  HarvestAPI → structured/<postId>.json
Stage 2 (pipeline):   structured JSON → backbone + LLM semantic layer → Neo4j
Demo UI:              React chat → FastAPI → GraphRAG (vectors + graph)
```

## Project layout

```
backend/
  pipeline/          # Stage 2 ETL (backbone, corpus, extract, resolve)
  api/               # FastAPI REST API for demo UI
  rag/               # GraphRAG query service (vector + graph context)
frontend/            # React demo chat UI (Vite)
scripts/             # Pipeline + demo launchers
config/              # kg_pipeline.yaml
data/raw/            # structured JSON input (gitignored)
reference/           # Stage 1 scraper + neo4j-graphrag docs (read-only)
tests/
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Neo4j Aura + OpenAI + HarvestAPI

# Demo UI (separate terminal)
cd frontend && npm install
```

## Run pipeline

```bash
export PYTHONPATH=.   # or use scripts/run_all.sh which sets this

python scripts/01_load_backbone.py          # deterministic graph (worked for you)
python scripts/02_build_semantic_graph.py   # LLM + vectors (re-run after resolve fix)
bash scripts/run_all.sh
```

## Run demo UI

Terminal 1 — API:
```bash
export PYTHONPATH=.
python scripts/start_api.py
```

Terminal 2 — Frontend:
```bash
cd frontend && npm run dev
```

Open **http://localhost:5173** and ask questions like:
- *Who commented on the post and what did they say?*
- *Which companies and awards were mentioned?*

Or one command: `bash scripts/start_demo.sh` (requires `npm install` in `frontend/`).

## Environment

| Variable | Purpose |
|---|---|
| `HARVEST_API_KEY` | Stage 1 scraper |
| `NEO4J_URI` | Aura: `neo4j+s://xxxx.databases.neo4j.io` |
| `NEO4J_USER` / `NEO4J_USERNAME` | Default `neo4j` |
| `NEO4J_PASSWORD` | Aura password |
| `OPENAI_API_KEY` | Semantic extraction + demo chat |

## Fixes applied

- **`02_build_semantic_graph.py` crash** — LLM sometimes writes `name` as a list; `normalize_name()` now coerces lists safely before fuzzy person reconciliation.
- **Code organization** — `src/` moved to `backend/pipeline/`; new `backend/api/` and `backend/rag/`; React frontend in `frontend/`.

## Tests

```bash
PYTHONPATH=. pytest tests/ -q
```

## Data governance

See `GOVERNANCE.md` before production use.
