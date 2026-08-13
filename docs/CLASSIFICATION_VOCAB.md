# Classification Vocabulary

Controlled vocabularies used by the pipeline. This is also the list to send the client for
sign-off. See `backend/pipeline/schema.py` (relationships, `ORG_TYPES`), `backend/pipeline/classify.py`
(post categories), and `backend/pipeline/org_classify.py` (orgType classifier) for the source of truth.

## Post categories (`Post.category`)

One primary category per post, assigned by `backend/pipeline/classify.py`. Defaults to
`Uncategorised` when the content doesn't clearly support a substantive label.

| Category | Definition |
|---|---|
| Award | Post announces or discusses an award nomination, win, or award programme. |
| Fundraising | Post about raising capital, funding rounds, or seeking investment. |
| Investment | Post about an investment made, investor backing, or VC activity. |
| RetailerBuyer | Post involving retail buyers, listings, or retail partnerships. |
| FounderStory | Post centred on a founder's journey, brand story, or product launch narrative. |
| Event | Post about a trade show, conference, or industry event to attend. |
| Partnership | Post announcing a collaboration or partnership between organisations/brands. |
| ProductLaunch | Post launching or promoting a specific consumer product. |
| Uncategorised | Content does not clearly fit any category above. |

Worked example: the bCreator post by Monique Anderson → `category = "Award"`
(evidence: "4 x nominations for our agency at this years bCreator").

## Organisation types (`Organisation.orgType`)

One `orgType` per `:Organisation` node, assigned by `backend/pipeline/org_classify.py`
(deterministic known-name/keyword rules first, LLM fallback from name + relationship
evidence otherwise). This is the ITV fix: sponsoring an award is not funding a business, so
`orgType` and relationship type both have to say so.

| orgType | Definition |
|---|---|
| Brand | Makes/sells a consumer product itself (rare on a generic Organisation node — usually a dedicated `:Brand` node instead). |
| Retailer | Sells other brands' products (shops, supermarkets, e-commerce). |
| Distributor | Moves/wholesales products between brands and retailers. |
| Investor | Puts equity capital into businesses. |
| Funder | Gives grants or non-equity funding directly to businesses. |
| Accelerator | Structured, time-boxed support programme for founders/brands. |
| Incubator | Early-stage structured support programme for founders/brands. |
| Sponsor | Pays to be associated with an award/event/programme (marketing spend). |
| Broadcaster | TV/radio/media channel. |
| AwardBody | Runs/organises an award programme. |
| Agency | Marketing, PR, talent, or creative services agency. |
| IndustryBody | Trade association, federation, or industry institute. |
| TradeShowOrganiser | Runs trade shows / exhibitions / expos. |
| Other | None of the above fit. |

Worked example: **ITV** → `orgType = "Broadcaster"` (curated known-name mapping — never
`Funder` or `Investor`, regardless of which edge type an LLM pass infers).

## Relationship types (semantic/inferred edges)

Every inferred edge carries `confidence_score` (0–1), `source_post_url`, and `evidence_text`
(short supporting quote) so the client can trace/trust each link.

| Relationship | Pattern | Definition |
|---|---|---|
| FOUNDED | (Person\|Founder)→(Brand\|Organisation) | Person founded or owns a brand/organisation. |
| WORKS_AT | (Person\|Founder)→(Organisation) | Person is employed by an organisation. |
| LISTED_IN | (Brand)→(Retailer) | Brand is listed in / sold at a retailer. |
| SUPPORTED_BY | (Organisation\|Brand\|Award)→(Organisation) | **Non-financial** support only: mentorship, visibility, endorsement, platform. Never money. |
| OPERATES_IN | (Brand\|Organisation)→(Category) | Brand/organisation operates in a product category or market. |
| INVESTED_IN | (Investor)→(Brand\|Organisation) | **Strict equity investment** — capital for an ownership stake. |
| FUNDS | (Organisation)→(Brand\|Organisation) | Grant / **non-equity** funding given directly to a business. No award/event attached, no equity taken. |
| BASED_IN | (Person\|Organisation)→(Location) | Person/organisation is based in a location. |
| NOMINATED_FOR | (Person)→(Award\|Programme) | Person nominated for an award or programme. |
| SPONSORS | (Organisation)→(Award\|Event\|Programme) | **Strict award/event/programme sponsorship** — pays to be associated with it. Marketing spend, not funding of a business. |
| RUNS | (Organisation)→(Programme\|Accelerator) | Organisation runs/operates a programme or accelerator. |
| PARTICIPATED_IN | (Brand)→(Event\|Programme) | Brand or person took part in an event or programme. |

### The money-relationship rule (ITV bug fix)

Before this pass, `SUPPORTED_BY` conflated sponsorship and funding: `bCreator SUPPORTED_BY
ITV` read as if ITV funded the challenger-brand ecosystem, when ITV is actually a broadcaster
paying to headline-sponsor an unrelated creator/talent award. Now:

- **SPONSORS** — award/event/programme sponsorship. Non-financial-to-business. *(ITV → bCreator)*
- **INVESTED_IN** — equity investment into a brand/org.
- **FUNDS** — grants / non-equity funding a body gives a business/brand.
- **SUPPORTED_BY** — narrowed to non-financial support only (mentorship, visibility, endorsement).

A query for "who funds/invests in challenger brands" should only ever traverse
`INVESTED_IN`/`FUNDS` — never `SPONSORS`/`SUPPORTED_BY` — and `ITV.orgType` should read
`Broadcaster`, never `Funder`/`Investor`.
