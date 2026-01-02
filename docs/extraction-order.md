# Axiom Extraction Order

When rebuilding the knowledge base from scratch, axioms must be extracted and loaded in this order:

## Scripts Overview

| Script | Purpose |
|--------|---------|
| `scripts/bootstrap.py` | Extract axioms from K-Framework semantics (*.k files) |
| `scripts/extract_cpp20.py` | Extract axioms from C++ draft spec (eel.is/c++draft) |
| `scripts/ingest.py` | Load TOML axioms into Neo4j and LanceDB |
| `scripts/extract_clang.py` | **Native Clang extraction** from C/C++ libraries (recommended) |
| `scripts/extract_library.py` | Interactive tree-sitter + LLM extraction from C/C++ libraries |
| `scripts/extract_stdlib.py` | Extract axioms from C++ stdlib headers |
| `scripts/link_depends_on.py` | Regex-based linking (types from signatures) |
| `scripts/link_semantic.py` | LLM-based linking (semantic grounding to foundations) |
| `scripts/load_pairings.py` | Load function pairings into Neo4j (K semantics or TOML) |

## 1. Foundation Axioms (K-semantics based)

**Script**: `scripts/bootstrap.py`

These are extracted from the K-Framework C/C++ semantics and provide the ground truth for language behavior.

- `c11_core` - C11 language semantics
- `c11_stdlib` - C11 standard library (includes C function signatures from profile headers)
- `cpp_core` - C++ core language semantics
- `cpp_stdlib` - C++ standard library (minimal - K-Framework only has `new.k`)

### Extraction Commands

```bash
# Clone K-Framework C semantics (if not already done)
git clone https://github.com/kframework/c-semantics /tmp/c-semantics

# Extract each layer (bootstrap.py also loads into Neo4j and LanceDB)
python scripts/bootstrap.py --layer c11_core --output knowledge/foundations/c11_core.toml
python scripts/bootstrap.py --layer c11_stdlib --output knowledge/foundations/c11_stdlib.toml
python scripts/bootstrap.py --layer cpp_core --output knowledge/foundations/cpp_core.toml
python scripts/bootstrap.py --layer cpp_stdlib --output knowledge/foundations/cpp_stdlib.toml
```

**IMPORTANT**: Do NOT use `--skip-graph` or `--skip-vectors` flags during extraction.
These flags skip the `depends_on` linking step, which is required for axiom relationships.
The TOML files in git already have `depends_on` computed - if you re-extract with skip flags,
you'll lose those links.

### Expected Axiom Counts
- c11_core: ~890 axioms (includes ~53 human-readable axioms from `\fromStandard` comments)
- c11_stdlib: ~590 axioms
- cpp_core: ~825 axioms
- cpp_stdlib: ~1 axiom (K-Framework C++ stdlib is minimal)

## 2. C++20 Axioms (LLM-extracted from eel.is/c++draft)

**Script**: `scripts/extract_cpp20.py`

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

### Ingestion (after extraction)

**Script**: `scripts/ingest.py`

```bash
# Ingest language axioms
python scripts/ingest.py knowledge/foundations/cpp20_language.toml

# Ingest library axioms
python scripts/ingest.py knowledge/foundations/cpp20_stdlib.toml
```

### Output Files
- Language axioms: `knowledge/foundations/cpp20_language.toml`
- Library axioms: `knowledge/foundations/cpp20_stdlib.toml`

### Expected Axiom Counts
- cpp20_language: ~300-400 axioms
- cpp20_stdlib: ~200-300 axioms

### Post-Extraction Dependency Linking

For stdlib-style axioms with C++ signatures, run the linker to populate `depends_on` fields:

```bash
# Analyze and link dependencies based on signatures
python scripts/link_depends_on.py knowledge/foundations/cpp20_stdlib.toml

# Dry run (show what would be linked without making changes)
python scripts/link_depends_on.py knowledge/foundations/cpp20_stdlib.toml --dry-run

# Force re-link (overwrite existing depends_on)
python scripts/link_depends_on.py knowledge/foundations/cpp20_stdlib.toml --force
```

