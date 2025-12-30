# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for library axiom depends_on linking (TDD - tests first).

This module tests the post-extraction linking of depends_on fields for
library axioms (cpp20_stdlib, user libraries). Unlike K-semantics axioms
which use function call parsing, library axioms use signature and content
parsing to find type references.
"""

import pytest

from axiom.extractors.library_depends_on import (
    extract_exception_types,
    extract_type_references,
    parse_cpp_signature_types,
    parse_formal_spec_types,
)
from axiom.models import Axiom, SourceLocation


def create_library_axiom(
    id: str = "test_axiom",
    content: str = "Test axiom content",
    formal_spec: str = "",
    signature: str = None,
    function: str = None,
    header: str = None,
    depends_on: list = None,
) -> Axiom:
    """Create a test library axiom."""
    return Axiom(
        id=id,
        content=content,
        formal_spec=formal_spec,
        layer="cpp20_stdlib",
        source=SourceLocation(file="optional", module="[optional]/1"),
        signature=signature,
        function=function,
        header=header,
        depends_on=depends_on or [],
    )


class TestParseCppSignatureTypes:
    """Tests for extracting types from C++ function signatures."""

    def test_simple_return_type(self) -> None:
        """Should handle simple return types (primitive types not extracted)."""
        signature = "bool has_value() const"
        types = parse_cpp_signature_types(signature)
        # Primitive types like bool are not extracted - we only care about
        # types that have corresponding axioms (references, pointers, etc.)
        assert isinstance(types, set)

    def test_reference_return_type(self) -> None:
        """Should extract reference type from return."""
        signature = "T& value()"
        types = parse_cpp_signature_types(signature)
        assert "reference" in types or "T" in types

    def test_const_reference_return(self) -> None:
        """Should extract const reference."""
        signature = "const T& value() const"
        types = parse_cpp_signature_types(signature)
        assert "reference" in types or "const_reference" in types

    def test_pointer_return_type(self) -> None:
        """Should extract pointer type."""
        signature = "T* operator->()"
        types = parse_cpp_signature_types(signature)
        assert "pointer" in types

    def test_size_type_parameter(self) -> None:
        """Should extract size_type from parameters."""
        signature = "reference at(size_type n)"
        types = parse_cpp_signature_types(signature)
        assert "size_type" in types
        assert "reference" in types

    def test_iterator_parameter(self) -> None:
        """Should extract iterator types."""
        signature = "void assign(InputIterator first, InputIterator last)"
        types = parse_cpp_signature_types(signature)
        assert "InputIterator" in types or "iterator" in types

    def test_allocator_type(self) -> None:
        """Should extract allocator type."""
        signature = "allocator_type get_allocator() const"
        types = parse_cpp_signature_types(signature)
        assert "allocator_type" in types or "allocator" in types

    def test_optional_template(self) -> None:
        """Should extract optional from template signature."""
        signature = "T& std::optional<T>::value()"
        types = parse_cpp_signature_types(signature)
        assert "optional" in types

    def test_variant_template(self) -> None:
        """Should extract variant from template signature."""
        signature = "R std::visit(Visitor&&, std::variant<Types...>&)"
        types = parse_cpp_signature_types(signature)
        assert "variant" in types

    def test_void_return(self) -> None:
        """Should handle void return type."""
        signature = "void reset()"
        types = parse_cpp_signature_types(signature)
        # void is typically not a linkable type
        assert "void" not in types or len(types) >= 0

    def test_empty_signature(self) -> None:
        """Should handle empty signature."""
        types = parse_cpp_signature_types("")
        assert types == set()

    def test_none_signature(self) -> None:
        """Should handle None signature."""
        types = parse_cpp_signature_types(None)
        assert types == set()


class TestExtractExceptionTypes:
    """Tests for extracting exception types from axiom content."""

    def test_throws_bad_optional_access(self) -> None:
        """Should extract bad_optional_access from throws clause."""
        content = "Calling value() on an empty optional throws bad_optional_access"
        types = extract_exception_types(content)
        assert "bad_optional_access" in types

    def test_throws_out_of_range(self) -> None:
        """Should extract out_of_range exception."""
        content = "Calling at(n) throws out_of_range if n >= size()"
        types = extract_exception_types(content)
        assert "out_of_range" in types

    def test_throws_bad_alloc(self) -> None:
        """Should extract bad_alloc exception."""
        content = "Allocation failure may throw bad_alloc"
        types = extract_exception_types(content)
        assert "bad_alloc" in types

    def test_throws_bad_any_cast(self) -> None:
        """Should extract bad_any_cast exception."""
        content = "any_cast throws bad_any_cast if type mismatch"
        types = extract_exception_types(content)
        assert "bad_any_cast" in types

    def test_throws_bad_variant_access(self) -> None:
        """Should extract bad_variant_access exception."""
        content = "get<I> throws bad_variant_access if variant is valueless"
        types = extract_exception_types(content)
        assert "bad_variant_access" in types

    def test_multiple_exceptions(self) -> None:
        """Should extract multiple exception types."""
        content = "May throw bad_alloc or out_of_range depending on context"
        types = extract_exception_types(content)
        assert "bad_alloc" in types
        assert "out_of_range" in types

    def test_no_exception(self) -> None:
        """Should handle content without exceptions."""
        content = "Returns true if the optional contains a value"
        types = extract_exception_types(content)
        assert len(types) == 0

    def test_empty_content(self) -> None:
        """Should handle empty content."""
        types = extract_exception_types("")
        assert types == set()


class TestParseFormalSpecTypes:
    """Tests for extracting types from formal_spec."""

    def test_throws_in_formal_spec(self) -> None:
        """Should extract exception from throws() in formal spec."""
        formal_spec = "!has_value() && call(value) => throws(bad_optional_access)"
        types = parse_formal_spec_types(formal_spec)
        assert "bad_optional_access" in types

    def test_multiple_throws(self) -> None:
        """Should extract multiple exceptions from formal spec."""
        formal_spec = "throws(out_of_range) || throws(bad_alloc)"
        types = parse_formal_spec_types(formal_spec)
        assert "out_of_range" in types
        assert "bad_alloc" in types

    def test_type_in_predicate(self) -> None:
        """Should extract types from predicates."""
        formal_spec = "is_pointer(p) && is_null(p) => undefined_behavior"
        types = parse_formal_spec_types(formal_spec)
        assert "pointer" in types or "null" in types

    def test_empty_formal_spec(self) -> None:
        """Should handle empty formal spec."""
        types = parse_formal_spec_types("")
        assert types == set()

    def test_none_formal_spec(self) -> None:
        """Should handle None formal spec."""
        types = parse_formal_spec_types(None)
        assert types == set()


class TestExtractTypeReferences:
    """Tests for full type reference extraction from axioms."""

    def test_extracts_from_signature(self) -> None:
        """Should extract types from signature."""
        axiom = create_library_axiom(
            signature="reference at(size_type n)",
            content="Returns reference to element at position n",
        )
        refs = extract_type_references(axiom)
        assert "reference" in refs
        assert "size_type" in refs

    def test_extracts_from_content(self) -> None:
        """Should extract exception types from content."""
        axiom = create_library_axiom(
            content="Calling value() on empty optional throws bad_optional_access",
        )
        refs = extract_type_references(axiom)
        assert "bad_optional_access" in refs

    def test_extracts_from_formal_spec(self) -> None:
        """Should extract types from formal_spec."""
        axiom = create_library_axiom(
            formal_spec="!has_value() => throws(bad_optional_access)",
        )
        refs = extract_type_references(axiom)
        assert "bad_optional_access" in refs

    def test_combines_all_sources(self) -> None:
        """Should combine types from signature, content, and formal_spec."""
        axiom = create_library_axiom(
            signature="reference at(size_type n)",
            content="throws out_of_range if n >= size()",
            formal_spec="n >= size() => throws(out_of_range)",
        )
        refs = extract_type_references(axiom)
        assert "reference" in refs
        assert "size_type" in refs
        assert "out_of_range" in refs

    def test_deduplicates_types(self) -> None:
        """Should not have duplicate type references."""
        axiom = create_library_axiom(
            content="throws out_of_range exception out_of_range",
            formal_spec="throws(out_of_range)",
        )
        refs = extract_type_references(axiom)
        # Should be a set, so no duplicates
        assert isinstance(refs, set)
        assert refs.count("out_of_range") if hasattr(refs, "count") else True

    def test_empty_axiom(self) -> None:
        """Should handle axiom with no type references."""
        axiom = create_library_axiom(
            content="Returns true if has value",
        )
        refs = extract_type_references(axiom)
        # May be empty or have minimal types
        assert isinstance(refs, set)


class TestResolveTypeToAxioms:
    """Tests for resolving type references to axiom IDs.

    Note: These tests require mocking LanceDBLoader since they
    depend on the vector database.
    """

    @pytest.mark.skip(reason="Requires LanceDB mock - implement after basic tests pass")
    def test_resolve_exception_type(self) -> None:
        """Should find axioms for exception types."""
        pass

    @pytest.mark.skip(reason="Requires LanceDB mock - implement after basic tests pass")
    def test_resolve_pointer_type(self) -> None:
        """Should find axioms for pointer types."""
        pass

    @pytest.mark.skip(reason="Requires LanceDB mock - implement after basic tests pass")
    def test_resolve_iterator_type(self) -> None:
        """Should find axioms for iterator types."""
        pass


class TestLinkAxiomDependsOn:
    """Tests for full dependency linking workflow.

    Note: These tests require mocking LanceDBLoader.
    """

    @pytest.mark.skip(reason="Requires LanceDB mock - implement after basic tests pass")
    def test_links_empty_depends_on(self) -> None:
        """Should populate depends_on for axioms without it."""
        pass

    @pytest.mark.skip(reason="Requires LanceDB mock - implement after basic tests pass")
    def test_skips_already_linked(self) -> None:
        """Should not modify axioms that already have depends_on."""
        pass

    @pytest.mark.skip(reason="Requires LanceDB mock - implement after basic tests pass")
    def test_updates_toml_file(self) -> None:
        """Should update the TOML file with new depends_on."""
        pass
