# Axiom Quick Start

Get Axiom running locally in under 10 minutes.

## Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Git
- K Framework (for pyk integration - optional for basic extraction)

## Step 1: Clone and Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/axiom.git
cd axiom

# Initialize submodules (includes c-semantics)
git submodule update --init --recursive

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install in development mode
pip install -e ".[dev]"
```

## Step 2: Install K Framework (Optional)

For full pyk integration, install the K Framework:

```bash
# Using kup (recommended)
bash <(curl https://kframework.org/install)
kup install k

# Or using Ubuntu .deb package
# Download from https://github.com/kframework/k/releases
sudo apt install ./kframework_*.deb

# Verify installation
kompile --version
```

## Step 3: Start Neo4j

```bash
# Start Neo4j in Docker
docker-compose up -d

# Wait for Neo4j to be ready (~10 seconds)
docker-compose logs -f neo4j

# When you see "Started", Neo4j is ready
# Press Ctrl+C to stop following logs
```

**Verify**: Open http://localhost:7474 in your browser
- Username: `neo4j`
- Password: `axiompass`

## Step 4: Extract C11 Axioms

```bash
# Run the bootstrap script
python scripts/bootstrap.py

# Should output:
# Step 1: Extracting axioms from K semantics...
#   - Found 1000+ axioms
# Step 2: Parsing error codes CSV...
#   - Parsed 248 error codes
# Step 3: Linking axioms to error codes...
#   - Linked 200+ axioms to error codes
# ...
```

For extraction only (skip Neo4j/LanceDB):
```bash
python scripts/bootstrap.py --skip-graph --skip-vectors
```


## Step 5: Explore the Graph

Open Neo4j Browser: http://localhost:7474

Try these Cypher queries:

```cypher
// View all axioms
MATCH (a:Axiom)
RETURN a
LIMIT 25

// Count axioms by layer
MATCH (a:Axiom)
RETURN a.layer, count(*) as count
ORDER BY count DESC

// Find undefined behavior axioms
MATCH (a:Axiom {type: 'undefined_behavior'})
RETURN a.id, a.content
LIMIT 10

// Find axioms about integer overflow
MATCH (a:Axiom)
WHERE a.content CONTAINS 'overflow'
RETURN a.id, a.content
```

## Step 6: Test the System

```bash
# Run tests
pytest tests/ -v

# Should show:
# ✅ test_extract_axioms
# ✅ test_load_neo4j
# ✅ test_semantic_search
# ✅ test_proof_chain
```

## Step 7: Try the API (Phase 3 - Coming Soon)

```bash
# Start API server
python -m axiom.api.main

# In another terminal:
curl -X POST http://localhost:8000/validate \
  -H "Content-Type: application/json" \
  -d '{
    "llm_output": "Signed integer overflow is defined behavior",
    "context": "c11"
  }'

# Response:
# {
#   "valid": false,
#   "contradictions": [{
#     "claim": "Signed integer overflow is defined behavior",
#     "violates": "Signed integer overflow is undefined behavior",
#     "axiom_id": "c11_UB-CCV1",
#     "proof_chain": [...]
#   }]
# }
```

## Common Issues

### Neo4j won't start
```bash
# Check if port 7474 or 7687 is in use
lsof -i :7474
lsof -i :7687

# Stop and remove containers
docker-compose down

# Start fresh
docker-compose up -d
```

### Can't connect to Neo4j
```bash
# Check Neo4j logs
docker-compose logs neo4j

# Verify it's running
docker-compose ps
```

### Missing dependencies
```bash
# Reinstall
pip install -e ".[dev]"

# Or install specific missing package
pip install neo4j lancedb sentence-transformers
```

## Next Steps

1. **Explore the code**:
   - `axiom/extractors/` - Knowledge extraction
   - `axiom/graph/` - Neo4j operations
   - `axiom/vectors/` - LanceDB operations
   - `axiom/reasoning/` - Validation logic

2. **Add more knowledge**:
   - Extract C++17 axioms (see `MVP_PLAN.md` Phase 2)
   - Scrape cppreference.com
   - Import library knowledge from Lucidity

3. **Build the API** (see `MVP_PLAN.md` Phase 3):
   - FastAPI service
   - Validation endpoint
   - Query endpoint

4. **Integrate with tools** (see `MVP_PLAN.md` Phase 4):
   - Claude Code hook
   - MCP server
   - VS Code extension

## Useful Commands

```bash
# Start Neo4j
docker-compose up -d

# Stop Neo4j
docker-compose down

# View Neo4j logs
docker-compose logs -f neo4j

# Clean everything (WARNING: deletes data)
docker-compose down -v
rm -rf knowledge/

# Rebuild from scratch
python scripts/extract_k_axioms.py
python scripts/bootstrap.py

# Run specific test
pytest tests/test_extractors.py::test_k_semantics -v

# Format code
ruff format .

# Lint code
ruff check .

# Type check
mypy axiom/
```

## Development Workflow

1. **Make changes** to code
2. **Run tests**: `pytest`
3. **Check types**: `mypy axiom/`
4. **Format**: `ruff format .`
5. **Commit**: `git add . && git commit -m "..."`

## Getting Help

- **Documentation**: See `README.md`, `ARCHITECTURE.md`, `MVP_PLAN.md`
- **Issues**: https://github.com/mattyv/axiom/issues
- **Discussions**: https://github.com/mattyv/axiom/discussions

## What's Next?

See `MVP_PLAN.md` for the full roadmap. Current phase:

**Phase 1: Proof of Concept** (2-3 weeks)
- [x] Extract C11 axioms ← You are here!
- [ ] Implement proof chains
- [ ] Build contradiction detector
- [ ] Validate one hallucination category
