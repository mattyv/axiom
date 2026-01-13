# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Tests for the live axiom store."""


from axiom.models import Axiom, AxiomType, SourceLocation
from axiom.watcher.store import AxiomStore, InMemoryAxiomStore


def make_axiom(
    id: str,
    function: str | None = None,
    file: str = "/test/file.cpp",
    content: str = "Test axiom",
) -> Axiom:
    """Create a test axiom."""
    return Axiom(
        id=id,
        content=content,
        formal_spec="true",
        source=SourceLocation(file=file, module="test"),
        function=function,
        axiom_type=AxiomType.PRECONDITION,
        confidence=0.9,
    )


class TestInMemoryAxiomStore:
    """Tests for InMemoryAxiomStore."""

    def test_implements_protocol(self) -> None:
        """Store implements AxiomStore protocol."""
        store = InMemoryAxiomStore()
        assert isinstance(store, AxiomStore)

    def test_upsert_single_axiom(self) -> None:
        """Can insert a single axiom."""
        store = InMemoryAxiomStore()
        axiom = make_axiom("test.1", function="foo")

        store.upsert([axiom])

        assert len(store) == 1
        assert "test.1" in store

    def test_upsert_multiple_axioms(self) -> None:
        """Can insert multiple axioms."""
        store = InMemoryAxiomStore()
        axioms = [
            make_axiom("test.1", function="foo"),
            make_axiom("test.2", function="bar"),
            make_axiom("test.3", function="foo"),
        ]

        store.upsert(axioms)

        assert len(store) == 3

    def test_upsert_updates_existing(self) -> None:
        """Upserting with same ID updates the axiom."""
        store = InMemoryAxiomStore()
        axiom1 = make_axiom("test.1", content="Original")
        axiom2 = make_axiom("test.1", content="Updated")

        store.upsert([axiom1])
        store.upsert([axiom2])

        assert len(store) == 1
        result = store.get_all()
        assert result[0].content == "Updated"

    def test_query_by_function(self) -> None:
        """Can query axioms by function name."""
        store = InMemoryAxiomStore()
        axioms = [
            make_axiom("test.1", function="foo"),
            make_axiom("test.2", function="bar"),
            make_axiom("test.3", function="foo"),
        ]
        store.upsert(axioms)

        foo_axioms = store.query_by_function("foo")

        assert len(foo_axioms) == 2
        assert all(a.function == "foo" for a in foo_axioms)

    def test_query_by_function_not_found(self) -> None:
        """Query for non-existent function returns empty list."""
        store = InMemoryAxiomStore()
        store.upsert([make_axiom("test.1", function="foo")])

        result = store.query_by_function("nonexistent")

        assert result == []

    def test_query_by_file(self) -> None:
        """Can query axioms by file path."""
        store = InMemoryAxiomStore()
        axioms = [
            make_axiom("test.1", file="/src/foo.cpp"),
            make_axiom("test.2", file="/src/bar.cpp"),
            make_axiom("test.3", file="/src/foo.cpp"),
        ]
        store.upsert(axioms)

        foo_axioms = store.query_by_file("/src/foo.cpp")

        assert len(foo_axioms) == 2

    def test_delete_by_file(self) -> None:
        """Can delete all axioms from a file."""
        store = InMemoryAxiomStore()
        axioms = [
            make_axiom("test.1", file="/src/foo.cpp", function="foo"),
            make_axiom("test.2", file="/src/bar.cpp", function="bar"),
            make_axiom("test.3", file="/src/foo.cpp", function="baz"),
        ]
        store.upsert(axioms)

        store.delete_by_file("/src/foo.cpp")

        assert len(store) == 1
        assert "test.2" in store
        assert "test.1" not in store
        assert "test.3" not in store

    def test_delete_by_file_updates_function_index(self) -> None:
        """Deleting by file also updates function index."""
        store = InMemoryAxiomStore()
        axioms = [
            make_axiom("test.1", file="/src/foo.cpp", function="foo"),
            make_axiom("test.2", file="/src/bar.cpp", function="foo"),
        ]
        store.upsert(axioms)

        store.delete_by_file("/src/foo.cpp")

        # Only one axiom with function "foo" should remain
        foo_axioms = store.query_by_function("foo")
        assert len(foo_axioms) == 1
        assert foo_axioms[0].id == "test.2"

    def test_get_all(self) -> None:
        """Can get all axioms."""
        store = InMemoryAxiomStore()
        axioms = [
            make_axiom("test.1"),
            make_axiom("test.2"),
        ]
        store.upsert(axioms)

        result = store.get_all()

        assert len(result) == 2

    def test_clear(self) -> None:
        """Can clear all axioms."""
        store = InMemoryAxiomStore()
        store.upsert([make_axiom("test.1"), make_axiom("test.2")])

        store.clear()

        assert len(store) == 0
        assert store.get_all() == []

    def test_contains(self) -> None:
        """Can check if axiom ID exists."""
        store = InMemoryAxiomStore()
        store.upsert([make_axiom("test.1")])

        assert "test.1" in store
        assert "test.2" not in store
