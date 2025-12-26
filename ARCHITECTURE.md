# Axiom Architecture

## System Overview

Axiom is a **grounded truth validation system** that uses a hybrid database approach (Neo4j + LanceDB) to validate LLM outputs against formal axioms through proof chain traversal.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                         │
│  ┌────────────┬────────────┬─────────────┬─────────────┐   │
│  │ FastAPI    │ Claude Code│ MCP Server  │ Python      │   │
│  │ REST API   │ Hook       │             │ Client      │   │
│  └────────────┴────────────┴─────────────┴─────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   Reasoning Engine                           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Hybrid Query Orchestrator                          │   │
│  │  - Semantic search (LanceDB)                        │   │
│  │  - Graph traversal (Neo4j)                          │   │
│  │  - Proof chain generation                           │   │
│  │  - Contradiction detection                          │   │
│  │  - Confidence scoring                               │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────┬──────────────────────────────────────┐
│   Neo4j Graph DB     │       LanceDB Vector DB              │
│                      │                                      │
│  Nodes:              │  Tables:                             │
│  - :Axiom            │  - axioms                            │
│  - :Knowledge        │  - knowledge                         │
│                      │  - stl_entries                       │
│  Relationships:      │                                      │
│  - :DEPENDS_ON       │  Columns:                            │
│  - :CONTRADICTS      │  - id, content, vector               │
│  - :DERIVES_FROM     │  - layer, confidence                 │
│  - :DEFINED_IN       │  - metadata                          │
└──────────────────────┴──────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   Knowledge Sources                          │
│  ┌────────────┬────────────┬─────────────┬─────────────┐   │
│  │ K Semantics│ C++ Std    │cppreference │ Lucidity    │   │
│  │ Extractor  │ Parser     │ Scraper     │ Import      │   │
│  └────────────┴────────────┴─────────────┴─────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Knowledge Sources Layer

#### K Semantics Extractor
**Purpose**: Extract C11/C17 axioms from K Framework formal semantics

**Input**: K Framework c-semantics repository
- `.k` files (semantic rules)
- `Error_Codes.csv` (UB definitions)
- Example programs

**Output**: JSON axioms
```json
{
  "id": "c11_UB-CCV1",
  "content": "Signed integer overflow",
  "layer": "c11_core",
  "type": "undefined_behavior",
  "c_standard_refs": ["6.5:5", "J.2:1 item 36"],
  "formal_spec": "rule I1 +Int I2 => UNDEF(...) when overflow(I1, I2)",
  "examples": [
    {"code": "int x = INT_MAX; x++;", "triggers": true}
  ],
  "confidence": 1.0,
  "source": "k-framework/c-semantics"
}
```

**Implementation**: `axiom/extractors/k_semantics.py`

#### C++ Standard Parser
**Purpose**: Extract C++17/20 core language axioms

**Input**:
- Manual curation from C++ standard
- Community knowledge bases

**Output**: C++ axioms
```json
{
  "id": "cpp17_trivially_destructible",
  "content": "Trivially destructible types have trivial destructor",
  "layer": "cpp17_core",
  "type": "type_trait",
  "cpp_standard_refs": ["[class.dtor]", "[meta.unary.prop]"],
  "examples": [
    {"type": "int", "is_trivially_destructible": true},
    {"type": "std::string", "is_trivially_destructible": false}
  ],
  "confidence": 0.95,
  "source": "ISO C++17 standard"
}
```

**Implementation**: `axiom/extractors/cpp_standard.py`

#### cppreference Scraper
**Purpose**: Extract STL semantics (complexity, exception safety, etc.)

**Input**: cppreference.com web pages

**Output**: STL knowledge
```json
{
  "id": "stl_vector_push_back",
  "content": "std::vector::push_back has amortized O(1) complexity",
  "layer": "stl",
  "type": "complexity_guarantee",
  "complexity": "O(1) amortized",
  "exception_safety": "strong",
  "iterator_invalidation": "all if reallocation",
  "depends_on": ["cpp17_move_semantics"],
  "confidence": 0.85,
  "source": "cppreference.com/vector/push_back"
}
```

**Implementation**: `axiom/extractors/cppreference.py`

#### Lucidity Import
**Purpose**: Import library-specific knowledge from Lucidity questionnaire

**Input**: Lucidity questionnaire output (JSON)

**Output**: Library knowledge with axiom links
```json
{
  "id": "ilp_for_smallstorage_constraint",
  "content": "ILP_FOR_T SmallStorage requires trivially destructible types",
  "layer": "library",
  "library": "ilp_for",
  "depends_on": [
    "cpp17_trivially_destructible",
    "cpp17_placement_new"
  ],
  "rationale": "SmallStorage uses placement new without explicit destructor calls",
  "confidence": 0.85,
  "source": "ilp_for maintainer questionnaire"
}
```

