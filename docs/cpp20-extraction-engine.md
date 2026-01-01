# C++20 Axiom Extraction Engine

A comprehensive design for extracting axioms from any C++20 codebase with high quality and minimal LLM usage.

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Phase 1: Clang Analysis** | ✅ Complete | Native C++ tool using LibTooling |
| **Phase 2: Explicit Constraints** | ✅ Complete | noexcept, nodiscard, const, constexpr, delete, requires, static_assert, concepts, enums, type aliases |
| **Phase 3: Hazard Detection** | ✅ Complete | Division, pointer deref, array access with guard analysis |
| **Phase 4: Call Graph** | ❌ Not Started | Precondition propagation (future) |
| **Phase 5: Foundation Linking** | ✅ Complete | LanceDB semantic search integration |
| **Phase 6: LLM Assist** | ⚠️ Placeholder | TODO in extract_clang.py |

### Quick Start

```bash
# Build the C++ tool
cd tools/axiom-extract && mkdir build && cd build
cmake .. && make

# Extract from a library (recursive)
python scripts/extract_clang.py \
    -r --file /path/to/library \
    --output axioms.toml

# With compile_commands.json
python scripts/extract_clang.py \
    --compile-commands /path/to/build/compile_commands.json \
    --output axioms.toml
```

### Key Files

| File | Purpose |
|------|---------|
| `tools/axiom-extract/` | Native C++ extraction tool |
| `scripts/extract_clang.py` | Python wrapper with LanceDB linking |
| `axiom/extractors/clang_loader.py` | JSON → AxiomCollection conversion |

---

## Design Philosophy

1. **Exploit what C++20 gives us** - Modern C++ is increasingly explicit about constraints
2. **Clang for semantics** - Full type resolution, template instantiation, control flow
3. **Rules for patterns** - Hazard detection is pattern matching, not understanding
4. **Propagation for completeness** - Call graph analysis propagates preconditions
5. **LLM only for gaps** - ~5% of cases, batched and targeted

## Two Complementary Axiom Sources

This engine extracts axioms from **code** (what the implementation does). It complements the existing spec-based extraction (what the standard says):

```
┌─────────────────────────────────────┐
│   C++ Standard Spec (eel.is)        │  ← Existing approach (LLM extraction)
│   "What the standard guarantees"    │
│   - Formal semantics                │
│   - UB definitions                  │
│   - Algorithm complexity            │
│   - Confidence: 0.85                │
└─────────────────────────────────────┘
                    +
┌─────────────────────────────────────┐
│   Actual C++ Code (Clang analysis)  │  ← This engine
│   "What the code actually does"     │
│   - Compiler-enforced constraints   │
│   - Hazardous operations            │
│   - Call graph preconditions        │
│   - Confidence: 0.95-1.0            │
└─────────────────────────────────────┘
                    =
┌─────────────────────────────────────┐
│   Combined Knowledge Base           │
│   - Spec axioms validate code       │
│   - Code axioms ground spec claims  │
│   - Cross-validation possible       │
└─────────────────────────────────────┘
```

## Confidence-Based Extraction Hierarchy

Extraction sources are tried in order of confidence, falling back to LLM only when needed:

```
┌────────┬──────────────────────────────────────────────────────────┐
│  1.0   │ Clang: Compiler-enforced (noexcept, [[nodiscard]], etc) │
├────────┼──────────────────────────────────────────────────────────┤
│  0.95  │ Clang: Pattern + CFG (hazard with guard analysis)       │
├────────┼──────────────────────────────────────────────────────────┤
│  0.90  │ Clang: Propagated (inherited from callee preconditions) │
├────────┼──────────────────────────────────────────────────────────┤
│  0.85  │ Spec KB: Matched to foundation axiom (eel.is extract)   │
├────────┼──────────────────────────────────────────────────────────┤
│  0.70  │ LLM Fallback: Batched, targeted questions (~5% of code) │
└────────┴──────────────────────────────────────────────────────────┘
```

**The flow:**

