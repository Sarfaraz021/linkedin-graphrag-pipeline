"""Post-type classification for FMCG ecosystem intelligence (Change 1)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from backend.pipeline.config import Settings
from backend.pipeline.llm_factory import build_llm, invoke_llm
from backend.pipeline.neo4j_client import Neo4jClient

POST_CATEGORIES: tuple[str, ...] = (
    "Award",
    "Fundraising",
    "Investment",
    "RetailerBuyer",
    "FounderStory",
    "Event",
    "Partnership",
    "ProductLaunch",
    "Uncategorised",
)

CATEGORY_DEFINITIONS: dict[str, str] = {
    "Award": "Post announces or discusses an award nomination, win, or award programme.",
    "Fundraising": "Post about raising capital, funding rounds, or seeking investment.",
    "Investment": "Post about an investment made, investor backing, or VC activity.",
    "RetailerBuyer": "Post involving retail buyers, listings, or retail partnerships.",
    "FounderStory": "Post centred on a founder's journey, brand story, or product launch narrative.",
    "Event": "Post about a trade show, conference, or industry event to attend.",
    "Partnership": "Post announcing a collaboration or partnership between organisations/brands.",
    "ProductLaunch": "Post launching or promoting a specific consumer product.",
    "Uncategorised": "Content does not clearly fit any category above.",
}

FEW_SHOT_EXAMPLES = """
Example 1 (Award):
Post: "4 x nominations for our agency at this years bCreator™ … Talent Manager of the Year … ITV as headline sponsors"
→ category: Award, confidence: 0.95, evidence: "4 x nominations for our agency at this years bCreator"

Example 2 (Fundraising):
Post: "Excited to announce we've closed our seed round with backing from …"
→ category: Fundraising, confidence: 0.92, evidence: "closed our seed round"

Example 3 (Uncategorised):
Post: "Happy Friday everyone — great week at the office!"
→ category: Uncategorised, confidence: 0.85, evidence: "Happy Friday everyone"
"""

CLASSIFIER_PROMPT = """You classify LinkedIn posts for an FMCG / challenger-brand ecosystem knowledge graph.

Allowed categories (use exactly one primary category):
{categories}

Definitions:
{definitions}

{examples}

Rules:
- Pick exactly ONE primary category from the allowed list.
- Use Uncategorised when the post does not clearly support a substantive label.
- Do NOT force a category.
- confidence is 0.0–1.0 reflecting how clearly the post fits the category.
- evidence must be a short direct quote (≤120 chars) from the post supporting the category.

Respond with JSON only:
{{"category": "<one of allowed categories>", "confidence": 0.0, "evidence": "<quote>"}}

Post URL: {post_url}
Post content:
{content}
"""


@dataclass
class PostClassification:
    category: str
    confidence: float
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


def _build_prompt(post: dict[str, Any]) -> str:
    categories = ", ".join(POST_CATEGORIES)
    definitions = "\n".join(f"- {k}: {v}" for k, v in CATEGORY_DEFINITIONS.items())
    return CLASSIFIER_PROMPT.format(
        categories=categories,
        definitions=definitions,
        examples=FEW_SHOT_EXAMPLES.strip(),
        post_url=post.get("url") or post.get("shareUrl") or "",
        content=(post.get("content") or "")[:6000],
    )


def _parse_classification(raw: str) -> PostClassification:
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    data = json.loads(text)
    category = str(data.get("category", "Uncategorised"))
    if category not in POST_CATEGORIES:
        category = "Uncategorised"
    confidence = float(data.get("confidence", 0.0))
    confidence = max(0.0, min(1.0, confidence))
    evidence = str(data.get("evidence", ""))[:500]
    return PostClassification(category=category, confidence=confidence, evidence=evidence)


def classify_post(post: dict[str, Any], settings: Settings) -> PostClassification:
    """Classify a single post dict (from structured JSON `post` key)."""
    if not settings.openai_api_key and not settings.anthropic_api_key:
        raise ValueError("OPENAI_API_KEY or ANTHROPIC_API_KEY is required for classification")

    llm = build_llm(settings, json_mode=True)
    content = invoke_llm(llm, _build_prompt(post))
    return _parse_classification(content)


def persist_classification(
    client: Neo4jClient,
    post_id: str,
    classification: PostClassification,
) -> None:
    """Write category fields onto the backbone Post node."""
    client.run_write(
        """
        MATCH (post:Post {id: $post_id})
        SET post.category = $category,
            post.categoryConfidence = $confidence,
            post.categoryEvidence = $evidence,
            post.updatedAt = datetime()
        """,
        {
            "post_id": post_id,
            "category": classification.category,
            "confidence": classification.confidence,
            "evidence": classification.evidence,
        },
    )


def classify_and_persist_post(
    client: Neo4jClient,
    settings: Settings,
    post: dict[str, Any],
) -> PostClassification:
    classification = classify_post(post, settings)
    persist_classification(client, post["id"], classification)
    return classification


def classify_and_persist_posts(
    client: Neo4jClient,
    settings: Settings,
    posts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Classify all posts and persist results. Returns summary rows."""
    results: list[dict[str, Any]] = []
    for data in posts:
        post = data["post"]
        classification = classify_and_persist_post(client, settings, post)
        results.append({"postId": post["id"], **classification.to_dict()})
    return results
