# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Detect contradictions between claims and axioms."""

from dataclasses import dataclass

from axiom.vectors import LanceDBLoader


@dataclass
class Contradiction:
    """A detected contradiction between a claim and an axiom."""

    claim: str
    axiom_id: str
    axiom_content: str
    formal_spec: str
    contradiction_type: str  # "direct", "semantic", "implied"
    confidence: float
    explanation: str


class ContradictionDetector:
    """Detect contradictions between LLM claims and formal axioms."""

    # Patterns that indicate contradictory semantics
    CONTRADICTION_PATTERNS = [
        # (claim_pattern, axiom_pattern, type)
        ("is safe", "undefined behavior", "direct"),
        ("is defined", "undefined", "direct"),
        ("is valid", "invalid", "direct"),
        ("can overflow", "must not overflow", "direct"),
        ("no check", "must check", "implied"),
        ("always", "not always", "semantic"),
        ("never", "may", "semantic"),
        ("guaranteed", "undefined", "direct"),
    ]

    # Known dangerous claims that often contradict C semantics
    DANGEROUS_CLAIMS = [
        "signed integer overflow is defined",
        "null pointer dereference is safe",
        "buffer overflow is harmless",
        "uninitialized variables have default values",
        "casting pointer to integer is always safe",
        "division by zero returns zero",
        "array bounds are not checked",
    ]

    def __init__(
        self,
        lance_loader: LanceDBLoader | None = None,
    ) -> None:
        """Initialize detector.

        Args:
            lance_loader: LanceDB connection for semantic search.
        """
        self._lance = lance_loader

    @property
    def lance(self) -> LanceDBLoader:
        """Get or create LanceDB loader."""
        if self._lance is None:
            self._lance = LanceDBLoader()
        return self._lance

    def detect(self, claim: str) -> list[Contradiction]:
        """Detect contradictions for a claim.

        Args:
            claim: The claim to check for contradictions.

        Returns:
            List of detected contradictions.
        """
        contradictions: list[Contradiction] = []

        # Check against dangerous claims first
        if self._is_dangerous_claim(claim):
            # Search for axioms that contradict dangerous patterns
            results = self._search_for_contradictions(claim)
            for axiom in results:
                contradiction = self._analyze_contradiction(claim, axiom)
                if contradiction:
                    contradictions.append(contradiction)

        # Also do semantic search for potential contradictions
        semantic_contradictions = self._semantic_contradiction_search(claim)
        contradictions.extend(semantic_contradictions)

        # Deduplicate and sort by confidence
        seen = set()
        unique = []
        for c in sorted(contradictions, key=lambda x: -x.confidence):
            if c.axiom_id not in seen:
                seen.add(c.axiom_id)
                unique.append(c)

        return unique

    def validate_claim(self, claim: str) -> tuple[bool, list[Contradiction]]:
        """Validate a claim against the axiom database.

        Args:
            claim: The claim to validate.

        Returns:
            Tuple of (is_valid, contradictions).
        """
        contradictions = self.detect(claim)

        # Claim is valid if no high-confidence contradictions
        high_confidence = [c for c in contradictions if c.confidence >= 0.8]
        is_valid = len(high_confidence) == 0

        return is_valid, contradictions

    def _is_dangerous_claim(self, claim: str) -> bool:
        """Check if claim matches known dangerous patterns."""
        claim_lower = claim.lower()

        for dangerous in self.DANGEROUS_CLAIMS:
            if self._fuzzy_match(claim_lower, dangerous):
                return True

        return False

    def _fuzzy_match(self, text: str, pattern: str) -> bool:
        """Fuzzy match between text and pattern."""
        pattern_words = set(pattern.split())
        text_words = set(text.split())

        # Match if most pattern words appear in text
        common = pattern_words & text_words
        return len(common) >= len(pattern_words) * 0.6

    def _search_for_contradictions(self, claim: str) -> list[dict]:
        """Search for axioms that might contradict the claim."""
        # Extract key terms and search for their negations
        search_terms = self._extract_contradiction_terms(claim)

        results = []
        for term in search_terms:
            axioms = self.lance.search(term, limit=5)
            results.extend(axioms)

        return results

    def _extract_contradiction_terms(self, claim: str) -> list[str]:
        """Extract terms to search for potential contradictions."""
        terms = []
        claim_lower = claim.lower()

        # Add direct topic search
        terms.append(claim_lower)

        # Add negation-based searches
        if "overflow" in claim_lower:
            terms.append("overflow undefined behavior")
        if "pointer" in claim_lower:
            terms.append("null pointer undefined")
        if "division" in claim_lower or "divide" in claim_lower:
            terms.append("division by zero undefined")
        if "array" in claim_lower or "buffer" in claim_lower:
            terms.append("array bounds undefined")
        if "uninitialized" in claim_lower:
            terms.append("uninitialized undefined behavior")

        return terms

    def _analyze_contradiction(
        self, claim: str, axiom: dict
    ) -> Contradiction | None:
        """Analyze if an axiom contradicts the claim."""
        claim_lower = claim.lower()
        axiom_content = axiom["content"].lower()

        # Check for contradiction patterns
        for claim_pattern, axiom_pattern, ctype in self.CONTRADICTION_PATTERNS:
            if claim_pattern in claim_lower and axiom_pattern in axiom_content:
                return Contradiction(
                    claim=claim,
                    axiom_id=axiom["id"],
                    axiom_content=axiom["content"],
                    formal_spec=axiom["formal_spec"],
                    contradiction_type=ctype,
                    confidence=0.9,
                    explanation=self._generate_explanation(
                        claim, axiom, claim_pattern, axiom_pattern
                    ),
                )

        return None

    def _semantic_contradiction_search(self, claim: str) -> list[Contradiction]:
        """Use semantic search to find potential contradictions."""
        contradictions = []
        claim_lower = claim.lower()

        # Search for semantically similar axioms
        axioms = self.lance.search(claim, limit=10)

        for axiom in axioms:
            # Check if the axiom's content contradicts the claim
            if self._semantically_contradicts(claim_lower, axiom):
                contradictions.append(
                    Contradiction(
                        claim=claim,
                        axiom_id=axiom["id"],
                        axiom_content=axiom["content"],
                        formal_spec=axiom["formal_spec"],
                        contradiction_type="semantic",
                        confidence=0.7,
                        explanation=f"The axiom states: {axiom['content']}",
                    )
                )

        return contradictions

    def _semantically_contradicts(self, claim: str, axiom: dict) -> bool:
        """Check if an axiom semantically contradicts a claim.

        Key insight: If claim asserts something is SAFE/DEFINED and axiom says
        it's UNDEFINED/UNSAFE, that's a contradiction.

        But if claim says something IS undefined/UB and axiom confirms it,
        that's SUPPORT, not contradiction.
        """
        axiom_content = axiom["content"].lower()

        # Patterns where claim asserts SAFETY and axiom warns DANGER
        safety_assertions = ["is safe", "is defined", "is valid", "is allowed", "is harmless"]
        danger_warnings = ["undefined", "unsafe", "invalid", "not allowed", "dangerous"]

        # Check if claim asserts safety
        claim_asserts_safety = any(pat in claim for pat in safety_assertions)

        # Check if axiom warns of danger
        axiom_warns_danger = any(warn in axiom_content for warn in danger_warnings)

        # Only a contradiction if claim says safe but axiom says dangerous
        if claim_asserts_safety and axiom_warns_danger:
            return True

        # Check reverse: claim says "never" but axiom says "may"
        if "never" in claim and ("may" in axiom_content or "can" in axiom_content):
            return True

        if "always" in claim and "not always" in axiom_content:
            return True

        return False

    def _generate_explanation(
        self,
        claim: str,
        axiom: dict,
        claim_pattern: str,
        axiom_pattern: str,
    ) -> str:
        """Generate explanation for a contradiction."""
        return (
            f"The claim asserts '{claim_pattern}', but the axiom "
            f"'{axiom['id']}' states that this involves '{axiom_pattern}'. "
            f"Formal specification: {axiom['formal_spec']}"
        )
