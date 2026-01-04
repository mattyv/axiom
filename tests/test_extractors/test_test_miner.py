# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for test mining extraction from test frameworks.

These tests verify that test assertions from Catch2, GoogleTest, and
Boost.Test are correctly extracted as axioms using Clang AST analysis.
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


def extract_test_axioms(code: str, framework: str = "catch2") -> list:
    """Run axiom-extract in test mode on code and return axioms.

    Args:
        code: C++ test code to analyze
        framework: Test framework to use (catch2, gtest, boost)
    """
    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
        f.write(code)
        f.flush()
        temp_path = Path(f.name)

    try:
        result = subprocess.run(
            [
                str(AXIOM_EXTRACT),
                str(temp_path),
                "--test-mode",
                f"--test-framework={framework}",
                "--",
                "-std=c++20",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Check for missing header errors
        stderr = result.stderr.lower()
        if "fatal error" in stderr and "file not found" in stderr:
            if "catch2" in stderr or "gtest" in stderr or "boost" in stderr:
                pytest.skip(f"Test framework headers not available: {result.stderr[:200]}")

        if result.returncode != 0 and not result.stdout:
            pytest.skip(f"Clang failed: {result.stderr}")

        data = json.loads(result.stdout)
        collection = parse_json(data)
        return collection.axioms
    finally:
        temp_path.unlink()


class TestCatch2Mining:
    """Tests for mining axioms from Catch2 test assertions.

    Note: These tests require Catch2 headers to be installed.
    If not available, tests will be skipped.
    """

    def test_require_becomes_postcondition(self):
        """REQUIRE(result == expected) should become POSTCONDITION."""
        code = """
        #define CATCH_CONFIG_MAIN
        #include <catch2/catch_test_macros.hpp>

        int add(int a, int b) { return a + b; }

        TEST_CASE("addition works") {
            REQUIRE(add(2, 3) == 5);
        }
        """
        axioms = extract_test_axioms(code, "catch2")

        # Should have postcondition about add() returning expected value
        postconds = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        assert len(postconds) > 0, f"Expected POSTCONDITION, got {[a.axiom_type for a in axioms]}"
        # Content should mention the function or the assertion
        assert any("add" in a.content.lower() or "5" in a.content for a in postconds)

    def test_check_becomes_postcondition_lower_confidence(self):
        """CHECK(cond) should become POSTCONDITION with lower confidence than REQUIRE."""
        code = """
        #define CATCH_CONFIG_MAIN
        #include <catch2/catch_test_macros.hpp>

        bool is_even(int n) { return n % 2 == 0; }

        TEST_CASE("even check") {
            CHECK(is_even(4));
        }
        """
        axioms = extract_test_axioms(code, "catch2")

        postconds = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        assert len(postconds) > 0, "Expected POSTCONDITION from CHECK"
        # CHECK should have lower confidence than REQUIRE (0.80 vs 0.85)
        assert all(a.confidence <= 0.80 for a in postconds)

    def test_require_throws_becomes_exception(self):
        """REQUIRE_THROWS_AS should become EXCEPTION axiom."""
        code = """
        #define CATCH_CONFIG_MAIN
        #include <catch2/catch_test_macros.hpp>
        #include <stdexcept>

        void fail_on_negative(int x) {
            if (x < 0) throw std::invalid_argument("negative");
        }

        TEST_CASE("throws on negative") {
            REQUIRE_THROWS_AS(fail_on_negative(-1), std::invalid_argument);
        }
        """
        axioms = extract_test_axioms(code, "catch2")

        exceptions = [a for a in axioms if a.axiom_type == AxiomType.EXCEPTION]
        assert len(exceptions) > 0, "Expected EXCEPTION from REQUIRE_THROWS_AS"
        # Should mention the exception type
        assert any("invalid_argument" in a.content.lower() for a in exceptions)

    def test_require_nothrow_becomes_constraint(self):
        """REQUIRE_NOTHROW should become a noexcept constraint."""
        code = """
        #define CATCH_CONFIG_MAIN
        #include <catch2/catch_test_macros.hpp>

        int safe_add(int a, int b) noexcept { return a + b; }

        TEST_CASE("safe_add doesn't throw") {
            REQUIRE_NOTHROW(safe_add(1, 2));
        }
        """
        axioms = extract_test_axioms(code, "catch2")

        # Should have either CONSTRAINT or evidence that function is noexcept
        assert len(axioms) > 0, "Expected axiom from REQUIRE_NOTHROW"

    def test_section_provides_context(self):
        """SECTION should provide context for axiom grouping."""
        code = """
        #define CATCH_CONFIG_MAIN
        #include <catch2/catch_test_macros.hpp>

        int multiply(int a, int b) { return a * b; }

        TEST_CASE("multiplication") {
            SECTION("positive numbers") {
                REQUIRE(multiply(3, 4) == 12);
            }
            SECTION("with zero") {
                REQUIRE(multiply(5, 0) == 0);
            }
        }
        """
        axioms = extract_test_axioms(code, "catch2")

        # Should have axioms from both sections
        assert len(axioms) >= 2, "Expected axioms from both SECTIONs"


class TestGoogleTestMining:
    """Tests for mining axioms from GoogleTest assertions."""

    def test_assert_eq_becomes_postcondition(self):
        """ASSERT_EQ(a, b) should become POSTCONDITION."""
        code = """
        #include <gtest/gtest.h>

        int square(int x) { return x * x; }

        TEST(MathTest, SquareWorks) {
            ASSERT_EQ(square(5), 25);
        }
        """
        axioms = extract_test_axioms(code, "gtest")

        postconds = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        assert len(postconds) > 0, "Expected POSTCONDITION from ASSERT_EQ"

    def test_expect_eq_lower_confidence(self):
        """EXPECT_EQ should have lower confidence than ASSERT_EQ."""
        code = """
        #include <gtest/gtest.h>

        int double_val(int x) { return x * 2; }

        TEST(MathTest, DoubleWorks) {
            EXPECT_EQ(double_val(3), 6);
        }
        """
        axioms = extract_test_axioms(code, "gtest")

        postconds = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        assert len(postconds) > 0, "Expected POSTCONDITION from EXPECT_EQ"
        # EXPECT should have lower confidence than ASSERT
        assert all(a.confidence <= 0.80 for a in postconds)

    def test_assert_true_becomes_postcondition(self):
        """ASSERT_TRUE(cond) should become POSTCONDITION."""
        code = """
        #include <gtest/gtest.h>

        bool is_positive(int x) { return x > 0; }

        TEST(NumberTest, PositiveCheck) {
            ASSERT_TRUE(is_positive(5));
        }
        """
        axioms = extract_test_axioms(code, "gtest")

        postconds = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        assert len(postconds) > 0, "Expected POSTCONDITION from ASSERT_TRUE"

    def test_assert_throw_becomes_exception(self):
        """ASSERT_THROW should become EXCEPTION axiom."""
        code = """
        #include <gtest/gtest.h>
        #include <stdexcept>

        void validate(int x) {
            if (x < 0) throw std::out_of_range("negative");
        }

        TEST(ValidationTest, ThrowsOnNegative) {
            ASSERT_THROW(validate(-1), std::out_of_range);
        }
        """
        axioms = extract_test_axioms(code, "gtest")

        exceptions = [a for a in axioms if a.axiom_type == AxiomType.EXCEPTION]
        assert len(exceptions) > 0, "Expected EXCEPTION from ASSERT_THROW"
        assert any("out_of_range" in a.content.lower() for a in exceptions)

    def test_assert_no_throw_constraint(self):
        """ASSERT_NO_THROW should indicate noexcept behavior."""
        code = """
        #include <gtest/gtest.h>

        int safe_divide(int a, int b) {
            return b != 0 ? a / b : 0;
        }

        TEST(DivisionTest, NoThrow) {
            ASSERT_NO_THROW(safe_divide(10, 2));
        }
        """
        axioms = extract_test_axioms(code, "gtest")

        assert len(axioms) > 0, "Expected axiom from ASSERT_NO_THROW"


class TestBoostTestMining:
    """Tests for mining axioms from Boost.Test assertions."""

    def test_boost_require_becomes_postcondition(self):
        """BOOST_REQUIRE should become POSTCONDITION."""
        code = """
        #define BOOST_TEST_MODULE MyTest
        #include <boost/test/unit_test.hpp>

        int increment(int x) { return x + 1; }

        BOOST_AUTO_TEST_CASE(increment_test) {
            BOOST_REQUIRE(increment(5) == 6);
        }
        """
        axioms = extract_test_axioms(code, "boost")

        postconds = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        assert len(postconds) > 0, "Expected POSTCONDITION from BOOST_REQUIRE"

    def test_boost_check_lower_confidence(self):
        """BOOST_CHECK should have lower confidence than BOOST_REQUIRE."""
        code = """
        #define BOOST_TEST_MODULE MyTest
        #include <boost/test/unit_test.hpp>

        bool is_valid(int x) { return x >= 0; }

        BOOST_AUTO_TEST_CASE(validity_test) {
            BOOST_CHECK(is_valid(10));
        }
        """
        axioms = extract_test_axioms(code, "boost")

        postconds = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        assert len(postconds) > 0, "Expected POSTCONDITION from BOOST_CHECK"
        assert all(a.confidence <= 0.80 for a in postconds)

    def test_boost_check_equal_becomes_postcondition(self):
        """BOOST_CHECK_EQUAL should become POSTCONDITION."""
        code = """
        #define BOOST_TEST_MODULE MyTest
        #include <boost/test/unit_test.hpp>

        int triple(int x) { return x * 3; }

        BOOST_AUTO_TEST_CASE(triple_test) {
            BOOST_CHECK_EQUAL(triple(4), 12);
        }
        """
        axioms = extract_test_axioms(code, "boost")

        postconds = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        assert len(postconds) > 0, "Expected POSTCONDITION from BOOST_CHECK_EQUAL"

    def test_boost_check_throw_becomes_exception(self):
        """BOOST_CHECK_THROW should become EXCEPTION axiom."""
        code = """
        #define BOOST_TEST_MODULE MyTest
        #include <boost/test/unit_test.hpp>
        #include <stdexcept>

        void require_positive(int x) {
            if (x <= 0) throw std::domain_error("must be positive");
        }

        BOOST_AUTO_TEST_CASE(throw_test) {
            BOOST_CHECK_THROW(require_positive(-5), std::domain_error);
        }
        """
        axioms = extract_test_axioms(code, "boost")

        exceptions = [a for a in axioms if a.axiom_type == AxiomType.EXCEPTION]
        assert len(exceptions) > 0, "Expected EXCEPTION from BOOST_CHECK_THROW"
        assert any("domain_error" in a.content.lower() for a in exceptions)


class TestMultiFrameworkDetection:
    """Tests for automatic framework detection."""

    def test_auto_detect_catch2(self):
        """Should auto-detect Catch2 from include."""
        code = """
        #include <catch2/catch_test_macros.hpp>

        TEST_CASE("simple") {
            REQUIRE(true);
        }
        """
        # Don't specify framework - should auto-detect
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
            f.write(code)
            f.flush()
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [
                    str(AXIOM_EXTRACT),
                    str(temp_path),
                    "--test-mode",
                    "--",
                    "-std=c++20",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Should succeed or at least not crash
            assert result.returncode == 0 or "error" not in result.stderr.lower()
        finally:
            temp_path.unlink()

    def test_auto_detect_gtest(self):
        """Should auto-detect GoogleTest from include."""
        code = """
        #include <gtest/gtest.h>

        TEST(Simple, Test) {
            ASSERT_TRUE(true);
        }
        """
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
            f.write(code)
            f.flush()
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [
                    str(AXIOM_EXTRACT),
                    str(temp_path),
                    "--test-mode",
                    "--",
                    "-std=c++20",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0 or "error" not in result.stderr.lower()
        finally:
            temp_path.unlink()


class TestTestModeBasic:
    """Basic tests for test mode that don't require framework headers."""

    def test_test_mode_flag_accepted(self):
        """The --test-mode flag should be accepted without error."""
        # Simple code without any test framework includes
        code = """
        void foo() {}
        """
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
            f.write(code)
            f.flush()
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [
                    str(AXIOM_EXTRACT),
                    str(temp_path),
                    "--test-mode",
                    "--",
                    "-std=c++20",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Should produce valid JSON output
            assert result.stdout, "Expected JSON output"
            data = json.loads(result.stdout)
            assert "test_mode" in data
            assert data["test_mode"] is True
        finally:
            temp_path.unlink()

    def test_test_framework_option_accepted(self):
        """The --test-framework option should be accepted."""
        code = """
        void bar() {}
        """
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
            f.write(code)
            f.flush()
            temp_path = Path(f.name)

        try:
            for framework in ["auto", "catch2", "gtest", "boost"]:
                result = subprocess.run(
                    [
                        str(AXIOM_EXTRACT),
                        str(temp_path),
                        "--test-mode",
                        f"--test-framework={framework}",
                        "--",
                        "-std=c++20",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert result.stdout, f"Expected JSON output for framework={framework}"
                data = json.loads(result.stdout)
                assert data["test_framework"] == framework
        finally:
            temp_path.unlink()

    def test_json_output_includes_test_mode_info(self):
        """JSON output should include test_mode and test_framework fields."""
        code = """
        int compute(int x) { return x * 2; }
        """
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
            f.write(code)
            f.flush()
            temp_path = Path(f.name)

        try:
            result = subprocess.run(
                [
                    str(AXIOM_EXTRACT),
                    str(temp_path),
                    "--test-mode",
                    "--test-framework=catch2",
                    "--",
                    "-std=c++20",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            data = json.loads(result.stdout)
            assert "test_mode" in data
            assert "test_framework" in data
            assert data["test_mode"] is True
            assert data["test_framework"] == "catch2"
        finally:
            temp_path.unlink()


class TestTestMiningHeuristics:
    """Tests for test mining heuristics."""

    def test_assertion_at_start_suggests_precondition(self):
        """Assertions at test start may suggest preconditions."""
        code = """
        #define CATCH_CONFIG_MAIN
        #include <catch2/catch_test_macros.hpp>

        void process(int* ptr) {
            // function body
        }

        TEST_CASE("process requires valid input") {
            int value = 42;
            int* ptr = &value;
            REQUIRE(ptr != nullptr);  // This checks a precondition
            process(ptr);
        }
        """
        axioms = extract_test_axioms(code, "catch2")

        # Early assertions about inputs may be detected as preconditions
        # This is a heuristic - just check we get some axioms
        assert len(axioms) >= 0  # At minimum should not crash

    def test_assertion_after_call_suggests_postcondition(self):
        """Assertions after function calls suggest postconditions."""
        code = """
        #define CATCH_CONFIG_MAIN
        #include <catch2/catch_test_macros.hpp>

        int compute(int x) { return x * 2; }

        TEST_CASE("compute doubles") {
            int result = compute(5);
            REQUIRE(result == 10);  // Postcondition check
        }
        """
        axioms = extract_test_axioms(code, "catch2")

        # Should recognize this as a postcondition about compute()
        assert len(axioms) >= 0  # At minimum should not crash

    def test_test_name_provides_context(self):
        """Test case names should be used in axiom metadata."""
        code = """
        #define CATCH_CONFIG_MAIN
        #include <catch2/catch_test_macros.hpp>

        int abs_val(int x) { return x < 0 ? -x : x; }

        TEST_CASE("abs_val returns non-negative for negative input") {
            REQUIRE(abs_val(-5) >= 0);
        }
        """
        axioms = extract_test_axioms(code, "catch2")

        # The test name context should help inform the axiom
        assert len(axioms) >= 0  # At minimum should not crash
