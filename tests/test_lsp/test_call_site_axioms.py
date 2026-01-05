# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Tests for call site axiom display.

When hovering over a function call, we should see the callee's axioms.
"""

import pytest

from axiom.models import Axiom, AxiomType, SourceLocation


class TestCallSiteHover:
    """Tests for showing axioms at call sites."""

    @pytest.fixture
    def divide_axiom(self) -> Axiom:
        """Axiom for divide function."""
        return Axiom(
            id="divide.precond.nonzero",
            content="Divisor must not be zero",
            formal_spec="b != 0",
            source=SourceLocation(file="/test/demo.cpp", module="demo", line_start=23),
            function="divide",
            signature="int divide(int a, int b)",
            axiom_type=AxiomType.PRECONDITION,
            confidence=0.95,
        )

    @pytest.fixture
    def call_graph(self) -> list[dict]:
        """Call graph with caller calling divide at line 100."""
        return [
            {
                "caller": "main",
                "callee": "divide",
                "callee_signature": "int divide(int a, int b)",
                "line": 100,
                "arguments": ["10", "2"],
            }
        ]

    def test_call_site_index_finds_calls_at_line(self, call_graph: list[dict]) -> None:
        """CallSiteIndex returns callees at a given line."""
        from axiom.lsp.call_sites import CallSiteIndex

        index = CallSiteIndex()
        index.add_call_graph("/test/demo.cpp", call_graph)

        callees = index.get_callees_at_line("/test/demo.cpp", 100)
        assert len(callees) == 1
        assert callees[0]["callee"] == "divide"

    def test_call_site_index_returns_empty_for_no_calls(self, call_graph: list[dict]) -> None:
        """CallSiteIndex returns empty for lines with no calls."""
        from axiom.lsp.call_sites import CallSiteIndex

        index = CallSiteIndex()
        index.add_call_graph("/test/demo.cpp", call_graph)

        callees = index.get_callees_at_line("/test/demo.cpp", 50)
        assert callees == []

    def test_get_axioms_for_call_site(self, divide_axiom: Axiom, call_graph: list[dict]) -> None:
        """Get axioms for a function being called."""
        from axiom.lsp.call_sites import CallSiteIndex, get_axioms_for_callee

        # Build axiom lookup by function name
        axioms_by_function = {"divide": [divide_axiom]}

        # Get axioms for the callee at line 100
        index = CallSiteIndex()
        index.add_call_graph("/test/demo.cpp", call_graph)

        callees = index.get_callees_at_line("/test/demo.cpp", 100)
        callee_name = callees[0]["callee"]

        axioms = get_axioms_for_callee(callee_name, axioms_by_function)
        assert len(axioms) == 1
        assert axioms[0].content == "Divisor must not be zero"


class TestCallSiteDiagnostics:
    """Tests for diagnostics at call sites."""

    @pytest.fixture
    def divide_axiom(self) -> Axiom:
        """Axiom for divide function."""
        return Axiom(
            id="divide.precond.nonzero",
            content="Divisor must not be zero",
            formal_spec="b != 0",
            source=SourceLocation(file="/test/demo.cpp", module="demo", line_start=23),
            function="divide",
            signature="int divide(int a, int b)",
            axiom_type=AxiomType.PRECONDITION,
            confidence=0.95,
        )

    @pytest.fixture
    def call_graph(self) -> list[dict]:
        """Call graph with main calling divide at line 100."""
        return [
            {
                "caller": "main",
                "callee": "divide",
                "callee_signature": "int divide(int a, int b)",
                "line": 100,
                "arguments": ["10", "2"],
            }
        ]

    def test_call_site_diagnostics_at_call_line(
        self, divide_axiom: Axiom, call_graph: list[dict]
    ) -> None:
        """Diagnostics are emitted at call site line, not definition line."""
        from axiom.lsp.call_sites import CallSiteIndex
        from axiom.lsp.diagnostics import call_site_diagnostics

        index = CallSiteIndex()
        index.add_call_graph("/test/demo.cpp", call_graph)

        axioms_by_function = {"divide": [divide_axiom]}

        def axiom_lookup(callee: str, signature: str | None = None) -> list:
            return axioms_by_function.get(callee, [])

        diagnostics = call_site_diagnostics(
            "/test/demo.cpp",
            index,
            axiom_lookup,
            mode="default",
        )

        # Should have diagnostic at line 100 (call site), not line 23 (definition)
        assert len(diagnostics) == 1
        assert diagnostics[0].range.start.line == 99  # LSP is 0-indexed


class TestAxiomTree:
    """Tests for showing axiom tree (transitive callees)."""

    def test_axiom_tree_includes_transitive_callees(self) -> None:
        """Axiom tree includes axioms from transitive callees."""
        from axiom.lsp.call_sites import CallSiteIndex, build_axiom_tree

        # a calls b, b calls c
        call_graph = [
            {"caller": "a", "callee": "b", "line": 10},
            {"caller": "b", "callee": "c", "line": 20},
        ]

        axiom_b = Axiom(
            id="b.precond",
            content="B precondition",
            formal_spec="",
            source=SourceLocation(file="/test.cpp", module="test"),
            function="b",
            axiom_type=AxiomType.PRECONDITION,
            confidence=0.9,
        )
        axiom_c = Axiom(
            id="c.precond",
            content="C precondition",
            formal_spec="",
            source=SourceLocation(file="/test.cpp", module="test"),
            function="c",
            axiom_type=AxiomType.PRECONDITION,
            confidence=0.9,
        )

        axioms_by_function = {"b": [axiom_b], "c": [axiom_c]}

        def axiom_lookup(callee: str, signature: str | None = None) -> list:
            return axioms_by_function.get(callee, [])

        index = CallSiteIndex()
        index.add_call_graph("/test.cpp", call_graph)

        # When hovering on call to 'b' at line 10, should see b's axioms and c's axioms
        tree = build_axiom_tree("b", index, axiom_lookup, max_depth=2)

        # Tree should contain both b and c
        assert tree.function == "b"
        assert len(tree.axioms) == 1
        assert tree.axioms[0].content == "B precondition"

        # Should have child for c
        assert len(tree.children) == 1
        assert tree.children[0].function == "c"
        assert tree.children[0].axioms[0].content == "C precondition"
