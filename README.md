# Axiom: Grounded Truth Validation for LLMs

[![CI](https://github.com/mattyv/axiom/actions/workflows/ci.yml/badge.svg)](https://github.com/mattyv/axiom/actions/workflows/ci.yml)

**Automatically build knowledge about your C++20 libraries so LLMs stop hallucinating about them.**

## The Problem

LLMs hallucinate about library code because they have no grounding in your library's actual constraints. When an LLM says "you can use `std::string` with `ILP_FOR_T`", there's no mechanism to validate this against the library's real requirements (which might require trivially destructible types).

## The Solution

Axiom automatically extracts axioms (constraints, preconditions, undefined behavior) from:
1. **Your library code** - via header analysis, comment annotations, and LLM-assisted extraction
2. **C++20 foundations** - grounding library axioms in formal language semantics

When an LLM makes a claim about your library, Axiom validates it against the extracted knowledge and returns a proof chain showing why it's valid or invalid.

## How It Works

```
Your Library Code
    |
    v
[Axiom Extraction]
    -> Parse headers, analyze signatures
    -> Extract constraints from comments/docs
    -> LLM-assisted semantic extraction
    |
    v
[Knowledge Graph]
    -> Library axioms linked to C++20 foundations
    -> Function pairings (acquire/release patterns)
    -> Type constraints and preconditions
    |
    v
[MCP Server for Claude Code]
    -> validate_claim: "Can I use X with Y?"
    -> search_axioms: Find relevant constraints
    -> Proof chains back to formal semantics
```

## Quick Start

### 1. Install

```bash
git clone https://github.com/mattyv/axiom.git
cd axiom
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Start Neo4j
docker-compose up -d
```

### 2. Ingest Your Library

```bash
# Interactive extraction from your library
python scripts/ingest_library.py /path/to/your/library

# Or add annotations to your headers:
# // @axiom:pairs_with resource_release
# // @axiom:required true
# void resource_acquire(Resource* r);
```

### 3. Connect to Claude Code

```bash
./scripts/install-mcp.sh
```

Now Claude Code can validate claims against your library's actual constraints.

## For Library Maintainers: Ship Knowledge With Your Library

Library maintainers can ship axiom knowledge alongside their code. Users who have Axiom installed will automatically get accurate LLM assistance for your library.

### Option 1: `.axiom.toml` Manifest

Add a `.axiom.toml` file to your library root:

```toml
# mylib/.axiom.toml
[metadata]
name = "mylib"
version = "1.0.0"

[[pairing]]
opener = "ILP_FOR"
closer = "ILP_END"
required = true
evidence = "Loop macro must be closed with ILP_END"

[[axiom]]
function = "ILP_FOR_T"
constraint = "trivially_destructible<T>"
evidence = "SmallStorage optimization requires trivial types"
```

### Option 2: Header Annotations

Add structured comments directly in your headers:

```cpp
// @axiom:pairs_with ILP_END
// @axiom:required true
#define ILP_FOR(type, var, start, end, N) ...

// @axiom:constraint trivially_destructible
// @axiom:evidence "SmallStorage requires trivial types"
template<typename T>
class ILP_FOR_T { ... };
```

### What Users Get

When a user runs `python scripts/ingest_library.py /path/to/mylib`, Axiom automatically:
1. Discovers your `.axiom.toml` or header annotations
2. Links your constraints to C++20 foundations
3. Loads into the knowledge graph (Neo4j + LanceDB)

The MCP server then provides RAG (Retrieval-Augmented Generation) for Claude Code:
- Semantic search finds relevant axioms for any query about your library
- Validation catches LLM hallucinations before they become bugs
- Proof chains explain *why* something is valid or invalid

## Foundation Knowledge

Axiom includes pre-extracted C++20 foundations (3,500+ axioms) that your library axioms link to:

| Layer | Description |
|-------|-------------|
| `c11_core` | C11 language semantics from K-Framework |
| `cpp_core` | C++ core language from K-Framework |
| `cpp20_language` | C++20 language features from ISO draft |
| `cpp20_stdlib` | Standard library from ISO draft |

This grounding means when Axiom says "your library function requires a non-null pointer", it can trace that requirement back to formal C++ semantics.

## MCP Tools

When connected to Claude Code:

- **`validate_claim`** - "Can I use std::string with ILP_FOR_T?" → Returns validity + proof chain
- **`search_axioms`** - Find constraints relevant to a query
- **`get_axiom`** - Get details of a specific axiom
- **`get_stats`** - Knowledge base statistics

## Example Validation

**Claim**: "std::string works with ILP_FOR_T"

**Result**:
```
INVALID

Contradiction found:
- ILP_FOR_T requires trivially_destructible types (library axiom)
- std::string has non-trivial destructor (cpp20_stdlib)
- trivially_destructible requires trivial destructor (cpp20_language)

Proof chain:
1. ILP_FOR_T<T> constraint (your_library, conf: 0.9)
2. trivially_destructible concept (cpp20_language, conf: 1.0)
3. std::string destructor (cpp20_stdlib, conf: 0.95)
```

## Current Status

- **Target**: C++20 libraries
- **Foundations**: 3,541 axioms across 6 layers
- **Extraction**: Header parsing, comment annotations, LLM-assisted
- **Integration**: MCP server for Claude Code

## Project Structure

```
axiom/
├── axiom/
│   ├── extractors/      # Extract axioms from sources
│   ├── graph/           # Neo4j graph operations
│   ├── vectors/         # LanceDB semantic search
│   ├── reasoning/       # Validation and proof chains
│   └── mcp/             # Claude Code integration
├── knowledge/
│   ├── foundations/     # C++20 foundation axioms
│   └── pairings/        # Function pairing definitions
└── scripts/
    ├── ingest_library.py    # Extract from your library
    ├── ingest.py            # Load axioms to graph
    └── load_pairings.py     # Load function pairings
```

## License

BSL-1.0

## Author

Matt Varendorff - https://github.com/mattyv
