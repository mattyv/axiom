# Foundation Layer Axioms

This document explains how the C/C++ foundation layer axioms were generated and how to rebuild them if needed.

## Overview

Axiom includes 3,500+ pre-extracted foundation axioms that form the ground truth for C/C++ semantics. These are organized into layers:

| Layer | Count | Source | Description |
|-------|-------|--------|-------------|
| `c11_core` | ~890 | K-Framework C semantics | C11 language semantics |
| `c11_stdlib` | ~590 | K-Framework C semantics | C11 standard library |
| `cpp_core` | ~825 | K-Framework C++ semantics | C++ core language |
| `cpp_stdlib` | ~1 | K-Framework C++ semantics | C++ stdlib (minimal) |
| `cpp20_language` | ~300-400 | eel.is/c++draft | C++20 language features |
| `cpp20_stdlib` | ~200-300 | eel.is/c++draft | C++20 standard library |

**Total**: ~3,541 axioms

## Layer Dependency Chain

Foundation layers must be extracted and loaded in this order:

```
c11_core → c11_stdlib → cpp_core → cpp_stdlib → cpp20_language → cpp20_stdlib
    ↓           ↓           ↓           ↓              ↓               ↓
 [ingest]   [ingest]    [ingest]    [ingest]       [ingest]        [ingest]
```

Each layer can reference axioms from previously loaded layers via `depends_on` fields.

## How Foundation Axioms Were Generated

### 1. K-Framework Layers (c11_core, c11_stdlib, cpp_core, cpp_stdlib)

