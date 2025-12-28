# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Link axioms to error codes based on shared formal specifications."""


from axiom.models import Axiom, AxiomCollection, ErrorCode, ViolationRef


class AxiomLinker:
    """Link axioms to their corresponding error codes."""

    def __init__(self) -> None:
        """Initialize the linker."""
        self._axiom_by_condition: dict[str, list[Axiom]] = {}
        self._error_by_code: dict[str, ErrorCode] = {}

    def link(
        self,
        axioms: list[Axiom],
        error_codes: list[ErrorCode],
        error_rules: list | None = None,
    ) -> AxiomCollection:
        """Link axioms to error codes and create a collection.

        Args:
            axioms: List of extracted axioms.
            error_codes: List of parsed error codes from CSV.
            error_rules: Optional list of parsed error rules from K files.

        Returns:
            AxiomCollection with linked axioms and error codes.
        """
        # Index error codes by internal code
        self._error_by_code = {ec.internal_code: ec for ec in error_codes}

        # If we have error rules from K files, use them to link
        if error_rules:
            self._link_via_error_rules(axioms, error_rules)

        # Also try to link via formal spec patterns
        self._link_via_patterns(axioms, error_codes)

        # Update error codes with linked axioms
        for axiom in axioms:
            for violation in axiom.violated_by:
                if violation.code in self._error_by_code:
                    ec = self._error_by_code[violation.code]
                    if axiom.id not in ec.validates_axioms:
                        ec.validates_axioms.append(axiom.id)

        return AxiomCollection(
            axioms=axioms,
            error_codes=error_codes,
        )

    def _link_via_error_rules(
        self, axioms: list[Axiom], error_rules: list
    ) -> None:
        """Link axioms to errors using parsed error rules from K files.

        Error rules have the same module and similar conditions as axioms,
        but include an error marker.
        """
        # Group axioms by module
        axioms_by_module: dict[str, list[Axiom]] = {}
        for axiom in axioms:
            module = axiom.source.module
            if module not in axioms_by_module:
                axioms_by_module[module] = []
            axioms_by_module[module].append(axiom)

        # For each error rule, find matching axioms
        for error_rule in error_rules:
            if not hasattr(error_rule, "error_marker") or not error_rule.error_marker:
                continue

            module = error_rule.module
            if module not in axioms_by_module:
                continue

            # Find axioms that the error rule might violate
            for axiom in axioms_by_module[module]:
                if self._rules_are_related(axiom, error_rule):
                    violation = ViolationRef(
                        code=error_rule.error_marker.code,
                        error_type=error_rule.error_marker.error_type,
                        message=error_rule.error_marker.message,
                    )
                    if not any(v.code == violation.code for v in axiom.violated_by):
                        axiom.violated_by.append(violation)

    def _rules_are_related(self, axiom: Axiom, error_rule) -> bool:
        """Check if an axiom and error rule are related.

        They're related if they're in the same module and share
        similar predicates (one being the positive case, one the negative).
        """
        if not hasattr(error_rule, "requires") or not error_rule.requires:
            return False

        # Extract key predicates from both
        axiom_preds = self._extract_predicates(axiom.formal_spec)
        error_preds = self._extract_predicates(error_rule.requires)

        # Check for overlapping predicates
        common = axiom_preds & error_preds
        if len(common) >= 2:  # At least 2 common predicates
            return True

        # Check for negation relationship
        for pred in axiom_preds:
            negated = f"notBool {pred}"
            if negated in error_preds or pred.replace("notBool ", "") in error_preds:
                return True

        return False

    def _extract_predicates(self, spec: str) -> set[str]:
        """Extract key predicates from a K specification."""
        if not spec:
            return set()

        predicates = set()

        # Common predicate patterns
        patterns = [
            "isPromoted",
            "isZero",
            "isUnknown",
            "==Type",
            "=/=Type",
            "isPointer",
            "isInteger",
            "hasIntegerType",
            "isFloat",
            "isComplete",
            "isConst",
        ]

        for pattern in patterns:
            if pattern in spec:
                predicates.add(pattern)

        return predicates

    def _link_via_patterns(
        self, axioms: list[Axiom], error_codes: list[ErrorCode]
    ) -> None:
        """Link axioms to errors using pattern matching on specifications.

        This is a fallback when we don't have parsed error rules.
        """
        # Create a mapping of key terms to error codes
        term_to_errors: dict[str, list[ErrorCode]] = {}

        for ec in error_codes:
            terms = self._extract_error_terms(ec.description)
            for term in terms:
                if term not in term_to_errors:
                    term_to_errors[term] = []
                term_to_errors[term].append(ec)

        # Match axioms to errors based on shared terms
        for axiom in axioms:
            axiom_terms = self._extract_axiom_terms(axiom)

            for term in axiom_terms:
                if term in term_to_errors:
                    for ec in term_to_errors[term]:
                        # Only link if not already linked
                        if not any(v.code == ec.internal_code for v in axiom.violated_by):
                            # Check for stronger match
                            if self._is_strong_match(axiom, ec):
                                violation = ViolationRef(
                                    code=ec.internal_code,
                                    error_type=ec.type.value.upper().replace("_", ""),
                                    message=ec.description,
                                )
                                axiom.violated_by.append(violation)

    def _extract_error_terms(self, description: str) -> set[str]:
        """Extract key terms from error description."""
        terms = set()
        desc_lower = description.lower()

        term_mappings = {
            "division": ["division", "divide", "/"],
            "modulus": ["modulus", "modulo", "%", "remainder"],
            "overflow": ["overflow"],
            "zero": ["zero", "0"],
            "pointer": ["pointer"],
            "integer": ["integer", "int"],
            "float": ["float", "floating"],
            "type": ["type"],
            "conversion": ["conversion", "convert"],
            "shift": ["shift", "<<", ">>"],
        }

        for term, patterns in term_mappings.items():
            if any(p in desc_lower for p in patterns):
                terms.add(term)

        return terms

    def _extract_axiom_terms(self, axiom: Axiom) -> set[str]:
        """Extract key terms from axiom."""
        terms = set()

        # From tags
        terms.update(axiom.tags)

        # From formal spec
        spec_lower = axiom.formal_spec.lower()

        if "zero" in spec_lower or "iszero" in spec_lower:
            terms.add("zero")
        if "pointer" in spec_lower:
            terms.add("pointer")
        if "integer" in spec_lower or "int" in spec_lower:
            terms.add("integer")
        if "float" in spec_lower:
            terms.add("float")
        if "type" in spec_lower:
            terms.add("type")

        return terms

    def _is_strong_match(self, axiom: Axiom, error: ErrorCode) -> bool:
        """Check if axiom and error have a strong semantic match."""
        # Get terms from both
        axiom_terms = self._extract_axiom_terms(axiom)
        error_terms = self._extract_error_terms(error.description)

        # Require at least 2 common terms for a strong match
        common = axiom_terms & error_terms
        return len(common) >= 2
