# Axiom: Grounded Truth Validation for LLMs

[![CI](https://github.com/mattyv/axiom/actions/workflows/ci.yml/badge.svg)](https://github.com/mattyv/axiom/actions/workflows/ci.yml)

A **grounded knowledge system** that validates LLM outputs against formal axioms, providing proof chains and catching hallucinations.

## The Core Problem

LLMs hallucinate because they lack grounding in formal axioms. When an LLM says "signed integer overflow wraps around in C", there's no mechanism to validate this against the C11 standard which defines it as undefined behavior.

## The Solution

A layered knowledge graph that:
1. **Grounds knowledge in formal semantics** (C11/C++20 from K-Framework and ISO standards)
2. **Validates LLM outputs** via semantic search + proof chain traversal
3. **Provides explainable confidence scores** based on axiom depth
4. **Detects contradictions** between LLM claims and foundational truths

## Current Status

**Knowledge Base**: 3,541 axioms across 6 foundation layers:

| Layer | Axioms | Source |
|-------|--------|--------|
| `c11_core` | ~700 | K-Framework C semantics |
| `c11_stdlib` | ~500 | K-Framework stdlib |
| `cpp_core` | ~650 | K-Framework C++ semantics |
| `cpp_stdlib` | ~100 | K-Framework C++ stdlib |
| `cpp20_language` | ~450 | C++ draft spec (eel.is) |
| `cpp20_stdlib` | ~250 | C++ draft spec (eel.is) |

**Features**:
- MCP server for Claude Code integration
- Semantic search via LanceDB embeddings
- Graph traversal via Neo4j
- Function pairing detection (malloc/free, new/delete, etc.)
- Proof chain generation
- Contradiction detection

## Quick Start

### Prerequisites

- Python 3.11+
- Neo4j 5.x (via Docker or native)
- K-Framework C semantics (optional, for extraction)

### Installation

```bash
# Clone and setup
git clone https://github.com/mattyv/axiom.git
cd axiom
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Start Neo4j
docker-compose up -d

# Ingest pre-extracted axioms into Neo4j + LanceDB
python scripts/ingest.py knowledge/foundations/c11_core.toml
python scripts/ingest.py knowledge/foundations/cpp20_language.toml
# ... repeat for other layers

# Load function pairings
python scripts/load_pairings.py --toml knowledge/pairings/cpp20_stdlib.toml
```

### MCP Server (Claude Code Integration)

```bash
# Install MCP server for Claude Code
./scripts/install-mcp.sh

# Or manually add to Claude Code settings
```

The MCP server provides these tools to Claude:
- `validate_claim` - Validate a claim against formal axioms
- `search_axioms` - Search for relevant axioms
- `get_axiom` - Get a specific axiom by ID
- `get_stats` - Get knowledge base statistics

## Architecture

### Hybrid Database Approach

```
User Question/LLM Claim
    |
    v
[Semantic Search - LanceDB]
    -> Find relevant axioms by embedding similarity
    |
    v
[Graph Traversal - Neo4j]
    -> Trace DEPENDS_ON relationships
    -> Build proof chain to foundations
    |
    v
[Validation]
    -> Check for contradictions
    -> Calculate confidence from foundation depth
    |
    v
Grounded Answer + Proof Chain
```

**Neo4j** stores:
- Axiom nodes with metadata
- DEPENDS_ON relationships (type dependencies)
- PAIRS_WITH relationships (function pairings like malloc/free)
- Idiom nodes (usage patterns)

**LanceDB** stores:
- Vector embeddings for semantic search
- Fast similarity queries

### Layered Knowledge Graph

```
Layer 0: K-Framework Semantics (c11_core, cpp_core)
    |
    | DEPENDS_ON
    v
Layer 1: Standard Library (c11_stdlib, cpp_stdlib)
    |
    | DEPENDS_ON
    v
Layer 2: C++20 Language/Library (cpp20_language, cpp20_stdlib)
    |
    | DEPENDS_ON
    v
Layer 3: User Libraries (custom axioms)
```

## Usage Examples

### Validate a Claim

```python
from axiom.reasoning import AxiomValidator

validator = AxiomValidator()
result = validator.validate("Signed integer overflow wraps around in C")

print(result.valid)  # False
print(result.contradiction)  # "Signed integer overflow is undefined behavior"
print(result.proof_chain)  # [axiom1, axiom2, ...]
```

### Search for Axioms

```python
from axiom.vectors import LanceDBLoader

loader = LanceDBLoader()
results = loader.search("null pointer dereference", limit=5)

for axiom in results:
    print(f"{axiom['id']}: {axiom['content']}")
```

### MCP Tool Usage (in Claude Code)

When integrated with Claude Code, you can ask:
- "Is signed integer overflow defined behavior in C?"
- "What happens when I dereference a null pointer?"
- "Search for axioms about memory allocation"

## Extraction

### From K-Framework Semantics

```bash
# Clone K-Framework C semantics
git clone https://github.com/kframework/c-semantics external/c-semantics

# Extract axioms
python scripts/bootstrap.py --layer c11_core --output knowledge/foundations/c11_core.toml
```

### From C++ Draft Spec

```bash
# Extract from a specific section
python scripts/extract_cpp20.py --section basic.life

# Extract all high-signal sections
python scripts/extract_cpp20.py --batch-language
python scripts/extract_cpp20.py --batch-library
```

### Function Pairings

Pairings are loaded from TOML manifests or extracted from K semantics:

```bash
# From K semantics (malloc/free, etc.)
python scripts/load_pairings.py

# From TOML manifest (new/delete, shared_ptr, etc.)
python scripts/load_pairings.py --toml knowledge/pairings/cpp20_stdlib.toml
```

## Project Structure

```
axiom/
├── axiom/
│   ├── extractors/          # Extract axioms from sources
│   │   ├── k_semantics.py   # K-Framework .k files
│   │   ├── k_pairings.py    # Function pairings from K
│   │   └── prompts.py       # LLM prompts for extraction
│   ├── graph/               # Neo4j operations
│   │   └── loader.py        # Load axioms + pairings
│   ├── vectors/             # LanceDB operations
│   │   └── loader.py        # Embeddings + search
│   ├── reasoning/           # Validation logic
│   │   ├── validator.py     # Main validator
│   │   ├── proof_chain.py   # Proof chain generation
│   │   └── entailment.py    # Claim vs axiom classification
│   ├── mcp/                 # MCP server
│   │   └── server.py        # Claude Code integration
│   └── models/              # Data models
│       ├── axiom.py         # Axiom dataclass
│       └── pairing.py       # Pairing/Idiom dataclasses
├── knowledge/
│   ├── foundations/         # Extracted axioms (TOML)
│   └── pairings/            # Function pairings (TOML)
├── scripts/                 # Extraction & ingestion scripts
└── tests/                   # Test suite
```

## Documentation

- [Extraction Order](docs/extraction-order.md) - How to extract and ingest axioms
- [Architecture](ARCHITECTURE.md) - Detailed system design

## Contributing

Contributions welcome! Areas of interest:
- Additional axiom extraction sources
- Improved contradiction detection
- Better proof chain visualization
- IDE integrations beyond Claude Code

## License

BSL-1.0

## Author

Matt Varendorff - https://github.com/mattyv
