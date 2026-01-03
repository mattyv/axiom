#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Extract axioms from C++ libraries using Clang LibTooling.

This script wraps the axiom-extract C++ tool and converts its JSON output
to TOML format compatible with the Axiom knowledge base.

By default, extraction includes:
- Foundation axiom linking (similarity-based)
- LLM refinement for low-confidence axioms
- Enrichment with on_violation descriptions

Usage:
    # Extract from library with compile_commands.json (full pipeline)
    python scripts/extract_clang.py \\
        --compile-commands /path/to/build/compile_commands.json \\
        --output knowledge/libraries/mylib.toml

    # Extract single file
    python scripts/extract_clang.py \\
        --file src/foo.cpp \\
        --args="-std=c++20 -I/path/to/include" \\
        --output axioms.toml

    # Fast extraction (no LLM, no enrichment)
    python scripts/extract_clang.py \\
        --compile-commands build/compile_commands.json \\
        --no-llm-fallback --no-enrich \\
        --output mylib.toml
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from collections.abc import Iterator
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.extractors import semantic_linker
from axiom.extractors.clang_loader import parse_json_with_call_graph
from axiom.extractors.enricher import enrich_axioms
from axiom.extractors.propagation import propagate_preconditions
from axiom.models import Axiom
from axiom.vectors.loader import LanceDBLoader

logger = logging.getLogger(__name__)


def discover_axiom_toml(source_path: Path) -> Path | None:
    """Look for .axiom.toml in source directory or parents.

    Searches the given path (if directory) or its parent (if file),
    then walks up to 3 parent levels looking for .axiom.toml files.
    The closest .axiom.toml takes precedence.

    Args:
        source_path: Path to source file or directory

    Returns:
        Path to .axiom.toml if found, None otherwise
    """
    path = source_path if source_path.is_dir() else source_path.parent

    # Check current directory first, then walk up to 3 levels
    for parent in [path] + list(path.parents)[:3]:
        candidate = parent / ".axiom.toml"
        if candidate.exists():
            return candidate

    return None


