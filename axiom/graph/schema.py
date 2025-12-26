"""Neo4j schema definitions and constraints."""

from typing import List

from neo4j import Driver

# Schema constraints for the Axiom knowledge graph
SCHEMA_CONSTRAINTS: List[str] = [
    # Unique constraints
    "CREATE CONSTRAINT axiom_id IF NOT EXISTS FOR (a:Axiom) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT error_code IF NOT EXISTS FOR (e:ErrorCode) REQUIRE e.code IS UNIQUE",
    "CREATE CONSTRAINT module_name IF NOT EXISTS FOR (m:KModule) REQUIRE m.name IS UNIQUE",
    # Indexes for common queries
    "CREATE INDEX axiom_layer IF NOT EXISTS FOR (a:Axiom) ON (a.layer)",
    "CREATE INDEX axiom_confidence IF NOT EXISTS FOR (a:Axiom) ON (a.confidence)",
    "CREATE INDEX error_type IF NOT EXISTS FOR (e:ErrorCode) ON (e.type)",
]

# Clear all data
CLEAR_GRAPH = "MATCH (n) DETACH DELETE n"


def apply_schema(driver: Driver) -> None:
    """Apply schema constraints to the database.

    Args:
        driver: Neo4j driver instance.
    """
    with driver.session() as session:
        for constraint in SCHEMA_CONSTRAINTS:
            try:
                session.run(constraint)
            except Exception as e:
                # Constraint might already exist
                if "already exists" not in str(e).lower():
                    raise


def clear_graph(driver: Driver) -> None:
    """Clear all data from the graph.

    Args:
        driver: Neo4j driver instance.
    """
    with driver.session() as session:
        session.run(CLEAR_GRAPH)
