"""Pytest fixtures for Axiom tests."""

from pathlib import Path

import pytest


@pytest.fixture
def c_semantics_root() -> Path:
    """Path to the c-semantics submodule."""
    return Path(__file__).parent.parent / "external" / "c-semantics"


@pytest.fixture
def error_codes_csv(c_semantics_root: Path) -> Path:
    """Path to the Error_Codes.csv file."""
    return c_semantics_root / "examples" / "c" / "error-codes" / "Error_Codes.csv"


@pytest.fixture
def multiplicative_k(c_semantics_root: Path) -> Path:
    """Path to the multiplicative.k file (good test case)."""
    return c_semantics_root / "semantics" / "c" / "language" / "common" / "expr" / "multiplicative.k"