class ExtractionProgress:
    """Progress tracker with spinner for extraction phases."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, total_items: int, phase: str = "Processing", width: int = 20):
        self.total_items = total_items
        self.current_item = 0
        self.processed_count = 0
        self.phase = phase
        self.width = width
        self.start_time = time.time()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._status = "Starting..."
        self._last_len = 0

    def _render(self, frame: str) -> str:
        with self._lock:
            percent = self.current_item / self.total_items if self.total_items > 0 else 0
            filled = int(self.width * percent)
            bar = "█" * filled + "░" * (self.width - filled)

            elapsed = time.time() - self.start_time
            if self.current_item > 0:
                eta = (elapsed / self.current_item) * (self.total_items - self.current_item)
                eta_min = int(eta // 60)
                eta_sec = int(eta % 60)
                eta_str = f"{eta_min}m{eta_sec:02d}s"
            else:
                eta_str = "..."

            pct = int(percent * 100)
            parts = [
                f"{frame}",
                f"[{bar}]",
                f"{pct:3d}%",
                f"{self.current_item}/{self.total_items}",
                f"ETA {eta_str}",
                f"| {self._status}",
            ]

            return " ".join(parts)

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop_event.is_set():
                break
            line = self._render(frame)
            padding = max(0, self._last_len - len(line))
            sys.stdout.write(f"\r{line}{' ' * padding}")
            sys.stdout.flush()
            self._last_len = len(line)
            time.sleep(0.1)

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self, success: bool = True):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        sys.stdout.write("\r" + " " * self._last_len + "\r")
        elapsed = time.time() - self.start_time
        if success:
            print(f"✓ {self.phase} complete: {self.processed_count}/{self.total_items} ({elapsed:.1f}s)")
        else:
            print(f"✗ {self.phase} failed after {elapsed:.1f}s")
        sys.stdout.flush()

    def update(self, item_num: int, status: str, processed: int | None = None):
        with self._lock:
            self.current_item = item_num
            self._status = status
            if processed is not None:
                self.processed_count = processed


def find_axiom_extract() -> Path | None:
    """Find the axiom-extract binary."""
    # Check common locations
    candidates = [
        Path(__file__).parent.parent / "tools" / "axiom-extract" / "build" / "axiom-extract",
        Path(__file__).parent.parent / "build" / "axiom-extract",
        Path("/usr/local/bin/axiom-extract"),
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    # Check PATH
    found = shutil.which("axiom-extract")
    if found:
        return Path(found)

    return None


def run_axiom_extract(
    compile_commands: Path | None = None,
    source_file: Path | None = None,
    source_files: list[Path] | None = None,
    extra_args: str | None = None,
    recursive: bool = False,
    parallel_jobs: int | None = None,
) -> dict:
    """Run the axiom-extract C++ tool and return JSON output.

    Args:
        compile_commands: Path to compile_commands.json
        source_file: Single source file or directory to analyze
        source_files: Additional source files to analyze
        extra_args: Extra compiler arguments (e.g., '-std=c++20 -I/path')
        recursive: Recursively scan directories for C++ source files
        parallel_jobs: Number of parallel jobs (-j flag)
    """
    binary = find_axiom_extract()
    if not binary:
        raise FileNotFoundError(
            "axiom-extract binary not found. "
            "Please build it with: cd tools/axiom-extract && mkdir build && cd build && cmake .. && make"
        )

    cmd = [str(binary)]

    if recursive:
        cmd.append("-r")

    if parallel_jobs:
        cmd.extend(["-j", str(parallel_jobs)])

    if compile_commands:
        cmd.extend(["-p", str(compile_commands.parent)])

    if source_file:
        cmd.append(str(source_file))

    if source_files:
        cmd.extend([str(f) for f in source_files])

    # Add extra compiler args using -- separator (standard Clang tooling format)
    if extra_args:
        cmd.append("--")
        cmd.extend(extra_args.split())

    logger.info(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"axiom-extract failed: {result.stderr}")
        raise RuntimeError(f"axiom-extract failed with code {result.returncode}")

    return result.stdout


def link_depends_on(
    axioms: list[Axiom],
    vector_db_path: Path | None = None,
    link_type: str = "similarity",
    show_progress: bool = True,
) -> list[Axiom]:
    """Link axioms to foundation axioms using semantic search filtered to foundation layers.

    Args:
        axioms: List of axioms to link
        vector_db_path: Path to LanceDB vector database
        link_type: Type of linking to use:
            - "similarity": Top-3 similarity-based linking (fast, no LLM)
            - "semantic": LLM-based direct dependency identification (accurate, uses LLM)
        show_progress: Whether to show interactive progress
    """
    if not vector_db_path:
        vector_db_path = Path(__file__).parent.parent / "data" / "lancedb"

    if not vector_db_path.exists():
        logger.warning(f"Vector DB not found at {vector_db_path}, skipping linking")
        return axioms

    # Suppress noisy SentenceTransformer/tqdm/LanceDB output
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    # Silence SentenceTransformer logging
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("lancedb").setLevel(logging.WARNING)
    logging.getLogger("pylance").setLevel(logging.WARNING)

    # Redirect stdout/stderr to suppress model loading messages
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')

    try:
        loader = LanceDBLoader(str(vector_db_path))
    except Exception as e:
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        logger.warning(f"Could not initialize LanceDBLoader: {e}")
        return axioms
    finally:
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Check if table exists
    tables = loader.db.list_tables()
    table_names = tables.tables if hasattr(tables, 'tables') else tables
    if "axioms" not in table_names:
        logger.warning("No axioms table in vector DB, skipping linking")
        return axioms

    # Initialize progress tracker
    progress: ExtractionProgress | None = None
    if show_progress and sys.stdout.isatty():
        progress = ExtractionProgress(len(axioms), f"Linking ({link_type})")
        progress.start()

    linked_count = 0

    if link_type == "semantic":
        # Batched LLM-based linking: group by function to reduce LLM calls
        function_groups = semantic_linker.group_by_function(axioms)

        linked_axioms = []
        item_num = 0
        for _function_name, func_axioms in function_groups.items():
            # For each function group, find union of candidates across all axioms
            all_candidates = {}
            for axiom in func_axioms:
                item_num += 1
                if progress:
                    func_short = _function_name[:20] + "..." if len(_function_name) > 20 else _function_name
                    progress.update(item_num, f"Searching {func_short}", linked_count)

                # Suppress tqdm during search
                old_stderr = sys.stderr
                sys.stderr = open(os.devnull, 'w')
                try:
                    query = f"{axiom.content} {axiom.formal_spec or ''}"
                    candidates = semantic_linker.search_foundations(query, loader, limit=10)
                    for c in candidates:
                        all_candidates[c["id"]] = c
                finally:
                    sys.stderr.close()
                    sys.stderr = old_stderr

            # Batch LLM call for all axioms in this function
            if progress:
                progress.update(item_num, f"LLM linking {len(func_axioms)} axioms", linked_count)

            candidate_list = list(all_candidates.values())
            link_map = semantic_linker.link_axioms_batch_with_llm(
                func_axioms,
                candidate_list,
                model="sonnet",
            )

            # Apply links to axioms
            for axiom in func_axioms:
                new_depends = link_map.get(axiom.id, [])
                axiom.depends_on = semantic_linker.merge_depends_on(axiom.depends_on, new_depends)
                if new_depends:
                    linked_count += 1
                linked_axioms.append(axiom)

        if progress:
            progress.processed_count = linked_count
            progress.stop(success=True)
        return linked_axioms

    else:
        # Similarity-based linking: fast, no LLM
        linked_axioms = []
        for i, axiom in enumerate(axioms):
            if progress:
                func_short = (axiom.function or "global")[:20]
                progress.update(i + 1, f"{func_short}", linked_count)

            try:
                # Suppress tqdm during search
                old_stderr = sys.stderr
                sys.stderr = open(os.devnull, 'w')
                try:
                    query = f"{axiom.content} {axiom.formal_spec or ''}"
                    candidates = semantic_linker.search_foundations(query, loader, limit=10)
                finally:
                    sys.stderr.close()
                    sys.stderr = old_stderr

                # Similarity-based: top 3 candidates
                new_depends = [c["id"] for c in candidates[:3] if c["id"] != axiom.id]

                axiom.depends_on = semantic_linker.merge_depends_on(axiom.depends_on, new_depends)
                if new_depends:
                    linked_count += 1
            except Exception as e:
                logger.debug(f"Could not search for {axiom.id}: {e}")

            linked_axioms.append(axiom)

        if progress:
            progress.processed_count = linked_count
            progress.stop(success=True)
        return linked_axioms


# LLM Refiner configuration
LLM_CONFIDENCE_THRESHOLD = 0.80
LLM_BATCH_SIZE = 25  # Optimized for haiku model
LLM_MODEL = "haiku"  # Fast model sufficient for refinement


def chunk(items: list, size: int) -> Iterator[list]:
    """Yield successive chunks of items."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def build_refinement_prompt(axioms: list[Axiom]) -> str:
    """Build prompt for axiom refinement."""
    axiom_lines = []
    for a in axioms:
        axiom_lines.append(
            f"""[[axioms]]
id = "{a.id}"
content = "{a.content}"
formal_spec = "{a.formal_spec}"
confidence = {a.confidence}
function = "{a.function or ''}"
"""
        )

    return f"""Review these low-confidence axioms extracted from C++ code.
For each axiom:
1. Verify correctness against C++ semantics
2. Improve the content/formal_spec if needed
3. Set confidence to your level of certainty (0.0-1.0)
4. Add rationale explaining your changes

Return ONLY valid TOML with refined axioms:

{chr(10).join(axiom_lines)}

Respond with refined axioms in the same TOML format, adding a 'rationale' field."""