**Source**: [K-Framework C/C++ Semantics](https://github.com/kframework/c-semantics)

**Script**: `scripts/bootstrap.py`

**Method**: Direct extraction from formal K semantics (`.k` files)

The K-Framework provides formal executable semantics for C and C++. The `bootstrap.py` script:
1. Parses `.k` files from the K-Framework C semantics repository
2. Extracts rules, syntax definitions, and configuration cells
3. Converts K semantic rules into axiom format
4. Extracts human-readable axioms from `\fromStandard` comments
5. Outputs TOML files and loads into Neo4j/LanceDB

**Example K rule extraction:**
```k
rule <k> X / 0 => undefined ... </k>
```
Becomes:
```toml
[[axioms]]
id = "c11_expr_div_by_zero_ub"
content = "Division by zero is undefined behavior"
formal_spec = "X / 0 => undefined"
layer = "c11_core"
```

### 2. C++20 Layers (cpp20_language, cpp20_stdlib)

**Source**: [C++ Draft Standard](https://eel.is/c++draft)

**Script**: `scripts/extract_cpp20.py`

**Method**: LLM-assisted extraction from HTML spec

The extraction process:
1. Fetches HTML sections from eel.is/c++draft
2. Converts HTML to clean text
3. Uses Claude CLI to extract axioms from spec text
4. Merges with existing TOML files (deduplicates by ID)
5. Outputs to `knowledge/foundations/cpp20_*.toml`

**High-value sections** (defined in `axiom/extractors/prompts.py`):
- **Language**: `basic.life`, `expr.*`, `class.*`, `dcl.*`, `temp.*`, etc.
- **Library**: `util.sharedptr`, `optional`, `variant`, `any`, `expected`, etc.

## Rebuilding Foundation Layers

### Full Rebuild from Scratch

**Warning**: This will clear all databases and rebuild everything. Only do this if you need to regenerate foundation layers.

```bash
# 1. Clear databases
rm -rf data/lancedb/axioms.lance
# Clear Neo4j via Cypher: MATCH (n) DETACH DELETE n

# 2. Extract and ingest K-Framework layers (in order)
for layer in c11_core c11_stdlib cpp_core cpp_stdlib; do
    echo "=== $layer ==="
    python scripts/bootstrap.py --layer $layer --output knowledge/foundations/$layer.toml
    python scripts/ingest.py knowledge/foundations/$layer.toml
done

# 3. Extract and ingest C++20 language axioms
python scripts/extract_cpp20.py --batch-language
python scripts/ingest.py knowledge/foundations/cpp20_language.toml

# 4. Extract and ingest C++20 stdlib axioms
python scripts/extract_cpp20.py --batch-library
python scripts/ingest.py knowledge/foundations/cpp20_stdlib.toml

# 5. Load function pairings
python scripts/load_pairings.py  # C11 from K semantics
python scripts/load_pairings.py --toml knowledge/pairings/cpp20_stdlib.toml  # C++20
```

### Rebuilding a Single Layer

If you only need to update one layer:

```bash
# K-Framework layer
python scripts/bootstrap.py --layer cpp_core --output knowledge/foundations/cpp_core.toml
python scripts/ingest.py knowledge/foundations/cpp_core.toml

# C++20 language (specific section)
python scripts/extract_cpp20.py --section basic.life
python scripts/ingest.py knowledge/foundations/cpp20_language.toml

# C++20 language (all high-value sections)
python scripts/extract_cpp20.py --batch-language
python scripts/ingest.py knowledge/foundations/cpp20_language.toml

# C++20 stdlib (all high-value sections)
python scripts/extract_cpp20.py --batch-library
python scripts/ingest.py knowledge/foundations/cpp20_stdlib.toml
```

### Adding New C++20 Sections

To extract additional sections from the C++ standard:

```bash
# List available sections
python scripts/extract_cpp20.py --list

# Extract a specific section
python scripts/extract_cpp20.py --section thread.mutex

# Dry run (see what would happen)
python scripts/extract_cpp20.py --section thread.mutex --dry-run

# Ingest the updated file
python scripts/ingest.py knowledge/foundations/cpp20_stdlib.toml
```

## Prerequisites for Extraction

### K-Framework Layers

```bash
# Clone K-Framework C semantics (one time)
git clone https://github.com/kframework/c-semantics /tmp/c-semantics

# The bootstrap script expects K semantics at /tmp/c-semantics
# Or specify a custom path:
python scripts/bootstrap.py --layer c11_core --semantics-root /path/to/c-semantics
```

### C++20 Layers

```bash
# Install Claude CLI
pip install claude-cli

# The script uses --dangerously-skip-permissions and --no-history flags
# to automate extraction without user prompts
```

## Post-Extraction Processing

### Dependency Linking

For axioms with C++ signatures, link `depends_on` fields to foundation types:

```bash
# Analyze and link dependencies based on type references in signatures
python scripts/link_depends_on.py knowledge/foundations/cpp20_stdlib.toml

# Dry run (show what would be linked)
python scripts/link_depends_on.py knowledge/foundations/cpp20_stdlib.toml --dry-run

# Force re-link (overwrite existing depends_on)
python scripts/link_depends_on.py knowledge/foundations/cpp20_stdlib.toml --force
```

### Semantic Linking (Optional)

Use LLM to create semantic links to foundation axioms:

```bash
# LLM-based semantic grounding
python scripts/link_semantic.py knowledge/foundations/cpp20_stdlib.toml
```

## TOML File Format

Foundation axioms use this TOML structure:

```toml
version = "1.0"
source = "k-semantics" | "cpp-draft"
extracted_at = "2025-01-01T00:00:00+00:00"

[[axioms]]
id = "unique_id_hash"                      # Unique identifier
content = "Human-readable axiom"           # Plain English description
formal_spec = "formal_notation"            # K rule or formal spec (optional)
layer = "c11_core"                         # Layer name
confidence = 0.95                          # Extraction confidence (0.0-1.0)
source_file = "path/to/source.k"           # Source file (K semantics only)
source_module = "module_name"              # K module (K semantics only)
function = "malloc"                        # Function name (if applicable)
header = "<stdlib.h>"                      # Header file (if applicable)
signature = "void* malloc(size_t size)"    # Full signature with return type
axiom_type = "precondition"                # Type: precondition, postcondition, invariant, etc.
on_violation = "undefined behavior"        # What happens on violation
depends_on = ["axiom_id_1", "axiom_id_2"]  # References to other axioms
```

## Verification

After rebuilding, verify the layer counts:

```bash
# Check axiom counts per layer
python -c "
from axiom.models import AxiomCollection
from pathlib import Path

for f in Path('knowledge/foundations').glob('*.toml'):
    col = AxiomCollection.from_toml(f)
    print(f'{f.stem}: {len(col.axioms)} axioms')
"
```

Expected output:
```
c11_core: ~890 axioms
c11_stdlib: ~590 axioms
cpp_core: ~825 axioms
cpp_stdlib: ~1 axiom
cpp20_language: ~300-400 axioms
cpp20_stdlib: ~200-300 axioms
```

## Troubleshooting

### "K semantics not found"

```bash
# Clone K-Framework C semantics
git clone https://github.com/kframework/c-semantics /tmp/c-semantics
```

### "Claude CLI extraction failed"

```bash
# Ensure Claude CLI is installed and configured
pip install claude-cli

# Check rate limits - add delays between sections
python scripts/extract_cpp20.py --batch-language --delay 5
```

### "depends_on references missing axioms"

This happens when layers are loaded out of order. Rebuild in the correct order:
```
c11_core → c11_stdlib → cpp_core → cpp_stdlib → cpp20_language → cpp20_stdlib
```

## Maintenance

Foundation layers should be updated when:
1. **K-Framework semantics change** - New C/C++ semantic rules are added
2. **C++ standard updates** - New C++ draft sections or revisions
3. **Bug fixes** - Incorrect axioms discovered through validation

Always regenerate layers in dependency order to maintain referential integrity.