```
Source code
    │
    ▼
┌─────────────────────────────┐
│  Clang extraction           │  ← Try first (fast, accurate)
│  - Explicit constraints     │
│  - Hazard detection + CFG   │
└─────────────────────────────┘
    │
    │ confidence >= 0.95? ──────────────────► Done ✓
    │
    ▼
┌─────────────────────────────┐
│  Match to spec axioms       │  ← Link to foundation KB
│  (existing extracted KB)    │
└─────────────────────────────┘
    │
    │ confidence >= 0.85? ──────────────────► Done ✓
    │
    ▼
┌─────────────────────────────┐
│  LLM assist (batched)       │  ← Last resort
│  "Given this pattern,       │
│   what's the precondition?" │
└─────────────────────────────┘
    │
    ▼
   Done (confidence 0.70)

## Architecture Overview

```
                         C++ Source Files
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Phase 1: Clang Semantic Analysis               │
│  - Full AST with type info                                        │
│  - Template instantiation                                         │
│  - Control flow graphs                                            │
│  - Data flow analysis                                             │
└───────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                Phase 2: Explicit Constraint Extraction            │
│  - C++20 concepts & requires clauses                              │
│  - noexcept specifications                                        │
│  - [[nodiscard]], [[deprecated]]                                  │
│  - static_assert declarations                                     │
│  - = delete specifications                                        │
│  - const/constexpr qualifiers                                     │
└───────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│              Phase 3: Hazard Detection & Pattern Matching         │
│  - Division operations → divisor != 0                             │
│  - Pointer dereference → ptr != nullptr                           │
│  - Array access → index < size                                    │
│  - Memory ops → valid allocation                                  │
│  - Guard detection (if checks before hazard)                      │
└───────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                  Phase 4: Call Graph & Propagation                │
│  - Build complete call graph                                      │
│  - Propagate callee preconditions to callers                      │
│  - Detect precondition satisfaction at call sites                 │
│  - Virtual dispatch handling                                      │
└───────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Phase 5: Foundation Linking                    │
│  - Match extracted axioms to foundation axioms                    │
│  - Link via semantic similarity (embeddings)                      │
│  - Establish depends_on relationships                             │
└───────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                 Phase 6: LLM Assist (Minimal, Targeted)           │
│  - Only for low-confidence cases                                  │
│  - Batched (10+ functions per call)                               │
│  - Specific questions, not open-ended                             │
│  - Validate LLM output against code structure                     │
└───────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                          TOML Export
```

---

## Phase 1: Clang Semantic Analysis

### Why Clang Instead of tree-sitter

| Feature | tree-sitter | Clang |
|---------|-------------|-------|
| Type resolution | No | Full |
| Template instantiation | No | Yes |
| Macro expansion | No | Yes |
| Control flow graph | No | Yes |
| Data flow analysis | No | Yes |
| Cross-file analysis | Limited | Full |
| Overload resolution | No | Yes |

### Implementation: Native C++ Tool (Recommended)

**Why C++ instead of Python libclang:**
- libclang Python bindings are incomplete (many AST nodes not exposed)
- C++20 features (concepts, requires) have limited Python support
- CFG/dataflow analysis requires direct Clang C++ API access
- Better performance for large codebases

**Architecture:**

```
┌─────────────────────────────────────────┐
│         axiom-extract (C++)             │
│  - Uses Clang's LibTooling              │
│  - Full AST/CFG/dataflow access         │
│  - Outputs JSON                         │
├─────────────────────────────────────────┤
│  Input: compile_commands.json           │
│         or directory with -r flag       │
│  Output: extracted_axioms.json          │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│         Python (existing axiom/)        │
│  - Loads JSON output                    │
│  - Foundation linking (embeddings)      │
│  - LLM assist (batched)                 │
│  - TOML export                          │
└─────────────────────────────────────────┘
```

**Implemented Tool Structure:**

```
tools/axiom-extract/
├── CMakeLists.txt           # Build configuration
├── include/
│   ├── Axiom.h              # Axiom data structures
│   ├── Extractors.h         # Extractor interfaces
│   └── IgnoreFilter.h       # .axignore pattern matching
└── src/
    ├── main.cpp             # Entry point, AST matchers, JSON output
    ├── ConstraintExtractor.cpp  # noexcept, nodiscard, const, etc.
    ├── HazardDetector.cpp   # CFG-based hazard detection
    ├── GuardAnalyzer.cpp    # Dominator-based guard detection
    └── MacroExtractor.cpp   # Preprocessor macro extraction
