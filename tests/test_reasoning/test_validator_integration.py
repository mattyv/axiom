"""Integration tests for validator false positives fix.

These tests verify that the validator correctly identifies contradictions
between claims and axioms, preventing false positives for claims like
"signed integer overflow wraps around".

These tests require neo4j to be installed.
"""

from unittest.mock import MagicMock

import pytest

from axiom.reasoning.entailment import EntailmentClassifier

# These imports require neo4j which may not be installed in CI
try:
    from axiom.reasoning.proof_chain import ProofChainGenerator
    from axiom.reasoning.validator import AxiomValidator

    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False
    ProofChainGenerator = None  # type: ignore[misc, assignment]
    AxiomValidator = None  # type: ignore[misc, assignment]

pytestmark = pytest.mark.skipif(not HAS_NEO4J, reason="neo4j not installed")


class TestValidatorFalsePositives:
    """Tests for the false positive issue - invalid claims should be rejected."""

    def test_signed_overflow_wraps_around_is_invalid(self):
        """The original bug: 'wraps around' claim should be INVALID."""
        # Create a mock proof chain generator that returns a relevant axiom
        mock_lance = MagicMock()
        mock_lance.search.return_value = [
            {
                "id": "c11_signed_overflow_test",
                "content": "Signed integer overflow",
                "formal_spec": "undefined behavior",
                "module": "C-OVERFLOW",
                "layer": "c11_core",
                "confidence": 1.0,
                "_distance": 0.5,
            }
        ]

        mock_neo4j = MagicMock()
        mock_neo4j.get_proof_chain.return_value = []

        generator = ProofChainGenerator(
            neo4j_loader=mock_neo4j,
            lance_loader=mock_lance,
        )
        validator = AxiomValidator(proof_generator=generator)

        result = validator.validate("Signed integer overflow wraps around")

        assert result.is_valid is False
        assert len(result.contradictions) > 0
        assert any(c.contradiction_type == "entailment" for c in result.contradictions)

    def test_signed_overflow_is_ub_is_valid(self):
        """Correct claim about UB should still validate."""
        mock_lance = MagicMock()
        mock_lance.search.return_value = [
            {
                "id": "c11_signed_overflow_test",
                "content": "Signed integer overflow is undefined behavior",
                "formal_spec": "undefined behavior",
                "module": "C-OVERFLOW",
                "layer": "c11_core",
                "confidence": 1.0,
                "_distance": 0.5,
            }
        ]

        mock_neo4j = MagicMock()
        mock_neo4j.get_proof_chain.return_value = []

        generator = ProofChainGenerator(
            neo4j_loader=mock_neo4j,
            lance_loader=mock_lance,
        )
        validator = AxiomValidator(proof_generator=generator)

        result = validator.validate("Signed integer overflow is undefined behavior")

        assert result.is_valid is True

    def test_null_deref_safe_is_invalid(self):
        """'Null deref is safe' claim should be INVALID."""
        mock_lance = MagicMock()
        mock_lance.search.return_value = [
            {
                "id": "c11_null_pointer_test",
                "content": "Operation requires: must not be a null pointer",
                "formal_spec": "requires: NOT isNull(ptr)",
                "module": "C-MEMORY",
                "layer": "c11_core",
                "confidence": 1.0,
                "_distance": 0.5,
            }
        ]

        mock_neo4j = MagicMock()
        mock_neo4j.get_proof_chain.return_value = []

        generator = ProofChainGenerator(
            neo4j_loader=mock_neo4j,
            lance_loader=mock_lance,
        )
        validator = AxiomValidator(proof_generator=generator)

        result = validator.validate("Dereferencing a null pointer is safe")

        assert result.is_valid is False
        assert len(result.contradictions) > 0

    def test_twos_complement_claim_is_invalid(self):
        """Two's complement claim should be INVALID for signed integers."""
        mock_lance = MagicMock()
        mock_lance.search.return_value = [
            {
                "id": "c11_signed_overflow_test",
                "content": "Signed integer overflow is undefined behavior",
                "formal_spec": "undefined",
                "module": "C-OVERFLOW",
                "layer": "c11_core",
                "confidence": 1.0,
                "_distance": 0.5,
            }
        ]

        mock_neo4j = MagicMock()
        mock_neo4j.get_proof_chain.return_value = []

        generator = ProofChainGenerator(
            neo4j_loader=mock_neo4j,
            lance_loader=mock_lance,
        )
        validator = AxiomValidator(proof_generator=generator)

        result = validator.validate("Signed integer overflow uses two's complement")

        assert result.is_valid is False
        assert len(result.contradictions) > 0


