"""ITV regression test: sponsoring an award must never read as funding a business.

Covers the schema/prompt fix (SUPPORTED_BY no longer conflates sponsorship and
funding; FUNDS/INVESTED_IN are the only money relationships) and the orgType
classifier (ITV must always resolve to Broadcaster, never Funder/Investor).
"""

from __future__ import annotations

import pytest

from backend.pipeline.config import get_settings
from backend.pipeline.neo4j_client import Neo4jClient
from backend.pipeline.org_classify import KNOWN_ORG_TYPES, classify_deterministic
from backend.pipeline.schema import ORG_TYPES, PATTERNS, RELATIONSHIP_TYPES

MONEY_RELATIONSHIPS = {"FUNDS", "INVESTED_IN"}
NON_MONEY_RELATIONSHIPS = {"SPONSORS", "SUPPORTED_BY"}


# ---------------------------------------------------------------------------
# Static tests — no live DB required, always run.
# ---------------------------------------------------------------------------


def test_funds_relationship_exists_and_is_distinct_from_sponsors():
    labels = {r["label"] if isinstance(r, dict) else r for r in RELATIONSHIP_TYPES}
    assert "FUNDS" in labels
    assert "SPONSORS" in labels
    assert "INVESTED_IN" in labels
    assert "SUPPORTED_BY" in labels


def test_sponsors_pattern_never_targets_plain_organisation():
    """SPONSORS must only reach Award/Event/Programme, never another Organisation —
    that ambiguity is exactly how the ITV-as-funder bug happened."""
    sponsors_targets = {dst for src, rel, dst in PATTERNS if rel == "SPONSORS"}
    assert sponsors_targets == {"Award", "Event", "Programme"}
    assert "Organisation" not in sponsors_targets


def test_org_type_vocab_has_funder_and_broadcaster_as_distinct_values():
    assert "Funder" in ORG_TYPES
    assert "Investor" in ORG_TYPES
    assert "Broadcaster" in ORG_TYPES
    assert "Sponsor" in ORG_TYPES


def test_itv_deterministically_classifies_as_broadcaster_not_funder():
    assert KNOWN_ORG_TYPES["itv"] == "Broadcaster"
    result = classify_deterministic("ITV", out_edge_types=set())
    assert result is not None
    assert result.org_type == "Broadcaster"


def test_itv_stays_broadcaster_even_with_a_sponsors_edge_signal():
    """The known-name table must be checked before any edge-type heuristic, so a
    SPONSORS edge on ITV can never push it toward Funder/Investor/Sponsor."""
    result = classify_deterministic("ITV", out_edge_types={"SPONSORS"})
    assert result is not None
    assert result.org_type == "Broadcaster"
    assert result.source == "known"


# ---------------------------------------------------------------------------
# Live-DB regression — skipped if Neo4j isn't reachable.
# ---------------------------------------------------------------------------


def _live_client() -> Neo4jClient | None:
    try:
        settings = get_settings()
        client = Neo4jClient(settings)
        client.run("RETURN 1")
        return client
    except Exception:
        return None


@pytest.fixture(scope="module")
def client():
    c = _live_client()
    if c is None:
        pytest.skip("Neo4j not reachable — skipping live regression checks")
    yield c
    c.close()


def test_itv_orgtype_is_broadcaster_in_graph(client: Neo4jClient):
    rows = client.run("MATCH (o:Organisation {name: 'ITV'}) RETURN DISTINCT o.orgType AS orgType")
    if not rows:
        pytest.skip("ITV not present in this graph snapshot")
    for row in rows:
        assert row["orgType"] == "Broadcaster"
        assert row["orgType"] not in {"Funder", "Investor"}


def test_itv_never_has_a_money_relationship_in_graph(client: Neo4jClient):
    rows = client.run(
        """
        MATCH (o:Organisation {name: 'ITV'})-[r]->()
        WHERE type(r) IN $money_rels
        RETURN type(r) AS relType
        """,
        {"money_rels": list(MONEY_RELATIONSHIPS)},
    )
    assert rows == [], f"ITV must never have a FUNDS/INVESTED_IN edge, found: {rows}"


def test_funding_query_excludes_sponsors_and_supported_by(client: Neo4jClient):
    """The actual seed query: 'what organisations provide funding to challenger
    brands?' must only traverse FUNDS/INVESTED_IN — this is what the RAG agent's
    system prompt is instructed to do, and what a correct Cypher query does."""
    rows = client.run(
        """
        MATCH (o:Organisation)-[r:FUNDS|INVESTED_IN]->(b)
        WHERE b:Brand OR b:Organisation
        RETURN o.name AS org, o.orgType AS orgType, type(r) AS relType
        """
    )
    for row in rows:
        assert row["org"] != "ITV", "ITV must never appear as a funder/investor"
        assert row["orgType"] not in {"Broadcaster", "Sponsor", "AwardBody"}, (
            f"{row['org']} has orgType={row['orgType']} but is being returned as a "
            "funder — that's the exact ITV-class bug this test guards against"
        )


def test_bcreator_post_category_is_award(client: Neo4jClient):
    rows = client.run(
        "MATCH (p:Post {id: '7470802348391673856'}) RETURN p.category AS category"
    )
    if not rows:
        pytest.skip("bCreator post not present in this graph snapshot")
    assert rows[0]["category"] == "Award"


def test_itv_sponsors_bcreator_edge_correctly_typed_when_present(client: Neo4jClient):
    """If the SPONSORS edge for this well-known fact was extracted, it must be
    correctly typed (Award target, not Organisation) and never duplicated as
    FUNDS/INVESTED_IN alongside it."""
    rows = client.run(
        """
        MATCH (itv:Organisation {name: 'ITV'})-[r]->(target)
        WHERE type(r) IN $rels
        RETURN type(r) AS relType, labels(target) AS targetLabels, target.name AS targetName
        """,
        {"rels": list(NON_MONEY_RELATIONSHIPS | MONEY_RELATIONSHIPS)},
    )
    for row in rows:
        assert row["relType"] not in MONEY_RELATIONSHIPS
        if row["relType"] == "SPONSORS":
            assert "Award" in row["targetLabels"] or "Event" in row["targetLabels"] or (
                "Programme" in row["targetLabels"]
            )
