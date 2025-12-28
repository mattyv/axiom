#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Ingest axioms from C++ draft standard (eel.is/c++draft).

This script fetches sections from the C++ draft standard and uses
Claude to extract axioms (preconditions, effects, complexity, etc.).

Usage:
    # Extract axioms from a single section
    python scripts/ingest_stdlib.py util.smartptr.shared

    # Extract from multiple sections
    python scripts/ingest_stdlib.py optional variant any expected

    # Extract with custom output
    python scripts/ingest_stdlib.py memory -o memory_axioms.toml

    # List available top-level sections
    python scripts/ingest_stdlib.py --list

    # Resume a review session
    python scripts/ingest_stdlib.py --review <session_id>
"""

import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.ingestion.reviewer import ReviewItem, ReviewSessionManager
from axiom.models import Axiom, AxiomType, SourceLocation


# Base URL for C++ draft standard
DRAFT_BASE_URL = "https://eel.is/c++draft"

# Common stdlib sections to extract
STDLIB_SECTIONS = [
    # Utilities
    "util.smartptr.shared",
    "optional",
    "variant",
    "any",
    "expected",
    # Containers
    "vector",
    "map",
    "set",
    "unord.map",
    "unord.set",
    # Algorithms
    "alg.sorting",
    "alg.modifying.operations",
    "alg.nonmodifying",
    # Strings
    "string.classes",
    "string.view",
    # Memory
    "allocator.requirements",
    "unique.ptr",
    # Concurrency
    "thread.mutex",
    "thread.condition",
    "futures",
    # Ranges (C++20)
    "range.access",
    "range.req",
    # Format (C++20)
    "format",
]


def fetch_section(section: str) -> Optional[str]:
    """Fetch a section from eel.is/c++draft.

    Args:
        section: Section identifier (e.g., "optional", "util.smartptr.shared")

    Returns:
        HTML content of the section, or None on error.
    """
    import urllib.request
    import urllib.error

    url = f"{DRAFT_BASE_URL}/{section}"

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        print(f"  Error fetching {url}: HTTP {e.code}")
        return None
    except urllib.error.URLError as e:
        print(f"  Error fetching {url}: {e.reason}")
        return None


def html_to_text(html: str) -> str:
    """Convert HTML to readable text, preserving structure.

    Args:
        html: Raw HTML content.

    Returns:
        Plain text with preserved structure.
    """
    # Remove script and style tags
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # Convert headers to markdown-style
    html = re.sub(r'<h1[^>]*>(.*?)</h1>', r'\n# \1\n', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n## \1\n', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n### \1\n', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<h4[^>]*>(.*?)</h4>', r'\n#### \1\n', html, flags=re.DOTALL | re.IGNORECASE)

    # Convert paragraphs and divs to newlines
    html = re.sub(r'<p[^>]*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</p>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<div[^>]*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</div>', '\n', html, flags=re.IGNORECASE)

    # Convert list items
    html = re.sub(r'<li[^>]*>', '\n- ', html, flags=re.IGNORECASE)
    html = re.sub(r'</li>', '', html, flags=re.IGNORECASE)

    # Convert code blocks
    html = re.sub(r'<pre[^>]*>(.*?)</pre>', r'\n```\n\1\n```\n', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', html, flags=re.DOTALL | re.IGNORECASE)

    # Convert breaks
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)

    # Remove remaining HTML tags
    html = re.sub(r'<[^>]+>', '', html)

    # Decode HTML entities
    html = html.replace('&nbsp;', ' ')
    html = html.replace('&lt;', '<')
    html = html.replace('&gt;', '>')
    html = html.replace('&amp;', '&')
    html = html.replace('&quot;', '"')
    html = html.replace('&#39;', "'")

    # Clean up whitespace
    html = re.sub(r'\n\s*\n\s*\n', '\n\n', html)
    html = re.sub(r'[ \t]+', ' ', html)

    return html.strip()


def generate_axiom_id(section: str, content: str) -> str:
    """Generate a unique axiom ID.

    Args:
        section: Section identifier.
        content: Axiom content.

    Returns:
        Unique ID string.
    """
    # Create hash from content
    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
    # Clean section name
    clean_section = re.sub(r'[^a-zA-Z0-9]', '_', section)
    return f"cpp_stdlib_{clean_section}_{content_hash}"


def extract_axioms_with_claude(section: str, content: str, verbose: bool = False) -> List[Axiom]:
    """Use Claude CLI to extract axioms from spec content.

    Args:
        section: Section identifier for metadata.
        content: Text content of the spec section.
        verbose: Print debug info.

    Returns:
        List of extracted Axiom objects.
    """
    prompt = f"""You are extracting formal axioms from the C++ standard library specification.

