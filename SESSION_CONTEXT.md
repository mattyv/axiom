# Session Context and Handoff

## Project Overview

**Axiom** is a grounded truth validation system for LLMs using formal axioms from programming language semantics. It combines Neo4j (graph relationships) with LanceDB (semantic search) to create a hybrid knowledge base.

## Key Insight: Compositional Ground Truth

The core idea is building knowledge like physics - from atomic ground truths:
- **Layer 0**: C11 core axioms (confidence 1.0)
- **Layer 1**: C++17/20 core (0.95)
- **Layer 2**: STL semantics (0.85)
- **Layer 3**: Library knowledge (0.7-0.9)

LLMs can validate claims by traversing the graph back to foundational axioms, detecting contradictions and nonsense.

## Critical Understanding: Error Codes ≠ Axioms

**IMPORTANT CORRECTION**: There was confusion in the previous session about error codes vs axioms.

### What Error Codes ARE
- **Error descriptions** of what happens when axioms are violated
- Example from `Error_Codes.csv`:
  ```
  UB-CEM2,Modulo by 0.,6.5.5:5; J.2:1 item 45,Undefined Behavior
  ```
- This describes the **violation**, not the foundational truth

### What Axioms ARE
- **Foundational truths** extracted from K semantic rules
- Found in the `requires` clauses of K rules
- Example from `semantics/c/language/common/expr/multiplicative.k`:
  ```k
  rule tv(I1:Int, T::UType) % tv(I2:Int, T'::UType)
       => intArithInterpret(T, I1 %Int I2)
       requires isPromoted(T)
            andBool T ==Type T'
            andBool notBool isZero(I2)  // ← THIS is the axiom
       [structural]
  ```

### Correct Extraction Approach

**From K Rules** (primary source):
```python
axiom = {
    "id": "c11_modulo_requires_nonzero",
    "content": "Modulo operation requires non-zero divisor",
    "formal_spec": "requires notBool isZero(I2)",
    "violated_by": ["UB-CEM2"],  # Link to error code
    "layer": "c11_core",
    "confidence": 1.0
}
```

**From Error Codes** (validation/linking only):
```python
error = {
    "code": "UB-CEM2",
    "description": "Modulo by 0.",
    "validates_axiom": "c11_modulo_requires_nonzero"
}
```

## Files Created

All files in `/home/mvarendorff/Documents/Code/python/axiom/`:

1. **README.md** - Project vision and overview
2. **ARCHITECTURE.md** - Technical design and component details
3. **MVP_PLAN.md** - 4-phase implementation roadmap
4. **QUICKSTART.md** - Getting started guide
5. **pyproject.toml** - Python dependencies (includes pyk>=0.3.2)
6. **docker-compose.yml** - Neo4j development environment
7. **.gitignore** - Standard Python ignores

## Key Technical Decisions

1. **Hybrid Database**: Neo4j (graph) + LanceDB (vectors)
   - Neo4j for relationship traversal and proof chains
   - LanceDB for semantic search to entry points

2. **Use pyk for K Parsing**: Official K Framework Python library
   - Parse `.k` semantic files directly
   - Extract `requires` clauses as axioms
   - Extract rule patterns as valid operations

3. **Knowledge Source**: K Framework c-semantics
   - Cloned to `/tmp/c-semantics`
   - C11/C17 formal semantics (~150 UB definitions)
   - Semantic files in `semantics/c/**/*.k`

4. **Separate from Lucidity**: This is a new project
   - Lucidity: Questionnaire system for library knowledge extraction
   - Axiom: Validation system using formal axioms

## Next Steps

### Immediate Tasks

1. **Create directory structure**:
   ```
   axiom/
   ├── extractors/
   │   ├── __init__.py
   │   └── k_semantics.py      # pyk-based K rule parser
   ├── knowledge/
   │   └── foundations/
   │       └── c11_axioms.json # Extracted axioms
   ├── graph/
   │   ├── __init__.py
   │   └── neo4j_loader.py     # Load axioms into Neo4j
   └── vector/
       ├── __init__.py
       └── lancedb_loader.py   # Load embeddings
   ```

2. **Write K Semantics Extractor** (`axiom/extractors/k_semantics.py`):
   ```python
   from pyk.kast.outer import KDefinition
   from pyk.ktool.kprove import KProve

   def extract_axioms_from_k_file(k_file_path):
       """
       Parse K semantic file and extract axioms from requires clauses.

       Returns:
           List of axioms with formal specs and violated_by links
       """
       # Use pyk to parse K definition
       # Extract rules with 'requires' clauses
       # Extract UNDEF/IMPL/CV calls to link error codes
       # Return structured axioms
   ```

3. **Bootstrap Neo4j Graph**:
   - Start Neo4j: `docker-compose up -d`
   - Create schema (Axiom nodes, DEPENDS_ON relationships)
   - Load C11 axioms from extracted JSON

4. **Validate with Error Codes**:
   - Parse `/tmp/c-semantics/examples/c/error-codes/Error_Codes.csv`
   - Check that all error codes have corresponding axioms
   - Use for completeness validation only

### Phase 1 Goals (2-3 weeks)

- Extract all C11 axioms from K semantics
- Setup Neo4j + LanceDB
- Implement basic proof chain traversal
- Validate one library claim against C11 axioms

## Important Context

### Why This Matters

Current RAG systems inject raw code semantically but can't validate LLM claims against foundational truths. Axiom creates proof chains:

```
LLM Claim: "This code is safe"
    ↓
Library Knowledge: "Function X doesn't check bounds"
    ↓ [DEPENDS_ON]
STL Knowledge: "std::vector::operator[] doesn't validate"
    ↓ [DERIVES_FROM]
C++ Axiom: "Unchecked array access is UB"
    ↓ [GROUNDED_IN]
C11 Axiom: "Out of bounds access → undefined behavior"
```

### Repository Locations

- **Axiom Project**: `/home/mvarendorff/Documents/Code/python/axiom/`
- **K Semantics**: `/tmp/c-semantics/`
  - Error codes: `examples/c/error-codes/Error_Codes.csv`
  - Semantic rules: `semantics/c/**/*.k`
- **Lucidity Project**: `/home/mvarendorff/Documents/Code/cpp/lucidity/`

### Git Status

Axiom project needs initial commit:
```bash
cd /home/mvarendorff/Documents/Code/python/axiom
git add .
git commit -m "Initial project setup with architecture and planning docs"
git push origin main
```

## User's Vision

From user's own words:

> "i imagine a system build of a handfull of atomic ground truths (like in physics) that are combine tother to forumlate other truths... c++20 or 17 is constructed off this. then the STL. then a library of the user chouse is build ontop of this foundational layer."

> "i i'magine semantic search to get a an entry and graph to traverse. the idea of the graphical side in my head is to traverse to allow the LLM to know if its talking nonsenes and find core truths easily about what the LLM may need to know."

This is about **compositional truth** and **contradiction detection**, not just semantic code injection.

## Questions for Next Session

1. Should we extract ALL K rules or focus on UB/implementation-defined behavior first?
2. How to handle C++17/20 axioms (no formal K semantics available)?
3. Should proof chains be pre-computed or computed on-demand?
4. What's the embedding strategy for axioms (whole axiom vs. decomposed components)?

## Ready to Start

All documentation and configuration is in place. Next session should:
1. Review this context
2. Create directory structure
3. Implement K semantics extractor using pyk
4. Bootstrap the knowledge graph

The foundation is solid. Time to build.
