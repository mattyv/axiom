# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Parser for Error_Codes.csv from c-semantics."""

import csv
from pathlib import Path
from typing import List, Optional

from axiom.models import ErrorCode, ErrorType


class ErrorCodesParser:
    """Parse the Error_Codes.csv file from c-semantics."""

    TYPE_MAP = {
        "Undefined Behavior": ErrorType.UNDEFINED_BEHAVIOR,
        "Constraint Violation": ErrorType.CONSTRAINT_VIOLATION,
        "Implementation Defined Behavior": ErrorType.IMPLEMENTATION_DEFINED,
        "Unspecified Behavior": ErrorType.UNSPECIFIED,
    }

    def __init__(self, csv_path: Path) -> None:
        """Initialize parser with path to CSV file.

        Args:
            csv_path: Path to Error_Codes.csv
        """
        self.csv_path = Path(csv_path)

    def parse(self) -> List[ErrorCode]:
        """Parse CSV and return list of ErrorCode objects.

        Returns:
            List of parsed ErrorCode objects.
        """
        error_codes: List[ErrorCode] = []

        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)

            for row in reader:
                error_code = self._parse_row(row)
                if error_code:
                    error_codes.append(error_code)

        return error_codes

    def _parse_row(self, row: List[str]) -> Optional[ErrorCode]:
        """Parse a single CSV row.

        Args:
            row: CSV row as list of strings.

        Returns:
            ErrorCode if row is valid, None otherwise.
        """
        if len(row) < 4:
            return None

        code = row[0].strip()

        # Skip header and metadata rows
        if not code or not self._is_valid_error_code(code):
            return None

        description = row[1].strip() if len(row) > 1 else ""
        refs = row[2].strip() if len(row) > 2 else ""
        error_type_str = row[3].strip() if len(row) > 3 else ""

        # Extract internal code (e.g., "CEMX1" from "UB-CEMX1")
        internal_code = self._extract_internal_code(code)

        # Parse C standard references
        c_refs = self._parse_references(refs)

        # Map error type
        error_type = self.TYPE_MAP.get(error_type_str, ErrorType.UNDEFINED_BEHAVIOR)

        return ErrorCode(
            code=code,
            internal_code=internal_code,
            type=error_type,
            description=description,
            c_standard_refs=c_refs,
        )

    def _is_valid_error_code(self, code: str) -> bool:
        """Check if code looks like a valid error code.

        Args:
            code: Potential error code string.

        Returns:
            True if code matches expected pattern.
        """
        valid_prefixes = ("UB-", "CV-", "USP-", "IMPL-", "SE-", "L-", "IMPLUB-")
        return code.startswith(valid_prefixes)

    def _extract_internal_code(self, code: str) -> str:
        """Extract internal code from full error code.

        Args:
            code: Full error code like "UB-CEMX1".

        Returns:
            Internal code like "CEMX1".
        """
        if "-" in code:
            return code.split("-", 1)[1]
        return code

    def _parse_references(self, refs: str) -> List[str]:
        """Parse C standard references from string.

        Args:
            refs: Comma-separated references like "6.5.5:5, J.2:1 item 45".

        Returns:
            List of individual references.
        """
        if not refs:
            return []

        # Split on comma and clean up
        return [r.strip() for r in refs.split(",") if r.strip()]
