"""LLM prompts for axiom extraction from C/C++ functions.

These prompts guide the LLM to extract K-semantic axioms by analyzing
the function's operation subgraph and finding related foundation axioms.
"""

# System prompt that establishes the LLM's role and capabilities
SYSTEM_PROMPT = """You are an expert in C/C++ semantics and formal verification.
Your task is to extract formal axioms from C/C++ functions by analyzing their operations.

You have access to:
1. A parsed operation subgraph showing every operation in the function
2. Related foundation axioms from the C11/C++20 standards (via RAG search)

Your job is to identify semantic requirements (preconditions, postconditions, invariants)
for each hazardous operation and link them to foundation axioms.

IMPORTANT: Only extract axioms for operations that have semantic requirements.
Not every operation needs an axiom - focus on:
- Division/modulo (requires non-zero divisor)
- Pointer dereference (requires valid, non-null pointer)
- Array access (requires valid index within bounds)
- Memory allocation/deallocation (requires proper pairing, size constraints)
- Integer operations that may overflow
- Type casts that may lose data
- Function calls with documented preconditions
"""

# Main extraction prompt template
EXTRACTION_PROMPT = """## Function to Analyze

**Signature**: `{signature}`
**Name**: `{function_name}`
**File**: `{file_path}`

## Operation Subgraph

The function has been parsed into the following operations:

```json
{subgraph_json}
```

### Summary
- Total operations: {total_ops}
- Has divisions: {has_divisions}
- Has pointer operations: {has_pointer_ops}
- Has loops: {has_loops}
- Function calls: {function_calls}

### Key Operations Requiring Semantic Analysis

{key_operations}

## Source Code

```cpp
{source_code}
```

## Related Foundation Axioms (from C11/C++20 standards)

{related_axioms}

## Task

Extract ALL semantic axioms from this function, including:
1. **PRECONDITION**: What must be true before calling this function
2. **POSTCONDITION**: What is guaranteed after the function returns
3. **INVARIANT**: What remains true throughout execution
4. **EFFECT**: Behavioral semantics (what the function does, side effects)
5. **CONSTRAINT**: Type/value constraints on parameters or results
6. **EXCEPTION**: What exceptions can be thrown and when
7. **ANTI_PATTERN**: Common mistakes or patterns to avoid
8. **COMPLEXITY**: Big-O time/space complexity guarantees

Output ONLY valid TOML with the following structure for each axiom:

```toml
[[axioms]]
id = "<generated_unique_id>"
function = "{function_name}"
header = "<header_file>"
axiom_type = "<precondition|postcondition|invariant|effect|constraint|exception|anti_pattern|complexity>"
content = "<human-readable description>"
formal_spec = "<formal condition using actual operand names>"
on_violation = "<what happens: undefined behavior, throws, returns error, etc.>"
depends_on = ["<foundation_axiom_id_1>", "<foundation_axiom_id_2>"]
source_operation_id = "<operation_id from subgraph>"
source_line = <line_number>
confidence = <0.0-1.0>
```

### Axiom Type Guidelines

- **PRECONDITION**: Requirements that callers must satisfy (e.g., "divisor != 0")
- **POSTCONDITION**: Guarantees the function provides (e.g., "returns sorted array")
- **INVARIANT**: Properties preserved during execution (e.g., "heap property maintained")
- **EFFECT**: What the function does (e.g., "invokes callback N times", "modifies global state")
- **CONSTRAINT**: Type or value limits (e.g., "index must be within bounds")
- **EXCEPTION**: Exception behavior (e.g., "throws std::out_of_range if index invalid")
- **ANTI_PATTERN**: Common mistakes (e.g., "do not call from signal handler")
- **COMPLEXITY**: Performance (e.g., "O(n log n) average case")

### Dependency Chain Guidelines

**CRITICAL**: Every axiom should link to foundation axioms via `depends_on`:

- Use ACTUAL axiom IDs from the "Related Foundation Axioms" section above
- Each axiom can depend on MULTIPLE foundation axioms (1:many relationship)
- Example: An EFFECT axiom about loop behavior might depend on:
  `depends_on = ["c11_stmt_for_semantics", "c11_expr_call"]`

This creates a chain from library axioms down to grounded formal semantics.

### Confidence Guidelines

- 1.0: Direct match to foundation axiom, no ambiguity
- 0.8-0.9: Clear semantic requirement, foundation axiom applies
- 0.6-0.7: Likely applies but context-dependent
- <0.6: Uncertain, may need human review

### Other Guidelines

- Use actual variable names from the subgraph operands
- Include guard conditions if the operation is protected by a check
- If an operation is already guarded, note this in content but still extract the axiom

Output only the TOML block, no other text.
"""

