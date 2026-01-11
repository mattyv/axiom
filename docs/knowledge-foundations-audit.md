# Knowledge Foundations Audit Report

**Date:** 2026-01-11
**Status:** Clean - Data quality issues resolved

## Overview

This document describes the current state of the `knowledge/foundations/` directory after cleanup.

## Directory Structure

```
knowledge/foundations/
├── c11_error_codes.toml   # 248 error codes - C11 undefined behaviors
├── cpp20_language.toml    # 633 axioms - C++20 language features
└── cpp20_stdlib.toml      # 1,134 axioms - C++20 standard library
```

**Total:** 1,767 axioms + 248 error codes

## Data Quality Summary

| Metric | Value |
|--------|-------|
| Total axioms | 1,767 |
| Unique axiom IDs | 1,767 |
| Duplicate IDs | 0 |
| Broken depends_on refs | 0 |
| Error codes | 248 |

All data quality issues from the original extraction have been resolved.

## Changes Made (2026-01-11)

### K-Framework Axioms Dropped

The following files were deleted:
- `c11_core.toml` (892 K axioms)
- `c11_stdlib.toml` (591 K axioms)
- `cpp_core.toml` (825 K axioms)
- `cpp_stdlib.toml` (1 K axiom)

**Reason:** Analysis showed ~70% of K-framework axioms were internal K evaluation guards (e.g., `isLocation`, `isKResult`, `isPromoted`) - useful for K's internal execution but not for code validation. The remaining ~30% with C standard refs were valuable but heavily duplicated.

### Error Codes Preserved

The 248 error codes from K-framework were preserved in `c11_error_codes.toml`. These are high-quality:
- Curated catalog of C11 undefined behaviors
- Direct citations to C11 standard (e.g., `6.5.8:5`, `J.2:1 item 53`)
- Machine-readable structured format

Examples:
| Code | Description | Standard Ref |
|------|-------------|--------------|
| UB-CERL1 | Cannot compare pointers with different base objects using '<' | 6.5.8:5 |
| UB-CER4 | Dereferencing a pointer past the end of an array | 6.5.6:8 |
| UB-CEER1 | Trying to read through a null pointer | 6.3.2.1:1 |
| UB-CCV1 | Signed integer overflow | 6.5:5 |

### C++20 Files Cleaned

Broken `depends_on` references to K axioms were stripped:
- `cpp20_language.toml`: 333 broken refs removed
- `cpp20_stdlib.toml`: 222 broken refs removed

### Scripts Updated

- `scripts/bootstrap.py` - Now extracts error codes only (K axioms no longer extracted)
- `scripts/ingest.py` - Updated DEFAULT_TOML_FILES list
- `docs/extraction-order.md` - Updated to reflect new structure

## File Details

### c11_error_codes.toml

| Metric | Value |
|--------|-------|
| Axioms | 0 |
| Error codes | 248 |
| Source | K-framework c-semantics |

Error code types:
- `UB-*` - Undefined Behavior
- `CV-*` - Constraint Violation
- `USP-*` - Unspecified Behavior
- `IMPL-*` - Implementation Defined
- `SE-*` - Syntax Error
- `L-*` - Language Extension

### cpp20_language.toml

| Metric | Value |
|--------|-------|
| Axioms | 633 |
| Unique IDs | 633 |
| Duplicate IDs | 0 |
| Broken refs | 0 |
| Source | eel.is/c++draft |

Covers: basic.life, expr.*, class.*, dcl.*, temp.*, except.*, and more.

### cpp20_stdlib.toml

| Metric | Value |
|--------|-------|
| Axioms | 1,134 |
| Unique IDs | 1,134 |
| Duplicate IDs | 0 |
| Broken refs | 0 |
| Source | eel.is/c++draft |

Covers: optional, variant, expected, any, string_view, span, ranges, and more.

## Verification

```bash
# Verify structure
ls -la knowledge/foundations/

# Count error codes
grep -c '^\[\[error_codes\]\]' knowledge/foundations/c11_error_codes.toml
# Expected: 248

# Verify no duplicates
python3 -c "
import tomllib
from pathlib import Path
ids = []
for f in Path('knowledge/foundations').glob('*.toml'):
    with open(f, 'rb') as fp:
        data = tomllib.load(fp)
    ids.extend(a['id'] for a in data.get('axioms', []))
print(f'Total axioms: {len(ids)}')
print(f'Unique IDs: {len(set(ids))}')
print(f'Duplicates: {len(ids) - len(set(ids))}')
"
# Expected: 1767 total, 1767 unique, 0 duplicates
```
