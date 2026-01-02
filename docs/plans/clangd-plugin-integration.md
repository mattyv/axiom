# Axiom Clangd Plugin Integration Plan

## Overview

Integrate axiom validation directly into clangd as a custom check/plugin. This gives Claude Code (and any LSP client) automatic axiom diagnostics without building a separate LSP server.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Claude Code                                 │
│                   (ENABLE_LSP_TOOL=1)                           │
└─────────────────────────┬───────────────────────────────────────┘
                          │ LSP Protocol
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                        clangd                                    │
├─────────────────────────────────────────────────────────────────┤
│  Built-in checks (clang-tidy, etc.)                             │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Axiom Check (plugin)                          │  │
│  │                                                            │  │
│  │  1. Receive AST from clangd                                │  │
│  │  2. Extract implicit claims from code patterns             │  │
│  │  3. Query axiom database                                   │  │
│  │  4. Emit clang diagnostics                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Axiom Database                                │
│              (LanceDB vectors + Neo4j graph)                     │
└─────────────────────────────────────────────────────────────────┘
```

## Axiom's Value: Semantic Context, Not Just Linting

**The problem with just errors/warnings:** Clang already does that. Axiom's unique value is:

1. **Formal grounding** - traces to C11/C++20 spec sections, K Framework semantics
2. **Library contracts** - knows API requirements clang doesn't
3. **Proof chains** - shows *why* something matters
4. **Nuanced context** - not binary "error/ok" but "here's what you should know"

**The key insight:** The LLM might know more context than the static analyzer. Axiom should inform, not just flag. The LLM can then dig deeper via MCP if the context seems relevant.

---

## Tiered Diagnostic Model

| Level | LSP Severity | Purpose | Example |
|-------|--------------|---------|---------|
| **error** | Error | Definite violation | Use-after-free, proven null deref |
| **warning** | Warning | Likely issue | Unguarded overflow on user input |
| **info** | Information | Semantic context | "Atomic ops have defined overflow per C11 §7.17" |
| **context** | Hint | Exploration prompt | "Related axioms exist - query via MCP if relevant" |

### Examples: All Four Levels

#### Level: ERROR - Definite Violation

```
memory.c:87:5: error: [axiom:heap-use-after-free] use after free
    buffer->data[0] = 'x';
    ^~~~~~~~~~~~~~~~~~~

  Violation: Pointer 'buffer' was freed at line 82
  Formal: C11 §7.22.3.3 - accessing freed memory is undefined behavior

  Proof chain:
    1. free(buffer) called at memory.c:82
    2. No reassignment of 'buffer' between free and use
    3. This access is undefined behavior

  Fix: Set pointer to NULL after free, or restructure to avoid reuse
```

The LLM **must** fix this - it's a definite bug.

---

#### Level: WARNING - Likely Issue

```
parser.c:142:15: warning: [axiom:c11-overflow] potential signed overflow
    int size = base + user_offset;
               ^~~~~~~~~~~~~~~~~~

  Claim: "signed arithmetic will not overflow"
  Risk: 'user_offset' comes from external input (line 138)
  Formal: C11 §6.5¶5 - signed overflow is undefined behavior

  Fixes:
    - Use __builtin_add_overflow()
    - Validate user_offset bounds before arithmetic
    - Use size_t for sizes

  Explore: mcp:axiom.search_axioms("overflow input validation")
```

The LLM **should** fix this - user input without bounds checking is risky.

---

#### Level: INFO - Semantic Context

```
crypto.c:56:5: info: [axiom:openssl-ctx-init] SSL_CTX initialization context
    SSL_CTX* ctx = SSL_CTX_new(TLS_method());
    ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

  Context: SSL_CTX_new returns NULL on failure. The OpenSSL API requires:
    1. Check return value for NULL
    2. Call SSL_CTX_free() when done (paired operation)
    3. Set minimum protocol version for security

  Formal: OpenSSL man page SSL_CTX_new(3)
  Related axioms: ssl-ctx-free (pairing), ssl-ctx-set-options

  Explore: mcp:axiom.search_axioms("SSL_CTX initialization best practices")
           mcp:axiom.get_axiom("openssl-ctx-free")
