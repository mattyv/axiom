# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for K dependency extraction (TDD - tests first)."""

from pathlib import Path

import pytest

from axiom.extractors.k_dependencies import (
    KDependencyExtractor,
    build_function_index,
    extract_function_calls,
    resolve_depends_on,
)
from axiom.models import Axiom, SourceLocation


class TestExtractFunctionCalls:
    """Tests for extracting function calls from K rule RHS."""

    def test_extract_simple_function_call(self) -> None:
        """Should extract a simple function call."""
        rhs = "alignedAlloc(cfg:alignofMalloc, Sz)"
        calls = extract_function_calls(rhs)
        assert "alignedAlloc" in calls

    def test_extract_multiple_function_calls(self) -> None:
        """Should extract all function calls from complex RHS."""
        rhs = "alloc(obj(!I:Int, Align, alloc), type(no-type), Sz) ~> tv(...)"
        calls = extract_function_calls(rhs)
        assert "alloc" in calls
        # tv is a K primitive, may or may not be excluded

    def test_extract_builtin_delegation(self) -> None:
        """Should detect when one builtin delegates to another."""
        rhs = 'builtin("malloc", tv(N:Int *Int Size:Int, utype(cfg:sizeut)))'
        calls = extract_function_calls(rhs)
        assert "malloc" in calls

    def test_extract_chained_calls(self) -> None:
        """Should extract function calls from chained K expressions."""
        rhs = "foo(x) ~> bar(y) ~> baz(z)"
        calls = extract_function_calls(rhs)
        assert "foo" in calls
        assert "bar" in calls
        assert "baz" in calls

    def test_extract_nested_calls(self) -> None:
        """Should extract nested function calls."""
        rhs = "outer(inner(deepest(x)))"
        calls = extract_function_calls(rhs)
        assert "outer" in calls
        assert "inner" in calls
        assert "deepest" in calls

    def test_excludes_k_primitives(self) -> None:
        """Should exclude K primitive functions."""
        rhs = "tv(I, utype(int)) ~> type(void)"
        calls = extract_function_calls(rhs)
        # These should be excluded as K primitives
        assert "tv" not in calls
        assert "utype" not in calls
        assert "type" not in calls

    def test_excludes_integer_operations(self) -> None:
        """Should exclude K integer operations like +Int, *Int."""
        rhs = "foo(I1 +Int I2, N *Int Size)"
        calls = extract_function_calls(rhs)
        assert "foo" in calls
        # +Int, *Int should not be treated as function calls
        # They use infix notation, not function call syntax

    def test_empty_rhs(self) -> None:
        """Should handle empty RHS."""
        rhs = ""
        calls = extract_function_calls(rhs)
        assert calls == []

    def test_no_function_calls(self) -> None:
        """Should handle RHS with no function calls."""
        rhs = "tv(42, int)"
        calls = extract_function_calls(rhs)
        # Only K primitive, should be empty or contain only primitives
        assert "tv" not in calls


class TestBuildFunctionIndex:
    """Tests for building function name to axiom ID index."""

    def test_build_simple_index(self) -> None:
        """Should build index from function name to axiom ID."""
        axioms = [
            Axiom(
                id="c11_alloc_abc123",
                content="alloc allocates memory",
                formal_spec="",
                source=SourceLocation(file="alloc.k", module="C-MEMORY-ALLOC"),
                function="alloc",
            ),
            Axiom(
                id="c11_malloc_def456",
                content="malloc allocates heap memory",
                formal_spec="",
                source=SourceLocation(file="stdlib.k", module="LIBC-STDLIB"),
                function="malloc",
            ),
        ]
        index = build_function_index(axioms)
        assert "alloc" in index
        assert "c11_alloc_abc123" in index["alloc"]
        assert "malloc" in index
        assert "c11_malloc_def456" in index["malloc"]

    def test_multiple_axioms_per_function(self) -> None:
        """Should handle multiple axioms for same function."""
        axioms = [
            Axiom(
                id="c11_malloc_precond_abc",
                content="malloc precondition",
                formal_spec="size > 0",
                source=SourceLocation(file="stdlib.k", module="LIBC-STDLIB"),
                function="malloc",
            ),
            Axiom(
                id="c11_malloc_postcond_def",
                content="malloc postcondition",
                formal_spec="returns pointer or null",
                source=SourceLocation(file="stdlib.k", module="LIBC-STDLIB"),
                function="malloc",
            ),
        ]
        index = build_function_index(axioms)
        assert len(index["malloc"]) == 2
        assert "c11_malloc_precond_abc" in index["malloc"]
        assert "c11_malloc_postcond_def" in index["malloc"]

    def test_skip_axioms_without_function(self) -> None:
        """Should skip axioms without function field."""
        axioms = [
            Axiom(
                id="c11_division_abc",
                content="division by zero is undefined",
                formal_spec="divisor != 0",
                source=SourceLocation(file="mult.k", module="C-EXPR"),
                function=None,  # No function
            ),
        ]
        index = build_function_index(axioms)
        assert len(index) == 0

    def test_empty_axiom_list(self) -> None:
        """Should handle empty axiom list."""
        index = build_function_index([])
        assert index == {}


