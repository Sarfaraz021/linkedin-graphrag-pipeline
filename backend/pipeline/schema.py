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
        "description": (
            "Company, agency, broadcaster, accelerator, or industry body. Classify its "
            "orgType (see docs/CLASSIFICATION_VOCAB.md) — sponsoring an award/event is NOT "
            "the same as funding a business: a Broadcaster/Sponsor org is not a Funder/Investor "
            "unless it demonstrably gives money directly to a brand/business (FUNDS/INVESTED_IN)."
        ),
        "properties": [
            {"name": "name", "type": "STRING"},
            {
                "name": "orgType",
                "type": "STRING",
                "description": (
                    "One of: Brand, Retailer, Distributor, Investor, Funder, Accelerator, "
                    "Incubator, Sponsor, Broadcaster, AwardBody, Agency, IndustryBody, "
                    "TradeShowOrganiser, Other."
                ),
            },
        ],
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
    _semantic_rel(
        "SUPPORTED_BY",
        "NON-FINANCIAL support only: mentorship, visibility, endorsement, platform, or "
        "amplification given to an Organisation, Brand, or Award by another Organisation. "
        "Never use this for money changing hands — sponsoring an award/event is SPONSORS, "
        "equity investment is INVESTED_IN, and grants/non-equity funding is FUNDS.",
    ),
    _semantic_rel("OPERATES_IN", "Brand or Organisation operates in a Category or market."),
    _semantic_rel(
        "INVESTED_IN",
        "STRICT equity investment: an Investor puts capital into a Brand or Organisation "
        "in exchange for equity/ownership stake.",
    ),
    _semantic_rel("BASED_IN", "Person or Organisation based in a Location."),
    _semantic_rel("NOMINATED_FOR", "Person nominated for an Award or Programme."),
    _semantic_rel(
        "SPONSORS",
        "STRICT award/event/programme sponsorship only — an Organisation pays to be "
        "associated with (headline/backs/sponsors) an Award, Event, or Programme. This is "
        "brand/marketing spend, NOT funding of a business — do not also emit FUNDS or "
        "INVESTED_IN for the same fact. Example: ITV SPONSORS bCreator (ITV is a Broadcaster "
        "sponsor, not a funder or investor).",
    ),
    _semantic_rel(
        "FUNDS",
        "Grant or other NON-EQUITY funding given directly to a Brand or Organisation (e.g. "
        "a government scheme, foundation, or fund gives money to a business with no award/"
        "event attached and no equity taken). Do not use for award/event sponsorship "
        "(use SPONSORS) or equity investment (use INVESTED_IN).",
    ),
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
    ("Organisation", "FUNDS", "Brand"),
    ("Organisation", "FUNDS", "Organisation"),
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

# Controlled vocabulary for Organisation.orgType (see docs/CLASSIFICATION_VOCAB.md).
ORG_TYPES: tuple[str, ...] = (
    "Brand",
    "Retailer",
    "Distributor",
    "Investor",
    "Funder",
    "Accelerator",
    "Incubator",
    "Sponsor",
    "Broadcaster",
    "AwardBody",
    "Agency",
    "IndustryBody",
    "TradeShowOrganiser",
    "Other",
)

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
