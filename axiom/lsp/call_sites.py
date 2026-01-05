# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Call site indexing for axiom display at call sites.

When you hover over `divide(10, 2)`, this module helps find
the axioms for `divide` and its transitive callees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from axiom.models import Axiom

# Axiom lookup takes (callee, signature) and returns axioms
AxiomLookup = Callable[[str, str | None], list["Axiom"]]


@dataclass
class AxiomTreeNode:
    """A node in the axiom tree showing callee axioms hierarchically."""

    function: str
    signature: str | None
    axioms: list[Axiom]
    children: list[AxiomTreeNode] = field(default_factory=list)


class CallSiteIndex:
    """Index of call sites by (file, line) for quick lookup.

    Allows answering: "What functions are called at line N of file F?"
    """

    def __init__(self) -> None:
        """Initialize empty index."""
        # Map: file_path -> {line -> [call_info, ...]}
        self._index: dict[str, dict[int, list[dict]]] = {}
        # Map: callee_name -> [call_info, ...] (for finding what a function calls)
        self._callee_calls: dict[str, list[dict]] = {}

    def add_call_graph(self, file_path: str, call_graph: list[dict]) -> None:
        """Add call graph entries from an extraction.

        Args:
            file_path: Source file path.
            call_graph: List of call entries from axiom-extract JSON.
        """
        if file_path not in self._index:
            self._index[file_path] = {}

        for call in call_graph:
            line = call.get("line")
            if line is None:
                continue

            if line not in self._index[file_path]:
                self._index[file_path][line] = []

            self._index[file_path][line].append(call)

            # Also index by caller for transitive lookup
            caller = call.get("caller")
            if caller:
                if caller not in self._callee_calls:
                    self._callee_calls[caller] = []
                self._callee_calls[caller].append(call)

    def get_callees_at_line(self, file_path: str, line: int) -> list[dict]:
        """Get all callees at a specific line.

        Args:
            file_path: Source file path.
            line: 1-indexed line number.

        Returns:
            List of call info dicts for callees at that line.
        """
        file_index = self._index.get(file_path, {})
        return file_index.get(line, [])

    def get_calls_by_function(self, function_name: str) -> list[dict]:
        """Get all calls made by a function.

        Args:
            function_name: Qualified function name.

        Returns:
            List of call info dicts for calls made by that function.
        """
        return self._callee_calls.get(function_name, [])

    def clear_file(self, file_path: str) -> None:
        """Clear index entries for a file.

        Args:
            file_path: Source file path.
        """
        if file_path in self._index:
            del self._index[file_path]


def build_axiom_tree(
    function_name: str,
    index: CallSiteIndex,
    axiom_lookup: AxiomLookup,
    max_depth: int = 3,
    visited: set[str] | None = None,
    callee_signature: str | None = None,
) -> AxiomTreeNode:
    """Build an axiom tree for a function and its callees.

    Args:
        function_name: Name of the function to build tree for.
        index: CallSiteIndex with call graph data.
        axiom_lookup: Callable that takes (callee, signature) and returns axioms.
        max_depth: Maximum depth to traverse.
        visited: Set of already-visited functions (for cycle detection).
        callee_signature: Optional signature for semantic search context.

    Returns:
        AxiomTreeNode with function's axioms and children.
    """
    if visited is None:
        visited = set()

    # Prevent cycles
    if function_name in visited:
        return AxiomTreeNode(
            function=function_name,
            signature=None,
            axioms=[],
            children=[],
        )

    visited.add(function_name)

    # Get axioms for this function (via semantic search if signature available)
    axioms = axiom_lookup(function_name, callee_signature)

    # Get signature from first axiom if available
    signature = callee_signature
    if not signature and axioms and axioms[0].signature:
        signature = axioms[0].signature

    # Build children if not at max depth
    children: list[AxiomTreeNode] = []
    if max_depth > 0:
        # Find what this function calls
        calls = index.get_calls_by_function(function_name)
        for call in calls:
            callee = call.get("callee")
            child_sig = call.get("callee_signature")
            if callee and callee not in visited:
                child = build_axiom_tree(
                    callee,
                    index,
                    axiom_lookup,
                    max_depth=max_depth - 1,
                    visited=visited.copy(),  # Copy to allow different paths
                    callee_signature=child_sig,
                )
                # Only add if the child has axioms or children
                if child.axioms or child.children:
                    children.append(child)

    return AxiomTreeNode(
        function=function_name,
        signature=signature,
        axioms=axioms,
        children=children,
    )


def get_axioms_for_callee(
    callee: str, axioms_by_function: dict[str, list["Axiom"]]
) -> list["Axiom"]:
    """Get axioms for a callee from a function-to-axioms dict.

    Simple helper for tests and basic lookups. The LSP server uses
    a more sophisticated lookup that also checks tags.

    Args:
        callee: The callee function name.
        axioms_by_function: Dict mapping function names to axiom lists.

    Returns:
        List of axioms for the callee, or empty list.
    """
    return axioms_by_function.get(callee, [])
