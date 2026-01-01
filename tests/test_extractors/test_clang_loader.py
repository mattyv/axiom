# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for clang_loader module."""

from datetime import datetime, timezone

import pytest

from axiom.models import AxiomType
from axiom.extractors.clang_loader import (
    load_from_string,
    parse_json,
    _parse_axiom,
)


class TestParseAxiom:
    """Tests for _parse_axiom function."""

    def test_parse_constraint_axiom(self):
        """Test parsing a constraint axiom."""
        data = {
            "id": "mylib.MyClass.getValue.noexcept",
            "content": "getValue is guaranteed not to throw exceptions",
            "formal_spec": "noexcept == true",
            "function": "MyClass::getValue",
            "signature": "int MyClass::getValue() const noexcept",
            "header": "mylib/MyClass.h",
            "axiom_type": "EXCEPTION",
            "confidence": 1.0,
            "source_type": "explicit",
            "line": 42,
        }

        axiom = _parse_axiom(data)

        assert axiom.id == "mylib.MyClass.getValue.noexcept"
        assert axiom.content == "getValue is guaranteed not to throw exceptions"
        assert axiom.formal_spec == "noexcept == true"
        assert axiom.function == "MyClass::getValue"
        assert axiom.signature == "int MyClass::getValue() const noexcept"
        assert axiom.header == "mylib/MyClass.h"
        assert axiom.axiom_type == AxiomType.EXCEPTION
        assert axiom.confidence == 1.0
        assert axiom.layer == "user_library"
        assert axiom.source.file == "mylib/MyClass.h"
        assert axiom.source.line_start == 42
        assert axiom.depends_on == []

    def test_parse_precondition_axiom(self):
        """Test parsing a precondition axiom from hazard detection."""
        data = {
            "id": "mylib.divide.precond.divisor_nonzero",
            "content": "Divisor must not be zero",
            "formal_spec": "b != 0",
            "function": "divide",
            "signature": "int divide(int a, int b)",
            "header": "mylib/math.h",
            "axiom_type": "PRECONDITION",
            "confidence": 0.95,
            "source_type": "pattern",
            "line": 15,
        }

        axiom = _parse_axiom(data)

        assert axiom.axiom_type == AxiomType.PRECONDITION
        assert axiom.confidence == 0.95
        assert axiom.layer == "user_library"

    def test_parse_with_defaults(self):
        """Test parsing with minimal data uses defaults."""
        data = {
            "id": "test.axiom",
            "content": "Test axiom content",
        }

        axiom = _parse_axiom(data)

        assert axiom.id == "test.axiom"
        assert axiom.content == "Test axiom content"
        assert axiom.axiom_type == AxiomType.CONSTRAINT
        assert axiom.confidence == 1.0
        assert axiom.formal_spec == ""  # Required field, defaults to empty
        assert axiom.function is None
        assert axiom.source.line_start is None

    def test_parse_all_axiom_types(self):
        """Test parsing all axiom types."""
        type_mapping = {
            "PRECONDITION": AxiomType.PRECONDITION,
            "POSTCONDITION": AxiomType.POSTCONDITION,
            "INVARIANT": AxiomType.INVARIANT,
            "EXCEPTION": AxiomType.EXCEPTION,
            "EFFECT": AxiomType.EFFECT,
            "CONSTRAINT": AxiomType.CONSTRAINT,
            "ANTI_PATTERN": AxiomType.ANTI_PATTERN,
            "COMPLEXITY": AxiomType.COMPLEXITY,
        }

        for json_type, expected_type in type_mapping.items():
            data = {
                "id": f"test.{json_type.lower()}",
                "content": f"Test {json_type}",
                "axiom_type": json_type,
            }
            axiom = _parse_axiom(data)
            assert axiom.axiom_type == expected_type, f"Failed for {json_type}"


class TestParseJson:
    """Tests for parse_json function."""

    def test_parse_empty_output(self):
        """Test parsing empty output."""
        data = {"axioms": []}
        collection = parse_json(data)

        assert len(collection.axioms) == 0

    def test_parse_with_axioms(self):
        """Test parsing output with axioms."""
        data = {
            "version": "1.0",
            "extracted_at": "2026-01-01T12:00:00Z",
            "source_files": ["src/foo.cpp", "src/bar.cpp"],
            "axioms": [
                {
                    "id": "foo.bar.noexcept",
                    "content": "bar does not throw",
                    "axiom_type": "EXCEPTION",
                },
                {
                    "id": "foo.baz.const",
                    "content": "baz does not modify state",
                    "axiom_type": "EFFECT",
                },
            ],
        }

        collection = parse_json(data, source="test")

        assert collection.version == "1.0"
        assert len(collection.axioms) == 2
        assert collection.axioms[0].id == "foo.bar.noexcept"
        assert collection.axioms[1].id == "foo.baz.const"

    def test_parse_timestamp(self):
        """Test parsing ISO timestamp."""
        data = {
            "extracted_at": "2026-01-01T12:00:00Z",
            "axioms": [],
        }

        collection = parse_json(data)

        assert collection.extracted_at is not None
        assert collection.extracted_at.year == 2026
        assert collection.extracted_at.month == 1
        assert collection.extracted_at.day == 1

    def test_parse_source_files_summary(self):
        """Test that source files are summarized."""
        data = {
            "source_files": ["a.cpp", "b.cpp", "c.cpp", "d.cpp", "e.cpp"],
            "axioms": [],
        }

        collection = parse_json(data)

        # Should include first 3 and count
        assert "a.cpp" in collection.source
        assert "(+2 more)" in collection.source


class TestLoadFromString:
    """Tests for load_from_string function."""

    def test_load_valid_json(self):
        """Test loading valid JSON string."""
        json_str = """{
            "version": "1.0",
            "axioms": [
                {
                    "id": "test.axiom",
                    "content": "Test content",
                    "axiom_type": "CONSTRAINT"
                }
            ]
        }"""

        collection = load_from_string(json_str)

        assert len(collection.axioms) == 1
        assert collection.axioms[0].id == "test.axiom"

    def test_load_with_custom_source(self):
        """Test loading with custom source identifier."""
        json_str = '{"axioms": []}'

        collection = load_from_string(json_str, source="my-library")

        # Source is derived from source_files or source parameter
        assert collection.source == "my-library"
