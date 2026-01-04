# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for macro semantic extraction.

These tests verify that:
- Macros with lambda captures generate CONSTRAINT axioms
- Macros with template calls generate COMPLEXITY axioms
- Incomplete macros generate CONSTRAINT axioms about companions
- Macros creating local vars generate POSTCONDITION axioms
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


class TestMacroLambdaCapture:
    """Tests for macro lambda capture detection."""

    def test_reference_capture_generates_constraint(self):
        """Macro with [&] capture should generate CONSTRAINT axiom."""
        code = """
        #define CAPTURE_REF(body) [&]() { body; }()

        void test() {
            int x = 0;
            CAPTURE_REF(x++);
        }
        """
        axioms = extract_axioms(code)

        # Should have constraint about reference capture
        constraint = [a for a in axioms if a.axiom_type == AxiomType.CONSTRAINT
                     and "capture" in a.content.lower()]
        assert len(constraint) > 0, f"Expected CONSTRAINT for [&] capture, got: {[a.content for a in axioms]}"

    def test_reference_capture_generates_anti_pattern(self):
        """Macro with [&] capture should generate ANTI_PATTERN about dangling refs."""
        code = """
        #define FOR_EACH(container, body) [&]() { for (auto& x : container) { body; } }()
        """
        axioms = extract_axioms(code)

        # Should have anti-pattern about temporaries
        anti = [a for a in axioms if a.axiom_type == AxiomType.ANTI_PATTERN
               and ("dangle" in a.content.lower() or "temporary" in a.content.lower())]
        assert len(anti) > 0, f"Expected ANTI_PATTERN for dangling reference, got: {[a.content for a in axioms]}"


class TestMacroTemplateCall:
    """Tests for macro template call detection."""

    def test_template_call_generates_complexity(self):
        """Macro calling template<N> should generate COMPLEXITY axiom."""
        code = """
        #define UNROLL(N, body) ::impl::unroll<N>([&]() { body; })
        """
        axioms = extract_axioms(code)

        # Should have complexity about template instantiation
        complexity = [a for a in axioms if a.axiom_type == AxiomType.COMPLEXITY
                     and ("template" in a.content.lower() or "instantiat" in a.content.lower())]
        assert len(complexity) > 0, f"Expected COMPLEXITY for template call, got: {[a.content for a in axioms]}"


class TestMacroIncomplete:
    """Tests for incomplete macro detection."""

    def test_incomplete_macro_generates_constraint(self):
        """Macro with unclosed braces should generate CONSTRAINT about companion."""
        code = """
        #define BEGIN_BLOCK { if (true) {
        #define END_BLOCK } }
        """
        axioms = extract_axioms(code)

        # Should have constraint about requiring companion
        constraint = [a for a in axioms if a.axiom_type == AxiomType.CONSTRAINT
                     and ("companion" in a.content.lower() or "incomplete" in a.content.lower()
                          or "completion" in a.content.lower())]
        assert len(constraint) > 0, f"Expected CONSTRAINT for incomplete macro, got: {[a.content for a in axioms]}"


class TestMacroLocalVars:
    """Tests for macro local variable detection."""

    def test_local_vars_generate_postcondition(self):
        """Macro creating __xyz vars should generate POSTCONDITION about scope."""
        code = """
        #define SETUP_CONTEXT auto __ctx = make_context(); auto __guard = ctx_guard(__ctx);
        """
        axioms = extract_axioms(code)

        # Should have postcondition about available identifiers
        postcond = [a for a in axioms if a.axiom_type == AxiomType.POSTCONDITION
                   and ("__ctx" in a.content or "__guard" in a.content
                        or "available" in a.content.lower() or "scope" in a.content.lower())]
        assert len(postcond) > 0, f"Expected POSTCONDITION for local vars, got: {[a.content for a in axioms]}"


class TestMacroLoopConstruct:
    """Tests for macro loop detection."""

    def test_loop_generates_effect(self):
        """Macro with for/while loop should generate EFFECT axiom."""
        code = """
        #define ITERATE(n, body) for (int __i = 0; __i < n; ++__i) { body; }
        """
        axioms = extract_axioms(code)

        # Should have effect about iteration
        effect = [a for a in axioms if a.axiom_type == AxiomType.EFFECT
                 and ("iterat" in a.content.lower() or "loop" in a.content.lower())]
        assert len(effect) > 0, f"Expected EFFECT for loop construct, got: {[a.content for a in axioms]}"


class TestMacroHazards:
    """Tests for existing hazard-based macro extraction."""

    def test_division_generates_precondition(self):
        """Macro with division should generate PRECONDITION about zero divisor."""
        code = """
        #define SAFE_DIV(a, b) ((a) / (b))
        """
        axioms = extract_axioms(code)

        # Should have precondition about divisor
        precond = [a for a in axioms if a.axiom_type == AxiomType.PRECONDITION
                  and ("divisor" in a.content.lower() or "zero" in a.content.lower())]
        assert len(precond) > 0, f"Expected PRECONDITION for division, got: {[a.content for a in axioms]}"