# Template for formatting key operations
KEY_OPERATION_TEMPLATE = """### {op_type} at line {line}
- Code: `{code_snippet}`
- Operands: {operands}
- Guards: {guards}
"""

# Template for formatting related axioms
RELATED_AXIOM_TEMPLATE = """### {axiom_id}
- Content: {content}
- Formal spec: `{formal_spec}`
- Standard refs: {standard_refs}
"""

# Prompt for generating search queries from operations
SEARCH_QUERY_PROMPT = """Given the following operation from a C/C++ function, generate a search query
to find related foundation axioms in the knowledge base.

Operation type: {op_type}
Code snippet: `{code_snippet}`
Operands: {operands}
Context: {context}

Generate a concise search query (1-2 sentences) that will find relevant C/C++ semantic rules.
Focus on the semantic requirement, not the syntax.

Examples:
- For division: "division by zero undefined behavior C integer"
- For pointer deref: "null pointer dereference undefined behavior"
- For array access: "array bounds out of range undefined behavior"
- For malloc: "malloc size zero memory allocation"

Output only the search query, nothing else.
"""

# Prompt for validating extracted axioms
VALIDATION_PROMPT = """Review the following extracted axiom for correctness:

## Extracted Axiom
```toml
{axiom_toml}
```

## Source Operation
- Type: {op_type}
- Code: `{code_snippet}`
- Line: {line}
- Guards: {guards}

## Foundation Axiom
- ID: {foundation_id}
- Content: {foundation_content}
- Formal spec: `{foundation_spec}`

## Questions to Answer

1. Does the formal_spec correctly use the operand names from the source?
2. Does the depends_on reference the correct foundation axiom?
3. Is the axiom_type (precondition/postcondition/invariant) correct?
4. Is the on_violation description accurate?
5. Is the confidence score appropriate?

Answer with:
- VALID: If the axiom is correct
- INVALID: <reason> if there's an error
- MODIFY: <suggested change> if minor correction needed
"""


def format_key_operations(subgraph) -> str:
    """Format key operations from subgraph for the prompt.

    Args:
        subgraph: FunctionSubgraph object

    Returns:
        Formatted string of key operations
    """
    sections = []

    # Divisions (divide-by-zero hazard)
    divisions = subgraph.get_divisions()
    for op in divisions:
        sections.append(KEY_OPERATION_TEMPLATE.format(
            op_type="Division/Modulo",
            line=op.line_start,
            code_snippet=op.code_snippet,
            operands=op.operands,
            guards=op.guards if op.guards else "None",
        ))

    # Pointer operations (null deref hazard)
    pointer_ops = subgraph.get_pointer_operations()
    for op in pointer_ops:
        sections.append(KEY_OPERATION_TEMPLATE.format(
            op_type=op.op_type.value.replace("_", " ").title(),
            line=op.line_start,
            code_snippet=op.code_snippet,
            operands=op.operands,
            guards=op.guards if op.guards else "None",
        ))

    # Memory operations (allocation hazards)
    memory_ops = subgraph.get_memory_operations()
    for op in memory_ops:
        sections.append(KEY_OPERATION_TEMPLATE.format(
            op_type=op.op_type.value.replace("_", " ").title(),
            line=op.line_start,
            code_snippet=op.code_snippet,
            operands=op.operands,
            guards=op.guards if op.guards else "None",
        ))

    # Function calls (may have preconditions)
    calls = subgraph.get_function_calls()
    for op in calls:
        if op.function_called:
            sections.append(KEY_OPERATION_TEMPLATE.format(
                op_type=f"Function Call: {op.function_called}",
                line=op.line_start,
                code_snippet=op.code_snippet,
                operands=op.call_arguments,
                guards=op.guards if op.guards else "None",
            ))

    if not sections:
        return "No hazardous operations identified in this function."

    return "\n".join(sections)


