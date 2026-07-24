"""Semantic-layer GraphSchema for LinkedIn LLM extraction."""

from __future__ import annotations

from typing import Any

from neo4j_graphrag.experimental.components.schema import (
    GraphSchema,
    NodeType,
    PropertyType,
    RelationshipType,
    SchemaBuilder,
)

NODE_TYPES: list[NodeType | str | dict[str, Any]] = [
    {
        "label": "Person",
        "description": "LinkedIn person referenced by name and profile URL; do not invent ids.",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "url", "type": "STRING"},
        ],
    },
    {
        "label": "Company",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Award",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Event",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Topic",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Skill",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "JobTitle",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Location",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    "Post",
]

RELATIONSHIP_TYPES: list[RelationshipType | str | dict[str, Any]] = [
    "WORKS_AT",
    "HAS_TITLE",
    "HAS_SKILL",
    "NOMINATED_FOR",
    "ABOUT_TOPIC",
    "LOCATED_IN",
    "PART_OF",
]

PATTERNS: list[tuple[str, str, str]] = [
    ("Person", "WORKS_AT", "Company"),
    ("Person", "HAS_TITLE", "JobTitle"),
    ("Person", "HAS_SKILL", "Skill"),
    ("Person", "NOMINATED_FOR", "Award"),
    ("Person", "LOCATED_IN", "Location"),
    ("Post", "ABOUT_TOPIC", "Topic"),
    ("Award", "PART_OF", "Event"),
]


async def build_semantic_schema() -> GraphSchema:
    builder = SchemaBuilder()
    return await builder.run(
        node_types=NODE_TYPES,
        relationship_types=RELATIONSHIP_TYPES,
        patterns=PATTERNS,
    )


def get_semantic_schema_dict() -> dict[str, Any]:
    """Synchronous schema dict for SimpleKGPipeline initialization."""
    return {
        "node_types": NODE_TYPES,
        "relationship_types": RELATIONSHIP_TYPES,
        "patterns": [list(p) for p in PATTERNS],
        "additional_node_types": False,
        "additional_relationship_types": False,
        "additional_patterns": False,
    }


SEMANTIC_NODE_LABELS = {
    "Company",
    "Award",
    "Event",
    "Topic",
    "Skill",
    "JobTitle",
    "Location",
}
