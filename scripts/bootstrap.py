#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Bootstrap the Axiom knowledge graph from K semantics."""

import argparse
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.extractors import (
    ErrorCodeLinker,
    CSignatureExtractor,
    ErrorCodesParser,
    KDependencyExtractor,
    KSemanticsExtractor,
)
from axiom.graph import Neo4jLoader, apply_schema
from axiom.vectors import LanceDBLoader


def main() -> int:
    """Bootstrap the Axiom knowledge graph."""
    parser = argparse.ArgumentParser(
        description="Bootstrap Axiom knowledge graph from K semantics"
    )
    parser.add_argument(
        "--k-semantics",
        type=Path,
        default=Path("external/c-semantics"),
        help="Path to c-semantics repository",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("knowledge/foundations/c11_core.toml"),
        help="Output TOML file for extracted axioms",
    )
    parser.add_argument(
        "--layer",
        default="c11_core",
        choices=["c11_core", "c11_stdlib", "cpp_core", "cpp_stdlib"],
        help="Which layer to extract",
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
    parser.add_argument(
        "--skip-toml",
        action="store_true",
        help="Skip saving to TOML",
    )
    parser.add_argument(
        "--with-deps",
        action="store_true",
        help="Extract with dependency resolution (two-pass)",
    )

    args = parser.parse_args()

    # Validate paths
    k_root = args.k_semantics
    if not k_root.exists():
        print(f"Error: K semantics directory not found: {k_root}")
        print("Did you run: git submodule update --init?")
        return 1

    # Determine semantics directory based on layer
    # Note: c11_core also includes semantics/common/ for shared functions like deleteObject
    # For stdlib layers, we include core directories for cross-layer dependency resolution
    layer_paths = {
        "c11_core": [
            k_root / "semantics" / "c" / "language",
            k_root / "semantics" / "common",  # Shared functions (deleteObject, etc.)
        ],
        "c11_stdlib": [
            k_root / "semantics" / "c" / "library",
            # Include core paths for cross-layer dependency index (but only extract from library)
        ],
        "cpp_core": [
            k_root / "semantics" / "cpp" / "language",
            k_root / "semantics" / "common",  # Shared functions
        ],
        "cpp_stdlib": [
            k_root / "semantics" / "cpp" / "library",
            # Include core paths for cross-layer dependency index (but only extract from library)
        ],
    }

    # Define which directories to include in the function index for cross-layer resolution
    # This allows stdlib axioms to depend on core axioms
    index_paths = {
        "c11_core": layer_paths["c11_core"],
        "c11_stdlib": [
            k_root / "semantics" / "c" / "library",
            k_root / "semantics" / "c" / "language",
            k_root / "semantics" / "common",
        ],
        "cpp_core": layer_paths["cpp_core"],
        "cpp_stdlib": [
            k_root / "semantics" / "cpp" / "library",
            k_root / "semantics" / "cpp" / "language",
            k_root / "semantics" / "common",
        ],
    }

    semantics_dirs = layer_paths[args.layer]
    index_dirs = index_paths[args.layer]

    for semantics_dir in semantics_dirs:
        if not semantics_dir.exists():
            print(f"Error: Semantics directory not found: {semantics_dir}")
            return 1

    error_codes_csv = k_root / "examples" / "c" / "error-codes" / "Error_Codes.csv"
    if not error_codes_csv.exists():
        print(f"Warning: Error codes CSV not found: {error_codes_csv}")
        error_codes_csv = None

    print("=" * 60)
    print(f"Axiom Knowledge Graph Bootstrap - {args.layer}")
    print("=" * 60)
    print(f"Extract from: {len(semantics_dirs)} directories")
    for d in semantics_dirs:
        print(f"  - {d.name}/")
    if args.with_deps and len(index_dirs) > len(semantics_dirs):
        print(f"Index includes: {len(index_dirs)} directories (cross-layer)")
    print()

    # Step 1: Extract axioms from K semantics (from all directories)
    print("Step 1: Extracting axioms from K semantics...")
    all_axioms = []

    if args.with_deps:
        # Build combined function index from INDEX directories (includes cross-layer)
        print("  - Building combined function index...")

        combined_index: dict[str, list[str]] = {}
        for idx_dir in index_dirs:
            if idx_dir.exists():
                extractor = KDependencyExtractor(idx_dir)
                dir_index = extractor.get_function_index()
                for func, axiom_ids in dir_index.items():
                    if func in combined_index:
                        combined_index[func].extend(axiom_ids)
                    else:
                        combined_index[func] = list(axiom_ids)
        print(f"    Index has {len(combined_index)} unique functions")

        # Now extract ONLY from semantics_dirs with dependency resolution
        for semantics_dir in semantics_dirs:
            print(f"  - Scanning {semantics_dir.name}/...")
            extractor = KDependencyExtractor(semantics_dir)
            axioms = extractor.extract_with_dependencies(base_index=combined_index)
            all_axioms.extend(axioms)
            print(f"    Found {len(axioms)} axioms")
    else:
        for semantics_dir in semantics_dirs:
            print(f"  - Scanning {semantics_dir.name}/...")
            extractor = KSemanticsExtractor(semantics_dir)
            axioms = extractor.extract_all()
            all_axioms.extend(axioms)
            print(f"    Found {len(axioms)} axioms")

    axioms = all_axioms
    # Set layer on all axioms
    for axiom in axioms:
        axiom.layer = args.layer
    print(f"  - Total: {len(axioms)} axioms")
    if args.with_deps:
        deps_count = sum(1 for a in axioms if a.depends_on)
        print(f"  - {deps_count} axioms have depends_on")

    # Step 1b: Extract C signatures for stdlib layers
    if args.layer in ("c11_stdlib", "cpp_stdlib"):
        headers_dir = k_root / "profiles/x86-gcc-limited-libc/include/library"
        if headers_dir.exists():
            print("\nStep 1b: Extracting C signatures from headers...")
            sig_extractor = CSignatureExtractor(headers_dir)
            signatures = sig_extractor.extract_all()
            print(f"  - Found {len(signatures)} function signatures")

            # Match signatures to axioms
            matched = 0
            for axiom in axioms:
                if axiom.function and axiom.function in signatures:
                    axiom.signature = signatures[axiom.function].signature
                    matched += 1
            print(f"  - Matched {matched} axioms with signatures")

    # Step 2: Parse error codes CSV
    print("\nStep 2: Parsing error codes CSV...")
    if error_codes_csv:
        error_parser = ErrorCodesParser(error_codes_csv)
        error_codes = error_parser.parse()
        print(f"  - Parsed {len(error_codes)} error codes")
    else:
        error_codes = []
        print("  - Skipped (no CSV found)")

    # Step 3: Link axioms to error codes
    print("\nStep 3: Linking axioms to error codes...")
    linker = ErrorCodeLinker()
    collection = linker.link(axioms, error_codes)
    collection.source = f"kframework/c-semantics/{args.layer}"

    linked_count = sum(1 for a in collection.axioms if a.violated_by)
    print(f"  - Linked {linked_count} axioms to error codes")

    # Step 4: Save to TOML
    if not args.skip_toml:
        print(f"\nStep 4: Saving to TOML ({args.output})...")
        collection.save_toml(args.output)
        print(f"  - Saved {len(collection.axioms)} axioms to {args.output}")
    else:
        print("\nStep 4: Skipping TOML save (--skip-toml)")

    # Step 5: Load into Neo4j
    if not args.skip_graph:
        print(f"\nStep 5: Loading into Neo4j ({args.neo4j_uri})...")
        try:
            with Neo4jLoader(
                args.neo4j_uri,
                args.neo4j_user,
                args.neo4j_password,
            ) as loader:
                # Apply schema
                from neo4j import GraphDatabase
                driver = GraphDatabase.driver(
                    args.neo4j_uri,
                    auth=(args.neo4j_user, args.neo4j_password),
                )
                apply_schema(driver)
                driver.close()

                # Load collection
                loader.load_collection(collection)
                counts = loader.count_nodes()
                print(f"  - Loaded {counts['axioms']} axioms")
                print(f"  - Loaded {counts['error_codes']} error codes")
                print(f"  - Created {counts['modules']} module nodes")
        except Exception as e:
            print(f"  - Warning: Failed to load into Neo4j: {e}")
            print("    Is Neo4j running? Try: docker-compose up -d")
    else:
        print("\nStep 5: Skipping Neo4j load (--skip-graph)")

    # Step 6: Load into LanceDB
    if not args.skip_vectors:
        print(f"\nStep 6: Loading into LanceDB ({args.lancedb_path})...")
        try:
            lance_loader = LanceDBLoader(str(args.lancedb_path))
            count = lance_loader.load_collection(collection)
            print(f"  - Created embeddings for {count} axioms")
        except Exception as e:
            print(f"  - Warning: Failed to load into LanceDB: {e}")
    else:
        print("\nStep 6: Skipping LanceDB load (--skip-vectors)")

    # Summary
    print("\n" + "=" * 60)
    print("Bootstrap Complete!")
    print("=" * 60)
    print(f"  Total axioms: {len(collection.axioms)}")
    print(f"  Total error codes: {len(collection.error_codes)}")
    print(f"  Linked axioms: {linked_count}")

    # Show sample axioms
    print("\nSample axioms:")
    for axiom in collection.axioms[:3]:
        print(f"  - {axiom.id}")
        print(f"    {axiom.content[:80]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
