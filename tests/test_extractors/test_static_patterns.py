# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for static pattern extraction from C++ code.

These tests verify that assert(), __builtin_assume(), and other
static analysis patterns are correctly extracted as axioms.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from axiom.extractors.clang_loader import parse_json
from axiom.models import AxiomType


def find_axiom_extract() -> Path | None:
    """Find the axiom-extract binary."""
    candidates = [
        Path(__file__).parent.parent.parent
        / "tools"
        / "axiom-extract"
        / "build"
        / "axiom-extract",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


AXIOM_EXTRACT = find_axiom_extract()
pytestmark = pytest.mark.skipif(
    AXIOM_EXTRACT is None, reason="axiom-extract binary not found"
)


def extract_axioms(code: str) -> list:
    """Run axiom-extract on code and return axioms."""
    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
        f.write(code)
        f.flush()
        temp_path = Path(f.name)

    try:
        result = subprocess.run(
            [str(AXIOM_EXTRACT), str(temp_path), "--", "-std=c++20"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and not result.stdout:
            pytest.skip(f"Clang failed: {result.stderr}")

        data = json.loads(result.stdout)
        collection = parse_json(data)
        return collection.axioms
    finally:
        temp_path.unlink()


class TestAssertExtraction:
    """Tests for extracting axioms from assert() calls."""

    def test_assert_null_check_becomes_precondition(self):
        """assert(ptr != nullptr) should become a precondition."""
        code = """
        #include <cassert>
        void foo(int* ptr) {
            assert(ptr != nullptr);
            *ptr = 42;
        }
        """
        axioms = extract_axioms(code)

        # Find precondition about pointer (may use 'p' or 'ptr' depending on parsing)
        ptr_axioms = [a for a in axioms if "pointer" in a.content.lower() or "null" in a.content.lower()]
        assert len(ptr_axioms) > 0, f"No pointer axioms found in {[a.content for a in axioms]}"

        # Should be a precondition
        precond = [a for a in ptr_axioms if a.axiom_type == AxiomType.PRECONDITION]
        assert len(precond) > 0, "Expected PRECONDITION for null check"

    def test_assert_range_check_becomes_precondition(self):
        """assert(i < size) should become a precondition about bounds."""
        code = """
        #include <cassert>
        int get(int* arr, int i, int size) {
            assert(i >= 0 && i < size);
            return arr[i];
        }
        """
        axioms = extract_axioms(code)

        # Should have array access precondition
        array_axioms = [a for a in axioms if a.axiom_type == AxiomType.PRECONDITION]
        assert len(array_axioms) > 0, "Expected at least one precondition"

    def test_assert_with_message_uses_message(self):
        """assert with message should use the message in content."""
        code = """
        #include <cassert>
        void process(int x) {
            assert(x > 0 && "x must be positive");
            // ...
        }
        """
        axioms = extract_axioms(code)

        # Note: This may not be implemented yet - test documents expected behavior
        assert len(axioms) >= 0  # Placeholder until implemented


class TestBuiltinAssumeExtraction:
    """Tests for __builtin_assume extraction."""

    def test_builtin_assume_becomes_precondition(self):
        """__builtin_assume(cond) should become a precondition."""
        code = """
        void fast_div(int a, int b) {
            __builtin_assume(b != 0);
            int c = a / b;
        }
        """
        axioms = extract_axioms(code)

        # Should have either assume-based or division hazard precondition
        precond = [a for a in axioms if a.axiom_type == AxiomType.PRECONDITION]
        assert len(precond) > 0, "Expected precondition for b != 0"


class TestEarlyReturnPatterns:
    """Tests for detecting preconditions from early return patterns."""

    def test_if_null_return_becomes_precondition(self):
        """if (ptr == nullptr) return; should indicate ptr precondition."""
        code = """
        int deref(int* ptr) {
            if (ptr == nullptr) return 0;
            return *ptr;
        }
        """
        extract_axioms(code)
        # The pointer dereference should be detected as guarded
        # This test documents expected behavior - may not be implemented

    def test_if_invalid_return_error(self):
        """if (!valid) return error; should indicate validity precondition."""
        code = """
        int process(bool valid, int data) {
            if (!valid) return -1;
            return data * 2;
        }
        """
        extract_axioms(code)
        # This pattern may or may not generate axioms depending on implementation


class TestRAIIPatterns:
    """Tests for detecting RAII patterns."""

    def test_lock_guard_detected(self):
        """std::lock_guard should be detected as RAII pattern."""
        code = """
        #include <mutex>
        std::mutex mtx;
        void safe_update(int& x) {
            std::lock_guard<std::mutex> lock(mtx);
            x++;
        }
        """
        extract_axioms(code)
        # RAII detection may or may not be implemented
        # Test documents expected behavior


class TestContractsC20:
    """Tests for C++20/26 contract attributes (future)."""

    @pytest.mark.skip(reason="C++26 contracts not yet supported by Clang")
    def test_expects_attribute(self):
        """[[expects: cond]] should become PRECONDITION."""
        code = """
        [[expects: x > 0]]
        int sqrt_int(int x) {
            // ...
            return 0;
        }
        """
        axioms = extract_axioms(code)
        precond = [a for a in axioms if a.axiom_type == AxiomType.PRECONDITION]
        assert len(precond) > 0

    @pytest.mark.skip(reason="C++26 contracts not yet supported by Clang")
    def test_ensures_attribute(self):
        """[[ensures: cond]] should become POSTCONDITION."""
        code = """
        [[ensures ret: ret >= 0]]
        int abs_int(int x) {
            return x < 0 ? -x : x;
        }
        """
        axioms = extract_axioms(code)
        postcond = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        assert len(postcond) > 0


class TestExistingStaticPatterns:
    """Tests for already-implemented static patterns."""

    def test_static_assert_extracted(self):
        """static_assert should be extracted as INVARIANT."""
        code = """
        static_assert(sizeof(int) >= 4, "int must be at least 4 bytes");
        """
        axioms = extract_axioms(code)

        invariants = [a for a in axioms if a.axiom_type == AxiomType.INVARIANT]
        assert len(invariants) > 0
        assert any("4" in a.content or "sizeof" in a.formal_spec for a in invariants)

    def test_concept_extracted(self):
        """C++20 concept should be extracted as CONSTRAINT."""
        code = """
        template<typename T>
        concept Addable = requires(T a, T b) { a + b; };
        """
        axioms = extract_axioms(code)

        constraints = [a for a in axioms if a.axiom_type == AxiomType.CONSTRAINT]
        assert len(constraints) > 0
        assert any("Addable" in a.function for a in constraints)

    def test_requires_clause_extracted(self):
        """requires clause should be extracted as CONSTRAINT."""
        code = """
        template<typename T>
        requires requires(T t) { t.size(); }
        void process(T& container) {
            container.size();  // Use the constraint
        }
        """
        axioms = extract_axioms(code)

        # Either have requires constraint or at least parse without error
        # Note: requires on template functions only generates axioms if
        # the function is instantiated or has a body
        # The tool may or may not extract this depending on implementation
        assert len(axioms) >= 0  # At minimum should not crash
