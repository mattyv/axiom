"""LLM prompts for C++20 axiom extraction from spec prose."""

SYSTEM_PROMPT = """You are an expert C++ standards committee member and formal methods specialist.
Your task is to extract precise, machine-verifiable axioms from C++ specification text.

## What is an Axiom?

An axiom is a fundamental rule about C++ behavior that MUST be true. Axioms typically describe:
- Undefined behavior (UB): "the behavior is undefined if..."
- Preconditions: conditions that MUST hold before an operation
- Constraints: rules that MUST be satisfied
- Invariants: properties that MUST remain true

## Output Format

You MUST output valid TOML. Each axiom follows this schema:

```toml
[[axioms]]
id = "<unique_id>"                    # Format: cpp20_<section>_<short_desc>_<8char_hash>
content = '''<human_readable>'''      # Plain English description
formal_spec = '''<formal_condition>'''  # Precise logical condition
layer = "cpp20_language"              # or "cpp20_stdlib"
confidence = 0.85                     # Your confidence (0.75-0.95)
source_file = "<spec_section>"        # e.g., "basic.life" or "string.view.ops"
source_module = "<section_ref>"       # e.g., "[basic.life]/8"
tags = ['<tag1>', '<tag2>']           # Relevant tags
c_standard_refs = ['<ref>']           # e.g., "6.7.2/4" for related C refs
```

## Extraction Rules

1. **Be Precise**: Extract the EXACT condition, not a paraphrase
2. **One Axiom Per Rule**: Each distinct UB/constraint = one axiom
3. **Include Context**: The formal_spec should be self-contained
4. **Tag Appropriately**: Use tags like 'lifetime', 'initialization', 'conversion', 'concurrency'
5. **Cite Precisely**: Use [section]/paragraph format (e.g., [dcl.init]/7)

## Confidence Levels

- 0.95: Explicitly stated "undefined behavior" or "shall" requirement
- 0.85: Clear implication from normative text
- 0.75: Inference from multiple clauses or notes

## ID Generation

Generate IDs as: cpp20_<section_snake_case>_<short_desc>_<hash>
Where hash is first 8 chars of SHA256(content + formal_spec)

Example: cpp20_basic_life_access_after_destroy_a1b2c3d4

## Example Extraction

Input:
> [basic.life]/7: ... if the object will be or was of a non-trivially-destructible type,
> the program has undefined behavior if the pointer is used as the operand of a delete-expression.

Output:
```toml
[[axioms]]
id = "cpp20_basic_life_delete_nontrivial_destroyed_f3a8b2c1"
content = '''Using a pointer to a destroyed non-trivially-destructible object as operand of delete-expression is undefined behavior.'''
formal_spec = '''destroyed(ptr) && non_trivially_destructible(pointee_type(ptr)) && delete_expr(ptr) => undefined_behavior'''
layer = "cpp20_language"
confidence = 0.95
source_file = "basic.life"
source_module = "[basic.life]/7"
tags = ['lifetime', 'destructor', 'delete']
```

## What NOT to Extract

- Implementation-defined behavior (unless it affects portability)
- Non-normative notes (unless they clarify UB)
- Examples (unless they demonstrate UB)
- Deprecated features
- Platform-specific behavior
"""

EXTRACTION_PROMPT = """## Task

Extract all axioms from the following C++ specification section.

## Section: {section_ref}

{html_content}

## Instructions

1. Read the entire section carefully
2. Identify ALL undefined behavior, preconditions, and constraints
3. For each, create a TOML axiom entry
4. Ensure IDs are unique (use hash suffix)
5. Set appropriate confidence levels

## Existing Axioms (DO NOT DUPLICATE)

The following axioms already exist in the knowledge base. Do NOT create duplicates:

{existing_axioms}

## Output

Output ONLY valid TOML with [[axioms]] entries. No markdown, no explanation.
Start your response with:

version = "1.0"
source = "eel.is/c++draft/{section_ref}"
extracted_at = "{timestamp}"

[[axioms]]
...
"""

