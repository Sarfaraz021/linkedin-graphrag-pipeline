"""Organisation.orgType classification — controlled vocabulary (Sophie's ask).

Deterministic rules first (known names, keyword heuristics, edge-type signals);
LLM fallback from name + relationship evidence otherwise. ITV-style sponsors
must resolve to Broadcaster/Sponsor, never Funder/Investor — that's the bug
this whole pass exists to fix, so it's covered by both the deterministic table
and the LLM few-shot below.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from backend.pipeline.config import Settings
from backend.pipeline.llm_factory import build_llm, invoke_llm
from backend.pipeline.neo4j_client import Neo4jClient
from backend.pipeline.schema import ORG_TYPES

# Curated exact-name lookups for well-known organisations whose real-world role
# is unambiguous and should never depend on which edge an LLM happened to infer.
KNOWN_ORG_TYPES: dict[str, str] = {
    "itv": "Broadcaster",
    "bbc": "Broadcaster",
    "channel 4": "Broadcaster",
    "channel4": "Broadcaster",
    "sky": "Broadcaster",
    "itv plc": "Broadcaster",
}

# Ordered keyword heuristics over the organisation name, checked when no exact
# known-name match exists. First match wins.
KEYWORD_RULES: tuple[tuple[str, str], ...] = (
    ("accelerator", "Accelerator"),
    ("incubator", "Incubator"),
    ("awards", "AwardBody"),
    ("award", "AwardBody"),
    ("trade show", "TradeShowOrganiser"),
    ("expo", "TradeShowOrganiser"),
    ("exhibition", "TradeShowOrganiser"),
    ("federation", "IndustryBody"),
    ("association", "IndustryBody"),
    ("institute", "IndustryBody"),
    ("chamber of commerce", "IndustryBody"),
    ("agency", "Agency"),
    ("consultancy", "Agency"),
    ("pr agency", "Agency"),
    ("distribution", "Distributor"),
    ("distributor", "Distributor"),
    ("wholesale", "Distributor"),
    ("capital", "Investor"),
    ("ventures", "Investor"),
    ("vc", "Investor"),
    ("supermarket", "Retailer"),
)

ORG_TYPE_PROMPT = """You classify an Organisation node in an FMCG / challenger-brand ecosystem
knowledge graph with exactly one orgType from this controlled vocabulary:
{org_types}

Definitions:
- Brand: makes/sells a consumer product itself (rare for a generic "Organisation" node).
- Retailer: sells other brands' products (shops, supermarkets, e-commerce).
- Distributor: moves/wholesales products between brands and retailers.
- Investor: puts equity capital into businesses.
- Funder: gives grants or non-equity funding directly to businesses.
- Accelerator / Incubator: structured support programme for founders/brands.
- Sponsor: pays to be associated with an award/event/programme (brand marketing spend).
- Broadcaster: TV/radio/media channel.
- AwardBody: runs/organises an award programme.
- Agency: marketing, PR, talent, or creative services agency.
- IndustryBody: trade association, federation, or industry institute.
- TradeShowOrganiser: runs trade shows / exhibitions / expos.
- Other: none of the above fit.

CRITICAL: sponsoring an award or event is NOT funding a business. An organisation that pays
to headline-sponsor an award (e.g. ITV sponsoring the "bCreator" award) is a Sponsor and/or
Broadcaster — NEVER Funder or Investor — unless there is separate direct evidence it puts
money into a specific brand/business.

Example 1:
Organisation name: ITV
Evidence: "ITV as headline sponsors of this years bCreator awards"
-> {{"orgType": "Broadcaster", "confidence": 0.9}}

Example 2:
Organisation name: Bethnal Green Ventures
Evidence: "backed by our seed investor Bethnal Green Ventures who took an equity stake"
-> {{"orgType": "Investor", "confidence": 0.9}}

Example 3:
Organisation name: Innovate UK
Evidence: "received a £50k grant from Innovate UK to develop our product, no equity given up"
-> {{"orgType": "Funder", "confidence": 0.85}}

Respond with JSON only: {{"orgType": "<one of the vocabulary above>", "confidence": 0.0}}

