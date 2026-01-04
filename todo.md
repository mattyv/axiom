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

[✅] - Complete ILP_FOR library axiom grounding (82% coverage, up from 62%)

    ## Current State (2025-12-31)
    **Major improvement after C++20 foundation expansion + re-linking:**
    - Before: 588/937 axioms with depends_on (62%)
    - After: 777/937 axioms with depends_on (82%)
    - Improvement: +189 axioms gained foundation links (+20%)

    ### Foundation Layers Expanded
    **C++20 Language Type System (cpp20_language.toml): 610 axioms**
    - ✅ dcl.enum (22) - Enum declarations with scoped enum (enum class)
    - ✅ temp.concept (10) - Concept definitions
    - ✅ temp.alias (7) - Template aliases
    - ✅ dcl.typedef (15) - Typedef declarations
    - ✅ class.mem (24) - Class member semantics
    - ✅ namespace.def (12) - Namespace definitions
    - ✅ namespace.alias (3) - Namespace aliases
    - ✅ dcl.type (42) - Type specifiers

    **C++20 Standard Library (cpp20_stdlib.toml): 1,026 axioms (3x increase)**
    - ✅ Type traits (153) - meta.unary.prop, meta.unary.cat, meta.trans.*
    - ✅ Concepts (34) - concepts.syn
    - ✅ Comparisons (57) - cmp.concept, cmp.alg
    - ✅ Concurrency (149) - thread.thread.class, thread.jthread.class, thread.stoptoken, atomics.*
    - ✅ Time/Chrono (101) - time.duration, time.point, time.cal
    - ✅ Coroutines (32) - coroutine.handle, coroutine.traits
    - ✅ Utilities (129) - views.span, bit.cast, bit.pow.two, func.invoke, function.objects
    - ✅ Numeric (50) - numeric.ops

    ### Type References Successfully Linked
    The re-linking found foundation axioms for:
    - reference (297 axioms)
    - range (114 axioms)
    - iterators (92 axioms)
    - lvalue/rvalue (100 axioms)
    - lambda expression (47 axioms)
    - template (40 axioms)
    - exceptions (21 axioms)
    - auto type deduction (16 axioms)

    ### Remaining Gaps (~18% unlinked)
    Still need foundation sections for:
    - [stmt.ranged] - Range-based for statement semantics
    - [range.range] - Range concept definition
    - [range.iota] - iota_view specification
    - [basic.scope] - Scope and block rules
    - Lambda capture semantics
    - Macro expansion rules

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

### Implementation Status

| Component | Status | Files |
|-----------|--------|-------|
| Data model (Pairing/Idiom) | ✅ Done | `axiom/models/pairing.py` |
| K semantics pairing extraction | ✅ Done | `axiom/extractors/k_pairings.py` |
| TOML manifest loading | ✅ Done | `scripts/load_pairings.py` |
| Graph schema (PAIRS_WITH) | ✅ Done | `axiom/graph/loader.py` |
| Search expansion | ✅ Done | `axiom/vectors/loader.py` |
| MCP integration | ✅ Done | `axiom/mcp/server.py` |
| C11 pairings loaded | ✅ Done | malloc→free, malloc→realloc, realloc→free |
| C++20 stdlib pairings TOML | ✅ Done | `knowledge/pairings/cpp20_stdlib.toml` |
| Comment annotation extraction | ✅ Done | `axiom/extractors/comment_annotations.py` |
| Spec text pairing extraction | ⏳ TODO | (parse C++ draft for pairing phrases) |
| Test co-occurrence mining | ⏳ TODO | (analyze test files for pairing patterns) |

### Universal Pairing Detection (Multi-Source)

| Source | Detection Method | Confidence | Status |
|--------|------------------|------------|--------|
| K semantics | Shared cell access | 1.0 | ✅ Implemented |
| TOML manifest | Author declaration | 1.0 | ✅ Implemented |
| Naming heuristics | Pattern matching | 0.7 | ✅ Implemented |
| Comment annotations | `@axiom:pairs_with` | 1.0 | ✅ Implemented |
| C++ draft spec | Language patterns | 1.0 | ⏳ TODO |
| Library tests | Co-occurrence | 0.9 | ⏳ TODO |

### Usage