**Implementation**: `scripts/import_from_lucidity.py`

---

### 2. Database Layer

#### Neo4j Graph Database

**Schema**:
```cypher
// Node Labels
:Axiom        // Foundational truths (C11, C++17, etc.)
:Knowledge    // Library-specific knowledge
:Example      // Code examples

// Node Properties
{
  id: String (unique),
  content: String,
  layer: String,        // c11_core, cpp17_core, stl, library
  confidence: Float,
  source: String,
  created_at: DateTime
}

// Relationship Types
(:Knowledge)-[:DEPENDS_ON]->(:Axiom)
  - Represents: "This knowledge requires this axiom"
  - Properties: {reason: String, required: Boolean}

(:Knowledge)-[:CONTRADICTS]->(:Knowledge)
  - Represents: "These two claims are incompatible"
  - Properties: {explanation: String}

(:Knowledge)-[:DERIVES_FROM]->(:Axiom)
  - Represents: "This is logically inferred from axiom"
  - Properties: {inference_rule: String}

(:Example)-[:DEMONSTRATES]->(:Knowledge)
  - Represents: "This code exemplifies this knowledge"
  - Properties: {works: Boolean, explanation: String}
```

**Key Queries**:

1. **Get Proof Chain**:
```cypher
MATCH path = (k:Knowledge {id: $id})-[:DEPENDS_ON*]->(a:Axiom)
WHERE a.layer IN ['c11_core', 'cpp17_core']
RETURN path
ORDER BY length(path) DESC
LIMIT 1
```

2. **Find Contradictions**:
```cypher
MATCH (k:Knowledge {id: $id})-[:DEPENDS_ON*]->(axiom:Axiom)
WITH collect(axiom) as axioms
MATCH (other:Knowledge)-[:CONTRADICTS]->(axiom)
WHERE axiom IN axioms
RETURN other
```

3. **Find Unsupported Claims**:
```cypher
MATCH (k:Knowledge {layer: 'library'})
WHERE NOT (k)-[:DEPENDS_ON*]->(:Axiom)
RETURN k.id, k.content
```

**Implementation**: `axiom/graph/`

#### LanceDB Vector Database

**Tables**:

1. **axioms** table:
```python
{
  "id": str,
  "content": str,
  "vector": list[float],  # 384-dim embedding (all-MiniLM-L6-v2)
  "layer": str,
  "confidence": float,
  "metadata": dict
}
```

2. **knowledge** table (same schema)

**Search Strategy**:
- Hybrid search: Vector similarity + FTS (full-text search)
- Index: IVF-PQ for large-scale
- Top-K retrieval, then filtered by layer/confidence

**Implementation**: `axiom/vectors/`

---

### 3. Reasoning Engine

#### Hybrid Query Orchestrator

**Flow**:
```
User Query
    ↓
1. Semantic Search (LanceDB)
    → Get top-K relevant entries
    ↓
2. Graph Traversal (Neo4j)
    → For each entry, get proof chain
    → Collect all axioms in chains
    ↓
3. Contradiction Detection
    → Check if claim contradicts any axiom
    → Build violation report
    ↓
4. Confidence Scoring
    → Calculate based on proof depth
    → Factor in axiom confidence
    ↓
5. Explanation Generation
    → Format proof chain
    → Generate human-readable explanation
    ↓
Return Result
```

**Implementation**: `axiom/reasoning/query.py`

#### Proof Chain Generator

**Algorithm**:
```python
def get_proof_chain(knowledge_id: str) -> list[Node]:
    """
    BFS traversal from knowledge to deepest axiom.

    Returns path with highest confidence score.
    """
    # 1. Query Neo4j for all paths
    paths = neo4j.run("""
        MATCH path = (k:Knowledge {id: $id})-[:DEPENDS_ON*]->(a:Axiom)
        WHERE a.layer IN ['c11_core', 'cpp17_core']
        RETURN path
    """, id=knowledge_id)

    # 2. Score each path
    scored_paths = [
        (path, score_path(path))
        for path in paths
    ]

    # 3. Return highest-scored path
    return max(scored_paths, key=lambda x: x[1])[0]

def score_path(path: list[Node]) -> float:
    """
    Score path quality:
    - Prefer shorter paths (more direct)
    - Prefer higher confidence nodes
    - Prefer foundational axioms (c11_core > cpp17_core > stl)
    """
    length_penalty = 1.0 / len(path)
    confidence_score = sum(node.confidence for node in path) / len(path)
    layer_score = layer_priority(path[-1].layer)

    return length_penalty * 0.3 + confidence_score * 0.4 + layer_score * 0.3
```

