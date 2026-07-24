"""Tests for backbone loading helpers and idempotent keys."""

from __future__ import annotations

import json
from pathlib import Path

from src.backbone import _comment_rows, _mention_rows, _person_row, _post_row
from src.io_load import count_expected_backbone, load_structured_post, validate_structured_post
from src.resolve import normalize_name

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "7470802348391673856.json"


def test_load_sample_structured_json():
    data = load_structured_post(SAMPLE)
    assert data["schemaVersion"] == "1.0"
    assert data["post"]["id"]


def test_person_row_keys_on_id_only():
    person = {
        "name": "Test User",
        "url": "https://www.linkedin.com/in/test",
        "headline": "Engineer",
    }
    row = _person_row("ACoAAA123", person)
    assert row["id"] == "ACoAAA123"
    assert row["linkedinUrl"] == person["url"]


def test_post_row_includes_reaction_breakdown():
    data = load_structured_post(SAMPLE)
    row = _post_row(data["post"])
    assert "reactions_LIKE" in row
    assert row["reactionsTotal"] == data["post"]["engagement"]["reactionsTotal"]


def test_expected_backbone_counts():
    data = load_structured_post(SAMPLE)
    counts = count_expected_backbone(data)
    assert counts["posts"] == 1
    assert counts["commented"] == len(data["comments"])
    assert counts["reacted"] == len(data["reactions"])
    assert counts["mentions"] == len(data["post"]["mentions"])


def test_mention_rows_preserve_ids():
    data = load_structured_post(SAMPLE)
    rows = _mention_rows(data["post"]["mentions"])
    assert all(r["id"] for r in rows)


def test_comment_rows_require_person_id():
    rows = _comment_rows([{"id": "c1", "personId": "p1", "text": "hi"}])
    assert rows[0]["personId"] == "p1"


def test_normalize_name_strips_punctuation():
    assert normalize_name("IT'S RATED BY") == normalize_name("ITS RATED BY")


def test_validate_rejects_missing_keys():
    try:
        validate_structured_post({"post": {}})
        raised = False
    except ValueError:
        raised = True
    assert raised
