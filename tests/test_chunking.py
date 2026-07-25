"""Tests for RecordCountSplitter."""

from __future__ import annotations

import asyncio

from backend.pipeline.chunking import RecordCountSplitter


def _records(n: int) -> str:
    return "\n---\n".join(f"record {i}" for i in range(n))


def test_splitter_respects_record_limit():
    splitter = RecordCountSplitter(chunk_records=30, chunk_overlap=5)
    text = f"[postId=abc123]\n{_records(60)}"
    chunks = asyncio.run(splitter.run(text))
    assert all(c.metadata["recordCount"] <= 30 for c in chunks.chunks)
    assert chunks.chunks[0].metadata["recordCount"] == 30


def test_splitter_overlap_is_exactly_five():
    splitter = RecordCountSplitter(chunk_records=30, chunk_overlap=5)
    records = [f"record {i}" for i in range(35)]
    chunks = splitter.split_records(records, post_id="post1")
    assert len(chunks.chunks) == 2
    assert chunks.chunks[0].metadata["recordCount"] == 30
    assert chunks.chunks[1].metadata["recordCount"] == 10
    assert chunks.chunks[1].metadata["recordStart"] == 25
    first_window = records[0:30]
    second_window = records[25:35]
    assert first_window[-5:] == second_window[:5]


def test_empty_input_returns_no_chunks():
    splitter = RecordCountSplitter()
    chunks = asyncio.run(splitter.run(""))
    assert chunks.chunks == []