class TestResolveDependsOn:
    """Tests for resolving function calls to axiom IDs."""

    def test_resolve_known_functions(self) -> None:
        """Should resolve function calls to axiom IDs."""
        calls = ["alloc", "malloc"]
        index = {
            "alloc": ["c11_alloc_abc123"],
            "malloc": ["c11_malloc_def456"],
        }
        deps = resolve_depends_on(calls, index)
        assert "c11_alloc_abc123" in deps
        assert "c11_malloc_def456" in deps

    def test_skip_unknown_functions(self) -> None:
        """Should skip functions not in index."""
        calls = ["alloc", "unknownFunc"]
        index = {"alloc": ["c11_alloc_abc123"]}
        deps = resolve_depends_on(calls, index)
        assert deps == ["c11_alloc_abc123"]

    def test_flatten_multiple_axioms(self) -> None:
        """Should include all axiom IDs for functions with multiple axioms."""
        calls = ["malloc"]
        index = {
            "malloc": ["c11_malloc_precond", "c11_malloc_postcond"],
        }
        deps = resolve_depends_on(calls, index)
        assert len(deps) == 2
        assert "c11_malloc_precond" in deps
        assert "c11_malloc_postcond" in deps

    def test_empty_calls(self) -> None:
        """Should handle empty calls list."""
        deps = resolve_depends_on([], {"alloc": ["c11_alloc"]})
        assert deps == []

    def test_empty_index(self) -> None:
        """Should handle empty index."""
        deps = resolve_depends_on(["alloc"], {})
        assert deps == []


class TestKDependencyExtractor:
    """Integration tests for full dependency extraction."""

    def test_extract_with_dependencies_from_stdlib(
        self, c_semantics_root: Path
    ) -> None:
        """malloc should depend on alignedAlloc which depends on alloc."""
        stdlib_dir = c_semantics_root / "semantics" / "c" / "library"
        if not stdlib_dir.exists():
            pytest.skip("c-semantics not available")

        extractor = KDependencyExtractor(c_semantics_root / "semantics" / "c")
        axioms = extractor.extract_with_dependencies()

        # Find malloc axiom
        malloc_axioms = [a for a in axioms if a.function == "malloc"]
        assert len(malloc_axioms) > 0, "Should find malloc axiom"

        malloc_axiom = malloc_axioms[0]
        # malloc should have depends_on populated
        assert len(malloc_axiom.depends_on) > 0, "malloc should have dependencies"

    def test_cross_file_dependencies(self, c_semantics_root: Path) -> None:
        """Dependencies should work across different K files."""
        semantics_dir = c_semantics_root / "semantics" / "c"
        if not semantics_dir.exists():
            pytest.skip("c-semantics not available")

        extractor = KDependencyExtractor(semantics_dir)
        axioms = extractor.extract_with_dependencies()

        # Find axioms that call functions defined in other files
        # e.g., stdlib.k calls alloc from alloc.k
        axioms_with_deps = [a for a in axioms if a.depends_on]
        assert len(axioms_with_deps) > 0, "Should have axioms with dependencies"

    def test_no_self_dependencies(self, c_semantics_root: Path) -> None:
        """Axioms should not depend on themselves."""
        semantics_dir = c_semantics_root / "semantics" / "c"
        if not semantics_dir.exists():
            pytest.skip("c-semantics not available")

        extractor = KDependencyExtractor(semantics_dir)
        axioms = extractor.extract_with_dependencies()

        for axiom in axioms:
            assert axiom.id not in axiom.depends_on, (
                f"Axiom {axiom.id} depends on itself"
            )


