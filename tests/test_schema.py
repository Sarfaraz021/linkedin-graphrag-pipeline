"""Tests for semantic schema definition (Sophie-aligned)."""

from __future__ import annotations

import asyncio

from backend.pipeline.schema import (
    INFERRED_EDGE_PROPERTIES,
    LEGACY_COMPANY_LABEL,
    PATTERNS,
    SEMANTIC_NODE_LABELS,
    build_semantic_schema,
    get_semantic_schema_dict,
)


def test_schema_dict_flags_are_strict():
    schema = get_semantic_schema_dict()
    assert schema["additional_node_types"] is False
    assert schema["additional_relationship_types"] is False
    assert schema["additional_patterns"] is False
    rel_labels = {r["label"] if isinstance(r, dict) else r for r in schema["relationship_types"]}
    assert "MENTIONS" not in rel_labels
    assert "WROTE" not in rel_labels


def test_schema_uses_client_labels_not_company():
    schema = get_semantic_schema_dict()
    node_labels = {
        n["label"] if isinstance(n, dict) else n for n in schema["node_types"]
    }
    assert "Organisation" in node_labels
    assert "Brand" in node_labels
    assert "Retailer" in node_labels
    assert "Founder" in node_labels
    assert "Investor" in node_labels
    assert LEGACY_COMPANY_LABEL not in node_labels


def test_semantic_relationships_carry_inferred_edge_properties():
    schema = get_semantic_schema_dict()
    for rel in schema["relationship_types"]:
        if isinstance(rel, dict):
            prop_names = {p["name"] for p in rel.get("properties", [])}
            assert prop_names >= {"confidence_score", "source_post_url", "evidence_text"}


def test_schema_builds_without_validation_errors():
    schema = asyncio.run(build_semantic_schema())
    labels = {nt.label for nt in schema.node_types}
    assert "Person" in labels
    assert "Organisation" in labels
    assert "Award" in labels
    for src, rel, dst in PATTERNS:
        assert src in labels or src == "Post"
        assert dst in labels or dst == "Post"
        rel_labels = {rt.label for rt in schema.relationship_types}
        assert rel in rel_labels


def test_semantic_labels_exclude_backbone_only_types():
    assert "Person" not in SEMANTIC_NODE_LABELS
    assert "Organisation" in SEMANTIC_NODE_LABELS
    assert "Award" in SEMANTIC_NODE_LABELS


def test_inferred_edge_properties_constant():
    names = {p["name"] for p in INFERRED_EDGE_PROPERTIES}
    assert names == {"confidence_score", "source_post_url", "evidence_text"}