def call_claude_cli(prompt: str, model: str = LLM_MODEL) -> str:
    """Call Claude CLI for refinement."""
    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--model",
                model,
                "--dangerously-skip-permissions",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.warning("LLM call timed out")
        return ""
    except FileNotFoundError:
        logger.warning("Claude CLI not found")
        return ""


def parse_refinement_response(response: str, originals: list[Axiom]) -> list[Axiom]:
    """Parse TOML response and update axioms."""
    try:
        # Extract TOML block if wrapped in markdown
        if "```toml" in response:
            start = response.index("```toml") + 7
            end = response.index("```", start)
            response = response[start:end]

        data = tomllib.loads(response)
        refined_map = {a["id"]: a for a in data.get("axioms", [])}

        result = []
        for orig in originals:
            if orig.id in refined_map:
                r = refined_map[orig.id]
                # Update axiom with refined values
                orig.content = r.get("content", orig.content)
                orig.formal_spec = r.get("formal_spec", orig.formal_spec)
                orig.confidence = r.get("confidence", orig.confidence)
            result.append(orig)
        return result
    except Exception as e:
        logger.warning(f"Failed to parse LLM response: {e}")
        return list(originals)


def group_axioms_by_function(axioms: list[Axiom]) -> dict[str, list[Axiom]]:
    """Group axioms by function for coherent batching."""
    from collections import defaultdict
    groups: dict[str, list[Axiom]] = defaultdict(list)
    for axiom in axioms:
        key = axiom.function or "__global__"
        groups[key].append(axiom)
    return dict(groups)