Section: {section}
Source: eel.is/c++draft/{section}

Extract axioms for each function/class described. For each axiom, identify:
- axiom_type: One of: precondition, postcondition, effect, invariant, constraint, complexity, anti_pattern, exception
- function: The function/method name (e.g., "push_back", "operator[]")
- header: The header file (e.g., "<vector>", "<optional>")
- content: Human-readable description of the axiom
- formal_spec: Formal/semi-formal specification (use C++ syntax or mathematical notation)
- on_violation: What happens if violated (e.g., "undefined behavior", "throws bad_optional_access")
- confidence: 0.0-1.0 based on how clearly the spec states this

Focus on:
1. PRECONDITION: What must be true before calling (e.g., "container must not be empty")
2. POSTCONDITION: What is guaranteed after the call
3. EFFECT: Observable behavior/side effects
4. COMPLEXITY: Big-O guarantees (e.g., "O(1) amortized", "O(n)")
5. EXCEPTION: What exceptions can be thrown and when
6. CONSTRAINT: Type requirements, concepts
7. ANTI_PATTERN: Common misuse patterns to avoid

Return JSON array:
```json
[
  {{
    "axiom_type": "precondition",
    "function": "front",
    "header": "<vector>",
    "content": "Container must not be empty when calling front()",
    "formal_spec": "requires: !empty()",
    "on_violation": "undefined behavior",
    "confidence": 1.0
  }},
  ...
]
```

IMPORTANT:
- Only extract axioms that are explicitly stated or clearly implied by the spec
- Include the exact section reference where possible
- For complexity, use standard Big-O notation
- Be precise about undefined behavior vs exceptions vs implementation-defined

