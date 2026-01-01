"""Tests for the error code linker module."""


from axiom.extractors.error_linker import ErrorCodeLinker
from axiom.models import Axiom, ErrorCode, ErrorType, SourceLocation, ViolationRef


def create_test_axiom(
    id: str = "test_axiom",
    formal_spec: str = "isZero(x)",
    module: str = "expr-div",
    tags: list = None,
) -> Axiom:
    """Create a test axiom."""
    return Axiom(
        id=id,
        content="Test axiom content",
        formal_spec=formal_spec,
        layer="c11_core",
        source=SourceLocation(file="test.k", module=module),
        tags=tags or [],
    )


def create_test_error_code(
    code: str = "UB-SE-DIV1",
    internal_code: str = "SE-DIV1",
    description: str = "Division by zero",
    error_type: ErrorType = ErrorType.UNDEFINED_BEHAVIOR,
) -> ErrorCode:
    """Create a test error code."""
    return ErrorCode(
        code=code,
        internal_code=internal_code,
        description=description,
        type=error_type,
    )


class TestErrorCodeLinker:
    """Tests for ErrorCodeLinker class."""

    def test_link_returns_collection(self):
        """Test that link returns an AxiomCollection."""
        linker = ErrorCodeLinker()
        axioms = [create_test_axiom()]
        error_codes = [create_test_error_code()]

        result = linker.link(axioms, error_codes)

        assert result is not None
        assert result.axioms == axioms
        assert result.error_codes == error_codes

    def test_link_empty_lists(self):
        """Test linking with empty lists."""
        linker = ErrorCodeLinker()

        result = linker.link([], [])

        assert result.axioms == []
        assert result.error_codes == []

    def test_link_via_patterns_matches_zero(self):
        """Test pattern matching for zero-related axioms and errors."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            id="div_by_zero",
            formal_spec="isZero(divisor)",
            tags=["zero", "division"],
        )
        error = create_test_error_code(
            internal_code="SE-DIV1",
            description="Division by zero is undefined behavior",
        )

        result = linker.link([axiom], [error])

        # Should have linked via pattern matching
        assert len(result.axioms[0].violated_by) > 0
        violation = result.axioms[0].violated_by[0]
        assert violation.code == "SE-DIV1"

    def test_link_via_patterns_matches_pointer(self):
        """Test pattern matching for pointer-related axioms and errors."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            id="null_ptr",
            formal_spec="isPointer(p) and not isNull(p)",
            tags=["pointer", "integer"],
        )
        error = create_test_error_code(
            internal_code="SE-PTR1",
            description="Invalid pointer dereference on integer type",
        )

        result = linker.link([axiom], [error])

        # Should match on pointer + integer terms
        assert len(result.axioms[0].violated_by) > 0

    def test_link_updates_error_code_validates_axioms(self):
        """Test that linked error codes track which axioms they validate."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            id="test_axiom_1",
            formal_spec="isZero(x)",
            tags=["zero", "division"],
        )
        # Add a pre-existing violation
        axiom.violated_by = [
            ViolationRef(code="SE-DIV1", error_type="UB", message="Division by zero")
        ]

        error = create_test_error_code(internal_code="SE-DIV1")

        result = linker.link([axiom], [error])

        # Error code should know it validates this axiom
        assert "test_axiom_1" in result.error_codes[0].validates_axioms

    def test_no_duplicate_violations(self):
        """Test that the same violation is not added twice."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            id="dup_test",
            formal_spec="isZero(x)",
            tags=["zero", "division"],
        )
        error = create_test_error_code(
            internal_code="SE-DIV1",
            description="Division by zero is undefined",
        )

        # Link twice
        linker.link([axiom], [error])
        result = linker.link([axiom], [error])

        # Should not have duplicate violations
        codes = [v.code for v in result.axioms[0].violated_by]
        assert codes.count("SE-DIV1") == 1

    def test_weak_match_not_linked(self):
        """Test that axioms with only one matching term are not linked."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            id="weak_match",
            formal_spec="someCheck(x)",
            tags=["integer"],  # Only one term
        )
        error = create_test_error_code(
            internal_code="SE-INT1",
            description="Integer overflow",  # Only integer matches
        )

        result = linker.link([axiom], [error])

        # Should not link - only 1 common term (need >= 2)
        assert len(result.axioms[0].violated_by) == 0


class TestExtractPredicates:
    """Tests for _extract_predicates method."""

    def test_extracts_common_predicates(self):
        """Test extracting common K predicates."""
        linker = ErrorCodeLinker()

        spec = "isPromoted(T) andBool isZero(V) andBool hasIntegerType(T)"
        predicates = linker._extract_predicates(spec)

        assert "isPromoted" in predicates
        assert "isZero" in predicates
        assert "hasIntegerType" in predicates

    def test_extracts_type_comparison(self):
        """Test extracting type comparison predicates."""
        linker = ErrorCodeLinker()

        spec = "T1 ==Type T2 orBool T1 =/=Type T3"
        predicates = linker._extract_predicates(spec)

        assert "==Type" in predicates
        assert "=/=Type" in predicates

    def test_extracts_pointer_predicates(self):
        """Test extracting pointer-related predicates."""
        linker = ErrorCodeLinker()

        spec = "isPointer(P) andBool isComplete(type(P))"
        predicates = linker._extract_predicates(spec)

        assert "isPointer" in predicates
        assert "isComplete" in predicates

    def test_empty_spec_returns_empty_set(self):
        """Test that empty spec returns empty set."""
        linker = ErrorCodeLinker()

        predicates = linker._extract_predicates("")
        assert predicates == set()

        predicates = linker._extract_predicates(None)
        assert predicates == set()


class TestExtractErrorTerms:
    """Tests for _extract_error_terms method."""

    def test_extracts_division_terms(self):
        """Test extracting division-related terms."""
        linker = ErrorCodeLinker()

        terms = linker._extract_error_terms("Division by zero is undefined")
        assert "division" in terms
        assert "zero" in terms

    def test_extracts_pointer_terms(self):
        """Test extracting pointer-related terms."""
        linker = ErrorCodeLinker()

        terms = linker._extract_error_terms("Invalid pointer to integer conversion")
        assert "pointer" in terms
        assert "integer" in terms
        assert "conversion" in terms

    def test_extracts_shift_terms(self):
        """Test extracting shift-related terms."""
        linker = ErrorCodeLinker()

        terms = linker._extract_error_terms("Shift by negative amount")
        assert "shift" in terms

    def test_extracts_overflow_terms(self):
        """Test extracting overflow-related terms."""
        linker = ErrorCodeLinker()

        terms = linker._extract_error_terms("Integer overflow in arithmetic")
        assert "overflow" in terms
        assert "integer" in terms


class TestExtractAxiomTerms:
    """Tests for _extract_axiom_terms method."""

    def test_extracts_from_tags(self):
        """Test extracting terms from axiom tags."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(tags=["division", "integer", "zero"])
        terms = linker._extract_axiom_terms(axiom)

        assert "division" in terms
        assert "integer" in terms
        assert "zero" in terms

    def test_extracts_from_formal_spec(self):
        """Test extracting terms from formal spec."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(formal_spec="isPointer(p) andBool hasIntegerType(t)")
        terms = linker._extract_axiom_terms(axiom)

        assert "pointer" in terms
        assert "integer" in terms

    def test_extracts_zero_from_iszero(self):
        """Test that isZero in spec adds zero term."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(formal_spec="notBool isZero(divisor)")
        terms = linker._extract_axiom_terms(axiom)

        assert "zero" in terms


