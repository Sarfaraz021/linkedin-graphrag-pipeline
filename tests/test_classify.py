"""Tests for post classification (Change 1)."""

from __future__ import annotations

import json

from backend.pipeline.classify import (
    POST_CATEGORIES,
    PostClassification,
    _parse_classification,
)


def test_parse_classification_valid_json():
    raw = json.dumps(
        {
            "category": "Award",
            "confidence": 0.93,
            "evidence": "4 x nominations for our agency at this years bCreator",
        }
    )
    result = _parse_classification(raw)
    assert result.category == "Award"
    assert result.confidence == 0.93
    assert "bCreator" in result.evidence


def test_parse_classification_unknown_category_defaults():
    raw = json.dumps({"category": "NotARealCategory", "confidence": 0.5, "evidence": "x"})
    result = _parse_classification(raw)
    assert result.category == "Uncategorised"


def test_parse_classification_clamps_confidence():
    raw = json.dumps({"category": "Event", "confidence": 1.5, "evidence": "trade show"})
    result = _parse_classification(raw)
    assert result.confidence == 1.0


def test_post_categories_include_award_and_uncategorised():
    assert "Award" in POST_CATEGORIES
    assert "Uncategorised" in POST_CATEGORIES


def test_classification_to_dict():
    c = PostClassification(category="Award", confidence=0.9, evidence="nomination")
    assert c.to_dict() == {"category": "Award", "confidence": 0.9, "evidence": "nomination"}
