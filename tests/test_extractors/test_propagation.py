# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for precondition propagation."""


from axiom.extractors.propagation import propagate_preconditions
from axiom.models import Axiom, AxiomType, SourceLocation


def make_axiom(
    id: str,
    content: str,
    function: str,
    axiom_type: AxiomType = AxiomType.PRECONDITION,
    formal_spec: str = "",
    confidence: float = 1.0,
) -> Axiom:
    """Helper to create test axioms."""
    return Axiom(
        id=id,
        content=content,
        formal_spec=formal_spec,
        function=function,
        source=SourceLocation(file="test.h", module="test"),
        layer="user_library",
        axiom_type=axiom_type,
        confidence=confidence,
        depends_on=[],
    )


class TestPropagatePreconditions:
    """Tests for propagate_preconditions function."""

    def test_empty_call_graph(self):
        """Test with empty call graph returns original axioms."""
        axioms = [
            make_axiom("div.precond", "divisor != 0", "divide", formal_spec="b != 0"),
        ]

        result = propagate_preconditions(axioms, [])

        assert len(result) == 1
        assert result[0].id == "div.precond"

    def test_empty_axioms(self):
        """Test with empty axioms returns empty list."""
        call_graph = [{"caller": "foo", "callee": "bar", "line": 10}]

        result = propagate_preconditions([], call_graph)

        assert len(result) == 0

    def test_propagate_simple_precondition(self):
        """Test that callee precondition propagates to caller."""
        axioms = [
            make_axiom(
                "mylib.divide.precond.divisor",
                "divisor must not be zero",
                "mylib::divide",
                formal_spec="b != 0",
            ),
        ]
        call_graph = [
            {
                "caller": "mylib::processData",
                "callee": "mylib::divide",
                "line": 25,
            },
        ]

        result = propagate_preconditions(axioms, call_graph)

        assert len(result) == 2
        # Original axiom should be preserved
        assert any(a.id == "mylib.divide.precond.divisor" for a in result)
        # Propagated axiom should be created
        propagated = [a for a in result if "propagated" in a.id]
        assert len(propagated) == 1
        assert propagated[0].function == "mylib::processData"
        assert "divisor" in propagated[0].id
        assert "Inherited from mylib::divide" in propagated[0].content
        assert propagated[0].formal_spec == "b != 0"
        assert propagated[0].confidence == 0.85
        assert propagated[0].axiom_type == AxiomType.PRECONDITION

    def test_propagated_axiom_depends_on_original(self):
        """Test that propagated axiom has depends_on link."""
        axioms = [
            make_axiom(
                "foo.precond",
                "ptr not null",
                "foo",
                formal_spec="ptr != nullptr",
            ),
        ]
        call_graph = [{"caller": "bar", "callee": "foo", "line": 10}]

        result = propagate_preconditions(axioms, call_graph)

        propagated = [a for a in result if "propagated" in a.id]
        assert len(propagated) == 1
        assert propagated[0].depends_on == ["foo.precond"]

    def test_no_propagation_for_non_preconditions(self):
        """Test that only preconditions are propagated."""
        axioms = [
            make_axiom(
                "foo.noexcept",
                "foo does not throw",
                "foo",
                axiom_type=AxiomType.EXCEPTION,
            ),
            make_axiom(
                "foo.const",
                "foo is const",
                "foo",
                axiom_type=AxiomType.EFFECT,
            ),
        ]
        call_graph = [{"caller": "bar", "callee": "foo", "line": 10}]

        result = propagate_preconditions(axioms, call_graph)

        # No propagation for non-preconditions
        assert len(result) == 2
        assert not any("propagated" in a.id for a in result)

    def test_multiple_preconditions_propagate(self):
        """Test that multiple preconditions from callee propagate."""
        axioms = [
            make_axiom(
                "div.precond.a",
                "a must be positive",
                "divide",
                formal_spec="a > 0",
            ),
            make_axiom(
                "div.precond.b",
                "b must not be zero",
                "divide",
                formal_spec="b != 0",
            ),
        ]
        call_graph = [{"caller": "calc", "callee": "divide", "line": 5}]

        result = propagate_preconditions(axioms, call_graph)

        assert len(result) == 4  # 2 original + 2 propagated
        propagated = [a for a in result if "propagated" in a.id]
        assert len(propagated) == 2

    def test_chain_propagation_through_call_graph(self):
        """Test propagation through multiple levels: A -> B -> C."""
        axioms = [
            make_axiom(
                "c.precond",
                "x must be valid",
                "C",
                formal_spec="x != nullptr",
            ),
        ]
        call_graph = [
            {"caller": "B", "callee": "C", "line": 10},
            {"caller": "A", "callee": "B", "line": 20},
        ]

        result = propagate_preconditions(axioms, call_graph)

        # Original + B's propagated
        # Note: A doesn't get C's precond directly (single-level propagation)
        assert len(result) == 2
        propagated = [a for a in result if "propagated" in a.id]
        assert len(propagated) == 1
        assert propagated[0].function == "B"

    def test_deduplicate_propagated_axioms(self):
        """Test that same precondition isn't propagated multiple times."""
        axioms = [
            make_axiom(
                "foo.precond",
                "valid input",
                "foo",
                formal_spec="x > 0",
            ),
        ]
        # Same caller calls same callee multiple times
        call_graph = [
            {"caller": "bar", "callee": "foo", "line": 10},
            {"caller": "bar", "callee": "foo", "line": 20},
        ]

        result = propagate_preconditions(axioms, call_graph)

        # Should only propagate once
        propagated = [a for a in result if "propagated" in a.id]
        assert len(propagated) == 1

    def test_virtual_dispatch_flag_preserved(self):
        """Test that call graph entries with is_virtual are processed."""
        axioms = [
            make_axiom(
                "base.precond",
                "valid state",
                "Base::method",
                formal_spec="state != null",
            ),
        ]
        call_graph = [
            {
                "caller": "Client::use",
                "callee": "Base::method",
                "line": 15,
                "is_virtual": True,
            },
        ]

        result = propagate_preconditions(axioms, call_graph)

        # Virtual calls should still propagate preconditions
        propagated = [a for a in result if "propagated" in a.id]
        assert len(propagated) == 1

    def test_caller_with_existing_precondition_not_duplicated(self):
        """Test that if caller already has precondition, it's not re-added."""
        axioms = [
            make_axiom(
                "callee.precond",
                "x not null",
                "callee",
                formal_spec="x != nullptr",
            ),
            # Caller already has same precondition
            make_axiom(
                "caller.precond",
                "x not null (existing)",
                "caller",
                formal_spec="x != nullptr",
            ),
        ]
        call_graph = [{"caller": "caller", "callee": "callee", "line": 10}]

        result = propagate_preconditions(axioms, call_graph)

        # Propagated is still added since we check by ID, not formal_spec
        # The guard_map check would prevent if caller had a guard
        propagated = [a for a in result if "propagated" in a.id]
        # For now, propagation happens even if duplicate formal_spec exists
        # This is correct - the caller might have its own independent precondition
        assert len(propagated) == 1


