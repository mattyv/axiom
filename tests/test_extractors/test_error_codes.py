"""Tests for error codes CSV parser."""

from pathlib import Path

import pytest

from axiom.extractors.error_codes import ErrorCodesParser
from axiom.models import ErrorCode, ErrorType


class TestErrorCodesParser:
    """Tests for ErrorCodesParser."""

    def test_parse_csv_returns_error_codes(self, error_codes_csv: Path) -> None:
        """Parser should return a list of ErrorCode objects."""
        parser = ErrorCodesParser(error_codes_csv)
        error_codes = parser.parse()

        assert isinstance(error_codes, list)
        assert len(error_codes) > 0
        assert all(isinstance(ec, ErrorCode) for ec in error_codes)

    def test_parse_csv_extracts_ub_codes(self, error_codes_csv: Path) -> None:
        """Parser should extract undefined behavior codes."""
        parser = ErrorCodesParser(error_codes_csv)
        error_codes = parser.parse()

        ub_codes = [ec for ec in error_codes if ec.type == ErrorType.UNDEFINED_BEHAVIOR]
        assert len(ub_codes) > 0

        # Check for known UB code from multiplicative.k
        cemx1 = next((ec for ec in ub_codes if ec.internal_code == "CEMX1"), None)
        assert cemx1 is not None
        assert cemx1.code == "UB-CEMX1"
        assert "division" in cemx1.description.lower() or "0" in cemx1.description

    def test_parse_csv_extracts_cv_codes(self, error_codes_csv: Path) -> None:
        """Parser should extract constraint violation codes."""
        parser = ErrorCodesParser(error_codes_csv)
        error_codes = parser.parse()

        cv_codes = [ec for ec in error_codes if ec.type == ErrorType.CONSTRAINT_VIOLATION]
        assert len(cv_codes) > 0

    def test_parse_csv_extracts_impl_codes(self, error_codes_csv: Path) -> None:
        """Parser should extract implementation-defined codes."""
        parser = ErrorCodesParser(error_codes_csv)
        error_codes = parser.parse()

        impl_codes = [ec for ec in error_codes if ec.type == ErrorType.IMPLEMENTATION_DEFINED]
        assert len(impl_codes) > 0

    def test_parse_csv_extracts_c_standard_refs(self, error_codes_csv: Path) -> None:
        """Parser should extract C standard references."""
        parser = ErrorCodesParser(error_codes_csv)
        error_codes = parser.parse()

        # Find a code with known references
        codes_with_refs = [ec for ec in error_codes if ec.c_standard_refs]
        assert len(codes_with_refs) > 0

        # Check format of references (e.g., "6.5.5:5")
        sample = codes_with_refs[0]
        assert all(":" in ref or "." in ref for ref in sample.c_standard_refs)

    def test_parse_csv_handles_internal_code_extraction(self, error_codes_csv: Path) -> None:
        """Parser should correctly extract internal code from full code."""
        parser = ErrorCodesParser(error_codes_csv)
        error_codes = parser.parse()

        for ec in error_codes:
            # Internal code should be the part after the prefix
            assert "-" in ec.code
            prefix, internal = ec.code.split("-", 1)
            assert ec.internal_code == internal

    def test_parse_csv_skips_header_rows(self, error_codes_csv: Path) -> None:
        """Parser should skip header/metadata rows in CSV."""
        parser = ErrorCodesParser(error_codes_csv)
        error_codes = parser.parse()

        # No error code should have empty or template-like values
        for ec in error_codes:
            assert ec.code
            assert ec.internal_code
            assert not ec.code.startswith(",")
            assert "Error_Type" not in ec.code
