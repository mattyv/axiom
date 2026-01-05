# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Build semantic queries from call site context.

This module parses callee signatures to extract operand types,
then builds natural language queries for semantic axiom search.
"""

from __future__ import annotations

import re


def parse_signature_types(
    callee: str, signature: str | None
) -> tuple[str, str | None, str | None]:
    """Parse operator and operand types from a callee signature.

    The extractor outputs signatures in formats like:
    - Binary: "int operator/ int", "float operator+ float"
    - Unary: "operator* pointer", "operator& int"
    - Subscript: "int operator[] array"

    Args:
        callee: The callee name (e.g., "operator/", "std::mutex::lock")
        signature: The signature string from the extractor, or None

    Returns:
        Tuple of (operator, left_type, right_type) where types may be None
    """
    if not signature:
        return (callee, None, None)

    signature = signature.strip()
    if not signature:
        return (callee, None, None)

    # Pattern for binary operators: "type operator<op> type"
    # Examples: "int operator/ int", "float operator>= float"
    binary_pattern = r"^(\w+)\s+(operator[^\s]+)\s+(\w+)$"
    match = re.match(binary_pattern, signature)
    if match:
        left_type = match.group(1)
        operator = match.group(2)
        right_type = match.group(3)
        return (operator, left_type, right_type)

    # Pattern for unary operators: "operator<op> type"
    # Examples: "operator* pointer", "operator& int"
    unary_pattern = r"^(operator[^\s]+)\s+(\w+)$"
    match = re.match(unary_pattern, signature)
    if match:
        operator = match.group(1)
        right_type = match.group(2)
        return (operator, None, right_type)

    # Function signature (not operator): return callee only
    # Examples: "void* malloc(size_t)", "int printf(const char*, ...)"
    return (callee, None, None)


# Maps operator names to semantic terms for query building
OPERATOR_SEMANTICS = {
    # Arithmetic
    "operator/": ("division", "divide", "divisor"),
    "operator%": ("modulus", "remainder", "divisor"),
    "operator+": ("addition", "add", "sum"),
    "operator-": ("subtraction", "subtract", "difference"),
    "operator*": ("multiplication", "multiply", "dereference", "pointer"),
    # Comparison
    "operator<": ("comparison", "less than", "relational"),
    "operator>": ("comparison", "greater than", "relational"),
    "operator<=": ("comparison", "less equal", "relational"),
    "operator>=": ("comparison", "greater equal", "relational"),
    "operator==": ("equality", "equal", "comparison"),
    "operator!=": ("inequality", "not equal", "comparison"),
    "operator<=>": ("comparison", "three-way", "spaceship"),
    # Subscript and access
    "operator[]": ("subscript", "array", "index", "bounds"),
    "operator->": ("member access", "pointer", "arrow"),
    # Bitwise
    "operator&": ("bitwise and", "address-of", "reference"),
    "operator|": ("bitwise or",),
    "operator^": ("bitwise xor",),
    "operator~": ("bitwise not", "complement"),
    "operator<<": ("left shift", "bitwise"),
    "operator>>": ("right shift", "bitwise"),
    # Logical
    "operator!": ("logical not", "boolean"),
    "operator&&": ("logical and", "boolean"),
    "operator||": ("logical or", "boolean"),
    # Assignment
    "operator=": ("assignment", "assign"),
    "operator+=": ("compound assignment", "addition"),
    "operator-=": ("compound assignment", "subtraction"),
    "operator*=": ("compound assignment", "multiplication"),
    "operator/=": ("compound assignment", "division"),
    "operator%=": ("compound assignment", "modulus"),
}

# Maps type names to semantic terms
TYPE_SEMANTICS = {
    "int": "integer",
    "long": "integer",
    "short": "integer",
    "char": "character",
    "float": "floating-point",
    "double": "floating-point",
    "bool": "boolean",
    "pointer": "pointer",
    "array": "array",
    "void": "void",
    "size_t": "size",
    "ptrdiff_t": "pointer difference",
}


def build_axiom_query(callee: str, signature: str | None) -> str:
    """Build a semantic search query from call context.

    Creates a natural language query that will match relevant axioms
    via vector similarity search.

    Args:
        callee: The callee name (e.g., "operator/", "std::mutex::lock")
        signature: The signature string from the extractor, or None

    Returns:
        Natural language query for semantic search

    Examples:
        ("operator/", "int operator/ int")
            -> "integer division precondition divisor zero"
        ("operator>=", "int operator>= int")
            -> "integer comparison greater equal precondition"
        ("operator[]", "int operator[] array")
            -> "array subscript index bounds precondition"
        ("std::mutex::lock", None)
            -> "mutex lock precondition"
    """
    parts: list[str] = []

    # Parse the signature to get types
    operator, left_type, right_type = parse_signature_types(callee, signature)

    # Add type context if available
    if left_type:
        semantic_type = TYPE_SEMANTICS.get(left_type, left_type)
        parts.append(semantic_type)

    # Add operator semantics
    if operator in OPERATOR_SEMANTICS:
        # Use first (primary) semantic term
        parts.append(OPERATOR_SEMANTICS[operator][0])
    elif operator.startswith("operator"):
        # Generic operator - extract the symbol
        op_symbol = operator.replace("operator", "").strip()
        parts.append(f"operator {op_symbol}")
    else:
        # Function name - extract meaningful parts
        # e.g., "std::mutex::lock" -> "mutex lock"
        name_parts = operator.replace("::", " ").replace("<", " ").replace(">", " ")
        # Filter out std and template noise
        meaningful = [
            p for p in name_parts.split()
            if p not in ("std", "const", "volatile") and not p.isdigit()
        ]
        parts.extend(meaningful[-2:])  # Take last 2 parts (most specific)

    # Add right type context if different from left
    if right_type and right_type != left_type:
        semantic_type = TYPE_SEMANTICS.get(right_type, right_type)
        parts.append(semantic_type)

    # Add "precondition" to help find the right axiom type
    parts.append("precondition")

    # For division/modulus, add "zero" hint since that's the key precondition
    if operator in ("operator/", "operator%"):
        parts.append("divisor")
        parts.append("zero")

    # For subscript, add "bounds" hint
    if operator == "operator[]":
        parts.append("bounds")

    # For dereference, add "null" hint
    if operator == "operator*" and right_type == "pointer":
        parts.append("null")

    return " ".join(parts)
