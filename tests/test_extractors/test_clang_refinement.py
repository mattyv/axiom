"""Tests for RAG-based refinement in extract_clang.py script."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from axiom.models import Axiom, AxiomType, SourceLocation


def make_axiom(**kwargs) -> Axiom:
    """Helper to create axioms with default required fields."""
    defaults = {
        "id": "test.axiom",
        "content": "Test content",
        "formal_spec": "",
        "axiom_type": AxiomType.PRECONDITION,
        "source": SourceLocation(file="test.cpp", module="test"),
    }
    defaults.update(kwargs)
    return Axiom(**defaults)


class TestGroupAxiomsByFunction:
    """Tests for grouping axioms by function."""

    def test_groups_by_function_name(self):
        """Test that axioms are grouped by their function field."""
        from scripts.extract_clang import group_axioms_by_function

        axioms = [
            make_axiom(id="func1.precond.a", content="Test a", function="func1"),
            make_axiom(id="func1.precond.b", content="Test b", function="func1"),
            make_axiom(id="func2.precond.a", content="Test c", function="func2"),
        ]

        groups = group_axioms_by_function(axioms)

        assert len(groups) == 2
        assert "func1" in groups
        assert "func2" in groups
        assert len(groups["func1"]) == 2
        assert len(groups["func2"]) == 1

    def test_groups_none_function_as_global(self):
        """Test that axioms with None function go to __global__ group."""
        from scripts.extract_clang import group_axioms_by_function

        axioms = [
            make_axiom(
                id="global.constraint",
                content="Global constraint",
                axiom_type=AxiomType.CONSTRAINT,
                function=None,
            ),
        ]

        groups = group_axioms_by_function(axioms)

        assert "__global__" in groups
        assert len(groups["__global__"]) == 1


class TestBuildRefinementQueries:
    """Tests for semantic query generation."""

    def test_detects_division_keywords(self):
        """Test that division-related content triggers appropriate query."""
        from scripts.extract_clang import build_refinement_queries

        axiom = make_axiom(id="test.div", content="Divisor must not be zero")

        queries = build_refinement_queries(axiom)

        assert any("division" in q for q in queries)

    def test_detects_pointer_keywords(self):
        """Test that pointer-related content triggers appropriate query."""
        from scripts.extract_clang import build_refinement_queries

        axiom = make_axiom(id="test.ptr", content="Pointer must not be null")

        queries = build_refinement_queries(axiom)

        assert any("pointer" in q or "null" in q for q in queries)

    def test_detects_memory_keywords(self):
        """Test that memory-related content triggers appropriate query."""
        from scripts.extract_clang import build_refinement_queries

        axiom = make_axiom(id="test.mem", content="Memory must be allocated before use")

        queries = build_refinement_queries(axiom)

        assert any("memory" in q or "alloc" in q for q in queries)

    def test_always_includes_content_query(self):
        """Test that a generic content-based query is always included."""
        from scripts.extract_clang import build_refinement_queries

        axiom = make_axiom(id="test.generic", content="Some unique specific content here")

        queries = build_refinement_queries(axiom)

        # At least one query should contain part of the content
        assert any("unique" in q or "specific" in q for q in queries)

    def test_limits_queries_to_five(self):
        """Test that no more than 5 queries are returned."""
        from scripts.extract_clang import build_refinement_queries

        # Create axiom that matches many patterns
        axiom = make_axiom(
            id="test.multi",
            content="Division of pointer in array with memory allocation and thread safety for integer overflow",
        )

        queries = build_refinement_queries(axiom)

        assert len(queries) <= 5


class TestQueryRagForRefinement:
    """Tests for RAG context querying."""

    def test_returns_empty_without_vector_db(self):
        """Test that no results are returned without vector DB."""
        from scripts.extract_clang import query_rag_for_refinement

        axioms = [make_axiom(id="test", content="Test")]

        result = query_rag_for_refinement(axioms, None)

        assert result == []

    def test_deduplicates_candidates(self):
        """Test that duplicate candidates are removed."""
        from scripts.extract_clang import query_rag_for_refinement

        axioms = [
            make_axiom(
                id="test.ptr",
                content="Pointer must not be null and nullable pointers are bad",
            )
        ]

        mock_loader = Mock()

        with patch("scripts.extract_clang.semantic_linker") as mock_sl:
            # Return same result for multiple queries
            mock_sl.search_foundations.return_value = [
                {"id": "cpp_core.nullptr", "content": "Null pointer check"}
            ]

            result = query_rag_for_refinement(axioms, mock_loader)

            # Should only have one entry despite multiple queries matching
            assert len(result) == 1
            assert result[0]["id"] == "cpp_core.nullptr"

    def test_limits_results_to_fifteen(self):
        """Test that results are limited to 15 candidates."""
        from scripts.extract_clang import query_rag_for_refinement

        axioms = [make_axiom(id="test", content="Complex content with many matches")]

        mock_loader = Mock()

        with patch("scripts.extract_clang.semantic_linker") as mock_sl:
            # Return many unique results
            mock_sl.search_foundations.return_value = [
                {"id": f"axiom_{i}", "content": f"Content {i}"}
                for i in range(20)
            ]

            result = query_rag_for_refinement(axioms, mock_loader)

            assert len(result) <= 15


class TestFormatRelatedAxioms:
    """Tests for formatting related axioms for prompt."""

    def test_formats_empty_list(self):
        """Test formatting when no related axioms found."""
        from scripts.extract_clang import format_related_axioms

        result = format_related_axioms([])

        assert "No related" in result

    def test_formats_axiom_list(self):
        """Test that axioms are formatted with id and content."""
        from scripts.extract_clang import format_related_axioms

        related = [
            {"id": "cpp_core.nullptr", "content": "Null pointer dereference is UB"},
            {"id": "c11_core.division", "content": "Division by zero is UB"},
        ]

        result = format_related_axioms(related)

        assert "cpp_core.nullptr" in result
        assert "c11_core.division" in result
        assert "Null pointer" in result
        assert "Division by zero" in result

    def test_limits_to_ten_axioms(self):
        """Test that only first 10 axioms are included."""
        from scripts.extract_clang import format_related_axioms

        related = [
            {"id": f"axiom_{i}", "content": f"Content {i}"}
            for i in range(15)
        ]

        result = format_related_axioms(related)

        # axiom_10 through axiom_14 should not appear
        assert "axiom_10" not in result
        assert "axiom_0" in result
        assert "axiom_9" in result


class TestParseRefinementResponseWithDepends:
    """Tests for parsing refinement responses with depends_on."""

    def test_parses_depends_on(self):
        """Test that depends_on is parsed from response."""
        from scripts.extract_clang import parse_refinement_response_with_depends

        originals = [make_axiom(id="test.precond", content="Original content", confidence=0.5)]

        response = '''[[axioms]]
id = "test.precond"
content = "Improved content"
formal_spec = "improved_spec"
confidence = 0.9
function = ""
depends_on = ["cpp_core.nullptr", "c11_core.ptr"]
'''

        result = parse_refinement_response_with_depends(response, originals)

        assert result[0].content == "Improved content"
        assert result[0].confidence == 0.9
        assert "cpp_core.nullptr" in result[0].depends_on
        assert "c11_core.ptr" in result[0].depends_on

    def test_merges_with_existing_depends_on(self):
        """Test that new depends_on are merged with existing ones."""
        from scripts.extract_clang import parse_refinement_response_with_depends

        originals = [
            make_axiom(
                id="test.precond",
                content="Original",
                confidence=0.5,
                depends_on=["existing.dep"],
            )
        ]

        response = '''[[axioms]]
id = "test.precond"
content = "Original"
formal_spec = ""
confidence = 0.9
function = ""
depends_on = ["new.dep"]
'''

        result = parse_refinement_response_with_depends(response, originals)

        assert "existing.dep" in result[0].depends_on
        assert "new.dep" in result[0].depends_on

    def test_extracts_toml_from_markdown(self):
        """Test that TOML is extracted from markdown code blocks."""
        from scripts.extract_clang import parse_refinement_response_with_depends

        originals = [make_axiom(id="test.precond", content="Original", confidence=0.5)]

        response = '''Here's the refined axiom:

```toml
[[axioms]]
id = "test.precond"
content = "Refined content"
formal_spec = ""
confidence = 0.85
function = ""
depends_on = []
```

I've updated the content.'''

        result = parse_refinement_response_with_depends(response, originals)

        assert result[0].content == "Refined content"
        assert result[0].confidence == 0.85

    def test_returns_originals_on_parse_error(self):
        """Test that original axioms are returned if parsing fails."""
        from scripts.extract_clang import parse_refinement_response_with_depends

        originals = [make_axiom(id="test.precond", content="Original", confidence=0.5)]

        response = "This is not valid TOML { invalid"

        result = parse_refinement_response_with_depends(response, originals)

        assert result[0].content == "Original"
        assert result[0].confidence == 0.5


class TestRefineLowConfidenceAxioms:
    """Tests for the main refinement function."""

    def test_skips_when_use_llm_false(self):
        """Test that refinement is skipped when use_llm=False."""
        from scripts.extract_clang import refine_low_confidence_axioms

        axioms = [make_axiom(id="test", content="Test", confidence=0.5)]

        result = refine_low_confidence_axioms(axioms, use_llm=False)

        assert result == axioms

    def test_skips_high_confidence_axioms(self):
        """Test that high confidence axioms are not sent for refinement."""
        from scripts.extract_clang import refine_low_confidence_axioms

        axioms = [
            make_axiom(id="high", content="High confidence", confidence=0.95),
            make_axiom(id="low", content="Low confidence", confidence=0.5),
        ]

        with patch("scripts.extract_clang.call_claude_cli") as mock_cli:
            mock_cli.return_value = '''[[axioms]]
id = "low"
content = "Refined low"
formal_spec = ""
confidence = 0.9
function = ""
'''
            result = refine_low_confidence_axioms(axioms, use_llm=True)

            # Only low confidence axiom should be refined
            assert any(a.id == "high" and a.content == "High confidence" for a in result)
            assert any(a.id == "low" and a.content == "Refined low" for a in result)

    def test_uses_rag_when_vector_db_provided(self):
        """Test that RAG context is used when vector_db is provided."""
        from scripts.extract_clang import refine_low_confidence_axioms

        axioms = [
            make_axiom(id="test", content="Test pointer", confidence=0.5, function="test_func")
        ]

        mock_vector_db = Mock()

        with patch("scripts.extract_clang.query_rag_for_refinement") as mock_rag:
            mock_rag.return_value = [{"id": "cpp_core.ptr", "content": "Pointer info"}]
            with patch("scripts.extract_clang.call_claude_cli") as mock_cli:
                mock_cli.return_value = '''[[axioms]]
id = "test"
content = "Refined"
formal_spec = ""
confidence = 0.9
function = "test_func"
depends_on = ["cpp_core.ptr"]
'''
                with patch("scripts.extract_clang.build_refinement_prompt_with_rag") as mock_prompt:
                    mock_prompt.return_value = "prompt"
                    refine_low_confidence_axioms(axioms, use_llm=True, vector_db=mock_vector_db)

                    # RAG should be queried
                    mock_rag.assert_called()
                    # RAG prompt should be used
                    mock_prompt.assert_called()

    def test_passes_model_and_batch_size(self):
        """Test that model and batch_size are passed to call_claude_cli."""
        from scripts.extract_clang import refine_low_confidence_axioms

        axioms = [make_axiom(id="test", content="Test", confidence=0.5, function="test_func")]

        with patch("scripts.extract_clang.call_claude_cli") as mock_cli:
            mock_cli.return_value = ""
            refine_low_confidence_axioms(
                axioms,
                use_llm=True,
                model="opus",
                batch_size=50
            )

            # Model should be passed
            mock_cli.assert_called()
            call_args = mock_cli.call_args
            # Model is passed as second positional arg or as keyword
            model_arg = call_args.kwargs.get("model") or (call_args.args[1] if len(call_args.args) > 1 else None)
            assert model_arg == "opus"