```bash
# Load pairings from K semantics (C11 stdlib)
python scripts/load_pairings.py --dry-run

# Load pairings from TOML manifest (C++20 stdlib)
python scripts/load_pairings.py --toml knowledge/pairings/cpp20_stdlib.toml --dry-run

# Actually load (remove --dry-run)
python scripts/load_pairings.py
python scripts/load_pairings.py --toml knowledge/pairings/cpp20_stdlib.toml
```

### TOML Manifest Format

```toml
# knowledge/pairings/my-library.toml

[metadata]
layer = "my_library"
version = "1.0.0"

[[pairing]]
opener = "resource_acquire"
closer = "resource_release"
required = true
evidence = "Resource lifecycle management"

[[idiom]]
name = "scoped_resource"
participants = ["resource_acquire", "resource_release"]
template = '''
resource_acquire(r);
// use r
resource_release(r);
'''
```

### Graph Schema for Pairings

```cypher
// Pairing relationship
(opener:Axiom)-[:PAIRS_WITH {
    required: true,
    role: "opener",
    source: "k_semantics",
    cell: "malloced"
}]->(closer:Axiom)

// Idiom node
(:Idiom {id, name, template, source})

// Axiom participation in idiom
(func:Axiom)-[:PARTICIPATES_IN]->(idiom:Idiom)
```

### Key Insight

> Libraries are languages. Functions are words. Pairings are grammar. Templates are valid sentences.

The axiom system needs all three layers to prevent errors like missing ILP_END.

---

## MCP Testing Session Results (2025-12-31)

### Knowledge Base State After Full Ingestion

**Total Stats:**
- **2,571 axioms** total (up from 937 ilp_for-only)
- **1,174 modules**
- **1,636 vector embeddings**

**Layers Loaded:**
1. **c11_core** - C11 language semantics (899KB TOML)
2. **c11_stdlib** - C11 standard library (384KB TOML)
3. **cpp_core** - C++ core language (836KB TOML)
4. **cpp_stdlib** - C++ standard library (53KB TOML)
5. **cpp20_language** - C++20 language rules (425KB TOML, 610 axioms)
6. **cpp20_stdlib** - C++20 standard library (681KB TOML, 1,026 axioms)
7. **library (ilp_for)** - Custom library layer (937 axioms)

### Linking Coverage Analysis (Updated 2025-12-31)

**cpp20_stdlib** (Standard Library):
- Total axioms: 1,026
- With depends_on links: 350
- **Coverage: ~34% linked**
- Note: This is CORRECT - many stdlib axioms are standalone requirements
- Dependencies link to exception handling, initialization, type traits

**cpp20_language** (Core Language):
- Total axioms: 610
- With depends_on links: (needs recount after type system expansion)
- Expected coverage: ~40-50% linked
- Better coverage due to direct grounding in C11 foundations

**ilp_for** (Library) - AFTER RE-LINKING:
- Total axioms: 937
- With depends_on links: 777
- **Coverage: 82% linked** ✅ (up from 62%)
- Major improvement: +189 axioms gained foundation links
- Now properly linked to:
  - Type traits (is_trivial, remove_reference, etc.)
  - Concepts (ranges, iterators)
  - Type system (enums, templates, typedefs)
  - Concurrency primitives
  - Exception handling
- Example: `cpp20_algorithms_requirements_bidirectionaliterator_requirement` → `for_loop_range_typed_precond_n_valid_offset` (ilp_for)

### STL Coverage Verification

Tested semantic search and validation for common STL components:

**Smart Pointers (✅ Well Covered):**
- `std::shared_ptr` - constructor constraints, aliasing ctor, unique_ptr conversion
- `std::unique_ptr` - pointer compatibility, deleter requirements
- `std::weak_ptr` - expired check, bad_weak_ptr exceptions
- Example axiom: `cpp20_shared_ptr_aliasing_ctor_dangling_pointer_3e4f5a6b`
  > "Using aliasing constructor shared_ptr(r, p) leads to dangling pointer unless p remains valid until ownership group of r is destroyed"

