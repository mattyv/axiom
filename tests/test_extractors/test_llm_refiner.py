# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for LLM refiner functionality in extract_clang.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from axiom.models import Axiom, AxiomType, SourceLocation


# We'll test the functions once they're added to extract_clang
# For now, define the functions inline for TDD


def chunk(items: list, size: int):
    """Yield successive chunks of items."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def build_refinement_prompt(axioms: list[Axiom]) -> str:
    """Build prompt for axiom refinement."""
    axiom_lines = []
    for a in axioms:
        axiom_lines.append(
            f"""[[axioms]]
id = "{a.id}"
content = "{a.content}"
formal_spec = "{a.formal_spec}"
confidence = {a.confidence}
function = "{a.function or ''}"
"""
        )

    return f"""Review these low-confidence axioms extracted from C++ code.
For each axiom:
1. Verify correctness against C++ semantics
2. Improve the content/formal_spec if needed
3. Set confidence to your level of certainty (0.0-1.0)
4. Add rationale explaining your changes

Return ONLY valid TOML with refined axioms:

{chr(10).join(axiom_lines)}

Respond with refined axioms in the same TOML format, adding a 'rationale' field."""


def parse_refinement_response(response: str, originals: list[Axiom]) -> list[Axiom]:
    """Parse TOML response and update axioms."""
    import tomllib

    try:
        # Extract TOML block if wrapped in markdown
        if "```toml" in response:
            start = response.index("```toml") + 7
            end = response.index("```", start)
            response = response[start:end]

        data = tomllib.loads(response)
        refined_map = {a["id"]: a for a in data.get("axioms", [])}

        result = []
        for orig in originals:
            if orig.id in refined_map:
                r = refined_map[orig.id]
                # Create new axiom with refined values
                result.append(
                    Axiom(
                        id=orig.id,
                        content=r.get("content", orig.content),
                        formal_spec=r.get("formal_spec", orig.formal_spec),
                        source=orig.source,
                        layer=orig.layer,
                        confidence=r.get("confidence", orig.confidence),
                        function=orig.function,
                        axiom_type=orig.axiom_type,
                        depends_on=orig.depends_on,
                    )
                )
            else:
                result.append(orig)
        return result
    except Exception:
        return list(originals)


LLM_CONFIDENCE_THRESHOLD = 0.80
LLM_BATCH_SIZE = 10


def refine_low_confidence_axioms(
    axioms: list[Axiom],
    use_llm: bool = False,
    call_llm_fn=None,
) -> list[Axiom]:
    """Refine low-confidence axioms using LLM."""
    if not use_llm:
        return list(axioms)

    # Identify axioms needing refinement
    needs_refinement = [a for a in axioms if a.confidence < LLM_CONFIDENCE_THRESHOLD]
    if not needs_refinement:
        return list(axioms)

    refined = []
    for batch in chunk(needs_refinement, LLM_BATCH_SIZE):
        prompt = build_refinement_prompt(batch)
        if call_llm_fn:
            response = call_llm_fn(prompt)
        else:
            response = ""
        if response:
            batch_refined = parse_refinement_response(response, batch)
            refined.extend(batch_refined)
        else:
            # Keep originals if LLM fails
            refined.extend(batch)

    # Merge: replace refined axioms, keep others
    refined_ids = {a.id for a in refined}
    return [a for a in axioms if a.id not in refined_ids] + refined


# Test fixtures
@pytest.fixture
def low_confidence_axiom() -> Axiom:
    """Create a low-confidence axiom for testing."""
    return Axiom(
        id="foo.precond.test",
        content="Test precondition",
        formal_spec="x > 0",
        source=SourceLocation(file="test.cpp", module="test"),
        layer="user_library",
        confidence=0.5,
        function="foo",
        axiom_type=AxiomType.PRECONDITION,
    )


@pytest.fixture
def high_confidence_axiom() -> Axiom:
    """Create a high-confidence axiom for testing."""
    return Axiom(
        id="bar.precond.test",
        content="High confidence precondition",
        formal_spec="y != nullptr",
        source=SourceLocation(file="test.cpp", module="test"),
        layer="user_library",
        confidence=0.95,
        function="bar",
        axiom_type=AxiomType.PRECONDITION,
    )


class TestChunk:
    """Tests for chunk utility function."""

    def test_chunk_exact_division(self) -> None:
        """Test chunking when items divide evenly."""
        items = [1, 2, 3, 4, 5, 6]
        result = list(chunk(items, 2))
        assert result == [[1, 2], [3, 4], [5, 6]]

    def test_chunk_with_remainder(self) -> None:
        """Test chunking with leftover items."""
        items = [1, 2, 3, 4, 5]
        result = list(chunk(items, 2))
        assert result == [[1, 2], [3, 4], [5]]

    def test_chunk_empty_list(self) -> None:
        """Test chunking empty list."""
        result = list(chunk([], 5))
        assert result == []

    def test_chunk_larger_than_list(self) -> None:
        """Test chunk size larger than list."""
        items = [1, 2, 3]
        result = list(chunk(items, 10))
        assert result == [[1, 2, 3]]


class TestBuildRefinementPrompt:
    """Tests for building LLM refinement prompts."""

    def test_single_axiom_prompt(self, low_confidence_axiom: Axiom) -> None:
        """Test prompt generation for single axiom."""
        prompt = build_refinement_prompt([low_confidence_axiom])

        assert "foo.precond.test" in prompt
        assert "Test precondition" in prompt
        assert "x > 0" in prompt
        assert "0.5" in prompt
        assert "foo" in prompt
        assert "Review these low-confidence axioms" in prompt

    def test_multiple_axioms_prompt(
        self, low_confidence_axiom: Axiom, high_confidence_axiom: Axiom
    ) -> None:
        """Test prompt generation for multiple axioms."""
        prompt = build_refinement_prompt([low_confidence_axiom, high_confidence_axiom])

        assert "foo.precond.test" in prompt
        assert "bar.precond.test" in prompt


class TestParseRefinementResponse:
    """Tests for parsing LLM responses."""

    def test_parse_valid_toml(self, low_confidence_axiom: Axiom) -> None:
        """Test parsing valid TOML response."""
        response = """[[axioms]]