Spec content:
{content[:15000]}
"""

    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            if verbose:
                print(f"  Claude CLI error: {result.stderr}")
            return []

        # Parse the response
        response = result.stdout.strip()

        # Try to find JSON array in response
        json_match = re.search(r'\[[\s\S]*\]', response)
        if not json_match:
            if verbose:
                print(f"  No JSON array found in response")
                print(f"  Response preview: {response[:500]}")
            return []

        try:
            axiom_data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            if verbose:
                print(f"  JSON decode error: {e}")
                print(f"  Matched text preview: {json_match.group()[:500]}")
            return []

        axioms = []
        for item in axiom_data:
            if not item.get("content"):
                continue

            axiom_type = None
            type_str = item.get("axiom_type", "").lower()
            if type_str:
                try:
                    axiom_type = AxiomType(type_str)
                except ValueError:
                    pass

            axiom = Axiom(
                id=generate_axiom_id(section, item.get("content", "")),
                content=item.get("content", ""),
                formal_spec=item.get("formal_spec", ""),
                source=SourceLocation(
                    file=f"eel.is/c++draft/{section}",
                    module=section,
                ),
                layer="cpp_stdlib",
                confidence=float(item.get("confidence", 0.9)),
                function=item.get("function"),
                header=item.get("header"),
                axiom_type=axiom_type,
                on_violation=item.get("on_violation"),
                c_standard_refs=[f"[{section}]"],
            )
            axioms.append(axiom)

        return axioms

    except subprocess.TimeoutExpired:
        print(f"  Timeout extracting from {section}")
        return []
    except json.JSONDecodeError as e:
        if verbose:
            print(f"  JSON parse error: {e}")
        return []
    except Exception as e:
        if verbose:
            print(f"  Error: {e}")
        return []


def run_review(manager: ReviewSessionManager, session_id: str):
    """Run the interactive review for a session."""
    from scripts.review_axioms import review_session

    session = manager.load_session(session_id)
    if session is None:
        print(f"Session '{session_id}' not found.")
        sys.exit(1)

    review_session(session, manager)


def main():
    parser = argparse.ArgumentParser(
        description="Extract axioms from C++ draft standard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "sections",
        nargs="*",
        help="Section identifiers to extract (e.g., optional, vector, util.smartptr.shared)",
    )
    parser.add_argument(
        "-o", "--output",
        default="knowledge/foundations/cpp20_stdlib.toml",
        help="Output TOML file (default: knowledge/foundations/cpp20_stdlib.toml)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List common stdlib sections",
    )
    parser.add_argument(
        "--review",
        metavar="SESSION_ID",
        help="Resume reviewing a session",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List all review sessions",
    )
    parser.add_argument(
        "--export",
        metavar="SESSION_ID",
        help="Export approved axioms from a session",
    )
    parser.add_argument(
        "--storage-dir",
        default="./data/reviews",
        help="Directory for review sessions",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "-j", "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Process N sections in parallel (default: 1)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Extract from all predefined stdlib sections",
    )

    args = parser.parse_args()

    # Initialize review manager
    manager = ReviewSessionManager(storage_dir=args.storage_dir)

    # Handle review commands
    if args.list_sessions:
        sessions = manager.list_sessions()
        if not sessions:
            print("No review sessions found.")
        else:
            print(f"\n{'ID':<25} {'Created':<20} {'Progress':<12} {'Source'}")
            print("-" * 80)
            for s in sessions:
                progress = f"{s['reviewed']}/{s['total_items']}"
                source = s["source_file"][:30] if s["source_file"] else "N/A"
                created = s["created_at"][:19]
                print(f"{s['session_id']:<25} {created:<20} {progress:<12} {source}")
        return

    if args.review:
        run_review(manager, args.review)
        return

    if args.export:
        session = manager.load_session(args.export)
        if session is None:
            print(f"Session '{args.export}' not found.")
            sys.exit(1)
        count = manager.export_approved(session, args.output)
        print(f"Exported {count} axioms to {args.output}")
        return

    # List sections mode
    if args.list:
        print("\nCommon C++ stdlib sections:")
        print("-" * 40)
        for section in STDLIB_SECTIONS:
            print(f"  {section}")
        print(f"\nUsage: python scripts/ingest_stdlib.py <section> [section...]")
        print(f"URL format: https://eel.is/c++draft/<section>")
        return

    # Determine sections to process
    sections = args.sections
    if args.all:
        sections = STDLIB_SECTIONS
    if not sections:
        parser.print_help()
        sys.exit(1)

    # Process a single section (used for parallel processing)
    def process_section(section: str) -> Tuple[str, List[Axiom]]:
        """Fetch and extract axioms from a section."""
        html = fetch_section(section)
        if not html:
            return (section, [])

        text = html_to_text(html)
        axioms = extract_axioms_with_claude(section, text, args.verbose)
        return (section, axioms)

    # Extract from each section
    all_axioms = []

    if args.parallel > 1:
        print(f"\nProcessing {len(sections)} sections with {args.parallel} workers...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
            future_to_section = {executor.submit(process_section, s): s for s in sections}
            for future in concurrent.futures.as_completed(future_to_section):
                section = future_to_section[future]
                try:
                    _, axioms = future.result()
                    print(f"  {section}: {len(axioms)} axioms")
                    all_axioms.extend(axioms)
                except Exception as e:
                    print(f"  {section}: ERROR - {e}")
    else:
        for section in sections:
            print(f"\nProcessing: {section}")
            print(f"  Fetching from {DRAFT_BASE_URL}/{section}...")

            html = fetch_section(section)
            if not html:
                continue

            # Convert to text
            text = html_to_text(html)
            if args.verbose:
                print(f"  Extracted {len(text)} chars of text")

            # Extract axioms
            print(f"  Extracting axioms with Claude...")
            axioms = extract_axioms_with_claude(section, text, args.verbose)

            if axioms:
                print(f"  Found {len(axioms)} axioms")
                all_axioms.extend(axioms)
            else:
                print(f"  No axioms extracted")

    if not all_axioms:
        print("\nNo axioms extracted.")
        return

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Extraction Summary")
    print(f"{'=' * 60}")
    print(f"Sections processed: {len(sections)}")
    print(f"Total axioms:       {len(all_axioms)}")

    # Save directly to TOML
    from axiom.models import AxiomCollection

    collection = AxiomCollection(
        source=f"eel.is/c++draft",
        axioms=all_axioms,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(collection.to_toml())

    print(f"\nSaved {len(all_axioms)} axioms to {args.output}")

    # Also create review session for optional review
    items = [ReviewItem(axiom=axiom) for axiom in all_axioms]
    session = manager.create_session(
        items=items,
        source_file=f"eel.is/c++draft ({', '.join(sections[:3])}{'...' if len(sections) > 3 else ''})",
    )

    print(f"Review session created: {session.session_id}")
    print(f"\nTo review axioms:")
    print(f"  python scripts/ingest_stdlib.py --review {session.session_id}")


if __name__ == "__main__":
    main()
