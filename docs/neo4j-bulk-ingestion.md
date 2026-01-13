# Neo4j Bulk Ingestion Optimization

## Current Problem

The Neo4j loader (`axiom/graph/loader.py`) processes axioms one at a time, resulting in ~12,000+ individual database transactions for a full ingestion. This takes several minutes when it could take seconds.

## Current Implementation Issues

### 1. Individual Transactions Per Axiom (lines 53-54)
```python
for axiom in collection.axioms:
    session.execute_write(self._create_axiom, axiom)
```
Each axiom creates a separate write transaction with commit overhead.

### 2. Multiple Queries Per Axiom (lines 108, 128, 139)
```python
tx.run(query, ...)           # Main axiom creation
tx.run(...)                  # violated_by_codes update
tx.run(...)                  # DEPENDS_ON relationships
```
Three separate `tx.run()` calls per axiom instead of one combined query.

### 3. No Batching
Processing 4,000+ axioms sequentially with no `UNWIND` bulk operations.

## Performance Impact

Current ingestion: ~3-5 minutes for 4,000 axioms
Expected after optimization: ~5-10 seconds

## Optimized Implementation

### Bulk Create with UNWIND

```python
def load_collection(self, collection: AxiomCollection) -> None:
    """Load a complete axiom collection using bulk operations."""
    with self.driver.session() as session:
        # Prepare all axiom data as dicts
        axiom_data = [self._axiom_to_dict(a) for a in collection.axioms]

        # Bulk create all axioms in one transaction
        session.execute_write(self._bulk_create_axioms, axiom_data)

        # Bulk create error codes
        error_data = [self._error_to_dict(e) for e in collection.error_codes]
        session.execute_write(self._bulk_create_errors, error_data)

        # Create relationships in bulk
        session.execute_write(self._create_all_relationships, collection)

def _axiom_to_dict(self, axiom: Axiom) -> dict:
    """Convert axiom to dict for bulk insert."""
    return {
        "id": axiom.id,
        "content": axiom.content,
        "formal_spec": axiom.formal_spec,
        "layer": axiom.layer,
        "confidence": axiom.confidence,
        "source_file": axiom.source.file,
        "module_name": axiom.source.module,
        "tags": axiom.tags,
        "c_refs": axiom.c_standard_refs,
        "function": axiom.function,
        "header": axiom.header,
        "axiom_type": axiom.axiom_type.value if axiom.axiom_type else None,
        "on_violation": axiom.on_violation,
        "depends_on": axiom.depends_on,
        "violated_by_codes": [v.code for v in axiom.violated_by],
    }

@staticmethod
def _bulk_create_axioms(tx, axioms: list[dict]) -> None:
    """Bulk create axiom nodes and module relationships."""
    tx.run("""
        UNWIND $axioms AS axiom
        MERGE (a:Axiom {id: axiom.id})
        SET a.content = axiom.content,
            a.formal_spec = axiom.formal_spec,
            a.layer = axiom.layer,
            a.confidence = axiom.confidence,
            a.source_file = axiom.source_file,
            a.module_name = axiom.module_name,
            a.tags = axiom.tags,
            a.c_standard_refs = axiom.c_refs,
            a.function = axiom.function,
            a.header = axiom.header,
            a.axiom_type = axiom.axiom_type,
            a.on_violation = axiom.on_violation,
            a.depends_on = axiom.depends_on,
            a.violated_by_codes = axiom.violated_by_codes

        MERGE (m:KModule {name: axiom.module_name})
        SET m.file_path = axiom.source_file

        MERGE (a)-[:DEFINED_IN]->(m)
    """, axioms=axioms)

@staticmethod
def _bulk_create_errors(tx, errors: list[dict]) -> None:
    """Bulk create error code nodes."""
    tx.run("""
        UNWIND $errors AS error
        MERGE (e:ErrorCode {code: error.code})
        SET e.internal_code = error.internal_code,
            e.type = error.type,
            e.description = error.description,
            e.c_standard_refs = error.c_refs,
            e.validates_axioms = error.validates_axioms
    """, errors=errors)

@staticmethod
def _create_all_relationships(tx, collection: AxiomCollection) -> None:
    """Create all relationships in bulk."""
    # VIOLATED_BY relationships
    tx.run("""
        MATCH (a:Axiom)
        WHERE a.violated_by_codes IS NOT NULL AND size(a.violated_by_codes) > 0
        UNWIND a.violated_by_codes AS code
        MATCH (e:ErrorCode {code: code})
        MERGE (a)-[:VIOLATED_BY]->(e)
    """)

    # DEPENDS_ON relationships
    tx.run("""
        MATCH (a:Axiom)
        WHERE a.depends_on IS NOT NULL AND size(a.depends_on) > 0
        UNWIND a.depends_on AS dep_id
        MATCH (foundation:Axiom {id: dep_id})
        MERGE (a)-[:DEPENDS_ON]->(foundation)
    """)
```

## Additional Optimizations

### 1. Create Indexes First
```python
def apply_schema(driver: Driver) -> None:
    """Apply schema constraints and indexes."""
    with driver.session() as session:
        # Unique constraints (also create indexes)
        session.run("CREATE CONSTRAINT axiom_id IF NOT EXISTS FOR (a:Axiom) REQUIRE a.id IS UNIQUE")
        session.run("CREATE CONSTRAINT error_code IF NOT EXISTS FOR (e:ErrorCode) REQUIRE e.code IS UNIQUE")
        session.run("CREATE CONSTRAINT module_name IF NOT EXISTS FOR (m:KModule) REQUIRE m.name IS UNIQUE")

        # Additional indexes for common lookups
        session.run("CREATE INDEX axiom_layer IF NOT EXISTS FOR (a:Axiom) ON (a.layer)")
        session.run("CREATE INDEX axiom_function IF NOT EXISTS FOR (a:Axiom) ON (a.function)")
        session.run("CREATE INDEX axiom_header IF NOT EXISTS FOR (a:Axiom) ON (a.header)")
```

### 2. Batch Size for Very Large Imports
For imports >10,000 axioms, split into batches:

```python
BATCH_SIZE = 1000

def load_collection_batched(self, collection: AxiomCollection) -> None:
    axiom_data = [self._axiom_to_dict(a) for a in collection.axioms]

    with self.driver.session() as session:
        for i in range(0, len(axiom_data), BATCH_SIZE):
            batch = axiom_data[i:i + BATCH_SIZE]
            session.execute_write(self._bulk_create_axioms, batch)
            print(f"Loaded {min(i + BATCH_SIZE, len(axiom_data))}/{len(axiom_data)} axioms")
```

### 3. Use APOC for Parallel Processing (if available)
```cypher
CALL apoc.periodic.iterate(
    "UNWIND $axioms AS axiom RETURN axiom",
    "MERGE (a:Axiom {id: axiom.id}) SET a += axiom",
    {batchSize: 500, parallel: true, params: {axioms: $axioms}}
)
```

## Expected Results

| Metric | Before | After |
|--------|--------|-------|
| Transactions | ~12,000 | ~3 |
| Time (4k axioms) | 3-5 min | 5-10 sec |
| Time (first install) | 5+ min | ~30 sec |

## Implementation Notes

1. Keep backward compatibility - don't remove single-axiom methods
2. Add progress logging for batch operations
3. Handle partial failures gracefully (some axioms might already exist)
4. Test with both fresh database and incremental updates
