# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Semantic linking of library axioms to foundation axioms.

This module provides LLM-assisted linking of library axioms to their
foundation dependencies based on semantic analysis, not just type signatures.

Unlike link_depends_on.py which extracts types from signatures via regex,
this module uses:
1. Semantic search to find candidate foundation axioms
2. LLM analysis to identify direct dependencies (not transitive)
3. Merge with existing depends_on (add to, not replace)
"""

import json
import re
from collections import defaultdict

from axiom.models import Axiom

# Foundation layers that library axioms can depend on
FOUNDATION_LAYERS = [
    "c11_core",
    "c11_stdlib",
    "cpp_core",
    "cpp_stdlib",
    "cpp20_language",
    "cpp20_stdlib",
]

# System prompt for the LLM linking task
LINKING_SYSTEM_PROMPT = """You are an expert at analyzing C++ code semantics.
Your task is to identify DIRECT dependencies between library axioms and C++ language foundation axioms.

CRITICAL: Only identify DIRECT dependencies - features the code explicitly uses in its implementation.
Do NOT include transitive dependencies (features used by the features it uses).

Example:
- If code uses a lambda → link to lambda axioms (DIRECT)
- If the lambda captures by reference → that's the lambda axiom's responsibility, not this code's (TRANSITIVE)

Output ONLY valid JSON in this format:
{"axiom_id_1": ["foundation_id_1", "foundation_id_2"], "axiom_id_2": [...]}
"""


def group_by_function(axioms: list[Axiom]) -> dict[str, list[Axiom]]:
    """Group axioms by function name for batched processing.

    Args:
        axioms: List of axioms to group.

    Returns:
        Dict mapping function name to list of axioms.
        Axioms with None function go to 'ungrouped'.
    """
    if not axioms:
        return {}

    groups: dict[str, list[Axiom]] = defaultdict(list)
    for axiom in axioms:
        key = axiom.function or "ungrouped"
        groups[key].append(axiom)

    return dict(groups)


def filter_to_foundation_layers(search_results: list[dict]) -> list[dict]:
    """Filter search results to only include foundation layer axioms.

    Args:
        search_results: Raw search results from LanceDB.

    Returns:
        Filtered list containing only foundation layer axioms.
    """
    return [r for r in search_results if r.get("layer") in FOUNDATION_LAYERS]


def search_foundations(
    query: str,
    lance,
    limit: int = 30,
) -> list[dict]:
    """Search for foundation axioms, excluding library layer.

    Since LanceDB semantic search returns the most similar axioms
    (which may all be from the library layer), we need to fetch
    extra results and filter.

    Args:
        query: Search query text.
        lance: LanceDB loader instance.
        limit: Maximum foundation axioms to return.

    Returns:
        List of foundation layer axiom dicts.
    """
    # Fetch more results to account for library axioms being filtered out
    # Library axioms often dominate similarity results
    raw_limit = limit * 10
    results = lance.search(query, limit=raw_limit)
    filtered = filter_to_foundation_layers(results)
    return filtered[:limit]


def merge_depends_on(
    existing: list[str] | None,
    new_links: list[str],
) -> list[str]:
    """Merge new dependency links with existing ones.

    Args:
        existing: Current depends_on list (may be None).
        new_links: New links to add.

    Returns:
        Merged list with duplicates removed.
    """
    existing_set = set(existing or [])
    new_set = set(new_links)
    merged = existing_set | new_set
    return list(merged)


def parse_llm_response(response: str) -> dict[str, list[str]]:
    """Parse LLM response to extract axiom ID to dependency mapping.

    Handles various response formats:
    - Pure JSON
    - JSON in markdown code blocks
    - JSON with surrounding text

    Args:
        response: Raw LLM response text.

    Returns:
        Dict mapping axiom IDs to lists of dependency IDs.
        Empty dict on parse failure.
    """
    if not response:
        return {}

    # Try to extract JSON from markdown code blocks first
    code_block_match = re.search(r"```(?:json)?\s*\n?({.*?})\s*\n?```", response, re.DOTALL)
    if code_block_match:
        json_str = code_block_match.group(1)
    else:
        # Try to find JSON object in the response
        json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = response

    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, dict):
            # Validate structure: all values should be lists
            result = {}
            for key, value in parsed.items():
                if isinstance(value, list):
                    result[key] = value
            return result
        return {}
    except json.JSONDecodeError:
        return {}


def validate_candidate_ids(
    links: list[str],
    candidates: list[dict],
) -> list[str]:
    """Validate that returned IDs exist in the candidates list.

    Args:
        links: List of axiom IDs from LLM response.
        candidates: List of candidate axiom dicts with 'id' field.

    Returns:
        Filtered list containing only valid IDs.
    """
    valid_ids = {c["id"] for c in candidates}
    return [link for link in links if link in valid_ids]


def build_linking_prompt(
    function_name: str,
    axioms: list[Axiom],
    candidates: list[dict],
) -> str:
    """Build the prompt for LLM linking analysis.

    Args:
        function_name: Name of the function/macro being analyzed.
        axioms: Library axioms to link.
        candidates: Candidate foundation axioms from semantic search.

    Returns:
        Formatted prompt string.
    """
    # Format library axioms
    axiom_lines = []
    for axiom in axioms:
        axiom_lines.append(f"ID: {axiom.id}")
        axiom_lines.append(f"Content: {axiom.content}")
        if axiom.formal_spec:
            axiom_lines.append(f"Formal spec: {axiom.formal_spec}")
        if axiom.signature:
            axiom_lines.append(f"Signature: {axiom.signature}")
        axiom_lines.append("")

    axiom_section = "\n".join(axiom_lines)

    # Format candidate foundation axioms
    candidate_lines = []
    for c in candidates:
        candidate_lines.append(f"ID: {c.get('id', 'unknown')}")
        candidate_lines.append(f"Layer: {c.get('layer', 'unknown')}")
        candidate_lines.append(f"Content: {c.get('content', '')}")
        candidate_lines.append("")

    candidate_section = "\n".join(candidate_lines) if candidate_lines else "(no candidates found)"

    return f"""You are analyzing axioms for the macro/function "{function_name}" to find its DIRECT C++ language dependencies.

