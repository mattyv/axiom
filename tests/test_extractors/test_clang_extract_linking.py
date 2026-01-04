"""Tests for semantic linking in extract_clang.py script."""

from unittest.mock import Mock, patch

import pytest

from axiom.models import Axiom, AxiomType, SourceLocation

# Skip all tests in this module if lancedb is not installed
pytest.importorskip("lancedb", reason="lancedb not installed")


class TestSemanticLinking:
    """Tests for semantic_linker integration in extract_clang.py."""

    def test_link_depends_on_uses_semantic_linker(self):
        """Test that link_depends_on uses semantic_linker instead of naive vector search."""
        # RED: This test will fail because we haven't implemented semantic_linker integration yet
        from scripts.extract_clang import link_depends_on

        # Create test axioms
        axioms = [
            Axiom(
                id="test.precond.ptr_valid",
                content="Pointer must not be null",
                formal_spec="ptr != nullptr",
                axiom_type=AxiomType.PRECONDITION,
                function="test_func",
                signature="void test_func(int* ptr)",
                header="test.h",
                source=SourceLocation(file="test.cpp", module="test_library"),
            )
        ]

        # Mock LanceDB loader and semantic_linker
        mock_loader = Mock()
        mock_loader.db = Mock()
        mock_loader.db.list_tables.return_value = Mock(tables=["axioms"])

        # Mock semantic_linker.search_foundations to return candidate foundation axioms
        mock_candidates = [
            {
                "id": "cpp_core.pointer.nullptr_check",
                "layer": "cpp_core",
                "content": "Dereferencing a null pointer is undefined behavior",
            }
        ]

        with patch("scripts.extract_clang.LanceDBLoader", return_value=mock_loader):
            with patch("scripts.extract_clang.semantic_linker") as mock_semantic:
                # Configure mock to return foundation axioms
                mock_semantic.search_foundations.return_value = mock_candidates
                mock_semantic.merge_depends_on.return_value = ["cpp_core.pointer.nullptr_check"]

                result = link_depends_on(axioms)

                # Verify semantic_linker was used
                assert mock_semantic.search_foundations.called
                assert result[0].depends_on == ["cpp_core.pointer.nullptr_check"]

    def test_link_preserves_existing_depends_on(self):
        """Test that linking merges with existing depends_on instead of replacing."""
        from scripts.extract_clang import link_depends_on

        axioms = [
            Axiom(
                id="test.effect.side_effect",
                content="Modifies global state",
                formal_spec="",
                axiom_type=AxiomType.EFFECT,
                function="test_func",
                depends_on=["existing.dependency"],
                source=SourceLocation(file="test.cpp", module="test_library"),
            )
        ]

        mock_loader = Mock()
        mock_loader.db = Mock()
        mock_loader.db.list_tables.return_value = Mock(tables=["axioms"])

        with patch("scripts.extract_clang.LanceDBLoader", return_value=mock_loader):
            with patch("scripts.extract_clang.semantic_linker") as mock_semantic:
                mock_semantic.search_foundations.return_value = [
                    {"id": "cpp_core.global.modification", "layer": "cpp_core", "content": "..."}
                ]
                # merge_depends_on should merge existing and new
                mock_semantic.merge_depends_on.return_value = [
                    "existing.dependency", "cpp_core.global.modification"
                ]

                result = link_depends_on(axioms)

                # Should merge, not replace
                assert "existing.dependency" in result[0].depends_on
                assert "cpp_core.global.modification" in result[0].depends_on

    def test_link_handles_no_vector_db(self):
        """Test that linking gracefully handles missing vector DB."""
        from scripts.extract_clang import link_depends_on

        axioms = [
            Axiom(
                id="test.precond",
                content="Test",
                formal_spec="",
                axiom_type=AxiomType.PRECONDITION,
                source=SourceLocation(file="test.cpp", module="test_library"),
            )
        ]

        # Mock non-existent vector DB path
        with patch("scripts.extract_clang.Path") as mock_path:
            mock_path_instance = Mock()
            mock_path_instance.exists.return_value = False
            mock_path.return_value = mock_path_instance

            result = link_depends_on(axioms, vector_db_path=mock_path_instance)

            # Should return axioms unchanged
            assert result == axioms
            assert not result[0].depends_on

    def test_link_filters_to_foundation_layers_only(self):
        """Test that linking only links to foundation layers, not other library axioms."""
        from scripts.extract_clang import link_depends_on

        axioms = [
            Axiom(
                id="mylib.func.precond",
                content="Parameter must be positive",
                formal_spec="",
                axiom_type=AxiomType.PRECONDITION,
                source=SourceLocation(file="mylib.cpp", module="mylib"),
            )
        ]

        mock_loader = Mock()
        mock_loader.db = Mock()
        mock_loader.db.list_tables.return_value = Mock(tables=["axioms"])

        with patch("scripts.extract_clang.LanceDBLoader", return_value=mock_loader):
            with patch("scripts.extract_clang.semantic_linker") as mock_semantic:
                # search_foundations should filter to foundation layers
                mock_semantic.search_foundations.return_value = [
                    {"id": "cpp_core.int.positive", "layer": "cpp_core", "content": "..."}
                    # Library layer axioms should already be filtered out by search_foundations
                ]
                mock_semantic.merge_depends_on.return_value = ["cpp_core.int.positive"]

                result = link_depends_on(axioms)

                # Verify search_foundations was called (which does the filtering)
                mock_semantic.search_foundations.assert_called()
                assert result[0].depends_on == ["cpp_core.int.positive"]
