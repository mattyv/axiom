#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Extract C++20 axioms from eel.is/c++draft using Claude CLI.

Usage:
    # Extract a single section:
    python scripts/extract_cpp20.py --section basic.life

    # Extract all high-signal language sections:
    python scripts/extract_cpp20.py --batch-language

    # List available sections:
    python scripts/extract_cpp20.py --list
"""

import argparse
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.extractors.prompts import (
    HIGH_SIGNAL_LIBRARY_SECTIONS,
    HIGH_SIGNAL_SECTIONS,
    SYSTEM_PROMPT,
    generate_extraction_prompt,
)
from axiom.models import AxiomCollection
from axiom.vectors import LanceDBLoader

LANGUAGE_OUTPUT_FILE = Path("knowledge/foundations/cpp20_language.toml")
LIBRARY_OUTPUT_FILE = Path("knowledge/foundations/cpp20_stdlib.toml")


class HTMLToText(HTMLParser):
    """Convert HTML to plain text."""

    def __init__(self):
        super().__init__()
        self.text = []
        self.in_pre = False
        self.skip_tags = {"script", "style", "nav", "header", "footer"}
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.skip_depth += 1
        elif tag == "pre":
            self.in_pre = True
        elif tag == "p":
            self.text.append("\n\n")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.text.append("\n\n## ")
        elif tag == "li":
            self.text.append("\n- ")

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag == "pre":
            self.in_pre = False

    def handle_data(self, data):
        if self.skip_depth == 0:
            self.text.append(" ".join(data.split()) if not self.in_pre else data)

    def get_text(self) -> str:
        return "".join(self.text).strip()


def fetch_section(section: str) -> str:
    """Fetch content from eel.is/c++draft."""
    url = f"https://eel.is/c++draft/{section}"
    print(f"  Fetching {url}...")

    with urlopen(url, timeout=30) as response:
        html = response.read().decode("utf-8")

    parser = HTMLToText()
    parser.feed(html)
    text = parser.get_text()

    # Limit size for context
    if len(text) > 40000:
        text = text[:40000] + "\n\n[Truncated]"

    return text


def get_existing_axioms(section: str) -> list[dict]:
    """Get existing axioms for dedup context."""
    try:
        lance = LanceDBLoader(str(Path("./data/lancedb")))
        return lance.search(section.replace(".", " "), limit=15)
    except Exception:
        return []


def extract_section(section: str, output_file: Path, dry_run: bool = False) -> int:
    """Extract axioms from a section using Claude CLI."""
    print(f"\n{'=' * 60}")
    print(f"Section: {section}")
    print(f"Output: {output_file}")
    print("=" * 60)

    # Fetch and prepare
    html_content = fetch_section(section)
    print(f"  Content: {len(html_content)} chars")

    existing = get_existing_axioms(section)
    print(f"  Existing axioms: {len(existing)}")

    # Build prompt
    timestamp = datetime.now(UTC).isoformat()
    prompt = generate_extraction_prompt(
        section_ref=section,
        html_content=html_content,
        existing_axioms=existing,
        timestamp=timestamp,
    )

    if dry_run:
        print(f"\n[DRY RUN] Would send {len(prompt)} char prompt to Claude")
        return 0

    # Call Claude CLI
    print("  Calling Claude CLI...")
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--system-prompt", SYSTEM_PROMPT,
                "--dangerously-skip-permissions",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("  Error: Claude CLI timed out")
        return 1
    except FileNotFoundError:
        print("  Error: claude CLI not found")
        return 1

    if result.returncode != 0:
        print(f"  Error: Claude CLI failed: {result.stderr}")
        return 1

    toml_output = result.stdout.strip()

    # Clean markdown code blocks (start and end)
    lines = toml_output.split("\n")
    lines = [line for line in lines if not line.strip().startswith("```")]
    toml_output = "\n".join(lines)

    # Strip any preamble before TOML (Claude sometimes adds text before)
    if "version = " in toml_output:
        idx = toml_output.find("version = ")
        if idx > 0:
            toml_output = toml_output[idx:]

    # Validate TOML
    try:
        data = tomllib.loads(toml_output)
    except Exception as e:
        print(f"  Error: Invalid TOML - {e}")
        # Save raw output for debugging
        debug_file = Path(f"/tmp/cpp20_{section.replace('.', '_')}_raw.txt")
        debug_file.write_text(toml_output)
        print(f"  Raw output saved to: {debug_file}")
        return 1

    if "axioms" not in data or not data["axioms"]:
        print("  Warning: No axioms extracted")
        return 0

    # Parse collection
    try:
        collection = AxiomCollection.load_toml_string(toml_output)
    except Exception as e:
        print(f"  Error parsing: {e}")
        return 1

    print(f"  Extracted: {len(collection.axioms)} axioms")

    # Merge with existing
    if output_file.exists():
        existing_col = AxiomCollection.load_toml(output_file)
        existing_ids = {a.id for a in existing_col.axioms}
        new_axioms = [a for a in collection.axioms if a.id not in existing_ids]
        existing_col.axioms.extend(new_axioms)
        existing_col.save_toml(output_file)
        print(f"  Added: {len(new_axioms)} new axioms (total: {len(existing_col.axioms)})")
    else:
        collection.source = "eel.is/c++draft"
        collection.save_toml(output_file)
        print(f"  Created: {output_file}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract C++20 axioms using Claude CLI")
    parser.add_argument("--section", help="Section to extract (e.g., 'basic.life')")
    parser.add_argument("--batch-language", action="store_true", help="Extract all language sections")
    parser.add_argument("--batch-library", action="store_true", help="Extract all library sections")
    parser.add_argument("--list", action="store_true", help="List sections")
    parser.add_argument("--dry-run", action="store_true", help="Don't call Claude, just show what would happen")

    args = parser.parse_args()

    if args.list:
        print("LANGUAGE sections:")
        for s in HIGH_SIGNAL_SECTIONS:
            print(f"  {s}")
        print("\nLIBRARY sections:")
        for s in HIGH_SIGNAL_LIBRARY_SECTIONS:
            print(f"  {s}")
        return 0

    if args.section:
        # Determine output file based on section type
        is_library = args.section in HIGH_SIGNAL_LIBRARY_SECTIONS
        output_file = LIBRARY_OUTPUT_FILE if is_library else LANGUAGE_OUTPUT_FILE
        return extract_section(args.section, output_file, args.dry_run)

    if args.batch_language:
        failed = 0
        for section in HIGH_SIGNAL_SECTIONS:
            if extract_section(section, LANGUAGE_OUTPUT_FILE, args.dry_run) != 0:
                failed += 1
        print(f"\nDone. {len(HIGH_SIGNAL_SECTIONS) - failed}/{len(HIGH_SIGNAL_SECTIONS)} succeeded")
        return 0 if failed == 0 else 1

    if args.batch_library:
        failed = 0
        for section in HIGH_SIGNAL_LIBRARY_SECTIONS:
            if extract_section(section, LIBRARY_OUTPUT_FILE, args.dry_run) != 0:
                failed += 1
        print(f"\nDone. {len(HIGH_SIGNAL_LIBRARY_SECTIONS) - failed}/{len(HIGH_SIGNAL_LIBRARY_SECTIONS)} succeeded")
        return 0 if failed == 0 else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
