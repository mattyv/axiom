# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for semantic axiom linking (TDD - tests first).

This module tests the LLM-assisted semantic linking of library axioms
to foundation axioms based on semantic concepts rather than just type signatures.
"""


from axiom.models import Axiom, SourceLocation


def create_test_axiom(
    id: str = "test_axiom",
    content: str = "Test axiom content",
    formal_spec: str = "",
    signature: str | None = None,
    function: str | None = None,
    layer: str = "library",
    depends_on: list | None = None,
) -> Axiom:
    """Create a test axiom."""
    return Axiom(
        id=id,
        content=content,
        formal_spec=formal_spec,
        layer=layer,
        source=SourceLocation(file="test.hpp", module="test"),
        signature=signature,
        function=function,
        depends_on=depends_on or [],
    )


class TestGroupByFunction:
    """Tests for grouping axioms by function name."""

    def test_groups_axioms_by_function_name(self) -> None:
        """Axioms with same function field should be grouped together."""
        from axiom.extractors.semantic_linker import group_by_function

        axioms = [
            create_test_axiom(id="a1", function="ILP_FOR"),
            create_test_axiom(id="a2", function="ILP_FOR"),
            create_test_axiom(id="a3", function="ILP_REDUCE"),
        ]

        groups = group_by_function(axioms)

        assert "ILP_FOR" in groups
        assert "ILP_REDUCE" in groups
        assert len(groups["ILP_FOR"]) == 2
        assert len(groups["ILP_REDUCE"]) == 1

    def test_ungrouped_for_none_function(self) -> None:
        """Axioms with None function go to 'ungrouped'."""
        from axiom.extractors.semantic_linker import group_by_function

        axioms = [
            create_test_axiom(id="a1", function=None),
            create_test_axiom(id="a2", function=None),
        ]

        groups = group_by_function(axioms)

        assert "ungrouped" in groups
        assert len(groups["ungrouped"]) == 2

    def test_preserves_all_axioms(self) -> None:
        """Total axioms across groups equals input count."""
        from axiom.extractors.semantic_linker import group_by_function

        axioms = [
            create_test_axiom(id="a1", function="func1"),
            create_test_axiom(id="a2", function="func2"),
            create_test_axiom(id="a3", function="func1"),
            create_test_axiom(id="a4", function=None),
        ]

        groups = group_by_function(axioms)

        total = sum(len(group) for group in groups.values())
        assert total == len(axioms)

    def test_empty_input(self) -> None:
        """Empty input returns empty dict."""
        from axiom.extractors.semantic_linker import group_by_function

        groups = group_by_function([])

        assert groups == {}


class TestFilterFoundationLayers:
    """Tests for filtering search results to foundation layers only."""

    def test_filters_to_foundation_layers(self) -> None:
        """Only returns axioms from FOUNDATION_LAYERS."""
        from axiom.extractors.semantic_linker import (
            FOUNDATION_LAYERS,
            filter_to_foundation_layers,
        )

        search_results = [
            {"id": "cpp_core_1", "layer": "cpp_core", "content": "test"},
            {"id": "cpp20_lang_1", "layer": "cpp20_language", "content": "test"},
            {"id": "library_1", "layer": "library", "content": "test"},
        ]

        filtered = filter_to_foundation_layers(search_results)

        assert len(filtered) == 2
        assert all(r["layer"] in FOUNDATION_LAYERS for r in filtered)

    def test_excludes_library_layer(self) -> None:
        """Library layer axioms are excluded from candidates."""
        from axiom.extractors.semantic_linker import filter_to_foundation_layers

        search_results = [
            {"id": "lib_1", "layer": "library", "content": "test"},
            {"id": "lib_2", "layer": "ilp_for", "content": "test"},
        ]

        filtered = filter_to_foundation_layers(search_results)

        assert len(filtered) == 0

    def test_empty_input(self) -> None:
        """Empty input returns empty list."""
        from axiom.extractors.semantic_linker import filter_to_foundation_layers

        filtered = filter_to_foundation_layers([])

        assert filtered == []


class TestMergeDependsOn:
    """Tests for merging new links with existing depends_on."""

    def test_merges_with_existing(self) -> None:
        """New links are added to existing depends_on, not replaced."""
        from axiom.extractors.semantic_linker import merge_depends_on

        existing = ["lib_axiom_1", "lib_axiom_2"]
        new_links = ["cpp_core_1", "cpp20_lang_1"]

        merged = merge_depends_on(existing, new_links)

        assert "lib_axiom_1" in merged
        assert "lib_axiom_2" in merged
        assert "cpp_core_1" in merged
        assert "cpp20_lang_1" in merged

    def test_deduplicates_links(self) -> None:
        """Duplicate axiom IDs are removed."""
        from axiom.extractors.semantic_linker import merge_depends_on

        existing = ["axiom_1", "axiom_2"]
        new_links = ["axiom_2", "axiom_3"]

        merged = merge_depends_on(existing, new_links)

        assert len(merged) == 3
        assert merged.count("axiom_2") == 1

    def test_preserves_existing_when_no_new_links(self) -> None:
        """Existing depends_on unchanged if new_links is empty."""
        from axiom.extractors.semantic_linker import merge_depends_on

        existing = ["axiom_1", "axiom_2"]

        merged = merge_depends_on(existing, [])

        assert set(merged) == set(existing)

    def test_handles_none_existing(self) -> None:
        """Handles None as existing depends_on."""
        from axiom.extractors.semantic_linker import merge_depends_on

        merged = merge_depends_on(None, ["axiom_1"])

        assert merged == ["axiom_1"]


class TestParseLLMResponse:
    """Tests for parsing LLM JSON output."""

    def test_parses_valid_json(self) -> None:
        """Parses {"axiom_id": ["dep1", "dep2"]} format."""
        from axiom.extractors.semantic_linker import parse_llm_response

        response = '{"lib_axiom_1": ["cpp_core_1", "cpp20_lang_1"], "lib_axiom_2": ["cpp_core_2"]}'

        parsed = parse_llm_response(response)

        assert parsed == {
            "lib_axiom_1": ["cpp_core_1", "cpp20_lang_1"],
            "lib_axiom_2": ["cpp_core_2"],
        }

    def test_handles_malformed_json(self) -> None:
        """Returns empty dict on parse failure."""
        from axiom.extractors.semantic_linker import parse_llm_response

        response = "This is not valid JSON {broken"

        parsed = parse_llm_response(response)

        assert parsed == {}

    def test_extracts_json_from_markdown(self) -> None:
        """Extracts JSON from markdown code block."""
        from axiom.extractors.semantic_linker import parse_llm_response

        response = """Here is the result:

```json
{"lib_axiom_1": ["cpp_core_1"]}
```

Hope this helps!"""

        parsed = parse_llm_response(response)

        assert parsed == {"lib_axiom_1": ["cpp_core_1"]}

    def test_handles_empty_response(self) -> None:
        """Returns empty dict for empty response."""
        from axiom.extractors.semantic_linker import parse_llm_response

        parsed = parse_llm_response("")

        assert parsed == {}

    def test_handles_json_with_extra_text(self) -> None:
        """Extracts JSON even with surrounding text."""
        from axiom.extractors.semantic_linker import parse_llm_response

        response = 'Some preamble {"lib_axiom_1": ["dep1"]} some postamble'

        parsed = parse_llm_response(response)

        assert parsed == {"lib_axiom_1": ["dep1"]}


class TestValidateCandidateIds:
    """Tests for validating that returned IDs exist in candidates."""

    def test_filters_invalid_axiom_ids(self) -> None:
        """Ignores axiom IDs not in candidates list."""
        from axiom.extractors.semantic_linker import validate_candidate_ids

        links = ["valid_id_1", "invalid_id", "valid_id_2"]
        candidates = [
            {"id": "valid_id_1", "content": "test"},
            {"id": "valid_id_2", "content": "test"},
        ]

        validated = validate_candidate_ids(links, candidates)

        assert validated == ["valid_id_1", "valid_id_2"]

    def test_preserves_order(self) -> None:
        """Maintains order of valid IDs."""
        from axiom.extractors.semantic_linker import validate_candidate_ids

        links = ["id_3", "id_1", "id_2"]
        candidates = [
            {"id": "id_1", "content": "test"},
            {"id": "id_2", "content": "test"},
            {"id": "id_3", "content": "test"},
        ]

        validated = validate_candidate_ids(links, candidates)

        assert validated == ["id_3", "id_1", "id_2"]

    def test_empty_links(self) -> None:
        """Returns empty list for empty links."""
        from axiom.extractors.semantic_linker import validate_candidate_ids

        candidates = [{"id": "id_1", "content": "test"}]

        validated = validate_candidate_ids([], candidates)

        assert validated == []


class TestBuildLinkingPrompt:
    """Tests for building the LLM prompt."""

    def test_includes_function_name(self) -> None:
        """Prompt includes the function name."""
        from axiom.extractors.semantic_linker import build_linking_prompt

        axioms = [create_test_axiom(id="a1", function="MY_MACRO")]
        candidates = [{"id": "cpp_core_1", "content": "test", "layer": "cpp_core"}]

        prompt = build_linking_prompt("MY_MACRO", axioms, candidates)

        assert "MY_MACRO" in prompt

    def test_includes_axiom_content(self) -> None:
        """Prompt includes axiom content."""
        from axiom.extractors.semantic_linker import build_linking_prompt

        axioms = [create_test_axiom(id="a1", content="Lambda captures by reference")]
        candidates = []

        prompt = build_linking_prompt("test", axioms, candidates)

        assert "Lambda captures by reference" in prompt

    def test_includes_candidate_axioms(self) -> None:
        """Prompt includes candidate foundation axioms."""
        from axiom.extractors.semantic_linker import build_linking_prompt

        axioms = [create_test_axiom(id="a1")]
        candidates = [
            {"id": "cpp20_lambda_1", "content": "Lambda expression semantics", "layer": "cpp20_language"},
        ]

        prompt = build_linking_prompt("test", axioms, candidates)

        assert "cpp20_lambda_1" in prompt
        assert "Lambda expression semantics" in prompt

    def test_includes_direct_dependency_principle(self) -> None:
        """Prompt includes the direct dependency principle."""
        from axiom.extractors.semantic_linker import build_linking_prompt

        axioms = [create_test_axiom(id="a1")]

        prompt = build_linking_prompt("test", axioms, [])

        assert "DIRECT" in prompt
        assert "transitive" in prompt.lower()
