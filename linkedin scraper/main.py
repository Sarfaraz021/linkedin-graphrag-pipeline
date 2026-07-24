#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LinkedIn Post Scraper -> Graph-ready JSON
=========================================

Reads LinkedIn post URLs from an Excel sheet, then for each post uses the
HarvestAPI (https://docs.harvestapi.io) to collect:

    * the post content + author details
    * EVERY comment  (with the full profile of each commenter)
    * EVERY reaction (with the full profile of each person who reacted)

...not just the counts. It writes:

    output/
      posts/<postId>.json       <- raw HarvestAPI response per post (debugging / full fidelity)
      structured/<postId>.json <- CLEAN, normalized, de-duplicated JSON (the one to read/feed in)
      graph/nodes.jsonl         <- deduplicated Person / Post nodes across ALL posts (one JSON/line)
      graph/relationships.jsonl<- AUTHORED / COMMENTED / REACTED edges (one JSON per line)
      graph/graph.json          <- everything in one structured object (nodes + relationships)

The .jsonl files load directly into Neo4j / Memgraph / any bulk graph loader.

structured/<postId>.json is the readable, "proper" schema: one post object,
a de-duplicated people{} dict keyed by person id (each with roles: author /
commenter / reactor), and comments/reactions that just reference personId
instead of repeating the whole profile every time.

-------------------------------------------------------------------------------
SETUP (run once in a terminal):
    pip install requests pandas openpyxl

RUN:
    python linkedin_scraper.py
    # or override anything, e.g.:
    python linkedin_scraper.py --no-reactions --sort-by date --max-pages 5
    # add full profile detail (location, company, connections) per unique person:
    python linkedin_scraper.py --enrich --enrich-mode basic
-------------------------------------------------------------------------------
"""

import os
import sys
import json
import time
import argparse
import subprocess
import importlib
from datetime import datetime, timezone


def _ensure_dependencies():
    """Auto-install required packages if missing; skip any already present."""
    # (import name, pip install name) -- same here, but kept explicit.
    required = [
        ("requests", "requests"),
        ("pandas", "pandas"),
        ("openpyxl", "openpyxl"),  # needed by pandas to read .xlsx
    ]
    for import_name, pip_name in required:
        try:
            importlib.import_module(import_name)   # already installed -> skip
        except ImportError:
            print(f"[setup] '{import_name}' not found - installing '{pip_name}' ...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pip_name]
                )
            except subprocess.CalledProcessError:
                sys.exit(
                    f"[setup] Could not install '{pip_name}' automatically.\n"
                    f"        Install it manually with:  "
                    f"{os.path.basename(sys.executable)} -m pip install {pip_name}"
                )


_ensure_dependencies()

import requests          # noqa: E402  (imported after the bootstrap above)
import pandas as pd      # noqa: E402


# =============================================================================
# CONFIG  -- edit these defaults, or override them on the command line.
# =============================================================================
API_KEY      = "Oy2teNO9EyGdjlnBLk4kSHUKzZi7O9Sy"                     # test key
EXCEL_PATH   = r"C:\Users\engin\Downloads\linkedin post url.xlsx"      # input
OUTPUT_DIR   = r"C:\Users\engin\Desktop\linkedin scraper\output"       # output folder

FETCH_POST        = True     # fetch post content + author
FETCH_COMMENTS    = True     # fetch all commenters (profiles)
FETCH_REACTIONS   = True     # fetch all reactors  (profiles)

# --- How many post URLs from the sheet to process ----------------------------
MAX_URLS          = 1        # 0 = use every URL; e.g. 5 = only the first 5
SKIP_URLS         = 0        # skip this many URLs from the top before starting

COMMENTS_SORT_BY  = "date"   # "date" or "relevance"

# --- How much to scrape, per endpoint (0 = no limit / everything) ------------
# Profile-COUNT caps: the primary knobs. Stop after collecting this many people.
MAX_COMMENTS      = 0        # e.g. 50 = only the first 50 commenter profiles
MAX_REACTIONS     = 0        # e.g. 100 = only the first 100 reactor profiles
# Optional PAGE caps (each page is ~10 profiles). Left at 0 unless you prefer
# to think in pages. If both a count and a page cap are set, whichever is hit
# first wins.
COMMENT_PAGES     = 0
REACTION_PAGES    = 0
MAX_PAGES         = 0        # convenience: applies to both if the two above are 0

RESOLVE_REACTOR_SLUGS = False  # True = extra API call per reactor to get clean /in/<slug> URL

# --- Profile enrichment (optional, extra API calls -- OFF by default) --------
# When ON, fetches the full LinkedIn profile (location, current company,
# connections, follower count, open-to-work) for every unique person seen
# across the whole run. Cached, so each person is only ever fetched ONCE no
# matter how many posts/comments/reactions they show up in.
ENRICH_PROFILES  = True
ENRICH_MODE      = "full"   # "basic" = cheaper, up to 5 exp/2 edu/2 skills; "full" = complete profile
ENRICH_EMAIL     = True     # extra credits: attempts SMTP-verified email lookup per person

# --- Which output files to write ---------------------------------------------
WRITE_RAW        = True      # posts/<postId>.json        - raw HarvestAPI response
WRITE_STRUCTURED = True      # structured/<postId>.json   - clean, de-duplicated schema

# --- Resume / avoid re-scraping posts you already have -----------------------
# On every run, a manifest.json in the output folder records what was already
# collected for each post URL. The next run skips a URL entirely (0 API calls)
# if the manifest shows it already has AT LEAST as much data as this run is
# asking for. Set REFRESH=True to ignore the manifest and re-scrape everything.
REFRESH           = False

API_BASE   = "https://api.harvest-api.com"
PAGE_SLEEP = 0.4             # polite pause between paged requests (seconds)
MAX_RETRIES = 4             # retries on 429 / transient errors
# =============================================================================


# ------------------------------------------------------------------ HTTP layer
def api_get(session, path, params):
    """GET {API_BASE}{path} with retry/backoff. Returns parsed JSON dict."""
    url = f"{API_BASE}{path}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=60)
        except requests.RequestException as e:
            wait = 2 * attempt
            print(f"    ! network error ({e}); retry in {wait}s")
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:  # rate limited
            wait = 5 * attempt
            print(f"    ! 429 rate limited; waiting {wait}s")
            time.sleep(wait)
            continue

        # Other errors: show body once and give up on this call.
        print(f"    ! HTTP {resp.status_code}: {resp.text[:300]}")
        return None

    print("    ! gave up after retries")
    return None


# --------------------------------------------------------------- Excel loading
def load_urls_from_excel(path):
    """Read post URLs from the sheet. Uses the column that looks like URLs,
    otherwise the first column. Blank rows are skipped."""
    if not os.path.exists(path):
        sys.exit(f"Excel file not found: {path}")

    df = pd.read_excel(path, dtype=str)  # needs openpyxl for .xlsx
    if df.empty:
        sys.exit("Excel sheet is empty.")

    # Find the column that most looks like it holds linkedin URLs.
    best_col, best_hits = None, -1
    for col in df.columns:
        hits = df[col].fillna("").str.contains("linkedin.com", case=False).sum()
        if hits > best_hits:
            best_col, best_hits = col, hits
    if best_hits <= 0:
        best_col = df.columns[0]  # fall back to first column

    urls = [
        u.strip()
        for u in df[best_col].fillna("").tolist()
        if u and u.strip() and "linkedin.com" in u.lower()
    ]
    # de-dupe, keep order
    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


# ------------------------------------------------------------ API fetch helpers
def fetch_post(session, post_url):
    data = api_get(session, "/linkedin/post", {"url": post_url})
    if not data:
        return None
    return data.get("element")


def fetch_paginated(session, path, base_params, max_pages=0, max_items=0):
    """Walk pages of a paginated endpoint and return the combined 'elements'.

    Stops as soon as EITHER cap is reached (whichever comes first):
        max_items -> total profiles collected (0 = unlimited)
        max_pages -> number of pages fetched   (0 = unlimited)
    The result is trimmed to exactly max_items when that cap is set.
    Handles the relevance-sort paginationToken automatically.
    """
    collected = []
    page = 1
    token = None
    while True:
        params = dict(base_params)
        params["page"] = page
        if token:
            params["paginationToken"] = token

        data = api_get(session, path, params)
        if not data:
            break

        elements = data.get("elements") or []
        collected.extend(elements)

        pg = data.get("pagination") or {}
        total_pages = pg.get("totalPages") or 1
        token = pg.get("paginationToken")  # may be None

        print(f"      page {page}/{total_pages}  (+{len(elements)}, total {len(collected)})")

        if not elements:
            break
        if max_items and len(collected) >= max_items:
            print(f"      (stopped early at max_items={max_items})")
            break
        if page >= total_pages:
            break
        if max_pages and page >= max_pages:
            print(f"      (stopped early at max_pages={max_pages})")
            break

        page += 1
        time.sleep(PAGE_SLEEP)

    if max_items:
        collected = collected[:max_items]  # trim to the exact cap
    return collected


def fetch_all_comments(session, post_url, sort_by, max_pages=0, max_items=0):
    return fetch_paginated(
        session, "/linkedin/post-comments",
        {"post": post_url, "sortBy": sort_by},
        max_pages=max_pages, max_items=max_items,
    )


def fetch_all_reactions(session, post_url, max_pages=0, max_items=0):
    return fetch_paginated(
        session, "/linkedin/post-reactions",
        {"post": post_url},
        max_pages=max_pages, max_items=max_items,
    )


# --------------------------------------------------------- Profile enrichment
def _apply_enrichment(target, extra, url_key):
    """Merge an enrichment dict into a target dict (a structured 'people'
    entry, or a graph node's 'properties'), without mutating the cached
    'extra' dict itself (it's shared across every place that person appears).
    'resolvedUrl' is renamed to whatever key the target uses for its URL
    ('url' in structured output, 'linkedinUrl' in graph nodes)."""
    if not extra:
        return
    for k, v in extra.items():
        if k == "resolvedUrl":
            if v:
                target[url_key] = v
        else:
            target[k] = v


# --------------------------------------------------------- Profile enrichment
class ProfileEnricher:
    """Fetches full LinkedIn profile details via GET /linkedin/profile, ONCE
    per unique person, no matter how many times they appear across posts,
    comments, or reactions -- and, when cache_path is given, ONCE ever across
    every run of the script, by persisting successful lookups to disk.

    Only SUCCESSFUL lookups are persisted. A failed lookup is remembered for
    the rest of THIS run (so we don't hammer a dead URL twice today) but is
    deliberately not written to disk, so a transient error doesn't
    permanently blacklist that person from future runs.
    """

    def __init__(self, basic=True, find_email=False, cache_path=None, ignore_disk_cache=False):
        self.basic = basic
        self.find_email = find_email
        self.cache_path = cache_path
        self.cache = {}     # person id -> extra-fields dict, or None if lookup failed this run
        self.loaded_from_disk = 0

        if cache_path and not ignore_disk_cache and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    on_disk = json.load(f)
                self.cache.update(on_disk)
                self.loaded_from_disk = len(on_disk)
            except Exception:
                print(f"  ! could not read {cache_path}; starting a fresh profile cache")

    def _save(self):
        if not self.cache_path:
            return
        # only ever persist real successes -- never bake in a failure
        on_disk = {k: v for k, v in self.cache.items() if v}
        tmp = self.cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(on_disk, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.cache_path)

    def get(self, session, person_id, fallback_url=None):
        if not person_id:
            return None
        if person_id in self.cache:
            return self.cache[person_id]

        params = {}
        if fallback_url:
            params["url"] = fallback_url
        else:
            params["url"] = f"https://www.linkedin.com/in/{person_id}"
        if self.basic:
            params["basic"] = "true"
        if self.find_email:
            params["findEmail"] = "true"

        data = api_get(session, "/linkedin/profile", params)
        element = (data or {}).get("element")
        if not element:
            self.cache[person_id] = None   # in-memory only for this run; not persisted
            return None

        loc = (element.get("location") or {})
        parsed = loc.get("parsed") or {}
        current = (element.get("currentPosition") or [{}])[0] if element.get("currentPosition") else {}

        extra = {
            "resolvedUrl": element.get("linkedinUrl"),  # clean /in/<slug> form -- free, same call
            "headline": element.get("headline"),
            "location": parsed.get("text") or loc.get("linkedinText"),
            "country": parsed.get("countryFull") or parsed.get("country"),
            "currentCompany": current.get("companyName"),
            "connectionsCount": element.get("connectionsCount"),
            "followerCount": element.get("followerCount"),
            "openToWork": element.get("openToWork"),
        }
        if self.find_email:
            extra["email"] = element.get("email")

        extra = {k: v for k, v in extra.items() if v not in (None, "", [])}
        self.cache[person_id] = extra
        self._save()   # persist immediately -- a new successful lookup is never lost
        time.sleep(PAGE_SLEEP)
        return extra


# ------------------------------------------------------- Normalized JSON schema
def _merge_person(people, actor, role):
    """Add/update a person in the de-duplicated people{} dict and record the
    role (author/commenter/reactor) they played on this post."""
    if not actor:
        return None
    pid = actor.get("id") or actor.get("linkedinUrl")
    if not pid:
        return None

    entry = people.get(pid)
    if entry is None:
        entry = {
            "id": pid,
            "name": actor.get("name"),
            "headline": actor.get("position") or actor.get("info"),
            "url": actor.get("linkedinUrl"),
            "avatarUrl": actor.get("pictureUrl"),
            "roles": [],
        }
        people[pid] = entry
    else:
        for k_src, k_dst in [("name", "name"), ("linkedinUrl", "url"),
                              ("position", "headline"), ("info", "headline"),
                              ("pictureUrl", "avatarUrl")]:
            if not entry.get(k_dst) and actor.get(k_src):
                entry[k_dst] = actor.get(k_src)

    if role not in entry["roles"]:
        entry["roles"].append(role)
    return pid


def normalize_post(post_url, post_id, element, comments, reactions,
                    enricher=None, session=None):
    """Turn the raw HarvestAPI response into a clean, de-duplicated,
    graph-ready schema: one post object, a people{} dict keyed by person id
    (each with the roles they played), and comments/reactions that reference
    personId instead of repeating the whole profile every time."""
    element = element or {}
    author = element.get("author") or {}
    engagement = element.get("engagement") or {}
    posted = element.get("postedAt") or {}

    rx_list = engagement.get("reactions") or []
    reaction_breakdown = {r.get("type"): r.get("count") for r in rx_list if r.get("type")}
    reactions_total = sum(reaction_breakdown.values()) if reaction_breakdown else engagement.get("likes")

    mentions = []
    for attr in element.get("contentAttributes") or []:
        prof = attr.get("profile")
        comp = attr.get("company")
        if prof:
            mentions.append({
                "type": "person",
                "id": prof.get("id"),
                "name": f'{prof.get("firstName","")} {prof.get("lastName","")}'.strip(),
                "url": prof.get("linkedinUrl"),
            })
        elif comp:
            mentions.append({
                "type": "company",
                "id": comp.get("id"),
                "name": comp.get("name"),
                "url": comp.get("linkedinUrl"),
            })

    people = {}
    author_id = _merge_person(people, author, "author") if author else None

    norm_comments = []
    for c in comments:
        pid = _merge_person(people, c.get("actor"), "commenter")
        rc = (c.get("engagement") or {}).get("reactions") or []
        rc_total = sum(x.get("count", 0) for x in rc)
        norm_comments.append({
            "id": c.get("id"),
            "url": c.get("linkedinUrl"),
            "text": c.get("commentary"),
            "createdAt": c.get("createdAt"),
            "reactionsOnComment": rc_total,
            "personId": pid,
        })

    norm_reactions = []
    for r in reactions:
        pid = _merge_person(people, r.get("actor"), "reactor")
        norm_reactions.append({
            "id": r.get("id"),
            "type": r.get("reactionType"),
            "personId": pid,
        })

    if enricher and session:
        for pid, entry in people.items():
            extra = enricher.get(session, pid, entry.get("url"))
            _apply_enrichment(entry, extra, url_key="url")

    return {
        "schemaVersion": "1.0",
        "post": {
            "id": post_id,
            "url": post_url,
            "shareUrl": (element.get("socialContent") or {}).get("shareUrl") or element.get("shareLinkedinUrl"),
            "postedAt": posted.get("date"),
            "content": element.get("content"),
            "images": [img.get("url") for img in (element.get("postImages") or [])],
            "mentions": mentions,
            "authorId": author_id,
            "engagement": {
                "reactionsTotal": reactions_total,
                "commentsTotal": engagement.get("comments"),
                "sharesTotal": engagement.get("shares"),
                "reactionBreakdown": reaction_breakdown,
            },
        },
        "people": people,
        "comments": norm_comments,
        "reactions": norm_reactions,
        "coverage": {
            "commentsCollected": len(comments),
            "commentsTotal": engagement.get("comments"),
            "reactionsCollected": len(reactions),
            "reactionsTotal": reactions_total,
        },
    }


# ------------------------------------------------------------- Graph accumulator
class GraphBuilder:
    """Deduplicates Person / Post nodes and collects relationship edges."""

    def __init__(self):
        self.persons = {}          # actor_id -> node dict
        self.posts = {}            # post_id  -> node dict
        self.relationships = []    # list of edge dicts

    def add_person(self, actor):
        if not actor:
            return None
        pid = actor.get("id") or actor.get("linkedinUrl")
        if not pid:
            return None
        if pid not in self.persons:
            self.persons[pid] = {
                "id": pid,
                "label": "Person",
                "properties": {
                    "name": actor.get("name"),
                    "linkedinUrl": actor.get("linkedinUrl"),
                    "position": actor.get("position"),
                    "pictureUrl": actor.get("pictureUrl"),
                },
            }
        else:
            # fill in any property we didn't have before
            props = self.persons[pid]["properties"]
            for k_src, k_dst in [("name", "name"), ("linkedinUrl", "linkedinUrl"),
                                 ("position", "position"), ("pictureUrl", "pictureUrl")]:
                if not props.get(k_dst) and actor.get(k_src):
                    props[k_dst] = actor.get(k_src)
        return pid

    def add_post(self, post_id, post_url, element):
        if post_id not in self.posts:
            engagement = (element or {}).get("engagement") or {}
            posted = (element or {}).get("postedAt") or {}
            self.posts[post_id] = {
                "id": post_id,
                "label": "Post",
                "properties": {
                    "url": post_url,
                    "linkedinUrl": (element or {}).get("linkedinUrl") or post_url,
                    "content": (element or {}).get("content"),
                    "postedAt": posted.get("date"),
                    "likes": engagement.get("likes"),
                    "comments": engagement.get("comments"),
                    "shares": engagement.get("shares"),
                },
            }
        return post_id

    def add_rel(self, src_id, rel_type, dst_id, props=None):
        if not src_id or not dst_id:
            return
        self.relationships.append({
            "from": src_id,
            "type": rel_type,
            "to": dst_id,
            "properties": props or {},
        })

    def dump(self, graph_dir):
        os.makedirs(graph_dir, exist_ok=True)
        nodes = list(self.persons.values()) + list(self.posts.values())

        with open(os.path.join(graph_dir, "nodes.jsonl"), "w", encoding="utf-8") as f:
            for n in nodes:
                f.write(json.dumps(n, ensure_ascii=False) + "\n")

        with open(os.path.join(graph_dir, "relationships.jsonl"), "w", encoding="utf-8") as f:
            for r in self.relationships:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        with open(os.path.join(graph_dir, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({"nodes": nodes, "relationships": self.relationships},
                      f, ensure_ascii=False, indent=2)

        print(f"\nGraph written: {len(nodes)} nodes, "
              f"{len(self.relationships)} relationships -> {graph_dir}")


# ---------------------------------------------------------------- post id helper
def derive_post_id(element, comments, reactions, post_url):
    """Find a stable post id from whatever data we have."""
    if element and element.get("id"):
        return str(element["id"])
    for coll in (comments, reactions):
        for item in coll:
            if item.get("postId"):
                return str(item["postId"])
    # last resort: use the URL itself
    return post_url


# --------------------------------------------------- Resume / avoid re-scraping
MANIFEST_NAME = "manifest.json"


def load_manifest(output_dir):
    """manifest.json remembers, per post URL, what was already collected --
    so re-running the script doesn't burn API calls on posts it already has."""
    path = os.path.join(output_dir, MANIFEST_NAME)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(f"  ! could not read {path}; starting a fresh manifest")
    return {}


def save_manifest(output_dir, manifest):
    """Written after EVERY post (not just at the end), so a crash or Ctrl-C
    partway through a big sheet never throws away the progress already made."""
    path = os.path.join(output_dir, MANIFEST_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic on both Windows and POSIX


def _cap_covers(prior_cap, prior_fetched, requested_cap):
    """Did a PRIOR run already collect at least as much as THIS run is asking
    for? prior_cap/requested_cap of 0 means 'no limit' (i.e. everything)."""
    if not prior_fetched:
        return False
    if prior_cap == 0:
        return True                    # prior run already got everything
    if requested_cap == 0:
        return False                   # now we want everything; prior was capped
    return prior_cap >= requested_cap


def load_cached_raw(output_dir, post_id):
    """Reload a previously-saved raw dump from disk instead of re-hitting the API."""
    safe_name = post_id.replace(":", "_").replace("/", "_")[:120]
    path = os.path.join(output_dir, "posts", f"{safe_name}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ------------------------------------------------------------------------- main
def process_post(session, post_url, args, graph, enricher=None, prior=None):
    print(f"\n=== {post_url}")
    prior = prior or {}

    # --- Can we skip the API entirely and reuse a previous run's raw dump? ---
    resumable = (
        not args.refresh
        and args.write_raw
        and bool(prior.get("postId"))
        and (not args.fetch_post or prior.get("fetchedPost"))
        and (not args.fetch_comments or _cap_covers(
            prior.get("commentsCapUsed", 0), prior.get("fetchedComments", False), args.max_comments))
        and (not args.fetch_reactions or _cap_covers(
            prior.get("reactionsCapUsed", 0), prior.get("fetchedReactions", False), args.max_reactions))
    )
    cached = load_cached_raw(args.output_dir, prior.get("postId")) if resumable else None

    if cached:
        print("  (already have enough data from a previous run - reusing it, 0 API calls)")
        element = cached.get("post")
        comments = cached.get("comments") or []
        reactions = cached.get("reactions") or []
        # a prior run may have collected MORE than this run asks for -- trim
        # so behavior matches what was actually requested this time.
        if args.fetch_comments and args.max_comments:
            comments = comments[:args.max_comments]
        if args.fetch_reactions and args.max_reactions:
            reactions = reactions[:args.max_reactions]
        if not args.fetch_comments:
            comments = []
        if not args.fetch_reactions:
            reactions = []
        post_id = prior["postId"]
    else:
        element = fetch_post(session, post_url) if args.fetch_post else None
        if args.fetch_post:
            print("  post: " + ("ok" if element else "FAILED"))

        # Resolve effective page caps: a specific --comment-pages / --reaction-pages
        # wins; otherwise fall back to the shared --max-pages.
        comment_pages  = args.comment_pages  or args.max_pages
        reaction_pages = args.reaction_pages or args.max_pages

        comments = []
        if args.fetch_comments:
            print(f"  comments (cap: {args.max_comments or 'all'} profiles):")
            comments = fetch_all_comments(
                session, post_url, args.sort_by,
                max_pages=comment_pages, max_items=args.max_comments,
            )

        reactions = []
        if args.fetch_reactions:
            print(f"  reactions (cap: {args.max_reactions or 'all'} profiles):")
            reactions = fetch_all_reactions(
                session, post_url,
                max_pages=reaction_pages, max_items=args.max_reactions,
            )

        post_id = derive_post_id(element, comments, reactions, post_url)

    # --- raw per-post JSON (full HarvestAPI response, for debugging/fidelity) ---
    if args.write_raw:
        posts_dir = os.path.join(args.output_dir, "posts")
        os.makedirs(posts_dir, exist_ok=True)
        safe_name = post_id.replace(":", "_").replace("/", "_")[:120]
        raw = {
            "postUrl": post_url,
            "postId": post_id,
            "post": element,
            "comments": comments,
            "reactions": reactions,
            "counts": {
                "commentsCollected": len(comments),
                "reactionsCollected": len(reactions),
            },
        }
        with open(os.path.join(posts_dir, f"{safe_name}.json"), "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

    # --- structured / graph-ready JSON: clean, de-duplicated, typed schema ---
    if args.write_structured:
        safe_name = post_id.replace(":", "_").replace("/", "_")[:120]
        structured_dir = os.path.join(args.output_dir, "structured")
        os.makedirs(structured_dir, exist_ok=True)
        structured = normalize_post(
            post_url, post_id, element, comments, reactions,
            enricher=enricher, session=session,
        )
        with open(os.path.join(structured_dir, f"{safe_name}.json"), "w", encoding="utf-8") as f:
            json.dump(structured, f, ensure_ascii=False, indent=2)

    # --- graph model (aggregated across ALL posts) ---
    graph.add_post(post_id, post_url, element)

    if element and element.get("author"):
        actor = element["author"]
        author_id = graph.add_person(actor)
        if enricher:
            extra = enricher.get(session, author_id, actor.get("linkedinUrl"))
            _apply_enrichment(graph.persons[author_id]["properties"], extra, "linkedinUrl")
        graph.add_rel(author_id, "AUTHORED", post_id)

    for c in comments:
        actor = c.get("actor")
        pid = graph.add_person(actor)
        if enricher and actor:
            extra = enricher.get(session, pid, actor.get("linkedinUrl"))
            _apply_enrichment(graph.persons[pid]["properties"], extra, "linkedinUrl")
        graph.add_rel(pid, "COMMENTED", post_id, {
            "commentId": c.get("id"),
            "commentary": c.get("commentary"),
            "createdAt": c.get("createdAt"),
            "commentUrl": c.get("linkedinUrl"),
        })

    for r in reactions:
        actor = r.get("actor")
        pid = graph.add_person(actor)
        if enricher and actor:
            extra = enricher.get(session, pid, actor.get("linkedinUrl"))
            _apply_enrichment(graph.persons[pid]["properties"], extra, "linkedinUrl")
        graph.add_rel(pid, "REACTED", post_id, {
            "reactionType": r.get("reactionType"),
        })

    print(f"  -> {len(comments)} comments, {len(reactions)} reactions captured")

    # --- manifest entry: what THIS run has, so the NEXT run can skip work it
    # doesn't need to redo. A failed/skipped fetch (element/list stays empty)
    # is recorded as NOT fetched, so it will retry automatically next time.
    return {
        "postId": post_id,
        "scrapedAt": datetime.now(timezone.utc).isoformat(),
        "fetchedPost": bool(args.fetch_post and element is not None),
        "fetchedComments": bool(args.fetch_comments),
        "commentsCapUsed": args.max_comments,
        "commentsCollected": len(comments),
        "fetchedReactions": bool(args.fetch_reactions),
        "reactionsCapUsed": args.max_reactions,
        "reactionsCollected": len(reactions),
    }


def parse_args():
    p = argparse.ArgumentParser(description="LinkedIn -> graph JSON scraper (HarvestAPI)")
    p.add_argument("--api-key",   default=API_KEY)
    p.add_argument("--excel",     default=EXCEL_PATH, dest="excel_path")
    p.add_argument("--output-dir", default=OUTPUT_DIR, dest="output_dir")

    # --- how many URLs from the sheet to process ---
    p.add_argument("--max-urls", type=int, default=MAX_URLS,
                   help="cap number of post URLs to process (0 = all)")
    p.add_argument("--skip", type=int, default=SKIP_URLS,
                   help="skip this many URLs from the top before starting")

    p.add_argument("--sort-by",   default=COMMENTS_SORT_BY, choices=["date", "relevance"])

    # --- how much to scrape (0 = everything) ---
    p.add_argument("--max-comments",  type=int, default=MAX_COMMENTS,
                   help="cap number of commenter profiles per post (0 = all)")
    p.add_argument("--max-reactions", type=int, default=MAX_REACTIONS,
                   help="cap number of reactor profiles per post (0 = all)")
    p.add_argument("--comment-pages", type=int, default=COMMENT_PAGES,
                   help="cap comment pages per post (0 = use --max-pages)")
    p.add_argument("--reaction-pages", type=int, default=REACTION_PAGES,
                   help="cap reaction pages per post (0 = use --max-pages)")
    p.add_argument("--max-pages", type=int, default=MAX_PAGES,
                   help="shared page cap for both endpoints (0 = all)")
    # toggles (default ON; pass --no-... to disable)
    p.add_argument("--no-post",      dest="fetch_post",      action="store_false", default=FETCH_POST)
    p.add_argument("--no-comments",  dest="fetch_comments",  action="store_false", default=FETCH_COMMENTS)
    p.add_argument("--no-reactions", dest="fetch_reactions", action="store_false", default=FETCH_REACTIONS)
    p.add_argument("--resolve-slugs", dest="resolve_slugs", action="store_true",
                   default=RESOLVE_REACTOR_SLUGS,
                   help="resolve clean /in/<slug> profile URLs via a cheap 'basic' "
                        "lookup, cached once per unique person (shares the cache "
                        "with --enrich, so nobody is ever fetched twice)")

    # --- profile enrichment (optional, extra API calls, cached per person) ---
    p.add_argument("--enrich", dest="enrich", action="store_true", default=ENRICH_PROFILES,
                   help="fetch full profile (location, company, connections) once per unique person")
    p.add_argument("--enrich-mode", default=ENRICH_MODE, choices=["basic", "full"],
                   help="'basic' = cheaper/fewer experiences; 'full' = complete profile (more credits)")
    p.add_argument("--enrich-email", dest="enrich_email", action="store_true", default=ENRICH_EMAIL,
                   help="also attempt SMTP-verified email lookup per person (costs more credits)")

    # --- which output files to write ---
    p.add_argument("--no-raw", dest="write_raw", action="store_false", default=WRITE_RAW,
                   help="skip writing the raw HarvestAPI dump to posts/ "
                        "(NOTE: also disables resume-from-cache on the next run)")
    p.add_argument("--no-structured", dest="write_structured", action="store_false", default=WRITE_STRUCTURED,
                   help="skip writing the clean structured/ JSON")

    # --- resume behavior ---
    p.add_argument("--refresh", dest="refresh", action="store_true", default=REFRESH,
                   help="ignore manifest.json and re-scrape every URL from scratch, "
                        "even ones already fully collected in a previous run")
    p.add_argument("--refresh-profiles", dest="refresh_profiles", action="store_true", default=False,
                   help="ignore the on-disk profile cache and re-fetch every person's "
                        "enrichment/slug data (use this if you turned on --enrich-email "
                        "after already caching people without it)")
    return p.parse_args()


def main():
    args = parse_args()

    urls = load_urls_from_excel(args.excel_path)
    if not urls:
        sys.exit("No LinkedIn URLs found in the Excel sheet.")
    total_found = len(urls)

    # Apply skip + cap (skip first, then limit the remainder).
    if args.skip:
        urls = urls[args.skip:]
    if args.max_urls:
        urls = urls[:args.max_urls]
    if not urls:
        sys.exit(f"Nothing to process after skip={args.skip}, "
                 f"max_urls={args.max_urls} (sheet had {total_found} URLs).")

    print(f"Sheet had {total_found} URL(s); processing {len(urls)} "
          f"(skip={args.skip}, max_urls={args.max_urls or 'all'}).")

    os.makedirs(args.output_dir, exist_ok=True)

    session = requests.Session()
    session.headers.update({"X-API-Key": args.api_key})

    # One enricher, shared by --enrich and --resolve-slugs, so a person is
    # ever only fetched once regardless of which flag(s) asked for it -- and
    # its results persist to disk, so re-running the script later doesn't
    # re-fetch people it already has.
    enricher = None
    if args.enrich or args.resolve_slugs:
        basic_mode = (args.enrich_mode == "basic") if args.enrich else True
        cache_path = os.path.join(args.output_dir, "profile_cache.json")
        enricher = ProfileEnricher(basic=basic_mode, find_email=args.enrich_email,
                                    cache_path=cache_path, ignore_disk_cache=args.refresh_profiles)
        reasons = []
        if args.enrich:
            reasons.append(f"enrichment (mode={args.enrich_mode})")
        if args.resolve_slugs:
            reasons.append("slug resolution")
        print(f"Profile lookups ON: {' + '.join(reasons)} "
              f"- each unique person is fetched once and cached"
              f"{f' ({enricher.loaded_from_disk} already on disk from a previous run)' if enricher.loaded_from_disk else ''}.")

    manifest = {} if args.refresh else load_manifest(args.output_dir)
    if not args.refresh and not args.write_raw:
        print("Note: --no-raw disables resume-from-cache (nothing saved to "
              "reload from), so every URL will be fetched fresh this run.")

    graph = GraphBuilder()
    for post_url in urls:
        try:
            prior = manifest.get(post_url)
            result = process_post(session, post_url, args, graph, enricher, prior)
            manifest[post_url] = result
            save_manifest(args.output_dir, manifest)  # save after every post -- never lose progress
        except Exception as e:                       # keep going on one bad post
            print(f"  ! error on this post: {e}")

    graph.dump(os.path.join(args.output_dir, "graph"))

    if enricher:
        ok = sum(1 for v in enricher.cache.values() if v)
        fresh_calls = len(enricher.cache) - enricher.loaded_from_disk
        print(f"Enrichment: {ok}/{len(enricher.cache)} unique profiles resolved "
              f"({fresh_calls} new API call(s) this run, "
              f"{enricher.loaded_from_disk} reused from disk).")

    print("\nDone.")


if __name__ == "__main__":
    main()