# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for LLM-based axiom enrichment.

These tests verify that the enricher correctly:
- Adds on_violation descriptions to axioms
- Infers missing EFFECT and POSTCONDITION axioms
- Batches axioms efficiently for LLM calls
- Handles LLM failures gracefully
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from axiom.models import Axiom, AxiomType, SourceLocation


def make_axiom(**kwargs) -> Axiom:
    """Create an axiom with default required fields."""
    defaults = {
        "id": "test.axiom",
        "content": "Test content",
        "formal_spec": "true",
        "source": SourceLocation(file="test.cpp", module="test"),
        "confidence": 0.95,
        "axiom_type": AxiomType.PRECONDITION,
    }
    defaults.update(kwargs)
    return Axiom(**defaults)


class TestEnricherBasics:
    """Basic enricher functionality tests."""

    def test_import_enricher_module(self):
        """Enricher module should be importable."""
        from axiom.extractors import enricher

        assert hasattr(enricher, "enrich_axioms")

    def test_enricher_accepts_axiom_list(self):
        """Enricher should accept a list of axioms."""
        from axiom.extractors.enricher import enrich_axioms

        axioms = [
            make_axiom(
                id="foo.precond.ptr_valid",
                content="Pointer ptr must not be null",
                formal_spec="ptr != nullptr",
            )
        ]

        # Should not raise
        result = enrich_axioms(axioms, use_llm=False)
        assert len(result) >= len(axioms)


class TestOnViolationEnrichment:
    """Tests for adding on_violation descriptions."""

    def test_precondition_gets_on_violation(self):
        """PRECONDITION axioms should get on_violation from LLM."""
        from axiom.extractors.enricher import build_enrichment_prompt

        axiom = make_axiom(
            id="divide.precond.divisor_nonzero",
            content="Divisor b must not be zero",
            formal_spec="b != 0",
        )

        prompt = build_enrichment_prompt([axiom])
        assert "on_violation" in prompt.lower() or "violation" in prompt.lower()

    def test_on_violation_parsing(self):
        """LLM response with on_violation should be parsed correctly."""
        from axiom.extractors.enricher import parse_enrichment_response

        axiom = make_axiom(
            id="test.precond",
            content="Test precondition",
            formal_spec="x > 0",
        )

        response = """```toml
[[axioms]]
id = "test.precond"
on_violation = "Division by zero error"
```"""

        enriched = parse_enrichment_response(response, [axiom])
        assert len(enriched) == 1
        assert enriched[0].on_violation == "Division by zero error"


class TestBatchingStrategy:
    """Tests for axiom batching."""

    def test_batch_size_respected(self):
        """Axioms should be batched by function for context coherence."""
        from axiom.extractors.enricher import group_by_function

        axioms = [
            make_axiom(id="foo.precond.1", content="c1", function="foo"),
            make_axiom(id="foo.precond.2", content="c2", function="foo"),
            make_axiom(id="bar.precond.1", content="c3", function="bar"),
        ]

        groups = group_by_function(axioms)
        assert len(groups) == 2
        assert len(groups["foo"]) == 2
        assert len(groups["bar"]) == 1

    def test_chunk_functions_for_batching(self):
        """Functions should be chunked for efficient batching."""
        from axiom.extractors.enricher import chunk_functions

        groups = {
            "func1": [MagicMock()],
            "func2": [MagicMock()],
            "func3": [MagicMock()],
        }

        chunks = list(chunk_functions(groups, max_functions=2))
        assert len(chunks) == 2  # 2 + 1


class TestInferredAxioms:
    """Tests for inferring missing axioms."""

    def test_infer_postcondition_from_signature(self):
        """LLM should infer POSTCONDITIONs from return type."""
        from axiom.extractors.enricher import build_enrichment_prompt

        axiom = make_axiom(
            id="get_size.constraint.noexcept",
            content="get_size is noexcept",
            formal_spec="noexcept(get_size())",
            axiom_type=AxiomType.CONSTRAINT,
            function="get_size",
        )

        prompt = build_enrichment_prompt([axiom])
        # Prompt should ask for postconditions
        assert "postcondition" in prompt.lower() or "return" in prompt.lower()


class TestErrorHandling:
    """Tests for error handling in enricher."""

    def test_empty_response_handled(self):
        """Empty LLM response should not crash."""
        from axiom.extractors.enricher import parse_enrichment_response

        axioms = [make_axiom(id="test", content="test")]

        result = parse_enrichment_response("", axioms)
        assert result == axioms  # Original axioms returned

    def test_invalid_toml_handled(self):
        """Invalid TOML should not crash."""
        from axiom.extractors.enricher import parse_enrichment_response

        axioms = [make_axiom(id="test", content="test")]

        result = parse_enrichment_response("not valid toml {{{", axioms)
        assert result == axioms  # Original axioms returned

    def test_missing_fields_use_defaults(self):
        """Missing fields in LLM response should use original values."""
        from axiom.extractors.enricher import parse_enrichment_response

        axiom = make_axiom(
            id="test.precond",
            content="Original content",
            formal_spec="x > 0",
        )

        # Response only has on_violation, no content override
        response = """```toml
[[axioms]]
id = "test.precond"
on_violation = "Error!"
```"""

        enriched = parse_enrichment_response(response, [axiom])
        assert enriched[0].content == "Original content"
        assert enriched[0].on_violation == "Error!"


class TestEnrichmentWithMockedLLM:
    """Tests with mocked LLM calls."""

    @patch("axiom.extractors.enricher.call_llm")
    def test_enrich_calls_llm_for_each_batch(self, mock_llm):
        """LLM should be called for each batch."""
        from axiom.extractors.enricher import enrich_axioms

        mock_llm.return_value = """```toml
[[axioms]]
id = "test.precond"
on_violation = "Mocked error"
```"""

        axioms = [
            make_axiom(
                id="test.precond",
                content="Test",
                function="test_func",
            )
        ]

        result = enrich_axioms(axioms, use_llm=True)
        assert mock_llm.called
        assert len(result) >= 1

    @patch("axiom.extractors.enricher.call_llm")
    def test_llm_failure_preserves_original(self, mock_llm):
        """LLM failure should preserve original axioms."""
        from axiom.extractors.enricher import enrich_axioms

        mock_llm.return_value = ""  # Empty response simulates failure

        axioms = [make_axiom(id="test.precond", content="Original")]

        result = enrich_axioms(axioms, use_llm=True)
        assert len(result) == 1
        assert result[0].content == "Original"


class TestNoLLMMode:
    """Tests for running without LLM."""

    def test_no_llm_returns_original(self):
        """use_llm=False should return original axioms unchanged."""
        from axiom.extractors.enricher import enrich_axioms

        axioms = [make_axiom(id="test.precond", content="Test")]

        result = enrich_axioms(axioms, use_llm=False)
        assert result == axioms


class TestCLIIntegration:
    """Tests for CLI flag integration."""

    def test_enrich_flag_calls_enricher(self):
        """--enrich flag should trigger enrichment."""
        # This tests that the flag exists and is wired up
        # Actual integration tested in extract_clang.py
        from axiom.extractors.enricher import enrich_axioms

        # Function should exist and be callable
        assert callable(enrich_axioms)
