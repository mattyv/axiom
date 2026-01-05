# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Tests for the Axiom LSP server."""

from axiom.models import Axiom, AxiomType, SourceLocation


class TestAxiomLanguageServer:
    """Tests for the AxiomLanguageServer class."""

    def test_server_can_be_instantiated(self) -> None:
        """Server can be instantiated without errors."""
        from axiom.lsp.server import AxiomLanguageServer

        server = AxiomLanguageServer()
        assert server is not None

    def test_server_has_feature_handlers(self) -> None:
        """Server has registered feature handlers."""
        from axiom.lsp.server import AxiomLanguageServer

        server = AxiomLanguageServer()

        # Should have registered handlers
        assert hasattr(server, "_store")
        assert hasattr(server, "_extractor")


class TestHoverHandler:
    """Tests for hover handler functionality."""

    def test_get_hover_for_position_returns_content(self) -> None:
        """get_hover_for_position returns hover content for matching axiom."""
        from axiom.lsp.server import AxiomLanguageServer

        server = AxiomLanguageServer()

        # Store some test axioms
        axioms = [
            Axiom(
                id="test.precond",
                content="Test precondition",
                formal_spec="x > 0",
                source=SourceLocation(file="/test.cpp", module="test", line_start=5),
                function="test_func",
                axiom_type=AxiomType.PRECONDITION,
                confidence=0.9,
            )
        ]
        server._store.upsert(axioms)

        # Get hover for line 5 (1-indexed in source, 4 in LSP 0-indexed)
        result = server.get_hover_for_position("/test.cpp", line=4, character=10)

        assert result is not None
        assert "test_func" in result
        assert "Precondition" in result

    def test_get_hover_returns_none_for_no_axioms(self) -> None:
        """get_hover_for_position returns None when no axioms match."""
        from axiom.lsp.server import AxiomLanguageServer

        server = AxiomLanguageServer()

        result = server.get_hover_for_position("/nonexistent.cpp", line=1, character=1)

        assert result is None


class TestDiagnosticMode:
    """Tests for diagnostic mode configuration."""

    def test_default_mode_is_default(self) -> None:
        """Server defaults to 'default' diagnostic mode."""
        from axiom.lsp.server import AxiomLanguageServer

        server = AxiomLanguageServer()

        assert server._diagnostic_mode == "default"

    def test_mode_can_be_set(self) -> None:
        """Diagnostic mode can be changed."""
        from axiom.lsp.server import AxiomLanguageServer

        server = AxiomLanguageServer()
        server.set_diagnostic_mode("human")

        assert server._diagnostic_mode == "human"