```

The LLM sees this and thinks: "Right, I should check for NULL and remember to free later." Not an error, but useful context about API contracts.

---

#### Level: CONTEXT - Exploration Prompt

```
counter.c:23:5: hint: [axiom:c11-atomics] atomic operation semantics
    atomic_fetch_add(&counter, delta);
    ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

  Context: Atomic operations have well-defined semantics that differ from
  regular operations:
    - Overflow wraps (defined, not UB)
    - Memory ordering applies (default: seq_cst)
    - Lock-free on most platforms for this type

  Formal: C11 §7.17.7.5

  This is informational - no action required. Explore if relevant:
    mcp:axiom.search_axioms("atomic memory ordering")
    mcp:axiom.search_axioms("atomic vs mutex performance")
```

The LLM sees this and thinks: "Good to know, atomics are fine here. I might look up memory ordering if I need weaker semantics for performance."

---

#### Level: CONTEXT - Library Pattern Recognition

```
network.c:201:5: hint: [axiom:posix-socket-lifecycle] socket API context
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

  Context: POSIX socket lifecycle pattern detected. Related axioms:
    - socket() returns -1 on error (check errno)
    - Must call close(fd) when done
    - Common pattern: socket → bind → listen → accept (server)
    - Common pattern: socket → connect (client)

  You're at step 1 of the lifecycle. Related operations will be flagged
  if axioms exist for them.

  Explore: mcp:axiom.search_axioms("socket error handling")
           mcp:axiom.search_axioms("socket resource leak")
```

The LLM sees the pattern and now has awareness of the full lifecycle, even if it's just writing one part.

---

### What Makes This Different From Clang

```
┌─────────────────────────────────────────────────────────────────┐
│  Clang says:                                                     │
│    warning: integer overflow in expression [-Woverflow]          │
│                                                                  │
│  Axiom says:                                                     │
│    info: [axiom:c11-overflow] signed arithmetic context          │
│      Formal: C11 §6.5¶5 - overflow is undefined behavior         │
│      Note: Common pattern. Inputs bounded? Using -fwrapv?        │
│      Explore: mcp:axiom.search_axioms("overflow bounds check")   │
└─────────────────────────────────────────────────────────────────┘
```

The LLM sees this and can:
1. **Ignore** - it knows the inputs are small constants
2. **Fix** - it realizes this is user input, adds bounds check
3. **Explore** - calls MCP to get full proof chain and related axioms

### Diagnostic Flow

```
LSP (passive, always-on)              MCP (active, on-demand)
        │                                      │
        ▼                                      │
   Axiom emits:                                │
   - errors (must fix)                         │
   - warnings (should fix)                     │
   - info (semantic context)    ──► LLM ──►   "Tell me more about X"
   - context (explore prompts)     decides          │
        │                         if relevant       ▼
        │                                    Full proof chains
        │                                    Related axioms
        │                                    Library contracts
        ▼                                    Formal spec text
   Claude sees all,
   acts on what's relevant
```

### Configurable Visibility

Users and LLMs may want different verbosity levels:

```toml
# .axiom/config.toml
[diagnostics]
# Minimum level to show (error > warning > info > context)
min_level = "info"          # Show info and above, hide context hints

# Or be specific
show_levels = ["error", "warning", "info"]

# LLM-specific: always include MCP exploration hints
include_mcp_hints = true

# Human-specific: maybe less noise in editor
editor_min_level = "warning"
```

### MCP Exploration Hooks in Diagnostics

Every diagnostic above "error" includes an exploration path:

```toml
[diagnostic]
severity = "info"
message = "atomic operations context"
mcp_explore = [
    { tool = "search_axioms", query = "atomic {function} overflow" },
    { tool = "get_axiom", id = "{axiom_id}" },
]
```

This renders as:
```
buffer.c:42:5: info: [axiom:c11-atomics] atomic increment context
    atomic_fetch_add(&counter, 1);
    ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  Context: Atomic operations have well-defined overflow (wrap) behavior
  Formal: C11 §7.17.7.5
  Explore: mcp:axiom.search_axioms("atomic_fetch_add overflow")
           mcp:axiom.get_axiom("c11-atomics-overflow")
```

---

## Design Principle: Config-Driven Patterns

Instead of hardcoding AST patterns in C++, patterns are defined **alongside their axioms** in TOML config files. The C++ plugin becomes a **pattern interpreter** that:

1. Loads pattern definitions from axiom TOML files
2. Dynamically registers corresponding AST matchers
3. On match → looks up the axiom → validates → emits diagnostic

This means:
- Adding new checks = adding a TOML file (no recompile)
- Library authors can ship axiom files with their headers
- Users can customize, disable, or extend patterns per-project

---

## Pattern Definition Format

Each axiom defines its trigger pattern in TOML:

### Example: Signed Overflow

```toml
# axioms/triggers/c11-overflow.toml
[axiom]
id = "c11-6.5-overflow"
content = "Signed integer overflow is undefined behavior"
formal_spec = "C11 §6.5¶5"
layer = "c11"

