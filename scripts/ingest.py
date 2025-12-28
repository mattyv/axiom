#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Ingest TOML axiom files into Neo4j and LanceDB.

Usage:
    python scripts/ingest.py                         # Load all TOML files
    python scripts/ingest.py --clear                 # Clear databases first
    python scripts/ingest.py knowledge/foundations/c11_core.toml  # Load specific file
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.graph import Neo4jLoader, apply_schema
from axiom.models import AxiomCollection
from axiom.vectors import LanceDBLoader


# Default TOML files to load (in order)
DEFAULT_TOML_FILES = [
    "knowledge/foundations/c11_core.toml",
    "knowledge/foundations/c11_stdlib.toml",
    "knowledge/foundations/cpp_core.toml",
    "knowledge/foundations/cpp_stdlib.toml",
    "knowledge/foundations/cpp20_language.toml",
    "knowledge/foundations/cpp20_stdlib.toml",
]


def main() -> int:
    """Ingest TOML files into databases."""
    parser = argparse.ArgumentParser(description="Ingest TOML axiom files")
    parser.add_argument(
        "files",
        type=Path,
        nargs="*",
        help="TOML files to ingest (default: all in knowledge/foundations/)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear databases before loading",
    )
    parser.add_argument(
        "--neo4j-uri",
        default="bolt://localhost:7687",
        help="Neo4j bolt URI",
    )
    parser.add_argument(
        "--neo4j-user",
        default="neo4j",
        help="Neo4j username",
    )
    parser.add_argument(
        "--neo4j-password",
        default="axiompass",
        help="Neo4j password",
    )
    parser.add_argument(
        "--lancedb-path",
        type=Path,
        default=Path("./data/lancedb"),
        help="Path to LanceDB database",
    )
    parser.add_argument(
        "--skip-graph",
        action="store_true",
        help="Skip loading into Neo4j",
    )
    parser.add_argument(
        "--skip-vectors",
        action="store_true",
        help="Skip loading into LanceDB",
    )

    args = parser.parse_args()

    # Use default files if none specified
    files_to_load = args.files if args.files else [Path(f) for f in DEFAULT_TOML_FILES]

    # Clear databases if requested
    if args.clear:
        print("Clearing databases...")
        if not args.skip_graph:
            try:
                from neo4j import GraphDatabase
                driver = GraphDatabase.driver(
                    args.neo4j_uri,
                    auth=(args.neo4j_user, args.neo4j_password),
                )
                with driver.session() as session:
                    session.run("MATCH (n) DETACH DELETE n")
                driver.close()
                print("  Neo4j cleared")
            except Exception as e:
                print(f"  Warning: Failed to clear Neo4j: {e}")

        if not args.skip_vectors:
            if args.lancedb_path.exists():
                shutil.rmtree(args.lancedb_path)
                print("  LanceDB cleared")

    # Load all TOML files
    all_axioms = []
    all_errors = []

    for toml_file in files_to_load:
        if not toml_file.exists():
            print(f"Warning: File not found: {toml_file}")
            continue

        print(f"Loading {toml_file}...")
        collection = AxiomCollection.load_toml(toml_file)
        all_axioms.extend(collection.axioms)
        all_errors.extend(collection.error_codes)
        print(f"  - {len(collection.axioms)} axioms, {len(collection.error_codes)} error codes")

    # Deduplicate error codes by code
    seen_errors = set()
    unique_errors = []
    for error in all_errors:
        if error.code not in seen_errors:
            seen_errors.add(error.code)
            unique_errors.append(error)

    # Create combined collection
    combined = AxiomCollection(
        source="combined",
        axioms=all_axioms,
        error_codes=unique_errors,
    )

    print(f"\nTotal: {len(combined.axioms)} axioms, {len(combined.error_codes)} error codes")

    # Load into Neo4j
    if not args.skip_graph:
        print(f"\nLoading into Neo4j ({args.neo4j_uri})...")
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                args.neo4j_uri,
                auth=(args.neo4j_user, args.neo4j_password),
            )
            apply_schema(driver)
            driver.close()

            with Neo4jLoader(
                args.neo4j_uri,
                args.neo4j_user,
                args.neo4j_password,
            ) as loader:
                loader.load_collection(combined)
                counts = loader.count_nodes()
                print(f"  - Loaded {counts['axioms']} axioms")
                print(f"  - Loaded {counts['error_codes']} error codes")
                print(f"  - Created {counts['modules']} module nodes")
        except Exception as e:
            print(f"  - Warning: Failed to load into Neo4j: {e}")
    else:
        print("\nSkipping Neo4j load (--skip-graph)")

    # Load into LanceDB
    if not args.skip_vectors:
        print(f"\nLoading into LanceDB ({args.lancedb_path})...")
        try:
            lance_loader = LanceDBLoader(str(args.lancedb_path))
            count = lance_loader.load_collection(combined)
            print(f"  - Created embeddings for {count} axioms")
        except Exception as e:
            print(f"  - Warning: Failed to load into LanceDB: {e}")
    else:
        print("\nSkipping LanceDB load (--skip-vectors)")

    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
