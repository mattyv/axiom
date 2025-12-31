# MCP Tool Test Report

This document demonstrates the axiom MCP server functionality across all layers of the knowledge base.

## System Statistics

```
Axioms:           3,541
Error Codes:      248
Modules:          803
Vector Embeddings: 10,255
```

## Layers Tested

| Layer | Description | Axiom Count |
|-------|-------------|-------------|
| c11_core | C11 language semantics (K-Framework) | ~890 |
| c11_stdlib | C11 standard library | ~590 |
| cpp_core | C++ core language semantics | ~825 |
| cpp20_language | C++20 language features | ~350 |
| cpp20_stdlib | C++20 standard library | ~275 |
| library | User libraries (ILP_FOR) | ~935 |

---

## Tool: `search_axioms`

### Test 1: C Memory Allocation (with pairing expansion)

**Query:** `malloc memory allocation`

**Result:** Returns malloc axiom plus paired functions (free, realloc) with annotations:

```
### c11_libc_stdlib_syntax_malloc_c1551473
**Function**: `malloc` | **Header**: `stdlib.h`
**Content**: The malloc function allocates space for an object...

### c11_libc_stdlib_syntax_realloc_94b91083
**(paired with `c11_libc_stdlib_syntax_malloc_c1551473`)**
**Function**: `realloc`

### c11_libc_stdlib_syntax_comparison_84c63abe
**(paired with `c11_libc_stdlib_syntax_malloc_c1551473`)**
**Function**: `free`
```

### Test 2: C++20 Move Semantics

**Query:** `move semantics rvalue reference`

**Result:**
```
### cpp20_move_returns_rvalue_ref_e4b6d2a8
**Module**: [forward]/10 | **Layer**: cpp20_stdlib
**Function**: `std::move` | **Header**: `<utility>`
**Signature**: `template<class T> constexpr remove_reference_t<T>&& move(T&& t) noexcept`
**Content**: std::move(t) returns static_cast<remove_reference_t<T>&&>(t)...
```

### Test 3: Library Axioms (ILP_FOR)

**Query:** `ILP_FOR loop macro parallel`

**Result:**
```
### ilp_for_macro_postcond_range_for_expansion_u1v2w3x4
**Function**: `ILP_FOR`
**Content**: Macro expands to a range-based for loop...
**Depends on**: 4 axiom(s)
  - for_loop_range_typed_impl_effect_forwards_range_p5q6r7s8
  - ilp_for_range_t_range_single_eval
  - ...
```

### Test 4: Operator new with Idiom Template

**Query:** `operator new memory allocation`

**Result:** Returns axioms plus idiom usage pattern:

```
### cpp20_new_delete_single_new_required_behavior_e5f6a7b8
**Function**: `operator new` | **Header**: `<new>`
**Content**: operator new(size_t) required to return non-null pointer or throw bad_alloc

### cpp20_new_delete_single_delete_precondition_7e8f9a0b
**(paired with `cpp20_new_delete_single_new_required_behavior_e5f6a7b8`)**
**Function**: `operator delete`

### Idiom: new_delete_pair
**Usage pattern**:
T* ptr = new T(args...);
// use ptr
delete ptr;  // MUST call delete on every non-null pointer from new
```

---

## Tool: `validate_claim`

### True Claims (Correctly Validated)

| Claim | Valid | Confidence | Grounding |
|-------|-------|------------|-----------|
| "double free causes undefined behavior" | True | 0.50 | c11_stdlib: free on already-freed |
| "std::move transfers ownership of resources" | True | 0.50 | cpp20_stdlib: [forward]/10 |
| "ILP_FOR requires ILP_END to close the loop" | True | 0.80 | library axioms |
| "calling free on a null pointer is safe" | True | 0.50 | c11_stdlib (correct per C standard) |
| "accessing an object after its lifetime has ended is undefined behavior" | True | 0.50 | cpp20: [basic.life]/8 |
| "std::shared_ptr automatically calls delete when reference count reaches zero" | True | 0.50 | cpp20_stdlib |

### False Claims (Correctly Rejected)

| Claim | Valid | Confidence | Contradiction Found |
|-------|-------|------------|---------------------|
| "dereferencing a null pointer is safe in C" | False | 0.10 | c11_stdlib: null pointer constraints |
| "signed integer overflow wraps around in C" | False | 0.10 | cpp_core: signed overflow is UB |
| "using delete on memory allocated with malloc is valid" | False | 0.30 | cpp20: delete requires new-allocated memory |

