#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Bootstrap error codes from K semantics.

This script extracts C11 error codes (undefined behavior catalog) from the
K-framework c-semantics repository. K axioms are no longer extracted as they
are primarily internal evaluation guards, not useful for code validation.

The error codes are high-quality: 248 unique undefined behaviors with direct
C11 standard references (e.g., 6.5.8:5, J.2:1 item 53).
"""

import argparse
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from axiom.extractors.error_codes import ErrorCodesParser
from axiom.models import AxiomCollection


def main() -> int:
    """Extract C11 error codes from K semantics."""
    parser = argparse.ArgumentParser(
        description="Extract C11 error codes from K-framework c-semantics"
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
        default=Path("knowledge/foundations/c11_error_codes.toml"),
        help="Output TOML file for extracted error codes",
    )

    args = parser.parse_args()

    # Validate paths
    k_root = args.k_semantics
    if not k_root.exists():
        print(f"Error: K semantics directory not found: {k_root}")
        print("Did you run: git submodule update --init?")
        return 1

    error_codes_csv = k_root / "examples" / "c" / "error-codes" / "Error_Codes.csv"
    if not error_codes_csv.exists():
        print(f"Error: Error codes CSV not found: {error_codes_csv}")
        return 1

    print("=" * 60)
    print("C11 Error Codes Extraction")
    print("=" * 60)
    print(f"Source: {error_codes_csv}")
    print(f"Output: {args.output}")
    print()

    # Parse error codes CSV
    print("Parsing error codes CSV...")
    error_parser = ErrorCodesParser(error_codes_csv)
    error_codes = error_parser.parse()
    print(f"  - Parsed {len(error_codes)} error codes")

    # Create collection with error codes only (no axioms)
    collection = AxiomCollection(
        source="kframework/c-semantics",
        description="C11 undefined behavior catalog extracted from K-framework C semantics",
        axioms=[],
        error_codes=error_codes,
    )

    # Save to TOML
    print(f"\nSaving to TOML ({args.output})...")
    collection.save_toml(args.output)
    print(f"  - Saved {len(error_codes)} error codes to {args.output}")

    # Summary
    print("\n" + "=" * 60)
    print("Extraction Complete!")
    print("=" * 60)
    print(f"  Total error codes: {len(error_codes)}")

    # Show sample error codes
    print("\nSample error codes:")
    for ec in error_codes[:3]:
        print(f"  - {ec.code}: {ec.description[:60]}...")
        if ec.c_standard_refs:
            print(f"    Refs: {', '.join(ec.c_standard_refs[:3])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
