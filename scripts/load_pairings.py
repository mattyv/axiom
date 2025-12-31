#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Load function pairings into Neo4j.

This script extracts pairing relationships from multiple sources:
1. K semantics cell access patterns (e.g., malloc/free via <malloced> cell)
2. TOML manifest files (e.g., knowledge/pairings/cpp20_stdlib.toml)
3. Naming heuristics (e.g., push_back/pop_back)

Usage:
    # Load from K semantics
    python scripts/load_pairings.py [--dry-run]

    # Load from TOML manifest
    python scripts/load_pairings.py --toml knowledge/pairings/cpp20_stdlib.toml [--dry-run]

The pairings connect existing axiom nodes - no re-extraction of axioms needed.
"""

import argparse
from pathlib import Path

import tomllib

from axiom.models.pairing import Idiom, Pairing


def load_pairings_from_toml(toml_path: Path) -> tuple[list[Pairing], list[Idiom]]:
    """Load pairings and idioms from a TOML manifest file.

    Args:
        toml_path: Path to the TOML file.

    Returns:
        Tuple of (pairings, idioms) loaded from the file.
    """
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    pairings = []
    for p in data.get("pairing", []):
        pairings.append(
            Pairing(
                opener_id=p["opener"],
                closer_id=p["closer"],
                required=p.get("required", True),
                source="toml_manifest",
                confidence=1.0,
                evidence=p.get("evidence", ""),
            )
        )

    idioms = []
    for i in data.get("idiom", []):
        idioms.append(
            Idiom(
                id=f"idiom_{i['name']}",
                name=i["name"],
                participants=i.get("participants", []),
                template=i.get("template", ""),
                source="toml_manifest",
            )
        )

    return pairings, idioms


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load function pairings into Neo4j from K semantics or TOML files"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show pairings that would be created without loading",
    )
    parser.add_argument(
        "--toml",
        type=Path,
        help="Load pairings from a TOML manifest file instead of K semantics",
    )
    parser.add_argument(
        "--semantics-root",
        type=Path,
        default=Path("external/c-semantics/semantics"),
        help="Root directory of K semantics files (ignored if --toml is used)",
    )
    args = parser.parse_args()

    all_pairings: list[Pairing] = []
    all_idioms: list[Idiom] = []

    # Load from TOML manifest if specified
    if args.toml:
        if not args.toml.exists():
            print(f"Error: TOML file not found: {args.toml}")
            return

        print(f"Loading pairings from: {args.toml}")
        pairings, idioms = load_pairings_from_toml(args.toml)
        print(f"  Found {len(pairings)} pairings and {len(idioms)} idioms")
        all_pairings.extend(pairings)
        all_idioms.extend(idioms)

    else:
        # Load from K semantics
        from axiom.extractors import KSemanticsExtractor

        semantics_root = args.semantics_root
        if not semantics_root.exists():
            print(f"Error: Semantics root not found: {semantics_root}")
            print("Clone the K-Framework C semantics repository first:")
            print("  git clone https://github.com/kframework/c-semantics external/c-semantics")
            return

        print(f"Extracting pairings from: {semantics_root}")

        c_lib = semantics_root / "c" / "library"
        cpp_lib = semantics_root / "cpp" / "library"

        for lib_path in [c_lib, cpp_lib]:
            if lib_path.exists():
                print(f"\nProcessing: {lib_path}")
                extractor = KSemanticsExtractor(lib_path)
                pairings = extractor.extract_all_pairings()
                print(f"  Found {len(pairings)} pairings")
                all_pairings.extend(pairings)

    if not all_pairings and not all_idioms:
        print("\nNo pairings or idioms found.")
        return

    # For K semantics, we need to resolve placeholder IDs to actual axiom IDs
    # For TOML, the IDs are function names that need to be resolved
    from axiom.graph.loader import Neo4jLoader

    print("\nResolving function names to axiom IDs...")
    try:
        neo4j = Neo4jLoader()
    except Exception as e:
        print(f"Error connecting to Neo4j: {e}")
        print("Make sure Neo4j is running.")
        return

    # Map internal K function names to C function names
    K_TO_C_FUNCTION = {
        "alignedAlloc": "malloc",
    }

    # Build function -> axiom ID mapping
    func_to_axiom: dict[str, str] = {}
    functions_needed = set()

    for p in all_pairings:
        # Extract function name from placeholder ID or use directly
        opener_func = p.opener_id.replace("axiom_for_", "")
        closer_func = p.closer_id.replace("axiom_for_", "")
        # Map K names to C names
        opener_func = K_TO_C_FUNCTION.get(opener_func, opener_func)
        closer_func = K_TO_C_FUNCTION.get(closer_func, closer_func)
        functions_needed.add(opener_func)
        functions_needed.add(closer_func)

    for idiom in all_idioms:
        for participant in idiom.participants:
            func = participant.replace("axiom_for_", "")
            func = K_TO_C_FUNCTION.get(func, func)
            functions_needed.add(func)

    for func in sorted(functions_needed):
        axioms = neo4j.get_axioms_by_function(func)
        if axioms:
            func_to_axiom[func] = axioms[0]["id"]
            print(f"  {func} -> {axioms[0]['id'][:50]}...")
        else:
            print(f"  {func} -> NOT FOUND (will skip)")

    neo4j.close()

    # Update pairings with real axiom IDs and deduplicate
    seen = set()
    unique_pairings = []
    for p in all_pairings:
        opener_func = p.opener_id.replace("axiom_for_", "")
        closer_func = p.closer_id.replace("axiom_for_", "")
        opener_func = K_TO_C_FUNCTION.get(opener_func, opener_func)
        closer_func = K_TO_C_FUNCTION.get(closer_func, closer_func)

        opener_id = func_to_axiom.get(opener_func)
        closer_id = func_to_axiom.get(closer_func)

        if not opener_id or not closer_id:
            continue

        key = (opener_id, closer_id)
        if key not in seen:
            seen.add(key)
            resolved = Pairing(
                opener_id=opener_id,
                closer_id=closer_id,
                required=p.required,
                source=p.source,
                confidence=p.confidence,
                cell=p.cell,
                evidence=p.evidence,
            )
            unique_pairings.append(resolved)

    # Update idioms with resolved axiom IDs
    unique_idioms = []
    for idiom in all_idioms:
        resolved_participants = []
        for participant in idiom.participants:
            func = participant.replace("axiom_for_", "")
            func = K_TO_C_FUNCTION.get(func, func)
            axiom_id = func_to_axiom.get(func)
            if axiom_id:
                resolved_participants.append(axiom_id)

        if resolved_participants:
            unique_idioms.append(
                Idiom(
                    id=idiom.id,
                    name=idiom.name,
                    participants=resolved_participants,
                    template=idiom.template,
                    source=idiom.source,
                )
            )

    print(f"\nTotal unique pairings (with resolved IDs): {len(unique_pairings)}")
    print(f"Total idioms (with resolved participants): {len(unique_idioms)}")

    if args.dry_run:
        print("\n[DRY RUN] Would create the following pairings:\n")
        for p in unique_pairings:
            print(f"  {p.opener_id} --[PAIRS_WITH]--> {p.closer_id}")
            print(f"    Cell: {p.cell or 'N/A'}, Confidence: {p.confidence}")
            print(f"    Evidence: {p.evidence}")
            print()

        if unique_idioms:
            print("\n[DRY RUN] Would create the following idioms:\n")
            for idiom in unique_idioms:
                print(f"  Idiom: {idiom.name}")
                print(f"    Participants: {idiom.participants}")
                print(f"    Template: {idiom.template[:80]}..." if len(idiom.template) > 80 else f"    Template: {idiom.template}")
                print()
        return

    # Load into Neo4j
    from axiom.graph.loader import Neo4jLoader

    print("\nLoading pairings into Neo4j...")
    try:
        with Neo4jLoader() as neo4j:
            neo4j.load_pairings(unique_pairings)
            print(f"Successfully loaded {len(unique_pairings)} pairings")

            if unique_idioms:
                neo4j.load_idioms(unique_idioms)
                print(f"Successfully loaded {len(unique_idioms)} idioms")
    except Exception as e:
        print(f"Error loading pairings: {e}")
        print("Make sure Neo4j is running and axioms are already loaded.")


if __name__ == "__main__":
    main()
