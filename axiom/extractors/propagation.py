# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Precondition propagation through call graphs.

When function A calls function B, A inherits B's preconditions
unless A has guards that satisfy them.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from axiom.models import Axiom, AxiomType, SourceLocation

if TYPE_CHECKING:
    pass


def propagate_preconditions(
    axioms: list[Axiom],
    call_graph: list[dict],
) -> list[Axiom]:
    """Propagate callee preconditions to callers.

    For each call A -> B in the call graph:
    - Find all preconditions of B
    - Check if A has guards that satisfy them
    - If not, create propagated preconditions for A

    Args:
        axioms: List of axioms extracted from the codebase.
        call_graph: List of call graph entries with caller/callee info.

    Returns:
        Original axioms plus newly propagated preconditions.
    """
    if not axioms or not call_graph:
        return list(axioms)

    # Build function -> preconditions map
    precond_map: dict[str, list[Axiom]] = defaultdict(list)
    for axiom in axioms:
        if axiom.axiom_type == AxiomType.PRECONDITION and axiom.function:
            precond_map[axiom.function].append(axiom)

    # Build function -> existing guards map (formal specs that are guarded)
    # This would be populated if axioms have guard_expression attribute
    guard_map: dict[str, set[str]] = defaultdict(set)
    for axiom in axioms:
        if (
            axiom.axiom_type == AxiomType.PRECONDITION
            and axiom.function
            and hasattr(axiom, "guard_expression")
            and axiom.guard_expression
        ):
            guard_map[axiom.function].add(axiom.formal_spec)

    propagated: list[Axiom] = []
    seen: set[str] = set()

    for call in call_graph:
        caller = call.get("caller")
        callee = call.get("callee")

        # Skip malformed entries
        if not caller or not callee:
            continue

        for precond in precond_map.get(callee, []):
            # Generate propagated axiom ID
            precond_suffix = precond.id.split(".")[-1]
            prop_id = f"{caller}.propagated.{precond_suffix}"

            # Skip if we've already propagated this
            if prop_id in seen:
                continue

            # Skip if caller has a guard that satisfies this precondition
            if precond.formal_spec in guard_map.get(caller, set()):
                continue

            # Create propagated axiom
            new_axiom = Axiom(
                id=prop_id,
                content=f"Inherited from {callee}: {precond.content}",
                formal_spec=precond.formal_spec,
                function=caller,
                source=SourceLocation(
                    file=precond.source.file if precond.source else "unknown",
                    module=caller,
                ),
                layer="user_library",
                axiom_type=AxiomType.PRECONDITION,
                confidence=0.85,  # Slightly lower confidence for propagated
                depends_on=[precond.id],
            )
            propagated.append(new_axiom)
            seen.add(prop_id)

    return list(axioms) + propagated
