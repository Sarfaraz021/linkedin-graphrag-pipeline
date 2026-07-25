"""Environment and pipeline settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    openai_api_key: str
    llm_model: str
    embed_model: str
    chunk_records: int
    chunk_overlap: int
    input_dir: Path
    processed_dir: Path
    include_reactor_profiles: bool
    fuzzy_similarity_threshold: float

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
            neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            embed_model=os.getenv("EMBED_MODEL", "text-embedding-3-small"),
            chunk_records=int(os.getenv("CHUNK_RECORDS", "30")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "5")),
            input_dir=Path(os.getenv("INPUT_DIR", "data/raw")),
            processed_dir=Path(os.getenv("PROCESSED_DIR", "data/processed")),
            include_reactor_profiles=_env_bool("INCLUDE_REACTOR_PROFILES", False),
            fuzzy_similarity_threshold=float(os.getenv("FUZZY_SIMILARITY_THRESHOLD", "0.85")),
        )

    def resolve_path(self, path: Path) -> Path:
        return path if path.is_absolute() else PROJECT_ROOT / path


def get_settings() -> Settings:
    settings = Settings.from_env()
    return Settings(
        **{
            **settings.__dict__,
            "input_dir": settings.resolve_path(settings.input_dir),
            "processed_dir": settings.resolve_path(settings.processed_dir),
        }
    )
