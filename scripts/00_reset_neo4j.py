#!/usr/bin/env python3
"""Wipe the Neo4j database and re-apply constraints/indexes for a clean rebuild.

Deletes all nodes/relationships, drops the vector indexes so they get
recreated at the correct dimensions, then re-applies constraints/indexes
from backend.pipeline.neo4j_client. Prints final counts (should be 0/0).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline.config import get_settings
from backend.pipeline.neo4j_client import Neo4jClient

DROP_INDEXES = [
    "DROP INDEX chunk_embedding IF EXISTS",
    "DROP INDEX entity_embedding IF EXISTS",
    "DROP INDEX entity_name_fulltext IF EXISTS",
]


def delete_all_data(client: Neo4jClient) -> None:
    # execute_query runs in an explicit transaction, which Neo4j forbids for
    # "CALL {} IN TRANSACTIONS"; batch manually instead (dataset is small).
    while True:
        result = client.run(
            "MATCH (n) WITH n LIMIT 5000 DETACH DELETE n RETURN count(n) AS c"
        )
        if not result or result[0]["c"] == 0:
            break


def main() -> None:
    settings = get_settings()
    with Neo4jClient(settings) as client:
        print(f"Connecting to {settings.neo4j_uri} / db={settings.neo4j_database}")

        delete_all_data(client)

        for stmt in DROP_INDEXES:
            try:
                client.run_write(stmt)
            except Exception as exc:  # noqa: BLE001
                print(f"  (skip) {stmt}: {exc}")

        client.ensure_schema()

        node_count = client.run("MATCH (n) RETURN count(n) AS c")[0]["c"]
        rel_count = client.run("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
        print(f"Nodes: {node_count}, Relationships: {rel_count}")

        constraints = client.run("SHOW CONSTRAINTS YIELD name RETURN name ORDER BY name")
        indexes = client.run("SHOW INDEXES YIELD name RETURN name ORDER BY name")
        print("Constraints:", [c["name"] for c in constraints])
        print("Indexes:", [i["name"] for i in indexes])


if __name__ == "__main__":
    main()