[trigger]
pattern = "binary_op"
operators = ["+", "-", "*"]
operand_types = ["signed_integer"]

# What claim this code implies
implicit_claim = "signed arithmetic will not overflow"

# Conditions where this is safe (suppress diagnostic)
safe_when = [
    "result_checked_with_overflow_builtin",
    "operands_bounds_checked",
    "compiler_flag_fwrapv"
]

[diagnostic]
severity = "warning"
message = "potential signed overflow"
fixes = [
    "Use __builtin_add_overflow()",
    "Use unsigned types",
    "Add bounds checking before operation"
]
mcp_explore = [
    { tool = "search_axioms", query = "signed overflow bounds checking" },
]
```

### Example: Informational Context (not an error)

```toml
# axioms/triggers/c11-atomics.toml
[axiom]
id = "c11-atomics-overflow"
content = "Atomic integer operations have well-defined wrap-around behavior"
formal_spec = "C11 §7.17.7.5"
layer = "c11"

[trigger]
pattern = "function_call"
functions = ["atomic_fetch_add", "atomic_fetch_sub", "atomic_fetch_*"]
operand_types = ["_Atomic"]

implicit_claim = "atomic overflow behavior is understood"

# This is context, not a warning - atomic overflow is DEFINED
safe_when = []  # Always emit - it's informational

[diagnostic]
severity = "context"  # Not error/warning - just helpful info
message = "atomic operation has defined overflow semantics"
context = """
Unlike regular signed integers, atomic operations wrap on overflow.
This is well-defined per C11 §7.17.7.5. No undefined behavior here.
"""
mcp_explore = [
    { tool = "get_axiom", id = "c11-atomics-overflow" },
    { tool = "search_axioms", query = "atomic operations memory ordering" },
]
```

This emits:
```
counter.c:15:5: hint: [axiom:c11-atomics-overflow] atomic overflow context
    atomic_fetch_add(&counter, 1);
    ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  Context: Atomic operations wrap on overflow (well-defined, not UB)
  Formal: C11 §7.17.7.5
  Explore: mcp:axiom.get_axiom("c11-atomics-overflow")
```

The LLM sees this and knows: "This is fine, but I now know where to look if I need more detail about atomics."

### Example: Library Function Contract

```toml
# axioms/triggers/lib-memcpy.toml
[axiom]
id = "lib-memcpy-overlap"
content = "memcpy source and destination must not overlap"
formal_spec = "C11 §7.24.2.1"
layer = "stdlib"

[trigger]
pattern = "function_call"
functions = ["memcpy", "wmemcpy"]
# Named argument positions for richer analysis
args = { dst = 0, src = 1, n = 2 }

implicit_claim = "memcpy regions do not overlap"

safe_when = [
    "dst_src_provably_disjoint",    # Static analysis proves no overlap
    "size_is_zero"                   # n == 0 is always safe
]

[diagnostic]
severity = "warning"
message = "memcpy with potentially overlapping regions"
fixes = [
    "Use memmove() if regions may overlap",
    "Ensure dst and src point to disjoint memory"
]
```

### Example: Null Pointer Dereference

```toml
# axioms/triggers/null-deref.toml
[axiom]
id = "c11-null-deref"
content = "Dereferencing a null pointer is undefined behavior"
formal_spec = "C11 §6.5.3.2¶4"
layer = "c11"

[trigger]
pattern = "pointer_deref"
# Matches: *ptr, ptr->field, ptr[i]
include = ["unary_deref", "member_access", "array_subscript"]

implicit_claim = "pointer is non-null"

safe_when = [
    "null_checked_in_dominator",     # if (ptr != NULL) above
    "assigned_from_alloc_checked",   # ptr = malloc(); if (!ptr) return;
    "parameter_with_nonnull_attr",   # __attribute__((nonnull))
    "reference_type"                 # C++ references can't be null
]

[diagnostic]
severity = "warning"
message = "potential null pointer dereference"
fixes = [
    "Add null check before use",
    "Use assert(ptr != NULL)",
    "Mark parameter with __attribute__((nonnull))"
]
```

### Example: Use-After-Free (Stateful Pattern)

```toml
# axioms/triggers/use-after-free.toml
[axiom]
id = "heap-use-after-free"
content = "Accessing memory after free is undefined behavior"
formal_spec = "C11 §7.22.3.3"
layer = "stdlib"

