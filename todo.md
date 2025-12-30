[ ] - distinguish "undefined" vs "implementation-defined" behavior in axioms (e.g., realloc(ptr, 0) is implementation-defined in C11 but the current axiom flags it as an error condition without this distinction)

[ ] - Validator returns false positives for contradictory claims (CRITICAL)

    ## Problem
    The validator uses semantic similarity search to find related axioms, then
    assumes they support the claim. It does NOT check logical entailment or
    detect contradictions.

    ## Examples of False Positives
    1. "Signed integer overflow in C wraps around using two's complement"
       - Validated as: True, confidence 1.00
       - Reality: Signed overflow is UB in C, not defined wrap

    2. "Dereferencing a null pointer in C is completely safe and well-defined"
       - Validated as: True, confidence 1.00
       - Axiom found: "Null pointer passed to strcpy" (error condition!)
       - Reality: Null deref is UB

    ## Root Cause
    `axiom/reasoning/validator.py` and `proof_chain.py` do:
    1. Semantic search for related axioms
    2. Check if axiom text mentions similar concepts
    3. Assume match = support

    Missing: actual contradiction detection between claim semantics and axiom
    semantics (e.g., "safe" vs "error", "defined" vs "undefined behavior")

    ## Detailed Root Cause Analysis

    ### 1. Vocabulary Mismatch
    The contradiction detector looks for "undefined behavior" in axiom content:
    ```python
    danger_warnings = ["undefined", "unsafe", "invalid", ...]
    ```

    But K semantics axioms use precondition language:
    - "must not be a null pointer"
    - "Operation requires: NOT: isNull(ptr)"

    Stats from Neo4j:
    - Axioms with "undefined behavior": 9
    - Axioms with "must not" / "requires": 1,583

    ### 2. Word Form Mismatch
    `_is_dangerous_claim` fuzzy match fails on word forms:
    - DANGEROUS_CLAIMS has "null pointer dereference is safe"
    - Claim uses "dereferencing" (gerund) not "dereference"
    - Exact word match fails

    ### 3. Axiom Content Too Terse
    Example axiom for null pointer:
    ```
    c11_c_memory_reading_syntax_operation_8c395fed:
    "Operation requires: ... must not be a null pointer"
    ```

    This should trigger contradiction with "null deref is safe" but:
    - No "undefined" keyword
    - No "unsafe" keyword
    - Just a precondition constraint

    ## Potential Fixes
    1. **Expand danger_warnings vocabulary** to include K semantics patterns:
       - "must not", "requires: NOT", "shall not", "error", "invalid"

    2. **Add lemmatization** for fuzzy matching:
       - "dereferencing" → "dereference"
       - Use spaCy or NLTK for word stemming

    3. **Add axiom metadata** during extraction:
       - `is_constraint: true` for precondition axioms
       - `violation_is_ub: true` for UB-causing violations

    4. **NLI model** to check entailment/contradiction semantically

    5. **LLM reasoning step** to compare claim vs axiom and classify

    6. **Invert logic for constraint axioms**:
       - If axiom says "requires X" and claim says "X is not needed" → contradiction
       - If axiom says "must not X" and claim says "X is safe" → contradiction

[ ] - Fix Neo4j DEPENDS_ON graph cycles causing validate_claim timeout

    ## Problem
    The `get_proof_chain` query in `axiom/graph/loader.py:257` uses unbounded
    variable-length path traversal (`DEPENDS_ON*`) which causes exponential
    blowup when cycles exist in the graph.

    ## Current Graph Stats
    - Total axioms: 5,653
    - Total DEPENDS_ON edges: 6,980
    - Two-hop cycles (A→B→A): 62 (down from 190)
    - Max out-degree: 19 dependencies per axiom
    - c11_core cycles: FIXED
    - Remaining cycles: all in library layer

    ## Root Cause
    The query pattern:
    ```cypher
    MATCH path = (a:Axiom {id: $id})-[:DEPENDS_ON*]->(foundation:Axiom)
    WHERE foundation.layer IN ['c11_core', ...]
    ```

    With 190 cycles, this explores paths repeatedly, causing timeout on
    validate_claim requests.

    ## Affected Code
    - `axiom/graph/loader.py:270-279` - get_proof_chain query
    - `axiom/reasoning/proof_chain.py:150` - calls get_proof_chain
    - `axiom/reasoning/validator.py:71` - calls proof_generator.generate
    - `axiom/mcp/server.py:201` - synchronous validator.validate blocks

    ## Fixes Required (choose one or combine)

    ### Option 1: Bound the path length
    Change `DEPENDS_ON*` to `DEPENDS_ON*1..10` to limit traversal depth.
    Quick fix but doesn't address root cause.

    ### Option 2: Add cycle detection in query
    ```cypher
    MATCH path = (a:Axiom {id: $id})-[:DEPENDS_ON*1..10]->(foundation:Axiom)
    WHERE foundation.layer IN ['c11_core', ...]
      AND ALL(n IN nodes(path) WHERE single(x IN nodes(path) WHERE x = n))
    ```
    Ensures no node appears twice in path.

    ### Option 3: Remove cycles from graph (recommended)
    Identify and remove bidirectional dependencies:
    ```cypher
    MATCH (a:Axiom)-[:DEPENDS_ON]->(b:Axiom)-[:DEPENDS_ON]->(a)
    RETURN a.id, b.id
    ```
    These represent incorrect axiom relationships - A depends on B AND B depends
    on A shouldn't exist in a proper dependency graph.

    ### Option 4: Make validation async
    The MCP server calls `validator.validate(claim)` synchronously at line 201.
    Could use asyncio.to_thread() to prevent blocking, but this just hides the
    performance issue rather than fixing it.

    ## Root Cause Analysis
    The bug is in `axiom/extractors/k_dependencies.py:126-142`:

    ```python
    def resolve_depends_on(calls: list[str], index: dict[str, list[str]]) -> list[str]:
        deps: list[str] = []
        for func in calls:
            if func in index:
                deps.extend(index[func])  # Adds ALL axioms for that function
        return deps
    ```

    When function `foo` has multiple axioms (A and B for different cases), and A's
    RHS references functions that B's RHS also references, they create mutual
    dependencies.

    Example from the graph:
    - `c11_c_check_restrict_syntax_operation_2a6a0e44` and
      `c11_c_check_restrict_syntax_operation_915ba6ae` are both axioms for the
      SAME function `check_restrict_syntax_operation`
    - Each RHS references functions defined by the other
    - Result: A depends on B, B depends on A

    The self-reference check at line 197 (`d != axiom.id`) only removes exact
    self-matches, not other axioms for the same function.

    ## Fix for k_dependencies.py
    Change line 191-199 to exclude axioms for the same function:

    ```python
    for axiom in axioms:
        rhs = axiom_rhs_map.get(axiom.id, "")
        calls = extract_function_calls(rhs)
        deps = resolve_depends_on(calls, index)

        # Remove self-reference AND other axioms for the same function
        same_function_axioms = set(index.get(axiom.function, []))
        deps = [d for d in deps if d not in same_function_axioms]

        axiom.depends_on = deps
    ```

    ## Remaining Library Layer Cycles (62)
    Examples:
    - `ilp_end_with_return_error_exception_no_throw` ↔ `return_with_exception_noexcept_if_r_noexcept`
    - `ctrl_r_conversion_operator_*` ↔ `extract_constraint_type_r_moveable`

    These are from LLM-based library linking where related concepts got linked
    bidirectionally. The LLM linker needs to enforce DAG structure.

    ## Suggested Fix Order
    1. [DONE] Fix k_dependencies.py - c11_core cycles eliminated
    2. Add path length bound to query as safety measure
    3. Fix library linking to enforce DAG (no bidirectional links)
    4. Re-run library linking to eliminate remaining 62 cycles

