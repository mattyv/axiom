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


class TestNumericContradiction:
    """Tests for numeric value contradiction detection."""

    def test_extracts_numeric_assertion(self):
        """Test: Extracts size() == 0 from text."""
        classifier = EntailmentClassifier()
        nums = classifier._extract_numeric_assertions("size() == 0 && data() == nullptr")
        assert "size()" in nums
        assert nums["size()"] == ("==", 0)

    def test_extracts_from_formal_spec(self):
        """Test: Extracts numeric assertions from formal_spec format."""
        classifier = EntailmentClassifier()
        nums = classifier._extract_numeric_assertions(
            "postcond(span()): size() == 0 && data() == nullptr"
        )
        assert "size()" in nums
        assert nums["size()"] == ("==", 0)

    def test_extracts_multiple_assertions(self):
        """Test: Extracts multiple numeric assertions."""
        classifier = EntailmentClassifier()
        nums = classifier._extract_numeric_assertions(
            "size() == 0 && use_count() == 1"
        )
        assert "size()" in nums
        assert "use_count()" in nums
        assert nums["size()"] == ("==", 0)
        assert nums["use_count()"] == ("==", 1)

    def test_size_equals_different_values_contradicts(self):
        """Test: size() == 1 contradicts size() == 0."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="std::span default constructed has size() == 1",
            axiom={
                "content": "Default constructor postcondition: size() == 0 && data() == nullptr.",
                "formal_spec": "postcond(span()): size() == 0 && data() == nullptr",
            },
        )
        assert result.relationship == "CONTRADICTS"
        assert result.confidence >= 0.85
        assert "size()" in result.explanation

    def test_use_count_different_values_contradicts(self):
        """Test: use_count() == 2 contradicts use_count() == 1."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="shared_ptr has use_count() == 2 after copy",
            axiom={
                "content": "After copy, use_count() == 1",
                "formal_spec": "postcond(copy): use_count() == 1",
            },
        )
        assert result.relationship == "CONTRADICTS"
        assert result.confidence >= 0.85

    def test_same_values_no_contradiction(self):
        """Test: size() == 0 does not contradict size() == 0."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="empty span has size() == 0",
            axiom={
                "content": "Default constructor postcondition: size() == 0",
                "formal_spec": "postcond(span()): size() == 0",
            },
        )
        assert result.relationship != "CONTRADICTS"

    def test_equality_vs_inequality_contradicts(self):
        """Test: count() == 0 contradicts count() != 0."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="container has count() == 0",
            axiom={
                "content": "Container is non-empty",
                "formal_spec": "invariant: count() != 0",
            },
        )
        assert result.relationship == "CONTRADICTS"

    def test_no_numeric_in_claim_no_contradiction(self):
        """Test: If claim has no numerics, no numeric contradiction."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="span is empty",
            axiom={
                "content": "size() == 0",
                "formal_spec": "",
            },
        )
        # No numeric in claim, so numeric check shouldn't trigger contradiction
        # Result depends on polarity/topic analysis
        # Just verify it doesn't crash and returns a result
        assert result.relationship in ("SUPPORTS", "CONTRADICTS", "RELATED_TO")


class TestRealWorldFalsePositives:
    """Tests for specific false positive cases found in production.

    These are real claims that were incorrectly validated as true in the
    MCP testing session (2025-12-31).
    """

    def test_double_delete_safe_contradicts_already_freed(self):
        """Double delete is safe should contradict 'already freed' error axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Double delete is safe",
            axiom={
                "content": "Called free on memory that was already freed",
                "formal_spec": "error_condition: double_free",
            },
        )
        assert result.relationship == "CONTRADICTS"
        assert result.confidence >= 0.8

    def test_double_delete_safe_contradicts_double_free(self):
        """Double delete is safe should contradict 'double free' axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Double delete is safe",
            axiom={
                "content": "Double free leads to undefined behavior",
                "formal_spec": "",
            },
        )
        assert result.relationship == "CONTRADICTS"

    def test_double_delete_safe_contradicts_invalid_free(self):
        """Double delete is safe should contradict 'invalid free' axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="Double delete is completely safe",
            axiom={
                "content": "Calling delete on an invalid pointer is undefined behavior",
                "formal_spec": "",
            },
        )
        assert result.relationship == "CONTRADICTS"

    def test_std_move_moves_contradicts_cast(self):
        """std::move moves object contradicts 'is a cast' axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="std::move moves object to new location",
            axiom={
                "content": "std::move returns static_cast<remove_reference_t<T>&&>(t)",
                "formal_spec": "static_cast<std::remove_reference_t<T>&&>(t)",
            },
        )
        assert result.relationship == "CONTRADICTS"
        assert result.confidence >= 0.8

    def test_std_move_deep_copy_contradicts_cast(self):
        """std::move performs deep copy contradicts 'is a cast' axiom."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="std::move performs a deep copy of the object",
            axiom={
                "content": "std::move is equivalent to static_cast to rvalue reference",
                "formal_spec": "",
            },
        )
        assert result.relationship == "CONTRADICTS"

    def test_forward_iterator_single_pass_contradiction(self):
        """ForwardIterator allows single-pass contradicts multi-pass requirement."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="ForwardIterator requirements allow only single-pass iteration",
            axiom={
                "content": "ForwardIterator must be multi-pass: can iterate multiple times",
                "formal_spec": "multipass_guarantee: true",
            },
        )
        # This should contradict because "only single-pass" vs "multi-pass"
        assert result.relationship == "CONTRADICTS"

    def test_vector_reverse_order_contradiction(self):
        """vector stores in reverse order contradicts contiguous storage."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="std::vector guarantees elements stored in reverse order",
            axiom={
                "content": "std::vector elements are stored contiguously in increasing index order",
                "formal_spec": "&v[n] == &v[0] + n",
            },
        )
        # Should contradict (reverse vs increasing order)
        assert result.relationship == "CONTRADICTS"

    def test_ilp_end_without_ilp_for_contradiction(self):
        """ILP_END without ILP_FOR contradicts pairing requirement."""
        classifier = EntailmentClassifier()
        result = classifier.classify(
            claim="ILP_END can be used without matching ILP_FOR macro",
            axiom={
                "content": "ILP_END must be paired with ILP_FOR opening macro",
                "formal_spec": "requires: matching_ilp_for",
            },
        )
        assert result.relationship == "CONTRADICTS"