**Implementation**: `axiom/reasoning/proof_chain.py`

#### Contradiction Detector

**Algorithm**:
```python
def detect_contradiction(claim: str, context: str) -> dict:
    """
    Check if claim contradicts any axiom.

    Steps:
    1. Parse claim into assertions
    2. Semantic search for relevant knowledge
    3. Get proof chains for each result
    4. Check each axiom in chains for contradiction
    """
    # 1. Extract assertions from claim
    assertions = extract_assertions(claim)

    # 2. Find relevant knowledge
    candidates = lancedb.search(claim, top_k=10)

    # 3. For each candidate, get proof chain
    contradictions = []
    for candidate in candidates:
        chain = get_proof_chain(candidate.id)

        # 4. Check each axiom
        for axiom in chain:
            for assertion in assertions:
                if contradicts(assertion, axiom):
                    contradictions.append({
                        "claim": assertion,
                        "violates": axiom.content,
                        "axiom_id": axiom.id,
                        "proof_chain": chain
                    })

    return {
        "valid": len(contradictions) == 0,
        "contradictions": contradictions
    }

def contradicts(assertion: str, axiom: dict) -> bool:
    """
    Determine if assertion contradicts axiom.

    Strategies:
    1. Explicit CONTRADICTS relationship in graph
    2. Keyword matching (e.g., "non-trivial" vs "trivially")
    3. LLM-based semantic contradiction (future)
    """
    # Simple keyword-based for MVP
    if "non-trivial" in assertion and "trivially" in axiom.content:
        return True

    # Graph-based
    result = neo4j.run("""
        MATCH (:Knowledge {content: $assertion})-[:CONTRADICTS]->(:Axiom {id: $axiom_id})
        RETURN count(*) > 0 as contradicts
    """, assertion=assertion, axiom_id=axiom.id)

    return result[0]["contradicts"]
```

**Implementation**: `axiom/reasoning/validator.py`

#### Confidence Scorer

**Formula**:
```python
def calculate_confidence(proof_chain: list[Node]) -> float:
    """
    Calculate confidence score for knowledge entry.

    Factors:
    1. Depth to foundation (shorter = better)
    2. Axiom confidence (layer-based)
    3. Relationship strength
    """
    if not proof_chain:
        return 0.3  # No foundation

    # Get deepest axiom
    deepest = proof_chain[-1]

    # Layer-based confidence
    layer_scores = {
        "c11_core": 1.0,
        "cpp17_core": 0.95,
        "cpp20_core": 0.9,
        "stl": 0.85,
        "library": 0.7
    }
    layer_conf = layer_scores.get(deepest.layer, 0.5)

    # Depth penalty (prefer shorter chains)
    depth_penalty = 1.0 / (1 + len(proof_chain) * 0.1)

    # Average node confidence
    avg_conf = sum(node.confidence for node in proof_chain) / len(proof_chain)

    return layer_conf * 0.5 + depth_penalty * 0.2 + avg_conf * 0.3
```

**Implementation**: `axiom/reasoning/confidence.py`

---

### 4. Application Layer

#### FastAPI REST Service

**Endpoints**:

```python
POST /validate
  Input: {llm_output: str, context: str}
  Output: {valid: bool, contradictions: [...], proof_chains: [...]}

POST /query
  Input: {question: str, top_k: int, include_proofs: bool}
  Output: {results: [...]}

GET /explain/{knowledge_id}
  Output: {content: str, proof_chain: [...], confidence: float}

GET /proof-chain/{knowledge_id}
  Output: {chain: [...], graph: {...}}

GET /stats
  Output: {axiom_count: int, knowledge_count: int, layers: {...}}
```

**Implementation**: `axiom/api/`

#### Claude Code Hook

**Hook Flow**:
```python
# hooks/axiom_validate.py

def user_prompt_submit_hook(prompt: str) -> dict:
    """Called before sending to Claude."""
    # Detect library context from codebase
    context = detect_library_context()

    # Search for relevant knowledge
    knowledge = axiom_client.query(prompt, context=context)

    # Inject as context
    if knowledge:
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": format_knowledge_context(knowledge)
            }
        }

def llm_response_hook(response: str) -> dict:
    """Called after Claude responds, before showing to user."""
    # Validate response
    validation = axiom_client.validate(response)

    # Warn if hallucination detected
    if not validation.valid:
        return {
            "hookSpecificOutput": {
                "hookEventName": "AfterLLMResponse",
                "warning": "⚠️ Potential hallucination detected",
                "contradictions": validation.contradictions
            }
        }
```