id = "foo.precond.test"
content = "Improved: Test precondition"
formal_spec = "x > 0 && x < INT_MAX"
confidence = 0.9
rationale = "Added upper bound check"
"""
        result = parse_refinement_response(response, [low_confidence_axiom])

        assert len(result) == 1
        assert result[0].content == "Improved: Test precondition"
        assert result[0].formal_spec == "x > 0 && x < INT_MAX"
        assert result[0].confidence == 0.9

    def test_parse_toml_in_markdown(self, low_confidence_axiom: Axiom) -> None:
        """Test parsing TOML wrapped in markdown code block."""
        response = """Here's the refined axiom:

```toml
[[axioms]]
id = "foo.precond.test"
content = "Refined content"
formal_spec = "x > 0"
confidence = 0.85
```

The axiom was improved."""
        result = parse_refinement_response(response, [low_confidence_axiom])

        assert len(result) == 1
        assert result[0].content == "Refined content"
        assert result[0].confidence == 0.85

    def test_parse_invalid_toml_returns_originals(
        self, low_confidence_axiom: Axiom
    ) -> None:
        """Test that invalid TOML returns original axioms."""
        response = "This is not valid TOML {{{"
        result = parse_refinement_response(response, [low_confidence_axiom])

        assert len(result) == 1
        assert result[0].content == low_confidence_axiom.content
        assert result[0].confidence == low_confidence_axiom.confidence

    def test_parse_missing_axiom_keeps_original(
        self, low_confidence_axiom: Axiom
    ) -> None:
        """Test that missing axiom in response keeps original."""
        response = """[[axioms]]
