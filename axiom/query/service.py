# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Query service for unified axiom lookups across static + live layers.

This service merges results from:
- Static layer: Neo4j (foundation + library axioms, with full dependency chains)
- Live layer: In-memory store (working directory axioms, fast C++ extraction)

The service provides the same axiom IDs and structure that MCP uses,
ensuring consistency between LSP diagnostics/hover and MCP tool responses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from axiom.graph import Neo4jLoader
    from axiom.watcher.store import AxiomStore

logger = logging.getLogger(__name__)


@dataclass
class AxiomResult:
    """Result from axiom query, suitable for LSP/MCP consumption."""

    id: str
    content: str
    formal_spec: str
    axiom_type: str | None
    confidence: float
    layer: str  # "static" or "live"
    function: str | None = None
    signature: str | None = None
    header: str | None = None

    # Dependency chain (for static layer axioms)
    depends_on: list[str] = field(default_factory=list)
    proof_chain: list[dict] = field(default_factory=list)

    # Pairing info
    pairs_with: list[str] = field(default_factory=list)


@dataclass
class SymbolAxioms:
    """Axioms for a specific symbol (function/type)."""

    symbol: str  # Qualified name
    layer: str  # "static", "live", or "both"
    axioms: list[AxiomResult] = field(default_factory=list)