**Implementation**: `integrations/claude_code/`

#### MCP Server

**Tools**:
```json
{
  "tools": [
    {
      "name": "axiom_validate",
      "description": "Validate a technical claim against formal axioms",
      "inputSchema": {
        "type": "object",
        "properties": {
          "claim": {"type": "string"},
          "context": {"type": "string"}
        }
      }
    },
    {
      "name": "axiom_search",
      "description": "Search knowledge base with proof chains",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "include_proofs": {"type": "boolean"}
        }
      }
    }
  ]
}
```

**Implementation**: `mcp/axiom_server.py`

---

## Data Flow Examples

### Example 1: LLM Validation

**Input**: "std::string can be used with ILP_FOR_T"

**Flow**:
```
1. API receives validation request
    ↓
2. LanceDB search for "ILP_FOR_T" + "std::string"
    → Returns: "ILP_FOR_T SmallStorage constraint"
    ↓
3. Neo4j get proof chain
    → ilp_for_smallstorage (library)
    → cpp17_trivially_destructible (core)
    ↓
4. Check std::string properties
    → LanceDB: "std::string has non-trivial destructor"
    ↓
5. Detect contradiction
    → Claim: "std::string works"
    → Axiom: "requires trivially destructible"
    → std::string: "non-trivial destructor"
    → CONTRADICTION!
    ↓
6. Return validation result
```

**Output**:
```json
{
  "valid": false,
  "contradictions": [{
    "claim": "std::string can be used with ILP_FOR_T",
    "violates": "SmallStorage requires trivially destructible types",
    "proof_chain": [
      {"id": "ilp_for_smallstorage", "layer": "library"},
      {"id": "cpp17_trivially_destructible", "layer": "cpp17_core"}
    ],
    "evidence": "std::string has non-trivial destructor (C++17 [string.cons])"
  }]
}
```

---

## Technology Choices

### Why Neo4j?
- Native graph traversal (optimized for relationship queries)
- Cypher query language (expressive for proof chains)
- ACID transactions
- Mature ecosystem

**Alternatives considered**:
- NetworkX (in-memory, not persistent)
- SQLite with recursive CTEs (slower for deep traversals)
- Custom graph implementation (reinventing wheel)

### Why LanceDB?
- Embedded (no separate server)
- Fast vector search
- Columnar format (efficient storage)
- Native Python support

**Alternatives considered**:
- Pinecone (cloud-only, cost)
- Weaviate (heavier, more complex)
- ChromaDB (good alternative, less mature)

### Why sentence-transformers?
- Fast local inference
- Good semantic quality for code/text
- 384-dim (smaller than OpenAI embeddings)
- Open source

**Alternatives considered**:
- OpenAI embeddings (API cost, latency)
- CodeBERT (specialized for code, but overkill)
- Custom fine-tuned model (future work)

---

## Scalability Considerations

### Current Design (MVP)
- **Neo4j**: Single instance, <10k nodes
- **LanceDB**: Embedded, <100MB data
- **API**: Single process, sync

**Expected Performance**:
- Query latency: <100ms (p95)
- Validation latency: <200ms (p95)
- Throughput: ~50 req/s

### Future Scaling (Production)
- **Neo4j**: Clustering, read replicas
- **LanceDB**: Distributed index, sharding
- **API**: Multiple workers, async
- **Caching**: Redis for frequent queries

**Target Performance**:
- Query latency: <50ms (p95)
- Validation latency: <100ms (p95)
- Throughput: ~500 req/s

---

## Security & Privacy

### Data Privacy
- All data stored locally (no cloud services)
- No telemetry by default
- User's knowledge never leaves their system

### API Security
- API key authentication (production)
- Rate limiting
- Input validation
- No arbitrary code execution

---

## Monitoring & Observability

### Metrics to Track
- Query latency (by endpoint)
- Validation accuracy
- False positive/negative rates
- Database sizes
- Cache hit rates

### Logging
- Structured JSON logs
- Request/response logging (optional)
- Error tracking
- Audit trail for knowledge updates

---

## Future Enhancements

### Short-term (6 months)
- Web UI for graph visualization
- Automatic relationship inference (LLM-based)
- More sophisticated contradiction detection
- Performance optimizations

### Long-term (1 year+)
- Support for more languages (Rust, Go, etc.)
- Distributed knowledge graph
- Community knowledge contributions
- Integration with code analysis tools (clang-tidy, etc.)
