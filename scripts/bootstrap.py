#!/usr/bin/env python3
"""Bootstrap the Axiom knowledge graph from K semantics."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.extractors import AxiomLinker, ErrorCodesParser, KSemanticsExtractor
from axiom.graph import Neo4jLoader, apply_schema
from axiom.models import AxiomCollection
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
        default=Path("knowledge/foundations/c11_axioms.json"),
        help="Output JSON file for extracted axioms",
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
        "--skip-json",
        action="store_true",
        help="Skip saving to JSON",
    )

    args = parser.parse_args()

    # Validate paths
    k_root = args.k_semantics
    if not k_root.exists():
        print(f"Error: K semantics directory not found: {k_root}")
        print("Did you run: git submodule update --init?")
        return 1

    semantics_dir = k_root / "semantics" / "c"
    if not semantics_dir.exists():
        print(f"Error: Semantics directory not found: {semantics_dir}")
        return 1

    error_codes_csv = k_root / "examples" / "c" / "error-codes" / "Error_Codes.csv"
    if not error_codes_csv.exists():
        print(f"Error: Error codes CSV not found: {error_codes_csv}")
        return 1

    print("=" * 60)
    print("Axiom Knowledge Graph Bootstrap")
    print("=" * 60)
    print()

    # Step 1: Extract axioms from K semantics
    print("Step 1: Extracting axioms from K semantics...")
    extractor = KSemanticsExtractor(semantics_dir)
    axioms = extractor.extract_all()
    print(f"  - Found {len(axioms)} axioms")

    # Step 2: Parse error codes CSV
    print("\nStep 2: Parsing error codes CSV...")
    error_parser = ErrorCodesParser(error_codes_csv)
    error_codes = error_parser.parse()
    print(f"  - Parsed {len(error_codes)} error codes")

    # Step 3: Link axioms to error codes
    print("\nStep 3: Linking axioms to error codes...")
    linker = AxiomLinker()
    collection = linker.link(axioms, error_codes)

    linked_count = sum(1 for a in collection.axioms if a.violated_by)
    print(f"  - Linked {linked_count} axioms to error codes")

    # Step 4: Save to JSON
    if not args.skip_json:
        print(f"\nStep 4: Saving to JSON ({args.output})...")
        args.output.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict and handle datetime serialization
        collection_dict = collection.model_dump()
        collection_dict["extracted_at"] = collection_dict["extracted_at"].isoformat()

        with open(args.output, "w") as f:
            json.dump(collection_dict, f, indent=2, default=str)
        print(f"  - Saved {len(collection.axioms)} axioms to {args.output}")
    else:
        print("\nStep 4: Skipping JSON save (--skip-json)")

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
