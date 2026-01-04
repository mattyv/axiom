#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Enrich existing axiom TOML files with on_violation and inferred axioms.

This script reads existing TOML files and enriches them using LLM to:
- Add on_violation descriptions for preconditions
- Infer missing POSTCONDITION axioms
- Enhance semantic content

Usage:
    # Enrich a single file (in-place)
    python scripts/enrich_axioms.py knowledge/libraries/mylib.toml

    # Enrich to a new file
    python scripts/enrich_axioms.py input.toml --output enriched.toml

    # Use a specific model
    python scripts/enrich_axioms.py input.toml --model opus
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.extractors.enricher import enrich_axioms
from axiom.models import AxiomCollection

logger = logging.getLogger(__name__)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Enrich axiom TOML files with on_violation and inferred axioms",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input TOML file to enrich",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output TOML file (default: overwrite input)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="sonnet",
        help="Model for enrichment (default: sonnet)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be enriched without making changes",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        return 1

    try:
        # Load existing axioms
        logger.info(f"Loading axioms from {args.input}...")
        collection = AxiomCollection.load_toml(args.input)
        original_count = len(collection.axioms)
        logger.info(f"Loaded {original_count} axioms")

        # Count axioms without on_violation
        missing_violation = sum(1 for a in collection.axioms if not a.on_violation)
        logger.info(f"Axioms without on_violation: {missing_violation}")

        if args.dry_run:
            logger.info("Dry run - would enrich the following axioms:")
            for a in collection.axioms[:10]:
                logger.info(f"  - {a.id}: {a.content[:50]}...")
            if original_count > 10:
                logger.info(f"  ... and {original_count - 10} more")
            return 0

        # Enrich
        logger.info(f"Enriching axioms with model {args.model}...")
        enriched = enrich_axioms(
            list(collection.axioms),
            use_llm=True,
            model=args.model,
        )
        collection.axioms = enriched

        new_count = len(collection.axioms) - original_count
        if new_count > 0:
            logger.info(f"Inferred {new_count} new axioms")

        # Count axioms now with on_violation
        with_violation = sum(1 for a in collection.axioms if a.on_violation)
        logger.info(f"Axioms with on_violation after enrichment: {with_violation}")

        # Save
        output_path = args.output or args.input
        collection.save_toml(output_path)
        logger.info(f"Saved {len(collection.axioms)} axioms to {output_path}")

        return 0

    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
