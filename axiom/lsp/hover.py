# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Format axioms as markdown hover content.

Generates rich markdown hover content showing:
- Function signature
- All axioms (preconditions, postconditions, etc.)
- Formal specifications
- Confidence levels
- Layer and axiom IDs
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from axiom.lsp.call_sites import AxiomTreeNode
    from axiom.models import Axiom


def format_hover(axioms: list[Axiom]) -> str:
    """Format axioms as markdown hover content.

    Args:
        axioms: List of axioms to format.

    Returns:
        Markdown formatted string for hover display.
    """
    if not axioms:
        return ""

    # Group axioms by function
    by_function: dict[str, list[Axiom]] = defaultdict(list)
    for axiom in axioms:
        key = axiom.function or "unknown"
        by_function[key].append(axiom)

    parts: list[str] = []

    for function, func_axioms in by_function.items():
        # Get signature from first axiom that has it
        signature = next(
            (a.signature for a in func_axioms if a.signature),
            None,
        )

        # Header with function name and signature
        if signature:
            parts.append(f"### {signature}")
        else:
            parts.append(f"### {function}")

        parts.append("")

        # Group axioms by type
        by_type: dict[str, list[Axiom]] = defaultdict(list)
        for axiom in func_axioms:
            type_name = axiom.axiom_type.value if axiom.axiom_type else "other"
            by_type[type_name].append(axiom)

        # Display in order: precondition, postcondition, invariant, etc.
        type_order = [
            "precondition",
            "postcondition",
            "invariant",
            "exception",
            "effect",
            "constraint",
            "anti_pattern",
            "complexity",
            "other",
        ]

        for type_name in type_order:
            if type_name not in by_type:
                continue

            for axiom in by_type[type_name]:
                # Format type name nicely
                display_type = type_name.replace("_", " ").title()
                parts.append(f"**{display_type}**: {axiom.content}")

                # Formal spec if available
                if axiom.formal_spec:
                    parts.append(f"- Formal: `{axiom.formal_spec}`")

                # Confidence as percentage
                confidence_pct = int(axiom.confidence * 100)
                parts.append(f"- Confidence: {confidence_pct}%")

                parts.append("")

        # Footer with layer and axiom IDs
        layers = {a.layer for a in func_axioms}
        layer_str = ", ".join(sorted(layers))
        axiom_ids = [a.id for a in func_axioms]
        ids_str = ", ".join(axiom_ids)

        parts.append("---")
        parts.append(f"*Source: {layer_str} layer | [{ids_str}]*")
        parts.append("")

    return "\n".join(parts).strip()


def format_axiom_tree(tree: AxiomTreeNode, depth: int = 0) -> str:
    """Format an axiom tree as markdown for call site hover.

    Shows the called function's axioms and recursively shows
    axioms from functions it calls.

    Args:
        tree: AxiomTreeNode with function axioms and children.
        depth: Current tree depth (for indentation).

    Returns:
        Markdown formatted string for hover display.
    """
    parts: list[str] = []
    indent = "  " * depth

    # Header with function name/signature
    if depth == 0:
        header = tree.signature or tree.function
        parts.append(f"**Calling** `{header}`")
        parts.append("")
    else:
        prefix = "└─ Calls" if depth > 0 else "Calls"
        header = tree.signature or tree.function
        parts.append(f"{indent}{prefix} `{header}`")

    # Show axioms for this function
    for axiom in tree.axioms:
        type_name = axiom.axiom_type.value.upper() if axiom.axiom_type else "AXIOM"
        parts.append(f"{indent}  **{type_name}**: {axiom.content}")

    # Recursively show children
    for child in tree.children:
        child_text = format_axiom_tree(child, depth + 1)
        parts.append(child_text)

    return "\n".join(parts)