[trigger]
pattern = "sequence"  # Stateful: tracks across statements
sequence = [
    { pattern = "function_call", functions = ["free", "realloc"], capture = "freed_ptr", arg = 0 },
    { pattern = "any_use", of = "freed_ptr" }
]

implicit_claim = "freed pointer is not used after free"

safe_when = [
    "ptr_reassigned_between",        # ptr = malloc() again
    "ptr_set_to_null",               # ptr = NULL after free
    "ptr_not_same_object"            # Alias analysis says different
]

[diagnostic]
severity = "error"  # This is almost always a bug
message = "use after free"
fixes = [
    "Set pointer to NULL after free",
    "Restructure to avoid reuse",
    "Use smart pointers (C++)"
]
```

---

## Pattern DSL Reference

The pattern DSL maps to clang AST concepts:

```yaml
# Pattern types and their fields

binary_op:
    operators: ["+", "-", "*", "/", "%", "<<", ">>", ...]
    operand_types: [signed_integer, unsigned_integer, pointer, float, ...]
    # Optional: specify left/right operand constraints separately
    lhs_type: ...
    rhs_type: ...

function_call:
    functions: ["name", "regex:pattern", ...]  # Function names or regex
    args: { name: position, ... }              # Named arg positions
    return_type: ...                           # Filter by return type

pointer_deref:
    include: [unary_deref, member_access, array_subscript]

array_subscript:
    index_type: [integer, ...]

cast:
    from_type: ...
    to_type: ...
    kind: [static, reinterpret, c_style, ...]

assignment:
    lhs_type: ...
    rhs_type: ...

sequence:
    # For multi-statement patterns (use-after-free, double-free, etc.)
    sequence: [{ pattern: ..., capture: "name" }, { pattern: ..., of: "name" }]

comparison:
    operators: ["==", "!=", "<", ">", "<=", ">="]
    operand_types: [...]
```

### Type Specifiers

```yaml
signed_integer:    int, short, long, long long, int8_t, int16_t, ...
unsigned_integer:  unsigned int, size_t, uint8_t, ...
pointer:           T* for any T
array:             T[] for any T
float:             float, double, long double
struct:            Any struct/class type
```

### Safe-When Conditions

These are symbolic conditions the plugin checks via control-flow analysis:

| Condition | Meaning |
|-----------|---------|
| `null_checked_in_dominator` | An `if (ptr != NULL)` dominates this use |
| `bounds_checked_in_dominator` | An `if (i < size)` dominates this use |
| `result_checked_with_overflow_builtin` | Uses `__builtin_*_overflow` |
| `assigned_from_alloc_checked` | Pointer assigned from malloc/new with null check |
| `parameter_with_nonnull_attr` | Has `__attribute__((nonnull))` |
| `compiler_flag_fwrapv` | `-fwrapv` flag present (wrapping overflow is defined) |
| `ptr_set_to_null` | Pointer assigned NULL after free |

---

## Components

### 1. Pattern Loader

Reads TOML files and builds pattern registry:

```cpp
class PatternLoader {
public:
    // Load all .toml files from directory
    void loadFromDirectory(const std::string& path);

    // Load project-specific overrides
    void loadOverrides(const std::string& project_config);

    // Get all loaded patterns
    const std::vector<TriggerPattern>& patterns() const;

private:
    std::vector<TriggerPattern> patterns_;
    std::unordered_set<std::string> disabled_;  // User-disabled patterns
};
```

### 2. Dynamic Matcher Builder

Converts TOML patterns to clang AST matchers at runtime:

```cpp
class DynamicMatcherBuilder {
public:
    // Build AST matcher from pattern definition
    ast_matchers::DeclarationMatcher buildMatcher(const TriggerPattern& pattern);

private:
    ast_matchers::DeclarationMatcher buildBinaryOpMatcher(const TriggerPattern& p);
    ast_matchers::DeclarationMatcher buildFunctionCallMatcher(const TriggerPattern& p);
    ast_matchers::DeclarationMatcher buildPointerDerefMatcher(const TriggerPattern& p);
    // ...
};
```

### 3. Clangd Check: `AxiomCheck`

Now a thin orchestrator:

```cpp
class AxiomCheck : public clang::tidy::ClangTidyCheck {
public:
    AxiomCheck(StringRef Name, ClangTidyContext* Context);

