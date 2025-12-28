# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Knowledge base integrator for ingested axioms.

This module provides the integration layer between the ingestion pipeline
(extraction + review) and the knowledge base (Neo4j + LanceDB).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import toml

from axiom.graph.loader import Neo4jLoader
from axiom.models import Axiom, AxiomCollection, AxiomType, SourceLocation
from axiom.vectors.loader import LanceDBLoader

from .reviewer import ReviewSession, ReviewSessionManager


@dataclass
class IntegrationResult:
    """Result of integrating axioms into the KB."""

    axioms_loaded: int
    neo4j_nodes_created: int
    lancedb_records_created: int
    dependencies_created: int
    errors: List[str]


class KBIntegrator:
    """Integrates reviewed axioms into Neo4j and LanceDB.

    This class provides the final step in the ingestion pipeline:
    1. Takes approved axioms from review sessions
    2. Loads them into Neo4j with DEPENDS_ON relationships
    3. Loads them into LanceDB for semantic search
    """

    def __init__(
        self,
        neo4j_loader: Optional[Neo4jLoader] = None,
        lancedb_loader: Optional[LanceDBLoader] = None,
        review_manager: Optional[ReviewSessionManager] = None,
    ):
        """Initialize the KB integrator.

        Args:
            neo4j_loader: Neo4j loader instance. If None, Neo4j loading is skipped.
            lancedb_loader: LanceDB loader instance. If None, vector loading is skipped.
            review_manager: Review session manager for accessing approved axioms.
        """
        self.neo4j_loader = neo4j_loader
        self.lancedb_loader = lancedb_loader
        self.review_manager = review_manager or ReviewSessionManager()

    def integrate_from_session(
        self,
        session_id: str,
        table_name: str = "axioms",
    ) -> IntegrationResult:
        """Integrate approved axioms from a review session.

        Args:
            session_id: ID of the review session.
            table_name: LanceDB table name.

        Returns:
            IntegrationResult with counts and errors.
        """
        session = self.review_manager.load_session(session_id)
        if session is None:
            return IntegrationResult(
                axioms_loaded=0,
                neo4j_nodes_created=0,
                lancedb_records_created=0,
                dependencies_created=0,
                errors=[f"Session '{session_id}' not found"],
            )

        axioms = session.get_approved_axioms()
        return self.integrate_axioms(axioms, table_name=table_name)

    def integrate_from_toml(
        self,
        toml_path: str,
        table_name: str = "axioms",
    ) -> IntegrationResult:
        """Integrate axioms from a TOML file.

        Args:
            toml_path: Path to TOML file with axioms.
            table_name: LanceDB table name.

        Returns:
            IntegrationResult with counts and errors.
        """
        path = Path(toml_path)
        if not path.exists():
            return IntegrationResult(
                axioms_loaded=0,
                neo4j_nodes_created=0,
                lancedb_records_created=0,
                dependencies_created=0,
                errors=[f"File not found: {toml_path}"],
            )

        try:
            collection = AxiomCollection.load_toml(path)
            return self.integrate_axioms(collection.axioms, table_name=table_name)
        except Exception as e:
            return IntegrationResult(
                axioms_loaded=0,
                neo4j_nodes_created=0,
                lancedb_records_created=0,
                dependencies_created=0,
                errors=[f"Failed to parse TOML: {e}"],
            )

    def integrate_axioms(
        self,
        axioms: List[Axiom],
        table_name: str = "axioms",
    ) -> IntegrationResult:
        """Integrate a list of axioms into the KB.

        Args:
            axioms: List of axioms to integrate.
            table_name: LanceDB table name.

        Returns:
            IntegrationResult with counts and errors.
        """
        errors = []
        neo4j_count = 0
        lancedb_count = 0
        deps_count = 0

        # Load into Neo4j
        if self.neo4j_loader is not None:
            for axiom in axioms:
                try:
                    self.neo4j_loader.load_axiom(axiom)
                    neo4j_count += 1
                    deps_count += len(axiom.depends_on)
                except Exception as e:
                    errors.append(f"Neo4j error for {axiom.id}: {e}")

        # Load into LanceDB
        if self.lancedb_loader is not None:
            for axiom in axioms:
                try:
                    self.lancedb_loader.load_axiom(axiom, table_name=table_name)
                    lancedb_count += 1
                except Exception as e:
                    errors.append(f"LanceDB error for {axiom.id}: {e}")

        return IntegrationResult(
            axioms_loaded=len(axioms),
            neo4j_nodes_created=neo4j_count,
            lancedb_records_created=lancedb_count,
            dependencies_created=deps_count,
            errors=errors,
        )

    def validate_dependencies(self, axioms: List[Axiom]) -> List[str]:
        """Check if all depends_on references exist in the KB.

        Args:
            axioms: List of axioms to validate.

        Returns:
            List of missing dependency IDs.
        """
        if self.neo4j_loader is None:
            return []

        missing = []
        for axiom in axioms:
            for dep_id in axiom.depends_on:
                if self.neo4j_loader.get_axiom(dep_id) is None:
                    missing.append(dep_id)

        return list(set(missing))  # Remove duplicates

    def get_integration_stats(self) -> dict:
        """Get statistics about the integrated KB.

        Returns:
            Dict with KB statistics.
        """
        stats = {
            "neo4j": None,
            "lancedb": None,
        }

        if self.neo4j_loader is not None:
            try:
                stats["neo4j"] = self.neo4j_loader.count_nodes()
            except Exception:
                stats["neo4j"] = {"error": "Could not connect to Neo4j"}

        if self.lancedb_loader is not None:
            try:
                stats["lancedb"] = {
                    "axioms": self.lancedb_loader.count("axioms"),
                }
            except Exception:
                stats["lancedb"] = {"error": "Could not access LanceDB"}

        return stats


def load_approved_axioms_to_kb(
    toml_path: str,
    neo4j_uri: str = "bolt://localhost:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "axiompass",
    lancedb_path: str = "./data/lancedb",
    table_name: str = "axioms",
) -> IntegrationResult:
    """Convenience function to load approved axioms into the KB.

    Args:
        toml_path: Path to TOML file with approved axioms.
        neo4j_uri: Neo4j connection URI.
        neo4j_user: Neo4j username.
        neo4j_password: Neo4j password.
        lancedb_path: Path to LanceDB directory.
        table_name: LanceDB table name.

    Returns:
        IntegrationResult with counts and errors.
    """
    neo4j_loader = None
    lancedb_loader = None
    errors = []

    # Try to connect to Neo4j
    try:
        neo4j_loader = Neo4jLoader(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
        )
    except Exception as e:
        errors.append(f"Could not connect to Neo4j: {e}")

    # Initialize LanceDB
    try:
        lancedb_loader = LanceDBLoader(db_path=lancedb_path)
    except Exception as e:
        errors.append(f"Could not initialize LanceDB: {e}")

    if neo4j_loader is None and lancedb_loader is None:
        return IntegrationResult(
            axioms_loaded=0,
            neo4j_nodes_created=0,
            lancedb_records_created=0,
            dependencies_created=0,
            errors=errors,
        )

    try:
        integrator = KBIntegrator(
            neo4j_loader=neo4j_loader,
            lancedb_loader=lancedb_loader,
        )
        result = integrator.integrate_from_toml(toml_path, table_name=table_name)
        result.errors.extend(errors)
        return result
    finally:
        if neo4j_loader is not None:
            neo4j_loader.close()
