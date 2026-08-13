"""LangGraph agent over the Neo4j knowledge graph.

Replaces the single-shot RagTemplate flow with a tool-calling agent that can:
- run semantic vector search over post chunks (for open-ended "what was said" questions)
- write and execute read-only Cypher against the graph (for analytical/aggregate
  questions such as "who appears most often" or multi-hop role/relationship lookups)
- hold short-term conversational memory per chat session via a LangGraph checkpointer
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings
from neo4j_graphrag.retrievers import VectorCypherRetriever

from backend.pipeline.config import Settings, get_settings
from backend.pipeline.neo4j_client import Neo4jClient

VECTOR_INDEX = "chunk_embedding"
ENTITY_VECTOR_INDEX = "entity_embedding"
ENTITY_FULLTEXT_INDEX = "entity_name_fulltext"

RETRIEVAL_QUERY = """
WITH node AS chunk, score
OPTIONAL MATCH (chunk)-[:FROM_DOCUMENT]->(doc:Document)
WITH chunk, score, doc,
     CASE
       WHEN doc.path STARTS WITH 'linkedin/post/' THEN replace(doc.path, 'linkedin/post/', '')
       WHEN doc.postId IS NOT NULL THEN doc.postId
       ELSE null
     END AS postId
OPTIONAL MATCH (post:Post {id: postId})
OPTIONAL MATCH (author:Person)-[:WROTE]->(post)
OPTIONAL MATCH (post)-[:MENTIONS]->(mentioned)
WITH chunk, score, doc, postId, author, post,
     collect(DISTINCT coalesce(mentioned.name, mentioned.id)) AS mentionedEntities
OPTIONAL MATCH (e1)-[rel]->(e2)
WHERE post IS NOT NULL AND rel.source_post_url = post.url
WITH chunk, score, doc, postId, author, post, mentionedEntities,
     collect(DISTINCT (coalesce(e1.name, '?') + ' -[' + type(rel) + ']-> ' + coalesce(e2.name, '?')))[0..5] AS graphFacts
RETURN chunk.text AS text,
       score,
       postId,
       author.name AS authorName,
       post.postedAt AS postedAt,
       left(post.content, 280) AS postPreview,
       doc.path AS source,
       mentionedEntities,
       graphFacts
"""

GRAPH_SCHEMA_DESCRIPTION = """
Node labels and key properties:
- Person {id, name, headline, location, country, currentCompany, linkedinUrl}
  Extra labels a Person may also carry: Founder, Investor, Buyer.
- Post {id, content, postedAt, reactionsTotal, commentsTotal, sharesTotal, category, url}
  category is one of: Award, Fundraising, Investment, RetailerBuyer, FounderStory,
  Event, Partnership, ProductLaunch, Uncategorised.
- Organisation {id, name, orgType, orgTypeConfidence} — separate node labels also exist for
  Brand, Retailer, Category, Trend, Location, Award, Event, Programme, Accelerator, Distributor
  (these are their own labels, not sub-labels of Organisation, except where the extractor
  emits an :Organisation node directly — that node's orgType tells you what it actually is:
  Brand, Retailer, Distributor, Investor, Funder, Accelerator, Incubator, Sponsor, Broadcaster,
  AwardBody, Agency, IndustryBody, TradeShowOrganiser, or Other).
- Chunk {text, postId, embedding} — raw text chunks of a Post, linked via FROM_DOCUMENT.
- __Entity__ — extra label on every LLM-extracted semantic node (Organisation/Brand/Award/
  etc), with an entity_embedding vector property for entity-level semantic search.

