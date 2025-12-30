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

# C++ language concepts to extract from content (for macro/template libraries)
# Maps regex pattern -> search query for foundation axioms
# Comprehensive coverage of C++20 language concepts
CPP_CONCEPT_PATTERNS = {
    # === Object Lifetime (basic.life) ===
    r"\blifetime\b": "object lifetime",
    r"\bstorage\s+duration\b": "storage duration",
    r"\bdestruct": "destructor",
    r"\bconstruct": "constructor",

    # === Value Categories (basic.lval) ===
    r"\blvalue\b": "lvalue",
    r"\brvalue\b": "rvalue",
    r"\bxvalue\b": "xvalue",
    r"\bprvalue\b": "prvalue",
    r"\bglvalue\b": "glvalue",

    # === Storage Duration (basic.stc) ===
    r"\bstatic\s+storage\b": "static storage duration",
    r"\bthread\s+local\b": "thread storage duration",
    r"\bautomatic\s+storage\b": "automatic storage duration",
    r"\bdynamic\s+storage\b": "dynamic storage duration",
    r"\bblock\s+scope\b": "block scope automatic",

    # === Initialization (dcl.init) ===
    r"\binitializ": "initialization",
    r"\bdefault[- ]initializ": "default initialization",
    r"\bvalue[- ]initializ": "value initialization",
    r"\bdirect[- ]initializ": "direct initialization",
    r"\bcopy[- ]initializ": "copy initialization",
    r"\blist[- ]initializ": "list initialization",
    r"\baggregate[- ]initializ": "aggregate initialization",
    r"\breference\s+initializ": "reference initialization",
    r"\bzero[- ]initializ": "zero initialization",

    # === References ===
    r"\breference\b": "reference",
    r"\bforwarding\s+reference\b": "forwarding reference",
    r"\buniversal\s+reference\b": "forwarding reference",
    r"\brvalue\s+reference\b": "rvalue reference",
    r"\blvalue\s+reference\b": "lvalue reference",
    r"\bdangling\s+reference\b": "reference lifetime",

    # === Expressions (expr.*) ===
    r"\blambda\b": "lambda expression",
    r"\bcapture\b": "lambda capture",
    r"\bclosure\b": "lambda closure",
    r"\bco_await\b": "await expression",
    r"\bcoroutine\b": "coroutine await",
    r"\bcast\b": "cast expression",
    r"\bstatic_cast\b": "static cast",
    r"\bdynamic_cast\b": "dynamic cast",
    r"\breinterpret_cast\b": "reinterpret cast",
    r"\bconst_cast\b": "const cast",
    r"\bsizeof\b": "sizeof expression",
    r"\balignof\b": "alignof expression",
    r"\bnew\s+expression\b": "new expression",
    r"\bdelete\s+expression\b": "delete expression",
    r"\boperator\s+new\b": "new expression",
    r"\boperator\s+delete\b": "delete expression",
    r"\boperator\b": "operator",
    r"\bconversion\b": "conversion",
    r"\bimplicit\s+conversion\b": "implicit conversion",
    r"\bexplicit\s+conversion\b": "explicit conversion",
    r"\bnarrowing\s+conversion\b": "narrowing conversion",

    # === Overloading (over.*) ===
    r"\boverload\b": "overload resolution",
    r"\boverload\s+resolution\b": "overload resolution match",
    r"\bcandidate\s+function\b": "overload candidate",
    r"\bviable\s+function\b": "overload viable",
    r"\bbest\s+viable\b": "overload match best",
    r"\bambiguous\b": "overload ambiguous",

    # === Templates (temp.*) ===
    r"\btemplate\b": "template",
    r"\btemplate\s+parameter\b": "template parameter",
    r"\btemplate\s+argument\b": "template argument",
    r"\btemplate\s+instantiation\b": "template instantiation",
    r"\bexplicit\s+specialization\b": "template explicit specialization",
    r"\bpartial\s+specialization\b": "template partial specialization",
    r"\bSFINAE\b": "template substitution failure",
    r"\bsubstitution\s+failure\b": "template substitution failure",
    r"\btype\s+deduction\b": "template type deduction",
    r"\bauto\b": "auto type deduction",
    r"\bdecltype\b": "decltype",

    # === Concepts (concept.*) ===
    r"\bconcept\b": "concept",
    r"\bconstraint\b": "concept constraint",
    r"\brequires\s+clause\b": "requires clause",
    r"\brequires\s+expression\b": "requires expression",
    r"\bsatisf": "concept satisfies",
    r"\bsame_as\b": "same_as concept",

    # === Exceptions (except.*) ===
    r"\bexception\b": "exception",
    r"\bthrow\b": "throw expression",
    r"\bcatch\b": "exception catch",
    r"\btry\b": "exception try",
    r"\bnoexcept\b": "noexcept",
    r"\bstack\s+unwinding\b": "exception stack unwinding",
    r"\bexception\s+specification\b": "exception specification",

    # === Special Member Functions (special.*) ===
    r"\bcopy\s+constructor\b": "copy constructor",
    r"\bmove\s+constructor\b": "move constructor",
    r"\bcopy\s+assignment\b": "copy assignment",
    r"\bmove\s+assignment\b": "move assignment",
    r"\bdefault\s+constructor\b": "default constructor",
    r"\bdestructor\b": "destructor",
    r"\bimplicitly[- ]declared\b": "implicit special member",
    r"\bdefaulted\b": "defaulted special member",
    r"\bdeleted\b": "deleted special member",
    r"\btrivial\b": "trivial special member",

    # === Classes (class.*) ===
    r"\bclass\b": "class",
    r"\bstruct\b": "class struct",
    r"\bbase\s+class\b": "base class",
    r"\bderived\s+class\b": "derived class",
    r"\binheritance\b": "inheritance",
    r"\bvirtual\b": "virtual",
    r"\bpure\s+virtual\b": "pure virtual",
    r"\babstract\s+class\b": "abstract class",
    r"\baccess\s+specifier\b": "access specifier",
    r"\bpublic\b": "public access",
    r"\bprotected\b": "protected access",
    r"\bprivate\b": "private access",

    # === Memory & Atomics (atomics.*, intro.races) ===
    r"\batomic\b": "atomic",
    r"\bmemory\s+order\b": "memory order",
    r"\bsequentially[- ]consistent\b": "sequentially consistent",
    r"\bacquire\b": "acquire",
    r"\brelease\b": "release",
    r"\bfence\b": "fence",
    r"\bdata\s+race\b": "data race",
    r"\bhappens[- ]before\b": "happens before",
    r"\bsynchroniz": "synchronization",

    # === Multithreading (intro.multithread, intro.progress) ===
    r"\bthread\b": "thread",
    r"\bforward\s+progress\b": "forward progress",
    r"\bblocking\b": "blocking",
    r"\bdeadlock\b": "deadlock",

    # === Iterators ===
    r"\biterator\b": "iterator",
    r"\binput\s+iterator\b": "input iterator",
    r"\boutput\s+iterator\b": "output iterator",
    r"\bforward\s+iterator\b": "forward iterator",
    r"\bbidirectional\s+iterator\b": "bidirectional iterator",
    r"\brandom\s+access\s+iterator\b": "random access iterator",
    r"\bcontiguous\s+iterator\b": "contiguous iterator",
    r"\bbegin\b": "begin iterator",
    r"\bend\b": "end iterator",

    # === Ranges ===
    r"\brange\b": "range",
    r"\brange[- ]based\s+for\b": "range-based for",
    r"\bview\b": "range view",

    # === Control Flow ===
    r"\bfor\s+loop\b": "for statement",
    r"\bwhile\s+loop\b": "while statement",
    r"\bif\s+statement\b": "if statement",
    r"\bswitch\s+statement\b": "switch statement",
    r"\breturn\s+statement\b": "return statement",

    # === Types ===
    r"\bintegral\b": "integral type",
    r"\bfloating[- ]point\b": "floating point type",
    r"\bvoid\b": "void type",
    r"\bbool\b": "bool type",
    r"\bpointer\b": "pointer",
    r"\bnullptr\b": "nullptr",
    r"\barray\b": "array",
    r"\bfunction\s+pointer\b": "function pointer",
    r"\bmember\s+pointer\b": "member pointer",
}


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


def extract_cpp_concepts(content: str | None) -> set[str]:
    """Extract C++ language concepts from axiom content.

    Scans content for mentions of C++ language features like "lambda",
    "iterator", "reference", etc. and returns search queries to find
    matching foundation axioms.

    Args:
        content: Axiom content text.

    Returns:
        Set of search queries for C++ concepts found.
    """
    if not content:
        return set()

    concepts = set()
    content_lower = content.lower()

    for pattern, search_query in CPP_CONCEPT_PATTERNS.items():
        if re.search(pattern, content_lower, re.IGNORECASE):
            concepts.add(search_query)

    return concepts


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
    - content: exception types mentioned, C++ language concepts
    - formal_spec: throws() clauses, type predicates

    Args:
        axiom: The axiom to extract types from

    Returns:
        Set of all type names/search queries found
    """
    refs = set()

    # From signature
    if axiom.signature:
        refs.update(parse_cpp_signature_types(axiom.signature))

    # From content - exception types
    if axiom.content:
        refs.update(extract_exception_types(axiom.content))

    # From content - C++ language concepts
    if axiom.content:
        refs.update(extract_cpp_concepts(axiom.content))

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
