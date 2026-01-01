# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Load axioms into Neo4j graph database."""


from neo4j import Driver, GraphDatabase

from axiom.models import Axiom, AxiomCollection, ErrorCode
from axiom.models.pairing import Idiom, Pairing


class Neo4jLoader:
    """Load axiom data into Neo4j."""

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "axiompass",
    ) -> None:
        """Initialize Neo4j connection.

        Args:
            uri: Neo4j bolt URI.
            user: Database username.
            password: Database password.
        """
        self.driver: Driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        """Close the database connection."""
        self.driver.close()

    def __enter__(self) -> "Neo4jLoader":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    def load_collection(self, collection: AxiomCollection) -> None:
        """Load a complete axiom collection.

        Args:
            collection: AxiomCollection to load.
        """
        with self.driver.session() as session:
            # Create axioms
            for axiom in collection.axioms:
                session.execute_write(self._create_axiom, axiom)

            # Create error codes
            for error in collection.error_codes:
                session.execute_write(self._create_error_code, error)

            # Create relationships
            session.execute_write(self._create_relationships, collection)

    def load_axiom(self, axiom: Axiom) -> None:
        """Load a single axiom.

        Args:
            axiom: Axiom to load.
        """
        with self.driver.session() as session:
            session.execute_write(self._create_axiom, axiom)

    def load_error_code(self, error: ErrorCode) -> None:
        """Load a single error code.

        Args:
            error: ErrorCode to load.
        """
        with self.driver.session() as session:
            session.execute_write(self._create_error_code, error)

    @staticmethod
    def _create_axiom(tx, axiom: Axiom) -> None:
        """Create an Axiom node and its module relationship."""
        query = """
        MERGE (a:Axiom {id: $id})
        SET a.content = $content,
            a.formal_spec = $formal_spec,
            a.layer = $layer,
            a.confidence = $confidence,
            a.source_file = $source_file,
            a.module_name = $module_name,
            a.tags = $tags,
            a.c_standard_refs = $c_refs,
            a.function = $function,
            a.header = $header,
            a.axiom_type = $axiom_type,
            a.on_violation = $on_violation,
            a.depends_on = $depends_on

        MERGE (m:KModule {name: $module_name})
        SET m.file_path = $source_file

        MERGE (a)-[:DEFINED_IN]->(m)
        """

        violated_by_codes = [v.code for v in axiom.violated_by]

        tx.run(
            query,
            id=axiom.id,
            content=axiom.content,
            formal_spec=axiom.formal_spec,
            layer=axiom.layer,
            confidence=axiom.confidence,
            source_file=axiom.source.file,
            module_name=axiom.source.module,
            tags=axiom.tags,
            c_refs=axiom.c_standard_refs,
            function=axiom.function,
            header=axiom.header,
            axiom_type=axiom.axiom_type.value if axiom.axiom_type else None,
            on_violation=axiom.on_violation,
            depends_on=axiom.depends_on,
        )

        # Store violated_by codes for later relationship creation
        if violated_by_codes:
            tx.run(
                """
                MATCH (a:Axiom {id: $id})
                SET a.violated_by_codes = $codes
                """,
                id=axiom.id,
                codes=violated_by_codes,
            )

        # Create DEPENDS_ON relationships to foundation axioms
        if axiom.depends_on:
            tx.run(
                """
                MATCH (a:Axiom {id: $id})
                UNWIND $depends_on AS dep_id
                MATCH (foundation:Axiom {id: dep_id})
                MERGE (a)-[:DEPENDS_ON]->(foundation)
                """,
                id=axiom.id,
                depends_on=axiom.depends_on,
            )

    @staticmethod
    def _create_error_code(tx, error: ErrorCode) -> None:
        """Create an ErrorCode node."""
        query = """
        MERGE (e:ErrorCode {code: $code})
        SET e.internal_code = $internal_code,
            e.type = $type,
            e.description = $description,
            e.c_standard_refs = $c_refs,
            e.validates_axioms = $validates_axioms
        """
        tx.run(
            query,
            code=error.code,
            internal_code=error.internal_code,
            type=error.type.value,
            description=error.description,
            c_refs=error.c_standard_refs,
            validates_axioms=error.validates_axioms,
        )

    @staticmethod
    def _create_relationships(tx, collection: AxiomCollection) -> None:
        """Create VIOLATED_BY relationships between axioms and error codes."""
        # Create relationships from axioms to error codes
        query = """
        MATCH (a:Axiom)
        WHERE a.violated_by_codes IS NOT NULL
        UNWIND a.violated_by_codes AS code
        MATCH (e:ErrorCode {code: code})
        MERGE (a)-[:VIOLATED_BY]->(e)
        """
        tx.run(query)

    def get_axiom(self, axiom_id: str) -> dict | None:
        """Get an axiom by ID.

        Args:
            axiom_id: Axiom ID.

        Returns:
            Axiom data as dict or None.
        """
        with self.driver.session() as session:
            result = session.run(
                "MATCH (a:Axiom {id: $id}) RETURN a",
                id=axiom_id,
            )
            record = result.single()
            if record:
                return dict(record["a"])
            return None

    def get_axioms_by_module(self, module: str) -> list:
        """Get all axioms in a module.

        Args:
            module: Module name.

        Returns:
            List of axiom dicts.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (a:Axiom)-[:DEFINED_IN]->(m:KModule {name: $module})
                RETURN a
                """,
                module=module,
            )
            return [dict(record["a"]) for record in result]

    def get_violations_for_axiom(self, axiom_id: str) -> list:
        """Get error codes that violate an axiom.

        Args:
            axiom_id: Axiom ID.

        Returns:
            List of error code dicts.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (a:Axiom {id: $id})-[:VIOLATED_BY]->(e:ErrorCode)
                RETURN e
                """,
                id=axiom_id,
            )
            return [dict(record["e"]) for record in result]

    def count_nodes(self) -> dict:
        """Count nodes by type.

        Returns:
            Dict with node counts.
        """
        with self.driver.session() as session:
            axiom_result = session.run("MATCH (a:Axiom) RETURN count(a) as count").single()
            error_result = session.run("MATCH (e:ErrorCode) RETURN count(e) as count").single()
            module_result = session.run("MATCH (m:KModule) RETURN count(m) as count").single()

            return {
                "axioms": axiom_result["count"] if axiom_result else 0,
                "error_codes": error_result["count"] if error_result else 0,
                "modules": module_result["count"] if module_result else 0,
            }

    def get_proof_chain(self, axiom_id: str) -> list:
        """Get the proof chain (dependency path) from an axiom to foundation.

        Follows DEPENDS_ON relationships to find the grounding axioms
        in c11_core, cpp_core, etc.

        Args:
            axiom_id: Starting axiom ID.

        Returns:
            List of axiom dicts forming the proof chain (deepest foundation first).
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH path = (a:Axiom {id: $id})-[:DEPENDS_ON*1..10]->(foundation:Axiom)
                WHERE foundation.layer IN ['c11_core', 'c11_stdlib', 'cpp_core', 'cpp_stdlib', 'cpp20_language', 'cpp20_stdlib']
                  AND ALL(n IN nodes(path) WHERE single(x IN nodes(path) WHERE x = n))
                WITH path, length(path) as depth
                ORDER BY depth DESC
                LIMIT 1
                UNWIND nodes(path) as node
                RETURN node
                """,
                id=axiom_id,
            )
            return [dict(record["node"]) for record in result]

    def get_dependencies(self, axiom_id: str) -> list:
        """Get direct dependencies of an axiom.

        Args:
            axiom_id: Axiom ID.

        Returns:
            List of axiom dicts that this axiom depends on.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (a:Axiom {id: $id})-[:DEPENDS_ON]->(dep:Axiom)
                RETURN dep
                """,
                id=axiom_id,
            )
            return [dict(record["dep"]) for record in result]

    def get_dependents(self, axiom_id: str) -> list:
        """Get axioms that depend on this axiom.

        Args:
            axiom_id: Axiom ID.

        Returns:
            List of axiom dicts that depend on this axiom.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (dependent:Axiom)-[:DEPENDS_ON]->(a:Axiom {id: $id})
                RETURN dependent
                """,
                id=axiom_id,
            )
            return [dict(record["dependent"]) for record in result]

    def get_axioms_by_function(self, function_name: str) -> list:
        """Get all axioms for a specific function.

        Args:
            function_name: Function name (e.g., "malloc", "memcpy").

        Returns:
            List of axiom dicts for that function.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (a:Axiom {function: $function})
                RETURN a
                """,
                function=function_name,
            )
            return [dict(record["a"]) for record in result]

    def get_axioms_by_header(self, header: str) -> list:
        """Get all axioms for a specific header.

        Args:
            header: Header file name (e.g., "stdlib.h", "string.h").

        Returns:
            List of axiom dicts from that header.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (a:Axiom {header: $header})
                RETURN a
                """,
                header=header,
            )
            return [dict(record["a"]) for record in result]

    def get_ungrounded_axioms(self) -> list:
        """Get library axioms without proof chains to foundations.

        Returns:
            List of axiom dicts that have no DEPENDS_ON path to foundation layers.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (a:Axiom)
                WHERE a.layer = 'library'
                AND NOT (a)-[:DEPENDS_ON*]->(:Axiom)
                RETURN a
                """
            )
            return [dict(record["a"]) for record in result]

    # --- Pairing and Idiom methods ---

    def create_pairing_relationship(self, pairing: Pairing) -> None:
        """Create a PAIRS_WITH relationship between two axioms.

        Args:
            pairing: Pairing defining the opener/closer relationship.
        """
        query = """
        MATCH (opener:Axiom {id: $opener_id})
        MATCH (closer:Axiom {id: $closer_id})
        MERGE (opener)-[r:PAIRS_WITH]->(closer)
        SET r.required = $required,
            r.source = $source,
            r.confidence = $confidence,
            r.cell = $cell,
            r.evidence = $evidence
        """
        with self.driver.session() as session:
            session.run(
                query,
                opener_id=pairing.opener_id,
                closer_id=pairing.closer_id,
                required=pairing.required,
                source=pairing.source,
                confidence=pairing.confidence,
                cell=pairing.cell,
                evidence=pairing.evidence,
            )

    def create_idiom_node(self, idiom: Idiom) -> None:
        """Create an Idiom node and link it to participating axioms.

        Args:
            idiom: Idiom with template and participants.
        """
        query = """
        MERGE (i:Idiom {id: $id})
        SET i.name = $name,
            i.template = $template,
            i.source = $source
        """
        with self.driver.session() as session:
            session.run(
                query,
                id=idiom.id,
                name=idiom.name,
                template=idiom.template,
                source=idiom.source,
            )

            # Create PARTICIPATES_IN relationships
            if idiom.participants:
                session.run(
                    """
                    MATCH (i:Idiom {id: $id})
                    UNWIND $participants AS participant_id
                    MATCH (a:Axiom {id: participant_id})
                    MERGE (a)-[:PARTICIPATES_IN]->(i)
                    """,
                    id=idiom.id,
                    participants=idiom.participants,
                )

    def get_paired_axioms(self, axiom_id: str) -> list[dict]:
        """Get axioms paired with the given axiom via PAIRS_WITH.

        Searches in both directions (opener or closer).

        Args:
            axiom_id: Axiom ID to find pairs for.

        Returns:
            List of paired axiom dicts.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (a:Axiom {id: $id})-[:PAIRS_WITH]-(paired:Axiom)
                RETURN paired
                """,
                id=axiom_id,
            )
            return [dict(record["paired"]) for record in result]

    def get_idioms_for_axiom(self, axiom_id: str) -> list[dict]:
        """Get idioms that the given axiom participates in.

        Args:
            axiom_id: Axiom ID to find idioms for.

        Returns:
            List of idiom dicts with id, name, template, source.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (a:Axiom {id: $id})-[:PARTICIPATES_IN]->(i:Idiom)
                RETURN i
                """,
                id=axiom_id,
            )
            return [dict(record["i"]) for record in result]

    def load_pairings(self, pairings: list[Pairing]) -> None:
        """Load multiple pairings at once.

        Args:
            pairings: List of Pairing objects to create relationships for.
        """
        for pairing in pairings:
            self.create_pairing_relationship(pairing)

    def load_idioms(self, idioms: list[Idiom]) -> None:
        """Load multiple idioms at once.

        Args:
            idioms: List of Idiom objects to create.
        """
        for idiom in idioms:
            self.create_idiom_node(idiom)