Relationship types:
- (Person)-[:WROTE]->(Post)
- (Person)-[:COMMENTED {commentary}]->(Post)
- (Person)-[:REACTED {type}]->(Post)
- (Post)-[:MENTIONS]->(Person|Organisation)
- Semantic/inferred edges (each carries confidence_score, source_post_url, evidence_text):
  (Person|Founder)-[:FOUNDED]->(Brand|Organisation)
  (Person|Founder)-[:WORKS_AT]->(Organisation)
  (Brand)-[:LISTED_IN]->(Retailer)
  (Organisation|Brand|Award)-[:SUPPORTED_BY]->(Organisation) — NON-financial support only
    (mentorship, visibility, endorsement). This is NOT money.
  (Brand|Organisation)-[:OPERATES_IN]->(Category)
  (Investor)-[:INVESTED_IN]->(Brand|Organisation) — STRICT equity investment only.
  (Organisation)-[:FUNDS]->(Brand|Organisation) — grant / non-equity funding only.
  (Person|Organisation)-[:BASED_IN]->(Location)
  (Person)-[:NOMINATED_FOR]->(Award|Programme)
  (Organisation)-[:SPONSORS]->(Award|Event|Programme) — award/event sponsorship (marketing
    spend), NOT funding of a business. e.g. ITV SPONSORS bCreator: ITV is a Broadcaster/
    Sponsor, never a Funder or Investor from this fact alone.
  (Organisation)-[:RUNS]->(Programme|Accelerator)
  (Brand)-[:PARTICIPATED_IN]->(Event|Programme)

