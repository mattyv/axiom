# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Validate LLM outputs against formal axioms."""

from dataclasses import dataclass, field

from .contradiction import Contradiction, ContradictionDetector
from .proof_chain import ProofChain, ProofChainGenerator


@dataclass
class ValidationResult:
    """Result of validating a claim or LLM output."""

    claim: str
    is_valid: bool
    confidence: float
    contradictions: list[Contradiction] = field(default_factory=list)
    proof_chain: ProofChain | None = None
    explanation: str = ""
    warnings: list[str] = field(default_factory=list)


class AxiomValidator:
    """Validate LLM outputs against the axiom knowledge base."""

    def __init__(
        self,
        proof_generator: ProofChainGenerator | None = None,
        contradiction_detector: ContradictionDetector | None = None,
    ) -> None:
        """Initialize validator with reasoning components.

        Args:
            proof_generator: Generator for proof chains.
            contradiction_detector: Detector for contradictions.
        """
        self._proof = proof_generator
        self._contradiction = contradiction_detector

    @property
    def proof_generator(self) -> ProofChainGenerator:
        """Get or create proof chain generator."""
        if self._proof is None:
            self._proof = ProofChainGenerator()
        return self._proof

    @property
    def contradiction_detector(self) -> ContradictionDetector:
        """Get or create contradiction detector."""
        if self._contradiction is None:
            self._contradiction = ContradictionDetector()
        return self._contradiction

    def validate(self, claim: str) -> ValidationResult:
        """Validate a single claim against axioms.

        Args:
            claim: The claim to validate.

        Returns:
            ValidationResult with validity, contradictions, and proof.
        """
        # Detect contradictions
        is_valid, contradictions = self.contradiction_detector.validate_claim(claim)

        # Generate proof chain (for supporting or contradicting)
        proof_chain = self.proof_generator.generate(claim)

        # Calculate overall confidence
        if contradictions:
            confidence = 1.0 - max(c.confidence for c in contradictions)
        elif proof_chain.grounded:
            confidence = proof_chain.confidence
        else:
            # Not grounded but may have supporting axioms
            if proof_chain.steps:
                # Use proof chain confidence scaled down for ungrounded claims
                confidence = proof_chain.confidence * 0.8
            else:
                confidence = 0.3  # No supporting axioms found

        # Generate explanation
        explanation = self._generate_explanation(
            claim, is_valid, contradictions, proof_chain
        )

        # Generate warnings
        warnings = self._generate_warnings(claim, contradictions)

        return ValidationResult(
            claim=claim,
            is_valid=is_valid,
            confidence=confidence,
            contradictions=contradictions,
            proof_chain=proof_chain,
            explanation=explanation,
            warnings=warnings,
        )

    def validate_text(self, text: str) -> list[ValidationResult]:
        """Validate multiple claims extracted from text.

        Args:
            text: Text containing claims to validate.

        Returns:
            List of ValidationResults for each detected claim.
        """
        # Extract claims from text
        claims = self._extract_claims(text)

        # Validate each claim
        results = []
        for claim in claims:
            result = self.validate(claim)
            results.append(result)

        return results

    def quick_check(self, claim: str) -> bool:
        """Quick validation without full proof chain.

        Args:
            claim: The claim to check.

        Returns:
            True if claim appears valid, False if contradictions found.
        """
        is_valid, _ = self.contradiction_detector.validate_claim(claim)
        return is_valid

    def _extract_claims(self, text: str) -> list[str]:
        """Extract individual claims from text.

        For now, split on sentences. Future: use NLP.
        """
        # Simple sentence splitting
        import re

        sentences = re.split(r"[.!?]+", text)
        claims = []

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 10:  # Skip very short fragments
                claims.append(sentence)

        return claims

    def _generate_explanation(
        self,
        claim: str,
        is_valid: bool,
        contradictions: list[Contradiction],
        proof_chain: ProofChain,
    ) -> str:
        """Generate a human-readable explanation of the validation."""
        if not is_valid and contradictions:
            c = contradictions[0]
            return (
                f"INVALID: The claim contradicts formal semantics. "
                f"The axiom '{c.axiom_id}' states: {c.axiom_content}. "
                f"Contradiction type: {c.contradiction_type}."
            )
        elif is_valid and proof_chain.grounded:
            return (
                f"VALID: The claim is grounded in formal semantics. "
                f"{proof_chain.explanation}"
            )
        elif is_valid and proof_chain.steps:
            return (
                f"LIKELY VALID: Found supporting axioms but claim is not "
                f"directly grounded. {proof_chain.explanation}"
            )
        elif is_valid:
            return (
                "UNCERTAIN: No contradictions found, but no supporting "
                "axioms were found either. Exercise caution."
            )
        else:
            return (
                "UNCERTAIN: Could not definitively validate or contradict "
                "this claim against the axiom database."
            )

    def _generate_warnings(
        self, claim: str, contradictions: list[Contradiction]
    ) -> list[str]:
        """Generate warnings based on validation results."""
        warnings = []

        # Warn about undefined behavior
        if any("undefined" in c.axiom_content.lower() for c in contradictions):
            warnings.append(
                "WARNING: This claim may involve undefined behavior in C/C++."
            )

        # Warn about implementation-defined behavior
        if any("implementation" in c.axiom_content.lower() for c in contradictions):
            warnings.append(
                "WARNING: This may depend on implementation-defined behavior."
            )

        # Warn about security implications
        dangerous_keywords = ["overflow", "buffer", "pointer", "null", "bounds"]
        if any(kw in claim.lower() for kw in dangerous_keywords):
            warnings.append(
                "WARNING: This claim involves security-sensitive operations."
            )

        return warnings