IMPORTANT: Only link to axioms that this code DIRECTLY uses in its implementation.
Do NOT link to transitive dependencies (things used by things it uses).

Direct dependency principle:
- If code uses feature A, and A uses feature B → only link to A, not B
- B is A's responsibility to link to, not this code's

## Axioms for {function_name}
{axiom_section}

## Foundation Axioms (potential direct dependencies)
{candidate_section}

## Task
Which foundation axioms does this macro/function DIRECTLY depend on?
Only include axioms for language features explicitly used in the implementation.

Return JSON mapping each library axiom ID to its direct foundation dependencies:
{{"lib_axiom_id_1": ["foundation_id_1", ...], "lib_axiom_id_2": [...], ...}}"""


def link_axiom_with_llm(
    axiom: Axiom,
    candidates: list[dict],
    model: str = "sonnet",
) -> list[str]:
    """Use LLM to identify direct dependencies for a single axiom.

    Args:
        axiom: The axiom to link.
        candidates: Candidate foundation axioms from semantic search.
        model: Model to use ("sonnet", "opus", "haiku").

    Returns:
        List of foundation axiom IDs that are direct dependencies.
    """
    import subprocess

    if not candidates:
        return []

    # Build prompt for this single axiom
    prompt = build_linking_prompt(
        axiom.function or axiom.id,
        [axiom],
        candidates,
    )

    # Call Claude CLI
    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--model",
                model,
                "--dangerously-skip-permissions",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            return []

        # Parse response
        link_map = parse_llm_response(result.stdout)
        links = link_map.get(axiom.id, [])

        # Validate that returned IDs exist in candidates
        validated = validate_candidate_ids(links, candidates)
        return validated

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return []


def link_axioms_batch_with_llm(
    axioms: list[Axiom],
    candidates: list[dict],
    model: str = "sonnet",
) -> dict[str, list[str]]:
    """Use LLM to identify direct dependencies for multiple axioms from the same function.

    This batches axioms from the same function into a single LLM call.

    Args:
        axioms: List of axioms to link (should be from same function).
        candidates: Candidate foundation axioms from semantic search.
        model: Model to use ("sonnet", "opus", "haiku").

    Returns:
        Dict mapping axiom IDs to their direct dependency IDs.
    """
    import subprocess

    if not candidates or not axioms:
        return {}

    # Build prompt for all axioms
    function_name = axioms[0].function or "ungrouped"
    prompt = build_linking_prompt(
        function_name,
        axioms,
        candidates,
    )

    # Call Claude CLI
    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--model",
                model,
                "--dangerously-skip-permissions",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=120,  # Longer timeout for batch
        )

        if result.returncode != 0:
            return {}

        # Parse response
        link_map = parse_llm_response(result.stdout)

        # Validate that returned IDs exist in candidates
        validated_map = {}
        for axiom_id, links in link_map.items():
            validated_map[axiom_id] = validate_candidate_ids(links, candidates)

        return validated_map

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return {}