IMPORTANT — money questions ("who funds/invests in X", "which orgs support brands
financially"): only INVESTED_IN and FUNDS represent money going to a business. SPONSORS and
SUPPORTED_BY are not funding. When asked about funding/investment, query specifically for
INVESTED_IN/FUNDS edges (optionally filter orgType IN ['Funder','Investor']) — do not include
SPONSORS/SUPPORTED_BY results and do not describe a sponsor as a funder.
"""

_WRITE_CLAUSE_RE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL\s*\{.*\}\s*IN\s*TRANSACTIONS|"
    r"LOAD\s+CSV|FOREACH)\b",
    re.IGNORECASE,
)


class CypherWriteRejected(ValueError):
    pass


def _ensure_read_only(cypher: str) -> None:
    if _WRITE_CLAUSE_RE.search(cypher):
        raise CypherWriteRejected(
            "Refused to run this query: it looks like it contains a write clause "
            "(CREATE/MERGE/DELETE/SET/REMOVE/DROP/...). Only read queries are allowed."
        )


@dataclass
class AgentTurnResult:
    answer: str
    sources: list[dict[str, Any]]
    tool_calls: list[str] = field(default_factory=list)


class GraphAgent:
    """LangGraph ReAct-style agent with short-term (per-session) memory."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client: Neo4jClient | None = None
        self._embedder: OpenAIEmbeddings | None = None
        self._retriever: VectorCypherRetriever | None = None
        self._llm: BaseChatModel | None = None
        self._checkpointer = InMemorySaver()
        self._agent = None
        self._last_sources: list[dict[str, Any]] = []

    def _client_or_create(self) -> Neo4jClient:
        if self._client is None:
            self._client = Neo4jClient(self.settings)
        return self._client

    def _embedder_or_create(self) -> OpenAIEmbeddings:
        if self._embedder is None:
            self._embedder = OpenAIEmbeddings(
                model=self.settings.embed_model,
                api_key=self.settings.openai_api_key,
            )
        return self._embedder

    def _retriever_or_create(self) -> VectorCypherRetriever:
        if self._retriever is None:
            client = self._client_or_create()
            self._retriever = VectorCypherRetriever(
                driver=client.driver,
                index_name=VECTOR_INDEX,
                retrieval_query=RETRIEVAL_QUERY,
                embedder=self._embedder_or_create(),
                neo4j_database=self.settings.neo4j_database,
            )
        return self._retriever

    def _build_llm(self, *, force_anthropic: bool = False) -> BaseChatModel:
        provider = self.settings.llm_provider.lower()
        use_anthropic = force_anthropic or provider == "anthropic" or (
            provider == "auto" and not self.settings.openai_api_key
        )
        if use_anthropic:
            from langchain_anthropic import ChatAnthropic

            if not self.settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY is required when using Anthropic")
            return ChatAnthropic(
                model=self.settings.anthropic_model,
                api_key=self.settings.anthropic_api_key,
                temperature=0.2,
            )
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=self.settings.llm_model,
            api_key=self.settings.openai_api_key,
            temperature=0.2,
        )

    def _make_tools(self) -> list[Any]:
        agent_self = self

        @tool
        def search_posts(query: str, top_k: int = 8) -> str:
            """Semantically search LinkedIn post content for open-ended questions
            about what was said, announced, or discussed (topics, opinions,
            stories, specific posts). Not for counting or ranking across the graph."""
            retriever = agent_self._retriever_or_create()
            result = retriever.search(query_text=query, top_k=top_k)
            if not result.items:
                return "No matching post chunks found."
            lines = []
            for item in result.items:
                meta = item.metadata or {}
                agent_self._last_sources.append(
                    {
                        "text": (item.content or "")[:240],
                        "score": meta.get("score"),
                        "postId": meta.get("postId"),
                        "authorName": meta.get("authorName"),
                        "source": meta.get("source"),
                    }
                )
                line = f"[Post {meta.get('postId')} by {meta.get('authorName')}] {item.content}"
                mentioned = [m for m in (meta.get("mentionedEntities") or []) if m]
                facts = [f for f in (meta.get("graphFacts") or []) if f]
                if mentioned:
                    line += f"\nMentioned entities: {', '.join(mentioned)}"
                if facts:
                    line += f"\nGraph facts extracted from this post: {'; '.join(facts)}"
                lines.append(line)
            return "\n\n".join(lines)

        @tool
        def search_entities(query: str, top_k: int = 8) -> str:
            """Resolve a SPECIFIC PROPER-NOUN entity name (e.g. "ITV", "Ayaa
            Botanicals") to its exact stored name/labels/orgType before filtering
            query_graph Cypher on it — do not guess exact casing or spelling.
            Do NOT call this with a generic category/relationship phrase like
            "challenger brands", "funding bodies", or "awards" — those are not
            entity names and will correctly return nothing; write query_graph
            Cypher directly over the relationship/label pattern instead."""
            client = agent_self._client_or_create()
            try:
                fulltext_rows = client.run(
                    """
                    CALL db.index.fulltext.queryNodes($index, $query) YIELD node, score
                    RETURN node.name AS name, labels(node) AS labels, node.orgType AS orgType,
                           score
                    ORDER BY score DESC LIMIT $top_k
                    """,
                    {"index": ENTITY_FULLTEXT_INDEX, "query": query, "top_k": top_k},
                )
            except Exception:
                fulltext_rows = []
            embedder = agent_self._embedder_or_create()
            vector = embedder.embed_query(query)
            try:
                vector_rows = client.run(
                    """
                    CALL db.index.vector.queryNodes($index, $top_k, $vector)
                    YIELD node, score
                    WHERE node.name IS NOT NULL
                    RETURN node.name AS name, labels(node) AS labels, node.orgType AS orgType,
                           score
                    """,
                    {"index": ENTITY_VECTOR_INDEX, "top_k": top_k, "vector": vector},
                )
            except Exception:
                vector_rows = []
            seen: dict[str, dict[str, Any]] = {}
            for row in fulltext_rows + vector_rows:
                key = row["name"]
                if key not in seen or row["score"] > seen[key]["score"]:
                    seen[key] = row
            if not seen:
                return "No matching entities found by name or meaning."
            lines = [
                f"{r['name']} — labels={[l for l in r['labels'] if l not in ('__Entity__', 'Resolved')]}"
                f"{' orgType=' + r['orgType'] if r.get('orgType') else ''} (match score {r['score']:.2f})"
                for r in sorted(seen.values(), key=lambda r: r["score"], reverse=True)
            ]
            agent_self._last_sources.append({"text": query, "source": "search_entities"})
            return "\n".join(lines)

        @tool
        def query_graph(cypher: str) -> str:
            """Run a READ-ONLY Cypher query against the Neo4j knowledge graph.
            Use this for analytical, counting, ranking, or multi-hop questions,
            e.g. "which people appear most frequently", "founders who are also
            partners of a retailer", "how many posts mention X". Write your own
            Cypher using the graph schema you were given in the system prompt.
            The query must start with MATCH/OPTIONAL MATCH/WITH/UNWIND/CALL
            (read procedures only) and must not contain write clauses. Always
            include a LIMIT (<=25) on queries that can return many rows."""
            try:
                _ensure_read_only(cypher)
            except CypherWriteRejected as exc:
                return str(exc)
            client = agent_self._client_or_create()
            try:
                rows = client.run(cypher)
            except Exception as exc:  # noqa: BLE001
                return f"Cypher execution error: {exc}"
            if not rows:
                return "Query ran successfully but returned no rows."
            agent_self._last_sources.append(
                {"text": cypher, "source": "graph_query"}
            )
            preview = rows[:25]
            return "\n".join(str(row) for row in preview)

        @tool
        def graph_overview() -> str:
            """Get quick node/relationship counts for the whole graph (people,
            posts, organisations, comments, reactions, mentions). Useful to
            sanity-check what data exists before writing a Cypher query."""
            client = agent_self._client_or_create()
            stats = {
                "people": client.count_nodes("Person"),
                "posts": client.count_nodes("Post"),
                "organisations": client.count_nodes("Organisation"),
                "comments": client.count_relationships("COMMENTED"),
                "reactions": client.count_relationships("REACTED"),
                "mentions": client.count_relationships("MENTIONS"),
            }
            return ", ".join(f"{k}={v}" for k, v in stats.items())

        return [search_posts, search_entities, query_graph, graph_overview]

    def _agent_or_create(self, *, force_anthropic: bool = False):
        if self._agent is None or force_anthropic:
            self._llm = self._build_llm(force_anthropic=force_anthropic)
            system_prompt = (
                "You are a friendly, knowledgeable LinkedIn engagement analyst having a "
                "conversation. Reply the way a helpful colleague would in chat — natural, "
                "warm, and to the point.\n\n"
                "Tools:\n"
                "- search_posts: semantic search over post text, for 'what was said' questions. "
                "Results include any graph facts (extracted relationships) tied to that post.\n"
                "- search_entities: fuzzy name + semantic lookup over organisation/brand/award/"
                "event/programme/etc nodes. Use this ONLY to resolve a specific proper-noun "
                "name the user gave you (e.g. 'ITV', 'Ayaa Botanicals') to its exact stored "
                "name/labels/orgType before filtering query_graph Cypher on that name. Do NOT "
                "call it with a category, relationship, or generic domain phrase like "
                "'challenger brands', 'funding bodies', or 'awards' — those are not entity "
                "names in the graph and will correctly return nothing. Every :Brand node in "
                "this dataset already IS a challenger brand (that's the whole dataset's "
                "domain) — there is no separate 'challenger brand' entity/label to search "
                "for. For 'which orgs fund/support/sponsor challenger brands' style "
                "questions, skip straight to query_graph and match the relationship pattern "
                "across all Brand/Organisation nodes (e.g. MATCH (o)-[r:FUNDS|INVESTED_IN]->"
                "(b:Brand) RETURN o.name, o.orgType, b.name, r.evidence_text) — do not search "
                "for the phrase 'challenger brand' first.\n"
                "- query_graph: write your own read-only Cypher for analytical/aggregate/"
                "ranking/multi-hop questions (counts, 'most frequent', role combinations "
                "across relationships, etc).\n"
                "- graph_overview: quick counts to sanity-check the graph before querying.\n\n"
                f"Graph schema:\n{GRAPH_SCHEMA_DESCRIPTION}\n\n"
                "Guidelines:\n"
                "- If the message is small talk (thanks, okay, hi), just reply naturally in "
                "a sentence or two — no tool calls, no headings, no source lists.\n"
                "- For factual questions, decide which tool(s) actually answer it. Prefer "
                "query_graph whenever the question is about counts, rankings, 'most/least', "
                "or combinations of roles/relationships — vector search over text cannot "
                "answer those reliably.\n"
                "- Scope: phrases like 'my posts', 'my saved posts', 'my database', 'the "
                "graph', 'across everything' all just mean every Post node currently in the "
                "graph — there is no separate 'saved'/owner/user-scoping property on any "
                "node, so never filter on one. Never ask the user for post IDs, node IDs, or "
                "any internal identifier before querying. Just write the Cypher over the "
                "full graph (with a LIMIT). Only ask a clarifying question when the user's "
                "own wording is ambiguous about which specific person/company/topic they "
                "mean — never ask permission to run a broader query, just run it.\n"
                "- Self-correct before answering: if a query_graph call returns zero rows, "
                "don't immediately conclude there's no data and don't ask the user whether "
                "you should try again. First check whether your own query was too narrow "
                "(an assumed property/label/filter that may not exist) and retry once with a "
                "broader version yourself. Only after that tell the user what you found or "
                "confirm it's genuinely absent.\n"
                "- The graph grows as new LinkedIn posts are ingested — always call "
                "graph_overview first to see the current post/people/org counts before "
                "answering scope questions. Some schema labels/relationships (e.g. "
                "Retailer, Investor, Accelerator, LISTED_IN, INVESTED_IN) may have few "
                "or zero nodes/edges even though they're valid parts of the schema. "
                "edges even though they're valid parts of the schema. A query returning zero "
                "rows can mean either 'not in this dataset' or 'wrong query' — don't just "
                "say 'no data found' and stop. If a query_graph result is empty or thin, "
                "either broaden the query (e.g. check overview/related labels or drop an "
                "overly-specific filter) or clearly tell the user what's genuinely absent "
                "from this dataset versus what related data does exist, so they can tell the "
                "two apart. Use graph_overview or a quick count query to ground that answer.\n"
                "- Answer directly in plain prose first. Only use bullet points or bold text "
                "when listing several distinct people, posts, or facts makes it genuinely "
                "easier to scan.\n"
                "- Never fabricate a 'Summary'/'Details'/'Sources' structure. Sources are "
                "shown separately in the UI — don't restate post IDs or citations.\n"
                "- Base factual claims only on tool results. If tools return nothing useful "
                "after a reasonable attempt to broaden the query, say plainly what's missing "
                "instead of guessing.\n"
                "- Relationship types are precise, not interchangeable: SPONSORS is award/"
                "event/programme sponsorship (non-financial-to-business), INVESTED_IN is "
                "equity investment, FUNDS is grant/non-equity funding, SUPPORTED_BY is "
                "non-financial support (mentorship/visibility/endorsement). Never describe a "
                "SPONSORS or SUPPORTED_BY relationship as 'funding' or 'investing' — check the "
                "actual edge type and orgType before answering questions about money/funding.\n"
                "- Keep responses as short as the question deserves.\n"
                "- You have memory of this conversation; use prior turns for context "
                "(e.g. follow-up questions) without re-asking the user to repeat themselves."
            )
            self._agent = create_react_agent(
                self._llm,
                tools=self._make_tools(),
                prompt=SystemMessage(content=system_prompt),
                checkpointer=self._checkpointer,
            )
        return self._agent

    @staticmethod
    def _is_llm_connection_error(exc: Exception) -> bool:
        name = type(exc).__name__.lower()
        text = str(exc).lower()
        return (
            "connection error" in text
            or "apiconnectionerror" in name
            or "connecterror" in name
            or "connection refused" in text
        )

    def ask(self, question: str, session_id: str, top_k: int = 8) -> AgentTurnResult:
        self._last_sources = []
        agent = self._agent_or_create()
        config = {"configurable": {"thread_id": session_id}}
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": question}]},
                config=config,
            )
        except Exception as exc:
            if not self._is_llm_connection_error(exc) or not self.settings.anthropic_api_key:
                raise
            self._agent = None
            agent = self._agent_or_create(force_anthropic=True)
            result = agent.invoke(
                {"messages": [{"role": "user", "content": question}]},
                config=config,
            )
        messages = result["messages"]
        final: AIMessage | None = None
        tool_calls: list[str] = []
        for msg in messages:
            if isinstance(msg, AIMessage):
                final = msg
            if isinstance(msg, ToolMessage):
                tool_calls.append(msg.name or "tool")
        answer = final.content if final else "No answer generated."
        if isinstance(answer, list):
            answer = "\n".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in answer
            )
        return AgentTurnResult(
            answer=answer or "No answer generated.",
            sources=self._last_sources,
            tool_calls=tool_calls,
        )

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