The linker parses C++ signatures to extract type references (references, pointers, iterators, exceptions) and uses semantic search to find matching foundation axioms.

### Notes
- Uses Claude CLI with `--dangerously-skip-permissions` and `--no-history`
- Fetches HTML from eel.is/c++draft and converts to text
- Merges new axioms with existing file (deduplicates by ID)
- Section lists defined in `axiom/extractors/prompts.py`

## 3. Library Axioms (from source code)

There are two approaches for extracting axioms from C/C++ source files:

### Option A: Native Clang Extraction (Recommended)

**Script**: `scripts/extract_clang.py`

Uses Clang LibTooling for high-confidence extraction with call graph propagation.

```bash
# Build the C++ tool first
cd tools/axiom-extract && mkdir -p build && cd build
cmake .. && make

# Extract from a single file
python scripts/extract_clang.py \
    --file /path/to/mylib.cpp \
    --args="-std=c++20" \
    --output mylib_axioms.toml

# Extract from a directory (recursive)
python scripts/extract_clang.py \
    -r --file /path/to/library/ \
    --output mylib_axioms.toml

# With compile_commands.json (best for complex projects)
python scripts/extract_clang.py \
    --compile-commands /path/to/build/compile_commands.json \
    --output mylib_axioms.toml

# With LLM fallback for low-confidence axioms (<0.80)
python scripts/extract_clang.py \
    --file /path/to/mylib.cpp \
    --llm-fallback \
    --output mylib_axioms.toml

# Link to foundation axioms (uses vector DB)
python scripts/extract_clang.py \
    --file /path/to/mylib.cpp \
    --link \
    --output mylib_axioms.toml

# Ingest into databases
python scripts/ingest.py mylib_axioms.toml
```

**Features:**
- Confidence 0.95-1.0 for compiler-enforced constraints
- Call graph extraction with precondition propagation
- Automatic LanceDB linking to foundation axioms
- Optional LLM refinement for low-confidence axioms

### Option B: Tree-sitter + LLM Extraction (Interactive)

**Script**: `scripts/extract_library.py`

Uses tree-sitter parsing + LLM analysis with interactive review.

```bash
# Extract axioms from a library directory
python scripts/extract_library.py -r /path/to/library/

# Interactive review process follows
# Accept/reject each axiom, then export

# Export approved axioms to TOML
python scripts/extract_library.py --export <session_id> -o mylib_axioms.toml

# Link depends_on for functions with typed signatures (regex-based)
python scripts/link_depends_on.py mylib_axioms.toml

# Link to foundation axioms via LLM semantic analysis (optional, for grounding)
python scripts/link_semantic.py mylib_axioms.toml

# Ingest into databases
python scripts/ingest.py mylib_axioms.toml
```

**Use when:** You want interactive review, or Clang can't parse the code.

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

## Quick Re-ingest (Most Common)

Most of the time you just need to re-ingest the existing TOML files into cleared databases.
Only re-extract if there's a significant change in the extraction system or schema.

```bash
# Clear and re-ingest all foundation axioms (fast - no LLM calls)
python scripts/ingest.py --clear
python scripts/ingest.py knowledge/foundations/c11_core.toml
python scripts/ingest.py knowledge/foundations/c11_stdlib.toml
python scripts/ingest.py knowledge/foundations/cpp_core.toml
python scripts/ingest.py knowledge/foundations/cpp_stdlib.toml
python scripts/ingest.py knowledge/foundations/cpp20_language.toml
python scripts/ingest.py knowledge/foundations/cpp20_stdlib.toml
```

## Full Rebuild Example (Rare)

**WARNING**: Full rebuild requires LLM calls for C++20 extraction and takes significant time.
Only do this when extraction logic or schema has changed significantly.