class TestIsStrongMatch:
    """Tests for _is_strong_match method."""

    def test_strong_match_with_multiple_terms(self):
        """Test strong match when multiple terms overlap."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            formal_spec="isZero(x)",
            tags=["zero", "division", "integer"],
        )
        error = create_test_error_code(
            description="Division by zero produces undefined integer result",
        )

        assert linker._is_strong_match(axiom, error) is True

    def test_weak_match_with_single_term(self):
        """Test weak match when only one term overlaps."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            formal_spec="someCheck(x)",
            tags=["integer"],
        )
        error = create_test_error_code(
            description="Integer overflow",
        )

        assert linker._is_strong_match(axiom, error) is False


class TestRulesAreRelated:
    """Tests for _rules_are_related method."""

    def test_related_via_common_predicates(self):
        """Test that rules with common predicates are related."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            formal_spec="isPromoted(T) andBool isZero(V) andBool hasIntegerType(T)"
        )

        # Mock error rule with similar predicates
        class MockErrorRule:
            requires = "isPromoted(T) andBool hasIntegerType(T) andBool isZero(V)"

        error_rule = MockErrorRule()

        assert linker._rules_are_related(axiom, error_rule) is True

    def test_related_via_negation(self):
        """Test that rules are related when one negates the other."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(formal_spec="notBool isZero(V)")

        class MockErrorRule:
            requires = "isZero(V)"

        error_rule = MockErrorRule()

        assert linker._rules_are_related(axiom, error_rule) is True

    def test_not_related_without_requires(self):
        """Test that rules without requires are not related."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom()

        class MockErrorRule:
            pass  # No requires attribute

        error_rule = MockErrorRule()

        assert linker._rules_are_related(axiom, error_rule) is False

    def test_not_related_with_empty_requires(self):
        """Test that rules with empty requires are not related."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom()

        class MockErrorRule:
            requires = ""

        error_rule = MockErrorRule()

        assert linker._rules_are_related(axiom, error_rule) is False


