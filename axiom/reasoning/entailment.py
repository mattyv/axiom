# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Entailment classification between claims and axioms.

This module determines whether an axiom SUPPORTS, CONTRADICTS, or is merely
RELATED_TO a given claim using polarity-based analysis.
"""

import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class EntailmentResult:
    """Result of classifying the relationship between a claim and axiom."""

    relationship: Literal["SUPPORTS", "CONTRADICTS", "RELATED_TO"]
    confidence: float
    explanation: str


class EntailmentClassifier:
    """Classify relationship between claims and axioms using polarity analysis.

    The key insight is that claims and axioms have polarity:
    - Positive: asserts defined/safe/valid behavior ("wraps around", "is safe")
    - Negative: asserts undefined/error/invalid behavior ("undefined", "must not")

    When claim polarity CONFLICTS with axiom polarity on the same topic,
    it's a CONTRADICTION.
    """

    # Positive polarity indicators - claim asserts defined/safe behavior
    POSITIVE_INDICATORS = [
        "wraps around",
        "two's complement",
        "is safe",
        "is defined",
        "is valid",
        "is allowed",
        "is harmless",
        "well-defined",
        "guaranteed",
        "returns",
        "works",
        "succeeds",
    ]

    # Negative polarity indicators - claim/axiom asserts undefined/error behavior
    # Extended to match K-semantics vocabulary (1,583 axioms use these patterns)
    NEGATIVE_INDICATORS = [
        "undefined behavior",
        "undefined",
        "error",
        "invalid",
        "must not",
        "shall not",
        "constraint violation",
        "requires: NOT",
        "requires:",
        "Operation requires:",
        "must be",
        "shall be",
        "violat",  # matches "violation", "violated", "violates"
    ]

    # Topic patterns for detecting what the text is about
    TOPIC_PATTERNS = {
        "overflow": [
            r"\boverflow\b",
            r"\boverflows\b",
            r"\bexceed\b",
            r"\bexceeds\b",
            r"\bout of range\b",
        ],
        "null_pointer": [
            r"\bnull pointer\b",
            r"\bnull\b",
            r"\bnullptr\b",
            r"\bNULL\b",
        ],
        "division": [
            r"\bdivision by zero\b",
            r"\bdivide by zero\b",
            r"\bdivisor.{0,10}zero\b",
        ],
        "buffer": [
            r"\bbuffer\b",
            r"\barray bounds\b",
            r"\bout.of.bounds\b",
            r"\bbounds\b",
        ],
        "memory": [
            r"\bmemory\b",
            r"\balloc\b",
            r"\bfree\b",
            r"\bheap\b",
        ],
        "pointer": [
            r"\bpointer\b",
            r"\bderef\b",
            r"\bdereference\b",
            r"\bdereferencing\b",
            r"\binvalid pointer\b",
        ],
        "integer": [
            r"\binteger\b",
            r"\bsigned\b",
            r"\bunsigned\b",
            r"\bint\b",
        ],
        "std_move": [
            r"\bstd::move\b",
            r"\bmove\b",
        ],
        "std_forward": [
            r"\bstd::forward\b",
            r"\bforward\b",
        ],
        "delete": [
            r"\bdelete\b",
            r"\bfree\b",
            r"\bdeallocate\b",
            r"\bdouble.?delete\b",
        ],
        "iterator": [
            r"\biterator\b",
            r"\bForwardIterator\b",
            r"\bInputIterator\b",
            r"\bRandomAccessIterator\b",
            r"\bBidirectionalIterator\b",
            r"\bOutputIterator\b",
            r"\bpass\b",  # single-pass, multi-pass
        ],
        "vector": [
            r"\bvector\b",
            r"\bstd::vector\b",
            r"\belements?\b",
            r"\bcontiguous\b",
            r"\bstored\b",
        ],
        "macro": [
            r"\bmacro\b",
            r"\bILP_\w+\b",
            r"\bpaired\b",
            r"\bmatching\b",
        ],
    }

    # Semantic opposition pairs - claim pattern vs axiom pattern that contradict
    # Format: (claim_pattern, axiom_pattern, explanation)
    SEMANTIC_OPPOSITIONS = [
        # Pass count: single vs multi
        (r"\bsingle.?pass\b", r"\bmulti.?pass\b", "single-pass contradicts multi-pass"),
        (r"\bmulti.?pass\b", r"\bsingle.?pass\b", "multi-pass contradicts single-pass"),
        # Direction: reverse vs increasing/forward
        (r"\breverse\s+order\b", r"\bincreasing\b", "reverse order contradicts increasing order"),
        (r"\breverse\s+order\b", r"\bforward\b", "reverse order contradicts forward order"),
        (r"\bincreasing\b", r"\breverse\b", "increasing contradicts reverse"),
        # Pairing: without vs must be paired
        (r"\bwithout\s+matching\b", r"\bmust\s+be\s+paired\b", "without matching contradicts must be paired"),
        (r"\bwithout\s+matching\b", r"\brequires.*matching\b", "without matching contradicts requires matching"),
        (r"\bcan\s+be\s+used\s+without\b", r"\bmust\s+be\s+paired\b", "can be used without contradicts must be paired"),
        # Valid/invalid
        (r"\binvalid\b", r"\bvalid\b", "invalid contradicts valid"),
        (r"\bvalid\b", r"\binvalid\b", "valid contradicts invalid"),
        # Safety with undefined behavior
        (r"\bis\s+safe\b", r"\binvalid pointer\b", "is safe contradicts invalid pointer error"),
        (r"\bis\s+safe\b", r"\bundefined\s+behavior\b", "is safe contradicts undefined behavior"),
        (r"\bcompletely\s+safe\b", r"\bundefined\s+behavior\b", "completely safe contradicts UB"),
    ]

    # Word form normalization for lemmatization
    LEMMA_MAP = {
        "dereferencing": "dereference",
        "overflows": "overflow",
        "overflowing": "overflow",
        "dividing": "division",
        "allocating": "allocation",
        "allocates": "allocation",
    }

    # Action categories for semantic understanding
    # Distinguishes between different types of operations that may superficially seem similar
    ACTION_CATEGORIES = {
        # Syntactic transformations (no runtime effect on object state)
        "syntactic": [
            r"\bcast\b",
            r"\bstatic_cast\b",
            r"\breinterpret_cast\b",
            r"\bconst_cast\b",
            r"\bdynamic_cast\b",
        ],
        # Semantic transfers (changes object state/ownership)
        # Note: Exclude "std::move" from patterns - it's a function name, not an action
        "transfer": [
            r"(?<!std::)(?<!::)\bmoves\b",  # "moves" but not part of "std::move"
            r"(?<!std::)(?<!::)\btransfer\b",
            r"\btransfers ownership\b",
            r"\btransfer ownership\b",
        ],
        # Duplication (creates new object)
        "duplication": [
            r"\bcopy\b",
            r"\bcopies\b",
            r"\bduplicate\b",
            r"\bclone\b",
        ],
    }

    # Pattern to extract numeric assertions like "size() == 0" or "count() != 1"
    NUMERIC_ASSERTION_PATTERN = re.compile(
        r"\b(\w+\(\))\s*(==|!=|<=|>=|<|>)\s*(\d+)",
        re.IGNORECASE,
    )

    # Terse axiom patterns that imply negative polarity (error condition)
    # These are K-semantics axioms that describe UB without saying "undefined"
    IMPLICIT_ERROR_PATTERNS = [
        r"signed integer overflow",
        r"null pointer",
        r"division by zero",
        r"buffer overflow",
        r"uninitialized",
        r"out of bounds",
        r"dangling pointer",
        r"use after free",
        r"double.?free",          # Matches "double free" or "double-free"
        r"already freed",         # State descriptor for double-free scenarios
        r"freed memory",          # State descriptor
        r"deallocated memory",    # State descriptor
        r"invalid pointer",       # Generic invalid pointer state
        r"integer division",      # Often describes error condition
    ]

    def classify(self, claim: str, axiom: dict) -> EntailmentResult:
        """Determine if axiom supports, contradicts, or is neutral to claim.

        Args:
            claim: The claim text to check.
            axiom: Dict with 'content', 'formal_spec', and optional metadata.

        Returns:
            EntailmentResult with relationship, confidence, and explanation.
        """
        axiom_content = axiom.get("content", "")

        # Extract polarities
        claim_polarity = self._extract_polarity(claim)
        axiom_polarity = self._extract_polarity(axiom_content)

        # Axioms from error contexts or with violated_by are implicitly negative
        if self._is_error_axiom(axiom):
            axiom_polarity = "negative"

        # Terse axioms that match error patterns are implicitly negative
        # e.g., "Signed integer overflow" without explicit "undefined" keyword
        if axiom_polarity == "neutral" and self._matches_error_pattern(axiom_content):
            axiom_polarity = "negative"

        # Check for numeric value contradictions FIRST (e.g., size()==1 vs size()==0)
        # These are strong signals that don't require topic overlap
        claim_numerics = self._extract_numeric_assertions(claim)
        # Parse both content and formal_spec for axiom numerics
        axiom_numerics = self._extract_numeric_assertions(axiom_content)
        formal_numerics = self._extract_numeric_assertions(axiom.get("formal_spec", ""))
        axiom_numerics.update(formal_numerics)

        if claim_numerics and axiom_numerics:
            contradicts, explanation = self._numeric_values_contradict(
                claim_numerics, axiom_numerics
            )
            if contradicts:
                return EntailmentResult(
                    relationship="CONTRADICTS",
                    confidence=0.90,
                    explanation=f"Numeric contradiction: {explanation}",
                )

        # Check topic overlap
        claim_topics = self._extract_topics(claim)
        axiom_topics = self._extract_topics(axiom_content)
        topic_overlap = claim_topics & axiom_topics

        # No topic overlap = just related
        if not topic_overlap:
            return EntailmentResult(
                relationship="RELATED_TO",
                confidence=0.3,
                explanation="No topic overlap between claim and axiom",
            )

        # Check for semantic action contradictions (e.g., "cast" vs "move")
        # This catches cases where both appear positive but describe incompatible actions
        claim_action = self._extract_action_category(claim)
        axiom_action = self._extract_action_category(axiom_content)

        if claim_action and axiom_action and claim_action != axiom_action:
            return EntailmentResult(
                relationship="CONTRADICTS",
                confidence=0.85,
                explanation=(
                    f"Claim describes {claim_action} action but axiom describes "
                    f"{axiom_action} action - these are semantically incompatible"
                ),
            )

        # Check for semantic opposition patterns (e.g., "single-pass" vs "multi-pass")
        opposition = self._check_semantic_opposition(claim, axiom_content)
        if opposition:
            return EntailmentResult(
                relationship="CONTRADICTS",
                confidence=0.88,
                explanation=f"Semantic opposition: {opposition}",
            )

        # Positive claim vs Negative axiom = CONTRADICTION
        if claim_polarity == "positive" and axiom_polarity == "negative":
            return EntailmentResult(
                relationship="CONTRADICTS",
                confidence=0.9,
                explanation=(
                    f"Claim asserts positive behavior ({claim_polarity}), "
                    f"but axiom indicates error/UB condition"
                ),
            )

        # Negative claim vs Negative axiom = SUPPORTS
        if claim_polarity == "negative" and axiom_polarity == "negative":
            return EntailmentResult(
                relationship="SUPPORTS",
                confidence=0.8,
                explanation="Both claim and axiom indicate undefined/error behavior",
            )

        # Positive claim vs Positive axiom = SUPPORTS
        if claim_polarity == "positive" and axiom_polarity == "positive":
            return EntailmentResult(
                relationship="SUPPORTS",
                confidence=0.7,
                explanation="Both claim and axiom assert positive behavior",
            )

        # Negative claim vs Positive axiom = potential contradiction
        if claim_polarity == "negative" and axiom_polarity == "positive":
            return EntailmentResult(
                relationship="CONTRADICTS",
                confidence=0.7,
                explanation="Claim asserts error/UB but axiom indicates defined behavior",
            )

        # Neutral polarity = just related
        return EntailmentResult(
            relationship="RELATED_TO",
            confidence=0.5,
            explanation="Topic overlap but no clear polarity conflict",
        )

    def _extract_polarity(self, text: str) -> Literal["positive", "negative", "neutral"]:
        """Extract polarity from text.

        Args:
            text: The text to analyze.

        Returns:
            "positive", "negative", or "neutral" polarity.
        """
        text_lower = text.lower()

        # Check for negative indicators FIRST (they're more specific and
        # should take precedence over positive indicators)
        # e.g., "Operation requires: pointer is valid" should be negative
        # even though it contains "is valid"
        for indicator in self.NEGATIVE_INDICATORS:
            if indicator.lower() in text_lower:
                return "negative"

        # Check for positive indicators
        for indicator in self.POSITIVE_INDICATORS:
            if indicator.lower() in text_lower:
                return "positive"

        return "neutral"

    def _extract_topics(self, text: str) -> set[str]:
        """Extract topics from text using pattern matching.

        Args:
            text: The text to analyze.

        Returns:
            Set of topic names found in text.
        """
        # Apply lemmatization first
        normalized = self._lemmatize(text)
        topics = set()

        for topic, patterns in self.TOPIC_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, normalized, re.IGNORECASE):
                    topics.add(topic)
                    break  # Found this topic, move to next

        return topics

    def _lemmatize(self, text: str) -> str:
        """Apply simple lemmatization for word form normalization.

        Args:
            text: The text to normalize.

        Returns:
            Text with word forms normalized.
        """
        result = text
        for word, lemma in self.LEMMA_MAP.items():
            result = re.sub(rf"\b{word}\b", lemma, result, flags=re.IGNORECASE)
        return result

    def _extract_action_category(self, text: str) -> str | None:
        """Extract action category from text to detect semantic contradictions.

        Args:
            text: The text to analyze.

        Returns:
            Action category ("syntactic", "transfer", "duplication") or None.
        """
        text_lower = text.lower()

        # Check categories in priority order: duplication > transfer > syntactic
        # This ensures "copies" is detected before "moves" in ambiguous text
        priority_order = ["duplication", "transfer", "syntactic"]

        for category in priority_order:
            if category in self.ACTION_CATEGORIES:
                for pattern in self.ACTION_CATEGORIES[category]:
                    if re.search(pattern, text_lower):
                        return category
        return None

    def _is_error_axiom(self, axiom: dict) -> bool:
        """Check if axiom is from an error context.

        Args:
            axiom: Axiom dict with optional metadata.

        Returns:
            True if axiom is from error/UB context.
        """
        # Check violated_by field
        if axiom.get("violated_by"):
            return True

        # Check module name for error patterns
        module = axiom.get("module", "")
        error_modules = ["ERROR", "VIOLATION", "UB", "UNDEFINED"]
        if any(err in module.upper() for err in error_modules):
            return True

        return False

    def _matches_error_pattern(self, text: str) -> bool:
        """Check if text matches known error condition patterns.

        These are terse descriptions that imply UB without explicitly saying
        "undefined behavior".

        Args:
            text: The text to check.

        Returns:
            True if text matches a known error pattern.
        """
        text_lower = text.lower()
        for pattern in self.IMPLICIT_ERROR_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _extract_numeric_assertions(self, text: str) -> dict[str, tuple[str, int]]:
        """Extract numeric assertions like 'size() == 0' from text.

        Args:
            text: The text to analyze.

        Returns:
            Dict mapping function name to (operator, value).
            Example: {"size()": ("==", 0)}
        """
        assertions = {}
        for match in self.NUMERIC_ASSERTION_PATTERN.finditer(text):
            func_name = match.group(1).lower()
            operator = match.group(2)
            value = int(match.group(3))
            assertions[func_name] = (operator, value)
        return assertions

    def _numeric_values_contradict(
        self,
        claim_nums: dict[str, tuple[str, int]],
        axiom_nums: dict[str, tuple[str, int]],
    ) -> tuple[bool, str]:
        """Check if numeric assertions contradict.

        Args:
            claim_nums: Numeric assertions from claim.
            axiom_nums: Numeric assertions from axiom.

        Returns:
            Tuple of (contradicts, explanation).
        """
        for func_name, (claim_op, claim_val) in claim_nums.items():
            if func_name not in axiom_nums:
                continue

            axiom_op, axiom_val = axiom_nums[func_name]

            # Both assert equality to different values
            if claim_op == "==" and axiom_op == "==" and claim_val != axiom_val:
                return (
                    True,
                    f"{func_name} == {claim_val} contradicts {func_name} == {axiom_val}",
                )

            # Claim asserts equality, axiom asserts inequality to same value
            if claim_op == "==" and axiom_op == "!=" and claim_val == axiom_val:
                return (
                    True,
                    f"{func_name} == {claim_val} contradicts {func_name} != {axiom_val}",
                )

            # Claim asserts inequality, axiom asserts equality to same value
            if claim_op == "!=" and axiom_op == "==" and claim_val == axiom_val:
                return (
                    True,
                    f"{func_name} != {claim_val} contradicts {func_name} == {axiom_val}",
                )

        return False, ""

    def _check_semantic_opposition(self, claim: str, axiom_content: str) -> str | None:
        """Check if claim and axiom have semantic opposition patterns.

        Args:
            claim: The claim text.
            axiom_content: The axiom content text.

        Returns:
            Explanation string if opposition found, None otherwise.
        """
        claim_lower = claim.lower()
        axiom_lower = axiom_content.lower()

        for claim_pattern, axiom_pattern, explanation in self.SEMANTIC_OPPOSITIONS:
            if (
                re.search(claim_pattern, claim_lower, re.IGNORECASE)
                and re.search(axiom_pattern, axiom_lower, re.IGNORECASE)
            ):
                return explanation

        return None
