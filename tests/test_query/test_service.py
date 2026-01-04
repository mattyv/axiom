# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Tests for the axiom query service."""

import pytest

from axiom.models import Axiom, AxiomType, SourceLocation
from axiom.query.service import AxiomQueryService, AxiomResult
from axiom.watcher.store import InMemoryAxiomStore


def make_axiom(
    id: str,
    function: str | None = None,
    file: str = "/test/file.cpp",
    content: str = "Test axiom",
    axiom_type: AxiomType = AxiomType.PRECONDITION,
) -> Axiom:
    """Create a test axiom."""
    return Axiom(
        id=id,
        content=content,
        formal_spec="true",
        source=SourceLocation(file=file, module="test"),
        function=function,
        axiom_type=axiom_type,
        confidence=0.9,
    )


class TestAxiomQueryService:
    """Tests for AxiomQueryService."""

    def test_query_empty_symbols(self) -> None:
        """Query with empty symbols returns empty list."""
        service = AxiomQueryService()

        result = service.query([])

        assert result == []

    def test_query_live_layer_only(self) -> None:
        """Query returns axioms from live layer when no Neo4j."""
        store = InMemoryAxiomStore()
        store.upsert([
            make_axiom("live.1", function="foo::bar(int)"),
            make_axiom("live.2", function="foo::bar(int)"),
        ])
        service = AxiomQueryService(live_store=store)

        results = service.query(["foo::bar(int)"])

        assert len(results) == 1
        assert results[0].symbol == "foo::bar(int)"
        assert results[0].layer == "live"
        assert len(results[0].axioms) == 2

    def test_query_multiple_symbols(self) -> None:
        """Query handles multiple symbols."""
        store = InMemoryAxiomStore()
        store.upsert([
            make_axiom("live.1", function="foo"),
            make_axiom("live.2", function="bar"),
        ])
        service = AxiomQueryService(live_store=store)

        results = service.query(["foo", "bar", "baz"])

        assert len(results) == 3
        assert results[0].symbol == "foo"
        assert len(results[0].axioms) == 1
        assert results[1].symbol == "bar"
        assert len(results[1].axioms) == 1
        assert results[2].symbol == "baz"
        assert results[2].layer == "none"
        assert len(results[2].axioms) == 0

    def test_get_axiom_from_live_store(self) -> None:
        """Can get specific axiom by ID from live store."""
        store = InMemoryAxiomStore()
        store.upsert([make_axiom("live.1", function="foo", content="Test content")])
        service = AxiomQueryService(live_store=store)

        result = service.get_axiom("live.1")

        assert result is not None
        assert result.id == "live.1"
        assert result.content == "Test content"
        assert result.layer == "live"

    def test_get_axiom_not_found(self) -> None:
        """Returns None when axiom not found."""
        store = InMemoryAxiomStore()
        service = AxiomQueryService(live_store=store)

        result = service.get_axiom("nonexistent")

        assert result is None

    def test_get_axioms_for_file(self) -> None:
        """Can get axioms for a specific file."""
        store = InMemoryAxiomStore()
        store.upsert([
            make_axiom("live.1", file="/src/foo.cpp"),
            make_axiom("live.2", file="/src/bar.cpp"),
            make_axiom("live.3", file="/src/foo.cpp"),
        ])
        service = AxiomQueryService(live_store=store)

        results = service.get_axioms_for_file("/src/foo.cpp")

        assert len(results) == 2
        assert all(r.layer == "live" for r in results)

    def test_axiom_result_includes_type(self) -> None:
        """AxiomResult includes axiom type."""
        store = InMemoryAxiomStore()
        store.upsert([make_axiom("live.1", function="foo", axiom_type=AxiomType.POSTCONDITION)])
        service = AxiomQueryService(live_store=store)

        results = service.query(["foo"])

        assert len(results[0].axioms) == 1
        assert results[0].axioms[0].axiom_type == "postcondition"

    def test_layer_detection_none(self) -> None:
        """Layer is 'none' when no axioms found."""
        service = AxiomQueryService()

        results = service.query(["unknown"])

        assert results[0].layer == "none"

    def test_layer_detection_live(self) -> None:
        """Layer is 'live' when only live axioms found."""
        store = InMemoryAxiomStore()
        store.upsert([make_axiom("live.1", function="foo")])
        service = AxiomQueryService(live_store=store)

        results = service.query(["foo"])

        assert results[0].layer == "live"


class TestAxiomResult:
    """Tests for AxiomResult dataclass."""

    def test_default_values(self) -> None:
        """AxiomResult has sensible defaults."""
        result = AxiomResult(
            id="test.1",
            content="Test",
            formal_spec="true",
            axiom_type="precondition",
            confidence=0.9,
            layer="live",
        )

        assert result.function is None
        assert result.signature is None
        assert result.header is None
        assert result.depends_on == []
        assert result.proof_chain == []
        assert result.pairs_with == []
