# Axiom: Grounded Truth Validation for LLMs

## The Vision

A **grounded knowledge system** that validates LLM outputs against formal axioms, providing proof chains and catching hallucinations.

### The Core Problem
LLMs hallucinate because they lack grounding in formal axioms. When an LLM says "you can use std::string with ILP_FOR_T", there's no mechanism to validate this against foundational C++ type system rules.

### The Solution
A layered knowledge graph that:
1. **Grounds knowledge in formal semantics** (C11, C++17, etc.)
2. **Validates LLM outputs** via proof chain traversal
3. **Provides explainable confidence scores** based on axiom depth
4. **Detects contradictions** between LLM claims and foundational truths

### The Key Insight
**Semantic Search + Graph Traversal = Truth Validation**

```
User Question/LLM Claim
    ↓
[Semantic Search in LanceDB]
    → Find relevant knowledge entries
    ↓
[Graph Traversal in Neo4j]
    → Trace dependencies to foundational axioms
    → Build proof chain
    ↓
[Validation]
    → Check for contradictions
    → Calculate confidence from foundation depth
    ↓
Grounded Answer + Proof Chain
```

## Architecture

### Hybrid Database Approach

**Neo4j (Graph Database)**
- Store axiom relationships (DEPENDS_ON, CONTRADICTS, DERIVES_FROM)
- Enable graph traversal (find proof chains)
- Support complex queries (transitive dependencies, shortest path to axiom)

**LanceDB (Vector Database)**
- Store embeddings for semantic search
- Fast similarity queries
- Initial retrieval layer

**Why Both?**
- LanceDB: "Find similar knowledge" (fast semantic search)
- Neo4j: "Trace to foundational truth" (relationship traversal)
- Together: "Find relevant knowledge AND prove it's grounded"

### Layered Knowledge Graph

```
Layer 0: Core Axioms (C11/C++17 formal semantics)
  ↓ DEPENDS_ON
Layer 1: STL Semantics (standard library guarantees)
  ↓ DEPENDS_ON
Layer 2: Library Knowledge (user library specifics)
  ↓ DERIVES_FROM
Layer 3: Usage Examples
```

Each layer inherits confidence from layers below. Knowledge with longer proof chains to Layer 0 has higher confidence.

## Knowledge Sources

