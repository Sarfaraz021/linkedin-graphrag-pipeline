"""Chat service facade: LangGraph agent over Neo4j vector + graph context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.pipeline.config import Settings, get_settings
from backend.pipeline.neo4j_client import Neo4jClient
from backend.rag.agent import GraphAgent


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
        self._agent = GraphAgent(self.settings)

    def _client_or_create(self) -> Neo4jClient:
        if self._client is None:
            self._client = Neo4jClient(self.settings)
        return self._client

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

    def ask(self, question: str, session_id: str, top_k: int = 8) -> ChatResponse:
        stats = self.graph_stats()
        result = self._agent.ask(question, session_id=session_id, top_k=top_k)
        retrieval_mode = "+".join(dict.fromkeys(result.tool_calls)) or "chat"
        return ChatResponse(
            answer=result.answer,
            sources=result.sources,
            graph_stats=stats,
            retrieval_mode=retrieval_mode,
        )

    def close(self) -> None:
        self._agent.close()
        if self._client:
            self._client.close()
            self._client = None
