[ ] - distinguish "undefined" vs "implementation-defined" behavior in axioms (e.g., realloc(ptr, 0) is implementation-defined in C11 but the current axiom flags it as an error condition without this distinction)

[ ] - Fix Neo4j DEPENDS_ON graph cycles causing validate_claim timeout

    ## Problem
    The `get_proof_chain` query in `axiom/graph/loader.py:257` uses unbounded
    variable-length path traversal (`DEPENDS_ON*`) which causes exponential
    blowup when cycles exist in the graph.

    ## Current Graph Stats
    - Total axioms: 5,653
    - Total DEPENDS_ON edges: 6,980
    - Two-hop cycles (A→B→A): 190
    - Max out-degree: 19 dependencies per axiom

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

    ## Suggested Fix Order
    1. Immediate: Add path length bound (Option 1) to unblock usage
    2. Fix k_dependencies.py to exclude same-function axioms
    3. Re-run bootstrap to regenerate c11_core without cycles
    4. Verify cycles are eliminated

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