def build_refinement_queries(axiom: Axiom) -> list[str]:
    """Generate semantic search queries for RAG context."""
    queries = []
    content = axiom.content.lower()

    # Operation-based queries
    if "divis" in content or "modulo" in content or "/" in content:
        queries.append("division by zero undefined behavior integer modulo")
    if "pointer" in content or "null" in content or "nullptr" in content:
        queries.append("null pointer dereference undefined behavior")
    if "array" in content or "index" in content or "bounds" in content:
        queries.append("array index bounds out of range undefined behavior")
    if "memory" in content or "alloc" in content or "new" in content or "delete" in content:
        queries.append("memory allocation deallocation new delete")
    if "overflow" in content or "integer" in content:
        queries.append("integer overflow signed unsigned undefined behavior")
    if "thread" in content or "mutex" in content or "lock" in content:
        queries.append("thread synchronization mutex data race")
    if "assert" in content or "expect" in content:
        queries.append("assertion precondition postcondition invariant")

    # Generic query from content
    if axiom.content:
        queries.append(axiom.content[:100])

    return queries[:5]  # Limit to 5 queries


def query_rag_for_refinement(
    axioms: list[Axiom],
    vector_db: LanceDBLoader | None,
) -> list[dict]:
    """Query vector DB for related foundation axioms."""
    if not vector_db:
        return []

    all_candidates: dict[str, dict] = {}
    for axiom in axioms:
        for query in build_refinement_queries(axiom):
            try:
                results = semantic_linker.search_foundations(query, vector_db, limit=5)
                for r in results:
                    if r["id"] not in all_candidates:
                        all_candidates[r["id"]] = r
            except Exception as e:
                logger.debug(f"RAG query failed for {axiom.id}: {e}")

    # Return top candidates by relevance (deduplicated)
    return list(all_candidates.values())[:15]


def format_related_axioms(related: list[dict]) -> str:
    """Format related foundation axioms for the prompt."""
    if not related:
        return "No related foundation axioms found."

    lines = []
    for r in related[:10]:  # Limit to 10 for prompt size
        lines.append(f"- {r['id']}: {r.get('content', '')[:100]}")
    return "\n".join(lines)


def build_refinement_prompt_with_rag(
    axioms: list[Axiom],
    related_axioms: list[dict],
) -> str:
    """Build prompt for axiom refinement with RAG context."""
    axiom_lines = []
    for a in axioms:
        axiom_lines.append(
            f"""[[axioms]]
id = "{a.id}"
content = "{a.content}"
formal_spec = "{a.formal_spec or ''}"
confidence = {a.confidence}
function = "{a.function or ''}"
depends_on = []
"""
        )

    related_section = format_related_axioms(related_axioms)

    return f"""You are an expert in C/C++ semantics. Review these low-confidence axioms.

## Related Foundation Axioms (from C11/C++20 standards)

{related_section}

## Axioms to Refine

{chr(10).join(axiom_lines)}

## Task

For each axiom:
1. Verify correctness against C++ semantics
2. Improve content/formal_spec if needed
3. Add `depends_on` array with IDs of relevant foundation axioms from above
4. Set confidence:
   - 1.0: Direct match to foundation axiom
   - 0.8-0.9: Clear semantic requirement
   - 0.6-0.7: Context-dependent
   - <0.6: Uncertain

Return ONLY valid TOML with refined axioms. Include depends_on = ["id1", "id2"] for linked axioms."""


