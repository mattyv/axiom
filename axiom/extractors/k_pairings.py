# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Extract function pairings from K semantics shared cell access.

K semantics tracks resource state through configuration cells. Functions that
share access to the same cell (one writing, one removing) form a pairing
relationship.

Example from stdlib.k:
- malloc WRITES to <malloced>: .Map => obj(...) |-> Sz
- free REMOVES from <malloced>: Base |-> _ => .Map

These functions are paired via the shared <malloced> cell.
"""

import re
from typing import TYPE_CHECKING

from axiom.models.pairing import Pairing

if TYPE_CHECKING:
    from axiom.extractors.k_semantics import ParsedRule

# Regex patterns for cell access

# Matches: <cellname>... .Map => X ...</cellname>  (writing to cell)
CELL_WRITE_PATTERN = re.compile(
    r"<(\w+)>[^<]*\.Map\s*=>\s*[^<]+</\1>",
    re.DOTALL,
)

# Matches: <cellname>... X |-> _ => .Map ...</cellname>  (removing from cell)
# Uses [^|]+ to match any content before |-> (including parentheses)
CELL_REMOVE_PATTERN = re.compile(
    r"<(\w+)>[^<]*?[^|]+\|->\s*_?\s*=>\s*\.Map[^<]*</\1>",
    re.DOTALL,
)

# Matches: <cellname>... (X => Y) |-> ...</cellname>  (modifying cell)
CELL_MODIFY_PATTERN = re.compile(
    r"<(\w+)>[^<]*\([^)]+\s*=>\s*[^)]+\)[^<]*\|->[^<]*</\1>",
    re.DOTALL,
)

# Matches: <cellname>... ...</cellname> for any cell access
CELL_ACCESS_PATTERN = re.compile(
    r"<(\w+)>[^<]*</\1>",
    re.DOTALL,
)

# Naming patterns for heuristic pairing detection (C-style)
NAMING_PATTERNS: list[tuple[str, str]] = [
    (r"(.+)_begin$", r"\1_end"),
    (r"(.+)_start$", r"\1_stop"),
    (r"(.+)_open$", r"\1_close"),
    (r"(.+)_lock$", r"\1_unlock"),
    (r"(.+)_init$", r"\1_destroy"),
    (r"(.+)_init$", r"\1_cleanup"),
    (r"(.+)_init$", r"\1_free"),
    (r"(.+)_init$", r"\1_finish"),
    (r"(.+)_acquire$", r"\1_release"),
    (r"^create_(.+)$", r"destroy_\1"),
    (r"^alloc_(.+)$", r"free_\1"),
    (r"^new_(.+)$", r"delete_\1"),
]

# C++ stdlib specific pairings (not detectable by naming patterns alone)
# These are semantic pairings based on C++ standard library design
CPP_STDLIB_PAIRINGS: list[tuple[str, str, str]] = [
    # Constructor/destructor pairs
    ("std::any::any", "std::any::~any", "RAII: constructor/destructor"),
    ("std::variant::variant", "std::variant::~variant", "RAII: constructor/destructor"),
    ("std::shared_ptr::shared_ptr", "std::shared_ptr::~shared_ptr", "RAII: constructor/destructor"),
    ("std::weak_ptr::weak_ptr", "std::weak_ptr::~weak_ptr", "RAII: constructor/destructor"),
    ("std::condition_variable", "std::condition_variable::~condition_variable", "RAII: constructor/destructor"),
    ("std::condition_variable_any", "std::condition_variable_any::~condition_variable_any", "RAII: constructor/destructor"),
    # Acquire/release pairs
    ("std::weak_ptr::lock", "std::weak_ptr::reset", "acquire/release: lock creates shared_ptr, reset releases"),
    # Container operation pairs
    ("push_back", "pop_back", "container: add/remove from back"),
    ("push_front", "pop_front", "container: add/remove from front"),
    ("emplace_back", "pop_back", "container: add/remove from back"),
    ("emplace_front", "pop_front", "container: add/remove from front"),
    # Range pairs
    ("ranges::begin", "ranges::end", "range: begin/end iterators"),
    ("ranges::rbegin", "ranges::rend", "range: reverse begin/end iterators"),
    ("ranges::cbegin", "ranges::cend", "range: const begin/end iterators"),
    ("ranges::crbegin", "ranges::crend", "range: const reverse begin/end iterators"),
    # Memory management
    ("std::make_shared", "std::shared_ptr::~shared_ptr", "memory: allocation/deallocation"),
    ("std::allocate_shared", "std::shared_ptr::~shared_ptr", "memory: allocation/deallocation"),
]


def extract_cell_patterns(text: str) -> list[tuple[str, str]]:
    """Extract cell access patterns from K rule text.

    Analyzes the RHS of a K rule to determine which cells are accessed
    and how (write, remove, modify, read).

    Args:
        text: K rule text (typically the RHS or full rule).

    Returns:
        List of (cell_name, access_type) tuples where access_type is one of:
        - "write": Adding to cell (.Map => X)
        - "remove": Removing from cell (X => .Map)
        - "modify": Modifying cell contents ((X => Y) |->)
        - "read": Reading/checking cell (in_keys, etc.)
    """
    patterns: list[tuple[str, str]] = []
    seen_cells: set[str] = set()

    # Check for write pattern: .Map => X
    for match in CELL_WRITE_PATTERN.finditer(text):
        cell_name = match.group(1)
        if cell_name not in seen_cells:
            patterns.append((cell_name, "write"))
            seen_cells.add(cell_name)

    # Check for remove pattern: X |-> _ => .Map
    for match in CELL_REMOVE_PATTERN.finditer(text):
        cell_name = match.group(1)
        if cell_name not in seen_cells:
            patterns.append((cell_name, "remove"))
            seen_cells.add(cell_name)

    # Check for modify pattern: (X => Y) |->
    for match in CELL_MODIFY_PATTERN.finditer(text):
        cell_name = match.group(1)
        if cell_name not in seen_cells:
            patterns.append((cell_name, "modify"))
            seen_cells.add(cell_name)

    # Check for general cell access (read)
    for match in CELL_ACCESS_PATTERN.finditer(text):
        cell_name = match.group(1)
        if cell_name not in seen_cells:
            patterns.append((cell_name, "read"))
            seen_cells.add(cell_name)

    return patterns


def extract_pairings_from_rules(rules: list["ParsedRule"]) -> list[Pairing]:
    """Extract pairings from K rules based on shared cell access.

    Functions that write to a cell are paired with functions that remove from
    the same cell.

    Args:
        rules: List of parsed K rules.

    Returns:
        List of Pairing objects representing opener/closer relationships.
    """
    # Collect cell writers and removers by cell name
    cell_writers: dict[str, list[str]] = {}  # cell -> [function names]
    cell_removers: dict[str, list[str]] = {}  # cell -> [function names]
    cell_modifiers: dict[str, list[str]] = {}  # cell -> [function names]

    for rule in rules:
        if not rule.function:
            continue

        # Combine LHS and RHS for pattern matching
        text = f"{rule.lhs or ''} {rule.rhs or ''}"
        patterns = extract_cell_patterns(text)

        for cell_name, access_type in patterns:
            # Skip internal K cells
            if cell_name in {"k", "K", "T", "thread", "threads"}:
                continue

            if access_type == "write":
                cell_writers.setdefault(cell_name, []).append(rule.function)
            elif access_type == "remove":
                cell_removers.setdefault(cell_name, []).append(rule.function)
            elif access_type == "modify":
                cell_modifiers.setdefault(cell_name, []).append(rule.function)

    # Generate pairings: writers -> removers via shared cell
    pairings: list[Pairing] = []
    seen_pairs: set[tuple[str, str]] = set()

    for cell_name, writers in cell_writers.items():
        removers = cell_removers.get(cell_name, [])
        modifiers = cell_modifiers.get(cell_name, [])

        # Writers paired with removers
        for writer in writers:
            for remover in removers:
                if writer == remover:
                    continue
                pair_key = (writer, remover)
                if pair_key not in seen_pairs:
                    pairings.append(
                        Pairing(
                            opener_id=f"axiom_for_{writer}",
                            closer_id=f"axiom_for_{remover}",
                            required=True,
                            source="k_semantics",
                            confidence=1.0,
                            cell=cell_name,
                            evidence=f"Shared cell <{cell_name}>: {writer} writes, {remover} removes",
                        )
                    )
                    seen_pairs.add(pair_key)

        # Writers paired with modifiers (modifiers can close)
        for writer in writers:
            for modifier in modifiers:
                if writer == modifier:
                    continue
                pair_key = (writer, modifier)
                if pair_key not in seen_pairs:
                    pairings.append(
                        Pairing(
                            opener_id=f"axiom_for_{writer}",
                            closer_id=f"axiom_for_{modifier}",
                            required=False,  # Modifiers don't necessarily close
                            source="k_semantics",
                            confidence=0.8,
                            cell=cell_name,
                            evidence=f"Shared cell <{cell_name}>: {writer} writes, {modifier} modifies",
                        )
                    )
                    seen_pairs.add(pair_key)

        # Modifiers paired with removers
        for modifier in modifiers:
            for remover in removers:
                if modifier == remover:
                    continue
                pair_key = (modifier, remover)
                if pair_key not in seen_pairs:
                    pairings.append(
                        Pairing(
                            opener_id=f"axiom_for_{modifier}",
                            closer_id=f"axiom_for_{remover}",
                            required=False,
                            source="k_semantics",
                            confidence=0.8,
                            cell=cell_name,
                            evidence=f"Shared cell <{cell_name}>: {modifier} modifies, {remover} removes",
                        )
                    )
                    seen_pairs.add(pair_key)

    return pairings


def detect_naming_pairings(function_names: list[str]) -> list[Pairing]:
    """Detect pairings based on function naming conventions.

    Looks for common patterns like:
    - X_begin / X_end
    - X_lock / X_unlock
    - X_init / X_destroy
    - create_X / destroy_X

    Args:
        function_names: List of function names to analyze.

    Returns:
        List of Pairing objects with lower confidence (heuristic-based).
    """
    pairings: list[Pairing] = []
    func_set = set(function_names)

    for func in function_names:
        for opener_pattern, closer_pattern in NAMING_PATTERNS:
            match = re.match(opener_pattern, func)
            if match:
                # Build the expected closer name
                base = match.group(1)
                expected_closer = re.sub(r"\\1", base, closer_pattern)

                if expected_closer in func_set:
                    pairings.append(
                        Pairing(
                            opener_id=f"axiom_for_{func}",
                            closer_id=f"axiom_for_{expected_closer}",
                            required=True,
                            source="naming_heuristic",
                            confidence=0.7,
                            evidence=f"Naming pattern: {func} -> {expected_closer}",
                        )
                    )

    return pairings


def detect_cpp_stdlib_pairings(function_names: list[str]) -> list[Pairing]:
    """Detect C++ stdlib pairings based on known semantic relationships.

    Uses CPP_STDLIB_PAIRINGS table for pairings that can't be detected
    by simple naming patterns (e.g., constructor/destructor, RAII pairs).

    Args:
        function_names: List of C++ function names to analyze.

    Returns:
        List of Pairing objects for C++ stdlib functions.
    """
    pairings: list[Pairing] = []
    func_set = set(function_names)

    for opener, closer, evidence in CPP_STDLIB_PAIRINGS:
        if opener in func_set and closer in func_set:
            pairings.append(
                Pairing(
                    opener_id=f"axiom_for_{opener}",
                    closer_id=f"axiom_for_{closer}",
                    required=True,
                    source="cpp_stdlib_semantic",
                    confidence=0.9,
                    evidence=evidence,
                )
            )

    return pairings
