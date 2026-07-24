# Neo4j GraphRAG — Knowledge Graph Builder (reference)

Condensed reference for Stage 2. Full docs: https://neo4j.com/docs/neo4j-graphrag-python/current/knowledge_graph_builder.html

## SimpleKGPipeline

```python
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline

kg_builder = SimpleKGPipeline(
    llm=llm,
    driver=neo4j_driver,
    embedder=embedder,
    schema={...},
    from_file=False,
    text_splitter=text_splitter,
    perform_entity_resolution=False,
    neo4j_database="neo4j",
)
await kg_builder.run_async(text="...", document_metadata={"postId": "..."})
```

## TextSplitter

Subclass `neo4j_graphrag.experimental.components.text_splitters.base.TextSplitter`:

```python
async def run(self, text: str) -> TextChunks:
    ...
```

Returns `TextChunks(chunks=[TextChunk(text=..., index=..., metadata={...})])`.

## Schema

Pass dict with `node_types`, `relationship_types`, `patterns`, and filtering flags:

```python
schema = {
    "node_types": [...],
    "relationship_types": [...],
    "patterns": [["Person", "WORKS_AT", "Company"]],
    "additional_node_types": False,
    "additional_relationship_types": False,
}
```

## Entity resolution

- `FuzzyMatchResolver(driver, filter_query="WHERE NOT entity:Resolved")` — merges `__Entity__` nodes by similar `name` (requires APOC).
- `SinglePropertyExactMatchResolver` — exact match on label + name.

LLM-written nodes receive the `__Entity__` label via `Neo4jWriter`. Backbone Person/Post nodes loaded directly do not.

## Config file runner

```python
from neo4j_graphrag.experimental.pipeline.config.runner import PipelineRunner
pipeline = PipelineRunner.from_config_file("config/kg_pipeline.yaml")
await pipeline.run({"text": "..."})
```

Environment resolution in YAML: `{ resolver_: ENV, var_: NEO4J_PASSWORD }`.
