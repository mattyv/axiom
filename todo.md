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

---

## Future C++20 Extraction Work

### std::move False Positive (needs investigation)
The claim "std::move moves object" validates as True (0.50). The axiom correctly
states std::move is a cast (`static_cast<remove_reference_t<T>&&>(t)`), but the
entailment classifier can't infer that "cast" contradicts "moves".

Options to explore:
1. Add clarifying axiom explicitly stating "std::move does not transfer/move anything"
2. Improve entailment logic to understand cast ≠ action
3. Accept current 0.50 confidence as "uncertain" (not high confidence)

### Priority 4: Containers & Iterators
- `associative.reqmts`, `unord.req`
- `iterator.requirements`, `iterator.operations`

### Priority 5: Algorithms & Ranges
- `algorithms.requirements`, `alg.sorting`
- `range.access`, `range.req`, `range.range`, `range.iota`

### Priority 6: Strings
- `basic.string`, `string.view`

### Priority 7: Concurrency
- `thread.mutex`, `thread.condition`, `futures`, `format`

### Retry (timed out during extraction)
- `optional`, `any`, `unique.ptr`, `util.smartptr.shared`

---

## Roadmap: Getting to 8-9/10 for Library Maintainers

### Current State: 5-6/10
The system works but requires manual effort. Library maintainers can extract axioms
but the process isn't streamlined.

### Target: 8-9/10 - Usable by Library Maintainers

#### 1. Streamlined Extraction CLI
**Goal**: `axiom extract ./my-library --output axioms.toml`

**Current state**:
- Extraction exists in `axiom/extractors/` but requires Python knowledge
- Multiple steps: extract → link → load to Neo4j → embed to LanceDB

**Implementation hints**:
- Create `axiom/cli/extract.py` with Click/Typer CLI
- Combine steps into single pipeline
- Auto-detect library type (header-only, CMake, etc.)
- Parse Doxygen/Javadoc comments for preconditions
- Use LLM to generate axioms from function signatures + comments

**Key files**:
- `axiom/extractors/library_extractor.py` - main extraction logic
- `axiom/extractors/prompts.py` - LLM prompts for axiom generation
- `axiom/ingestion/kb_integrator.py` - loads axioms to Neo4j + LanceDB

#### 2. Auto-Link to C++ Foundations
**Goal**: Automatically link library axioms to cpp20_language/cpp20_stdlib

**Current state**:
- Manual LLM-based linking via `axiom/extractors/semantic_linker.py`
- ~50% coverage on ILP_FOR library

**Implementation hints**:
- Batch process: for each library axiom, ask LLM "which C++20 concepts does this depend on?"
- Match LLM response to existing foundation axiom IDs via semantic search
- Add `depends_on` edges in Neo4j
- Validate: no cycles (use topological sort check before committing)

**Key files**:
- `axiom/extractors/semantic_linker.py` - LLM-based linking
- `axiom/extractors/library_depends_on.py` - dependency resolution
- `axiom/graph/loader.py` - Neo4j operations, `add_dependency()` method

#### 3. Validation Report for Maintainers
**Goal**: "90% of your library axioms are grounded to C++ foundations"

**Current state**:
- Can query ungrounded axioms via Neo4j
- No user-friendly report

**Implementation hints**:
- Add `axiom report ./my-library-axioms.toml` command
- Output: coverage %, ungrounded axioms list, suggested foundation links
- Use `get_ungrounded_axioms()` in `axiom/graph/loader.py`
- Generate markdown or HTML report
- Show dependency graph visualization

#### 4. Easy Integration with LLM Tools
**Goal**: Library maintainers publish axioms, LLM tools consume them

**Current state**:
- MCP server works (`axiom/mcp/server.py`)
- Requires local Neo4j + LanceDB setup

**Implementation hints**:
- Support standalone TOML/JSON axiom files (no database required for small libs)
- Publish axiom packages to registry (like npm for axioms)
- Claude/Cursor plugins that auto-fetch axioms for imported libraries
- WASM build of LanceDB for browser-based validation

---

## Roadmap: Getting to 9-10/10 for Safety-Critical Use

### Target: 9-10/10 - Production Safety Validation

#### 1. NLI/Entailment Model for Contradiction Detection
**Goal**: Semantically detect SUPPORTS vs CONTRADICTS vs NEUTRAL

**Current state**:
- Keyword matching in `axiom/reasoning/contradiction.py`
- Vocabulary mismatch causes false positives (std::move, double delete)

**Why it matters**:
- "std::move moves object" vs "std::move is a cast" - need to understand cast ≠ move
- "double delete is safe" vs "already freed" - need to understand freed = error

**Implementation hints**:
- Option A: Fine-tune sentence-transformers on (claim, axiom, label) triples
  - Labels: ENTAILS, CONTRADICTS, NEUTRAL
  - Training data: generate from axioms + known UB patterns
