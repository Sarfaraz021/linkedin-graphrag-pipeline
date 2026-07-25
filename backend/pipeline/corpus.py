"""Build LLM corpus records from structured post JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from backend.pipeline.backbone import RECORD_SEPARATOR

PROFILE_ROLES = {"author", "commenter"}
REACTOR_ROLE = "reactor"


@dataclass
class CorpusRecord:
    post_id: str
    person_id: str | None
    record_type: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _profile_text(person: dict[str, Any]) -> str:
    parts = [
        person.get("name") or "",
        person.get("headline") or "",
        person.get("currentCompany") or "",
        person.get("location") or "",
    ]
    return " — ".join(p for p in parts if p)


def build_corpus_records(
    data: dict[str, Any],
    *,
    include_reactor_profiles: bool = False,
) -> list[CorpusRecord]:
    post = data["post"]
    post_id = post["id"]
    people = data.get("people") or {}
    records: list[CorpusRecord] = []

    author = people.get(post.get("authorId") or "")
    author_name = (author or {}).get("name") or "Unknown author"
    author_headline = (author or {}).get("headline") or ""
    post_text = post.get("content") or ""
    records.append(
        CorpusRecord(
            post_id=post_id,
            person_id=post.get("authorId"),
            record_type="post",
            text=f"{author_name} ({author_headline})\n{post_text}".strip(),
        )
    )

    for comment in data.get("comments") or []:
        person_id = comment.get("personId")
        person = people.get(person_id or {}) or {}
        name = person.get("name") or "Unknown commenter"
        headline = person.get("headline") or ""
        location = person.get("location") or ""
        company = person.get("currentCompany") or ""
        context = " — ".join(p for p in [headline, company, location] if p)
        comment_text = comment.get("text") or ""
        records.append(
            CorpusRecord(
                post_id=post_id,
                person_id=person_id,
                record_type="comment",
                text=f"{name} ({context})\n{comment_text}".strip(),
            )
        )

    seen_profiles: set[str] = set()
    for person_id, person in people.items():
        roles = set(person.get("roles") or [])
        if REACTOR_ROLE in roles and PROFILE_ROLES.isdisjoint(roles):
            if not include_reactor_profiles:
                continue
        if PROFILE_ROLES.intersection(roles) or (
            include_reactor_profiles and REACTOR_ROLE in roles
        ):
            if person_id in seen_profiles:
                continue
            seen_profiles.add(person_id)
            records.append(
                CorpusRecord(
                    post_id=post_id,
                    person_id=person_id,
                    record_type="profile",
                    text=_profile_text(person),
                )
            )

    return records


def records_to_corpus_text(records: list[CorpusRecord], post_id: str) -> str:
    body = RECORD_SEPARATOR.join(r.text for r in records)
    return f"[postId={post_id}]\n{body}"


def write_corpus_debug(processed_dir: Path, post_id: str, records: list[CorpusRecord]) -> Path:
    processed_dir.mkdir(parents=True, exist_ok=True)
    out_path = processed_dir / f"{post_id}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    return out_path


def iter_corpus_for_posts(
    posts: list[dict[str, Any]],
    processed_dir: Path,
    *,
    include_reactor_profiles: bool = False,
) -> Iterator[tuple[str, list[CorpusRecord], str]]:
    for data in posts:
        post_id = data["post"]["id"]
        records = build_corpus_records(
            data,
            include_reactor_profiles=include_reactor_profiles,
        )
        write_corpus_debug(processed_dir, post_id, records)
        yield post_id, records, records_to_corpus_text(records, post_id)