```

**Command Line Options:**

```bash
axiom-extract [options] <source files or directories>

Options:
  -r, --recursive      Recursively scan directories for C++ files
  -o, --output FILE    Write JSON to file instead of stdout
  -v, --verbose        Enable verbose output
  --hazards           Enable hazard detection (division, deref, array)
  --ignore FILE       Path to .axignore file
  --no-ignore         Disable .axignore filtering
  -p PATH             Path to compile_commands.json directory
  -- <clang args>     Extra arguments passed to Clang
```

**Build with CMake:**

```bash
cd tools/axiom-extract
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

**Essential: compile_commands.json**

Real C++ projects require a compilation database:

```bash
# CMake projects
cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON ..

# Meson projects
meson setup build

# Any build system (via Bear)
bear -- make
```

Without this, Clang can't resolve includes, macros, or flags.

### Alternative: Python libclang (Limited)

For simple extraction (explicit constraints only), Python bindings work:

```python
import clang.cindex

def analyze_file(filepath: str) -> dict:
    """Extract semantic information from a C++ file."""
    index = clang.cindex.Index.create()
    tu = index.parse(filepath, args=['-std=c++20'])

    functions = {}
    for cursor in tu.cursor.walk_preorder():
        if cursor.kind == clang.cindex.CursorKind.FUNCTION_DECL:
            functions[cursor.spelling] = extract_function_info(cursor)

    return functions

def extract_function_info(cursor) -> dict:
    """Extract all relevant info from a function declaration."""
    return {
        'name': cursor.spelling,
        'qualified_name': cursor.displayname,
        'return_type': cursor.result_type.spelling,
        'parameters': extract_parameters(cursor),
        'is_noexcept': is_noexcept(cursor),
        'is_nodiscard': has_attribute(cursor, 'nodiscard'),
        'is_const': cursor.is_const_method(),
        'is_virtual': cursor.is_virtual_method(),
        'requires_clause': extract_requires(cursor),
        'body': extract_body(cursor),
    }
```

**Limitation:** CFG/dataflow analysis not available in Python bindings.

### AST Database Schema

