#!/usr/bin/env python3
"""Link library axioms to foundation axioms by analyzing content.

This script analyzes existing axioms and populates the depends_on field
by finding semantically related foundation axioms.

Usage:
    # Analyze and show proposed links (dry run)
    python scripts/link_axioms.py --dry-run

    # Apply links to the database
    python scripts/link_axioms.py --apply

    # Link a specific axiom by ID
    python scripts/link_axioms.py --axiom-id "ilp_break_context_requirement"
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.vectors import LanceDBLoader


# Keywords that indicate dependencies between axioms
DEPENDENCY_PATTERNS = [
    # Variable/symbol dependencies
    (r"requires?\s+(\w+)\s+(?:to be|in scope|variable|must)", "scope_dependency"),
    (r"(\w+)\s+must\s+(?:be|have|exist)", "requirement"),
    (r"must\s+(?:be\s+)?(?:used\s+)?(?:within|inside)\s+(\w+)", "context_dependency"),
    (r"access\s+to\s+(\w+)", "access_dependency"),
    (r"(\w+)\s+(?:variable|parameter)\s+(?:must|in scope)", "variable_dependency"),
    # Type dependencies
    (r"(\w+)\s+must\s+be\s+a\s+(?:valid\s+)?(\w+)", "type_requirement"),
    # Macro/function dependencies
    (r"requires?\s+(\w+)\s+macro", "macro_dependency"),
    (r"provided\s+by\s+(\w+)", "provided_by"),
]


def extract_dependencies_from_content(content: str) -> list[str]:
    """Extract potential dependency keywords from axiom content."""
    keywords = []
    content_lower = content.lower()

    for pattern, dep_type in DEPENDENCY_PATTERNS:
        matches = re.findall(pattern, content_lower)
        for match in matches:
            if isinstance(match, tuple):
                keywords.extend(match)
            else:
                keywords.append(match)

    # Also extract identifiers that look like they might be defined elsewhere
    # (e.g., __ilp_ctrl, ILP_FOR)
    identifiers = re.findall(r'\b(__\w+|\b[A-Z][A-Z_0-9]+)\b', content)
    keywords.extend(identifiers)

    return list(set(keywords))


def find_foundation_axioms(
    lance: LanceDBLoader,
    keywords: list[str],
    source_axiom_id: str,
    source_content: str,
) -> list[dict]:
    """Find foundation axioms related to the given keywords."""
    # Use dict to track best match for each axiom ID
    candidates_by_id: dict[str, dict] = {}

    # Determine if source axiom is a "requires" type
    source_lower = source_content.lower()
    is_requires = any(w in source_lower for w in ["requires", "must be", "must have", "needs", "access to"])

    for keyword in keywords:
        # Search strategies: direct keyword search first, then semantic variations
        search_queries = [
            keyword,  # Direct search for the keyword
            f"{keyword} provides",
            f"{keyword} parameter",
            f"provides {keyword}",
            f"macro {keyword}",
        ]

        for query in search_queries:
            results = lance.search(query, limit=10)

            for r in results:
                axiom_id = r.get("id", "")
                if axiom_id == source_axiom_id:
                    continue

                content = r.get("content", "")
                content_lower = content.lower()

                # Check if this axiom is from a foundation layer
                layer = r.get("layer", "")
                is_foundation = layer in {
                    "c11_core", "c11_stdlib",
                    "cpp_core", "cpp_stdlib",
                    "cpp20_language", "cpp20_stdlib",
                }

                # Check if content mentions providing/defining something
                is_provider = any(word in content_lower for word in [
                    "provides", "defines", "creates", "introduces",
                    "declares", "establishes",
                ])

                # Check if keyword appears in this axiom's content
                keyword_in_content = keyword.lower() in content_lower

                # For "requires X" axioms, prefer "provides X" axioms
                complements_source = is_requires and is_provider

                if is_foundation or is_provider or keyword_in_content:
                    candidate = {
                        "id": axiom_id,
                        "content": content,
                        "layer": layer,
                        "function": r.get("function", ""),
                        "is_foundation": is_foundation,
                        "is_provider": is_provider,
                        "keyword_match": keyword,
                        "keyword_in_content": keyword_in_content,
                        "complements_source": complements_source,
                    }

                    # Keep the version with the best match characteristics
                    if axiom_id in candidates_by_id:
                        existing = candidates_by_id[axiom_id]
                        # Prefer provider matches and complement matches
                        if candidate["is_provider"] and not existing["is_provider"]:
                            candidates_by_id[axiom_id] = candidate
                        elif candidate["complements_source"] and not existing["complements_source"]:
                            candidates_by_id[axiom_id] = candidate
                    else:
                        candidates_by_id[axiom_id] = candidate

    return list(candidates_by_id.values())


def analyze_axiom(lance: LanceDBLoader, axiom: dict) -> list[str]:
    """Analyze an axiom and return suggested depends_on IDs."""
    content = axiom.get("content", "")
    axiom_id = axiom.get("id", "")

    # Extract dependency keywords
    keywords = extract_dependencies_from_content(content)

    if not keywords:
        return []

    # Find foundation axioms
    candidates = find_foundation_axioms(lance, keywords, axiom_id, content)

    # Score and filter candidates
    scored = []
    for c in candidates:
        score = 0

        # Prefer foundation axioms
        if c.get("is_foundation"):
            score += 2

        # Prefer axioms that are providers (strongly!)
        if c.get("is_provider"):
            score += 4

        # Prefer axioms where keyword is in content
        if c.get("keyword_in_content"):
            score += 3

        # Prefer axioms that complement source (requires/provides pair) - highest priority
        if c.get("complements_source"):
            score += 5

        # Prefer axioms about different functions (cross-linking)
        # But not the same axiom type (avoid linking to self-similar axioms)
        if c.get("function") != axiom.get("function"):
            score += 1

        scored.append((score, c))

    # Sort by score and return top matches
    scored.sort(key=lambda x: x[0], reverse=True)

    return [c["id"] for score, c in scored[:3] if score > 1]


def main():
    parser = argparse.ArgumentParser(description="Link library axioms to foundations")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show proposed links without applying",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply links to the database",
    )
    parser.add_argument(
        "--axiom-id",
        help="Analyze a specific axiom by ID",
    )
    parser.add_argument(
        "--lancedb-path",
        default="./data/lancedb",
        help="Path to LanceDB database",
    )
    parser.add_argument(
        "--layer",
        default="library",
        help="Layer to analyze (default: library)",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.apply and not args.axiom_id:
        parser.error("Specify --dry-run, --apply, or --axiom-id")

    lance = LanceDBLoader(args.lancedb_path)

    # Get axioms to analyze
    if args.axiom_id:
        # Search for specific axiom
        results = lance.search(args.axiom_id, limit=1)
        if not results:
            print(f"Axiom not found: {args.axiom_id}")
            return 1
        axioms = [r for r in results if r.get("id") == args.axiom_id]
        if not axioms:
            print(f"Axiom not found: {args.axiom_id}")
            return 1
    else:
        # Get all library axioms
        results = lance.search("library axiom", limit=500)
        axioms = [r for r in results if r.get("layer") == args.layer]

    print(f"Analyzing {len(axioms)} axioms from layer '{args.layer}'...")
    print()

    links_found = 0
    for axiom in axioms:
        axiom_id = axiom.get("id", "unknown")
        existing_deps = axiom.get("depends_on", [])

        if existing_deps:
            continue  # Skip axioms that already have dependencies

        suggested = analyze_axiom(lance, axiom)

        if suggested:
            links_found += 1
            print(f"Axiom: {axiom_id}")
            print(f"  Content: {axiom.get('content', '')[:80]}...")
            print(f"  Suggested depends_on: {suggested}")
            print()

            if args.apply:
                success = lance.update_depends_on(axiom_id, suggested)
                if success:
                    print(f"  ✓ Updated depends_on in LanceDB")
                else:
                    print(f"  ✗ Failed to update in LanceDB")

    print(f"\nFound {links_found} axioms that could be linked.")

    if args.dry_run:
        print("\nRun with --apply to update the database.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