class TestProofChainRelationships:
    """Tests for proof chain relationship classification."""

    def test_proof_step_has_contradicts_relationship(self):
        """Test that contradicting axioms get CONTRADICTS relationship."""
        mock_lance = MagicMock()
        mock_lance.search.return_value = [
            {
                "id": "test_axiom",
                "content": "Signed integer overflow",
                "formal_spec": "",
                "module": "TEST",
                "layer": "c11_core",
                "confidence": 1.0,
                "_distance": 0.5,
            }
        ]

        mock_neo4j = MagicMock()
        mock_neo4j.get_proof_chain.return_value = []

        generator = ProofChainGenerator(
            neo4j_loader=mock_neo4j,
            lance_loader=mock_lance,
        )

        chain = generator.generate("Signed integer overflow wraps around")

        assert len(chain.steps) > 0
        assert chain.steps[0].relationship == "CONTRADICTS"

    def test_proof_step_has_supports_relationship_for_ub_claim(self):
        """Test that UB claims with UB axioms get SUPPORTS relationship."""
        mock_lance = MagicMock()
        mock_lance.search.return_value = [
            {
                "id": "test_axiom",
                "content": "Signed integer overflow is undefined behavior",
                "formal_spec": "",
                "module": "TEST",
                "layer": "c11_core",
                "confidence": 1.0,
                "_distance": 0.5,
            }
        ]

        mock_neo4j = MagicMock()
        mock_neo4j.get_proof_chain.return_value = []

        generator = ProofChainGenerator(
            neo4j_loader=mock_neo4j,
            lance_loader=mock_lance,
        )

        chain = generator.generate("Signed integer overflow is undefined behavior")

        assert len(chain.steps) > 0
        assert chain.steps[0].relationship == "SUPPORTS"


class TestValidationExplanations:
    """Tests for validation result explanations."""

    def test_contradiction_explanation_mentions_conflict(self):
        """Test that contradiction explanations mention the conflict."""
        mock_lance = MagicMock()
        mock_lance.search.return_value = [
            {
                "id": "test_axiom",
                "content": "Signed integer overflow",
                "formal_spec": "",
                "module": "TEST",
                "layer": "c11_core",
                "confidence": 1.0,
                "_distance": 0.5,
            }
        ]

        mock_neo4j = MagicMock()
        mock_neo4j.get_proof_chain.return_value = []

        generator = ProofChainGenerator(
            neo4j_loader=mock_neo4j,
            lance_loader=mock_lance,
        )
        validator = AxiomValidator(proof_generator=generator)

        result = validator.validate("Signed integer overflow wraps around")

        assert "INVALID" in result.explanation or "contradict" in result.explanation.lower()

    def test_valid_claim_explanation_mentions_grounded(self):
        """Test that valid claim explanations mention grounding."""
        mock_lance = MagicMock()
        mock_lance.search.return_value = [
            {
                "id": "test_axiom",
                "content": "Signed integer overflow is undefined behavior",
                "formal_spec": "",
                "module": "TEST",
                "layer": "c11_core",
                "confidence": 1.0,
                "_distance": 0.5,
            }
        ]

        mock_neo4j = MagicMock()
        mock_neo4j.get_proof_chain.return_value = []

        generator = ProofChainGenerator(
            neo4j_loader=mock_neo4j,
            lance_loader=mock_lance,
        )
        validator = AxiomValidator(proof_generator=generator)

        result = validator.validate("Signed integer overflow is undefined behavior")

        # Should be valid with grounded explanation
        assert result.is_valid is True
        assert "VALID" in result.explanation or "grounded" in result.explanation.lower()


class TestKSemanticsPatterns:
    """Tests for K-semantics vocabulary patterns."""

    def test_must_not_pattern_detected_as_negative(self):
        """Test 'must not' K-semantics pattern is detected as negative."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Dereferencing a null pointer is safe",
            axiom={"content": "pointer must not be null", "formal_spec": ""},
        )
        assert result.relationship == "CONTRADICTS"

    def test_operation_requires_pattern_detected_as_negative(self):
        """Test 'Operation requires:' K-semantics pattern is detected as negative."""
        classifier = EntailmentClassifier()
        classifier.classify(
            claim="Array access is always safe",
            axiom={"content": "Operation requires: index < size", "formal_spec": ""},
        )
        # Should be negative polarity (constraint = violation is UB)
        polarity = classifier._extract_polarity("Operation requires: index < size")
        assert polarity == "negative"