```sql
-- Core function information
CREATE TABLE functions (
    id TEXT PRIMARY KEY,
    file TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT,
    signature TEXT NOT NULL,
    return_type TEXT,
    line_start INTEGER,
    line_end INTEGER,
    body_hash TEXT,  -- For incremental analysis

    -- C++20 attributes (directly extractable)
    is_template BOOLEAN DEFAULT FALSE,
    is_noexcept BOOLEAN DEFAULT FALSE,
    is_nodiscard BOOLEAN DEFAULT FALSE,
    is_const BOOLEAN DEFAULT FALSE,
    is_constexpr BOOLEAN DEFAULT FALSE,
    is_consteval BOOLEAN DEFAULT FALSE,
    is_static BOOLEAN DEFAULT FALSE,
    is_virtual BOOLEAN DEFAULT FALSE,
    is_deleted BOOLEAN DEFAULT FALSE,
    is_defaulted BOOLEAN DEFAULT FALSE
);

-- Function parameters with full type info
CREATE TABLE parameters (
    id INTEGER PRIMARY KEY,
    function_id TEXT REFERENCES functions(id),
    position INTEGER NOT NULL,
    name TEXT,
    type TEXT NOT NULL,
    canonical_type TEXT,  -- Resolved through typedefs
    is_const BOOLEAN DEFAULT FALSE,
    is_pointer BOOLEAN DEFAULT FALSE,
    is_reference BOOLEAN DEFAULT FALSE,
    is_rvalue_ref BOOLEAN DEFAULT FALSE,
    has_default BOOLEAN DEFAULT FALSE
);

-- C++20 concepts and requires clauses
CREATE TABLE constraints (
    id INTEGER PRIMARY KEY,
    function_id TEXT REFERENCES functions(id),
    constraint_type TEXT NOT NULL,  -- 'requires', 'concept', 'enable_if', 'static_assert'
    expression TEXT NOT NULL,
    is_compiler_enforced BOOLEAN DEFAULT TRUE,
    confidence REAL DEFAULT 1.0
);

-- Detected hazardous operations
CREATE TABLE hazards (
    id INTEGER PRIMARY KEY,
    function_id TEXT REFERENCES functions(id),
    hazard_type TEXT NOT NULL,  -- 'division', 'pointer_deref', 'array_access', 'cast'
    expression TEXT NOT NULL,
    operand TEXT,  -- The variable/expression being checked
    line INTEGER,
    has_guard BOOLEAN DEFAULT FALSE,
    guard_expression TEXT,
    guard_line INTEGER,
    guard_type TEXT  -- 'if_check', 'assert', 'early_return', 'exception'
);

-- Function calls for call graph
CREATE TABLE calls (
    id INTEGER PRIMARY KEY,
    caller_id TEXT REFERENCES functions(id),
    callee_name TEXT NOT NULL,
    callee_qualified_name TEXT,
    callee_id TEXT REFERENCES functions(id),  -- Resolved after initial pass
    line INTEGER,
    is_virtual BOOLEAN DEFAULT FALSE,
    arguments TEXT  -- JSON array of argument expressions
);

-- Generated axioms
CREATE TABLE axioms (
    id TEXT PRIMARY KEY,
    function_id TEXT REFERENCES functions(id),
    axiom_type TEXT NOT NULL,
    content TEXT NOT NULL,
    formal_spec TEXT,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,  -- 'explicit', 'pattern', 'propagated', 'llm'
    rule_id TEXT,
    foundation_link TEXT,
    needs_review BOOLEAN DEFAULT FALSE
);
```

---

## Phase 2: Explicit Constraint Extraction

### What C++20 Gives Us (100% Confidence)

These are compiler-enforced constraints that translate directly to axioms:

| C++20 Feature | Example | Axiom Type | Confidence |
|---------------|---------|------------|------------|
| `requires` clause | `requires std::integral<T>` | constraint | 1.0 |
| `concept` | `template<std::integral T>` | constraint | 1.0 |
| `noexcept` | `void f() noexcept` | exception | 1.0 |
| `noexcept(expr)` | `noexcept(sizeof(T) < 8)` | conditional exception | 1.0 |
| `[[nodiscard]]` | `[[nodiscard]] int f()` | postcondition | 1.0 |
| `[[nodiscard("msg")]]` | `[[nodiscard("check error")]]` | postcondition + reason | 1.0 |
| `const` method | `int get() const` | effect (no mutation) | 1.0 |
| `constexpr` | `constexpr int f()` | compile-time evaluable | 1.0 |
| `consteval` | `consteval int f()` | must be compile-time | 1.0 |
| `static_assert` | `static_assert(sizeof(T) == 4)` | invariant | 1.0 |
| `= delete` | `void f() = delete` | not callable | 1.0 |

### Extraction Rules

```python
EXPLICIT_CONSTRAINT_RULES = [
    # C++20 requires clause
    Rule(
        id="requires_clause",
        axiom_type="constraint",
        query="""
            SELECT f.id, f.name, c.expression
            FROM functions f
            JOIN constraints c ON f.id = c.function_id
            WHERE c.constraint_type = 'requires'
        """,
        template=lambda r: f"Template parameters must satisfy: {r['expression']}",
        formal_spec=lambda r: r['expression'],
        confidence=1.0,
        source="explicit"
    ),

    # noexcept specification
    Rule(
        id="noexcept_spec",
        axiom_type="exception",
        query="SELECT id, name FROM functions WHERE is_noexcept = TRUE",
        template=lambda r: f"{r['name']} is guaranteed not to throw exceptions",
        formal_spec=lambda r: "noexcept == true",
        confidence=1.0,
        source="explicit"
    ),

    # [[nodiscard]] attribute
    Rule(
        id="nodiscard_attr",
        axiom_type="postcondition",
        query="SELECT id, name, return_type FROM functions WHERE is_nodiscard = TRUE",
        template=lambda r: f"Return value of {r['name']} must not be discarded",
        formal_spec=lambda r: "[[nodiscard]]",
        confidence=1.0,
        source="explicit"
    ),

    # const method
    Rule(
        id="const_method",
        axiom_type="effect",
        query="SELECT id, name FROM functions WHERE is_const = TRUE",
        template=lambda r: f"{r['name']} does not modify object state",
        formal_spec=lambda r: "this->state == old(this->state)",
        confidence=1.0,
        source="explicit"
    ),

    # deleted function
    Rule(
        id="deleted_function",
        axiom_type="constraint",
        query="SELECT id, name FROM functions WHERE is_deleted = TRUE",
        template=lambda r: f"{r['name']} is explicitly deleted and cannot be called",
        formal_spec=lambda r: "callable == false",
        confidence=1.0,
        source="explicit"
    ),
]
```

