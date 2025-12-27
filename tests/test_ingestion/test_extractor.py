"""Tests for the AxiomExtractor and related functionality."""

import pytest

from axiom.ingestion import AxiomExtractor, ExtractionResult, extract_axioms
from axiom.ingestion.prompts import (
    build_extraction_prompt,
    build_search_queries,
    format_key_operations,
    format_related_axioms,
)
from axiom.models import AxiomType


class TestAxiomExtractor:
    """Tests for AxiomExtractor class."""

    def test_extract_from_source_builds_subgraph(self):
        """Test that extraction builds a subgraph."""
        code = """
        int divide(int x, int y) {
            return x / y;
        }
        """
        extractor = AxiomExtractor()
        result = extractor.extract_from_source(code, "divide")

        assert result.function_name == "divide"
        assert result.subgraph is not None
        assert result.subgraph.name == "divide"

    def test_extract_returns_error_for_missing_function(self):
        """Test that extraction returns error for missing function."""
        code = "int foo() { return 0; }"
        extractor = AxiomExtractor()
        result = extractor.extract_from_source(code, "bar")

        assert result.error is not None
        assert "not found" in result.error

    def test_extract_identifies_hazardous_ops(self):
        """Test that hazardous operations are identified."""
        code = """
        int process(int* ptr, int divisor) {
            return *ptr / divisor;
        }
        """
        extractor = AxiomExtractor()
        result = extractor.extract_from_source(code, "process")

        # Should have subgraph with hazardous ops
        assert result.subgraph is not None
        assert len(result.subgraph.get_divisions()) > 0
        assert len(result.subgraph.get_pointer_operations()) > 0

    def test_extract_skips_safe_functions(self):
        """Test that functions without hazards return no axioms."""
        code = """
        int add(int a, int b) {
            return a + b;
        }
        """
        extractor = AxiomExtractor()
        result = extractor.extract_from_source(code, "add")

        # No hazardous ops, no axioms extracted
        assert result.axioms == []
        assert result.error is None

    def test_extract_with_c_language(self):
        """Test extraction with C language mode."""
        code = """
        int divide(int x, int y) {
            return x / y;
        }
        """
        extractor = AxiomExtractor(language="c")
        result = extractor.extract_from_source(code, "divide")

        assert result.subgraph is not None
        assert result.subgraph.name == "divide"

    def test_convenience_function(self):
        """Test the extract_axioms convenience function."""
        code = """
        int divide(int x, int y) {
            return x / y;
        }
        """
        result = extract_axioms(code, "divide")

        assert isinstance(result, ExtractionResult)
        assert result.function_name == "divide"


class TestLLMResponseParsing:
    """Tests for parsing LLM responses."""

    def test_parse_valid_toml_response(self):
        """Test parsing a valid TOML response."""
        extractor = AxiomExtractor()

        response = '''```toml
[[axioms]]
id = "test_divide_precond"
function = "divide"
header = "math.h"
axiom_type = "precondition"
content = "Division requires non-zero divisor"
formal_spec = "y != 0"
on_violation = "undefined behavior"
depends_on = ["c11_expr_div_nonzero"]
confidence = 0.9
```'''

        axioms = extractor._parse_llm_response(response, "divide", "math.h", "test.cpp")

        assert len(axioms) == 1
        axiom = axioms[0]
        assert axiom.function == "divide"
        assert axiom.header == "math.h"
        assert axiom.axiom_type == AxiomType.PRECONDITION
        assert axiom.formal_spec == "y != 0"
        assert axiom.on_violation == "undefined behavior"
        assert axiom.confidence == 0.9

    def test_parse_multiple_axioms(self):
        """Test parsing multiple axioms from response."""
        extractor = AxiomExtractor()

        response = '''```toml
[[axioms]]
id = "axiom1"
function = "process"
content = "First axiom"
axiom_type = "precondition"

[[axioms]]
id = "axiom2"
function = "process"
content = "Second axiom"
axiom_type = "postcondition"
```'''

        axioms = extractor._parse_llm_response(response, "process", "", "test.cpp")

        assert len(axioms) == 2
        assert axioms[0].axiom_type == AxiomType.PRECONDITION
        assert axioms[1].axiom_type == AxiomType.POSTCONDITION

    def test_parse_generates_id_if_missing(self):
        """Test that ID is generated if not provided."""
        extractor = AxiomExtractor()

        response = '''```toml
[[axioms]]
function = "test"
content = "Some axiom content"
```'''

        axioms = extractor._parse_llm_response(response, "test", "", "test.cpp")

        assert len(axioms) == 1
        assert axioms[0].id.startswith("lib_test_")

    def test_parse_handles_invalid_toml(self):
        """Test that invalid TOML returns empty list."""
        extractor = AxiomExtractor()

        response = "This is not valid TOML at all { ] }"

        axioms = extractor._parse_llm_response(response, "test", "", "test.cpp")

        assert axioms == []

    def test_parse_handles_empty_response(self):
        """Test that empty response returns empty list."""
        extractor = AxiomExtractor()

        axioms = extractor._parse_llm_response("", "test", "", "test.cpp")

        assert axioms == []