- Option B: LLM with structured output
  ```python
  prompt = f"Does axiom '{axiom}' support or contradict claim '{claim}'?"
  response = llm.generate(prompt, schema={"relationship": "enum", "reason": "str"})
  ```
- Option C: Hybrid - use embedding similarity to shortlist, LLM to classify

**Key files**:
- `axiom/reasoning/contradiction.py` - add entailment check after similarity
- `axiom/reasoning/entailment.py` - new file for NLI/LLM entailment logic

#### 2. Formal Verification Integration
**Goal**: Connect axioms to actual C/C++ verification tools

**Implementation hints**:
- Export axioms to ACSL format (Frama-C annotations)
- Generate CBMC assertions from preconditions
- Parse RV-Match/KCC output back into axiom violations
- CI integration: `axiom verify ./src --report violations.json`

**Example flow**:
```
axiom: "must not be a null pointer"
  → generates: /*@ requires ptr != NULL; */
  → Frama-C proves or finds counterexample
  → violation reported back to user
```

#### 3. Complete C++20 Standard Coverage
**Goal**: Every standard library function has axioms with signatures + preconditions

**Current state**:
- cpp20_language: partial coverage from standard quotes
- cpp20_stdlib: ~18 functions with signatures

**Implementation hints**:
- Systematic cppreference.com scraping (already have some)
- Focus areas by priority:
  1. Memory: `new`, `delete`, `malloc`, `free` (UB-heavy)
  2. Containers: `vector`, `map`, `unordered_map` (common)
  3. Algorithms: `sort`, `find`, `transform` (widely used)
  4. Concurrency: `mutex`, `thread`, `atomic` (subtle bugs)

#### 4. Real-Time Code Analysis
**Goal**: Validate code as it's written, not just natural language claims

**Key insight**: Code IS claims. When you write:
```cpp
ptr->foo;           // Implicit claim: "ptr is not null"
delete p; delete p; // Implicit claim: "double delete is valid"
vec[i];             // Implicit claim: "i is within bounds"
```

**Implementation hints**:
- Parse C++ AST (tree-sitter-cpp or libclang)
- Extract implicit claims from code patterns
- Match extracted claims against axioms
- LSP integration for real-time IDE warnings

**Key files to create**:
- `axiom/analysis/code_parser.py` - AST → implicit claims
- `axiom/analysis/claim_extractor.py` - pattern matching for common UB
- `axiom/lsp/server.py` - Language Server Protocol for IDE integration

---

## Compositional Semantics: Pairing & Idiom Detection

### The Problem
Libraries aren't just collections of functions with contracts. They're **vocabularies with grammar**.
Current axioms capture vocabulary (individual functions). Missing: grammar (how functions compose).

Example failure: Claude generated ILP_FOR examples without ILP_END because axioms describe
individual macros but not their required pairing.

### Universal Pairing Detection (Multi-Source)

| Source | Detection Method | Confidence | Example |
|--------|------------------|------------|---------|
| K semantics | Shared cell access | 1.0 | malloc/free share `<malloced>` cell |
| C++ draft spec | Language patterns | 1.0 | "matching deallocation function" |
| Library tests | Co-occurrence | 0.9 | ILP_FOR + ILP_END in all tests |
| Naming heuristics | Pattern matching | 0.7 | `X_begin`/`X_end`, `X_open`/`X_close` |
| Annotations | Author manifest | 1.0 | Explicit declaration |

### 1. K Semantics Pairing Extraction

K tracks pairing through configuration cells. Example from `stdlib.k`:

```k
# malloc - WRITES to cell
<malloced>... .Map => obj(!I, Align, alloc) |-> Sz ...</malloced>

# free - REMOVES from cell, checks membership
<malloced>... Base |-> _ => .Map ...</malloced>
requires notBool Base in_keys(Malloced)
  => UNDEF("STDLIB2", "Called free on memory not allocated by malloc")
```

**Extraction algorithm:**
```python
def extract_pairings_from_k(k_rules):
    cell_writers = {}  # cell -> [functions that add]
    cell_readers = {}  # cell -> [functions that remove/check]

    for rule in k_rules:
        for cell in rule.cells:
            if is_add_pattern(cell):      # .Map => X
                cell_writers[cell.name].append(rule.function)
            if is_remove_pattern(cell):   # X => .Map, in_keys check
                cell_readers[cell.name].append(rule.function)

    # Functions sharing same cell are paired
    for cell, writers in cell_writers.items():
        for w in writers:
            for r in cell_readers.get(cell, []):
                yield Pairing(opener=w, closer=r, cell=cell)
```

**Key files:**
- `axiom/extractors/k_semantics.py` - parse K rule cells
- `axiom/extractors/k_pairings.py` - new file for pairing extraction

### 2. Draft Spec Pairing Extraction

The C++ standard uses specific language patterns for pairing:

```python
PAIRING_PHRASES = [
    r"matching (deallocation|allocation) function",
    r"shall deallocate.*allocated by",
    r"corresponding (constructor|destructor)",
    r"shall be released by",
    r"must be paired with",
]

def extract_pairings_from_spec(section_text, section_ref):
    for pattern in PAIRING_PHRASES:
        if match := re.search(pattern, section_text):
            # Extract function names from surrounding context
            yield Pairing(
                opener=extract_opener(match),
                closer=extract_closer(match),
                source=f"spec:{section_ref}",
                evidence=match.group(0)
            )
```

**Key sections to parse:**
- `[basic.stc.dynamic]` - new/delete pairing
- `[class.ctor]` + `[class.dtor]` - constructor/destructor
- `[thread.mutex]` - lock/unlock
- `[utilities]` - RAII patterns

### 3. Library Test Mining

For libraries without K semantics or spec text:

```python
def extract_pairings_from_tests(test_files):
    co_occurrence = defaultdict(Counter)

    for file in test_files:
        functions_used = extract_function_calls(file)
        for f1, f2 in combinations(functions_used, 2):
            co_occurrence[f1][f2] += 1
            co_occurrence[f2][f1] += 1

    # High co-occurrence suggests pairing
    for func, partners in co_occurrence.items():
        for partner, count in partners.most_common(3):
            if count / total_uses[func] > 0.8:  # 80%+ co-occurrence
                yield Pairing(
                    opener=func,
                    closer=partner,
                    source="test_mining",
                    confidence=count / total_uses[func]
                )
```

### 4. Naming Heuristics

Detect standard naming patterns:

```python
PAIRING_PATTERNS = [
    (r"(.+)_begin$", r"\1_end"),
    (r"(.+)_start$", r"\1_stop"),
    (r"(.+)_open$", r"\1_close"),
    (r"(.+)_lock$", r"\1_unlock"),
    (r"(.+)_init$", r"\1_(cleanup|destroy|free|finish)"),
    (r"(.+)_acquire$", r"\1_release"),
    (r"create_(.+)$", r"destroy_\1"),
    (r"^(.+)$", r"end_\1"),  # X / end_X pattern
]
```

### 5. Library Author Annotations

Minimal manifest format (separate file, no code changes):

```toml
# my-library.axiom.toml

[library]
name = "ilp_for"
version = "1.0.0"

[[pairing]]
opener = "ILP_FOR"
closer = "ILP_END"
required = true
role_opener = "loop_start"
role_closer = "loop_end"

[[pairing]]
opener = "ILP_FOR_T"
closer = "ILP_END"
required = true

[[idiom]]
name = "ilp_for_loop"
participants = ["ILP_FOR", "ILP_END"]
template = '''
ILP_FOR(${type} ${var}, ${start}, ${end}, ${N}) {
    ${body}
} ILP_END
'''
```

### Auto-Generation + Review Workflow

```bash
# 1. Auto-detect pairings from all sources
axiom extract-pairings ./my-library \
    --tests ./tests \
    --headers ./include \
    --output pairings.toml

# 2. Author reviews, fixes false positives/negatives

# 3. Integrate into axiom extraction
axiom extract ./my-library \
    --pairings pairings.toml \
    --output axioms.toml
```

### Graph Schema for Pairings

New relationship types in Neo4j:

```cypher
// Pairing relationship
(opener:Axiom)-[:PAIRS_WITH {
    required: true,
    role: "opener",
    source: "k_semantics",
    cell: "malloced"
}]->(closer:Axiom)

// Idiom participation
(func:Axiom)-[:PARTICIPATES_IN {
    role: "opener"
}]->(idiom:Idiom)

// Idiom node with template
CREATE (i:Idiom {
    id: "ilp_for_loop",
    name: "ILP FOR Loop",
    template: "ILP_FOR(...) { ... } ILP_END"
})
```

### Modified Search Behavior

When searching for a function, auto-expand to include paired functions:

```python
def search_with_pairings(query):
    results = semantic_search(query)

    expanded = []
    for axiom in results:
        expanded.append(axiom)

        # Get paired functions
        paired = neo4j.query("""
            MATCH (a:Axiom {id: $id})-[:PAIRS_WITH]-(paired:Axiom)
            RETURN paired
        """, id=axiom.id)

        for p in paired:
            expanded.append(p)

        # Get idiom templates
        idioms = neo4j.query("""
            MATCH (a:Axiom {id: $id})-[:PARTICIPATES_IN]->(i:Idiom)
            RETURN i
        """, id=axiom.id)

        for idiom in idioms:
            expanded.append(idiom)  # Include template!

    return dedupe(expanded)
```

### Key Insight

> Libraries are languages. Functions are words. Pairings are grammar. Templates are valid sentences.

The axiom system needs all three layers to prevent errors like missing ILP_END.