**Containers (✅ Partial Coverage):**
- `std::span` - bounds checking, iterator requirements, default constructor postconditions
- `std::variant` - get<I>() throwing bad_variant_access, index() semantics
- `std::expected` - value_or() mandates, monadic operations (and_then)
- `std::any` - has_value() postconditions
- Example axiom: `cpp20_span_elem_subscript_hardened_u5v6w7x8`
  > "operator[](idx) hardened precondition: idx < size() must be true"

**Iterators & Algorithms (✅ Good Coverage):**
- Iterator requirements: ForwardIterator, BidirectionalIterator, mutable iterators
- Algorithm preconditions: `std::accumulate` (CopyConstructible + CopyAssignable)
- Data race guarantees: algorithms don't modify unless specified
- ranges::begin dispatch behavior
- Example axiom: `cpp20_algorithms_requirements_mutable_iterator_required_e5f2a8b4`
  > "If algorithm Effects modifies value via iterator, type shall meet mutable iterator requirements"

**Utilities (✅ Good Coverage):**
- `std::forward` - rvalue/lvalue forwarding, mandates on is_lvalue_reference_v<T>
- `std::move` - cast semantics (not actual move operation)
- `std::move_if_noexcept` - conditional cast for strong exception safety
- Type traits: is_void, is_abstract, is_polymorphic, completeness requirements
- Example axiom: `cpp20_forward_rvalue_overload_mandates_a3b7c9d1`
  > "Attempting to forward an rvalue as lvalue reference is ill-formed"

**Node Handles (✅ Specialized Coverage):**
- `node_handle::mapped()` - precondition: handle must be non-empty
- User-defined pair specialization UB warnings

### Validation Tool Critical Bugs Discovered

#### Bug #1: False Positives on Contradictory Claims (CRITICAL)

**Test Claims (All INCORRECT but marked VALID):**

1. ❌ "std::vector guarantees elements stored in reverse order"
   - Expected: Invalid
   - Actual: Valid (confidence 0.50)
   - Found axiom: `cpp20_cmp_alg_strong_order_float_comparison_consistency` (UNRELATED!)

