"""Tests for Axiom and AxiomType models."""

import pytest

from axiom.models import Axiom, AxiomType, SourceLocation


class TestAxiomType:
    """Tests for AxiomType enum."""

    def test_all_axiom_types_exist(self):
        """Test all expected axiom types exist."""
        assert AxiomType.PRECONDITION.value == "precondition"
        assert AxiomType.POSTCONDITION.value == "postcondition"
        assert AxiomType.INVARIANT.value == "invariant"
        assert AxiomType.EXCEPTION.value == "exception"
        assert AxiomType.EFFECT.value == "effect"
        assert AxiomType.CONSTRAINT.value == "constraint"
        assert AxiomType.ANTI_PATTERN.value == "anti_pattern"
        assert AxiomType.COMPLEXITY.value == "complexity"

    def test_axiom_type_count(self):
        """Test the total number of axiom types."""
        assert len(AxiomType) == 8

    def test_anti_pattern_type(self):
        """Test ANTI_PATTERN axiom type for common mistakes/warnings."""
        axiom = Axiom(
            id="test_anti_pattern",
            content="Avoid calling body() with negative indices",
            formal_spec="forall i: i >= 0 when calling body(i)",
            source=SourceLocation(file="test.cpp", module="test"),
            axiom_type=AxiomType.ANTI_PATTERN,
        )
        assert axiom.axiom_type == AxiomType.ANTI_PATTERN
        assert axiom.axiom_type.value == "anti_pattern"

    def test_complexity_type(self):
        """Test COMPLEXITY axiom type for Big-O guarantees."""
        axiom = Axiom(
            id="test_complexity",
            content="Time complexity is O(N) where N is the iteration count",
            formal_spec="T(n) = O(n)",
            source=SourceLocation(file="test.cpp", module="test"),
            axiom_type=AxiomType.COMPLEXITY,
        )
        assert axiom.axiom_type == AxiomType.COMPLEXITY
        assert axiom.axiom_type.value == "complexity"

    def test_effect_type_for_behavioral_axioms(self):
        """Test EFFECT axiom type captures behavioral semantics."""
        axiom = Axiom(
            id="test_effect",
            content="body is invoked exactly N times per outer iteration",
            formal_spec="count(body_calls) == N",
            source=SourceLocation(file="ilp.hpp", module="ilp"),
            axiom_type=AxiomType.EFFECT,
            depends_on=["c11_stmt_for_semantics", "c11_expr_call"],
        )
        assert axiom.axiom_type == AxiomType.EFFECT
        assert len(axiom.depends_on) == 2
        assert "c11_stmt_for_semantics" in axiom.depends_on

    def test_axiom_type_from_string(self):
        """Test creating AxiomType from string value."""
        assert AxiomType("anti_pattern") == AxiomType.ANTI_PATTERN
        assert AxiomType("complexity") == AxiomType.COMPLEXITY
        assert AxiomType("effect") == AxiomType.EFFECT

    def test_invalid_axiom_type_raises_error(self):
        """Test that invalid axiom type raises ValueError."""
        with pytest.raises(ValueError):
            AxiomType("invalid_type")


class TestAxiomDependsOn:
    """Tests for axiom dependency chains."""

    def test_depends_on_is_list(self):
        """Test depends_on field is a list."""
        axiom = Axiom(
            id="test",
            content="Test axiom",
            formal_spec="test",
            source=SourceLocation(file="test.cpp", module="test"),
        )
        assert isinstance(axiom.depends_on, list)
        assert len(axiom.depends_on) == 0

    def test_depends_on_multiple_axioms(self):
        """Test depends_on can reference multiple foundation axioms (1:many)."""
        axiom = Axiom(
            id="library_axiom",
            content="body receives sequential indices from i*N to i*N + N-1",
            formal_spec="body(i*N + j) for j in 0..N-1",
            source=SourceLocation(file="ilp.hpp", module="ilp"),
            axiom_type=AxiomType.EFFECT,
            depends_on=[
                "c11_expr_add",
                "c11_expr_mul",
                "c11_stmt_for_semantics",
                "c11_expr_call",
            ],
        )
        assert len(axiom.depends_on) == 4
        assert "c11_expr_add" in axiom.depends_on
        assert "c11_expr_mul" in axiom.depends_on

    def test_depends_on_preserved_in_serialization(self):
        """Test depends_on is preserved through TOML serialization."""
        from axiom.models import AxiomCollection

        axiom = Axiom(
            id="test_axiom",
            content="Test",
            formal_spec="test",
            source=SourceLocation(file="test.cpp", module="test"),
            depends_on=["foundation_1", "foundation_2"],
        )
        collection = AxiomCollection(axioms=[axiom])
        toml_str = collection.to_toml()

        loaded = AxiomCollection.load_toml_string(toml_str)
        assert loaded.axioms[0].depends_on == ["foundation_1", "foundation_2"]


