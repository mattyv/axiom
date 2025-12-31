"""Tests for EntailmentClassifier - claim vs axiom relationship detection."""


from axiom.reasoning.entailment import EntailmentClassifier


class TestPolarityExtraction:
    """Tests for polarity extraction from text."""

    def test_positive_polarity_wraps_around(self):
        """Test 'wraps around' is detected as positive polarity."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("overflow wraps around")
        assert polarity == "positive"

    def test_positive_polarity_twos_complement(self):
        """Test 'two's complement' is detected as positive polarity."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("uses two's complement arithmetic")
        assert polarity == "positive"

    def test_positive_polarity_is_safe(self):
        """Test 'is safe' is detected as positive polarity."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("dereferencing is safe")
        assert polarity == "positive"

    def test_positive_polarity_is_defined(self):
        """Test 'is defined' is detected as positive polarity."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("the behavior is defined")
        assert polarity == "positive"

    def test_positive_polarity_well_defined(self):
        """Test 'well-defined' is detected as positive polarity."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("this operation is well-defined")
        assert polarity == "positive"

    def test_negative_polarity_undefined_behavior(self):
        """Test 'undefined behavior' is detected as negative polarity."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("this is undefined behavior")
        assert polarity == "negative"

    def test_negative_polarity_undefined(self):
        """Test 'undefined' alone is detected as negative polarity."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("the result is undefined")
        assert polarity == "negative"

    def test_negative_polarity_must_not(self):
        """Test 'must not' is detected as negative polarity (K-semantics)."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("pointer must not be null")
        assert polarity == "negative"

    def test_negative_polarity_operation_requires(self):
        """Test 'Operation requires:' is detected as negative polarity (K-semantics)."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("Operation requires: pointer is valid")
        assert polarity == "negative"

    def test_negative_polarity_requires_not(self):
        """Test 'requires: NOT' is detected as negative polarity (K-semantics)."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("requires: NOT: isNull(ptr)")
        assert polarity == "negative"

    def test_neutral_polarity_descriptive(self):
        """Test neutral/descriptive text has neutral polarity."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity("Signed integer overflow")
        assert polarity == "neutral"


class TestTopicExtraction:
    """Tests for topic extraction from text."""

    def test_extracts_overflow_topic(self):
        """Test overflow topic is extracted."""
        classifier = EntailmentClassifier()
        topics = classifier._extract_topics("Signed integer overflow in C")
        assert "overflow" in topics

    def test_extracts_null_pointer_topic(self):
        """Test null pointer topic is extracted."""
        classifier = EntailmentClassifier()
        topics = classifier._extract_topics("Dereferencing a null pointer")
        assert "null_pointer" in topics

    def test_extracts_division_topic(self):
        """Test division by zero topic is extracted."""
        classifier = EntailmentClassifier()
        topics = classifier._extract_topics("Division by zero is undefined")
        assert "division" in topics

    def test_extracts_multiple_topics(self):
        """Test multiple topics can be extracted."""
        classifier = EntailmentClassifier()
        topics = classifier._extract_topics("null pointer and overflow")
        assert "null_pointer" in topics
        assert "overflow" in topics


class TestEntailmentClassification:
    """Tests for the main classify() method."""

    def test_contradicts_wraps_around_vs_undefined_axiom(self):
        """Key test: 'wraps around' claim contradicts UB axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Signed integer overflow wraps around",
            axiom={"content": "Signed integer overflow", "formal_spec": ""},
        )
        assert result.relationship == "CONTRADICTS"

    def test_contradicts_twos_complement_vs_undefined(self):
        """Test: two's complement claim contradicts UB axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Signed integer overflow uses two's complement",
            axiom={"content": "Signed integer overflow is undefined behavior", "formal_spec": ""},
        )
        assert result.relationship == "CONTRADICTS"

    def test_contradicts_safe_vs_must_not(self):
        """Test: 'is safe' claim contradicts 'must not' axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Dereferencing a null pointer is safe",
            axiom={"content": "pointer must not be null", "formal_spec": ""},
        )
        assert result.relationship == "CONTRADICTS"

    def test_contradicts_safe_vs_operation_requires(self):
        """Test: 'is safe' claim contradicts 'Operation requires' axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Dereferencing a null pointer is safe",
            axiom={"content": "Operation requires: must not be a null pointer", "formal_spec": ""},
        )
        assert result.relationship == "CONTRADICTS"

    def test_supports_ub_claim_with_ub_axiom(self):
        """Test: UB claim is supported by UB axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Signed integer overflow is undefined behavior",
            axiom={"content": "Signed integer overflow", "formal_spec": ""},
        )
        assert result.relationship == "SUPPORTS"

    def test_supports_ub_claim_with_must_not_axiom(self):
        """Test: UB claim is supported by 'must not' axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Dereferencing null is undefined behavior",
            axiom={"content": "pointer must not be null", "formal_spec": ""},
        )
        assert result.relationship == "SUPPORTS"

    def test_related_to_when_no_topic_overlap(self):
        """Test: unrelated claim and axiom are RELATED_TO."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Memory allocation returns a pointer",
            axiom={"content": "Array bounds checking", "formal_spec": ""},
        )
        assert result.relationship == "RELATED_TO"

    def test_related_to_when_neutral_polarity(self):
        """Test: neutral polarity results in RELATED_TO."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="The function returns an integer",
            axiom={"content": "Integer conversion rules", "formal_spec": ""},
        )
        assert result.relationship == "RELATED_TO"


class TestErrorAxiomDetection:
    """Tests for detecting error axioms from metadata."""

    def test_axiom_with_violated_by_is_negative(self):
        """Test: axiom with violated_by field is treated as negative."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Division by zero returns zero",
            axiom={
                "content": "Division by zero",
                "formal_spec": "",
                "violated_by": ["E0001"],
            },
        )
        assert result.relationship == "CONTRADICTS"

    def test_axiom_from_error_module_is_negative(self):
        """Test: axiom from error-related module is treated as negative."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Buffer overflow is safe",
            axiom={
                "content": "Buffer access",
                "formal_spec": "",
                "module": "ERROR-MEMORY",
            },
        )
        assert result.relationship == "CONTRADICTS"


class TestConfidenceScores:
    """Tests for confidence scores in results."""

    def test_contradiction_has_high_confidence(self):
        """Test: contradictions have high confidence (>= 0.8)."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Signed overflow wraps around",
            axiom={"content": "Signed integer overflow is undefined", "formal_spec": ""},
        )
        assert result.confidence >= 0.8

    def test_support_has_good_confidence(self):
        """Test: support has good confidence (>= 0.7)."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Signed overflow is undefined behavior",
            axiom={"content": "Signed integer overflow is undefined", "formal_spec": ""},
        )
        assert result.confidence >= 0.7

    def test_related_to_has_lower_confidence(self):
        """Test: RELATED_TO has lower confidence (< 0.7)."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Functions can be called",
            axiom={"content": "Function call semantics", "formal_spec": ""},
        )
        assert result.confidence < 0.7