### Known False Positives (still in MVP and nobodies perfect)

| Claim | Expected | Got | Issue |
|-------|----------|-----|-------|
| "reading from an uninitialized variable is always safe" | False | True (0.50) | Vocabulary gap - found "vacuous initialization" but missed UB |

---

## Tool: `get_axiom`

**Query:** `c11_libc_stdlib_syntax_malloc_c1551473`

**Result:**
```
## Axiom: c11_libc_stdlib_syntax_malloc_c1551473

**Module**: LIBC-STDLIB-SYNTAX
**Layer**: c11_stdlib
**Function**: `malloc`
**Header**: `stdlib.h`

### Content
The malloc function allocates space for an object whose size is specified
by size and whose value is indeterminate.

### Dependents
2 axiom(s) depend on this:
- `c11_libc_stdlib_syntax_calloc_f2c846a8` (`calloc`)
- `c11_libc_stdlib_syntax_realloc_5902cc0a` (`realloc`)

### Paired With
This axiom pairs with the following (must be used together):
- `c11_libc_stdlib_syntax_realloc_94b91083` (`realloc`)
- `c11_libc_stdlib_syntax_comparison_84c63abe` (`free`)
```

---

## Tool: `search_by_section`

### Test 1: Object Lifetime

**Query:** `basic.life`

**Result:** Found 14 axioms including:
- `cpp20_basic_life_end_without_destructor_9c0d1e2f`
- `cpp20_basic_life_glvalue_properties_well_defined_2d3e4f5a`
- `cpp20_basic_life_indirection_limited_use_7f8a9b0c`
- `cpp20_basic_life_launder_required_6c7d8e9f`
- ...

### Test 2: Delete Expressions

**Query:** `expr.delete`

**Result:** Found 25 axioms covering:
- Virtual destructor requirements
- Array vs single-object delete
- Deallocation function selection
- Incomplete type handling
- Null pointer behavior

---

## Tool: `check_duplicates`

**Query:** `malloc allocates memory and returns a pointer` (threshold: 0.7)

**Result:**
```
## Duplicate Check Results

### UNIQUE

No similar axioms found above threshold. Safe to add.
```

---

## Tool: `get_stats`

**Result:**
```
## Axiom Knowledge Base Statistics

- Axioms: 3541
- Error Codes: 248
- Modules: 803
- Vector Embeddings: 10255
```

---

## Function Pairings

40 pairings loaded from K semantics and TOML manifests:

### From K Semantics (Cell-Based Detection)
| Opener | Closer | Cell | Confidence |
|--------|--------|------|------------|
| malloc | free | malloced | 1.0 |
| malloc | realloc | malloced | 0.8 |
| realloc | free | malloced | 0.8 |

### From TOML Manifests
| Opener | Closer | Evidence |
|--------|--------|----------|
| operator new | operator delete | Memory allocation/deallocation |
| operator new[] | operator delete[] | Array allocation/deallocation |
| ILP_FOR | ILP_END | Loop macro pairing |
| std::make_shared | std::shared_ptr::~shared_ptr | RAII ref counting |
| push_back | pop_back | Container operations |
| std::condition_variable::wait | std::condition_variable::notify_one | Thread sync |

---

## Cross-Layer Dependency Chains

Library axioms link to foundation axioms via `depends_on`:

```
ILP_FOR (library)
  └── for_loop_range_typed_impl (library)
        └── cpp20_dcl_init_ref_reference_related_def (cpp20_language)
              └── cpp20_dcl_init_ref_not_direct_bind_definition (cpp20_language)
```

---

## Summary

| Capability | Status |
|------------|--------|
| Semantic search across all layers | ✅ Working |
| Pairing expansion in search results | ✅ Working |
| Idiom templates in search results | ✅ Working |
| Claim validation with proof chains | ✅ Working |
| Contradiction detection | ⚠️ Partial (vocabulary gaps) |
| Section-based lookup | ✅ Working |
| Duplicate detection | ✅ Working |
| Direct axiom retrieval | ✅ Working |
| Cross-layer DEPENDS_ON traversal | ✅ Working |
