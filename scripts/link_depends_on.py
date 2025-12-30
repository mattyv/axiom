#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Post-extraction depends_on linking for library axioms.

This script scans library axioms (cpp20_stdlib, user libraries), extracts
type references from signatures and content, and populates the depends_on
field with axiom IDs from the foundation layers.

Usage:
    python scripts/link_depends_on.py knowledge/foundations/cpp20_stdlib.toml
    python scripts/link_depends_on.py --dry-run knowledge/foundations/cpp20_stdlib.toml
"""

import argparse
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.extractors.library_depends_on import (
    extract_type_references,
    link_axiom_depends_on,
)
from axiom.models import AxiomCollection
from axiom.vectors import LanceDBLoader


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Link depends_on fields for library axioms"
    )
    parser.add_argument(
        "toml_file",
        type=Path,
        help="Path to TOML file with axioms to link",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be linked without modifying files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-link axioms that already have depends_on",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("./data/lancedb"),
        help="Path to LanceDB database",
    )

    args = parser.parse_args()

    if not args.toml_file.exists():
        print(f"Error: File not found: {args.toml_file}")
        return 1

    # Load axioms
    print(f"Loading axioms from {args.toml_file}...")
    collection = AxiomCollection.load_toml(args.toml_file)
    total = len(collection.axioms)
    print(f"  Loaded {total} axioms")

    # Count current depends_on
    with_deps = sum(1 for a in collection.axioms if a.depends_on)
    print(f"  Already have depends_on: {with_deps}/{total} ({100*with_deps//total}%)")

    # Load LanceDB
    print(f"\nConnecting to LanceDB at {args.db_path}...")
    try:
        lance = LanceDBLoader(str(args.db_path))
    except Exception as e:
        print(f"Error: Could not connect to LanceDB: {e}")
        return 1

    # Analyze type references
    print("\nAnalyzing type references...")
    type_counts = {}
    for axiom in collection.axioms:
        refs = extract_type_references(axiom)
        for ref in refs:
            type_counts[ref] = type_counts.get(ref, 0) + 1

    print(f"  Found {len(type_counts)} unique type references:")
    for type_name, count in sorted(type_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"    {type_name}: {count} axioms")

    if args.dry_run:
        print("\n[DRY RUN] Would link axioms - no changes made")
        return 0

    # Link depends_on
    print("\nLinking depends_on...")
    updated = link_axiom_depends_on(
        collection.axioms,
        search_func=lance.search,
        skip_existing=not args.force,
    )
    print(f"  Updated {updated} axioms")

    # Save updated collection
    print(f"\nSaving to {args.toml_file}...")
    collection.save_toml(args.toml_file)

    # Report final stats
    with_deps = sum(1 for a in collection.axioms if a.depends_on)
    print(f"\nFinal: {with_deps}/{total} axioms with depends_on ({100*with_deps//total}%)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