class TestPromptBuilding:
    """Tests for prompt building functions."""

    def test_build_extraction_prompt(self):
        """Test building the full extraction prompt."""
        from axiom.ingestion import SubgraphBuilder

        code = """
        int divide(int x, int y) {
            if (y != 0) {
                return x / y;
            }
            return 0;
        }
        """
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "divide")

        prompt = build_extraction_prompt(
            subgraph=subgraph,
            source_code=code,
            related_axioms=[],
            file_path="test.cpp",
        )

        assert "divide" in prompt
        assert "test.cpp" in prompt
        assert "Division" in prompt or "division" in prompt

    def test_build_search_queries_for_division(self):
        """Test search query generation for division."""
        from axiom.ingestion import SubgraphBuilder

        code = """
        int divide(int x, int y) {
            return x / y;
        }
        """
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "divide")

        queries = build_search_queries(subgraph)

        assert len(queries) > 0
        assert any("division" in q.lower() for q in queries)

    def test_build_search_queries_for_pointers(self):
        """Test search query generation for pointers."""
        from axiom.ingestion import SubgraphBuilder

        code = """
        int deref(int* ptr) {
            return *ptr;
        }
        """
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "deref")

        queries = build_search_queries(subgraph)

        assert len(queries) > 0
        assert any("pointer" in q.lower() for q in queries)

    def test_build_search_queries_for_array(self):
        """Test search query generation for array access."""
        from axiom.ingestion import SubgraphBuilder

        code = """
        int get(int arr[], int i) {
            return arr[i];
        }
        """
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "get")

        queries = build_search_queries(subgraph)

        assert len(queries) > 0
        assert any("array" in q.lower() or "bounds" in q.lower() for q in queries)

    def test_build_search_queries_for_function_calls(self):
        """Test search query generation for function calls."""
        from axiom.ingestion import SubgraphBuilder

        code = """
        void* allocate(int size) {
            return malloc(size);
        }
        """
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "allocate")

        queries = build_search_queries(subgraph)

        assert len(queries) > 0
        assert any("malloc" in q.lower() for q in queries)


class TestFormatFunctions:
    """Tests for formatting helper functions."""

    def test_format_key_operations_division(self):
        """Test formatting key operations for division."""
        from axiom.ingestion import SubgraphBuilder

        code = """
        int divide(int x, int y) {
            return x / y;
        }
        """
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "divide")

        formatted = format_key_operations(subgraph)

        assert "Division" in formatted or "Modulo" in formatted
        assert "x / y" in formatted

    def test_format_key_operations_empty(self):
        """Test formatting when no hazardous operations."""
        from axiom.ingestion import SubgraphBuilder

        code = """
        int add(int a, int b) {
            return a + b;
        }
        """
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "add")

        formatted = format_key_operations(subgraph)

        assert "No hazardous operations" in formatted

    def test_format_related_axioms(self):
        """Test formatting related axioms."""
        axioms = [
            {
                "id": "test_axiom_1",
                "content": "Division requires non-zero divisor",
                "formal_spec": "y != 0",
                "c_standard_refs": ["6.5.5/5"],
            },
            {
                "id": "test_axiom_2",
                "content": "Pointer must be valid",
                "formal_spec": "ptr != NULL",
                "c_standard_refs": [],
            },
        ]

        formatted = format_related_axioms(axioms)

        assert "test_axiom_1" in formatted
        assert "test_axiom_2" in formatted
        assert "Division requires non-zero divisor" in formatted
        assert "y != 0" in formatted

    def test_format_related_axioms_empty(self):
        """Test formatting with no related axioms."""
        formatted = format_related_axioms([])

        assert "No related foundation axioms" in formatted


