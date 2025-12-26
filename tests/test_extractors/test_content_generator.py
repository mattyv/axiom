"""Tests for human-readable content generator."""

import pytest

from axiom.extractors.content_generator import ContentGenerator


class TestContentGenerator:
    """Tests for ContentGenerator."""

    def test_generates_content_for_division_axiom(self) -> None:
        """Generator should create readable content for division axiom."""
        generator = ContentGenerator()

        formal_spec = "isPromoted(T) andBool T ==Type T' andBool notBool isZero(I2)"
        operation = "division"

        content = generator.generate(formal_spec, operation=operation)

        assert content
        assert isinstance(content, str)
        # Should mention the operation
        assert "division" in content.lower()
        # Should mention non-zero requirement
        assert "non-zero" in content.lower() or "not zero" in content.lower() or "zero" in content.lower()

    def test_generates_content_for_type_match(self) -> None:
        """Generator should handle type matching predicates."""
        generator = ContentGenerator()

        formal_spec = "T ==Type T'"

        content = generator.generate(formal_spec)

        assert content
        assert "type" in content.lower()
        assert "match" in content.lower() or "equal" in content.lower() or "same" in content.lower()

    def test_generates_content_for_promoted_type(self) -> None:
        """Generator should handle isPromoted predicate."""
        generator = ContentGenerator()

        formal_spec = "isPromoted(T)"

        content = generator.generate(formal_spec)

        assert content
        assert "promoted" in content.lower() or "promotion" in content.lower()

    def test_generates_content_for_negation(self) -> None:
        """Generator should handle notBool predicates."""
        generator = ContentGenerator()

        formal_spec = "notBool isZero(I2)"

        content = generator.generate(formal_spec)

        assert content
        assert "not" in content.lower() or "non" in content.lower()
        assert "zero" in content.lower()

    def test_generates_content_for_multiple_conditions(self) -> None:
        """Generator should handle multiple andBool conditions."""
        generator = ContentGenerator()

        formal_spec = "isPromoted(T) andBool T ==Type T' andBool notBool isZero(I2)"

        content = generator.generate(formal_spec)

        # Should mention all conditions
        assert content
        # Content should be non-trivial
        assert len(content) > 20

    def test_handles_empty_formal_spec(self) -> None:
        """Generator should handle empty formal spec gracefully."""
        generator = ContentGenerator()

        content = generator.generate("")

        assert content is not None
        assert isinstance(content, str)

    def test_handles_unknown_predicates(self) -> None:
        """Generator should handle unknown predicates without crashing."""
        generator = ContentGenerator()

        formal_spec = "someUnknownPredicate(X) andBool anotherUnknown(Y, Z)"

        content = generator.generate(formal_spec)

        # Should still return something meaningful
        assert content is not None
        assert isinstance(content, str)

    def test_parse_conditions_splits_andbool(self) -> None:
        """Generator should split on andBool correctly."""
        generator = ContentGenerator()

        formal_spec = "isPromoted(T) andBool notBool isZero(I2)"
        conditions = generator.parse_conditions(formal_spec)

        assert len(conditions) == 2
        assert "isPromoted(T)" in conditions
        assert "notBool isZero(I2)" in conditions

    def test_parse_conditions_handles_orbool(self) -> None:
        """Generator should handle orBool conditions."""
        generator = ContentGenerator()

        formal_spec = "isUnknown(V) orBool isUnknown(V')"
        conditions = generator.parse_conditions(formal_spec)

        # orBool conditions should be parsed but marked differently
        assert len(conditions) >= 1

    def test_generates_axiom_id(self) -> None:
        """Generator should create a unique axiom ID."""
        generator = ContentGenerator()

        axiom_id = generator.generate_axiom_id(
            module="C-COMMON-EXPR-MULTIPLICATIVE",
            operation="division",
            formal_spec="notBool isZero(I2)"
        )

        assert axiom_id
        assert isinstance(axiom_id, str)
        # ID should be lowercase and use underscores
        assert axiom_id == axiom_id.lower()
        assert "_" in axiom_id or axiom_id.isalnum()
        # Should reference the module or operation
        assert "division" in axiom_id or "multiplicative" in axiom_id or "c11" in axiom_id
