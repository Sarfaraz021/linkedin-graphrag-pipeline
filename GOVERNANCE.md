# Data governance

This pipeline ingests LinkedIn engagement data: names, headlines, locations, employers, follower counts, and comments from people who interacted with scraped posts. Many subjects are in the UK/EU, so treat this as **personal data under GDPR**.

## Lawful basis and purpose

- Document the lawful basis (e.g. legitimate interest, consent, or contract) and the **specific purpose** before running production loads (e.g. industry research, creator marketing analysis).
- Limit processing to that purpose; do not reuse the graph for unrelated profiling.

## Data minimization

- Stage 1 scraper controls what is collected (comments, reactions, enrichment).
- Stage 2 defaults `INCLUDE_REACTOR_PROFILES=false` because reactors rarely add free text beyond a headline.
- Do not enable profile enrichment in Stage 1 unless required for the stated purpose.

## Security

- Run Neo4j on a **private**, authenticated instance. Do not expose Bolt or Browser publicly.
- Store credentials in `.env` only; never commit `.env`, raw dumps, or `data/` to git.
- Restrict database access to operators who need it.

## Retention and deletion

- Define a retention window (e.g. 90 days) and review periodically.
- **Deletion path:** remove a person with `Neo4jClient.delete_person_data(person_id)` or Cypher:

  ```cypher
  MATCH (p:Person {id: $personId})
  OPTIONAL MATCH (p)-[r]-()
  DELETE r, p
  ```

- Also delete corresponding rows from local `data/raw/` and `data/processed/` if storing copies off-database.

## Re-runs and idempotency

- Backbone loads are idempotent (`MERGE` on stable ids).
- Semantic resolution marks merged entities with `:Resolved` so re-runs do not re-merge the same nodes.

## Team checklist

- [ ] Lawful basis documented
- [ ] Neo4j access restricted
- [ ] Retention policy set
- [ ] `.env` and `data/` excluded from version control
- [ ] Deletion procedure tested on a non-production copy