Organisation name: {name}
Evidence (short quotes from posts mentioning this organisation):
{evidence}
"""


@dataclass
class OrgTypeResult:
    org_type: str
    confidence: float
    source: str  # "known" | "keyword" | "edge" | "llm" | "default"


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def classify_deterministic(name: str, out_edge_types: set[str]) -> OrgTypeResult | None:
    norm = _normalise(name)
    if not norm:
        return None
    if norm in KNOWN_ORG_TYPES:
        return OrgTypeResult(KNOWN_ORG_TYPES[norm], 1.0, "known")
    for keyword, org_type in KEYWORD_RULES:
        if keyword in norm:
            return OrgTypeResult(org_type, 0.8, "keyword")
    # Edge-type signals only used when the name gives no hint (avoids the ITV
    # bug: ITV has a SPONSORS edge but must resolve via the known-name table).
    if "FUNDS" in out_edge_types:
        return OrgTypeResult("Funder", 0.6, "edge")
    if "INVESTED_IN" in out_edge_types:
        return OrgTypeResult("Investor", 0.6, "edge")
    if "SPONSORS" in out_edge_types:
        return OrgTypeResult("Sponsor", 0.55, "edge")
    return None


def _parse_llm_response(raw: str) -> OrgTypeResult:
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return OrgTypeResult("Other", 0.0, "default")
    org_type = str(data.get("orgType", "Other"))
    if org_type not in ORG_TYPES:
        org_type = "Other"
    confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    return OrgTypeResult(org_type, confidence, "llm")


def classify_llm(name: str, evidence: list[str], settings: Settings) -> OrgTypeResult:
    if not settings.openai_api_key and not settings.anthropic_api_key:
        return OrgTypeResult("Other", 0.0, "default")
    llm = build_llm(settings, json_mode=True)
    prompt = ORG_TYPE_PROMPT.format(
        org_types=", ".join(ORG_TYPES),
        name=name,
        evidence="\n".join(f"- {e}" for e in evidence[:5]) or "(no evidence text available)",
    )
    raw = invoke_llm(llm, prompt)
    return _parse_llm_response(raw)


def _fetch_organisation_context(client: Neo4jClient) -> list[dict[str, Any]]:
    return client.run(
        """
        MATCH (o:Organisation)
        WHERE o.name IS NOT NULL AND o.name <> ''
        OPTIONAL MATCH (o)-[r]->()
        WITH o, collect(DISTINCT type(r)) AS outTypes,
             collect(DISTINCT r.evidence_text)[0..5] AS outEvidence
        OPTIONAL MATCH ()-[r2]->(o)
        WITH o, outTypes, outEvidence,
             collect(DISTINCT r2.evidence_text)[0..5] AS inEvidence
        RETURN elementId(o) AS id, o.name AS name, outTypes AS outTypes,
               [e IN outEvidence + inEvidence WHERE e IS NOT NULL] AS evidence
        """
    )


def fix_merged_org_types(client: Neo4jClient) -> int:
    """Collapse orgType back to a single value after fuzzy-resolution merges.

    apoc.refactor.mergeNodes(properties: 'combine') turns a scalar property into
    a list when two merged duplicates disagreed (e.g. classified before vs. after
    a name-casing merge). Re-run deterministic classification by name where
    possible so a known org (e.g. ITV) can never end up ambiguous post-merge.
    """
    rows = client.run(
        """
        MATCH (o:Organisation)
        WHERE o.orgType IS NOT NULL AND apoc.meta.cypher.type(o.orgType) CONTAINS 'LIST'
        RETURN elementId(o) AS id, o.name AS name, o.orgType AS types
        """
    )
    fixed = 0
    for row in rows:
        types = [t for t in (row.get("types") or []) if t]
        chosen = next((t for t in types if t != "Other"), None) or (types[0] if types else "Other")
        det = classify_deterministic(row["name"], set())
        if det:
            chosen = det.org_type
        client.run_write(
            """
            MATCH (o) WHERE elementId(o) = $id
            SET o.orgType = $orgType, o.orgTypeSource = 'merge_fix'
            """,
            {"id": row["id"], "orgType": chosen},
        )
        fixed += 1
    return fixed


def classify_and_persist_organisations(
    client: Neo4jClient,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Classify orgType for every Organisation node. Idempotent (re-classifies all)."""
    rows = _fetch_organisation_context(client)
    results: list[dict[str, Any]] = []
    for row in rows:
        out_edge_types = set(row.get("outTypes") or [])
        result = classify_deterministic(row["name"], out_edge_types)
        if result is None:
            result = classify_llm(row["name"], row.get("evidence") or [], settings)
        client.run_write(
            """
            MATCH (o) WHERE elementId(o) = $id
            SET o.orgType = $orgType,
                o.orgTypeConfidence = $confidence,
                o.orgTypeSource = $source,
                o.updatedAt = datetime()
            """,
            {
                "id": row["id"],
                "orgType": result.org_type,
                "confidence": result.confidence,
                "source": result.source,
            },
        )
        results.append({"name": row["name"], **result.__dict__})
    return results