---

## Phase 3: Hazard Detection & Pattern Matching

### Hazard Types and Their Preconditions

| Hazard | Detection Pattern | Precondition Template | Foundation Link |
|--------|-------------------|----------------------|-----------------|
| Division | `a / b`, `a % b` | `b != 0` | `cpp20.undefined.division_by_zero` |
| Pointer deref | `*p`, `p->m` | `p != nullptr` | `cpp20.undefined.null_dereference` |
| Array access | `a[i]` | `i >= 0 && i < size(a)` | `cpp20.undefined.out_of_bounds` |
| C-style cast | `(T*)p` | varies | `cpp20.undefined.invalid_cast` |
| Signed overflow | `a + b` (signed) | `no_overflow(a, b)` | `cpp20.undefined.signed_overflow` |

### Guard Detection

A hazard is "guarded" if there's a dominating check:

```cpp
// Guarded - if check dominates dereference
if (ptr != nullptr) {
    return ptr->value;  // Safe
}

// Guarded - assert before use
assert(ptr != nullptr);
*ptr = value;  // Safe

// Guarded - early return
if (!ptr) return error;
use(ptr->data);  // Safe

// UNGUARDED - no check
return ptr->value;  // Needs precondition
```

### Guard Detection Algorithm

```python
def detect_guards(function_cfg, hazard) -> Optional[Guard]:
    """
    Detect if a hazard is guarded by a dominating check.

    Uses control flow graph to find dominating checks.
    """
    hazard_block = get_block(hazard.line)

    # Walk backwards through dominators
    for block in dominators(hazard_block):
        for stmt in block.statements:
            if is_null_check(stmt, hazard.operand):
                return Guard(
                    type='if_check',
                    expression=stmt.condition,
                    line=stmt.line
                )
            if is_assert(stmt, hazard.operand):
                return Guard(
                    type='assert',
                    expression=stmt.condition,
                    line=stmt.line
                )
            if is_early_return(stmt, hazard.operand):
                return Guard(
                    type='early_return',
                    expression=stmt.condition,
                    line=stmt.line
                )

    return None  # Unguarded
```

### Pattern Matching Rules

