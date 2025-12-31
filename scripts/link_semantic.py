#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""LLM-assisted semantic linking of library axioms to foundations.

This script uses LLM analysis to link library axioms to their direct
foundation dependencies based on semantic understanding, not just type
signatures.

Unlike link_depends_on.py (regex-based type extraction), this script:
1. Groups axioms by function for batched LLM calls
2. Uses semantic search to find candidate foundation axioms
3. Has LLM identify DIRECT dependencies (not transitive)
4. Merges with existing depends_on (adds to, doesn't replace)

Usage:
    python scripts/link_semantic.py ilp_for_axioms.toml
    python scripts/link_semantic.py ilp_for_axioms.toml --dry-run
    python scripts/link_semantic.py ilp_for_axioms.toml --force
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.extractors.semantic_linker import (
    LINKING_SYSTEM_PROMPT,
    build_linking_prompt,
    group_by_function,
    merge_depends_on,
    parse_llm_response,
    search_foundations,
    validate_candidate_ids,
)
from axiom.models import AxiomCollection
from axiom.vectors import LanceDBLoader


def get_candidate_foundations(
    func_name: str,
    axioms: list,
    lance: LanceDBLoader,
    limit: int = 30,
) -> list[dict]:
    """Use semantic search to find candidate foundation axioms.

    Searches using multiple query strategies to find relevant foundations:
    1. Function signature (contains C++ type info)
    2. Content from axioms (semantic meaning)
    3. Generic C++ terms extracted from content

    Args:
        func_name: Function/macro name.
        axioms: Library axioms to find candidates for.
        lance: LanceDB loader instance.
        limit: Maximum candidates to return.

    Returns:
        List of candidate foundation axiom dicts.
    """
    all_candidates = []
    seen_ids = set()

    # Strategy 1: Search by signature (most specific C++ terms)
    for axiom in axioms[:3]:
        if axiom.signature:
            results = search_foundations(axiom.signature, lance, limit=10)
            for r in results:
                if r["id"] not in seen_ids:
                    all_candidates.append(r)
                    seen_ids.add(r["id"])

    # Strategy 2: Search by content with C++ keywords added
    content = " ".join(a.content for a in axioms[:3])
    # Add generic C++ terms to improve matching
    cpp_terms = "C++ lambda template parameter reference capture"
    query = f"{content} {cpp_terms}"
    results = search_foundations(query, lance, limit=20)
    for r in results:
        if r["id"] not in seen_ids:
            all_candidates.append(r)
            seen_ids.add(r["id"])

    # Strategy 3: Search for key C++ concepts mentioned in content
    key_concepts = []
    content_lower = content.lower()
    if "lambda" in content_lower:
        key_concepts.append("lambda expression capture closure")
    if "template" in content_lower or "parameter" in content_lower:
        key_concepts.append("template parameter instantiation")
    if "reference" in content_lower or "capture" in content_lower:
        key_concepts.append("reference capture lifetime")
    if "range" in content_lower or "iterator" in content_lower or "loop" in content_lower:
        key_concepts.append("range-based for loop iterator")

    for concept in key_concepts:
        results = search_foundations(concept, lance, limit=10)
        for r in results:
            if r["id"] not in seen_ids:
                all_candidates.append(r)
                seen_ids.add(r["id"])

    return all_candidates[:limit]


def link_function_group(
    func_name: str,
    axioms: list,
    candidates: list[dict],
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Call LLM to link axioms to their direct foundation dependencies.

    Args:
        func_name: Function/macro name being analyzed.
        axioms: Library axioms for this function.
        candidates: Candidate foundation axioms.
        dry_run: If True, don't call LLM, just show what would happen.

    Returns:
        Dict mapping axiom IDs to lists of foundation axiom IDs.
    """
    prompt = build_linking_prompt(func_name, axioms, candidates)

    if dry_run:
        print(f"    [DRY RUN] Would send {len(prompt)} char prompt")
        return {}

    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--system-prompt", LINKING_SYSTEM_PROMPT,
                "--dangerously-skip-permissions",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print(f"    Error: LLM timed out for {func_name}")
        return {}
    except FileNotFoundError:
        print("    Error: claude CLI not found")
        return {}

    if result.returncode != 0:
        print(f"    Error: Claude CLI failed: {result.stderr[:100]}")
        return {}

    # Parse response
    raw_links = parse_llm_response(result.stdout)

    # Validate that returned IDs exist in candidates
    validated = {}
    for axiom_id, links in raw_links.items():
        validated[axiom_id] = validate_candidate_ids(links, candidates)

    return validated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LLM-assisted semantic linking of library axioms to foundations"
    )
    parser.add_argument(
        "toml_file",
        type=Path,
        help="Path to TOML file with library axioms to link",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be linked without modifying files or calling LLM",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-link all axioms (even those with existing foundation links)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("./data/lancedb"),
        help="Path to LanceDB database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of function groups to process (for testing)",
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

    # Count current foundation dependencies
    foundation_deps = 0
    for a in collection.axioms:
        if a.depends_on:
            for dep in a.depends_on:
                # Check if any deps are from foundation layers
                if any(layer in dep for layer in ["c11_", "cpp_", "cpp20_"]):
                    foundation_deps += 1
                    break

    print(f"  With foundation deps: {foundation_deps}/{total}")

    # Group by function
    print("\nGrouping axioms by function...")
    groups = group_by_function(collection.axioms)
    print(f"  Found {len(groups)} function groups")

    # Show group sizes
    group_sizes = sorted([(k, len(v)) for k, v in groups.items()], key=lambda x: -x[1])
    print("  Largest groups:")
    for name, size in group_sizes[:5]:
        print(f"    {name}: {size} axioms")

    # Connect to LanceDB
    print(f"\nConnecting to LanceDB at {args.db_path}...")
    try:
        lance = LanceDBLoader(str(args.db_path))
    except Exception as e:
        print(f"Error: Could not connect to LanceDB: {e}")
        return 1

    # Process each function group
    print("\nProcessing function groups...")
    total_linked = 0
    groups_processed = 0

    group_items = list(groups.items())
    if args.limit:
        group_items = group_items[:args.limit]

    for func_name, func_axioms in group_items:
        groups_processed += 1
        print(f"\n  [{groups_processed}/{len(group_items)}] {func_name} ({len(func_axioms)} axioms)")

        # Get candidate foundations via semantic search
        candidates = get_candidate_foundations(func_name, func_axioms, lance)
        print(f"    Found {len(candidates)} candidate foundations")

        if not candidates:
            print("    Skipping - no candidates found")
            continue

        # Call LLM to identify direct dependencies
        links = link_function_group(func_name, func_axioms, candidates, dry_run=args.dry_run)

        if args.dry_run:
            continue

        # Merge links into axioms
        for axiom in func_axioms:
            new_links = links.get(axiom.id, [])
            if new_links:
                axiom.depends_on = merge_depends_on(axiom.depends_on, new_links)
                total_linked += 1
                print(f"    Linked {axiom.id}: +{len(new_links)} deps")

    if args.dry_run:
        print(f"\n[DRY RUN] Would process {len(group_items)} groups")
        return 0

    # Save updated collection
    print(f"\nSaving to {args.toml_file}...")
    collection.save_toml(args.toml_file)

    # Report final stats
    foundation_deps = 0
    for a in collection.axioms:
        if a.depends_on:
            for dep in a.depends_on:
                if any(layer in dep for layer in ["c11_", "cpp_", "cpp20_"]):
                    foundation_deps += 1
                    break

    print(f"\nFinal: {foundation_deps}/{total} axioms with foundation deps")
    print(f"Total axioms updated: {total_linked}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