class TestEffectiveConfidence:
    """Tests for effective_confidence property."""

    def test_foundation_layer_returns_base_confidence(self):
        """Test that foundation layers return original confidence unchanged."""
        axiom = Axiom(
            id="c11_test",
            content="Foundation axiom",
            formal_spec="test",
            source=SourceLocation(file="test.k", module="test"),
            layer="c11_core",
            confidence=1.0,
        )
        assert axiom.effective_confidence == 1.0

    def test_foundation_layer_c11_stdlib(self):
        """Test c11_stdlib is treated as grounded."""
        axiom = Axiom(
            id="c11_stdlib_test",
            content="Stdlib axiom",
            formal_spec="test",
            source=SourceLocation(file="test.k", module="test"),
            layer="c11_stdlib",
            confidence=0.9,
        )
        assert axiom.effective_confidence == 0.9

    def test_foundation_layer_cpp_core(self):
        """Test cpp_core is treated as grounded."""
        axiom = Axiom(
            id="cpp_core_test",
            content="C++ core axiom",
            formal_spec="test",
            source=SourceLocation(file="test.k", module="test"),
            layer="cpp_core",
            confidence=0.95,
        )
        assert axiom.effective_confidence == 0.95

    def test_foundation_layer_cpp_stdlib(self):
        """Test cpp_stdlib is treated as grounded."""
        axiom = Axiom(
            id="cpp_stdlib_test",
            content="C++ stdlib axiom",
            formal_spec="test",
            source=SourceLocation(file="test.k", module="test"),
            layer="cpp_stdlib",
            confidence=1.0,
        )
        assert axiom.effective_confidence == 1.0

    def test_foundation_layer_cpp20_language(self):
        """Test cpp20_language is treated as grounded."""
        axiom = Axiom(
            id="cpp20_test",
            content="C++20 axiom",
            formal_spec="test",
            source=SourceLocation(file="test.k", module="test"),
            layer="cpp20_language",
            confidence=0.8,
        )
        assert axiom.effective_confidence == 0.8

    def test_foundation_layer_cpp20_stdlib(self):
        """Test cpp20_stdlib is treated as grounded."""
        axiom = Axiom(
            id="cpp20_stdlib_test",
            content="C++20 stdlib axiom",
            formal_spec="test",
            source=SourceLocation(file="test.k", module="test"),
            layer="cpp20_stdlib",
            confidence=0.85,
        )
        assert axiom.effective_confidence == 0.85

    def test_library_layer_unreviewed_gets_70_percent(self):
        """Test unreviewed library axioms get 70% of base confidence."""
        axiom = Axiom(
            id="library_test",
            content="Library axiom",
            formal_spec="test",
            source=SourceLocation(file="lib.cpp", module="lib"),
            layer="library",
            confidence=1.0,
            reviewed=False,
        )
        # 1.0 * 0.7 = 0.7
        assert axiom.effective_confidence == 0.7

    def test_library_layer_reviewed_gets_90_percent(self):
        """Test reviewed library axioms get 90% of base confidence."""
        axiom = Axiom(
            id="library_test",
            content="Library axiom",
            formal_spec="test",
            source=SourceLocation(file="lib.cpp", module="lib"),
            layer="library",
            confidence=1.0,
            reviewed=True,
        )
        # 1.0 * 0.9 = 0.9
        assert axiom.effective_confidence == 0.9

    def test_library_layer_partial_confidence_unreviewed(self):
        """Test partial confidence with unreviewed status."""
        axiom = Axiom(
            id="library_test",
            content="Library axiom",
            formal_spec="test",
            source=SourceLocation(file="lib.cpp", module="lib"),
            layer="library",
            confidence=0.8,
            reviewed=False,
        )
        # 0.8 * 0.7 = 0.56
        assert axiom.effective_confidence == pytest.approx(0.56)

    def test_library_layer_partial_confidence_reviewed(self):
        """Test partial confidence with reviewed status."""
        axiom = Axiom(
            id="library_test",
            content="Library axiom",
            formal_spec="test",
            source=SourceLocation(file="lib.cpp", module="lib"),
            layer="library",
            confidence=0.8,
            reviewed=True,
        )
        # 0.8 * 0.9 = 0.72
        assert axiom.effective_confidence == pytest.approx(0.72)

    def test_effective_confidence_capped_at_one(self):
        """Test that effective_confidence never exceeds 1.0."""
        axiom = Axiom(
            id="high_confidence",
            content="High confidence axiom",
            formal_spec="test",
            source=SourceLocation(file="lib.cpp", module="lib"),
            layer="library",
            confidence=1.5,  # Artificially high
            reviewed=True,
        )
        # min(1.5 * 0.9, 1.0) = min(1.35, 1.0) = 1.0
        assert axiom.effective_confidence == 1.0

    def test_unknown_layer_treated_as_library(self):
        """Test that unknown layers are treated like library axioms."""
        axiom = Axiom(
            id="custom_layer",
            content="Custom layer axiom",
            formal_spec="test",
            source=SourceLocation(file="custom.cpp", module="custom"),
            layer="custom_layer",
            confidence=1.0,
            reviewed=False,
        )
        # Should be treated like library: 1.0 * 0.7 = 0.7
        assert axiom.effective_confidence == 0.7