class TestHeaderInference:
    """Tests for header file inference."""

    def test_infer_header_from_h_file(self):
        """Test header inference from .h file."""
        extractor = AxiomExtractor()
        header = extractor._infer_header("/path/to/stdlib.h")
        assert header == "stdlib.h"

    def test_infer_header_from_hpp_file(self):
        """Test header inference from .hpp file."""
        extractor = AxiomExtractor()
        header = extractor._infer_header("/path/to/vector.hpp")
        assert header == "vector.hpp"

    def test_infer_header_from_cpp_file(self):
        """Test header inference from .cpp file."""
        extractor = AxiomExtractor()
        header = extractor._infer_header("/path/to/utils.cpp")
        # Returns the source file name as fallback
        assert header == "utils.cpp"


class TestFunctionSourceExtraction:
    """Tests for extracting function source code."""

    def test_extract_function_source(self):
        """Test extracting just the function source."""
        from axiom.ingestion import SubgraphBuilder

        full_source = """#include <stdio.h>

int add(int a, int b) {
    return a + b;
}

int main() {
    return add(1, 2);
}
"""
        builder = SubgraphBuilder()
        subgraph = builder.build(full_source, "add")

        extractor = AxiomExtractor()
        func_source = extractor._extract_function_source(full_source, subgraph)

        assert "int add(int a, int b)" in func_source
        assert "return a + b" in func_source
        # Should not include main
        assert "int main()" not in func_source


class TestHazardousOperationDetection:
    """Tests for hazardous operation detection."""

    def test_detects_division_as_hazardous(self):
        """Test that division is detected as hazardous."""
        from axiom.ingestion import SubgraphBuilder

        code = "int f(int x, int y) { return x / y; }"
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "f")

        extractor = AxiomExtractor()
        assert extractor._has_hazardous_ops(subgraph) is True

    def test_detects_pointer_deref_as_hazardous(self):
        """Test that pointer dereference is detected as hazardous."""
        from axiom.ingestion import SubgraphBuilder

        code = "int f(int* p) { return *p; }"
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "f")

        extractor = AxiomExtractor()
        assert extractor._has_hazardous_ops(subgraph) is True

    def test_detects_function_call_as_hazardous(self):
        """Test that function calls are detected as potentially hazardous."""
        from axiom.ingestion import SubgraphBuilder

        code = "int f() { return foo(); }"
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "f")

        extractor = AxiomExtractor()
        assert extractor._has_hazardous_ops(subgraph) is True

    def test_simple_addition_not_hazardous(self):
        """Test that simple addition is not hazardous."""
        from axiom.ingestion import SubgraphBuilder

        code = "int f(int a, int b) { return a + b; }"
        builder = SubgraphBuilder()
        subgraph = builder.build(code, "f")

        extractor = AxiomExtractor()
        # Addition without function calls is not hazardous
        # Note: This test assumes no function calls makes it safe
        # The current implementation returns True for any function call
        # so we need a function with truly no hazards
        code_no_calls = "int f(int a, int b) { int c = a + b; return c; }"
        subgraph_no_calls = builder.build(code_no_calls, "f")

        # Still has no divisions, no pointer ops, but has variable declaration
        # The _has_hazardous_ops checks for divisions, pointers, memory ops, and calls
        assert extractor._has_hazardous_ops(subgraph_no_calls) is False
