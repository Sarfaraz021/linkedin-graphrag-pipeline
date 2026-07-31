"""Load and validate structured JSON from Stage 1 scraper output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

REQUIRED_TOP_KEYS = {"schemaVersion", "post", "people", "comments", "reactions"}
REQUIRED_POST_KEYS = {"id", "url", "authorId", "mentions", "engagement"}


class StructuredPostValidationError(ValueError):
    """Raised when a structured post JSON file fails validation."""


def validate_structured_post(data: dict[str, Any], source: str = "") -> dict[str, Any]:
    missing = REQUIRED_TOP_KEYS - data.keys()
    if missing:
        raise StructuredPostValidationError(
            f"{source}: missing top-level keys: {sorted(missing)}"
        )
    post = data["post"]
    if not isinstance(post, dict):
        raise StructuredPostValidationError(f"{source}: post must be an object")
    missing_post = REQUIRED_POST_KEYS - post.keys()
    if missing_post:
        raise StructuredPostValidationError(
            f"{source}: post missing keys: {sorted(missing_post)}"
        )
    if not post["id"]:
        raise StructuredPostValidationError(f"{source}: post.id is required")
    if not isinstance(data["people"], dict):
        raise StructuredPostValidationError(f"{source}: people must be a dict")
    if not isinstance(data["comments"], list):
        raise StructuredPostValidationError(f"{source}: comments must be a list")
    if not isinstance(data["reactions"], list):
        raise StructuredPostValidationError(f"{source}: reactions must be a list")
    return data


def load_structured_post(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return validate_structured_post(data, source=str(path))


def iter_structured_posts(input_dir: Path) -> Iterator[dict[str, Any]]:
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    paths = sorted(input_dir.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No structured JSON files in {input_dir}")
    for path in paths:
        yield load_structured_post(path)


def count_expected_backbone(data: dict[str, Any]) -> dict[str, int]:
    """Return expected relationship counts for acceptance tests."""
    post = data["post"]
    return {
        "wrote": 1 if post.get("authorId") else 0,
        "commented": len(data.get("comments") or []),
        "reacted": len(data.get("reactions") or []),
        "mentions": len(post.get("mentions") or []),
        "people": len(data.get("people") or {}),
        "posts": 1,
    }
