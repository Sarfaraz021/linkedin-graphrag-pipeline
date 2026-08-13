"""Neo4j driver, constraints, and indexes."""

from __future__ import annotations

from typing import Any

import neo4j

from backend.pipeline.config import Settings

LEGACY_MIGRATIONS = [
    "MATCH (c:Company) SET c:Organisation REMOVE c:Company",
    """
    MATCH (a)-[r:AUTHORED]->(b)
    MERGE (a)-[w:WROTE]->(b)
    SET w += properties(r)
    DELETE r
    """,
]

CONSTRAINTS_AND_INDEXES = [
    "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT post_id IF NOT EXISTS FOR (p:Post) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT organisation_id IF NOT EXISTS FOR (o:Organisation) REQUIRE o.id IS UNIQUE",
    "CREATE INDEX person_url IF NOT EXISTS FOR (p:Person) ON (p.linkedinUrl)",
    "CREATE INDEX organisation_name IF NOT EXISTS FOR (o:Organisation) ON (o.name)",
    "CREATE INDEX post_category IF NOT EXISTS FOR (p:Post) ON (p.category)",
    "CREATE INDEX chunk_post_id IF NOT EXISTS FOR (c:Chunk) ON (c.postId)",
    (
        "CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS "
        "FOR (c:Chunk) ON (c.embedding) "
        "OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "CREATE VECTOR INDEX entity_embedding IF NOT EXISTS "
        "FOR (n:__Entity__) ON (n.entity_embedding) "
        "OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "CREATE FULLTEXT INDEX entity_name_fulltext IF NOT EXISTS "
        "FOR (n:Organisation|Brand|Retailer|Award|Event|Programme|Accelerator|Distributor) "
        "ON EACH [n.name]"
    ),
    "CREATE INDEX organisation_type IF NOT EXISTS FOR (o:Organisation) ON (o.orgType)",
]


class Neo4jClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.driver = neo4j.GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        self.database = settings.neo4j_database

    def close(self) -> None:
        self.driver.close()

    def __enter__(self) -> Neo4jClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        records, _, _ = self.driver.execute_query(
            query,
            parameters_=parameters or {},
            database_=self.database,
        )
        return [r.data() for r in records]

    def run_write(self, query: str, parameters: dict[str, Any] | None = None) -> None:
        self.run(query, parameters)

    def migrate_legacy_labels(self) -> None:
        """One-time idempotent migrations (Company→Organisation, AUTHORED→WROTE)."""
        for stmt in LEGACY_MIGRATIONS:
            try:
                self.run_write(stmt)
            except Exception:
                pass

    def ensure_schema(self) -> None:
        self.migrate_legacy_labels()
        for stmt in CONSTRAINTS_AND_INDEXES:
            try:
                self.run_write(stmt)
            except Exception as exc:
                # Vector index may fail if dimensions differ or edition lacks vector support.
                if "chunk_embedding" in stmt or "entity_embedding" in stmt:
                    continue
                raise exc

    def count_relationships(self, rel_type: str) -> int:
        rows = self.run(
            f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS c"
        )
        return int(rows[0]["c"]) if rows else 0

    def count_nodes(self, label: str) -> int:
        rows = self.run(f"MATCH (n:{label}) RETURN count(n) AS c")
        return int(rows[0]["c"]) if rows else 0

    def delete_person_data(self, person_id: str) -> None:
        """GDPR deletion path: remove a person and their deterministic edges."""
        self.run_write(
            """
            MATCH (p:Person {id: $person_id})
            OPTIONAL MATCH (p)-[r]-()
            DELETE r, p
            """,
            {"person_id": person_id},
        )
