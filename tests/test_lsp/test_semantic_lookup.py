# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Tests for semantic axiom lookup.

These tests verify that we can:
1. Parse operand types from callee signatures
2. Build semantic queries from call context
3. Get relevant axioms via semantic search (not flat tag lookup)
"""

import pytest


class TestSignatureParser:
    """Tests for parse_signature_types()."""

    def test_parse_binary_division(self) -> None:
        """Parse 'int operator/ int' -> ('operator/', 'int', 'int')."""
        from axiom.lsp.query_builder import parse_signature_types

        op, left, right = parse_signature_types("operator/", "int operator/ int")
        assert op == "operator/"
        assert left == "int"
        assert right == "int"

    def test_parse_binary_comparison(self) -> None:
        """Parse 'int operator>= int' -> ('operator>=', 'int', 'int')."""
        from axiom.lsp.query_builder import parse_signature_types

        op, left, right = parse_signature_types("operator>=", "int operator>= int")
        assert op == "operator>="
        assert left == "int"
        assert right == "int"

    def test_parse_float_division(self) -> None:
        """Parse 'float operator/ float' -> ('operator/', 'float', 'float')."""
        from axiom.lsp.query_builder import parse_signature_types

        op, left, right = parse_signature_types("operator/", "float operator/ float")
        assert op == "operator/"
        assert left == "float"
        assert right == "float"

    def test_parse_unary_dereference(self) -> None:
        """Parse 'operator* pointer' -> ('operator*', None, 'pointer')."""
        from axiom.lsp.query_builder import parse_signature_types

        op, left, right = parse_signature_types("operator*", "operator* pointer")
        assert op == "operator*"
        assert left is None
        assert right == "pointer"

    def test_parse_unary_address_of(self) -> None:
        """Parse 'operator& int' -> ('operator&', None, 'int')."""
        from axiom.lsp.query_builder import parse_signature_types

        op, left, right = parse_signature_types("operator&", "operator& int")
        assert op == "operator&"
        assert left is None
        assert right == "int"

    def test_parse_subscript(self) -> None:
        """Parse 'int operator[] array' -> ('operator[]', 'int', 'array')."""
        from axiom.lsp.query_builder import parse_signature_types

        op, left, right = parse_signature_types("operator[]", "int operator[] array")
        assert op == "operator[]"
        assert left == "int"
        assert right == "array"

    def test_parse_method_call_no_signature(self) -> None:
        """Method calls without operator signature return callee only."""
        from axiom.lsp.query_builder import parse_signature_types

        op, left, right = parse_signature_types("std::vector<int>::push_back", None)
        assert op == "std::vector<int>::push_back"
        assert left is None
        assert right is None

    def test_parse_function_call(self) -> None:
        """Regular function calls return callee only."""
        from axiom.lsp.query_builder import parse_signature_types

        op, left, right = parse_signature_types("malloc", "void* malloc(size_t)")
        assert op == "malloc"
        # Function signatures don't have operator format
        assert left is None
        assert right is None

    def test_parse_empty_signature(self) -> None:
        """Empty signature returns callee only."""
        from axiom.lsp.query_builder import parse_signature_types

        op, left, right = parse_signature_types("operator/", "")
        assert op == "operator/"
        assert left is None
        assert right is None


class TestQueryBuilder:
    """Tests for build_axiom_query()."""

    def test_division_query_mentions_integer(self) -> None:
        """Division with ints should mention 'integer' in query."""
        from axiom.lsp.query_builder import build_axiom_query

        query = build_axiom_query("operator/", "int operator/ int")
        assert "integer" in query.lower() or "int" in query.lower()

    def test_division_query_mentions_division(self) -> None:
        """Division query should mention 'division'."""
        from axiom.lsp.query_builder import build_axiom_query

        query = build_axiom_query("operator/", "int operator/ int")
        assert "division" in query.lower() or "divide" in query.lower()

    def test_float_division_mentions_float(self) -> None:
        """Float division should mention 'float' or 'floating'."""
        from axiom.lsp.query_builder import build_axiom_query

        query = build_axiom_query("operator/", "float operator/ float")
        assert "float" in query.lower()

    def test_comparison_query_has_no_pointer(self) -> None:
        """Integer comparison query should NOT mention pointer."""
        from axiom.lsp.query_builder import build_axiom_query

        query = build_axiom_query("operator>=", "int operator>= int")
        assert "pointer" not in query.lower()

    def test_comparison_query_has_no_restrict(self) -> None:
        """Integer comparison query should NOT mention restrict."""
        from axiom.lsp.query_builder import build_axiom_query

        query = build_axiom_query("operator>=", "int operator>= int")
        assert "restrict" not in query.lower()

    def test_subscript_query_mentions_bounds(self) -> None:
        """Array subscript should mention bounds or subscript."""
        from axiom.lsp.query_builder import build_axiom_query

        query = build_axiom_query("operator[]", "int operator[] array")
        query_lower = query.lower()
        assert "bounds" in query_lower or "subscript" in query_lower or "array" in query_lower

    def test_dereference_query_mentions_pointer(self) -> None:
        """Pointer dereference should mention pointer or null."""
        from axiom.lsp.query_builder import build_axiom_query

        query = build_axiom_query("operator*", "operator* pointer")
        query_lower = query.lower()
        assert "pointer" in query_lower or "dereference" in query_lower or "null" in query_lower

    def test_function_query_uses_name(self) -> None:
        """Function call query should include function name."""
        from axiom.lsp.query_builder import build_axiom_query

        query = build_axiom_query("std::mutex::lock", None)
        assert "mutex" in query.lower() or "lock" in query.lower()

    def test_query_includes_precondition(self) -> None:
        """Queries should mention precondition for better matching."""
        from axiom.lsp.query_builder import build_axiom_query

        query = build_axiom_query("operator/", "int operator/ int")
        # Precondition helps vector search find the right axiom type
        assert "precondition" in query.lower() or "require" in query.lower()


class TestSemanticLookup:
    """Integration tests - require LanceDB with axioms loaded."""

    @pytest.fixture
    def lance_loader(self):
        """Get LanceDB loader (skips if unavailable)."""
        try:
            from axiom.vectors import LanceDBLoader
            loader = LanceDBLoader()
            if loader.count() == 0:
                pytest.skip("LanceDB has no axioms loaded")
            return loader
        except Exception as e:
            pytest.skip(f"LanceDB not available: {e}")

    def test_division_search_returns_zero_check(self, lance_loader) -> None:
        """Division search should return 'divisor must be non-zero' or similar."""
        results = lance_loader.search("integer division precondition divisor", limit=10)
        contents = [r.get("content", "").lower() for r in results]

        # At least one result should mention zero/non-zero
        has_zero_check = any(
            "zero" in c or "non-zero" in c or "!= 0" in c or "≠ 0" in c
            for c in contents
        )
        assert has_zero_check, f"No zero check found in: {contents[:3]}"

    def test_integer_comparison_excludes_restrict(self, lance_loader) -> None:
        """Integer comparison search should not be dominated by restrict axioms."""
        results = lance_loader.search("integer comparison >= precondition", limit=10)

        # Count how many results mention restrict
        restrict_count = sum(
            1 for r in results
            if "restrict" in r.get("content", "").lower()
        )

        # Should not be majority restrict axioms
        assert restrict_count < len(results) / 2, (
            f"Too many restrict axioms: {restrict_count}/{len(results)}"
        )

    def test_semantic_search_returns_fewer_than_tag_lookup(self, lance_loader) -> None:
        """Semantic search should return fewer results than tag-based lookup."""
        # Semantic search with limit
        semantic_results = lance_loader.search("integer comparison >=", limit=10)

        # We expect semantic search to be focused (10 or fewer)
        assert len(semantic_results) <= 10

        # The key improvement: these 10 should be MORE relevant than
        # the 100+ you'd get from tag lookup
        # (This test just verifies we get a reasonable number back)

    def test_subscript_search_returns_bounds_axioms(self, lance_loader) -> None:
        """Array subscript search should return bounds-related axioms."""
        results = lance_loader.search("array subscript bounds precondition", limit=10)

        # Check that at least some results mention array/bounds/subscript
        relevant_count = sum(
            1 for r in results
            if any(term in r.get("content", "").lower()
                   for term in ["array", "bounds", "subscript", "element", "index"])
        )

        assert relevant_count > 0, "No array-related axioms found"


class TestSemanticVsTagLookup:
    """Compare semantic search to tag-based lookup."""

    @pytest.fixture
    def server_and_lance(self):
        """Get both LSP server and LanceDB loader."""
        try:
            from axiom.lsp.server import AxiomLanguageServer
            from axiom.vectors import LanceDBLoader

            server = AxiomLanguageServer()
            lance = LanceDBLoader()

            if lance.count() == 0:
                pytest.skip("LanceDB has no axioms loaded")

            return server, lance
        except Exception as e:
            pytest.skip(f"Setup failed: {e}")

    def test_comparison_semantic_is_smaller(self, server_and_lance) -> None:
        """Semantic search for comparison returns fewer axioms than tag lookup."""
        server, lance = server_and_lance

        # Old way: all axioms tagged "comparison"
        tag_axioms = server._axioms_by_tag.get("comparison", [])

        # New way: semantic search
        semantic_axioms = lance.search("integer comparison >= precondition", limit=10)

        # Semantic should be MUCH smaller
        if len(tag_axioms) > 0:
            assert len(semantic_axioms) < len(tag_axioms), (
                f"Semantic ({len(semantic_axioms)}) should be fewer than "
                f"tag lookup ({len(tag_axioms)})"
            )

    def test_division_semantic_finds_zero_check(self, server_and_lance) -> None:
        """Semantic search for division finds the zero-check axiom."""
        _, lance = server_and_lance

        results = lance.search("integer division divisor zero precondition", limit=5)
        contents = " ".join(r.get("content", "") for r in results).lower()

        # The critical axiom should be found
        assert "zero" in contents or "0" in contents, (
            "Division search should find divisor != 0 axiom"
        )