class TestLinkViaErrorRules:
    """Tests for _link_via_error_rules method."""

    def test_links_axiom_to_error_via_rules(self):
        """Test linking axioms to errors using error rules."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            id="div_axiom",
            formal_spec="isPromoted(T) andBool isZero(V) andBool hasIntegerType(T)",
            module="expr-div",
        )

        class MockErrorMarker:
            code = "SE-DIV1"
            error_type = "UB"
            message = "Division by zero"

        class MockErrorRule:
            module = "expr-div"
            error_marker = MockErrorMarker()
            requires = "isPromoted(T) andBool isZero(V) andBool hasIntegerType(T)"

        error_rules = [MockErrorRule()]

        linker._link_via_error_rules([axiom], error_rules)

        assert len(axiom.violated_by) == 1
        assert axiom.violated_by[0].code == "SE-DIV1"

    def test_skips_rules_without_error_marker(self):
        """Test that rules without error markers are skipped."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(module="expr-div")

        class MockErrorRule:
            module = "expr-div"
            # No error_marker

        error_rules = [MockErrorRule()]

        linker._link_via_error_rules([axiom], error_rules)

        assert len(axiom.violated_by) == 0

    def test_skips_rules_from_different_module(self):
        """Test that rules from different modules are not linked."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            formal_spec="isPromoted(T) andBool isZero(V) andBool hasIntegerType(T)",
            module="expr-add",  # Different module
        )

        class MockErrorMarker:
            code = "SE-DIV1"
            error_type = "UB"
            message = "Division by zero"

        class MockErrorRule:
            module = "expr-div"  # Different from axiom
            error_marker = MockErrorMarker()
            requires = "isPromoted(T) andBool isZero(V) andBool hasIntegerType(T)"

        error_rules = [MockErrorRule()]

        linker._link_via_error_rules([axiom], error_rules)

        assert len(axiom.violated_by) == 0

    def test_no_duplicate_violations_from_rules(self):
        """Test that the same violation is not added twice from rules."""
        linker = ErrorCodeLinker()

        axiom = create_test_axiom(
            formal_spec="isPromoted(T) andBool isZero(V) andBool hasIntegerType(T)",
            module="expr-div",
        )
        # Pre-add a violation
        axiom.violated_by = [
            ViolationRef(code="SE-DIV1", error_type="UB", message="Existing")
        ]

        class MockErrorMarker:
            code = "SE-DIV1"
            error_type = "UB"
            message = "Division by zero"

        class MockErrorRule:
            module = "expr-div"
            error_marker = MockErrorMarker()
            requires = "isPromoted(T) andBool isZero(V) andBool hasIntegerType(T)"

        error_rules = [MockErrorRule()]

        linker._link_via_error_rules([axiom], error_rules)

        # Should still only have one violation
        assert len(axiom.violated_by) == 1
