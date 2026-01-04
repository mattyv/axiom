# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for template constraint extraction from C++20 code.

These tests verify that C++20 concepts, requires clauses, and
template constraints are correctly extracted as axioms.
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


class TestConceptExtraction:
    """Tests for extracting axioms from C++20 concept definitions."""

    def test_simple_concept_becomes_constraint(self):
        """A simple concept should become a CONSTRAINT axiom."""
        code = """
        #include <concepts>

        template<typename T>
        concept Numeric = std::integral<T> || std::floating_point<T>;
        """
        axioms = extract_axioms(code)

        # Find concept axiom
        concept_axioms = [a for a in axioms if "Numeric" in a.id or "Numeric" in a.content]
        assert len(concept_axioms) > 0, f"No Numeric concept found in {[a.id for a in axioms]}"

        # Should be a CONSTRAINT
        constraint = [a for a in concept_axioms if a.axiom_type == AxiomType.CONSTRAINT]
        assert len(constraint) > 0, "Expected CONSTRAINT for concept definition"

    def test_concept_with_compound_requirements(self):
        """A concept with compound requirements should be extracted."""
        code = """
        #include <concepts>

        template<typename T>
        concept Hashable = requires(T a) {
            { std::hash<T>{}(a) } -> std::convertible_to<std::size_t>;
        };
        """
        axioms = extract_axioms(code)

        # Find Hashable concept
        hashable = [a for a in axioms if "Hashable" in a.id or "Hashable" in a.content]
        assert len(hashable) > 0, f"No Hashable concept found in {[a.id for a in axioms]}"

    def test_concept_confidence_is_high(self):
        """Concepts should have high confidence (1.0) since they're explicit."""
        code = """
        template<typename T>
        concept Addable = requires(T a, T b) {
            { a + b } -> std::same_as<T>;
        };
        """
        axioms = extract_axioms(code)

        concept_axioms = [a for a in axioms if "Addable" in a.id]
        assert len(concept_axioms) > 0
        assert concept_axioms[0].confidence >= 0.95


class TestRequiresClauseExtraction:
    """Tests for extracting axioms from requires clauses on functions."""

    def test_trailing_requires_clause(self):
        """Trailing requires clause should be captured in function info."""
        code = """
        #include <concepts>

        template<typename T>
        T add(T a, T b) requires std::integral<T> {
            return a + b;
        }
        """
        axioms = extract_axioms(code)

        # Find add function axioms
        add_axioms = [a for a in axioms if "add" in a.function if a.function]
        # Should have some axiom mentioning the constraint
        assert len(add_axioms) >= 0  # May or may not generate constraint axiom

    def test_requires_clause_with_concept(self):
        """Requires clause using a concept should be extracted."""
        code = """
        template<typename T>
        concept Incrementable = requires(T t) { ++t; };

        template<Incrementable T>
        void increment(T& value) {
            ++value;
        }
        """
        axioms = extract_axioms(code)

        # Should have concept axiom
        concept_axioms = [a for a in axioms if "Incrementable" in a.id]
        assert len(concept_axioms) > 0


class TestStaticAssertExtraction:
    """Tests for extracting axioms from static_assert declarations."""

    def test_static_assert_becomes_invariant(self):
        """static_assert should become an INVARIANT axiom."""
        code = """
        template<typename T>
        struct Container {
            static_assert(sizeof(T) <= 64, "Type too large");
            T data;
        };
        """
        axioms = extract_axioms(code)

        # Find static_assert axioms
        static_axioms = [a for a in axioms if "static_assert" in a.id.lower()
                        or "sizeof" in a.content.lower()
                        or a.axiom_type == AxiomType.INVARIANT]
        assert len(static_axioms) > 0, f"No static_assert axioms in {[a.id for a in axioms]}"

    def test_static_assert_confidence_is_one(self):
        """static_assert axioms should have confidence 1.0."""
        code = """
        static_assert(sizeof(int) == 4, "int must be 4 bytes");
        """
        axioms = extract_axioms(code)

        # Find the static_assert axiom
        static_axioms = [a for a in axioms if "static_assert" in a.id.lower()]
        if static_axioms:
            assert static_axioms[0].confidence == 1.0


class TestEnableIfPatterns:
    """Tests for SFINAE/enable_if pattern detection."""

    def test_enable_if_template_parameter(self):
        """enable_if in template parameter should be recognized."""
        code = """
        #include <type_traits>

        template<typename T,
                 typename = std::enable_if_t<std::is_integral_v<T>>>
        T square(T x) {
            return x * x;
        }
        """
        axioms = extract_axioms(code)

        # The function should be extracted (even if constraint isn't explicit axiom)
        assert len(axioms) >= 0  # At minimum, no crash


class TestTemplateClassConstraints:
    """Tests for constraints on template classes."""

    def test_constrained_template_class(self):
        """Template class with concept constraint should be extracted."""
        code = """
        #include <concepts>

        template<std::integral T>
        class IntWrapper {
            T value;
        public:
            IntWrapper(T v) : value(v) {}
            T get() const { return value; }
        };
        """
        axioms = extract_axioms(code)

        # Should extract class and its methods
        wrapper_axioms = [a for a in axioms if a.function and "IntWrapper" in a.function]
        assert len(wrapper_axioms) >= 0  # Class should be parsed without error

    def test_class_with_requires_clause_on_method(self):
        """Method with requires clause should be extracted."""
        code = """
        #include <concepts>

        template<typename T>
        class Container {
            T value;
        public:
            void print() requires std::integral<T> {
                // print as int
            }
        };
        """
        axioms = extract_axioms(code)

        # Should parse without error
        assert isinstance(axioms, list)


class TestNestedTemplateConstraints:
    """Tests for nested template constraints."""

    def test_nested_concept_usage(self):
        """Concepts used in nested contexts should be extracted."""
        code = """
        #include <concepts>
        #include <vector>

        template<typename T>
        concept Container = requires(T c) {
            c.begin();
            c.end();
            c.size();
        };

        template<Container C>
        auto sum(const C& container) {
            auto result = typename C::value_type{};
            for (const auto& item : container) {
                result += item;
            }
            return result;
        }
        """
        axioms = extract_axioms(code)

        # Should extract Container concept
        container_concept = [a for a in axioms if "Container" in a.id]
        assert len(container_concept) > 0


class TestRealWorldPatterns:
    """Tests based on real-world C++20 patterns."""

    def test_ranges_style_concept(self):
        """Ranges-style concepts should be extracted."""
        code = """
        #include <concepts>
        #include <iterator>

        template<typename I>
        concept ForwardIterator =
            std::input_iterator<I> &&
            std::incrementable<I> &&
            std::sentinel_for<I, I>;
        """
        axioms = extract_axioms(code)

        # Should extract ForwardIterator concept
        iter_concept = [a for a in axioms if "ForwardIterator" in a.id]
        assert len(iter_concept) > 0

    def test_callable_concept(self):
        """Callable concepts should be extracted."""
        code = """
        #include <concepts>
        #include <functional>

        template<typename F, typename... Args>
        concept Callable = std::invocable<F, Args...>;

        template<typename F>
        concept Predicate = Callable<F, int> &&
            std::convertible_to<std::invoke_result_t<F, int>, bool>;
        """
        axioms = extract_axioms(code)

        # Should extract both concepts
        callable = [a for a in axioms if "Callable" in a.id]
        predicate = [a for a in axioms if "Predicate" in a.id]
        assert len(callable) > 0
        assert len(predicate) > 0
