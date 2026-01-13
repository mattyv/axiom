# ESBMC + Axiom Integration

## Overview

This document outlines how ESBMC (a bounded model checker with SMT solving) can be integrated with Axiom to improve LLM coding assistance. The key insight is that Axiom provides **abstract knowledge** (rules, preconditions, specifications) while ESBMC provides **concrete execution** (paths, counterexamples, proofs).

**Reference Implementation**: [ESBMC-AI](https://github.com/esbmc/esbmc-ai) - demonstrates production patterns for LLM + SMT integration.

---

## Core Value Proposition

Axiom helps LLMs avoid mistakes by providing context. ESBMC makes that context **actionable**:

| Without ESBMC | With ESBMC |
|---------------|------------|
| "This axiom says X is undefined" | "Here's input X=5, Y=-1 that triggers UB" |
| "These axioms might conflict" | "When ptr==NULL, both can't be true" |
| "Confidence: 0.85" | "Verified against 1000 paths" |
| "Here are 47 related axioms" | "Here are 2 axioms your code violates" |

---

## Integration Points

### 1. Counterexamples as Context (Highest Impact, Lowest Effort)

**Problem**: Abstract rules require LLM to reason about applicability.

```
Current context:
  "Per C++20 [expr.mul]/4, if during evaluation of an expression,
   the result is not mathematically defined or not in the range of
   representable values for its type, the behavior is undefined."
```

**With ESBMC**:
```
ESBMC context:
  "When x = INT_MAX and y = 1, line 15 overflows:
   x + y = -2147483648 (wrapped)"
```

Concrete examples are self-evident. No interpretation needed.

### 2. Axiom Relevance Filtering (Major Token Savings)

**Problem**: Vector similarity returns many "related" axioms, most are noise.

**Solution**: Use ESBMC to verify which axioms actually matter for specific code.

```
LLM writes:
    int get(int* arr, int i) { return arr[i]; }

Axiom DB has 47 array-related axioms.

ESBMC approach:
    1. Generate assertions from axioms:
       - assert(arr != NULL)        // from null_deref axiom
       - assert(i >= 0 && i < size) // from bounds axiom

    2. Run ESBMC on this code

    3. Results:
       - NULL check: FALSIFIABLE     → SHOW this axiom
       - Bounds check: FALSIFIABLE   → SHOW this axiom
       - 45 other axioms: N/A        → SKIP

Context injection: 2 axioms instead of 47 (95% token reduction)
```

### 3. Provable Axioms (Confidence Stratification)

Create a trust hierarchy based on verification status:

```
┌─────────────────────────────────────────────────────────────┐
│  CONFIDENCE LEVELS                                          │
├─────────────────────────────────────────────────────────────┤
│  1.00  ESBMC-VERIFIED     "Proven for all paths up to k"   │
│  0.95  COMPILER-ENFORCED  "Clang attribute guarantees"      │
│  0.85  HUMAN-REVIEWED     "Developer confirmed"             │
│  0.70  LLM-EXTRACTED      "Heuristic extraction"            │
│  0.50  ESBMC-TIMEOUT      "Couldn't verify, inconclusive"   │
│  0.00  ESBMC-FALSIFIED    "Counterexample found - WRONG"    │
└─────────────────────────────────────────────────────────────┘
```

**Workflow**:
```
Extract axiom: "foo(x) requires x > 0"
        ↓
Run ESBMC with assertion
        ↓
VERIFIED   → confidence = 1.0, store proof witness
FALSIFIED  → confidence = 0.0, flag for removal
TIMEOUT    → keep heuristic confidence
```

### 4. Axiom-Augmented Program Repair

Enhance ESBMC-AI's repair loop with Axiom's knowledge:

```
ESBMC finds bug → Axiom provides similar patterns/fixes → LLM generates informed fix → ESBMC verifies
```

**Example**:
```
ESBMC: "Null dereference at line 23"

Without Axiom:
  LLM guesses: if (ptr) { ... }

With Axiom:
  Axiom DB: "Pattern: null check before deref
    - src/foo.cpp:45 uses early return
    - src/bar.cpp:120 uses optional<T>
    - project style: prefer optional over raw pointers"

  LLM generates: std::optional-based fix matching project conventions
```

### 5. Incremental Verification (Real-time Feedback)

As LLM generates code, run ESBMC incrementally:

```
LLM writes line 1:  int* p = get_ptr();
ESBMC: (nothing yet)

LLM writes line 2:  *p = 5;
ESBMC: ⚠️ "p can be NULL here (get_ptr may return NULL per axiom X)"

LLM sees warning → adds null check before continuing
```

### 6. Axiom Mining from Verification

Discover implicit contracts by analyzing what ESBMC verifies:

```
Run ESBMC on codebase:
  "foo() called 47 times, ESBMC verified x>0 at all call sites"
        ↓
Infer axiom:
  "foo() has implicit precondition x>0 (verified by usage)"
```

### 7. Weakest Precondition Inference

Auto-refine axiom precision:

```
Extracted: "b must be positive"  (confidence 0.80)
ESBMC WP:  "b must be non-zero"  (actual requirement)
        ↓
Refine axiom to "b != 0" (confidence 0.95, ESBMC-backed)
```

### 8. Differential Verification

Show exactly what a code change broke:

```
Before: foo(x) { if (x > 0) bar(x); }
After:  foo(x) { bar(x); }  // LLM removed the guard

ESBMC differential:
  "REGRESSION: bar(x) precondition 'x > 0' was previously guaranteed,
   now reachable with x <= 0"
```

### 9. Compositional Verification (Scale)

Verify functions individually, compose results:

```
Verify foo(): postcondition Q_foo  ✓
Verify bar(): precondition P_bar   ✓

Check composition: Q_foo implies P_bar?
  If no → "foo() guarantees x >= 0, bar() requires x > 0, gap: x == 0"
```

### 10. Axiom Freshness Detection

Detect when code changes invalidate axioms:

```
Periodic job:
  For each axiom A:
    Run ESBMC to verify A still holds
    If FALSIFIED:
      "Axiom 'foo requires x>0' no longer holds since commit abc123"
```

### 11. Uncertainty-Targeted Verification

LLM expresses uncertainty → ESBMC verifies specifically that:

```
LLM: "I think this handles negative numbers, but unsure about INT_MIN"

System runs ESBMC specifically for INT_MIN case

Returns: "Verified safe" or counterexample
```

### 12. Proof Witnesses as Artifacts

Store proofs for later citation:

```
Axiom: "malloc/free paired correctly in module X"
ESBMC: VERIFIED (proof witness attached)

Later LLM query: "Does this leak memory?"
Response: "Per ESBMC verification from [date], all allocations paired."
```

---

## Architecture

### Proposed Module Structure

```
axiom/
├── verifiers/                    # NEW
│   ├── base_verifier.py          # Abstract interface
│   ├── esbmc_verifier.py         # ESBMC subprocess wrapper
│   ├── z3_verifier.py            # Direct Z3 bindings (optional)
│   ├── output_parser.py          # Parse counterexamples/proofs
│   └── cache.py                  # SHA-based verification cache
├── smt/                          # NEW
│   ├── translator.py             # Axiom → SMT-LIB translation
│   ├── encoding.py               # C++ semantics encoding
│   └── models.py                 # SMT result types
├── reasoning/                    # MODIFIED
│   ├── validator.py              # Add SMT verification step
│   ├── proof_chain.py            # Add formal chain verification
│   └── contradiction.py          # Replace heuristics with SMT
```

### Key Abstractions (from ESBMC-AI)

```python
class BaseVerifier(ABC):
    @abstractmethod
    def verify(self, source: Path, properties: list[str]) -> VerifierOutput

class VerifierOutput:
    return_code: int
    result: Literal["verified", "falsified", "unknown", "timeout"]
    issues: list[VerifierIssue]
    counterexample: Counterexample | None
    duration: float

class VerifierIssue:
    property_violated: str
    location: SourceLocation
    trace: list[TraceStep]

class Counterexample:
    variable_assignments: dict[str, Any]
    execution_path: list[TraceStep]
```

### MCP Tool Addition

```python
@mcp.tool()
def check_code_safety(file_path: str, focus: str = None) -> str:
    """Run ESBMC on code, return findings as context"""
    findings = esbmc_context.analyze(Path(file_path), focus=focus)
    if not findings:
        return "ESBMC: No safety issues detected"
    return "\n".join(f"⚠️ {f.location}: {f.message}" for f in findings)

@mcp.tool()
def verify_axiom(axiom_id: str, source_file: str) -> str:
    """Verify an axiom holds for specific code"""
    axiom = get_axiom(axiom_id)
    result = esbmc.verify_property(source_file, axiom.formal_spec)
    if result.verified:
        return f"✓ Axiom verified for {source_file}"
    return f"✗ Counterexample: {result.counterexample}"
```

---

## Implementation Tiers

| Tier | Effort | Value | Description |
|------|--------|-------|-------------|
| **1** | Low | High | Counterexample context - concrete examples |
| **2** | Low | High | Relevance filtering - 90% token reduction |
| **3** | Medium | High | Axiom verification - confidence = 1.0 |
| **4** | Medium | Medium | Augmented repair - better fix suggestions |
| **5** | Medium | High | Incremental feedback - catch bugs during generation |
| **6** | Medium | Medium | Axiom mining - discover implicit contracts |
| **7** | High | Medium | WP inference - auto-refine precision |
| **8** | High | High | Compositional - scale to large codebases |
| **9** | Low | Medium | Drift detection - keep axioms fresh |

**Recommended starting point**: Tiers 1-2 provide highest ROI with lowest effort.

---

## ESBMC-AI Patterns to Adopt

### 1. Subprocess Management
```python
esbmc_cmd = [esbmc_path] + params
esbmc_cmd.extend(["--timeout", str(timeout - 5) + "s"])  # 5s grace period
esbmc_cmd.extend(["--function", entry_function])
esbmc_cmd.append("--show-stacktrace")
```

### 2. Output Parsing
ESBMC-AI has 710 lines of output parsing. Key patterns:
- Split on `[Counterexample]` markers
- Extract `State N file X line Y` blocks
- Capture variable assignments between state markers
- Filter traces to relevant files only

### 3. Caching
```python
cache_key = sha512(source + properties + solver_version + config)
# Cache verification results to avoid redundant checks
```

### 4. Hierarchical Configuration
```toml
[verifier.esbmc]
path = "/usr/bin/esbmc"
timeout = 60
extra_args = ["--no-unwinding-assertions"]

[verifier.z3]
timeout = 30
```

---

## ESBMC Quick Reference

### Common Flags

| Flag | Purpose |
|------|---------|
| `--std c++20` | C++20 parsing (required) |
| `--overflow-check` | Detect integer overflows |
| `--memory-leak-check` | Find unfreed memory |
| `--pointer-check` | Null/invalid pointer detection |
| `--unwind N` | Loop unwinding limit |
| `--k-induction` | Prove properties for any loop depth |
| `--incremental-bmc` | Faster for iterative verification |

### Verification Loop

```
1. Write code with assert() or __ESBMC_assert()
2. Run: esbmc {file} --std c++20 --overflow-check --pointer-check
3. If FAILED: Read counterexample trace (State X: variable == VALUE)
4. Fix using concrete values from trace
5. Repeat until VERIFICATION SUCCESSFUL
```

### ESBMC Intrinsics

```c++
__ESBMC_assume(condition);     // Constrain solver's search space
__ESBMC_assert(cond, "msg");   // Property to prove
```

---

## Big Picture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AXIOM + ESBMC                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ESBMC provides:              Axiom provides:                      │
│   ├─ Concrete counterexamples  ├─ Semantic knowledge                │
│   ├─ Formal verification       ├─ Project patterns                  │
│   ├─ Path exploration          ├─ Cross-reference to standards      │
│   └─ Proof witnesses           └─ Human-curated wisdom              │
│                                                                     │
│                         ↓↓↓                                         │
│                                                                     │
│   LLM gets:                                                         │
│   ├─ "Here's a concrete input that breaks your code"               │
│   ├─ "Here's why it's wrong (axiom + standard reference)"          │
│   ├─ "Here's how similar bugs were fixed in this project"          │
│   └─ "Here's proof that your fix actually works"                   │
│                                                                     │
│   Result: LLM self-corrects faster, with fewer iterations,          │
│           using less context, with higher confidence                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

The key is that **ESBMC makes axioms actionable**. Instead of "here's a rule you might be breaking," it's "here's *exactly* how you're breaking it, *exactly* when, with *exactly* what inputs."