**CRITICAL**: Each layer must be ingested into the database BEFORE extracting the next layer.
This allows `depends_on` links to reference axioms from previous layers.

```bash
# 1. Clear databases
python scripts/ingest.py --clear

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
# Option A: Native Clang extraction (recommended for C++20 code)
cd tools/axiom-extract && mkdir -p build && cd build && cmake .. && make && cd ../../..
python scripts/extract_clang.py \
    --compile-commands /path/to/mylib/build/compile_commands.json \
    --link \
    --output mylib_axioms.toml
python scripts/ingest.py mylib_axioms.toml

# Option B: Tree-sitter + LLM extraction (interactive review)
# python scripts/extract_library.py -r /path/to/mylib/
# python scripts/extract_library.py --export <session_id> -o mylib_axioms.toml
# python scripts/link_depends_on.py mylib_axioms.toml
# python scripts/link_semantic.py mylib_axioms.toml
# python scripts/ingest.py mylib_axioms.toml
```

### Layer Dependency Chain

```
c11_core → c11_stdlib → cpp_core → cpp_stdlib → cpp20_language → cpp20_stdlib → user_library
    ↓           ↓           ↓           ↓              ↓               ↓
 [ingest]   [ingest]    [ingest]    [ingest]       [ingest]        [ingest]
```

Each extraction can use `depends_on` to link to any previously ingested layer.

## 4. Function Pairings (Graph Relationships)

**Script**: `scripts/load_pairings.py`

Pairings connect axioms that represent functions that must be used together (e.g., malloc/free, lock/unlock). These are loaded AFTER axioms are ingested.

### Loading C11 Pairings (from K semantics)

```bash
# Dry run - see what pairings would be created
python scripts/load_pairings.py --dry-run

# Load pairings into Neo4j
python scripts/load_pairings.py
```

This extracts pairings from K semantics cell access patterns (functions that share a configuration cell like `<malloced>`).

### Loading C++20 Pairings (from TOML manifest)

```bash
# Dry run
python scripts/load_pairings.py --toml knowledge/pairings/cpp20_stdlib.toml --dry-run

# Load pairings
python scripts/load_pairings.py --toml knowledge/pairings/cpp20_stdlib.toml
```

### TOML Manifest Format

```toml
# knowledge/pairings/my-library.toml

[metadata]
layer = "my_library"
version = "1.0.0"

[[pairing]]
opener = "std::make_shared"
closer = "std::shared_ptr::~shared_ptr"
required = true
evidence = "Memory: allocation/deallocation"

[[idiom]]
name = "shared_ptr_scope"
participants = ["std::make_shared", "std::shared_ptr::~shared_ptr"]
template = '''
auto ptr = std::make_shared<T>(args...);
// use ptr
// destructor called automatically
'''
```

### Pairing Sources

| Source | Script/Flag | Confidence |
|--------|-------------|------------|
| K semantics | `--semantics-root` (default) | 1.0 |
| TOML manifest | `--toml <file>` | 1.0 |

### Full Rebuild with Pairings

Add these steps to the full rebuild example:

```bash
# ... after all axioms are ingested ...

# 6. Load function pairings
python scripts/load_pairings.py  # C11 from K semantics
python scripts/load_pairings.py --toml knowledge/pairings/cpp20_stdlib.toml  # C++20
```

### Layer Dependency Chain (Updated)

```
c11_core → c11_stdlib → cpp_core → cpp_stdlib → cpp20_language → cpp20_stdlib → user_library
    ↓           ↓           ↓           ↓              ↓               ↓              ↓
 [ingest]   [ingest]    [ingest]    [ingest]       [ingest]        [ingest]       [ingest]
                                                                                      ↓
                                                                            [load_pairings]
```

Pairings are loaded last since they create PAIRS_WITH relationships between existing axiom nodes.
