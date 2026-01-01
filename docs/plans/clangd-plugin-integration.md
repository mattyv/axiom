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

## Components

### 1. Clangd Check: `AxiomCheck`

A clang-tidy style check that runs on the AST.

```cpp
// axiom/clangd/AxiomCheck.h
class AxiomCheck : public clang::tidy::ClangTidyCheck {
public:
    void registerMatchers(ast_matchers::MatchFinder* finder) override;
    void check(const ast_matchers::MatchFinder::MatchResult& result) override;

private:
    AxiomClient* axiom_client_;  // Connection to axiom DB
};
```

### 2. AST Matchers for Risky Patterns

Register matchers for code patterns that imply claims:

| Pattern | AST Matcher | Implicit Claim |
|---------|-------------|----------------|
| Signed arithmetic | `binaryOperator(hasOperatorName("+"), hasType(isSignedInteger()))` | "overflow handled" |
| Pointer deref | `unaryOperator(hasOperatorName("*"))` | "pointer non-null" |
| Array subscript | `arraySubscriptExpr()` | "index in bounds" |
| Division | `binaryOperator(hasOperatorName("/"))` | "divisor non-zero" |
| Stdlib calls | `callExpr(callee(functionDecl(hasName("memcpy"))))` | "regions don't overlap" |
| Free + use | `callExpr(callee(functionDecl(hasName("free"))))` | track for use-after-free |

### 3. Claim Extractor

Converts AST match + context into a validatable claim:

```cpp
struct ExtractedClaim {
    SourceLocation loc;
    std::string claim_text;      // "memcpy regions do not overlap"
    std::string code_context;    // The actual code snippet
    ClaimCategory category;      // OVERFLOW, NULL_DEREF, BOUNDS, etc.
    float base_confidence;       // Lower if guessing from heuristics
};

class ClaimExtractor {
public:
    // Uses type info, control flow context, etc.
    std::optional<ExtractedClaim> extract(
        const MatchResult& match,
        ASTContext& ctx
    );

private:
    // Track null checks, bounds checks already performed
    ControlFlowAnalyzer cfa_;
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
│   ├── AxiomCheck.cpp
│   ├── AxiomCheck.h
│   ├── ClaimExtractor.cpp
│   ├── ClaimExtractor.h
│   ├── AxiomClient.cpp       # REST/embedded client
│   ├── AxiomClient.h
│   ├── PatternMatchers.cpp   # AST matchers
│   └── PatternMatchers.h
├── python/                    # Existing Python code
│   └── axiom/
└── data/                      # Axiom database
```

## Open Questions

1. **Latency budget** - How fast does validation need to be? clangd expects fast checks.

2. **Scope of analysis** - Per-function? Per-file? Cross-TU?

3. **False positive handling** - How to suppress? Comments? Config?

4. **Existing C++ branch** - What patterns does it already extract? Can we reuse directly?

5. **Library axioms** - How to associate project-specific axioms with include paths?

## Next Steps

1. Review existing C++ clang AST code on the other branch
2. Identify reusable components for pattern matching
3. Prototype simplest possible check (e.g., signed overflow only)
4. Measure round-trip latency to axiom DB
5. Iterate based on real-world testing with Claude Code