2. ❌ "std::move performs a deep copy of the object"
   - Expected: Invalid
   - Actual: Valid (confidence 0.50)
   - Found axiom: `cpp20_move_returns_rvalue_ref_e4b6d2a8` (correct axiom but didn't detect contradiction!)
   - Reality: std::move is just `static_cast<remove_reference_t<T>&&>(t)` - no copying

3. ❌ "ForwardIterator requirements allow only single-pass iteration"
   - Expected: Invalid (that's InputIterator, not ForwardIterator)
   - Actual: Valid (confidence 0.50)
   - Found axiom: `cpp20_algorithms_requirements_forwarditerator_requirement_f5a6b7c8` (correct but no contradiction check)

4. ❌ "ILP_END can be used without matching ILP_FOR macro"
   - Expected: Invalid
   - Actual: Valid (confidence 0.50)
   - Found axiom: `cpp20_inclusive_scan_precond_movable_c5d0f8a3` (COMPLETELY UNRELATED!)

5. ❌ "std::span default constructor results in size() == 1 and data() == nullptr"
   - Expected: Invalid (size() should be 0, not 1)
   - Actual: Valid (confidence 0.50)
   - Found axiom: `cpp20_span_cons_default_postcond_k7l8m9n0` stating "size() == 0" (DIRECTLY CONTRADICTS CLAIM but not detected!)

**Root Cause Analysis:**

The validator (`axiom/reasoning/validator.py` and `proof_chain.py`) does:
1. Semantic search for related axioms via vector similarity
2. Return axioms with similar embeddings
3. **Assume similarity = support** ← BUG!

**Missing:** Logical entailment/contradiction detection. The system finds axioms in the same semantic domain but cannot:
- Detect when claim states opposite of axiom (size() == 1 vs size() == 0)
- Understand that "cast" contradicts "copy" (std::move case)
- Recognize completely unrelated matches (ILP_END → inclusive_scan)

#### Bug #2: Semantic Search Quality Issues

**Test: ILP_FOR Specific Claims**

Query: "ILP_RETURN ILP_END_RETURN pairing required"
- Expected: ilp_for pairing axioms
- Actual: `cpp20_expected_and_then_mandates` (std::expected, unrelated!)

**Root Cause:** Vector embeddings can't distinguish:
- "ILP_RETURN must pair with ILP_END_RETURN" (macro pairing)
- "expected::and_then result must pair with error_type E" (monadic pairing)

Both contain "pairing" and "required" → similar embeddings → bad match

**Workaround:** Section-based search works perfectly:

```python
mcp__axiom__search_by_section("ILP_END_RETURN")
# Returns:
# - ILP_END_RETURN_macro_marker_semantics (CORRECT!)
#   "paired with ILP_FOR* opening macros. Must be used instead of ILP_END when..."
```

### Working Validation Examples

Despite bugs, validation **does work** for clearly grounded claims:

✅ **"std::shared_ptr from unique_ptr requires compatible pointer types"**
- Valid: True, confidence 0.50
- Found: `cpp20_shared_ptr_ctor_unique_ptr_constraints_7e8f9a0b`
- Correct axiom, correct validation

✅ **"std::forward can forward rvalue as lvalue reference"**
- Valid: True, confidence 0.50
- Found: `cpp20_forward_rvalue_overload_mandates_a3b7c9d1` stating this is **ill-formed**
- Note: Claim was actually testing if validator catches this - it found the axiom saying it's wrong, but marked the claim as valid (BUG)

✅ **"std::variant::get throws bad_variant_access on wrong index"**
- Valid: True, confidence 0.50
- Found: `cpp20_variant_get_throws_bad_variant_access_q7r8s9t0`
- Correct axiom, correct validation

✅ **"std::accumulate requires CopyConstructible and CopyAssignable"**
- Valid: True, confidence 0.50
- Found: `cpp20_accumulate_precond_t_copyconstructible_a8f3d2e1`
- Perfect match

### What Works vs What Doesn't

| Feature | Status | Notes |
|---------|--------|-------|
| Axiom extraction | ✅ Excellent | 2,571 axioms, comprehensive coverage |
| Axiom storage | ✅ Excellent | Neo4j + LanceDB working well |
| Section search | ✅ Excellent | `search_by_section()` finds exact matches |
| Dependency linking | ✅ Good | 34-85% coverage, needs more linking work |
| Semantic search | ⚠️ Partial | Works for broad topics, fails on specific concepts |
| Claim validation | ❌ Broken | Cannot detect contradictions, poor axiom matching |
| Proof chains | ✅ Good | When correct axioms found, chains are valid |

### Recommended Fixes (Priority Order)

1. **CRITICAL: Add contradiction detection logic**
   - Compare claim semantics vs axiom semantics
   - Detect opposite values (size() == 1 vs size() == 0)
   - Understand semantic opposites (cast ≠ copy, safe ≠ undefined)
   - Options:
     - NLI model (sentence-transformers fine-tuned on entailment)
     - LLM reasoning step before marking valid
     - Expand keyword patterns for contradiction

2. **HIGH: Improve vector embeddings**
   - Current embeddings conflate "pairing" across different domains
   - Options:
     - Add layer/module prefix to embedding text
     - Fine-tune embedding model on axiom corpus
     - Use hybrid search (keyword + semantic)

3. **MEDIUM: Add validation confidence thresholds**
   - Current: all validations return 0.50 confidence (meaningless)
   - Should vary based on:
     - Axiom match quality
     - Number of supporting axioms
     - Contradiction check results

4. **LOW: Complete dependency linking**
   - cpp20_stdlib: 34% → target 80%+
   - Missing: containers, algorithms, ranges
   - Use semantic linker in batch mode

### Next Steps: Google Test Extraction

**Proposed:** Extract axioms from Google Test framework (~13k LOC, ~45-60 min extraction)

**Expected Axioms:**
- TEST/TEST_F macro preconditions
- ASSERT_*/EXPECT_* usage patterns
- Fixture lifecycle (SetUp/TearDown pairing)
- Death test requirements
- Parameterized test constraints
- Thread safety requirements

**Value:**
- Demonstrate extraction on widely-used framework
- Show axiom system works beyond parsers/containers
- ~400-600 axioms for testing domain
- Real-world library with clear preconditions

**Considerations:**
- Validation tool bugs mean we can't reliably validate claims about gtest after extraction
- But: extraction, storage, and section-based search work fine
- Primary value: expanding knowledge base, demonstrating capability
