#!/usr/bin/env python3
"""Trim scraped structured JSON to pipeline-ready clean format (like *.clean.json)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.pipeline.io_load import StructuredPostValidationError, validate_structured_post

SCRAPER_DIR = ROOT / "linkedin scraper"
STRUCTURED_DIR = SCRAPER_DIR / "output" / "structured"
RAW_POSTS_DIR = SCRAPER_DIR / "output" / "posts"
DEFAULT_OUT_DIR = ROOT / "data" / "raw"

POST_ID_RE = re.compile(r"^\d+\.json$")

PERSON_CORE = ("id", "name", "headline", "url", "roles")
PERSON_OPTIONAL = (
    "location",
    "country",
    "currentCompany",
    "connectionsCount",
    "followerCount",
    "openToWork",
    "avatarUrl",
)


def strip_url_query(url: str | None) -> str | None:
    if not url:
        return url
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def trim_person(person: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": person["id"],
        "name": person.get("name"),
        "headline": person.get("headline"),
        "url": strip_url_query(person.get("url")),
        "roles": person.get("roles") or [],
    }
    for key in PERSON_OPTIONAL:
        val = person.get(key)
        if val not in (None, "", []):
            out[key] = val
    return out


def trim_comment(comment: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": comment["id"],
        "text": comment.get("text"),
        "createdAt": comment.get("createdAt"),
        "personId": comment.get("personId"),
    }
    if comment.get("url"):
        out["url"] = comment["url"]
    rx = comment.get("reactionsOnComment")
    if rx:
        out["reactionsOnComment"] = rx
    return out


def trim_reaction(reaction: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": reaction["id"],
        "type": reaction.get("type"),
        "personId": reaction.get("personId"),
    }


def trim_post_block(post: dict[str, Any]) -> dict[str, Any]:
    images = [u for u in (post.get("images") or []) if u]
    out: dict[str, Any] = {
        "id": post["id"],
        "url": post.get("url"),
        "shareUrl": post.get("shareUrl"),
        "postedAt": post.get("postedAt"),
        "content": post.get("content"),
        "mentions": post.get("mentions") or [],
        "authorId": post.get("authorId"),
        "engagement": post.get("engagement") or {},
    }
    if images:
        out["images"] = images
    return out


def trim_structured(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": data.get("schemaVersion", "1.0"),
        "post": trim_post_block(data["post"]),
        "people": {pid: trim_person(p) for pid, p in (data.get("people") or {}).items()},
        "comments": [trim_comment(c) for c in (data.get("comments") or [])],
        "reactions": [trim_reaction(r) for r in (data.get("reactions") or [])],
        "coverage": data.get("coverage") or {},
    }


def load_from_raw_post(path: Path) -> dict[str, Any]:
    sys.path.insert(0, str(SCRAPER_DIR))
    from main import normalize_post  # noqa: WPS433

    raw = json.loads(path.read_text(encoding="utf-8"))
    post_id = str(raw.get("postId") or raw.get("post", {}).get("id") or path.stem)
    post_url = raw.get("postUrl") or raw.get("post", {}).get("linkedinUrl") or ""
    return normalize_post(
        post_url=post_url,
        post_id=post_id,
        element=raw.get("post") or {},
        comments=raw.get("comments") or [],
        reactions=raw.get("reactions") or [],
    )


def discover_sources(structured_dir: Path, raw_posts_dir: Path) -> dict[str, Path]:
    sources: dict[str, Path] = {}

    if structured_dir.exists():
        for path in sorted(structured_dir.glob("*.json")):
            if not POST_ID_RE.match(path.name):
                continue
            post_id = path.stem
            sources[post_id] = path

    if raw_posts_dir.exists():
        for path in sorted(raw_posts_dir.glob("*.json")):
            if not POST_ID_RE.match(path.name):
                continue
            post_id = path.stem
            sources.setdefault(post_id, path)

    return sources


def clean_one(source: Path, out_dir: Path, *, from_raw: bool = False) -> dict[str, Any]:
    if from_raw or source.parent.name == "posts":
        data = load_from_raw_post(source)
    else:
        data = json.loads(source.read_text(encoding="utf-8"))

    cleaned = trim_structured(data)
    validate_structured_post(cleaned, source=str(source))

    post_id = cleaned["post"]["id"]
    out_path = out_dir / f"{post_id}.json"
    out_path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "postId": post_id,
        "source": str(source.relative_to(ROOT)),
        "output": str(out_path.relative_to(ROOT)),
        "people": len(cleaned["people"]),
        "comments": len(cleaned["comments"]),
        "reactions": len(cleaned["reactions"]),
        "lines": out_path.read_text(encoding="utf-8").count("\n") + 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean scraped posts for Stage 2 pipeline")
    parser.add_argument(
        "--structured-dir",
        type=Path,
        default=STRUCTURED_DIR,
        help="Scraper structured output directory",
    )
    parser.add_argument(
        "--raw-posts-dir",
        type=Path,
        default=RAW_POSTS_DIR,
        help="Scraper raw posts directory (fallback)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Where to write cleaned JSON (default: data/raw)",
    )
    args = parser.parse_args()

    structured_dir = args.structured_dir if args.structured_dir.is_absolute() else ROOT / args.structured_dir
    raw_posts_dir = args.raw_posts_dir if args.raw_posts_dir.is_absolute() else ROOT / args.raw_posts_dir
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = discover_sources(structured_dir, raw_posts_dir)
    if not sources:
        raise SystemExit(f"No post JSON files found under {structured_dir} or {raw_posts_dir}")

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for post_id, path in sorted(sources.items()):
        from_raw = path.parent.name == "posts"
        try:
            results.append(clean_one(path, out_dir, from_raw=from_raw))
            print(f"OK  {post_id}  people={results[-1]['people']}  comments={results[-1]['comments']}  reactions={results[-1]['reactions']}")
        except (StructuredPostValidationError, KeyError, json.JSONDecodeError) as exc:
            errors.append(f"{post_id}: {exc}")
            print(f"ERR {post_id}: {exc}")

    summary = {
        "cleaned": len(results),
        "failed": len(errors),
        "output_dir": str(out_dir.relative_to(ROOT)),
        "posts": results,
        "errors": errors,
    }
    summary_path = out_dir / "_clean_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"\nCleaned {len(results)} post(s) -> {out_dir}")
    if errors:
        print(f"Failed: {len(errors)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
