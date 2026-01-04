# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for effect detection from C++ code.

These tests verify that parameter modifications, member writes,
memory operations, and container mutations are correctly detected
and extracted as EFFECT axioms.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from axiom.extractors.clang_loader import parse_json
from axiom.models import AxiomType


def find_axiom_extract() -> Path | None:
    """Find the axiom-extract binary."""
    candidates = [
        Path(__file__).parent.parent.parent
        / "tools"
        / "axiom-extract"
        / "build"
        / "axiom-extract",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


AXIOM_EXTRACT = find_axiom_extract()
pytestmark = pytest.mark.skipif(
    AXIOM_EXTRACT is None, reason="axiom-extract binary not found"
)


def extract_axioms(code: str) -> list:
    """Run axiom-extract on code and return axioms."""
    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
        f.write(code)
        f.flush()
        temp_path = Path(f.name)

    try:
        result = subprocess.run(
            [str(AXIOM_EXTRACT), str(temp_path), "--", "-std=c++20"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and not result.stdout:
            pytest.skip(f"Clang failed: {result.stderr}")

        data = json.loads(result.stdout)
        collection = parse_json(data)
        return collection.axioms
    finally:
        temp_path.unlink()


class TestParameterModification:
    """Tests for detecting parameter modifications."""

    def test_direct_parameter_assignment(self):
        """Direct assignment to reference parameter should be detected."""
        code = """
        void set_value(int& x) {
            x = 42;
        }
        """
        axioms = extract_axioms(code)

        # Should have an EFFECT axiom about modifying x
        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        assert len(effect_axioms) > 0, f"No EFFECT axioms in {[a.id for a in axioms]}"

        # Should mention the parameter
        param_effects = [a for a in effect_axioms if "x" in a.content.lower()]
        assert len(param_effects) > 0, "No effects mentioning parameter x"

    def test_increment_parameter(self):
        """Increment of parameter should be detected."""
        code = """
        void increment(int& count) {
            count++;
        }
        """
        axioms = extract_axioms(code)

        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        assert len(effect_axioms) > 0, f"No EFFECT axioms in {[a.id for a in axioms]}"

    def test_pointer_parameter_write(self):
        """Write through pointer parameter should be detected."""
        code = """
        void write_ptr(int* ptr) {
            *ptr = 100;
        }
        """
        axioms = extract_axioms(code)

        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        assert len(effect_axioms) > 0, f"No EFFECT axioms in {[a.id for a in axioms]}"

    def test_const_parameter_no_effect(self):
        """Const reference parameter should NOT generate effect."""
        code = """
        int read_only(const int& x) {
            return x * 2;
        }
        """
        axioms = extract_axioms(code)

        # Should NOT have EFFECT axioms (const means no modification)
        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        assert len(effect_axioms) == 0, "Unexpected EFFECT axioms for const param"


class TestMemberWrite:
    """Tests for detecting member variable writes."""

    def test_direct_member_assignment(self):
        """Direct member assignment should be detected."""
        code = """
        class Counter {
            int value_;
        public:
            void set(int v) {
                value_ = v;
            }
        };
        """
        axioms = extract_axioms(code)

        # Should have an EFFECT axiom for the set method
        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        assert len(effect_axioms) > 0, f"No EFFECT axioms in {[a.id for a in axioms]}"

    def test_member_increment(self):
        """Member increment should be detected."""
        code = """
        class Counter {
            int count_;
        public:
            void increment() {
                count_++;
            }
        };
        """
        axioms = extract_axioms(code)

        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        assert len(effect_axioms) > 0, f"No EFFECT axioms in {[a.id for a in axioms]}"

    def test_const_method_no_effect(self):
        """Const method should NOT generate member effect."""
        code = """
        class Counter {
            int count_;
        public:
            int get() const {
                return count_;
            }
        };
        """
        axioms = extract_axioms(code)

        # Const methods shouldn't have member modification effects
        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        member_effects = [a for a in effect_axioms if "member" in a.content.lower() or "count" in a.content.lower()]
        assert len(member_effects) == 0, "Unexpected member EFFECT in const method"


class TestMemoryOperations:
    """Tests for detecting memory operations."""

    def test_new_allocation(self):
        """new expression should be detected."""
        code = """
        int* allocate() {
            return new int(42);
        }
        """
        axioms = extract_axioms(code)

        # Should have EFFECT for memory allocation
        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        alloc_effects = [a for a in effect_axioms if "alloc" in a.content.lower() or "new" in a.content.lower() or "memory" in a.content.lower()]
        assert len(alloc_effects) > 0, f"No allocation EFFECT in {[a.content for a in effect_axioms]}"

    def test_delete_deallocation(self):
        """delete expression should be detected."""
        code = """
        void deallocate(int* ptr) {
            delete ptr;
        }
        """
        axioms = extract_axioms(code)

        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        dealloc_effects = [a for a in effect_axioms if "dealloc" in a.content.lower() or "delete" in a.content.lower() or "free" in a.content.lower() or "memory" in a.content.lower()]
        assert len(dealloc_effects) > 0, f"No deallocation EFFECT in {[a.content for a in effect_axioms]}"

    def test_array_new(self):
        """new[] expression should be detected."""
        code = """
        int* allocate_array(size_t n) {
            return new int[n];
        }
        """
        axioms = extract_axioms(code)

        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        assert len(effect_axioms) > 0, "No EFFECT for array allocation"


class TestContainerModification:
    """Tests for detecting container modifications."""

    @pytest.mark.xfail(reason="Container effect detection not yet implemented")
    def test_vector_push_back(self):
        """vector::push_back should be detected."""
        code = """
        #include <vector>
        void add_item(std::vector<int>& v, int x) {
            v.push_back(x);
        }
        """
        axioms = extract_axioms(code)

        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        container_effects = [a for a in effect_axioms if "push" in a.content.lower() or "container" in a.content.lower() or "vector" in a.content.lower() or "modif" in a.content.lower()]
        assert len(container_effects) > 0 or len(effect_axioms) > 0, f"No container EFFECT in {[a.content for a in axioms if a.axiom_type == AxiomType.EFFECT]}"

    @pytest.mark.xfail(reason="Container effect detection not yet implemented")
    def test_vector_clear(self):
        """vector::clear should be detected."""
        code = """
        #include <vector>
        void clear_all(std::vector<int>& v) {
            v.clear();
        }
        """
        axioms = extract_axioms(code)

        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        assert len(effect_axioms) > 0, "No EFFECT for vector::clear"

    @pytest.mark.xfail(reason="Container effect detection not yet implemented")
    def test_map_insert(self):
        """map::insert should be detected."""
        code = """
        #include <map>
        void add_entry(std::map<int, int>& m, int k, int v) {
            m.insert({k, v});
        }
        """
        axioms = extract_axioms(code)

        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        assert len(effect_axioms) > 0, "No EFFECT for map::insert"


class TestEffectConfidence:
    """Tests for effect confidence levels."""

    def test_direct_assignment_high_confidence(self):
        """Direct assignment should have high confidence (>= 0.90)."""
        code = """
        void set(int& x) {
            x = 10;
        }
        """
        axioms = extract_axioms(code)

        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        if effect_axioms:
            assert effect_axioms[0].confidence >= 0.90, f"Low confidence {effect_axioms[0].confidence}"

    def test_member_write_high_confidence(self):
        """Member write should have high confidence (>= 0.90)."""
        code = """
        class Foo {
            int x_;
        public:
            void set(int v) { x_ = v; }
        };
        """
        axioms = extract_axioms(code)

        effect_axioms = [a for a in axioms if a.axiom_type == AxiomType.EFFECT]
        if effect_axioms:
            assert effect_axioms[0].confidence >= 0.90, f"Low confidence {effect_axioms[0].confidence}"
