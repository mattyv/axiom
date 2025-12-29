# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""K dependency extraction for axiom-to-axiom linking.

This module provides two-pass extraction from K semantics:
1. Extract all axioms and build function->axiom_id index
2. Parse RHS of each rule to find function calls and resolve depends_on
"""

import re
from collections import defaultdict
from pathlib import Path

from axiom.extractors.k_semantics import KSemanticsExtractor
from axiom.models import Axiom

# K primitive functions to exclude from dependency tracking
# These are K framework internals, not semantic C/C++ functions
K_PRIMITIVES: set[str] = {
    # Type wrappers
    "tv",
    "utype",
    "type",
    "ut",
    "t",
    # Location primitives
    "lnew",
    "loc",
    "base",
    "bnew",
    "obj",
    # Collections
    "list",
    "Map",
    "Set",
    "List",
    "ListItem",
    "SetItem",
    # Values
    "reval",
    "lval",
    "voidVal",
    # Memory
    "piece",
    "uninit",
    "makeArray",
    "fillArray",
    # Control flow
    "Computation",
    "Call",
    # Provenance
    "addProv",
    "fromArray",
    # Configuration
    "size",
    "max",
    "min",
    # Misc K internals
    "stripStorageSpecifiers",
    "dynamicType",
    "pointerType",
    "arrayType",
    "lengthString",
    "isNull",
    "isNativeLoc",
    "NullPointer",
}

# Regex to find function calls: word followed by (
# Excludes patterns like +Int, *Int which are infix operators
FUNCTION_CALL_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")

# Regex to extract function name from builtin("funcName", ...)
BUILTIN_PATTERN = re.compile(r'builtin\s*\(\s*"([^"]+)"')


def extract_function_calls(rhs: str) -> list[str]:
    """Extract function names from K rule RHS.

    Args:
        rhs: The right-hand side of a K rule.

    Returns:
        List of unique function names called (excluding K primitives).
    """
    if not rhs:
        return []

    calls: set[str] = set()

    # Find all function call patterns: name(
    for match in FUNCTION_CALL_PATTERN.finditer(rhs):
        name = match.group(1)
        if name not in K_PRIMITIVES:
            calls.add(name)

    # Also extract function names from builtin("name", ...) patterns
    for match in BUILTIN_PATTERN.finditer(rhs):
        name = match.group(1)
        calls.add(name)

    return sorted(calls)


def build_function_index(axioms: list[Axiom]) -> dict[str, list[str]]:
    """Build function_name -> [axiom_ids] mapping.

    Args:
        axioms: List of axioms to index.

    Returns:
        Dictionary mapping function names to lists of axiom IDs.
    """
    index: dict[str, list[str]] = defaultdict(list)

    for axiom in axioms:
        if axiom.function:
            index[axiom.function].append(axiom.id)

    return dict(index)


def resolve_depends_on(calls: list[str], index: dict[str, list[str]]) -> list[str]:
    """Resolve function calls to axiom IDs.

    Args:
        calls: List of function names called.
        index: Function name to axiom ID mapping.

    Returns:
        List of axiom IDs that the caller depends on.
    """
    deps: list[str] = []

    for func in calls:
        if func in index:
            deps.extend(index[func])

    return deps


class KDependencyExtractor:
    """Extract K axioms with dependency resolution.

    Uses a two-pass approach:
    1. Extract all axioms from K files
    2. Build function->axiom index and resolve depends_on for each axiom
    """

    def __init__(self, semantics_root: Path) -> None:
        """Initialize extractor.

        Args:
            semantics_root: Root directory of K semantics (e.g., semantics/c).
        """
        self.semantics_root = Path(semantics_root)

    def extract_with_dependencies(
        self, base_index: dict[str, list[str]] | None = None
    ) -> list[Axiom]:
        """Extract all axioms with resolved depends_on.

        Args:
            base_index: Optional function index from a previous layer (e.g., c11_core).
                       This enables cross-layer dependency resolution.

        Returns:
            List of axioms with depends_on populated.
        """
        # Pass 1: Extract all axioms and collect RHS for each
        extractor = KSemanticsExtractor(self.semantics_root)
        axioms = extractor.extract_all()

        # Build function index (merged with base_index if provided)
        index = build_function_index(axioms)
        if base_index:
            # Merge base_index into current index (base takes precedence for shared keys)
            for func, axiom_ids in base_index.items():
                if func in index:
                    index[func].extend(axiom_ids)
                else:
                    index[func] = list(axiom_ids)

        # Pass 2: For each axiom, parse RHS and resolve depends_on
        # We need to re-parse to get the RHS
        axiom_rhs_map = self._build_axiom_rhs_map(extractor)

        for axiom in axioms:
            rhs = axiom_rhs_map.get(axiom.id, "")
            calls = extract_function_calls(rhs)
            deps = resolve_depends_on(calls, index)

            # Remove self-reference
            deps = [d for d in deps if d != axiom.id]

            axiom.depends_on = deps

        return axioms

    def get_function_index(self) -> dict[str, list[str]]:
        """Extract axioms and return the function index for cross-layer use.

        Returns:
            Dictionary mapping function names to axiom IDs.
        """
        extractor = KSemanticsExtractor(self.semantics_root)
        axioms = extractor.extract_all()
        return build_function_index(axioms)

    def _build_axiom_rhs_map(self, extractor: KSemanticsExtractor) -> dict[str, str]:
        """Build mapping from axiom ID to rule RHS.

        Args:
            extractor: The K semantics extractor instance.

        Returns:
            Dictionary mapping axiom ID to rule RHS string.
        """
        from axiom.extractors.content_generator import ContentGenerator

        rhs_map: dict[str, str] = {}
        generator = ContentGenerator()

        for k_file in self.semantics_root.rglob("*.k"):
            try:
                rules = extractor.parse_file(k_file)
                for rule in rules:
                    # Generate the axiom ID the same way extract_axioms_from_file does
                    if rule.requires and not rule.error_marker:
                        axiom_id = generator.generate_axiom_id(
                            module=rule.module,
                            operation=extractor._infer_operation(rule.lhs),
                            formal_spec=rule.requires,
                        )
                        rhs_map[axiom_id] = rule.rhs

                    elif rule.standard_ref and rule.function and not rule.error_marker:
                        axiom_id = generator.generate_axiom_id(
                            module=rule.module,
                            operation=rule.function,
                            formal_spec=rule.standard_ref.text[:100]
                            if rule.standard_ref.text
                            else "",
                        )
                        rhs_map[axiom_id] = rule.rhs

                    elif rule.error_marker and rule.function:
                        axiom_id = generator.generate_axiom_id(
                            module=rule.module,
                            operation=rule.function,
                            formal_spec=rule.error_marker.message,
                        )
                        rhs_map[axiom_id] = rule.rhs

                    # Handle function rules without requires/standard_ref/error
                    elif rule.function and not rule.error_marker:
                        axiom_id = generator.generate_axiom_id(
                            module=rule.module,
                            operation=rule.function,
                            formal_spec=rule.rhs[:100] if rule.rhs else "",
                        )
                        rhs_map[axiom_id] = rule.rhs

            except Exception:
                # Skip files that fail to parse
                pass

        return rhs_map
