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

For each operation that has semantic requirements:

1. Identify the specific precondition, postcondition, or invariant
2. Match it to a foundation axiom from the list above
3. Extract the formal specification using the operands from the subgraph

Output ONLY valid TOML with the following structure for each axiom:

```toml
[[axioms]]
id = "<generated_unique_id>"
function = "{function_name}"
header = "<header_file>"
axiom_type = "<precondition|postcondition|invariant|constraint>"
content = "<human-readable description>"
formal_spec = "<formal condition using actual operand names>"
on_violation = "<what happens: undefined behavior, throws, returns error, etc.>"
depends_on = ["<foundation_axiom_id>"]
source_operation_id = "<operation_id from subgraph>"
source_line = <line_number>
confidence = <0.0-1.0>
```

### Guidelines

- Use actual variable names from the subgraph operands
- Include guard conditions if the operation is protected by a check
- Link to the most specific foundation axiom available
- Set confidence based on how clearly the axiom applies:
  - 1.0: Direct match to foundation axiom, no ambiguity
  - 0.8-0.9: Clear semantic requirement, foundation axiom applies
  - 0.6-0.7: Likely applies but context-dependent
  - <0.6: Uncertain, may need human review

If an operation is already guarded (has guard conditions that prevent the hazard),
note this in the content but still extract the axiom with the guard as the formal_spec.

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