def parse_refinement_response_with_depends(
    response: str,
    originals: list[Axiom],
) -> list[Axiom]:
    """Parse TOML response and update axioms including depends_on."""
    try:
        # Extract TOML block if wrapped in markdown
        if "```toml" in response:
            start = response.index("```toml") + 7
            end = response.index("```", start)
            response = response[start:end]
        elif "```" in response:
            start = response.index("```") + 3
            newline_idx = response.find("\n", start)
            if newline_idx != -1:
                start = newline_idx + 1
            end = response.index("```", start)
            response = response[start:end]

        data = tomllib.loads(response)
        refined_map = {a["id"]: a for a in data.get("axioms", [])}

        result = []
        for orig in originals:
            if orig.id in refined_map:
                r = refined_map[orig.id]
                # Update axiom with refined values
                orig.content = r.get("content", orig.content)
                orig.formal_spec = r.get("formal_spec", orig.formal_spec)
                orig.confidence = r.get("confidence", orig.confidence)
                # Update depends_on if provided
                if "depends_on" in r and r["depends_on"]:
                    new_deps = r["depends_on"]
                    existing = orig.depends_on or []
                    # Merge without duplicates
                    orig.depends_on = list(dict.fromkeys(existing + new_deps))
            result.append(orig)
        return result
    except Exception as e:
        logger.warning(f"Failed to parse LLM response: {e}")
        return list(originals)


def refine_low_confidence_axioms(
    axioms: list[Axiom],
    use_llm: bool = False,
    model: str = LLM_MODEL,
    batch_size: int = LLM_BATCH_SIZE,
    vector_db: LanceDBLoader | None = None,
    show_progress: bool = True,
) -> list[Axiom]:
    """Refine low-confidence axioms using LLM with RAG context.

    Axioms with confidence below LLM_CONFIDENCE_THRESHOLD are sent to the
    Claude CLI in batches for refinement. When vector_db is provided,
    related foundation axioms are included for context.

    Args:
        axioms: List of axioms to refine.
        use_llm: Whether to use LLM for refinement.
        model: Model to use (default: haiku).
        batch_size: Number of axioms per LLM call (default: 25).
        vector_db: Optional LanceDB loader for RAG context.
        show_progress: Whether to show interactive progress.
    """
    if not use_llm:
        return list(axioms)

    # Identify axioms needing refinement
    needs_refinement = [a for a in axioms if a.confidence < LLM_CONFIDENCE_THRESHOLD]
    if not needs_refinement:
        print(f"✓ No axioms need LLM refinement (all confidence >= {LLM_CONFIDENCE_THRESHOLD})")
        return list(axioms)

    # Group by function for coherent batching
    groups = group_axioms_by_function(needs_refinement)

    # Calculate total batches
    total_batches = sum(
        (len(func_axioms) + batch_size - 1) // batch_size
        for func_axioms in groups.values()
    )

    # Initialize progress tracker
    progress: ExtractionProgress | None = None
    if show_progress and sys.stdout.isatty():
        progress = ExtractionProgress(total_batches, f"Refining ({model})")
        progress.start()

    refined = []
    batch_num = 0
    refined_count = 0

    for func_name, func_axioms in groups.items():
        # Query RAG for this function's axioms (suppress tqdm)
        if vector_db:
            old_stderr = sys.stderr
            sys.stderr = open(os.devnull, 'w')
            try:
                related = query_rag_for_refinement(func_axioms, vector_db)
            finally:
                sys.stderr.close()
                sys.stderr = old_stderr
        else:
            related = []

        # Process in batches within this function group
        for batch in chunk(func_axioms, batch_size):
            batch_num += 1
            func_short = func_name[:20] + "..." if len(func_name) > 20 else func_name
            if progress:
                progress.update(batch_num, f"{func_short} ({len(batch)} axioms)", refined_count)

            if vector_db:
                prompt = build_refinement_prompt_with_rag(batch, related)
            else:
                prompt = build_refinement_prompt(batch)

            response = call_claude_cli(prompt, model)
            if response:
                if vector_db:
                    batch_refined = parse_refinement_response_with_depends(response, batch)
                else:
                    batch_refined = parse_refinement_response(response, batch)
                refined.extend(batch_refined)
                refined_count += len(batch_refined)
            else:
                # Keep originals if LLM fails
                refined.extend(batch)

    if progress:
        progress.processed_count = refined_count
        progress.stop(success=True)

    # Merge: replace refined axioms, keep others
    refined_ids = {a.id for a in refined}
    return [a for a in axioms if a.id not in refined_ids] + refined