DEDUP_CHECK_PROMPT = """## Task

Check if the following proposed axiom is a duplicate of any existing axiom.

## Proposed Axiom

```toml
{proposed_axiom}
```

## Existing Axioms

{existing_axioms}

## Instructions

Respond with ONLY one of:
- "DUPLICATE:<existing_id>" if this is a duplicate (include the existing ID)
- "UNIQUE" if this is a new, distinct axiom

Consider an axiom a duplicate if:
1. It describes the SAME condition/behavior
2. Even if wording differs slightly
3. Even if from a different source section

Be conservative - when in doubt, mark as DUPLICATE.
"""

# High-signal sections for C++20 language UB extraction
HIGH_SIGNAL_SECTIONS = [
    # Object model and lifetime
    "basic.life",
    "basic.stc",
    "basic.stc.dynamic",
    "basic.stc.dynamic.safety",

    # Expressions
    "expr.pre",
    "expr.prop",
    "expr.prim",
    "expr.unary",
    "expr.cast",
    "expr.mptr.oper",
    "expr.mul",
    "expr.add",
    "expr.shift",
    "expr.rel",
    "expr.eq",

    # Declarations
    "dcl.init",
    "dcl.init.ref",
    "dcl.init.list",
    "dcl.init.aggr",

    # Classes
    "class.cdtor",
    "class.base.init",
    "class.copy",
    "class.dtor",

    # Derived classes
    "class.virtual",
    "class.abstract",

    # Special member functions
    "special",

    # Overloading
    "over.match",
    "over.oper",

    # Templates
    "temp.deduct",
    "temp.spec",

    # Exception handling
    "except.throw",
    "except.ctor",
    "except.handle",

    # Concurrency (C++11/14/17/20)
    "intro.multithread",
    "intro.races",
    "atomics.order",
    "atomics.fences",

    # C++20 specific
    "concept.same",
    "dcl.init.list",  # Designated initializers
    "expr.prim.req",  # Requires expressions
    "module",         # Modules
    "dcl.fct.def.coroutine",  # Coroutines
    "temp.constr",    # Constraints
    "cmp",            # Three-way comparison
]

# High-signal library sections
HIGH_SIGNAL_LIBRARY_SECTIONS = [
    # Containers
    "container.requirements",
    "sequence.reqmts",
    "associative.reqmts",
    "unord.req",

    # Iterators
    "iterator.requirements",
    "iterator.operations",

    # Algorithms
    "algorithms.requirements",
    "alg.sorting",

    # Strings
    "string.view",
    "basic.string",

    # Memory
    "unique.ptr",
    "util.sharedptr",
    "allocator.requirements",

    # Utilities
    "optional",
    "variant",
    "any",
    "expected",

    # Ranges (C++20)
    "range.access",
    "range.req",

    # Concurrency
    "thread.mutex",
    "thread.condition",
    "futures",

    # Format (C++20)
    "format",
]


def generate_extraction_prompt(
    section_ref: str,
    html_content: str,
    existing_axioms: list[dict],
    timestamp: str,
) -> str:
    """Generate extraction prompt with existing axioms for dedup.

    Args:
        section_ref: Section reference (e.g., "basic.life")
        html_content: HTML content of the section
        existing_axioms: List of existing axiom dicts from search
        timestamp: ISO timestamp for extraction

    Returns:
        Formatted extraction prompt
    """
    # Format existing axioms for context
    if existing_axioms:
        existing_str = "\n".join(
            f"- {a['id']}: {a['content'][:100]}..."
            for a in existing_axioms[:20]  # Limit to 20 for context window
        )
    else:
        existing_str = "(No existing axioms found for this section)"

    return EXTRACTION_PROMPT.format(
        section_ref=section_ref,
        html_content=html_content,
        existing_axioms=existing_str,
        timestamp=timestamp,
    )


def generate_dedup_prompt(
    proposed_axiom: str,
    existing_axioms: list[dict],
) -> str:
    """Generate deduplication check prompt.

    Args:
        proposed_axiom: TOML string of proposed axiom
        existing_axioms: List of existing axiom dicts from search

    Returns:
        Formatted dedup prompt
    """
    if existing_axioms:
        existing_str = "\n\n".join(
            f"ID: {a['id']}\nContent: {a['content']}\nFormal: {a.get('formal_spec', 'N/A')}"
            for a in existing_axioms[:10]
        )
    else:
        existing_str = "(No similar axioms found)"

    return DEDUP_CHECK_PROMPT.format(
        proposed_axiom=proposed_axiom,
        existing_axioms=existing_str,
    )
