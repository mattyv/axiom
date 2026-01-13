# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Tests for axiom to LSP diagnostic conversion."""

import pytest

from axiom.models import Axiom, AxiomType, SourceLocation


class TestAxiomToDiagnostics:
    """Tests for converting Axiom objects to LSP diagnostics."""

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
            axiom_type=AxiomType.PRECONDITION,
            confidence=0.95,
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
            axiom_type=AxiomType.POSTCONDITION,
            confidence=0.90,
        )

    def test_axiom_to_diagnostics_returns_list(self, precondition_axiom: Axiom) -> None:
        """axiom_to_diagnostics returns a list of diagnostics."""
        from axiom.lsp.diagnostics import axiom_to_diagnostics

        result = axiom_to_diagnostics(precondition_axiom)

        assert isinstance(result, list)
        assert len(result) >= 1  # At least one diagnostic (axiom-context)

    def test_context_diagnostic_has_correct_source(self, precondition_axiom: Axiom) -> None:
        """Context diagnostic has source='axiom-context'."""
        from axiom.lsp.diagnostics import axiom_to_diagnostics

        diagnostics = axiom_to_diagnostics(precondition_axiom)

        context_diag = next(d for d in diagnostics if d.source == "axiom-context")
        assert context_diag is not None
        assert context_diag.source == "axiom-context"

    def test_context_diagnostic_is_information_severity(self, precondition_axiom: Axiom) -> None:
        """Context diagnostic has Information severity (shows in Problems panel)."""
        from lsprotocol.types import DiagnosticSeverity

        from axiom.lsp.diagnostics import axiom_to_diagnostics

        diagnostics = axiom_to_diagnostics(precondition_axiom)
        context_diag = next(d for d in diagnostics if d.source == "axiom-context")

        assert context_diag.severity == DiagnosticSeverity.Information

    def test_diagnostic_range_uses_line_numbers(self, precondition_axiom: Axiom) -> None:
        """Diagnostic range uses line_start from source location."""
        from axiom.lsp.diagnostics import axiom_to_diagnostics

        diagnostics = axiom_to_diagnostics(precondition_axiom)
        context_diag = next(d for d in diagnostics if d.source == "axiom-context")

        # LSP lines are 0-indexed, axiom lines are 1-indexed
        assert context_diag.range.start.line == 9  # line_start=10 -> 9
        assert context_diag.range.start.character == 0
        # End of line (we use large value since we don't have column info)
        assert context_diag.range.end.character > 0

    def test_diagnostic_code_is_axiom_id(self, precondition_axiom: Axiom) -> None:
        """Diagnostic code is the axiom ID."""
        from axiom.lsp.diagnostics import axiom_to_diagnostics

        diagnostics = axiom_to_diagnostics(precondition_axiom)
        context_diag = next(d for d in diagnostics if d.source == "axiom-context")

        assert context_diag.code == "demo.divide.precond.nonzero"

    def test_diagnostic_message_includes_function_and_type(
        self, precondition_axiom: Axiom
    ) -> None:
        """Diagnostic message includes function name and axiom type."""
        from axiom.lsp.diagnostics import axiom_to_diagnostics

        diagnostics = axiom_to_diagnostics(precondition_axiom)
        context_diag = next(d for d in diagnostics if d.source == "axiom-context")

        assert "divide" in context_diag.message
        assert "PRECONDITION" in context_diag.message.upper()

    def test_diagnostic_message_includes_content(self, precondition_axiom: Axiom) -> None:
        """Diagnostic message includes the axiom content."""
        from axiom.lsp.diagnostics import axiom_to_diagnostics

        diagnostics = axiom_to_diagnostics(precondition_axiom)
        context_diag = next(d for d in diagnostics if d.source == "axiom-context")

        assert "Divisor must not be zero" in context_diag.message

    def test_axiom_without_line_info_uses_line_zero(self) -> None:
        """Axiom without line info defaults to line 0."""
        from axiom.lsp.diagnostics import axiom_to_diagnostics

        axiom = Axiom(
            id="test.axiom",
            content="Test content",
            formal_spec="test",
            source=SourceLocation(file="/test.cpp", module="test"),
            confidence=1.0,
        )

        diagnostics = axiom_to_diagnostics(axiom)
        context_diag = next(d for d in diagnostics if d.source == "axiom-context")

        assert context_diag.range.start.line == 0

    def test_multiple_axioms_to_diagnostics(
        self, precondition_axiom: Axiom, postcondition_axiom: Axiom
    ) -> None:
        """Convert multiple axioms to diagnostics list."""
        from axiom.lsp.diagnostics import axioms_to_diagnostics

        diagnostics = axioms_to_diagnostics([precondition_axiom, postcondition_axiom])

        # Should have at least 2 diagnostics (one per axiom)
        assert len(diagnostics) >= 2

        # Check both axiom IDs present
        codes = [d.code for d in diagnostics]
        assert "demo.divide.precond.nonzero" in codes
        assert "demo.divide.postcond.result" in codes


class TestDiagnosticModeFiltering:
    """Tests for diagnostic mode filtering (human vs LLM)."""

    @pytest.fixture
    def test_axiom(self) -> Axiom:
        """Create a test axiom."""
        return Axiom(
            id="test.axiom",
            content="Test axiom",
            formal_spec="test",
            source=SourceLocation(file="/test.cpp", module="test", line_start=1),
            axiom_type=AxiomType.PRECONDITION,
            confidence=0.95,
        )

    def test_default_mode_emits_context(self, test_axiom: Axiom) -> None:
        """Default mode emits axiom-context diagnostics."""
        from axiom.lsp.diagnostics import axiom_to_diagnostics

        diagnostics = axiom_to_diagnostics(test_axiom, mode="default")

        sources = [d.source for d in diagnostics]
        assert "axiom-context" in sources

    def test_llm_mode_emits_context(self, test_axiom: Axiom) -> None:
        """LLM mode emits axiom-context diagnostics."""
        from axiom.lsp.diagnostics import axiom_to_diagnostics

        diagnostics = axiom_to_diagnostics(test_axiom, mode="llm")

        sources = [d.source for d in diagnostics]
        assert "axiom-context" in sources

    def test_human_mode_suppresses_context(self, test_axiom: Axiom) -> None:
        """Human mode suppresses axiom-context diagnostics."""
        from axiom.lsp.diagnostics import axiom_to_diagnostics

        diagnostics = axiom_to_diagnostics(test_axiom, mode="human")

        sources = [d.source for d in diagnostics]
        assert "axiom-context" not in sources