[ ] - Complete ILP_FOR library axiom grounding (~50% coverage, up from 25%)

    ## Current State (improved)
    Several axioms now have 6+ dependencies reaching C++20 foundations:

    ### Grounded with C++20 Foundation Links
    - ilp_for_t_auto_complexity_iota_construction (6 deps)
      -> cpp20_basic_life_vacuous_initialization_def_7c4e5d6a (foundation)
    - ilp_for_t_auto_effect_single_eval_parenthesized (6 deps)
      -> cpp20_basic_life_vacuous_initialization_def_7c4e5d6a (foundation)
    - ilp_for_t_auto_postcond_range_for_expansion (4 deps)
    - ilp_for_t_auto_precond_start_end_valid (3 deps)
    - ilp_for_t_auto_constraint_requires_cpp11 (4 deps)
    - ilp_for_t_auto_macro_effect_no_side_effects_expansion (2 deps)

    ### Still Ungrounded (~7 axioms)
    - ilp_for_t_auto_macro_effect_context_variable
    - ilp_for_auto_macro_constraint_loop_var_shadowing
    - ilp_for_t_auto_macro_complexity_lambda_overhead
    - ilp_for_t_auto_macro_postcondition_if_condition
    - ilp_for_auto_effect_namespace_qualified
    - ilp_for_t_auto_precond_iota_visible
    - ilp_for_auto_postcondition_range_for_loop

    ## Key C++20 Foundation Sections Still Needed
    - [stmt.ranged] - Range-based for statement semantics
    - [range.range] - Range concept definition
    - [range.iota] - iota_view specification
    - [basic.scope] - Scope and block rules

---

## Testing Session Results (2024-12-31)

### Fixes Deployed
1. [x] k_dependencies.py - exclude same-function axioms from depends_on (prevents c11_core cycles)
2. [x] loader.py - added path length bound `*1..10` and cycle detection to get_proof_chain query
3. [x] Contradiction detector improvements (vocabulary expansion)

### Validation Test Results (After Fixes)

| Claim | Before | After | Status |
|-------|--------|-------|--------|
| "Null pointer deref is safe" | True (1.00) | **False (0.10)** | ✅ FIXED |
| "Signed overflow wraps (two's complement)" | True (1.00) | **False (0.10)** | ✅ FIXED |
| "std::move moves object to new location" | True (0.95) | True (0.50) | ⚠️ Still wrong, lower confidence |
| "Double delete is safe" | - | True (0.50) | ⚠️ Wrong - axiom found but not flagged |
| "ILP_FOR_T_AUTO needs 6 params" | - | True (0.50) | ✅ Correct |

### Performance
- Queries now run fast (sub-second) vs 2+ minute timeouts before
- c11_core cycles eliminated (190 → 0)
- Library layer cycles remain (62) but bounded query prevents hangs

### Remaining Issues
1. **std::move false positive**: Axioms about move semantics found, but they describe
   actual moves, not what `std::move()` itself does (it's just a cast)

2. **Double delete false positive**: Axiom "Called free on memory... already freed"
   found but phrasing doesn't trigger contradiction detection (no "undefined"/"unsafe")

3. **Vocabulary gap**: Error-condition axioms from K semantics don't use
   "undefined behavior" language, so some contradictions slip through