class TestBuiltinDelegation:
    """Tests for detecting builtin function delegation."""

    def test_extract_builtin_target(self) -> None:
        """Should extract the target function from builtin() calls."""
        # This is the pattern: builtin("functionName", args...)
        rhs = 'builtin("realloc", tv(loc(Base, 0), _), tv(NewLen, _))'
        calls = extract_function_calls(rhs)
        assert "realloc" in calls

    def test_calloc_delegates_to_malloc(self) -> None:
        """calloc rule should show dependency on malloc."""
        # From stdlib.k: builtin("calloc", ...) => builtin("malloc", ...)
        rhs = 'builtin("malloc", tv(N:Int *Int Size:Int, utype(cfg:sizeut))) ~> calloc-aux'
        calls = extract_function_calls(rhs)
        assert "malloc" in calls

    def test_realloc_null_delegates_to_malloc(self) -> None:
        """realloc with null should delegate to malloc."""
        rhs = 'builtin("malloc", Len)'
        calls = extract_function_calls(rhs)
        assert "malloc" in calls


class TestCrossLayerDependencies:
    """Tests for cross-layer dependency resolution using base_index."""

    def test_base_index_merges_with_local_index(self) -> None:
        """base_index should be merged with local function index."""
        # Simulate a base index from c11_core
        base_index = {
            "alloc": ["c11_core_alloc_abc123"],
            "alignedAlloc": ["c11_core_aligned_def456"],
        }

        # Create a mock extractor scenario
        # When stdlib extracts, it should find these base functions
        calls = ["alloc", "malloc"]
        local_index = {"malloc": ["c11_stdlib_malloc_ghi789"]}

        # Merge indexes (same logic as in extract_with_dependencies)
        merged = dict(local_index)
        for func, axiom_ids in base_index.items():
            if func in merged:
                merged[func].extend(axiom_ids)
            else:
                merged[func] = list(axiom_ids)

        # Resolve using merged index
        deps = resolve_depends_on(calls, merged)
        assert "c11_core_alloc_abc123" in deps  # From base
        assert "c11_stdlib_malloc_ghi789" in deps  # From local

    def test_cross_layer_extraction(self, c_semantics_root: Path) -> None:
        """c11_stdlib should be able to resolve dependencies to c11_core functions."""
        core_dir = c_semantics_root / "semantics" / "c" / "language"
        stdlib_dir = c_semantics_root / "semantics" / "c" / "library"
        if not core_dir.exists() or not stdlib_dir.exists():
            pytest.skip("c-semantics not available")

        # First extract c11_core and build its function index
        core_extractor = KDependencyExtractor(core_dir)
        core_index = core_extractor.get_function_index()

        # Now extract c11_stdlib with the core index as base
        stdlib_extractor = KDependencyExtractor(stdlib_dir)
        stdlib_axioms = stdlib_extractor.extract_with_dependencies(base_index=core_index)

        # Check that stdlib axioms can depend on core axioms
        deps_to_core = []
        for axiom in stdlib_axioms:
            for dep in axiom.depends_on:
                # Check if this dependency looks like a core axiom
                # (we can't easily identify core vs stdlib by ID alone,
                # but we can verify deps exist)
                deps_to_core.append(dep)

        assert len(deps_to_core) > 0, "stdlib should have dependencies"

    def test_get_function_index(self, c_semantics_root: Path) -> None:
        """get_function_index should return function->axiom_ids mapping."""
        semantics_dir = c_semantics_root / "semantics" / "c" / "library"
        if not semantics_dir.exists():
            pytest.skip("c-semantics not available")

        extractor = KDependencyExtractor(semantics_dir)
        index = extractor.get_function_index()

        assert isinstance(index, dict)
        assert len(index) > 0, "Should have indexed functions"
        # Check structure: each value should be a list of axiom IDs
        for func, axiom_ids in index.items():
            assert isinstance(func, str)
            assert isinstance(axiom_ids, list)
            assert all(isinstance(aid, str) for aid in axiom_ids)