class TestAxiomCollectionToml:
    """Tests for AxiomCollection TOML serialization."""

    def test_to_toml_includes_function(self):
        """Test that function field is included in TOML output."""
        from axiom.models import AxiomCollection

        axiom = Axiom(
            id="test",
            content="Test",
            formal_spec="test",
            source=SourceLocation(file="test.cpp", module="test"),
            function="malloc",
        )
        collection = AxiomCollection(axioms=[axiom])
        toml_str = collection.to_toml()
        assert 'function = "malloc"' in toml_str

    def test_to_toml_includes_header(self):
        """Test that header field is included in TOML output."""
        from axiom.models import AxiomCollection

        axiom = Axiom(
            id="test",
            content="Test",
            formal_spec="test",
            source=SourceLocation(file="test.cpp", module="test"),
            header="stdlib.h",
        )
        collection = AxiomCollection(axioms=[axiom])
        toml_str = collection.to_toml()
        assert 'header = "stdlib.h"' in toml_str

    def test_to_toml_includes_axiom_type(self):
        """Test that axiom_type field is included in TOML output."""
        from axiom.models import AxiomCollection

        axiom = Axiom(
            id="test",
            content="Test",
            formal_spec="test",
            source=SourceLocation(file="test.cpp", module="test"),
            axiom_type=AxiomType.PRECONDITION,
        )
        collection = AxiomCollection(axioms=[axiom])
        toml_str = collection.to_toml()
        assert 'axiom_type = "precondition"' in toml_str

    def test_to_toml_includes_on_violation(self):
        """Test that on_violation field is included in TOML output."""
        from axiom.models import AxiomCollection

        axiom = Axiom(
            id="test",
            content="Test",
            formal_spec="test",
            source=SourceLocation(file="test.cpp", module="test"),
            on_violation="undefined behavior",
        )
        collection = AxiomCollection(axioms=[axiom])
        toml_str = collection.to_toml()
        assert "on_violation" in toml_str

    def test_to_toml_includes_depends_on(self):
        """Test that depends_on field is included in TOML output."""
        from axiom.models import AxiomCollection

        axiom = Axiom(
            id="test",
            content="Test",
            formal_spec="test",
            source=SourceLocation(file="test.cpp", module="test"),
            depends_on=["axiom_1", "axiom_2"],
        )
        collection = AxiomCollection(axioms=[axiom])
        toml_str = collection.to_toml()
        assert "depends_on" in toml_str

    def test_to_toml_includes_reviewed(self):
        """Test that reviewed field is included in TOML output."""
        from axiom.models import AxiomCollection

        axiom = Axiom(
            id="test",
            content="Test",
            formal_spec="test",
            source=SourceLocation(file="test.cpp", module="test"),
            reviewed=True,
        )
        collection = AxiomCollection(axioms=[axiom])
        toml_str = collection.to_toml()
        assert "reviewed = true" in toml_str

    def test_to_toml_skips_false_reviewed(self):
        """Test that reviewed=False is not included in TOML output."""
        from axiom.models import AxiomCollection

        axiom = Axiom(
            id="test",
            content="Test",
            formal_spec="test",
            source=SourceLocation(file="test.cpp", module="test"),
            reviewed=False,  # Default, should not appear in output
        )
        collection = AxiomCollection(axioms=[axiom])
        toml_str = collection.to_toml()
        assert "reviewed" not in toml_str

    def test_load_toml_string_parses_axiom_type(self):
        """Test loading TOML string with axiom_type."""
        from axiom.models import AxiomCollection

        toml_str = """
version = "1.0"
source = "test"
extracted_at = "2024-01-01T00:00:00"

[[axioms]]
id = "test"
content = '''Test'''
formal_spec = '''spec'''
layer = "c11_core"
confidence = 1.0
source_file = "test.k"
source_module = "test"
axiom_type = "effect"
"""
        collection = AxiomCollection.load_toml_string(toml_str)
        assert collection.axioms[0].axiom_type == AxiomType.EFFECT

    def test_load_toml_string_parses_reviewed(self):
        """Test loading TOML string with reviewed field."""
        from axiom.models import AxiomCollection

        toml_str = """
version = "1.0"
source = "test"
extracted_at = "2024-01-01T00:00:00"

[[axioms]]
id = "test"
content = '''Test'''
formal_spec = '''spec'''
layer = "c11_core"
confidence = 1.0
source_file = "test.k"
source_module = "test"
reviewed = true
"""
        collection = AxiomCollection.load_toml_string(toml_str)
        assert collection.axioms[0].reviewed is True

    def test_load_toml_string_defaults_reviewed_false(self):
        """Test that reviewed defaults to False when not in TOML."""
        from axiom.models import AxiomCollection

        toml_str = """
version = "1.0"
source = "test"
extracted_at = "2024-01-01T00:00:00"

[[axioms]]
id = "test"
content = '''Test'''
formal_spec = '''spec'''
layer = "c11_core"
confidence = 1.0
source_file = "test.k"
source_module = "test"
"""
        collection = AxiomCollection.load_toml_string(toml_str)
        assert collection.axioms[0].reviewed is False
