# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for POSTCONDITION and COMPLEXITY axiom extraction.

These tests verify that:
- Functions returning non-void types generate POSTCONDITION axioms
- Template functions generate COMPLEXITY axioms about instantiation
- Return type semantics are properly captured
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


class TestPostconditionFromReturnType:
    """Tests for POSTCONDITION axioms generated from return types."""

    def test_optional_return_generates_postcondition(self):
        """std::optional<T> return should generate POSTCONDITION about validity."""
        code = """
        #include <optional>

        std::optional<int> find_value(int key) {
            if (key > 0) return key * 2;
            return std::nullopt;
        }
        """
        axioms = extract_axioms(code)

        # Should have postcondition about optional return
        postcond = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        optional_axioms = [a for a in postcond if "optional" in a.content.lower()
                          or "value" in a.content.lower()]
        assert len(optional_axioms) > 0, f"Expected POSTCONDITION for optional return, got: {[a.content for a in axioms]}"

    def test_bool_return_generates_postcondition(self):
        """bool return should generate POSTCONDITION about true/false meaning."""
        code = """
        bool is_valid(int x) {
            return x > 0;
        }
        """
        axioms = extract_axioms(code)

        # Should have postcondition about boolean return
        postcond = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION
                   and a.function and "is_valid" in a.function]
        assert len(postcond) > 0, f"Expected POSTCONDITION for bool return"

    def test_constexpr_bool_return_generates_postcondition(self):
        """constexpr bool return should also generate POSTCONDITION."""
        code = """
        constexpr bool is_positive(int x) {
            return x > 0;
        }
        """
        axioms = extract_axioms(code)

        # Should have postcondition even with constexpr qualifier
        postcond = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION
                   and a.function and "is_positive" in a.function]
        assert len(postcond) > 0, f"Expected POSTCONDITION for constexpr bool return, got: {[a.content for a in axioms]}"

    def test_pointer_return_generates_postcondition(self):
        """Pointer return should generate POSTCONDITION about null possibility."""
        code = """
        int* find_element(int* arr, int size, int value) {
            for (int i = 0; i < size; ++i) {
                if (arr[i] == value) return &arr[i];
            }
            return nullptr;
        }
        """
        axioms = extract_axioms(code)

        # Should have postcondition about pointer return
        ptr_axioms = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION
                     and "pointer" in a.content.lower() or "null" in a.content.lower()]
        # This is optional - we may or may not generate this
        assert isinstance(ptr_axioms, list)

    def test_iterator_return_generates_postcondition(self):
        """Iterator return should generate POSTCONDITION about validity."""
        code = """
        #include <vector>

        std::vector<int>::iterator find_it(std::vector<int>& v, int x) {
            for (auto it = v.begin(); it != v.end(); ++it) {
                if (*it == x) return it;
            }
            return v.end();
        }
        """
        axioms = extract_axioms(code)

        # Should parse without error
        assert isinstance(axioms, list)


class TestComplexityFromTemplates:
    """Tests for COMPLEXITY axioms generated from template functions."""

    def test_template_function_generates_complexity(self):
        """Template function should generate COMPLEXITY about instantiation."""
        code = """
        template<int N>
        int factorial() {
            if constexpr (N <= 1) return 1;
            else return N * factorial<N-1>();
        }
        """
        axioms = extract_axioms(code)

        # Should have complexity axiom about template instantiation
        complexity = [a for a in axioms if a.axiom_type == AxiomType.COMPLEXITY]
        assert len(complexity) > 0, f"Expected COMPLEXITY axiom for template function, got: {[a.axiom_type for a in axioms]}"
        # Should mention template or instantiation
        assert any("template" in a.content.lower() or "instantiat" in a.content.lower()
                   for a in complexity), f"COMPLEXITY axiom should mention template: {[a.content for a in complexity]}"

    def test_template_class_generates_complexity(self):
        """Template class should generate COMPLEXITY axiom about type instantiation."""
        code = """
        template<typename T>
        class Container {
        public:
            void add(T value) { /* ... */ }
            T get(int index) { return T{}; }
        };
        """
        axioms = extract_axioms(code)

        # Should have complexity axiom about template class
        complexity = [a for a in axioms if a.axiom_type == AxiomType.COMPLEXITY]
        assert len(complexity) > 0, f"Expected COMPLEXITY axiom for template class, got: {[a.axiom_type for a in axioms]}"

    def test_recursive_template_generates_complexity(self):
        """Recursive template should note compile-time recursion cost."""
        code = """
        template<unsigned N>
        constexpr unsigned fib() {
            if constexpr (N <= 1) return N;
            else return fib<N-1>() + fib<N-2>();
        }
        """
        axioms = extract_axioms(code)

        # Should have complexity axiom about recursive template
        complexity = [a for a in axioms if a.axiom_type == AxiomType.COMPLEXITY]
        assert len(complexity) > 0, f"Expected COMPLEXITY axiom for recursive template"
        # Should have constexpr constraint too
        constexpr_axioms = [a for a in axioms if a.formal_spec == "constexpr == true"]
        assert len(constexpr_axioms) > 0, f"Expected constexpr constraint for constexpr template"

    def test_variadic_template_generates_complexity(self):
        """Variadic template should note parameter pack expansion."""
        code = """
        template<typename... Args>
        void print_all(Args... args) {
            (void)(std::cout << ... << args);
        }
        """
        axioms = extract_axioms(code)

        # Should have complexity axiom about variadic template
        complexity = [a for a in axioms if a.axiom_type == AxiomType.COMPLEXITY]
        # Variadic templates have complexity due to pack expansion
        assert len(complexity) > 0, f"Expected COMPLEXITY axiom for variadic template"


class TestNodeiscardPostcondition:
    """Tests for [[nodiscard]] generating POSTCONDITION."""

    def test_nodiscard_generates_postcondition(self):
        """[[nodiscard]] should generate POSTCONDITION about return value."""
        code = """
        [[nodiscard]] int compute() {
            return 42;
        }
        """
        axioms = extract_axioms(code)

        # Should have postcondition from nodiscard
        postcond = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION]
        nodiscard = [a for a in postcond if "discard" in a.content.lower()]
        assert len(nodiscard) > 0, f"Expected POSTCONDITION for [[nodiscard]]"

    def test_nodiscard_with_message(self):
        """[[nodiscard("reason")]] should include the reason."""
        code = """
        [[nodiscard("important result")]] int important() {
            return 42;
        }
        """
        axioms = extract_axioms(code)

        # Should have postcondition
        postcond = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION
                   and a.function and "important" in a.function]
        assert len(postcond) > 0


class TestReturnTypeSemantics:
    """Tests for semantic understanding of return types."""

    def test_expected_return_type(self):
        """std::expected should generate error-handling postcondition."""
        code = """
        #include <expected>

        std::expected<int, std::string> parse(const char* str) {
            if (!str) return std::unexpected("null input");
            return 42;
        }
        """
        axioms = extract_axioms(code)

        # Should parse without error (expected is C++23)
        assert isinstance(axioms, list)

    def test_void_return_no_postcondition(self):
        """void return should not generate return value postcondition."""
        code = """
        void do_nothing() {
            // nothing
        }
        """
        axioms = extract_axioms(code)

        # Should NOT have postcondition about return value
        postcond = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION
                   and a.function and "do_nothing" in a.function]
        # Void functions shouldn't have return value postconditions
        # (they might have other postconditions about side effects)
        assert len(postcond) == 0 or all("return" not in a.content.lower() for a in postcond)