class AxiomQueryService:
    """Unified query interface for static and live axiom layers.

    This is the primary interface for clangd plugin communication.
    It queries both Neo4j (static) and in-memory store (live), merging results.
    """

    def __init__(
        self,
        neo4j: Neo4jLoader | None = None,
        live_store: AxiomStore | None = None,
    ) -> None:
        """Initialize query service.

        Args:
            neo4j: Neo4j loader for static layer. Can be None if unavailable.
            live_store: In-memory store for live layer. Can be None if unavailable.
        """
        self._neo4j = neo4j
        self._live_store = live_store

    def query(self, symbols: list[str]) -> list[SymbolAxioms]:
        """Query axioms for multiple symbols.

        This is the main entry point for clangd plugin queries.

        Args:
            symbols: List of qualified function names (e.g., ["foo::bar(int)", "std::vector::push_back"]).

        Returns:
            List of SymbolAxioms, one per queried symbol.
        """
        results = []

        for symbol in symbols:
            axioms = self._query_symbol(symbol)
            layer = self._determine_layer(axioms)
            results.append(SymbolAxioms(
                symbol=symbol,
                layer=layer,
                axioms=axioms,
            ))

        return results

    def _query_symbol(self, symbol: str) -> list[AxiomResult]:
        """Query axioms for a single symbol from both layers."""
        results: list[AxiomResult] = []

        # Query live layer first (usually faster, working directory code)
        if self._live_store is not None:
            live_axioms = self._live_store.query_by_function(symbol)
            for axiom in live_axioms:
                results.append(AxiomResult(
                    id=axiom.id,
                    content=axiom.content,
                    formal_spec=axiom.formal_spec,
                    axiom_type=axiom.axiom_type.value if axiom.axiom_type else None,
                    confidence=axiom.confidence,
                    layer="live",
                    function=axiom.function,
                    signature=axiom.signature,
                    header=axiom.header,
                    depends_on=axiom.depends_on,
                    pairs_with=axiom.pairs_with,
                    # No proof chain for live axioms (not linked to foundation yet)
                    proof_chain=[],
                ))

        # Query static layer (Neo4j - foundation + library axioms)
        if self._neo4j is not None:
            try:
                static_axioms = self._neo4j.get_axioms_by_function(symbol)
                for axiom_dict in static_axioms:
                    axiom_id = axiom_dict.get("id", "")

                    # Get full proof chain for static axioms
                    proof_chain = self._neo4j.get_proof_chain(axiom_id)

                    # Get paired axioms
                    paired = self._neo4j.get_paired_axioms(axiom_id)
                    pairs_with = [p.get("id", "") for p in paired]

                    results.append(AxiomResult(
                        id=axiom_id,
                        content=axiom_dict.get("content", ""),
                        formal_spec=axiom_dict.get("formal_spec", ""),
                        axiom_type=axiom_dict.get("axiom_type"),
                        confidence=axiom_dict.get("confidence", 1.0),
                        layer="static",
                        function=axiom_dict.get("function"),
                        signature=axiom_dict.get("signature"),
                        header=axiom_dict.get("header"),
                        depends_on=axiom_dict.get("depends_on", []),
                        proof_chain=proof_chain,
                        pairs_with=pairs_with,
                    ))
            except Exception as e:
                logger.warning("Neo4j query failed for %s: %s", symbol, e)

        return results

    def _determine_layer(self, axioms: list[AxiomResult]) -> str:
        """Determine the combined layer for a set of axioms."""
        has_static = any(a.layer == "static" for a in axioms)
        has_live = any(a.layer == "live" for a in axioms)

        if has_static and has_live:
            return "both"
        elif has_static:
            return "static"
        elif has_live:
            return "live"
        else:
            return "none"

    def get_axiom(self, axiom_id: str) -> AxiomResult | None:
        """Get a specific axiom by ID.

        This matches the MCP get_axiom tool behavior.

        Args:
            axiom_id: Axiom ID.

        Returns:
            AxiomResult or None if not found.
        """
        # Check live store first
        if self._live_store is not None:
            for axiom in self._live_store.get_all():
                if axiom.id == axiom_id:
                    return AxiomResult(
                        id=axiom.id,
                        content=axiom.content,
                        formal_spec=axiom.formal_spec,
                        axiom_type=axiom.axiom_type.value if axiom.axiom_type else None,
                        confidence=axiom.confidence,
                        layer="live",
                        function=axiom.function,
                        signature=axiom.signature,
                        header=axiom.header,
                        depends_on=axiom.depends_on,
                        pairs_with=axiom.pairs_with,
                        proof_chain=[],
                    )

        # Check static layer
        if self._neo4j is not None:
            try:
                axiom_dict = self._neo4j.get_axiom(axiom_id)
                if axiom_dict:
                    proof_chain = self._neo4j.get_proof_chain(axiom_id)
                    paired = self._neo4j.get_paired_axioms(axiom_id)
                    pairs_with = [p.get("id", "") for p in paired]

                    return AxiomResult(
                        id=axiom_id,
                        content=axiom_dict.get("content", ""),
                        formal_spec=axiom_dict.get("formal_spec", ""),
                        axiom_type=axiom_dict.get("axiom_type"),
                        confidence=axiom_dict.get("confidence", 1.0),
                        layer="static",
                        function=axiom_dict.get("function"),
                        signature=axiom_dict.get("signature"),
                        header=axiom_dict.get("header"),
                        depends_on=axiom_dict.get("depends_on", []),
                        proof_chain=proof_chain,
                        pairs_with=pairs_with,
                    )
            except Exception as e:
                logger.warning("Neo4j get_axiom failed for %s: %s", axiom_id, e)

        return None

    def get_axioms_for_file(self, file_path: str) -> list[AxiomResult]:
        """Get all axioms from a specific file (live layer only).

        Args:
            file_path: Path to source file.

        Returns:
            List of axioms from that file.
        """
        results: list[AxiomResult] = []

        if self._live_store is not None:
            axioms = self._live_store.query_by_file(file_path)
            for axiom in axioms:
                results.append(AxiomResult(
                    id=axiom.id,
                    content=axiom.content,
                    formal_spec=axiom.formal_spec,
                    axiom_type=axiom.axiom_type.value if axiom.axiom_type else None,
                    confidence=axiom.confidence,
                    layer="live",
                    function=axiom.function,
                    signature=axiom.signature,
                    header=axiom.header,
                    depends_on=axiom.depends_on,
                    pairs_with=axiom.pairs_with,
                    proof_chain=[],
                ))

        return results
