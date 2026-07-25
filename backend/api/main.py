"""FastAPI application for the demo chat UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.rag.service import RagService

rag_service: RagService | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global rag_service
    rag_service = RagService()
    yield
    if rag_service:
        rag_service.close()
        rag_service = None


app = FastAPI(
    title="LinkedIn GraphRAG Demo API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=20)


class ChatResponseModel(BaseModel):
    answer: str
    sources: list[dict[str, Any]]
    graph_stats: dict[str, int]
    retrieval_mode: str


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/stats")
def stats() -> dict[str, int]:
    if not rag_service:
        raise HTTPException(503, "Service not ready")
    return rag_service.graph_stats()


@app.post("/api/chat", response_model=ChatResponseModel)
def chat(body: ChatRequest) -> ChatResponseModel:
    if not rag_service:
        raise HTTPException(503, "Service not ready")
    try:
        result = rag_service.ask(body.message.strip(), top_k=body.top_k)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return ChatResponseModel(
        answer=result.answer,
        sources=result.sources,
        graph_stats=result.graph_stats,
        retrieval_mode=result.retrieval_mode,
    )
