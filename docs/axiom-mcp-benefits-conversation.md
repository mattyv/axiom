# Axiom MCP Benefits for C++ Reasoning

*Conversation demonstrating how the Axiom MCP helps ground C++ semantics in formal specifications*

---

## Overview

The Axiom MCP provides a **formal knowledge base of 2,571 axioms** extracted from C11 and C++20 standards with dependency graphs and vector embeddings.

### Key Statistics
- **Axioms**: 2,571
- **Modules**: 1,174
- **Vector Embeddings**: 3,945

---

## Core Benefits

### 1. Grounded Reasoning About UB and Edge Cases

Instead of relying on training data (which may be incomplete or conflated with folklore), claims can be validated against the *actual standard*:

```
Claim: "Dereferencing a dangling pointer is UB"
→ VALID (85% confidence)
→ Grounded in [expr.unary.op]/1: "Dereferencing a pointer that does
   not point to an object or function is undefined behavior"
```

### 2. Section-Based Lookup

Query by standard section (e.g., `[basic.life]`) to get all axioms about a topic. For example, `[basic.life]` returns 14 axioms covering:
- When lifetime begins/ends
- Transparent replacement semantics
- When `std::launder` is required
- What operations are valid on storage before/after lifetime

### 3. Dependency Chains

Axioms have explicit dependencies. When validating "const ref extends temporary lifetime," the proof chain shows:
- `[except.ctor]/3` - exception handling interaction
- `[basic.life]/7` - limited lvalue use rules
- `[dcl.type.cv]/4` - const modification rules

### 4. Coverage of Tricky Areas

The knowledge base covers the hardest parts of C++:
- **Move semantics**: `std::move`, `std::forward`, reference collapsing
- **Template metaprogramming**: SFINAE, substitution failure, constraints
- **Object lifetime**: construction order, destruction order, storage reuse
- **Smart pointers**: `unique_ptr`, `shared_ptr` aliasing, `weak_ptr` semantics

---

## Examples: Where Training Fails, MCP Succeeds

### Example 1: Pointer Use After Lifetime

**Common belief (from training):**
> "After an object's lifetime ends, using a pointer to it is undefined behavior."

**MCP Validation Result:**
```
Claim: "Using a pointer to an object after its lifetime has ended is always undefined behavior"
Valid: False
Confidence: 0.10

Contradiction Found:
- cpp20_basic_life_ptr_void_star_well_defined_3b4c5d6e
  "Before an object's lifetime starts or after it ends, a pointer to the
   storage location may be used as if the pointer were of type void* and
   such use is well-defined."
```

**The Truth (per [basic.life]/7):**
You *can* use a pointer after lifetime ends - you just can't dereference it for most operations. Treating it as `void*` is well-defined. This matters for placement new patterns.

---

### Example 2: Signed Integer Overflow

**Common belief:**
> "Signed integer overflow is always undefined behavior in C++."

**MCP Validation Result:**
```
Claim: "Signed integer overflow is undefined behavior in C++"
Valid: True
Confidence: 0.95

But proof chain reveals exception:
- cpp20_atomics_ref_int_signed_overflow_no_ub_f0a4b8c2 [[atomics.ref.int]/8]
  "For signed integer types in fetch_key operations, the computation is
   performed as if converted to unsigned, computed, and converted back,
   resulting in no undefined behavior from overflow."
```

**The Nuance:**
```cpp
int x = INT_MAX;
x + 1;  // UB

std::atomic<int> a{INT_MAX};
a.fetch_add(1);  // Well-defined! Wraps to INT_MIN
```

---

### Example 3: Placement New and Transparent Replacement

**Common belief:**
> "After placement new, you can just use the old pointer to access the new object."

**MCP Validation Result:**
```
Claim: "After using placement new to create a new object in the storage of
        an old object, you can always use the old pointer to access the new object"
Valid: True
Confidence: 0.50  ← Low confidence signals nuance!

Proof chain reveals:
- cpp20_basic_life_launder_required_6c7d8e9f [[basic.life]/10]
  "If transparent replacement conditions are not met, a pointer to the new
   object can be obtained from a pointer that represents the address of its
   storage by calling std::launder."
```

**The Truth:**
Transparent replacement fails when the type has `const` or reference members:

```cpp
struct S {
    const int n;  // const member!
};

S* p = new S{42};
new (p) S{43};     // placement new
int x = p->n;      // UB! Not transparently replaceable due to const member

int y = std::launder(p)->n;  // OK, returns 43
```

---

## Summary: Training vs MCP

| Scenario | Training Says | MCP Corrects |
|----------|---------------|--------------|
| Pointer after lifetime | "It's UB" | You can use it as `void*` |
| Signed overflow | "Always UB" | Atomics wrap, defined behavior |
| Placement new pointer reuse | "Just works" | Need `std::launder` for const/ref members |
| Lifetime rules | General intuition | 14 specific axioms with formal specs |

---

## Sample Axioms

### Object Lifetime ([basic.life])

```
cpp20_basic_life_end_without_destructor_9c0d1e2f
Module: [basic.life]/6
Content: A program may end the lifetime of an object of class type without
         invoking the destructor, by reusing or releasing the storage.
Formal: is_class_type(T) && type(obj) == T &&
        (storage_reused(obj) || storage_released(obj)) =>
        lifetime_ended(obj) && !destructor_invoked(obj)
```

### Move Semantics

```
cpp20_move_returns_rvalue_ref_e4b6d2a8
Module: [forward]/10
Function: std::move
Content: std::move(t) returns static_cast<remove_reference_t<T>&&>(t),
         unconditionally casting t to an rvalue reference to enable move semantics.
Formal: call(std::move<T>, T&&) => static_cast<remove_reference_t<T>&&>(t)
```

### Template Instantiation

```
cpp20_temp_alias_template_id_substitution_failure_8a3f1b2e
Module: [temp.alias]/2
Content: A template-id that names a specialization of an alias template is
         ill-formed if forming the associated type results in substitution failure.
Formal: alias_template_specialization(template_id) &&
        substitution_failure(associated_type(template_id)) => ill_formed
```

---

## Conclusion

The Axiom MCP provides **grounded refutation** with section citations and confidence scores, rather than allowing confident statements of half-truths from training data. For C++, where "works on my machine" and "actually correct per the standard" are often different things, this formal grounding is essential.