def _save_pairings_toml(
    pairings: list,
    idioms: list,
    output_path: Path,
) -> None:
    """Save pairings and idioms to a TOML file.

    Args:
        pairings: List of Pairing objects
        idioms: List of Idiom objects
        output_path: Path to save the TOML file
    """
    lines = ["# Function pairings and usage idioms", ""]

    if pairings:
        for p in pairings:
            lines.append("[[pairing]]")
            lines.append(f'opener = "{p.opener_id}"')
            lines.append(f'closer = "{p.closer_id}"')
            lines.append(f"required = {'true' if p.required else 'false'}")
            lines.append(f"confidence = {p.confidence}")
            lines.append(f'source = "{p.source}"')
            if p.evidence:
                lines.append(f'evidence = "{p.evidence}"')
            if p.cell:
                lines.append(f'cell = "{p.cell}"')
            lines.append("")

    if idioms:
        for i in idioms:
            lines.append("[[idiom]]")
            lines.append(f'id = "{i.id}"')
            lines.append(f'name = "{i.name}"')
            participants_str = ", ".join(f'"{p}"' for p in i.participants)
            lines.append(f"participants = [{participants_str}]")
            if i.template:
                # Use multiline string for template
                lines.append("template = '''")
                lines.append(i.template.strip())
                lines.append("'''")
            lines.append(f'source = "{i.source}"')
            lines.append("")

    output_path.write_text("\n".join(lines))


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Extract axioms from C++ libraries using Clang LibTooling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--compile-commands",
        type=Path,
        help="Path to compile_commands.json",
    )
    parser.add_argument(
        "--file",
        type=Path,
        action="append",
        dest="files",
        help="Source file or directory to analyze (can be specified multiple times)",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Recursively scan directories for C++ source files",
    )
    parser.add_argument(
        "-j", "--jobs",
        type=int,
        help="Number of parallel jobs (default: number of CPU cores)",
    )
    parser.add_argument(
        "--args",
        type=str,
        help="Extra compiler arguments (e.g., '-std=c++20 -I/path')",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Output TOML file path",
    )
    parser.add_argument(
        "--name",
        type=str,
        help="Library name for the axiom collection",
    )
    parser.add_argument(
        "--no-llm-fallback",
        action="store_true",
        help="Disable LLM refinement for low-confidence axioms (enabled by default)",
    )
    parser.add_argument(
        "--refine-model",
        type=str,
        default=LLM_MODEL,
        help=f"Model for LLM refinement (default: {LLM_MODEL})",
    )
    parser.add_argument(
        "--refine-batch-size",
        type=int,
        default=LLM_BATCH_SIZE,
        help=f"Batch size for LLM refinement (default: {LLM_BATCH_SIZE})",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip enrichment (enrichment enabled by default)",
    )
    parser.add_argument(
        "--enrich-model",
        type=str,
        default="sonnet",
        help="Model for enrichment (default: sonnet)",
    )
    parser.add_argument(
        "--link",
        action="store_true",
        default=True,
        help="Link axioms to foundation axioms (default: True)",
    )
    parser.add_argument(
        "--no-link",
        action="store_false",
        dest="link",
        help="Skip linking to foundation axioms",
    )
    parser.add_argument(
        "--link-type",
        type=str,
        choices=["similarity", "semantic"],
        default="similarity",
        help="Type of dependency linking: 'similarity' (fast, top-3) or 'semantic' (LLM-based, accurate)",
    )
    parser.add_argument(
        "--vector-db",
        type=Path,
        help="Path to LanceDB vector database",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--axiom-toml",
        type=Path,
        help="Path to .axiom.toml file with pairings/idioms (auto-discovered if not specified)",
    )
    parser.add_argument(
        "--no-axiom-toml",
        action="store_true",
        help="Disable auto-discovery of .axiom.toml files",
    )

    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not args.compile_commands and not args.files:
        parser.error("Either --compile-commands or --file is required")

    try:
        # Run C++ extractor
        logger.info("Running axiom-extract...")
        # Handle multiple files: first is source_file, rest are source_files
        source_file = args.files[0] if args.files else None
        source_files = args.files[1:] if args.files and len(args.files) > 1 else None
        json_str = run_axiom_extract(
            compile_commands=args.compile_commands,
            source_file=source_file,
            source_files=source_files,
            extra_args=args.args,
            recursive=args.recursive,
            parallel_jobs=args.jobs,
        )

        # Parse JSON output to AxiomCollection with call graph
        source = str(args.compile_commands or (args.files[0] if args.files else "unknown"))
        json_data = json.loads(json_str)
        collection, call_graph = parse_json_with_call_graph(json_data, source=source)
        logger.info(f"Extracted {len(collection.axioms)} axioms")

        # Propagate preconditions through call graph
        if call_graph:
            logger.info(f"Propagating preconditions from {len(call_graph)} calls...")
            original_count = len(collection.axioms)
            collection.axioms = propagate_preconditions(list(collection.axioms), call_graph)
            propagated_count = len(collection.axioms) - original_count
            if propagated_count > 0:
                logger.info(f"Added {propagated_count} propagated preconditions")

        # Link to foundation axioms
        if args.link:
            logger.info("Linking to foundation axioms...")
            collection.axioms = link_depends_on(
                list(collection.axioms),
                vector_db_path=args.vector_db,
                link_type=args.link_type,
            )

        # LLM fallback for low-confidence axioms (enabled by default)
        if not args.no_llm_fallback:
            # Initialize vector DB for RAG context if available
            vector_db = None
            vector_db_path = args.vector_db or Path(__file__).parent.parent / "data" / "lancedb"
            if vector_db_path.exists():
                try:
                    vector_db = LanceDBLoader(str(vector_db_path))
                    logger.info("Using RAG context for LLM refinement")
                except Exception as e:
                    logger.debug(f"Could not load vector DB for refinement: {e}")

            original_count = len(collection.axioms)
            collection.axioms = refine_low_confidence_axioms(
                list(collection.axioms),
                use_llm=True,
                model=args.refine_model,
                batch_size=args.refine_batch_size,
                vector_db=vector_db,
            )
            logger.info(f"LLM refinement complete ({len(collection.axioms)} axioms)")

        # Enrich axioms with on_violation and inferred axioms (enabled by default)
        if not args.no_enrich:
            original_count = len(collection.axioms)
            collection.axioms = enrich_axioms(
                list(collection.axioms),
                use_llm=True,
                model=args.enrich_model,
            )
            new_count = len(collection.axioms) - original_count
            if new_count > 0:
                logger.info(f"Enrichment added {new_count} inferred axioms")

        # Save to TOML using the built-in method
        collection.save_toml(args.output)
        logger.info(f"Saved {len(collection.axioms)} axioms to {args.output}")

        # Handle .axiom.toml pairings
        axiom_toml_path = args.axiom_toml
        if not axiom_toml_path and not args.no_axiom_toml:
            # Auto-discover from source path
            source_path = args.files[0] if args.files else args.compile_commands.parent
            axiom_toml_path = discover_axiom_toml(source_path)
            if axiom_toml_path:
                logger.info(f"Discovered .axiom.toml at: {axiom_toml_path}")

        if axiom_toml_path and axiom_toml_path.exists():
            from scripts.load_pairings import load_pairings_from_toml

            pairings, idioms = load_pairings_from_toml(axiom_toml_path)
            if pairings or idioms:
                logger.info(f"Loaded {len(pairings)} pairings and {len(idioms)} idioms from {axiom_toml_path.name}")
                # Save pairings alongside the axioms output
                pairings_output = args.output.with_suffix(".pairings.toml")
                _save_pairings_toml(pairings, idioms, pairings_output)
                logger.info(f"Saved pairings to {pairings_output}")

        # Print statistics
        stats = json_data.get("statistics", {})
        if stats:
            logger.info(f"Statistics: {stats.get('files_processed', 0)} files, "
                       f"{stats.get('axioms_extracted', 0)} axioms")

        return 0

    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
