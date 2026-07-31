"""Semantic-layer GraphSchema aligned to client FMCG ecosystem vocabulary."""

from __future__ import annotations

from typing import Any

from neo4j_graphrag.experimental.components.schema import (
    GraphSchema,
    NodeType,
    RelationshipType,
    SchemaBuilder,
)

# ---------------------------------------------------------------------------
# Inferred-edge properties (Change 3) — required on every LLM semantic edge
# ---------------------------------------------------------------------------
INFERRED_EDGE_PROPERTIES: list[dict[str, str]] = [
    {"name": "confidence_score", "type": "FLOAT"},
    {"name": "source_post_url", "type": "STRING"},
    {"name": "evidence_text", "type": "STRING"},
]


def _semantic_rel(label: str, description: str = "") -> dict[str, Any]:
    rel: dict[str, Any] = {
        "label": label,
        "properties": list(INFERRED_EDGE_PROPERTIES),
    }
    if description:
        rel["description"] = description
    return rel


# ---------------------------------------------------------------------------
# Node types — client core + extended (Change 2)
# ---------------------------------------------------------------------------
NODE_TYPES: list[NodeType | str | dict[str, Any]] = [
    {
        "label": "Person",
        "description": (
            "LinkedIn person referenced by name and profile URL; do not invent ids. "
            "Add :Founder or :Investor as an extra label when the role is explicit."
        ),
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "url", "type": "STRING"},
        ],
    },
    {
        "label": "Founder",
        "description": "Person who founded or owns a consumer brand; include name and url.",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "url", "type": "STRING"},
        ],
    },
    {
        "label": "Investor",
        "description": "Person or fund representative who invests in brands; include name and url.",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "url", "type": "STRING"},
        ],
    },
    {
        "label": "Buyer",
        "description": "Retail buyer or procurement contact mentioned in post text.",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Organisation",
        "description": "Company, agency, broadcaster, accelerator, or industry body.",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Brand",
        "description": "Named consumer product brand (FMCG / challenger brand on shelf).",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Retailer",
        "description": "Retail chain or buyer organisation where brands are listed.",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Category",
        "description": "FMCG product category or sector (e.g. snacks, beverages).",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Trend",
        "description": "Market or industry trend referenced in the post.",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Location",
        "description": "Geographic location referenced in the post.",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Award",
        "description": "Named award or award programme (e.g. bCreator Talent Manager of the Year).",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Event",
        "description": "Trade show, conference, or industry event.",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Programme",
        "description": "Accelerator, incubator, or support programme for brands/founders.",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Accelerator",
        "description": "Accelerator or incubator organisation supporting challenger brands.",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    {
        "label": "Distributor",
        "description": "Distributor or wholesaler mentioned in the post.",
        "properties": [{"name": "name", "type": "STRING"}],
    },
    "Post",
]

RELATIONSHIP_TYPES: list[RelationshipType | str | dict[str, Any]] = [
    _semantic_rel("FOUNDED", "Person/Founder founded a Brand or Organisation."),
    _semantic_rel("WORKS_AT", "Person works at an Organisation."),
    _semantic_rel("LISTED_IN", "Brand is listed in / sold at a Retailer."),
    _semantic_rel("SUPPORTED_BY", "Organisation, Brand, or Award programme supported or sponsored by another Organisation."),
    _semantic_rel("OPERATES_IN", "Brand or Organisation operates in a Category or market."),
    _semantic_rel("INVESTED_IN", "Investor invested in a Brand or Organisation."),
    _semantic_rel("BASED_IN", "Person or Organisation based in a Location."),
    _semantic_rel("NOMINATED_FOR", "Person nominated for an Award or Programme."),
    _semantic_rel("SPONSORS", "Organisation sponsors an Award, Event, or Programme."),
    _semantic_rel("PARTICIPATED_IN", "Brand or Person participated in an Event or Programme."),
    _semantic_rel("RUNS", "Organisation runs a Programme or Accelerator."),
]

# MENTIONS and WROTE are deterministic backbone edges — not extracted by LLM.
PATTERNS: list[tuple[str, str, str]] = [
    ("Person", "FOUNDED", "Brand"),
    ("Founder", "FOUNDED", "Brand"),
    ("Person", "WORKS_AT", "Organisation"),
    ("Founder", "WORKS_AT", "Organisation"),
    ("Brand", "LISTED_IN", "Retailer"),
    ("Organisation", "SUPPORTED_BY", "Organisation"),
    ("Brand", "SUPPORTED_BY", "Organisation"),
    ("Award", "SUPPORTED_BY", "Organisation"),
    ("Brand", "OPERATES_IN", "Category"),
    ("Organisation", "OPERATES_IN", "Category"),
    ("Investor", "INVESTED_IN", "Brand"),
    ("Investor", "INVESTED_IN", "Organisation"),
    ("Person", "BASED_IN", "Location"),
    ("Organisation", "BASED_IN", "Location"),
    ("Person", "NOMINATED_FOR", "Award"),
    ("Person", "NOMINATED_FOR", "Programme"),
    ("Organisation", "SPONSORS", "Award"),
    ("Organisation", "SPONSORS", "Event"),
    ("Organisation", "SPONSORS", "Programme"),
    ("Organisation", "RUNS", "Programme"),
    ("Organisation", "RUNS", "Accelerator"),
    ("Brand", "PARTICIPATED_IN", "Event"),
    ("Brand", "PARTICIPATED_IN", "Programme"),
]

# Labels handled by semantic extraction + fuzzy resolution (not backbone-only).
SEMANTIC_NODE_LABELS = {
    "Organisation",
    "Brand",
    "Retailer",
    "Founder",
    "Investor",
    "Buyer",
    "Category",
    "Trend",
    "Location",
    "Award",
    "Event",
    "Programme",
    "Accelerator",
    "Distributor",
}

# Legacy alias — removed in Change 2; kept only for migration scripts.
LEGACY_COMPANY_LABEL = "Company"

BACKBONE_RELATIONSHIPS = ("WROTE", "COMMENTED", "REACTED", "MENTIONS")


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
