# Terminology Standardization Plan

## Definitions

| Term | Definition | Artifact |
|------|------------|----------|
| **Extraction** | Creating TOML files from source code | `*.toml` files |
| **Ingestion** | Loading TOML files into databases | Neo4j/LanceDB records |
| **Linking** | Creating `depends_on` relationships (library → foundation) | `depends_on` field population |

## Changes Required

### Phase 1: Script Renames

| Current | New | Rationale |
|---------|-----|-----------|
| `scripts/ingest_library.py` | `scripts/extract_library.py` | Does extraction, not ingestion |
| `scripts/ingest_stdlib.py` | `scripts/extract_stdlib.py` | Does extraction, not ingestion |

### Phase 2: Class/Method Renames (keep package structure)

| Current | New | Location |
|---------|-----|----------|
| `KBIntegrator.integrate_axioms()` | `KBIntegrator.ingest_axioms()` | `axiom/ingestion/kb_integrator.py` |
| `KBIntegrator.integrate_from_toml()` | `KBIntegrator.ingest_from_toml()` | `axiom/ingestion/kb_integrator.py` |
| `KBIntegrator.integrate_from_session()` | `KBIntegrator.ingest_from_session()` | `axiom/ingestion/kb_integrator.py` |
| `IntegrationResult` | `IngestionResult` | `axiom/ingestion/kb_integrator.py` |

### Phase 3: Error Linker Rename

| Current | New | Purpose |
|---------|-----|---------|
| `axiom/extractors/linker.py` | `axiom/extractors/error_linker.py` | Links axioms to error codes |
| `AxiomLinker` | `ErrorCodeLinker` | Class name |

Foundation linking keeps current names:
- `axiom/extractors/semantic_linker.py` ✓
- `axiom/extractors/library_depends_on.py` ✓

### Phase 4: Test Updates

| File | Changes |
|------|---------|
| `tests/test_extractors/test_linker.py` | Rename → `test_error_linker.py`, update class refs |
| `tests/test_ingestion/test_kb_integrator.py` | Rename `test_integrate_*` → `test_ingest_*` |

### Phase 5: Docstring Updates

Update all docstrings to use consistent terminology:
- "extract" for source → TOML
- "ingest" for TOML → database
- "link" for library → foundation depends_on

---

## Files to Modify (in order)

### 1. Scripts (git mv + docstring)
- `scripts/ingest_library.py` → `scripts/extract_library.py`
- `scripts/ingest_stdlib.py` → `scripts/extract_stdlib.py`

### 2. Error Linker (git mv + class rename)
- `axiom/extractors/linker.py` → `axiom/extractors/error_linker.py`
- `axiom/extractors/__init__.py` - update import

### 3. KB Integrator (method renames)
- `axiom/ingestion/kb_integrator.py` - rename integrate→ingest methods

### 4. Package docstrings
- `axiom/ingestion/__init__.py` - clarify terminology

### 5. Tests
- `tests/test_extractors/test_linker.py` → `tests/test_extractors/test_error_linker.py`
- `tests/test_ingestion/test_kb_integrator.py` - rename test methods

### 6. Documentation
- `README.md` - update script references
- `QUICKSTART.md` - update script references
- `ARCHITECTURE.md` - update terminology