class TestLemmatization:
    """Tests for word form normalization."""

    def test_dereferencing_matches_dereference(self):
        """Test: 'dereferencing' matches 'dereference' patterns."""
        classifier = EntailmentClassifier()
        # Claim uses gerund, pattern uses base form
        result = classifier.classify(
            claim="Dereferencing a null pointer is safe",
            axiom={"content": "null pointer dereference is undefined", "formal_spec": ""},
        )
        assert result.relationship == "CONTRADICTS"

    def test_overflows_matches_overflow(self):
        """Test: 'overflows' matches 'overflow' patterns."""
        classifier = EntailmentClassifier()
        topics = classifier._extract_topics("when the integer overflows")
        assert "overflow" in topics


class TestActionCategories:
    """Tests for action category extraction and semantic contradiction detection."""

    def test_extracts_syntactic_action_cast(self):
        """Test: 'cast' is detected as syntactic action."""
        classifier = EntailmentClassifier()
        action = classifier._extract_action_category("std::move is a cast")
        assert action == "syntactic"

    def test_extracts_transfer_action_move(self):
        """Test: 'move' is detected as transfer action."""
        classifier = EntailmentClassifier()
        action = classifier._extract_action_category("std::move moves the object")
        assert action == "transfer"

    def test_extracts_duplication_action_copy(self):
        """Test: 'copy' is detected as duplication action."""
        classifier = EntailmentClassifier()
        action = classifier._extract_action_category("std::move copies the object")
        assert action == "duplication"

    def test_contradicts_cast_vs_move(self):
        """Test: Claim about 'move' contradicts axiom about 'cast'."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="std::move moves object to new location",
            axiom={
                "content": "std::move is a cast (static_cast<remove_reference_t<T>&&>(t))",
                "formal_spec": "",
            },
        )
        assert result.relationship == "CONTRADICTS"
        assert result.confidence >= 0.8
        assert "syntactic" in result.explanation or "transfer" in result.explanation

    def test_contradicts_cast_vs_copy(self):
        """Test: Claim about 'copy' contradicts axiom about 'cast'."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="std::move performs a deep copy of the object",
            axiom={
                "content": "std::move is a cast to rvalue reference",
                "formal_spec": "",
            },
        )
        assert result.relationship == "CONTRADICTS"
        assert result.confidence >= 0.8

    def test_no_contradiction_when_same_action_category(self):
        """Test: Same action category doesn't trigger contradiction."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="std::forward is a cast operation",
            axiom={
                "content": "std::forward is static_cast<T&&>(arg)",
                "formal_spec": "",
            },
        )
        # Should not contradict due to action categories (both are syntactic)
        # Might be SUPPORTS or RELATED_TO depending on polarity
        assert result.relationship != "CONTRADICTS" or result.confidence < 0.8


class TestImplicitErrorPatterns:
    """Tests for expanded IMPLICIT_ERROR_PATTERNS including state descriptors."""

    def test_already_freed_detected_as_error(self):
        """Test: 'already freed' is detected as negative/error condition."""
        classifier = EntailmentClassifier()
        polarity = classifier._extract_polarity(
            "Called free on memory that was already freed"
        )
        # Should be detected via _matches_error_pattern since "already freed" is now in IMPLICIT_ERROR_PATTERNS
        assert polarity == "negative" or classifier._matches_error_pattern(
            "Called free on memory that was already freed"
        )

    def test_freed_memory_detected_as_error(self):
        """Test: 'freed memory' is detected as error condition."""
        classifier = EntailmentClassifier()
        assert classifier._matches_error_pattern("Accessing freed memory")

    def test_deallocated_memory_detected_as_error(self):
        """Test: 'deallocated memory' is detected as error condition."""
        classifier = EntailmentClassifier()
        assert classifier._matches_error_pattern("Using deallocated memory")

    def test_double_delete_contradiction(self):
        """Test: 'Double delete is safe' contradicts axiom about freed memory."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Double delete is safe",
            axiom={
                "content": "Called free on memory that was already freed",
                "formal_spec": "",
            },
        )
        # With "already freed" in IMPLICIT_ERROR_PATTERNS, this should contradict
        assert result.relationship == "CONTRADICTS"
        assert result.confidence >= 0.8