```python
HAZARD_PATTERN_RULES = [
    # Unguarded pointer dereference → precondition
    Rule(
        id="ptr_deref_unguarded",
        axiom_type="precondition",
        query="""
            SELECT f.id, f.name, h.operand, h.expression, h.line
            FROM functions f
            JOIN hazards h ON f.id = h.function_id
            WHERE h.hazard_type = 'pointer_deref'
              AND h.has_guard = FALSE
        """,
        template=lambda r: f"Pointer {r['operand']} must not be null",
        formal_spec=lambda r: f"{r['operand']} != nullptr",
        confidence=0.95,
        source="pattern",
        foundation_link="cpp20.undefined.null_dereference"
    ),

    # Guarded pointer → document the guard
    Rule(
        id="ptr_deref_guarded",
        axiom_type="invariant",
        query="""
            SELECT f.id, f.name, h.operand, h.guard_expression, h.guard_type
            FROM functions f
            JOIN hazards h ON f.id = h.function_id
            WHERE h.hazard_type = 'pointer_deref'
              AND h.has_guard = TRUE
        """,
        template=lambda r: f"Null check for {r['operand']} via {r['guard_type']}: {r['guard_expression']}",
        formal_spec=lambda r: r['guard_expression'],
        confidence=1.0,
        source="pattern"
    ),

    # Division
    Rule(
        id="division_unguarded",
        axiom_type="precondition",
        query="""
            SELECT f.id, f.name, h.operand, h.expression
            FROM functions f
            JOIN hazards h ON f.id = h.function_id
            WHERE h.hazard_type = 'division'
              AND h.has_guard = FALSE
        """,
        template=lambda r: f"Divisor {r['operand']} must not be zero",
        formal_spec=lambda r: f"{r['operand']} != 0",
        confidence=0.95,
        source="pattern",
        foundation_link="cpp20.undefined.division_by_zero"
    ),

    # Array access
    Rule(
        id="array_access_unguarded",
        axiom_type="precondition",
        query="""
            SELECT f.id, f.name, h.operand, h.expression
            FROM functions f
            JOIN hazards h ON f.id = h.function_id
            WHERE h.hazard_type = 'array_access'
              AND h.has_guard = FALSE
        """,
        template=lambda r: f"Index must be within bounds for array access: {r['expression']}",
        formal_spec=lambda r: f"0 <= index && index < size",
        confidence=0.90,
        source="pattern",
        foundation_link="cpp20.undefined.out_of_bounds"
    ),
]
```

---

## Phase 4: Call Graph & Propagation

### The Key Insight

If function `A` calls function `B`, and `B` has preconditions, then either:
1. `A` must satisfy `B`'s preconditions before the call, OR
2. `A` inherits `B`'s preconditions as its own

### Propagation Algorithm

```python
def propagate_preconditions(call_graph, axioms):
    """
    Propagate callee preconditions to callers.

    Uses topological sort (callees before callers).
    """
    # Build dependency order
    topo_order = topological_sort(call_graph)

    for func_id in reversed(topo_order):  # Process callees first
        for call in get_calls(func_id):
            callee_preconditions = get_preconditions(call.callee_id)

            for precond in callee_preconditions:
                # Check if caller satisfies precondition at call site
                if is_satisfied_at_callsite(func_id, call, precond):
                    # Document that it's satisfied
                    add_axiom(
                        function_id=func_id,
                        axiom_type="invariant",
                        content=f"Precondition '{precond.content}' satisfied before call to {call.callee_name}",
                        confidence=0.90,
                        source="propagated"
                    )
                else:
                    # Propagate precondition to caller
                    translated = translate_precondition(precond, call.arguments)
                    add_axiom(
                        function_id=func_id,
                        axiom_type="precondition",
                        content=f"Required by call to {call.callee_name}: {translated}",
                        formal_spec=translated,
                        confidence=precond.confidence * 0.95,  # Slight decay
                        source="propagated"
                    )

def is_satisfied_at_callsite(caller_id, call, precondition) -> bool:
    """Check if precondition is satisfied before the call."""
    # Check for dominating guards
    # Check for earlier assignments that satisfy the condition
    # Use data flow analysis
    pass
```

### Example

```cpp
void processData(int* data, size_t size) {
    // Extracted precondition: data != nullptr
    for (size_t i = 0; i < size; i++) {
        data[i] *= 2;  // Pointer deref
    }
}

void handleRequest(Request* req) {
    // Call to processData - inherits precondition
    processData(req->data, req->size);
    // Propagated: req != nullptr (for req->data access)
    // Propagated: req->data != nullptr (from processData)
}
```

---

## Phase 5: Foundation Linking

### Semantic Matching

Link extracted axioms to foundation axioms using:

1. **Exact keyword match** - "null", "nullptr", "zero", "bounds"
2. **Expression pattern match** - `!= 0`, `!= nullptr`, `< size`
3. **Embedding similarity** - For natural language descriptions

