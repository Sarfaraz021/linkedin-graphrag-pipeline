# CURSOR_CHANGES.md — Align Pipeline to Sophie's Requirements

Change-order for Cursor. Apply on top of the existing `linkedin-graphrag-pipeline` (see `CURSOR_TASK.md`). Each section maps a client requirement to specific files and behaviour. Do the changes in the numbered order — 1–3 are schema/data model, 4–5 are filtering, 6 is UI.

## Context (why these changes)

The current graph is strong on **social engagement** (author, commenters, reactors, mentions). The client's product is **FMCG / challenger-brand ecosystem intelligence** — awards, organisations, brands, retailers, investors, events, accelerators. The scraping is fine; what's missing is **classification, schema alignment, and relevance filtering** so the graph answers "what awards/retailers/investors should a challenger brand know?" instead of "who liked this post?"

Worked reference example (use throughout): the **bCreator post** by Monique Anderson is an **Award** post — `IT'S RATED BY` / Monique `NOMINATED_FOR` `bCreator` (Talent Manager of the Year), `bCreator` `SUPPORTED_BY` `ITV`. The author is a talent manager, **not** a consumer-goods founder, so her personal engagement is low-relevance; the award, sponsor, and organisers are what matter.

---

## Change 1 — Post classification (top priority)

Add a **post-type classifier** that tags each `Post` node with a `category`.

- New file `src/classify.py`: an LLM step that reads the post content and returns one (or more) category from a **fixed list**:
  `Award`, `Fundraising`, `Investment`, `RetailerBuyer`, `FounderStory`, `Event`, `Partnership`, `ProductLaunch`, `Uncategorised`.
- Not every post gets a substantive label — default to `Uncategorised` when the content doesn't clearly support one. Do not force a category.
- Write results to the `Post` node: `category` (string), `categoryConfidence` (0–1), `categoryEvidence` (short quote from the post).
- The classifier prompt must be given the category list + a one-line definition of each, plus 2–3 few-shot examples (include the bCreator = `Award` example).

Acceptance: the bCreator post loads with `category = "Award"`.

---

## Change 2 — Align node schema to the client's entity types

Rename/extend the schema in `src/schema.py` to match the client's vocabulary from the Fiverr order (3 July). Use **her labels**, not generic ones.

**Core entity types (first-class nodes):**
`Person`, `Organisation`, `Brand`, `Retailer`, `Founder`, `Investor`, `Category`, `Trend`, `Post`, `Location`

**Extended types (from the long brief):**
`Buyer`, `Accelerator`, `Distributor`, `Event`, `Programme`, `Award`

Migration notes for Cursor:
- Rename `Company` → `Organisation` everywhere (nodes, Cypher, UI).
- `Brand` and `Retailer` are **their own labels**, not sub-types of Organisation. A node can carry multiple labels (e.g. `:Organisation:Retailer`).
- `Founder` and `Investor` are roles a `Person` can also hold — model as additional labels on the Person (`:Person:Founder`) OR as a `role` property; pick one and be consistent (prefer multi-label for queryability).
- Keep the deterministic backbone keys unchanged (Person on `id`, Post on `id`, mentioned Organisation on company `id`).

---

## Change 3 — Relationship vocabulary + edge properties

Extend `src/schema.py` relationship types and the extractor to produce the client's edges (not just backbone edges).

**Required relationships:**
`WROTE` (author→post; rename from `AUTHORED`), `MENTIONS`, `FOUNDED`, `WORKS_AT`, `LISTED_IN` (brand→retailer), `SUPPORTED_BY`, `OPERATES_IN`, `INVESTED_IN`, `BASED_IN`, plus `NOMINATED_FOR` and `SPONSORS` for awards.

**Edge properties on every LLM-inferred edge:**
- `confidence_score` (0–1)
- `source_post_url`
- `evidence_text` (the sentence the edge was inferred from)

Keep the deterministic backbone edges (`WROTE`, `COMMENTED`, `REACTED`, `MENTIONS`) as-is but ensure the extractor's semantic edges (`SUPPORTED_BY`, `LISTED_IN`, `INVESTED_IN`, …) carry the three properties above. This lets the client trust/trace inferred links.

Acceptance: bCreator post yields `(:Organisation {name:"bCreator"})-[:SUPPORTED_BY {confidence_score, source_post_url, evidence_text}]->(:Organisation {name:"ITV"})`.

---

## Change 4 — Author-relevance gate

Add `src/relevance.py`. Before/within extraction, classify the **author**:

- `is_consumer_brand_founder` (bool) — does the author own a physical consumer-goods product brand (something that ends up on a shop shelf), vs. a service/marketing/creator profile?
- Store on the author Person node: `author_relevance` (`high` | `low`) + `author_relevance_reason`.

