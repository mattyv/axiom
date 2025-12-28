"""Tests for K semantics extractor."""

from pathlib import Path

from axiom.extractors.k_semantics import KSemanticsExtractor, ParsedRule
from axiom.models import Axiom


class TestKSemanticsExtractor:
    """Tests for KSemanticsExtractor."""

    def test_extractor_parses_k_file(self, multiplicative_k: Path) -> None:
        """Extractor should parse a K file and return rules."""
        extractor = KSemanticsExtractor(multiplicative_k.parent.parent.parent.parent)
        rules = extractor.parse_file(multiplicative_k)

        assert isinstance(rules, list)
        assert len(rules) > 0
        assert all(isinstance(r, ParsedRule) for r in rules)

    def test_extractor_finds_module_name(self, multiplicative_k: Path) -> None:
        """Extractor should identify the module name."""
        extractor = KSemanticsExtractor(multiplicative_k.parent.parent.parent.parent)
        rules = extractor.parse_file(multiplicative_k)

        # All rules from this file should have the same module
        modules = {r.module for r in rules}
        assert "C-COMMON-EXPR-MULTIPLICATIVE" in modules

    def test_extractor_finds_requires_clauses(self, multiplicative_k: Path) -> None:
        """Extractor should extract requires clauses from rules."""
        extractor = KSemanticsExtractor(multiplicative_k.parent.parent.parent.parent)
        rules = extractor.parse_file(multiplicative_k)

        rules_with_requires = [r for r in rules if r.requires]
        assert len(rules_with_requires) > 0

        # Check for known requires clause patterns
        requires_texts = [r.requires for r in rules_with_requires]
        assert any("isPromoted" in req for req in requires_texts)
        assert any("isZero" in req for req in requires_texts)

    def test_extractor_identifies_error_markers(self, multiplicative_k: Path) -> None:
        """Extractor should identify UNDEF/CV/IMPL error markers."""
        extractor = KSemanticsExtractor(multiplicative_k.parent.parent.parent.parent)
        rules = extractor.parse_file(multiplicative_k)

        error_rules = [r for r in rules if r.error_marker]
        assert len(error_rules) > 0

        # Check for known error markers from multiplicative.k
        error_codes = [r.error_marker.code for r in error_rules if r.error_marker]
        assert "CEMX1" in error_codes  # Division by 0
        assert "CEMX2" in error_codes  # Modulus by 0

    def test_extractor_extracts_error_marker_details(self, multiplicative_k: Path) -> None:
        """Extractor should extract error type, code, and message."""
        extractor = KSemanticsExtractor(multiplicative_k.parent.parent.parent.parent)
        rules = extractor.parse_file(multiplicative_k)

        error_rules = [r for r in rules if r.error_marker]
        cemx1_rule = next((r for r in error_rules if r.error_marker and r.error_marker.code == "CEMX1"), None)

        assert cemx1_rule is not None
        assert cemx1_rule.error_marker.error_type == "UNDEF"
        assert cemx1_rule.error_marker.code == "CEMX1"
        assert "division" in cemx1_rule.error_marker.message.lower() or "0" in cemx1_rule.error_marker.message

    def test_extractor_distinguishes_axiom_vs_error_rules(self, multiplicative_k: Path) -> None:
        """Extractor should distinguish positive rules (axioms) from error rules."""
        extractor = KSemanticsExtractor(multiplicative_k.parent.parent.parent.parent)
        rules = extractor.parse_file(multiplicative_k)

        axiom_rules = [r for r in rules if r.requires and not r.error_marker]
        error_rules = [r for r in rules if r.error_marker]

        # Both should exist in multiplicative.k
        assert len(axiom_rules) > 0, "Should have positive rules (axioms)"
        assert len(error_rules) > 0, "Should have error rules"

    def test_extract_axioms_from_file(self, multiplicative_k: Path) -> None:
        """Extractor should convert rules to Axiom objects."""
        extractor = KSemanticsExtractor(multiplicative_k.parent.parent.parent.parent)
        axioms = extractor.extract_axioms_from_file(multiplicative_k)

        assert isinstance(axioms, list)
        assert len(axioms) > 0
        assert all(isinstance(a, Axiom) for a in axioms)

        # Check axiom properties
        for axiom in axioms:
            assert axiom.id
            assert axiom.formal_spec
            assert axiom.source.module == "C-COMMON-EXPR-MULTIPLICATIVE"
            assert axiom.layer == "c11_core"
            assert axiom.confidence == 1.0

    def test_extract_all_from_directory(self, c_semantics_root: Path) -> None:
        """Extractor should process all K files in a directory."""
        semantics_dir = c_semantics_root / "semantics" / "c"
        extractor = KSemanticsExtractor(semantics_dir)
        axioms = extractor.extract_all()

        assert isinstance(axioms, list)
        assert len(axioms) > 50  # Should find many axioms across all files

        # Check that we have axioms from multiple modules
        modules = {a.source.module for a in axioms}
        assert len(modules) > 5


class TestParsedRule:
    """Tests for ParsedRule dataclass."""

    def test_parsed_rule_has_required_fields(self) -> None:
        """ParsedRule should have all required fields."""
        rule = ParsedRule(
            lhs="tv(I1:Int, T::UType) / tv(I2:Int, T'::UType)",
            rhs="intArithInterpret(T, I1 /Int I2)",
            requires="isPromoted(T) andBool notBool isZero(I2)",
            module="C-COMMON-EXPR-MULTIPLICATIVE",
            source_file="multiplicative.k",
            error_marker=None,
            attributes=["structural"],
        )

        assert rule.lhs
        assert rule.rhs
        assert rule.requires
        assert rule.module
        assert rule.source_file
        assert rule.error_marker is None
        assert "structural" in rule.attributes
