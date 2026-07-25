"""Tests for semantic schema definition."""

from __future__ import annotations

import asyncio

from backend.pipeline.schema import (
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
    assert "MENTIONS" not in schema["relationship_types"]


def test_schema_builds_without_validation_errors():
    schema = asyncio.run(build_semantic_schema())
    labels = {nt.label for nt in schema.node_types}
    assert "Person" in labels
    assert "Company" in labels
    for src, rel, dst in PATTERNS:
        assert src in labels
        assert dst in labels
        rel_labels = {rt.label for rt in schema.relationship_types}
        assert rel in rel_labels


def test_semantic_labels_exclude_backbone_only_types():
    assert "Person" not in SEMANTIC_NODE_LABELS
    assert "Company" in SEMANTIC_NODE_LABELS
