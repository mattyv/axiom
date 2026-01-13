#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Load function pairings into Neo4j from TOML manifest files.

Usage:
    python scripts/load_pairings.py --toml knowledge/pairings/cpp20_stdlib.toml [--dry-run]

The pairings connect existing axiom nodes - no re-extraction of axioms needed.
"""

import argparse
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.models.pairing import Idiom, Pairing


def load_pairings_from_toml(toml_path: Path) -> tuple[list[Pairing], list[Idiom]]:
    """Load pairings and idioms from a TOML manifest file.

    Args:
        toml_path: Path to the TOML file.

    Returns:
        Tuple of (pairings, idioms) loaded from the file.
    """
    pairings, idioms, _ = load_axiom_toml(toml_path)
    return pairings, idioms


def load_axiom_toml(toml_path: Path) -> tuple[list[Pairing], list[Idiom], list]:
    """Load pairings, idioms, and axioms from a .axiom.toml file.

    Args:
        toml_path: Path to the TOML file.

    Returns:
        Tuple of (pairings, idioms, axioms) loaded from the file.
    """
    from axiom.models import Axiom, AxiomType, SourceLocation

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

    # Load axioms (domain knowledge)
    axioms = []
    metadata = data.get("metadata", {})
    layer = metadata.get("layer", "library")

    for a in data.get("axioms", []):
        axiom_type = None
        if a.get("axiom_type"):
            try:
                axiom_type = AxiomType(a["axiom_type"])
            except ValueError:
                pass

        axioms.append(
            Axiom(
                id=a["id"],
                content=a["content"],
                formal_spec=a.get("formal_spec", ""),
                source=SourceLocation(
                    file=a.get("header", ""),
                    module=layer,
                ),
                layer=layer,
                confidence=a.get("confidence", 1.0),
                function=a.get("function"),
                header=a.get("header"),
                signature=a.get("signature"),
                axiom_type=axiom_type,
                on_violation=a.get("on_violation"),
            )
        )

    return pairings, idioms, axioms


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load function pairings into Neo4j from TOML files"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show pairings that would be created without loading",
    )
    parser.add_argument(
        "--toml",
        type=Path,
        required=True,
        help="Load pairings from a TOML manifest file",
    )
    args = parser.parse_args()

    all_pairings: list[Pairing] = []
    all_idioms: list[Idiom] = []

    if not args.toml.exists():
        print(f"Error: TOML file not found: {args.toml}")
        return

    print(f"Loading pairings from: {args.toml}")
    pairings, idioms = load_pairings_from_toml(args.toml)
    print(f"  Found {len(pairings)} pairings and {len(idioms)} idioms")
    all_pairings.extend(pairings)
    all_idioms.extend(idioms)

    if not all_pairings and not all_idioms:
        print("\nNo pairings or idioms found.")
        return

    # Resolve function names to axiom IDs
    from axiom.graph.loader import Neo4jLoader

    print("\nResolving function names to axiom IDs...")
    try:
        neo4j = Neo4jLoader()
    except Exception as e:
        print(f"Error connecting to Neo4j: {e}")
        print("Make sure Neo4j is running.")
        return

    # Build function -> axiom ID mapping
    func_to_axiom: dict[str, str] = {}
    functions_needed = set()

    for p in all_pairings:
        functions_needed.add(p.opener_id)
        functions_needed.add(p.closer_id)

    for idiom in all_idioms:
        for participant in idiom.participants:
            functions_needed.add(participant)

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
        opener_id = func_to_axiom.get(p.opener_id)
        closer_id = func_to_axiom.get(p.closer_id)

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
            axiom_id = func_to_axiom.get(participant)
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
                print(
                    f"    Template: {idiom.template[:80]}..."
                    if len(idiom.template) > 80
                    else f"    Template: {idiom.template}"
                )
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
