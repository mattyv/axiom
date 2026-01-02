# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""LLM-based axiom enrichment.

This module enriches axioms extracted from code with:
- on_violation descriptions
- Inferred EFFECT and POSTCONDITION axioms
- Enhanced semantic content

Uses batching for efficient LLM calls.
"""

from __future__ import annotations

import logging
import subprocess
import tomllib
from collections import defaultdict
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from axiom.models import Axiom

logger = logging.getLogger(__name__)

# Enrichment configuration
BATCH_SIZE = 15  # Functions per LLM call
DEFAULT_MODEL = "sonnet"


def group_by_function(axioms: list[Axiom]) -> dict[str, list[Axiom]]:
    """Group axioms by their function for context coherence."""
    groups: dict[str, list[Axiom]] = defaultdict(list)
    for axiom in axioms:
        key = axiom.function or "__global__"
        groups[key].append(axiom)
    return dict(groups)


def chunk_functions(
    groups: dict[str, list[Axiom]], max_functions: int = BATCH_SIZE
) -> Iterator[dict[str, list[Axiom]]]:
    """Yield successive chunks of function groups."""
    items = list(groups.items())
    for i in range(0, len(items), max_functions):
        yield dict(items[i : i + max_functions])


def build_enrichment_prompt(axioms: list[Axiom]) -> str:
    """Build prompt for axiom enrichment.

    Asks the LLM to:
    1. Add on_violation descriptions
    2. Infer missing postconditions from return types
    3. Enhance semantic content
    """
    axiom_lines = []
    for a in axioms:
        axiom_lines.append(
            f"""[[axioms]]
id = "{a.id}"
content = "{a.content}"
formal_spec = "{a.formal_spec or ''}"
axiom_type = "{a.axiom_type.name if a.axiom_type else 'UNKNOWN'}"
function = "{a.function or ''}"
"""
        )

    return f"""You are enriching axioms extracted from C++ code.

For each axiom, add an on_violation field describing what error or undefined behavior
occurs when the axiom is violated. Be specific and concise.

For PRECONDITION axioms, describe the runtime error or UB.
For EFFECT axioms, describe what state change occurs.
For CONSTRAINT axioms, describe what compilation or runtime issue arises.

If you can infer a POSTCONDITION from the function signature or axioms,
add it as a new axiom with axiom_type = "POSTCONDITION".

Return ONLY valid TOML with enriched axioms:

{chr(10).join(axiom_lines)}

Add 'on_violation = "..."' to each axiom. Keep all original fields.
If inferring new axioms, use a new id like "function.inferred.postcond"."""


def call_llm(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Call Claude CLI for enrichment."""
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
            timeout=120,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.warning("LLM call timed out")
        return ""
    except FileNotFoundError:
        logger.warning("Claude CLI not found")
        return ""


def parse_enrichment_response(response: str, originals: list[Axiom]) -> list[Axiom]:
    """Parse TOML response and update axioms with enrichment.

    Handles:
    - Adding on_violation to existing axioms
    - Updating content/formal_spec if improved
    - Adding new inferred axioms
    """
    if not response or not response.strip():
        return list(originals)

    try:
        # Extract TOML block if wrapped in markdown
        if "```toml" in response:
            start = response.index("```toml") + 7
            end = response.index("```", start)
            response = response[start:end]
        elif "```" in response:
            # Generic code block
            start = response.index("```") + 3
            # Skip language identifier if present
            newline_idx = response.find("\n", start)
            if newline_idx != -1:
                start = newline_idx + 1
            end = response.index("```", start)
            response = response[start:end]

        data = tomllib.loads(response)
        enriched_map = {a["id"]: a for a in data.get("axioms", [])}

        result = []
        for orig in originals:
            if orig.id in enriched_map:
                enriched = enriched_map[orig.id]
                # Update on_violation
                if "on_violation" in enriched:
                    orig.on_violation = enriched["on_violation"]
                # Optionally update content if improved
                if "content" in enriched and enriched["content"] != orig.content:
                    # Keep original unless explicitly improved
                    pass
            result.append(orig)

        # Add any new inferred axioms
        original_ids = {a.id for a in originals}
        for axiom_data in data.get("axioms", []):
            if axiom_data.get("id") not in original_ids:
                # New inferred axiom
                from axiom.models import AxiomType

                new_axiom = Axiom(
                    id=axiom_data.get("id", ""),
                    content=axiom_data.get("content", ""),
                    formal_spec=axiom_data.get("formal_spec", ""),
                    axiom_type=AxiomType[axiom_data.get("axiom_type", "POSTCONDITION")],
                    confidence=0.85,  # Lower confidence for inferred
                    function=axiom_data.get("function", ""),
                    on_violation=axiom_data.get("on_violation", ""),
                )
                result.append(new_axiom)

        return result
    except Exception as e:
        logger.warning(f"Failed to parse LLM response: {e}")
        return list(originals)


def enrich_axioms(
    axioms: list[Axiom],
    use_llm: bool = True,
    model: str = DEFAULT_MODEL,
) -> list[Axiom]:
    """Enrich axioms with LLM-generated on_violation and inferred axioms.

    Args:
        axioms: List of axioms to enrich.
        use_llm: Whether to use LLM for enrichment.
        model: Model to use for LLM calls.

    Returns:
        Enriched axioms with on_violation and any new inferred axioms.
    """
    if not use_llm:
        return list(axioms)

    if not axioms:
        return []

    # Group by function for context coherence
    groups = group_by_function(axioms)

    logger.info(f"Enriching {len(axioms)} axioms across {len(groups)} functions...")

    enriched_all = []
    for chunk in chunk_functions(groups, BATCH_SIZE):
        # Flatten chunk to list
        chunk_axioms = []
        for func_axioms in chunk.values():
            chunk_axioms.extend(func_axioms)

        prompt = build_enrichment_prompt(chunk_axioms)
        response = call_llm(prompt, model)

        if response:
            chunk_enriched = parse_enrichment_response(response, chunk_axioms)
            enriched_all.extend(chunk_enriched)
        else:
            # Keep originals if LLM fails
            enriched_all.extend(chunk_axioms)

    logger.info(f"Enrichment complete: {len(enriched_all)} axioms")
    return enriched_all