    void registerMatchers(ast_matchers::MatchFinder* finder) override {
        // Dynamically register matchers from loaded patterns
        for (const auto& pattern : loader_.patterns()) {
            auto matcher = builder_.buildMatcher(pattern);
            finder->addMatcher(matcher, this);
        }
    }

    void check(const MatchFinder::MatchResult& result) override;

private:
    PatternLoader loader_;
    DynamicMatcherBuilder builder_;
    SafetyAnalyzer safety_;      // Checks safe_when conditions
    AxiomClient* axiom_client_;
};
```

### 4. Safety Analyzer

Checks `safe_when` conditions to suppress false positives:

```cpp
class SafetyAnalyzer {
public:
    // Check if any safe_when condition is satisfied
    bool isSafe(
        const MatchResult& match,
        const TriggerPattern& pattern,
        ASTContext& ctx
    );

private:
    bool checkNullInDominator(const Expr* ptr, ASTContext& ctx);
    bool checkBoundsInDominator(const Expr* index, ASTContext& ctx);
    bool checkOverflowBuiltin(const BinaryOperator* op, ASTContext& ctx);
    // ...

    // Cache for control-flow analysis results
    std::unordered_map<const FunctionDecl*, CFG*> cfg_cache_;
};
```

### 4. Axiom Client

Queries the axiom database. Options:

**Option A: REST API**
```cpp
class AxiomRestClient : public AxiomClient {
    // HTTP calls to axiom FastAPI server
    ValidationResult validate(const std::string& claim);
};
```

**Option B: Embedded (link LanceDB C++)**
```cpp
class AxiomEmbeddedClient : public AxiomClient {
    // Direct LanceDB/SQLite queries, no network
    lancedb::Connection db_;
};
```

**Option C: Unix Socket / IPC**
```cpp
class AxiomIPCClient : public AxiomClient {
    // Fast local IPC to a running axiom daemon
};
```

Recommendation: Start with REST, optimize to embedded/IPC if latency matters.

### 5. Diagnostic Emitter

Convert validation results to clang diagnostics:

```cpp
void AxiomCheck::emitDiagnostic(
    const ExtractedClaim& claim,
    const ValidationResult& result
) {
    if (!result.is_valid) {
        diag(claim.loc, "potential undefined behavior: %0 [axiom:%1]")
            << result.explanation
            << result.contradictions[0].axiom_id;

        // Add note with proof chain
        for (const auto& step : result.proof_chain) {
            diag(claim.loc, "grounded in: %0", DiagnosticIDs::Note)
                << step.formal_spec;
        }

        // Add fix-it hint if available
        if (result.suggested_fix) {
            diag(claim.loc, "consider: %0", DiagnosticIDs::Note)
                << *result.suggested_fix;
        }
    }
}
```

## Diagnostic Output Examples

**What Claude would see:**

```
src/buffer.c:142:15: warning: potential undefined behavior [axiom:c11-overflow]
    int size = base + offset;
               ^~~~~~~~~~~~
  Implicit claim: "signed addition will not overflow"
  Contradicts axiom 'c11-6.5-overflow': "signed integer overflow is undefined"

src/buffer.c:142:15: note: grounded in C11 §6.5¶5
  "If an exceptional condition occurs during the evaluation of an
   expression (that is, if the result is not mathematically defined
   or not in the range of representable values for its type), the
   behavior is undefined."

src/buffer.c:142:15: note: consider using __builtin_add_overflow() or unsigned types
```

```
src/net.c:87:5: warning: potential null pointer dereference [axiom:lib-socket]
    conn->fd = socket(AF_INET, SOCK_STREAM, 0);
    ^~~~
  Implicit claim: "conn is non-null"
  No null check found in control flow path

src/net.c:87:5: note: function 'process_connection' receives conn from external caller
```

## Integration Steps

### Phase 1: Standalone clang-tidy Check

1. Create `axiom-tidy` as an out-of-tree clang-tidy module
2. Implement basic pattern matchers (overflow, null deref)
3. REST client to existing axiom API
4. Test with: `clang-tidy -checks=axiom-* file.c`

### Phase 2: Clangd Integration

1. Build as clangd plugin (`.so`/`.dylib`)
2. Configure clangd to load: `.clangd` file or `--query-driver`
3. Test with VSCode + clangd extension

### Phase 3: Claude Code Integration

1. Document clangd setup for axiom
2. Test with `ENABLE_LSP_TOOL=1 claude`
3. Verify diagnostics flow into Claude's context

### Phase 4: Optimize

1. Benchmark latency (target: <100ms per file)
2. If too slow: embedded LanceDB, caching, incremental analysis
3. Tune false-positive rate based on feedback

## Configuration

`.clangd` file in project root:

```yaml
CompileFlags:
  Add: [-Wno-unused]  # Reduce noise