def format_related_axioms(axiom_results: list) -> str:
    """Format RAG search results for the prompt.

    Args:
        axiom_results: List of axiom dicts from LanceDB search

    Returns:
        Formatted string of related axioms
    """
    if not axiom_results:
        return "No related foundation axioms found."

    sections = []
    for result in axiom_results:
        sections.append(RELATED_AXIOM_TEMPLATE.format(
            axiom_id=result.get("id", "unknown"),
            content=result.get("content", ""),
            formal_spec=result.get("formal_spec", "N/A"),
            standard_refs=result.get("c_standard_refs", []),
        ))

    return "\n".join(sections)


def build_extraction_prompt(
    subgraph,
    source_code: str,
    related_axioms: list,
    file_path: str = "",
) -> str:
    """Build the full extraction prompt.

    Args:
        subgraph: FunctionSubgraph object
        source_code: Original source code of the function
        related_axioms: List of related axiom dicts from RAG
        file_path: Path to the source file

    Returns:
        Complete prompt string
    """
    import json

    summary = subgraph.to_summary()

    return EXTRACTION_PROMPT.format(
        signature=subgraph.signature,
        function_name=subgraph.name,
        file_path=file_path or "unknown",
        subgraph_json=json.dumps(summary, indent=2),
        total_ops=summary["total_operations"],
        has_divisions="Yes" if summary["has_divisions"] else "No",
        has_pointer_ops="Yes" if summary["has_pointer_ops"] else "No",
        has_loops="Yes" if summary["has_loops"] else "No",
        function_calls=", ".join(summary["function_calls"]) or "None",
        key_operations=format_key_operations(subgraph),
        source_code=source_code,
        related_axioms=format_related_axioms(related_axioms),
    )


def build_search_queries(subgraph) -> list:
    """Generate search queries for RAG based on operations.

    Args:
        subgraph: FunctionSubgraph object

    Returns:
        List of search query strings
    """
    queries = []

    # Division operations
    if subgraph.get_divisions():
        queries.append("division by zero undefined behavior integer modulo")

    # Pointer operations
    pointer_ops = subgraph.get_pointer_operations()
    if pointer_ops:
        queries.append("null pointer dereference undefined behavior")
        queries.append("pointer validity lifetime")

    # Array access
    from axiom.models import OperationType
    array_ops = subgraph.get_operations_of_type(OperationType.ARRAY_ACCESS)
    if array_ops:
        queries.append("array index bounds out of range undefined behavior")

    # Memory operations
    memory_ops = subgraph.get_memory_operations()
    if memory_ops:
        queries.append("malloc free memory allocation deallocation")
        queries.append("new delete memory leak double free")

    # Function calls - search for each unique function
    calls = subgraph.get_function_calls()
    seen_funcs = set()
    for call in calls:
        if call.function_called and call.function_called not in seen_funcs:
            seen_funcs.add(call.function_called)
            queries.append(f"{call.function_called} precondition semantics")

    return queries


# =============================================================================
# Macro extraction prompts
# =============================================================================

MACRO_SYSTEM_PROMPT = """You are an expert in C/C++ preprocessor semantics and formal verification.
Your task is to extract formal axioms from C/C++ macro definitions.

Macros require special attention because:
1. They perform textual substitution, not function calls
2. Arguments may be evaluated multiple times (side effects!)
3. Operator precedence can cause unexpected behavior without parentheses
4. They can hide hazardous operations behind simple syntax

Focus on extracting axioms for:
- Macros that perform division or modulo
- Macros that dereference pointers
- Macros that cast types
- Macros with multiple argument evaluation
- Macros that call functions with preconditions
"""

