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
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.extractors.clang_loader import load_from_string
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
    extra_args: str | None = None,
    recursive: bool = False,
) -> dict:
    """Run the axiom-extract C++ tool and return JSON output."""
    binary = find_axiom_extract()
    if not binary:
        raise FileNotFoundError(
            "axiom-extract binary not found. "
            "Please build it with: cd tools/axiom-extract && mkdir build && cd build && cmake .. && make"
        )

    cmd = [str(binary)]

    if recursive:
        cmd.append("-r")

    if compile_commands:
        cmd.extend(["-p", str(compile_commands.parent)])

    if source_file:
        cmd.append(str(source_file))

    if extra_args:
        cmd.extend(["--extra-arg", extra_args])

    logger.info(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"axiom-extract failed: {result.stderr}")
        raise RuntimeError(f"axiom-extract failed with code {result.returncode}")

    return result.stdout


def link_depends_on(
    axioms: list[Axiom],
    vector_db_path: Path | None = None,
) -> list[Axiom]:
    """Link axioms to foundation axioms using semantic search."""
    if not vector_db_path:
        vector_db_path = Path(__file__).parent.parent / "knowledge" / "lancedb"

    if not vector_db_path.exists():
        logger.warning(f"Vector DB not found at {vector_db_path}, skipping linking")
        return axioms

    try:
        loader = LanceDBLoader(str(vector_db_path))
    except Exception as e:
        logger.warning(f"Could not initialize LanceDBLoader: {e}")
        return axioms

    linked_axioms = []
    for axiom in axioms:
        # Search for related foundation axioms
        query = f"{axiom.content} {axiom.formal_spec or ''}"
        try:
            results = loader.search(query, limit=5)
            depends = []
            for result in results:
                # Only link if similarity is high enough
                if result.get("_distance", 1.0) < 0.5:
                    dep_id = result.get("id")
                    if dep_id and dep_id != axiom.id:
                        depends.append(dep_id)

            axiom.depends_on = depends[:3]  # Limit to top 3
        except Exception as e:
            logger.debug(f"Could not search for {axiom.id}: {e}")

        linked_axioms.append(axiom)

    return linked_axioms


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
        help="Single source file to analyze",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Recursively scan directory for C++ source files",
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

    if not args.compile_commands and not args.file:
        parser.error("Either --compile-commands or --file is required")

    try:
        # Run C++ extractor
        logger.info("Running axiom-extract...")
        json_str = run_axiom_extract(
            compile_commands=args.compile_commands,
            source_file=args.file,
            extra_args=args.args,
            recursive=args.recursive,
        )

        # Parse JSON output to AxiomCollection
        source = str(args.compile_commands or args.file)
        collection = load_from_string(json_str, source=source)
        logger.info(f"Extracted {len(collection.axioms)} axioms")

        # Link to foundation axioms
        if args.link:
            logger.info("Linking to foundation axioms...")
            collection.axioms = link_depends_on(list(collection.axioms), args.vector_db)

        # TODO: LLM fallback for low-confidence axioms
        if args.llm_fallback:
            logger.warning("LLM fallback not yet implemented")

        # Save to TOML using the built-in method
        collection.save_toml(args.output)
        logger.info(f"Saved {len(collection.axioms)} axioms to {args.output}")

        # Print statistics
        json_data = json.loads(json_str)
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