```python
def link_to_foundation(axiom, foundation_axioms) -> Optional[str]:
    """Link an axiom to the most relevant foundation axiom."""

    # Try keyword-based linking first
    keywords = extract_keywords(axiom.formal_spec)

    keyword_links = {
        'nullptr': 'cpp20.undefined.null_dereference',
        'null': 'cpp20.undefined.null_dereference',
        '!= 0': 'cpp20.undefined.division_by_zero',
        'bounds': 'cpp20.undefined.out_of_bounds',
        'overflow': 'cpp20.undefined.signed_overflow',
        'noexcept': 'cpp20.exception.noexcept_guarantee',
    }

    for keyword, foundation_id in keyword_links.items():
        if keyword in axiom.formal_spec.lower():
            return foundation_id

    # Fall back to embedding similarity
    axiom_embedding = embed(axiom.content)
    best_match = None
    best_score = 0.0

    for foundation in foundation_axioms:
        score = cosine_similarity(axiom_embedding, foundation.embedding)
        if score > best_score and score > 0.8:  # Threshold
            best_score = score
            best_match = foundation.id

    return best_match
```

---

## Phase 6: LLM Assist (Minimal, Targeted)

### When LLM is Needed (~5% of cases)

1. **Semantic interpretation** - What does this complex condition mean in English?
2. **Intent clarification** - Is this a precondition or an invariant?
3. **Missing context** - Comments suggest constraints not in code
4. **Complex patterns** - Multi-step validation logic

### Batched, Targeted Queries

```python
def llm_assist_batch(functions_needing_help: list[dict]) -> list[dict]:
    """
    Send batched, targeted questions to LLM.

    NOT: "Extract axioms from this function"
    YES: "Given this hazard pattern, what is the precondition?"
    """

    prompt = """You are assisting with C++ axiom extraction.

For each function below, I've already detected hazardous operations.
Please provide ONLY the missing preconditions in formal notation.

Format your response as JSON:
[
  {"function_id": "...", "preconditions": ["condition1", "condition2"]}
]

Functions:
"""

    for func in functions_needing_help:
        prompt += f"""
---
Function: {func['signature']}
Detected hazards:
{format_hazards(func['hazards'])}
Existing guards:
{format_guards(func['guards'])}

What preconditions are missing?
"""

    response = call_llm(prompt)
    return parse_json_response(response)
```

### Validation of LLM Output

```python
def validate_llm_axiom(axiom, function_info) -> bool:
    """
    Validate that LLM-generated axiom makes sense.

    Checks:
    - References valid parameters/variables
    - Expression is syntactically valid
    - Doesn't contradict explicit constraints
    """

    # Check that referenced variables exist
    variables_in_axiom = extract_variables(axiom.formal_spec)
    valid_variables = set(function_info['parameters'].keys())
    valid_variables.add('this')

    if not variables_in_axiom.issubset(valid_variables):
        return False

    # Check expression validity (simple parser)
    if not is_valid_expression(axiom.formal_spec):
        return False

    # Check for contradictions with explicit constraints
    for constraint in function_info['constraints']:
        if contradicts(axiom.formal_spec, constraint):
            return False

    return True
```

---

## Confidence Scoring

### Confidence Sources

| Source | Base Confidence | Notes |
|--------|-----------------|-------|
| `explicit` | 1.0 | C++20 language features, compiler-enforced |
| `pattern` (guarded) | 0.95-1.0 | Hazard with explicit guard in code |
| `pattern` (unguarded) | 0.85-0.95 | Hazard without guard, inferred precondition |
| `propagated` | parent * 0.95 | Inherited from callee, slight decay |
| `llm` | 0.70-0.85 | LLM-generated, validated |
| `llm` (unvalidated) | 0.50 | Needs human review |

### Confidence Thresholds

```python
CONFIDENCE_THRESHOLDS = {
    'auto_accept': 0.95,    # No review needed
    'auto_include': 0.80,   # Include but flag for optional review
    'needs_review': 0.70,   # Must be reviewed before use
    'reject': 0.50,         # Don't include unless manually approved
}
```

---

## Performance Characteristics

### Expected Speed

