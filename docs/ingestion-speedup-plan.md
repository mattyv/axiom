# Plan: Speed Up Library Ingestion Pipeline

## Problem Statement

The library ingestion pipeline (`scripts/ingest_library.py`) is slow. The bottleneck is **LLM extraction** which takes 2-10 seconds per function/macro, and everything runs sequentially.

**Constraint:** Must NOT compromise extraction quality.

## Current Architecture

```
File Discovery → Parsing (tree-sitter) → LLM Extraction → Review → KB Integration
     ~1s              ~100ms/file         2-10s/function    human      ~50ms/axiom
```

**Critical finding:** LLM extraction is 95%+ of execution time.

## Key Bottlenecks

1. **Sequential LLM calls** - Each function = 1 Claude CLI subprocess (2-10s each)
2. **No parallelism** - Files and functions processed one at a time
3. **Subprocess overhead** - ~100-200ms per `claude` CLI spawn

## Optimization Strategy (Prioritized)

### Phase 1: Quick Wins (No Quality Risk)

#### 1.1 Add Direct Anthropic API Backend
- Add `--backend api|cli` flag (default: `api` if ANTHROPIC_API_KEY set, else `cli`)
- API mode: `anthropic.Anthropic().messages.create()` - faster, enables async
- CLI mode: Keep existing `subprocess.run(["claude", ...])` as fallback
- **Speedup:** 15-30% per LLM call (API mode)
- **File:** `axiom/ingestion/extractor.py`
- **Dependency:** Add `anthropic>=0.40.0` to pyproject.toml (optional)

#### 1.2 Parallel File Parsing
- Use `ProcessPoolExecutor` for tree-sitter parsing
- CPU-bound, files are independent
- **Speedup:** 2-8x for parsing phase (but parsing is <5% of total time)
- **File:** `scripts/ingest_library.py`

### Phase 2: Concurrent LLM Extraction (Main Win)

#### 2.1 Async Function-Level Parallelism
- Process N functions concurrently (N=3-4 to respect rate limits)
- Use `asyncio.Semaphore` for rate limiting
- Implement exponential backoff for API errors
- Add `--parallel N` flag to control concurrency (default: 4)
- **Speedup:** 3-4x (limited by API rate limits)
- **Note:** Only works with API backend; CLI mode stays sequential
- **Files:** `axiom/ingestion/extractor.py`, `scripts/ingest_library.py`

#### 2.2 Rate Limit Management
- Track requests/minute
- Semaphore limits concurrent calls
- Exponential backoff on 429 errors
- **Dependency:** Add `tenacity>=8.2.0` for retry logic

### Phase 3: Caching & Incremental (For Repeat Runs)

#### 3.1 Incremental Extraction Cache
- Hash (file_path + func_name + source_hash) → cache extracted axioms
- Skip unchanged functions on re-run
- **Speedup:** 100% for unchanged code
- **New file:** `axiom/ingestion/extraction_cache.py`

#### 3.2 Anthropic Prompt Caching
- Use `cache_control: {"type": "ephemeral"}` on system prompt
- Same system prompt cached across calls
- **Speedup:** 10-20% latency, significant cost savings

## Implementation Order

```
Step 1: Direct Anthropic API backend (1.1)
Step 2: Async parallel extraction (2.1 + 2.2) - THE BIG WIN
Step 3: Incremental cache (3.1) - for repeat runs
Step 4: Prompt caching (3.2) - cost savings
```

## Files to Modify

| File | Changes |
|------|---------|
| `axiom/ingestion/extractor.py` | Direct API, async, rate limiting |
| `scripts/ingest_library.py` | Parallel parsing, async orchestration |
| `pyproject.toml` | Add anthropic, tenacity deps |
| `axiom/ingestion/extraction_cache.py` | NEW: incremental cache |

## Expected Speedup

| Phase | Speedup | Cumulative |
|-------|---------|------------|
| Phase 1 | 1.5-2x | 1.5-2x |
| Phase 2 | 3-4x | 5-8x |
| Phase 3 | 2x (repeat runs) | 10-16x |

## Quality Safeguards

1. Same prompts, same model → same quality
2. Parallelism doesn't change extraction logic
3. A/B test any prompt size optimizations
4. Review workflow unchanged
