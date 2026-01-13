# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Tests for hover content formatting."""

import pytest

from axiom.models import Axiom, AxiomType, SourceLocation


class TestFormatHover:
    """Tests for formatting axioms as markdown hover content."""

    @pytest.fixture
    def precondition_axiom(self) -> Axiom:
        """Create a test precondition axiom."""
        return Axiom(
            id="demo.divide.precond.nonzero",
            content="Divisor must not be zero",
            formal_spec="b != 0",
            source=SourceLocation(
                file="/test/demo.cpp",
                module="demo",
                line_start=10,
                line_end=15,
            ),
            function="divide",
            signature="int divide(int a, int b)",
            axiom_type=AxiomType.PRECONDITION,
            confidence=0.95,
            layer="live",
        )

    @pytest.fixture
    def postcondition_axiom(self) -> Axiom:
        """Create a test postcondition axiom."""
        return Axiom(
            id="demo.divide.postcond.result",
            content="Returns the quotient of a divided by b",
            formal_spec="result == a / b",
            source=SourceLocation(
                file="/test/demo.cpp",
                module="demo",
                line_start=10,
                line_end=15,
            ),
            function="divide",
            signature="int divide(int a, int b)",
            axiom_type=AxiomType.POSTCONDITION,
            confidence=0.90,
            layer="live",
        )

    def test_format_hover_returns_string(self, precondition_axiom: Axiom) -> None:
        """format_hover returns a markdown string."""
        from axiom.lsp.hover import format_hover

        result = format_hover([precondition_axiom])

        assert isinstance(result, str)
        assert len(result) > 0

    def test_hover_includes_function_name(self, precondition_axiom: Axiom) -> None:
        """Hover content includes the function name as header."""
        from axiom.lsp.hover import format_hover

        result = format_hover([precondition_axiom])

        assert "divide" in result

    def test_hover_includes_axiom_type(self, precondition_axiom: Axiom) -> None:
        """Hover content includes the axiom type."""
        from axiom.lsp.hover import format_hover

        result = format_hover([precondition_axiom])

        assert "Precondition" in result or "precondition" in result.lower()

    def test_hover_includes_content(self, precondition_axiom: Axiom) -> None:
        """Hover content includes the axiom content."""
        from axiom.lsp.hover import format_hover

        result = format_hover([precondition_axiom])

        assert "Divisor must not be zero" in result

    def test_hover_includes_formal_spec(self, precondition_axiom: Axiom) -> None:
        """Hover content includes the formal spec."""
        from axiom.lsp.hover import format_hover

        result = format_hover([precondition_axiom])

        assert "b != 0" in result

    def test_hover_includes_confidence(self, precondition_axiom: Axiom) -> None:
        """Hover content includes confidence percentage."""
        from axiom.lsp.hover import format_hover

        result = format_hover([precondition_axiom])

        assert "95%" in result

    def test_hover_multiple_axioms(
        self, precondition_axiom: Axiom, postcondition_axiom: Axiom
    ) -> None:
        """Hover content includes all axioms."""
        from axiom.lsp.hover import format_hover

        result = format_hover([precondition_axiom, postcondition_axiom])

        assert "Precondition" in result or "precondition" in result.lower()
        assert "Postcondition" in result or "postcondition" in result.lower()
        assert "Divisor must not be zero" in result
        assert "Returns the quotient" in result

    def test_hover_includes_layer_info(self, precondition_axiom: Axiom) -> None:
        """Hover content includes layer information."""
        from axiom.lsp.hover import format_hover

        result = format_hover([precondition_axiom])

        assert "live" in result.lower()

    def test_hover_includes_axiom_id(self, precondition_axiom: Axiom) -> None:
        """Hover content includes axiom ID."""
        from axiom.lsp.hover import format_hover

        result = format_hover([precondition_axiom])

        assert "demo.divide.precond.nonzero" in result

    def test_hover_empty_list_returns_empty(self) -> None:
        """format_hover with empty list returns indication of no axioms."""
        from axiom.lsp.hover import format_hover

        result = format_hover([])

        # Should return something indicating no axioms, or empty string
        assert result is not None

    def test_hover_signature_displayed(self, precondition_axiom: Axiom) -> None:
        """Hover content includes function signature if available."""
        from axiom.lsp.hover import format_hover

        result = format_hover([precondition_axiom])

        assert "int divide(int a, int b)" in result


class TestFormatHoverGrouping:
    """Tests for hover grouping axioms by function."""

    def test_axioms_grouped_by_function(self) -> None:
        """Axioms from same function are grouped together."""
        from axiom.lsp.hover import format_hover

        axiom1 = Axiom(
            id="foo.precond",
            content="Foo precondition",
            formal_spec="x > 0",
            source=SourceLocation(file="/test.cpp", module="test"),
            function="foo",
            axiom_type=AxiomType.PRECONDITION,
            confidence=0.9,
        )
        axiom2 = Axiom(
            id="foo.postcond",
            content="Foo postcondition",
            formal_spec="result >= 0",
            source=SourceLocation(file="/test.cpp", module="test"),
            function="foo",
            axiom_type=AxiomType.POSTCONDITION,
            confidence=0.9,
        )
        axiom3 = Axiom(
            id="bar.precond",
            content="Bar precondition",
            formal_spec="y != null",
            source=SourceLocation(file="/test.cpp", module="test"),
            function="bar",
            axiom_type=AxiomType.PRECONDITION,
            confidence=0.9,
        )

        result = format_hover([axiom1, axiom2, axiom3])

        # Both foo and bar should be present
        assert "foo" in result
        assert "bar" in result