Diagnostics:
  ClangTidy:
    Add: [axiom-*]
    Remove: [modernize-*]  # Focus on axiom checks

  Axiom:
    # Axiom-specific config
    DatabasePath: /path/to/axiom/data
    ApiEndpoint: http://localhost:8000  # Or unix socket
    Confidence:
      MinReport: 0.7      # Only report high-confidence issues
      MinWarning: 0.9     # Promote to warning at this level
    Categories:
      Overflow: true
      NullDeref: true
      Bounds: true
      UseAfterFree: true
      LibraryContracts: true
```

## Dependencies

- LLVM/Clang libraries (libclang, libtooling)
- clangd headers (for plugin API)
- HTTP client (libcurl or cpp-httplib) for REST
- Optional: LanceDB C++ bindings for embedded mode

## File Structure

```
axiom/
├── clangd/
│   ├── CMakeLists.txt
│   ├── AxiomCheck.cpp          # Main check orchestrator
│   ├── AxiomCheck.h
│   ├── PatternLoader.cpp       # TOML pattern loader
│   ├── PatternLoader.h
│   ├── DynamicMatcherBuilder.cpp  # Pattern → AST matcher
│   ├── DynamicMatcherBuilder.h
│   ├── SafetyAnalyzer.cpp      # Control-flow safety checks
│   ├── SafetyAnalyzer.h
│   ├── AxiomClient.cpp         # REST/embedded client
│   └── AxiomClient.h
│
├── axioms/
│   ├── triggers/               # Pattern definitions (TOML)
│   │   ├── c11-overflow.toml
│   │   ├── c11-null-deref.toml
│   │   ├── c11-division.toml
│   │   ├── stdlib-memcpy.toml
│   │   ├── stdlib-free.toml
│   │   └── ...
│   │
│   ├── library/                # Library-specific axioms
│   │   ├── openssl/
│   │   │   ├── ssl-ctx.toml
│   │   │   └── ...
│   │   └── ...
│   │
│   └── schema.json             # JSON schema for TOML validation
│
├── python/                     # Existing Python code
│   └── axiom/
│
└── data/                       # Axiom database (LanceDB, Neo4j)
```

### Project-Level Overrides

Users can customize patterns per-project:

```
my-project/
├── .axiom/
│   ├── config.toml             # Enable/disable patterns
│   ├── overrides/              # Project-specific pattern overrides
│   │   └── custom-null.toml    # "Our SafePtr is always non-null"
│   └── suppressions.toml       # File/line suppressions
└── ...
```

```toml
# .axiom/config.toml
[patterns]
disabled = ["c11-overflow"]     # We use -fwrapv everywhere

[severity]
# Promote these to errors for our project
errors = ["heap-use-after-free", "c11-null-deref"]

[includes]
# Also check axioms for these libraries
libraries = ["openssl", "zlib"]
```

## Open Questions

1. **Latency budget** - How fast does validation need to be? clangd expects fast checks. Pattern loading should be cached.

2. **Scope of analysis** - Per-function? Per-file? Cross-TU? Stateful patterns (use-after-free) need function-scope at minimum.

3. **DSL expressiveness vs complexity** - How sophisticated should the pattern DSL be? Start simple, extend based on real needs.

4. **Existing C++ branch** - What patterns does it already extract? Can that code inform the DSL design?

5. **Library axiom distribution** - How do library authors ship axiom TOML files? Alongside headers? Separate package?

6. **Safe-when extensibility** - Can users define custom safe-when conditions, or only use built-in ones?

## Next Steps

1. **Review existing C++ clang AST branch** - understand current pattern extraction
2. **Design TOML schema** - formalize the pattern DSL with JSON schema for validation
3. **Prototype PatternLoader** - parse TOML, validate against schema
4. **Prototype DynamicMatcherBuilder** - start with binary_op and function_call only
5. **Test with 2-3 core axioms** - overflow, null-deref, memcpy
6. **Measure latency** - ensure pattern loading + matching is fast enough for clangd
7. **Iterate on DSL** - extend based on what patterns we can't express