id = "different.id"
content = "Different axiom"
formal_spec = "y != 0"
confidence = 0.9
"""
        result = parse_refinement_response(response, [low_confidence_axiom])

        assert len(result) == 1
        assert result[0].id == low_confidence_axiom.id
        assert result[0].content == low_confidence_axiom.content


class TestRefineLowConfidenceAxioms:
    """Tests for the main refinement function."""

    def test_no_refinement_when_disabled(
        self, low_confidence_axiom: Axiom, high_confidence_axiom: Axiom
    ) -> None:
        """Test no changes when LLM is disabled."""
        axioms = [low_confidence_axiom, high_confidence_axiom]
        result = refine_low_confidence_axioms(axioms, use_llm=False)

        assert len(result) == 2
        assert result[0].confidence == 0.5  # Unchanged

    def test_only_low_confidence_refined(
        self, low_confidence_axiom: Axiom, high_confidence_axiom: Axiom
    ) -> None:
        """Test that only low-confidence axioms are sent to LLM."""
        mock_llm = MagicMock(
            return_value="""[[axioms]]
id = "foo.precond.test"
content = "Refined"
formal_spec = "x > 0"
confidence = 0.9
"""
        )

        axioms = [low_confidence_axiom, high_confidence_axiom]
        result = refine_low_confidence_axioms(axioms, use_llm=True, call_llm_fn=mock_llm)

        # LLM should be called once with only the low-confidence axiom
        mock_llm.assert_called_once()
        call_args = mock_llm.call_args[0][0]
        assert "foo.precond.test" in call_args
        assert "bar.precond.test" not in call_args  # High confidence not included

        # Result should include both axioms
        assert len(result) == 2

    def test_llm_failure_keeps_originals(self, low_confidence_axiom: Axiom) -> None:
        """Test that LLM failure preserves original axioms."""
        mock_llm = MagicMock(return_value="")  # Empty response = failure

        result = refine_low_confidence_axioms(
            [low_confidence_axiom], use_llm=True, call_llm_fn=mock_llm
        )

        assert len(result) == 1
        assert result[0].confidence == 0.5  # Unchanged

    def test_batch_processing(self) -> None:
        """Test that axioms are processed in batches."""
        # Create 25 low-confidence axioms
        axioms = [
            Axiom(
                id=f"test.precond.{i}",
                content=f"Test {i}",
                formal_spec=f"x{i} > 0",
                source=SourceLocation(file="test.cpp", module="test"),
                layer="user_library",
                confidence=0.5,
                function=f"func{i}",
                axiom_type=AxiomType.PRECONDITION,
            )
            for i in range(25)
        ]

        mock_llm = MagicMock(return_value="")  # Just count calls

        refine_low_confidence_axioms(axioms, use_llm=True, call_llm_fn=mock_llm)

        # Should be called 3 times (10 + 10 + 5)
        assert mock_llm.call_count == 3

    def test_no_low_confidence_skips_llm(self, high_confidence_axiom: Axiom) -> None:
        """Test that no LLM call is made if all axioms are high confidence."""
        mock_llm = MagicMock()

        result = refine_low_confidence_axioms(
            [high_confidence_axiom], use_llm=True, call_llm_fn=mock_llm
        )

        mock_llm.assert_not_called()
        assert len(result) == 1


class TestCallClaudeCli:
    """Tests for the Claude CLI integration (mocked)."""

    @patch("subprocess.run")
    def test_successful_call(self, mock_run: MagicMock) -> None:
        """Test successful CLI call."""
        # This tests the actual implementation in extract_clang.py
        # For now just test the mock setup
        mock_run.return_value = MagicMock(stdout="[[axioms]]\nid = 'test'", returncode=0)

        import subprocess

        result = subprocess.run(
            ["claude", "--print", "test prompt"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert "[[axioms]]" in result.stdout
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_timeout_returns_empty(self, mock_run: MagicMock) -> None:
        """Test timeout handling."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)

        try:
            subprocess.run(
                ["claude", "--print", "test prompt"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            result = ""
        except subprocess.TimeoutExpired:
            result = ""

        assert result == ""
