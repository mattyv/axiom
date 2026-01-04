# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Axiom storage interface and implementations for live layer.

The store interface is designed to be DB-ready - start with InMemoryAxiomStore,
swap to SQLiteAxiomStore later if memory becomes an issue.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from axiom.models import Axiom


@runtime_checkable
class AxiomStore(Protocol):
    """Interface for live axiom storage.

    All implementations must support these operations for the live layer.
    The interface is intentionally simple to allow easy swapping between
    in-memory and persistent storage.
    """

    def upsert(self, axioms: list[Axiom]) -> None:
        """Insert or update axioms.

        Axioms are keyed by their ID. If an axiom with the same ID exists,
        it will be replaced.

        Args:
            axioms: List of axioms to insert/update.
        """
        ...

    def query_by_function(self, qualified_name: str) -> list[Axiom]:
        """Get axioms for a function by its qualified name.

        Args:
            qualified_name: Fully qualified function name (e.g., "foo::bar(int)").

        Returns:
            List of axioms associated with this function.
        """
        ...

    def query_by_file(self, file_path: str) -> list[Axiom]:
        """Get all axioms extracted from a file.

        Args:
            file_path: Absolute path to the source file.

        Returns:
            List of axioms from this file.
        """
        ...

    def delete_by_file(self, file_path: str) -> None:
        """Remove all axioms from a file.

        Called before re-extraction to clear stale axioms.

        Args:
            file_path: Absolute path to the source file.
        """
        ...

    def get_all(self) -> list[Axiom]:
        """Get all axioms in the store.

        Returns:
            List of all axioms.
        """
        ...

    def clear(self) -> None:
        """Remove all axioms from the store."""
        ...


class InMemoryAxiomStore:
    """Fast in-memory implementation of AxiomStore.

    Uses dictionaries for O(1) lookups by function and file.
    Suitable for most projects; swap to SQLiteAxiomStore for very large codebases.
    """

    def __init__(self) -> None:
        """Initialize empty store."""
        # Primary storage: axiom_id -> Axiom
        self._axioms: dict[str, Axiom] = {}

        # Indexes for fast lookup
        self._by_function: dict[str, set[str]] = defaultdict(set)  # function -> axiom_ids
        self._by_file: dict[str, set[str]] = defaultdict(set)  # file_path -> axiom_ids

    def upsert(self, axioms: list[Axiom]) -> None:
        """Insert or update axioms."""
        for axiom in axioms:
            # Remove from old indexes if updating
            if axiom.id in self._axioms:
                old = self._axioms[axiom.id]
                if old.function:
                    self._by_function[old.function].discard(axiom.id)
                if old.source and old.source.file:
                    self._by_file[old.source.file].discard(axiom.id)

            # Store axiom
            self._axioms[axiom.id] = axiom

            # Update indexes
            if axiom.function:
                self._by_function[axiom.function].add(axiom.id)
            if axiom.source and axiom.source.file:
                self._by_file[axiom.source.file].add(axiom.id)

    def query_by_function(self, qualified_name: str) -> list[Axiom]:
        """Get axioms for a function by its qualified name."""
        axiom_ids = self._by_function.get(qualified_name, set())
        return [self._axioms[aid] for aid in axiom_ids if aid in self._axioms]

    def query_by_file(self, file_path: str) -> list[Axiom]:
        """Get all axioms extracted from a file."""
        axiom_ids = self._by_file.get(file_path, set())
        return [self._axioms[aid] for aid in axiom_ids if aid in self._axioms]

    def delete_by_file(self, file_path: str) -> None:
        """Remove all axioms from a file."""
        axiom_ids = self._by_file.pop(file_path, set())
        for axiom_id in axiom_ids:
            axiom = self._axioms.pop(axiom_id, None)
            if axiom and axiom.function:
                self._by_function[axiom.function].discard(axiom_id)

    def get_all(self) -> list[Axiom]:
        """Get all axioms in the store."""
        return list(self._axioms.values())

    def clear(self) -> None:
        """Remove all axioms from the store."""
        self._axioms.clear()
        self._by_function.clear()
        self._by_file.clear()

    def __len__(self) -> int:
        """Return number of axioms in store."""
        return len(self._axioms)

    def __contains__(self, axiom_id: str) -> bool:
        """Check if axiom ID exists in store."""
        return axiom_id in self._axioms