### 1. K Framework C Semantics
- **Source**: [kframework/c-semantics](https://github.com/kframework/c-semantics)
- **What**: Formal executable semantics for C11/C17
- **Coverage**: ~150 undefined behavior axioms
- **Extraction**: Parse `.k` files and `Error_Codes.csv`
- **Confidence**: 1.0 (formally verified)

### 2. C++ Standard (Manual Curation)
- **Source**: ISO C++17/20 standard
- **What**: Core language features, type system rules
- **Coverage**: ~50-100 core axioms (move semantics, type traits, etc.)
- **Extraction**: Manual curation initially
- **Confidence**: 0.95 (language standard)

### 3. cppreference.com
- **Source**: Web scraping
- **What**: STL semantics, complexity guarantees, exception safety
- **Coverage**: ~100-200 STL entries
- **Extraction**: Automated scraping
- **Confidence**: 0.85 (community-curated documentation)

### 4. Library Knowledge
- **Source**: Lucidity questionnaire system
- **What**: Library-specific gotchas, antipatterns, constraints
- **Coverage**: Per-library basis
- **Extraction**: Interactive questionnaire with maintainers
- **Confidence**: 0.7-0.9 (maintainer expertise)

## Use Cases

### Use Case 1: LLM Hallucination Detection

**Input**: LLM claims "std::string can be used with ILP_FOR_T"

**Process**:
1. Semantic search finds "ILP_FOR_T constraints"
2. Graph traversal: ILP_FOR_T → SmallStorage → requires trivially_destructible → C++17 type trait
3. Validation: std::string has non-trivial destructor (violates requirement)

**Output**:
```json
{
  "valid": false,
  "violation": {
    "claim": "std::string works with ILP_FOR_T",
    "contradicts": "SmallStorage requires trivially destructible types",
    "proof_chain": [
      "ILP_FOR_T usage constraint (library, conf: 0.85)",
      "SmallStorage requirements (library, conf: 0.9)",
      "trivially_destructible concept (cpp17_core, conf: 1.0)",
      "std::string destructor (stl, conf: 0.95)"
    ],
    "foundational_axiom": "C++17 [class.dtor]"
  }
}
```

### Use Case 2: Explainable Knowledge

**Input**: "Why can't I use std::vector with ILP_FOR?"

**Output**: Interactive proof chain visualization showing:
- Your question
- → ILP_FOR_T constraints (semantic similarity: 0.92)
- → SmallStorage requirements (DEPENDS_ON)
- → Trivially destructible (DEPENDS_ON)
- → C++17 Type Traits (DEFINED_IN)
- ❌ std::vector has non-trivial destructor
- ✅ Suggested alternatives: std::array, std::span

### Use Case 3: Knowledge Gap Detection

**Query**:
```cypher
// Find library knowledge with no axiom foundation
MATCH (k:Knowledge {layer: 'library'})
WHERE NOT (k)-[:DEPENDS_ON*]->(:Axiom)
RETURN k.id, k.content
```

**Output**: List of "floating claims" that need grounding or validation

## Tech Stack

### Core
- **Python 3.11+**
- **Neo4j 5.x**: Graph database
- **LanceDB**: Vector database
- **sentence-transformers**: Embeddings (all-MiniLM-L6-v2)

### Extractors
- **tree-sitter** (already in lucidity): AST parsing
- **beautifulsoup4**: Web scraping
- **pandas**: CSV/data processing

### API
- **FastAPI**: REST API
- **pydantic**: Data validation
- **neo4j-python-driver**: Graph queries

### Dev Tools
- **pytest**: Testing
- **docker-compose**: Local dev environment
- **ruff**: Linting

## Project Structure

```
axiom/
├── README.md                    # This file
├── ARCHITECTURE.md              # Detailed architecture
├── MVP_PLAN.md                  # Phase-by-phase implementation plan
├── docker-compose.yml           # Neo4j + dev services
├── pyproject.toml              # Python dependencies
│
├── axiom/
│   ├── __init__.py
│   │
│   ├── extractors/             # Extract axioms from sources
│   │   ├── k_semantics.py      # Parse K Framework .k files
│   │   ├── cpp_standard.py     # Manual C++ axiom curation
│   │   └── cppreference.py     # Scrape cppreference.com
│   │
│   ├── graph/                  # Neo4j graph operations
│   │   ├── client.py           # Neo4j connection
│   │   ├── schema.py           # Graph schema & constraints
│   │   ├── queries.py          # Cypher queries
│   │   └── relationships.py    # Relationship types
│   │
│   ├── vectors/                # LanceDB vector operations
│   │   ├── client.py           # LanceDB connection
│   │   ├── embeddings.py       # Generate embeddings
│   │   └── search.py           # Semantic search
│   │
│   ├── reasoning/              # Core validation logic
│   │   ├── proof_chain.py      # Generate proof chains
│   │   ├── validator.py        # Contradiction detection
│   │   ├── confidence.py       # Calculate confidence scores
│   │   └── explainer.py        # Generate explanations
│   │
│   ├── api/                    # FastAPI service
│   │   ├── main.py            # API entry point
│   │   ├── models.py          # Pydantic models
│   │   ├── validate.py        # /validate endpoint
│   │   ├── query.py           # /query endpoint
│   │   └── explain.py         # /explain endpoint
│   │
│   └── models/                # Data models
│       ├── axiom.py           # Axiom model
│       ├── knowledge.py       # Knowledge entry model
│       └── proof.py           # Proof chain model
│
├── knowledge/                  # Extracted knowledge (JSON)
│   ├── foundations/
│   │   ├── c11_axioms.json    # From K semantics
│   │   └── cpp17_axioms.json  # Manual curation
│   ├── stl/
│   │   └── stl_semantics.json # From cppreference
│   └── libraries/
│       └── (imported from Lucidity questionnaire)
│
├── scripts/                    # Utility scripts
│   ├── bootstrap.py           # Initial DB setup
│   ├── extract_all.py         # Run all extractors
│   ├── sync_to_graph.py       # Sync JSON → Neo4j
│   └── sync_to_vectors.py     # Sync JSON → LanceDB
│
└── tests/                     # Tests
    ├── test_extractors/
    ├── test_reasoning/
    └── test_api/
```

## Relationship to Lucidity

**Lucidity** (existing project):
- Interactive questionnaire system
- Extracts knowledge from library maintainers
- Outputs structured knowledge JSON

**Axiom** (this project):
- Consumes knowledge from multiple sources (including Lucidity)
- Builds axiom graph with formal foundations
- Provides validation API

**Integration**:
```
Lucidity Questionnaire
    ↓ (exports JSON)
Axiom Knowledge Importer
    ↓
Neo4j Graph + LanceDB Vectors
    ↓
Validation API
    ↓
Claude Code / Other LLM Tools
```

Lucidity becomes a **knowledge source** for Axiom, specifically for Layer 2 (library-specific knowledge).

## Getting Started

See [MVP_PLAN.md](MVP_PLAN.md) for detailed implementation phases.

### Quick Start (Local Development)

```bash
# 1. Clone and setup
git clone https://github.com/mattyv/axiom.git
cd axiom
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
pip install -e ".[dev]"

# 2. Start Neo4j
docker-compose up -d

# 3. Extract C11 axioms from K semantics
git clone https://github.com/kframework/c-semantics.git /tmp/c-semantics
python scripts/extract_k_axioms.py

# 4. Bootstrap knowledge graph
python scripts/bootstrap.py

# 5. View graph in Neo4j browser
open http://localhost:7474
# Login: neo4j / axiompass

# 6. Run API server
python -m axiom.api.main

# 7. Test validation
curl -X POST http://localhost:8000/validate \
  -H "Content-Type: application/json" \
  -d '{
    "llm_output": "std::string works with ILP_FOR_T",
    "context": "ilp_for"
  }'
```

## Roadmap

### Phase 1: Proof of Concept (2-3 weeks)
- Extract C11 axioms from K semantics
- Set up Neo4j + LanceDB
- Implement basic validation (1 category of hallucinations)
- **Goal**: Prove the core idea works

### Phase 2: Knowledge Base Expansion (1-2 months)
- Extract all ~150 C11 axioms
- Add C++17 core features (~50 axioms)
- Scrape basic STL knowledge (~100 entries)
- Import one library from Lucidity
- **Goal**: Comprehensive knowledge graph

### Phase 3: API Development (1 month)
- Build FastAPI service
- Implement validation endpoint
- Add proof chain generation
- Create explanation endpoint
- **Goal**: Usable API

### Phase 4: LLM Integration (1-2 months)
- Claude Code hook integration
- MCP server implementation
- API client libraries
- **Goal**: Production integration

## Contributing

This is an early-stage research project. We're exploring:
- How to extract formal axioms from various sources
- How to represent knowledge relationships in graphs
- How to validate LLM outputs against axiom chains

## License

MIT

## Contact

mattyv - https://github.com/mattyv
