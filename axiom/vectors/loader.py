# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Load axiom embeddings into LanceDB."""

from pathlib import Path

import lancedb
from sentence_transformers import SentenceTransformer

from axiom.models import Axiom, AxiomCollection


class LanceDBLoader:
    """Load axiom embeddings into LanceDB."""

    def __init__(
        self,
        db_path: str = "./data/lancedb",
        model_name: str = "all-mpnet-base-v2",
        neo4j: "object | None" = None,
    ) -> None:
        """Initialize LanceDB connection and embedding model.

        Args:
            db_path: Path to LanceDB database directory.
            model_name: Sentence transformer model name.
            neo4j: Optional Neo4jLoader for pairing expansion.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.db_path))
        self._model: SentenceTransformer | None = None
        self._model_name = model_name
        self.neo4j = neo4j

    @property
    def model(self) -> SentenceTransformer:
        """Lazy load the embedding model."""
        if self._model is None:
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def load_collection(
        self,
        collection: AxiomCollection,
        table_name: str = "axioms",
    ) -> int:
        """Load axiom collection into LanceDB.

        Args:
            collection: AxiomCollection to load.
            table_name: Name of the LanceDB table.

        Returns:
            Number of records loaded.
        """
        records = []

        for axiom in collection.axioms:
            record = self._axiom_to_record(axiom)
            records.append(record)

        if not records:
            return 0

        # Add to existing table or create new one
        if table_name in self.db.table_names():
            table = self.db.open_table(table_name)
            table.add(records)
        else:
            self.db.create_table(table_name, records)
        return len(records)

    def load_axiom(
        self,
        axiom: Axiom,
        table_name: str = "axioms",
    ) -> None:
        """Load a single axiom into LanceDB.

        Args:
            axiom: Axiom to load.
            table_name: Name of the LanceDB table.
        """
        record = self._axiom_to_record(axiom)

        if table_name in self.db.table_names():
            table = self.db.open_table(table_name)
            table.add([record])
        else:
            self.db.create_table(table_name, [record])

    def _axiom_to_record(self, axiom: Axiom) -> dict:
        """Convert an Axiom to a LanceDB record.

        Args:
            axiom: Axiom to convert.

        Returns:
            Dict record with embedding vector.
        """
        # Create combined text for embedding
        embedding_text = self._create_embedding_text(axiom)
        vector = self.model.encode(embedding_text).tolist()

        return {
            "id": axiom.id,
            "content": axiom.content,
            "vector": vector,
            "layer": axiom.layer,
            "error_codes": [v.code for v in axiom.violated_by],
            "tags": axiom.tags,
            "source_file": axiom.source.file,
            "module": axiom.source.module,
            "c_standard_refs": axiom.c_standard_refs,
            "confidence": axiom.confidence,
            "formal_spec": axiom.formal_spec,
            # New fields for function-centric axioms
            "function": axiom.function or "",
            "header": axiom.header or "",
            "signature": axiom.signature or "",
            "axiom_type": axiom.axiom_type.value if axiom.axiom_type else "",
            "on_violation": axiom.on_violation or "",
            "depends_on": axiom.depends_on,
        }

    def _create_embedding_text(self, axiom: Axiom) -> str:
        """Create text for embedding from axiom.

        Args:
            axiom: Axiom to create embedding text for.

        Returns:
            Combined text for embedding.
        """
        parts = [axiom.content]

        # Add function and header context for library axioms
        if axiom.function:
            parts.append(f"Function: {axiom.function}")
        if axiom.header:
            parts.append(f"Header: {axiom.header}")
        if axiom.signature:
            parts.append(f"Signature: {axiom.signature}")
        if axiom.axiom_type:
            parts.append(f"Type: {axiom.axiom_type.value}")
        if axiom.on_violation:
            parts.append(f"On violation: {axiom.on_violation}")

        parts.append(f"Module: {axiom.source.module}")

        if axiom.tags:
            parts.append(f"Tags: {', '.join(axiom.tags)}")

        if axiom.violated_by:
            violations = [f"{v.error_type}: {v.message}" for v in axiom.violated_by]
            parts.append(f"Violations: {'; '.join(violations)}")

        return ". ".join(parts)

    def search(
        self,
        query: str,
        table_name: str = "axioms",
        limit: int = 10,
    ) -> list[dict]:
        """Search for axioms by semantic similarity.

        Args:
            query: Search query text.
            table_name: Name of the LanceDB table.
            limit: Maximum number of results.

        Returns:
            List of matching axiom records.
        """
        if table_name not in self.db.table_names():
            return []

        table = self.db.open_table(table_name)
        query_vector = self.model.encode(query).tolist()

        results = table.search(query_vector).limit(limit).to_list()
        return results

    def search_by_tag(
        self,
        tag: str,
        table_name: str = "axioms",
    ) -> list[dict]:
        """Search for axioms by tag.

        Args:
            tag: Tag to search for.
            table_name: Name of the LanceDB table.

        Returns:
            List of matching axiom records.
        """
        if table_name not in self.db.table_names():
            return []

        table = self.db.open_table(table_name)

        # Use SQL filter
        results = table.search().where(f"array_contains(tags, '{tag}')").to_list()
        return results

    def count(self, table_name: str = "axioms") -> int:
        """Count records in table.

        Args:
            table_name: Name of the LanceDB table.

        Returns:
            Number of records.
        """
        if table_name not in self.db.table_names():
            return 0

        table = self.db.open_table(table_name)
        return table.count_rows()

    def search_by_function(
        self,
        function_name: str,
        table_name: str = "axioms",
    ) -> list[dict]:
        """Search for axioms by function name.

        Args:
            function_name: Function name to search for.
            table_name: Name of the LanceDB table.

        Returns:
            List of matching axiom records.
        """
        if table_name not in self.db.table_names():
            return []

        table = self.db.open_table(table_name)
        results = table.search().where(f"function = '{function_name}'").to_list()
        return results

    def search_by_header(
        self,
        header: str,
        table_name: str = "axioms",
    ) -> list[dict]:
        """Search for axioms by header file.

        Args:
            header: Header file name to search for.
            table_name: Name of the LanceDB table.

        Returns:
            List of matching axiom records.
        """
        if table_name not in self.db.table_names():
            return []

        table = self.db.open_table(table_name)
        results = table.search().where(f"header = '{header}'").to_list()
        return results

    def search_by_axiom_type(
        self,
        axiom_type: str,
        table_name: str = "axioms",
    ) -> list[dict]:
        """Search for axioms by axiom type.

        Args:
            axiom_type: Axiom type (precondition, postcondition, etc.).
            table_name: Name of the LanceDB table.

        Returns:
            List of matching axiom records.
        """
        if table_name not in self.db.table_names():
            return []

        table = self.db.open_table(table_name)
        results = table.search().where(f"axiom_type = '{axiom_type}'").to_list()
        return results

    def update_depends_on(
        self,
        axiom_id: str,
        depends_on: list[str],
        table_name: str = "axioms",
    ) -> bool:
        """Update the depends_on field for an axiom.

        Args:
            axiom_id: ID of the axiom to update.
            depends_on: List of axiom IDs this axiom depends on.
            table_name: Name of the LanceDB table.

        Returns:
            True if update was successful, False otherwise.
        """
        if table_name not in self.db.table_names():
            return False

        table = self.db.open_table(table_name)

        # LanceDB update using pyarrow
        try:
            table.update(
                where=f"id = '{axiom_id}'",
                values={"depends_on": depends_on},
            )
            return True
        except Exception:
            return False

    def search_with_pairings(
        self,
        query: str,
        table_name: str = "axioms",
        limit: int = 10,
    ) -> list[dict]:
        """Search for axioms and auto-expand to include paired functions.

        This method:
        1. Performs regular semantic search
        2. For each result, fetches paired axioms from Neo4j
        3. Fetches idiom templates the axioms participate in
        4. Returns expanded results without duplicates

        Args:
            query: Search query text.
            table_name: Name of the LanceDB table.
            limit: Maximum number of base results.

        Returns:
            List of results including base axioms, paired axioms (marked with
            _paired_with), and idiom templates (marked with _idiom).
        """
        # Get base search results
        base_results = self.search(query, table_name=table_name, limit=limit)

        if not base_results:
            return []

        # If no Neo4j connection, just return base results
        if self.neo4j is None:
            return base_results

        expanded: list[dict] = []
        seen_ids: set[str] = set()

        for axiom in base_results:
            axiom_id = axiom.get("id")
            if not axiom_id or axiom_id in seen_ids:
                continue

            expanded.append(axiom)
            seen_ids.add(axiom_id)

            # Get paired axioms from Neo4j
            try:
                paired = self.neo4j.get_paired_axioms(axiom_id)
                for p in paired:
                    paired_id = p.get("id")
                    if paired_id and paired_id not in seen_ids:
                        p["_paired_with"] = axiom_id
                        expanded.append(p)
                        seen_ids.add(paired_id)

                # Get idiom templates
                idioms = self.neo4j.get_idioms_for_axiom(axiom_id)
                for idiom in idioms:
                    expanded.append({"_idiom": idiom})
            except Exception:
                # Neo4j error - continue without expansion
                pass

        return expanded
