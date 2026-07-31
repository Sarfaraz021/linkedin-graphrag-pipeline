"""GraphRAG query service over Neo4j vector + graph context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings
from neo4j_graphrag.generation import GraphRAG
from neo4j_graphrag.generation.prompts import RagTemplate
from neo4j_graphrag.llm import OpenAILLM
from neo4j_graphrag.retrievers import VectorCypherRetriever

from backend.pipeline.config import Settings, get_settings
from backend.pipeline.neo4j_client import Neo4jClient

VECTOR_INDEX = "chunk_embedding"

RETRIEVAL_QUERY = """
WITH node AS chunk, score
OPTIONAL MATCH (chunk)-[:FROM_DOCUMENT]->(doc:Document)
WITH chunk, score, doc,
     CASE
       WHEN doc.path STARTS WITH 'linkedin/post/' THEN replace(doc.path, 'linkedin/post/', '')
       WHEN doc.postId IS NOT NULL THEN doc.postId
       ELSE null
     END AS postId
OPTIONAL MATCH (post:Post {id: postId})
OPTIONAL MATCH (author:Person)-[:WROTE]->(post)
RETURN chunk.text AS text,
       score,
       postId,
       author.name AS authorName,
       post.postedAt AS postedAt,
       left(post.content, 280) AS postPreview,
       doc.path AS source
"""

DEMO_RAG_TEMPLATE = RagTemplate(
    template="""You are a professional LinkedIn engagement analyst assistant.
Answer using ONLY the retrieved context from the knowledge graph.
Format responses clearly with markdown:
- Use **bold** for people and company names
- Use bullet lists for multiple items
- Include a short **Summary** then **Details** when helpful
- If mentioning people, note their role (author, commenter, reactor) when known
- End with **Sources** listing post ids or snippets used
- If context is insufficient, say what is missing

Context:
{context}

Examples:
{examples}

Question:
{query_text}

Answer:"""
)


@dataclass
class ChatResponse:
    answer: str
    sources: list[dict[str, Any]]
    graph_stats: dict[str, int]
    retrieval_mode: str


class RagService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client: Neo4jClient | None = None
        self._graph_rag: GraphRAG | None = None

    def _client_or_create(self) -> Neo4jClient:
        if self._client is None:
            self._client = Neo4jClient(self.settings)
        return self._client

    def _graph_rag_or_create(self) -> GraphRAG:
        if self._graph_rag is None:
            client = self._client_or_create()
            embedder = OpenAIEmbeddings(
                model=self.settings.embed_model,
                api_key=self.settings.openai_api_key,
            )
            retriever = VectorCypherRetriever(
                driver=client.driver,
                index_name=VECTOR_INDEX,
                retrieval_query=RETRIEVAL_QUERY,
                embedder=embedder,
                neo4j_database=self.settings.neo4j_database,
            )
            llm = OpenAILLM(
                model_name=self.settings.llm_model,
                api_key=self.settings.openai_api_key,
                model_params={"temperature": 0.2},
            )
            self._graph_rag = GraphRAG(
                retriever=retriever,
                llm=llm,
                prompt_template=DEMO_RAG_TEMPLATE,
            )
        return self._graph_rag

    def graph_stats(self) -> dict[str, int]:
        client = self._client_or_create()
        stats = {
            "people": client.count_nodes("Person"),
            "posts": client.count_nodes("Post"),
            "organisations": client.count_nodes("Organisation"),
            "companies": client.count_nodes("Organisation"),  # backward compat for UI
            "chunks": client.count_nodes("Chunk"),
            "comments": client.count_relationships("COMMENTED"),
            "reactions": client.count_relationships("REACTED"),
            "mentions": client.count_relationships("MENTIONS"),
        }
        return stats

    def _graph_fallback_context(self, question: str) -> str:
        client = self._client_or_create()
        rows = client.run(
            """
            MATCH (post:Post)
            OPTIONAL MATCH (author:Person)-[:WROTE]->(post)
            OPTIONAL MATCH (commenter:Person)-[c:COMMENTED]->(post)
            WITH post, author,
                 collect(DISTINCT {name: commenter.name, text: c.commentary})[..8] AS comments
            RETURN post.id AS postId,
                   author.name AS author,
                   left(post.content, 400) AS content,
                   post.reactionsTotal AS reactions,
                   comments
            LIMIT 3
            """
        )
        if not rows:
            return "No graph data loaded yet. Run the backbone pipeline first."
        parts = [f"User question: {question}", "Graph context (no vector chunks matched):"]
        for row in rows:
            parts.append(
                f"Post {row.get('postId')} by {row.get('author')}: {row.get('content')}"
            )
            for c in row.get("comments") or []:
                if c.get("text"):
                    parts.append(f"  Comment by {c.get('name')}: {c.get('text')[:200]}")
        return "\n".join(parts)

    def ask(self, question: str, top_k: int = 8) -> ChatResponse:
        stats = self.graph_stats()
        sources: list[dict[str, Any]] = []
        retrieval_mode = "vector+graph"

        try:
            rag = self._graph_rag_or_create()
            result = rag.search(
                query_text=question,
                retriever_config={"top_k": top_k},
                return_context=True,
            )
            answer = result.answer or "No answer generated."
            if result.retriever_result and result.retriever_result.items:
                for item in result.retriever_result.items:
                    meta = item.metadata or {}
                    sources.append(
                        {
                            "text": (item.content or "")[:240],
                            "score": meta.get("score"),
                            "postId": meta.get("postId"),
                            "authorName": meta.get("authorName"),
                            "source": meta.get("source"),
                        }
                    )
        except Exception as exc:
            retrieval_mode = "graph_fallback"
            fallback = self._graph_fallback_context(question)
            llm = OpenAILLM(
                model_name=self.settings.llm_model,
                api_key=self.settings.openai_api_key,
                model_params={"temperature": 0.2},
            )
            prompt = DEMO_RAG_TEMPLATE.format(
                context=fallback, query_text=question, examples=""
            )
            answer = llm.invoke(prompt).content or str(exc)
            sources = [{"text": fallback[:300], "source": "graph_fallback"}]

        return ChatResponse(
            answer=answer,
            sources=sources,
            graph_stats=stats,
            retrieval_mode=retrieval_mode,
        )

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