Behaviour:
- **High relevance** (author is a consumer-brand founder): keep full engagement — commenters/reactors are candidate `Buyer` / `Founder` / `Investor` nodes and stay in the graph.
- **Low relevance** (e.g. creator/marketing/talent, like Monique): **do not centre the graph on the author or her 180 congrats reactors.** Keep the post's `Award` / `Organisation` / sponsor / organiser entities; demote generic engagement (see Change 5).

Do NOT delete data — tag it so it's filterable.

---

## Change 5 — Commenter / reactor filtering by headline

In `src/relevance.py`, tag each commenter/reactor Person with a `relevance` flag derived from their **headline/title**:

- Relevant roles: founder, co-founder, brand owner, buyer, retail buyer, investor, distributor, accelerator/programme lead.
- Noise: student, intern, unrelated roles.
- Store `engagement_relevance` (`relevant` | `noise`) + the matched role.

Keep everything in the graph but let the UI/queries filter on this flag. On **low-relevance-author** posts, default queries exclude `noise` engagement.

### HarvestAPI constraint (important — document in README)
HarvestAPI is **all-or-nothing** per post: you cannot selectively scrape some reactors/commenters. Therefore filtering happens at **ingest / entity-extraction**, not during scrape. Provide two modes via config:
- `ENGAGEMENT_MODE=full` — scrape everything, filter at ingest (default; richest data).
- `ENGAGEMENT_MODE=author_only` — for posts whose author is pre-classified low-relevance, skip pulling reactors/commenters entirely to **save cost** (~$1/post with full engagement × ~1,800 posts). Requires a lightweight author pre-check before the full scrape.

---

## Change 6 — UI: filter by entity + relationship, and the seed queries

- Add UI filters for **entity type** and **relationship type** (not chat-only), driven by the Change 2/3 labels.
- Wire these natural-language seed queries (the client's own test set) as suggested prompts and validate they return sensible results once the ~1,800 URLs are loaded:
  1. What organisations support challenger brands in FMCG?
  2. What retailers support challenger brands?
  3. Who are the investors supporting challenger brands?
  4. What awards should challenger brands consider?
  5. What events / trade shows should founders attend to get in front of buyers?
- Framing to keep in mind while building: the user is a founder asking **"where do I need to be seen to get funding, retail listings, and visibility?"** — not "who commented on this post."

---

## Acceptance criteria (all must pass on the bCreator sample + a founder-authored sample)

1. bCreator post `Post.category == "Award"` with evidence text populated.
2. Nodes exist for `bCreator` (Organisation/Award), `ITV` (Organisation), `IT'S RATED BY` (Organisation), with `NOMINATED_FOR` and `SUPPORTED_BY` edges carrying `confidence_score` + `source_post_url` + `evidence_text`.
3. Schema uses the client's labels (`Organisation`, `Brand`, `Retailer`, `Founder`, `Investor`, …) — no bare `Company` label remains.
4. Author Monique tagged `author_relevance = "low"` with a reason; her generic reactors tagged `engagement_relevance = "noise"` and excluded from default relevance-filtered queries — but still present in the DB.
5. A founder-authored post keeps full engagement (author_relevance = high).
6. UI exposes entity-type and relationship-type filters; the 5 seed queries run.
7. `ENGAGEMENT_MODE=author_only` skips reactor/commenter scraping for low-relevance authors (cost check).

---

## Two things to confirm with the client (flag, don't guess)

- **Category list is authoritative?** Change 1 uses `Award / Fundraising / Investment / RetailerBuyer / FounderStory / Event / Partnership / ProductLaunch`. Sophie said the agreed list is in the Fiverr order (3 July) — reconcile against that exact list before locking it in.
- **Scope of bCreator-type awards.** bCreator is a **creator/influencer** award, not an FMCG/consumer-brand award. It's a perfect *format* example for the `Award` category, but may be out of scope for her FMCG focus. Confirm whether creator-economy awards are in or out, so classification doesn't fill the graph with off-target awards.

---

## Kickoff prompt for Cursor

> Read `CURSOR_CHANGES.md` in full, then the existing `CURSOR_TASK.md` and `src/schema.py`. Apply the changes in order 1→6. Start with Changes 1–3 (classification + schema/relationship alignment), show me the updated `schema.py`, `classify.py`, and the bCreator sample output in Neo4j, and stop for review before doing the filtering (4–5) and UI (6). Do not delete any scraped data — relevance is a flag, not a deletion. Preserve deterministic backbone keys (Person on id, Post on id).