class TestEdgeCases:
    """Edge case tests for propagation."""

    def test_missing_caller_field(self):
        """Test handling of malformed call graph entry."""
        axioms = [
            make_axiom("foo.precond", "valid", "foo"),
        ]
        call_graph = [{"callee": "foo", "line": 10}]  # Missing caller

        # Should handle gracefully
        result = propagate_preconditions(axioms, call_graph)
        assert len(result) == 1  # Only original, no crash

    def test_missing_callee_field(self):
        """Test handling of malformed call graph entry."""
        axioms = [
            make_axiom("foo.precond", "valid", "foo"),
        ]
        call_graph = [{"caller": "bar", "line": 10}]  # Missing callee

        result = propagate_preconditions(axioms, call_graph)
        assert len(result) == 1  # Only original, no crash

    def test_callee_not_in_axioms(self):
        """Test call to function without preconditions."""
        axioms = [
            make_axiom("unrelated.precond", "valid", "unrelated"),
        ]
        call_graph = [{"caller": "bar", "callee": "foo", "line": 10}]

        result = propagate_preconditions(axioms, call_graph)
        assert len(result) == 1  # Only original

    def test_self_recursive_call(self):
        """Test handling of recursive calls."""
        axioms = [
            make_axiom("rec.precond", "n >= 0", "recursive", formal_spec="n >= 0"),
        ]
        call_graph = [{"caller": "recursive", "callee": "recursive", "line": 5}]

        result = propagate_preconditions(axioms, call_graph)
        # Self-call creates propagated with same function name but different ID
        propagated = [a for a in result if "propagated" in a.id]
        assert len(propagated) == 1
        assert propagated[0].function == "recursive"
