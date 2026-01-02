#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Extract axioms from C++ libraries using Clang LibTooling.

This script wraps the axiom-extract C++ tool and converts its JSON output
to TOML format compatible with the Axiom knowledge base.

Usage:
    # Extract from library with compile_commands.json
    python scripts/extract_clang.py \\
        --compile-commands /path/to/build/compile_commands.json \\
        --output knowledge/libraries/mylib.toml

    # Extract single file
    python scripts/extract_clang.py \\
        --file src/foo.cpp \\
        --args="-std=c++20 -I/path/to/include" \\
        --output axioms.toml

    # With LLM fallback for low-confidence axioms
    python scripts/extract_clang.py \\
        --compile-commands build/compile_commands.json \\
        --llm-fallback \\
        --output mylib.toml
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
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
) -> list[Axiom]:
    """Link axioms to foundation axioms using semantic search filtered to foundation layers.

    Args:
        axioms: List of axioms to link
        vector_db_path: Path to LanceDB vector database
        link_type: Type of linking to use:
            - "similarity": Top-3 similarity-based linking (fast, no LLM)
            - "semantic": LLM-based direct dependency identification (accurate, uses LLM)
    """
    if not vector_db_path:
        vector_db_path = Path(__file__).parent.parent / "data" / "lancedb"

    if not vector_db_path.exists():
        logger.warning(f"Vector DB not found at {vector_db_path}, skipping linking")
        return axioms

    try:
        loader = LanceDBLoader(str(vector_db_path))
    except Exception as e:
        logger.warning(f"Could not initialize LanceDBLoader: {e}")
        return axioms

    # Check if table exists
    tables = loader.db.list_tables()
    table_names = tables.tables if hasattr(tables, 'tables') else tables
    if "axioms" not in table_names:
        logger.warning("No axioms table in vector DB, skipping linking")
        return axioms

    # Use semantic_linker to search only foundation layer axioms
    logger.info(f"Searching for foundation axiom dependencies (link_type={link_type})...")
    linked_axioms = []
    for axiom in axioms:
        try:
            # Build search query
            query = f"{axiom.content} {axiom.formal_spec or ''}"

            # Use semantic_linker.search_foundations to filter to foundation layers only
            candidates = semantic_linker.search_foundations(query, loader, limit=10)

            if link_type == "semantic":
                # TODO: Use LLM to identify direct dependencies from candidates
                # For now, fall back to similarity-based
                logger.warning("Semantic linking not yet implemented, falling back to similarity")
                new_depends = [c["id"] for c in candidates[:3] if c["id"] != axiom.id]
            else:
                # Similarity-based: top 3 candidates
                new_depends = [c["id"] for c in candidates[:3] if c["id"] != axiom.id]

            # Merge with existing depends_on using semantic_linker.merge_depends_on
            axiom.depends_on = semantic_linker.merge_depends_on(axiom.depends_on, new_depends)

        except Exception as e:
            logger.debug(f"Could not search for {axiom.id}: {e}")

        linked_axioms.append(axiom)

    return linked_axioms


# LLM Refiner configuration
LLM_CONFIDENCE_THRESHOLD = 0.80
LLM_BATCH_SIZE = 10


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


def call_claude_cli(prompt: str) -> str:
    """Call Claude CLI for refinement."""
    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--model",
                "sonnet",
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


def refine_low_confidence_axioms(
    axioms: list[Axiom],
    use_llm: bool = False,
) -> list[Axiom]:
    """Refine low-confidence axioms using LLM.

    Axioms with confidence below LLM_CONFIDENCE_THRESHOLD are sent to the
    Claude CLI in batches for refinement.
    """
    if not use_llm:
        return list(axioms)

    # Identify axioms needing refinement
    needs_refinement = [a for a in axioms if a.confidence < LLM_CONFIDENCE_THRESHOLD]
    if not needs_refinement:
        logger.info("No axioms need LLM refinement")
        return list(axioms)

    logger.info(f"Refining {len(needs_refinement)} axioms with LLM...")

    refined = []
    for batch in chunk(needs_refinement, LLM_BATCH_SIZE):
        prompt = build_refinement_prompt(batch)
        response = call_claude_cli(prompt)
        if response:
            batch_refined = parse_refinement_response(response, batch)
            refined.extend(batch_refined)
        else:
            # Keep originals if LLM fails
            refined.extend(batch)

    # Merge: replace refined axioms, keep others
    refined_ids = {a.id for a in refined}
    return [a for a in axioms if a.id not in refined_ids] + refined


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
        "--llm-fallback",
        action="store_true",
        help="Use LLM for low-confidence axioms",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Enrich axioms with on_violation descriptions and infer new axioms",
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

        # LLM fallback for low-confidence axioms
        if args.llm_fallback:
            original_count = len(collection.axioms)
            collection.axioms = refine_low_confidence_axioms(
                list(collection.axioms), use_llm=True
            )
            logger.info(f"LLM refinement complete ({len(collection.axioms)} axioms)")

        # Enrich axioms with on_violation and inferred axioms
        if args.enrich:
            original_count = len(collection.axioms)
            logger.info(f"Enriching {original_count} axioms...")
            collection.axioms = enrich_axioms(
                list(collection.axioms),
                use_llm=True,
                model=args.enrich_model,
            )
            new_count = len(collection.axioms) - original_count
            if new_count > 0:
                logger.info(f"Enrichment added {new_count} inferred axioms")
            logger.info(f"Enrichment complete ({len(collection.axioms)} axioms)")

        # Save to TOML using the built-in method
        collection.save_toml(args.output)
        logger.info(f"Saved {len(collection.axioms)} axioms to {args.output}")

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