| Phase | gtest (500 funcs) | Large project (10K funcs) |
|-------|-------------------|---------------------------|
| Clang parsing | ~10 seconds | ~2 minutes |
| Constraint extraction | ~1 second | ~10 seconds |
| Hazard detection | ~5 seconds | ~1 minute |
| Call graph + propagation | ~5 seconds | ~2 minutes |
| Foundation linking | ~2 seconds | ~30 seconds |
| LLM assist (~5%) | ~2 minutes | ~20 minutes |
| **Total** | **~3 minutes** | **~25 minutes** |

### Comparison to Current Approach

| Approach | gtest (500 funcs) | Cost |
|----------|-------------------|------|
| Claude per function | ~2-3 hours | $$$ |
| This design | ~3 minutes | $ (LLM for 5%) |
| **Speedup** | **40-60x** | **10-20x cheaper** |

---

## Implementation Roadmap

### Phase 1: Clang Integration ✅ COMPLETE

- [x] Native C++ tool using LibTooling (not Python bindings)
- [x] Parse C++ files with full AST access
- [x] Extract function metadata (noexcept, nodiscard, const, etc.)
- [x] Extract template constraints and requires clauses
- [x] Recursive directory scanning with .axignore support

### Phase 2: Hazard Detection ✅ COMPLETE

- [x] Implement hazard detection (division, deref, array access)
- [x] Build control flow graphs via Clang CFG
- [x] Implement guard detection algorithm (dominator analysis)
- [x] Link hazards to guards
- [x] Macro hazard detection

### Phase 3: Explicit Constraint Extraction ✅ COMPLETE

- [x] noexcept specifications
- [x] [[nodiscard]], [[deprecated]] attributes
- [x] const/constexpr/consteval methods
- [x] = delete specifications
- [x] static_assert declarations
- [x] C++20 concepts and requires clauses
- [x] Scoped enums (enum class)
- [x] Trivially copyable structs/classes
- [x] Type aliases

### Phase 4: Call Graph & Propagation ❌ NOT STARTED

- [ ] Build call graph from AST database
- [ ] Implement precondition propagation
- [ ] Detect satisfied preconditions at call sites
- [ ] Handle virtual dispatch

### Phase 5: Foundation Linking ✅ COMPLETE

- [x] LanceDB semantic search integration
- [x] Embedding similarity matching
- [x] Populate depends_on fields via extract_clang.py --link

### Phase 6: LLM Integration ⚠️ PLACEHOLDER

- [x] Placeholder in extract_clang.py (--llm-fallback flag)
- [ ] Identify functions needing LLM assist
- [ ] Implement batched queries
- [ ] Validate LLM output
- [ ] Merge with rule-generated axioms

---

## Quality Guarantees

### What We Guarantee

1. **No false positives from explicit constraints** - C++20 features are compiler-enforced
2. **Complete hazard detection** - Clang gives us all operations
3. **Traceable axioms** - Every axiom links to source line and rule
4. **Reproducible** - Same code = same axioms (excluding LLM assist)

### What We Don't Guarantee

1. **Complete semantic coverage** - Some intent is only in comments/docs
2. **100% accuracy on inferred preconditions** - May miss context
3. **Performance characteristics** - Complexity analysis still needs LLM

### Quality vs Speed Tradeoff

```python
# Configuration options
EXTRACTION_CONFIG = {
    'mode': 'balanced',  # 'fast', 'balanced', 'thorough'

    # Fast mode: explicit + pattern only
    # Balanced mode: + propagation + targeted LLM
    # Thorough mode: + LLM for all low-confidence

    'confidence_threshold': 0.80,  # Minimum confidence to include
    'llm_batch_size': 10,          # Functions per LLM call
    'enable_propagation': True,    # Call graph analysis
}
```

---

## Future Enhancements

### Short Term

- [ ] Support for C++23 features
- [ ] SAL annotation parsing (Windows codebases)
- [ ] Doxygen comment extraction

### Medium Term

- [ ] SMT validation of extracted axioms
- [ ] Incremental re-extraction (only changed functions)
- [ ] Fine-tuned micro-model for axiom generation

### Long Term

- [ ] Cross-library axiom propagation
- [ ] Test-as-specification integration
- [ ] IDE plugin for real-time axiom display