MACRO_EXTRACTION_PROMPT = """## Macro to Analyze

**Name**: `{macro_name}`
**Signature**: `{signature}`
**File**: `{file_path}`
**Line**: {line}

## Macro Definition

```cpp
#define {signature} {body}
```

## Analysis

- Is function-like: {is_function_like}
- Parameters: {parameters}
- Has division: {has_division}
- Has pointer ops: {has_pointer_ops}
- Has casts: {has_casts}
- Function calls: {function_calls}
- Referenced macros: {referenced_macros}

## Related Foundation Axioms

{related_axioms}

## Task

Extract ALL semantic axioms from this macro, including:
1. **PRECONDITION**: What must be true before using this macro
2. **POSTCONDITION**: What is guaranteed after macro expansion
3. **EFFECT**: Behavioral semantics (side effects, multiple evaluation)
4. **CONSTRAINT**: Type/value constraints on parameters
5. **ANTI_PATTERN**: Common mistakes or patterns to avoid
6. **COMPLEXITY**: Performance implications

For macros, pay special attention to:
1. **Multiple evaluation**: If an argument appears more than once, side effects are evaluated multiple times
2. **Operator precedence**: Without parentheses around arguments, precedence can cause bugs
3. **Type safety**: Macros don't have type checking - document expected types
4. **Hazardous operations**: Division, pointer ops, etc. in the expansion

Output ONLY valid TOML with the following structure for each axiom:

```toml
[[axioms]]
id = "<generated_unique_id>"
function = "{macro_name}"  # Use the macro name
header = "<header_file>"
axiom_type = "<precondition|postcondition|invariant|effect|constraint|exception|anti_pattern|complexity>"
content = "<human-readable description>"
formal_spec = "<formal condition using parameter names>"
on_violation = "<what happens: undefined behavior, incorrect result, etc.>"
depends_on = ["<foundation_axiom_id_1>", "<foundation_axiom_id_2>"]
confidence = <0.0-1.0>
tags = ["macro"]
```

### Dependency Chain Guidelines

**CRITICAL**: Every axiom should link to foundation axioms via `depends_on`:

- Use ACTUAL axiom IDs from the "Related Foundation Axioms" section above
- Each axiom can depend on MULTIPLE foundation axioms (1:many relationship)
- This creates a chain from macro axioms down to grounded formal semantics

### Other Guidelines

- Use parameter names from the macro definition
- Note if arguments may be evaluated multiple times (use 'effect' axiom_type)
- Document expected types as constraints
- Include "macro" in tags

If the macro is simple (e.g., just a constant) and has no semantic requirements,
output an empty axioms array:

```toml
[[axioms]]
# No axioms needed for this simple macro
```

Output only the TOML block, no other text.
"""


def build_macro_extraction_prompt(
    macro,
    related_axioms: list,
    file_path: str = "",
) -> str:
    """Build the extraction prompt for a macro.

    Args:
        macro: MacroDefinition object
        related_axioms: List of related axiom dicts from RAG
        file_path: Path to the source file

    Returns:
        Complete prompt string
    """
    return MACRO_EXTRACTION_PROMPT.format(
        macro_name=macro.name,
        signature=macro.to_signature(),
        file_path=file_path or macro.file_path or "unknown",
        line=macro.line_start,
        body=macro.body,
        is_function_like="Yes" if macro.is_function_like else "No",
        parameters=", ".join(macro.parameters) if macro.parameters else "None",
        has_division="Yes" if macro.has_division else "No",
        has_pointer_ops="Yes" if macro.has_pointer_ops else "No",
        has_casts="Yes" if macro.has_casts else "No",
        function_calls=", ".join(macro.function_calls) if macro.function_calls else "None",
        referenced_macros=", ".join(macro.referenced_macros) if macro.referenced_macros else "None",
        related_axioms=format_related_axioms(related_axioms),
    )


def build_macro_search_queries(macro) -> list:
    """Generate search queries for RAG based on macro content.

    Args:
        macro: MacroDefinition object

    Returns:
        List of search query strings
    """
    queries = []

    if macro.has_division:
        queries.append("division by zero undefined behavior macro")

    if macro.has_pointer_ops:
        queries.append("pointer dereference undefined behavior")

    if macro.has_casts:
        queries.append("type cast undefined behavior")

    # Search for function semantics
    for func in macro.function_calls:
        queries.append(f"{func} precondition semantics")

    # Search for referenced macro semantics
    for ref in macro.referenced_macros:
        queries.append(f"{ref} macro semantics")

    # If function-like with multiple parameter uses, search for evaluation
    if macro.is_function_like and macro.parameters:
        queries.append("macro argument evaluation side effects")

    return queries
