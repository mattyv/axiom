# Axiom Extraction Order

When rebuilding the knowledge base from scratch, axioms must be extracted and loaded in this order:

## 1. Foundation Axioms (K-semantics based)

These are extracted from the K-Framework C/C++ semantics and provide the ground truth for language behavior.

- `c11_core` - C11 language semantics
- `c11_stdlib` - C11 standard library
- `cpp_core` - C++ core language semantics
- `cpp_stdlib` - C++ standard library (minimal - K-Framework only has `new.k`)

### Extraction Commands

```bash
# Clone K-Framework C semantics (if not already done)
git clone https://github.com/kframework/c-semantics /tmp/c-semantics

# Extract each layer
python scripts/bootstrap.py --layer c11_core --output knowledge/foundations/c11_core.toml
python scripts/bootstrap.py --layer c11_stdlib --output knowledge/foundations/c11_stdlib.toml
python scripts/bootstrap.py --layer cpp_core --output knowledge/foundations/cpp_core.toml
python scripts/bootstrap.py --layer cpp_stdlib --output knowledge/foundations/cpp_stdlib.toml
```

### Expected Axiom Counts
- c11_core: ~790 axioms
- c11_stdlib: ~290 axioms
- cpp_core: ~743 axioms
- cpp_stdlib: ~1 axiom (K-Framework C++ stdlib is minimal)

## 2. C++20 Axioms (LLM-extracted from eel.is/c++draft)

These are extracted from the C++ standard draft using Claude CLI.

- `cpp20_language` - C++20 language features (basic.life, expr.*, class.*, etc.)
- `cpp20_stdlib` - C++20 standard library (any, optional, variant, etc.)

### Extraction Commands

```bash
# List available sections
python scripts/extract_cpp20.py --list

# Extract single section
python scripts/extract_cpp20.py --section basic.life

# Extract all language sections (HIGH_SIGNAL_SECTIONS)
python scripts/extract_cpp20.py --batch-language

# Extract all library sections (HIGH_SIGNAL_LIBRARY_SECTIONS)
python scripts/extract_cpp20.py --batch-library

# Dry run (show what would happen without calling Claude)
python scripts/extract_cpp20.py --batch-language --dry-run
```

### Output Files
- Language axioms: `knowledge/foundations/cpp20_language.toml`
- Library axioms: `knowledge/foundations/cpp20_stdlib.toml`

### Expected Axiom Counts
- cpp20_language: ~1000-1200 axioms
- cpp20_stdlib: ~500-600 axioms

### Notes
- Uses Claude CLI with `--dangerously-skip-permissions`
- Fetches HTML from eel.is/c++draft and converts to text
- Merges new axioms with existing file (deduplicates by ID)
- Section lists defined in `axiom/extractors/prompts.py`

## 3. Library Axioms (LLM-extracted from source code)

These are extracted from actual C/C++ source files using tree-sitter parsing + LLM analysis.

- User libraries like ILP_FOR, etc.
- These depend on foundation axioms via `depends_on` field

### Extraction Commands

```bash
# Extract axioms from a library directory
python scripts/ingest_library.py -r /path/to/library/

# Interactive review process follows
# Accept/reject each axiom, then export

# Export approved axioms to TOML
python scripts/ingest_library.py --export <session_id> -o mylib_axioms.toml
```

## Why This Order Matters

Library axioms use RAG to find related foundation axioms during extraction. The foundation axioms must be in the vector DB first so the LLM can reference them when extracting library semantics.

## Function Signatures in Axiom Space

For library axioms (both C++20 stdlib and user libraries), each function axiom MUST include:

1. **`signature`** - Full function signature WITH return type
   - Return type is critical for correct usage even though not formally part of C++ signature
   - Example: `T& std::optional<T>::value()` not just `std::optional<T>::value()`

2. **`function`** - Function name (e.g., `std::optional::value`)

3. **`header`** - Header file (e.g., `<optional>`)

4. **`depends_on`** - Links to axioms for each type used in signature
   - Return type should link to relevant type axioms
   - Each argument type should link to relevant type axioms
   - Example: `malloc(size_t)` should depend on `size_t` axioms and pointer axioms

### Example

```toml
[[axioms]]
id = "cpp20_optional_value_precondition_a1b2c3d4"
content = '''Calling value() on an empty optional throws bad_optional_access'''
formal_spec = '''!has_value() && call(value) => throws(bad_optional_access)'''
layer = "cpp20_stdlib"
function = "std::optional::value"
header = "<optional>"
signature = '''T& std::optional<T>::value()'''
depends_on = ['cpp20_optional_has_value_...', 'cpp20_bad_optional_access_...']
```

This enables RAG to return not just the axiom but also its full signature and type dependencies.

## Loading Axioms into Databases

After extraction, load axioms into Neo4j and LanceDB:

```bash
# Load all foundation axioms
python scripts/ingest.py knowledge/foundations/*.toml

# Load library axioms
python scripts/ingest.py mylib_axioms.toml
```

## Full Rebuild Example

**CRITICAL**: Each layer must be ingested into the database BEFORE extracting the next layer.
This allows `depends_on` links to reference axioms from previous layers.

```bash
# 1. Clear databases
rm -rf data/lancedb/axioms.lance
# Clear Neo4j via cypher: MATCH (n) DETACH DELETE n

# 2. Extract and ingest K foundation axioms (each layer before the next)
python scripts/bootstrap.py --layer c11_core --output knowledge/foundations/c11_core.toml
python scripts/ingest.py knowledge/foundations/c11_core.toml

python scripts/bootstrap.py --layer c11_stdlib --output knowledge/foundations/c11_stdlib.toml
python scripts/ingest.py knowledge/foundations/c11_stdlib.toml

python scripts/bootstrap.py --layer cpp_core --output knowledge/foundations/cpp_core.toml
python scripts/ingest.py knowledge/foundations/cpp_core.toml

python scripts/bootstrap.py --layer cpp_stdlib --output knowledge/foundations/cpp_stdlib.toml
python scripts/ingest.py knowledge/foundations/cpp_stdlib.toml

# 3. Extract and ingest C++20 language axioms
python scripts/extract_cpp20.py --batch-language
python scripts/ingest.py knowledge/foundations/cpp20_language.toml

# 4. Extract and ingest C++20 stdlib axioms (can now depend on language axioms)
python scripts/extract_cpp20.py --batch-library
python scripts/ingest.py knowledge/foundations/cpp20_stdlib.toml

# 5. Extract and load a library (can now depend on all foundation axioms)
python scripts/ingest_library.py -r /path/to/mylib/
python scripts/ingest_library.py --export <session_id> -o mylib_axioms.toml
python scripts/ingest.py mylib_axioms.toml
```

### Layer Dependency Chain

```
c11_core → c11_stdlib → cpp_core → cpp_stdlib → cpp20_language → cpp20_stdlib → user_library
    ↓           ↓           ↓           ↓              ↓               ↓
 [ingest]   [ingest]    [ingest]    [ingest]       [ingest]        [ingest]
```

Each extraction can use `depends_on` to link to any previously ingested layer.
