# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Post-extraction depends_on linking for library axioms.

This module provides functions to parse C++ signatures and axiom content
to extract type references, then resolve them to axiom IDs for the
depends_on field.

Unlike K-semantics axioms (which use function call parsing), library axioms
extracted from C++ spec use:
- Signature parsing: `T& value()` -> reference type
- Content parsing: "throws bad_optional_access" -> exception type
- Formal spec parsing: `throws(out_of_range)` -> exception type
"""

import re

from axiom.models import Axiom


# C++ type patterns to extract from signatures
CPP_TYPE_PATTERNS = {
    # Reference types
    r"\b(\w+)&": "reference",
    r"const\s+(\w+)&": "const_reference",
    # Pointer types
    r"\b(\w+)\*": "pointer",
    r"const\s+(\w+)\*": "const_pointer",
    # Common stdlib types
    r"\bsize_type\b": "size_type",
    r"\bsize_t\b": "size_t",
    r"\ballocator_type\b": "allocator_type",
    r"\ballocator\b": "allocator",
    r"\biterator\b": "iterator",
    r"\bInputIterator\b": "InputIterator",
    r"\bForwardIterator\b": "ForwardIterator",
    r"\bBidirectionalIterator\b": "BidirectionalIterator",
    r"\bRandomAccessIterator\b": "RandomAccessIterator",
    r"\bconst_iterator\b": "const_iterator",
    r"\breference\b": "reference",
    r"\bconst_reference\b": "const_reference",
    r"\bvalue_type\b": "value_type",
    r"\bkey_type\b": "key_type",
    r"\bmapped_type\b": "mapped_type",
    # Template types
    r"std::optional<": "optional",
    r"std::variant<": "variant",
    r"std::any\b": "any",
    r"std::expected<": "expected",
    r"std::shared_ptr<": "shared_ptr",
    r"std::unique_ptr<": "unique_ptr",
    r"std::weak_ptr<": "weak_ptr",
}

# Exception types to extract from content/formal_spec
EXCEPTION_PATTERNS = [
    r"\bbad_optional_access\b",
    r"\bbad_variant_access\b",
    r"\bbad_any_cast\b",
    r"\bbad_alloc\b",
    r"\bout_of_range\b",
    r"\blength_error\b",
    r"\binvalid_argument\b",
    r"\boverflow_error\b",
    r"\bunderflow_error\b",
    r"\bdomain_error\b",
    r"\brange_error\b",
    r"\bruntime_error\b",
    r"\blogic_error\b",
    r"\bsystem_error\b",
]


def parse_cpp_signature_types(signature: str | None) -> set[str]:
    """Extract type references from a C++ function signature.

    Args:
        signature: C++ function signature like "T& value()" or "void reset()"

    Returns:
        Set of type names found in the signature
    """
    if not signature:
        return set()

    types = set()

    # Check for reference return/param types
    if "&" in signature:
        types.add("reference")

    # Check for pointer return/param types
    if "*" in signature:
        types.add("pointer")

    # Check for common type patterns
    for pattern, type_name in CPP_TYPE_PATTERNS.items():
        if re.search(pattern, signature):
            types.add(type_name)

    # Extract template types: std::optional<T> -> optional
    template_match = re.search(r"std::(\w+)<", signature)
    if template_match:
        types.add(template_match.group(1))

    return types


def extract_exception_types(content: str | None) -> set[str]:
    """Extract exception type names from axiom content.

    Args:
        content: Axiom content text, e.g., "throws bad_optional_access"

    Returns:
        Set of exception type names
    """
    if not content:
        return set()

    exceptions = set()

    for pattern in EXCEPTION_PATTERNS:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            # Normalize to lowercase
            exceptions.add(match.group(0).lower())

    return exceptions


def parse_formal_spec_types(formal_spec: str | None) -> set[str]:
    """Extract type references from formal_spec.

    Args:
        formal_spec: Formal specification like "throws(bad_optional_access)"

    Returns:
        Set of type names found
    """
    if not formal_spec:
        return set()

    types = set()

    # Extract throws() arguments
    throws_matches = re.findall(r"throws\((\w+)\)", formal_spec)
    for exc_type in throws_matches:
        types.add(exc_type.lower())

    # Check for pointer/null predicates
    if re.search(r"\bpointer\b|\bis_pointer\b", formal_spec, re.IGNORECASE):
        types.add("pointer")
    if re.search(r"\bnull\b|\bis_null\b", formal_spec, re.IGNORECASE):
        types.add("null")

    return types


def extract_type_references(axiom: Axiom) -> set[str]:
    """Extract all type references from an axiom.

    Combines types from:
    - signature: return types, parameter types
    - content: exception types mentioned
    - formal_spec: throws() clauses, type predicates

    Args:
        axiom: The axiom to extract types from

    Returns:
        Set of all type names found
    """
    refs = set()

    # From signature
    if axiom.signature:
        refs.update(parse_cpp_signature_types(axiom.signature))

    # From content
    if axiom.content:
        refs.update(extract_exception_types(axiom.content))

    # From formal_spec
    if axiom.formal_spec:
        refs.update(parse_formal_spec_types(axiom.formal_spec))

    return refs


def resolve_type_to_axioms(
    type_ref: str,
    search_func,
    current_axiom_id: str | None = None,
) -> list[str]:
    """Find axiom IDs for a type reference.

    Args:
        type_ref: Type name to search for (e.g., "bad_optional_access")
        search_func: Function that takes query string and returns axiom dicts
        current_axiom_id: ID of current axiom (to avoid self-reference)

    Returns:
        List of axiom IDs that match the type
    """
    axiom_ids = []

    # Search for axioms mentioning this type
    results = search_func(type_ref, limit=5)

    # Normalize type reference for matching
    type_lower = type_ref.lower()
    # Also check for base type without _type suffix
    type_base = type_lower.replace("_type", "")

    for r in results:
        axiom_id = r.get("id", "")
        content = r.get("content", "").lower()
        axiom_id_lower = axiom_id.lower()

        # Skip self-reference
        if current_axiom_id and axiom_id == current_axiom_id:
            continue

        # Filter for relevance - check content OR axiom ID
        if type_lower in content or type_base in content or type_base in axiom_id_lower:
            axiom_ids.append(axiom_id)

    # Limit to 3 per type to avoid bloating depends_on
    return list(set(axiom_ids))[:3]


def link_axiom_depends_on(
    axioms: list[Axiom],
    search_func,
    skip_existing: bool = True,
) -> int:
    """Link depends_on for a list of axioms.

    Args:
        axioms: List of axioms to process
        search_func: Function that takes query string and returns axiom dicts
        skip_existing: If True, skip axioms that already have depends_on

    Returns:
        Number of axioms updated
    """
    updated = 0

    for axiom in axioms:
        # Skip if already has depends_on
        if skip_existing and axiom.depends_on:
            continue

        # Extract type references
        type_refs = extract_type_references(axiom)
        if not type_refs:
            continue

        # Resolve each type to axiom IDs
        all_deps = []
        for type_ref in type_refs:
            deps = resolve_type_to_axioms(type_ref, search_func, axiom.id)
            all_deps.extend(deps)

        # Update axiom
        if all_deps:
            axiom.depends_on = list(set(all_deps))
            updated += 1

    return updated
