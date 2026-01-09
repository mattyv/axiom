# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for bulk Neo4j ingestion using UNWIND operations."""

from unittest.mock import MagicMock

import pytest

from axiom.models import Axiom, AxiomCollection, AxiomSource, ErrorCode
from axiom.models.error import ErrorType

# Skip all tests in this module if neo4j is not installed
neo4j = pytest.importorskip("neo4j")


@pytest.fixture
def sample_axioms() -> list[Axiom]:
    """Create sample axioms for testing."""
    return [
        Axiom(
            id="test_axiom_1",
            content="First test axiom",
            source=AxiomSource(file="test.toml", module="test_module"),
            layer="test",
            confidence=1.0,
            tags=["test"],
            depends_on=["foundation_axiom_1"],
        ),
        Axiom(
            id="test_axiom_2",
            content="Second test axiom",
            source=AxiomSource(file="test.toml", module="test_module"),
            layer="test",
            confidence=0.9,
            tags=["test", "example"],
            depends_on=[],
        ),
    ]


@pytest.fixture
def sample_errors() -> list[ErrorCode]:
    """Create sample error codes for testing."""
    return [
        ErrorCode(
            code="TEST001",
            internal_code="test_error_1",
            type=ErrorType.ERROR,
            description="Test error 1",
        ),
        ErrorCode(
            code="TEST002",
            internal_code="test_error_2",
            type=ErrorType.WARNING,
            description="Test error 2",
        ),
    ]


@pytest.fixture
def sample_collection(sample_axioms, sample_errors) -> AxiomCollection:
    """Create a sample collection for testing."""
    return AxiomCollection(
        source="test",
        axioms=sample_axioms,
        error_codes=sample_errors,
    )


@pytest.fixture
def mock_loader():
    """Create a Neo4jLoader with mocked driver."""
    from axiom.graph.loader import Neo4jLoader

    mock_tx = MagicMock()
    mock_session = MagicMock()
    mock_session.execute_write = MagicMock(side_effect=lambda fn, *args: fn(mock_tx, *args))

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

    loader = Neo4jLoader.__new__(Neo4jLoader)
    loader.driver = mock_driver

    return loader, mock_tx, mock_session


class TestAxiomToDict:
    """Tests for _axiom_to_dict helper."""

    def test_converts_axiom_to_dict(self, sample_axioms) -> None:
        """_axiom_to_dict creates dict with all required fields."""
        from axiom.graph.loader import Neo4jLoader

        axiom = sample_axioms[0]
        result = Neo4jLoader._axiom_to_dict(axiom)

        assert result["id"] == "test_axiom_1"
        assert result["content"] == "First test axiom"
        assert result["layer"] == "test"
        assert result["confidence"] == 1.0
        assert result["source_file"] == "test.toml"
        assert result["module_name"] == "test_module"
        assert result["tags"] == ["test"]
        assert result["depends_on"] == ["foundation_axiom_1"]

    def test_handles_none_depends_on(self) -> None:
        """_axiom_to_dict handles None depends_on gracefully."""
        from axiom.graph.loader import Neo4jLoader

        axiom = Axiom(
            id="no_deps",
            content="No dependencies",
            source=AxiomSource(file="test.toml", module="test"),
            layer="test",
            depends_on=None,
        )

        result = Neo4jLoader._axiom_to_dict(axiom)
        assert result["depends_on"] == []

    def test_handles_axiom_type(self) -> None:
        """_axiom_to_dict extracts axiom_type value."""
        from axiom.graph.loader import Neo4jLoader
        from axiom.models import AxiomType

        axiom = Axiom(
            id="typed",
            content="Typed axiom",
            source=AxiomSource(file="test.toml", module="test"),
            layer="test",
            axiom_type=AxiomType.PRECONDITION,
        )

        result = Neo4jLoader._axiom_to_dict(axiom)
        assert result["axiom_type"] == "precondition"


class TestErrorToDict:
    """Tests for _error_to_dict helper."""

    def test_converts_error_to_dict(self, sample_errors) -> None:
        """_error_to_dict creates dict with all required fields."""
        from axiom.graph.loader import Neo4jLoader

        error = sample_errors[0]
        result = Neo4jLoader._error_to_dict(error)

        assert result["code"] == "TEST001"
        assert result["internal_code"] == "test_error_1"
        assert result["type"] == "error"
        assert result["description"] == "Test error 1"


class TestBulkCreateAxioms:
    """Tests for _bulk_create_axioms method."""

    def test_uses_unwind_query(self, mock_loader, sample_axioms) -> None:
        """_bulk_create_axioms uses UNWIND for bulk insert."""
        from axiom.graph.loader import Neo4jLoader

        loader, mock_tx, _ = mock_loader
        axiom_data = [Neo4jLoader._axiom_to_dict(a) for a in sample_axioms]

        Neo4jLoader._bulk_create_axioms(mock_tx, axiom_data)

        mock_tx.run.assert_called_once()
        query = mock_tx.run.call_args[0][0]

        assert "UNWIND" in query
        assert "MERGE (a:Axiom" in query
        assert "MERGE (m:KModule" in query
        assert "DEFINED_IN" in query

    def test_passes_axioms_as_parameter(self, mock_loader, sample_axioms) -> None:
        """_bulk_create_axioms passes axiom list as parameter."""
        from axiom.graph.loader import Neo4jLoader

        loader, mock_tx, _ = mock_loader
        axiom_data = [Neo4jLoader._axiom_to_dict(a) for a in sample_axioms]

        Neo4jLoader._bulk_create_axioms(mock_tx, axiom_data)

        call_kwargs = mock_tx.run.call_args[1]
        assert "axioms" in call_kwargs
        assert len(call_kwargs["axioms"]) == 2


class TestBulkCreateErrors:
    """Tests for _bulk_create_errors method."""

    def test_uses_unwind_query(self, mock_loader, sample_errors) -> None:
        """_bulk_create_errors uses UNWIND for bulk insert."""
        from axiom.graph.loader import Neo4jLoader

        loader, mock_tx, _ = mock_loader
        error_data = [Neo4jLoader._error_to_dict(e) for e in sample_errors]

        Neo4jLoader._bulk_create_errors(mock_tx, error_data)

        mock_tx.run.assert_called_once()
        query = mock_tx.run.call_args[0][0]

        assert "UNWIND" in query
        assert "MERGE (e:ErrorCode" in query


class TestBulkCreateRelationships:
    """Tests for bulk relationship creation."""

    def test_bulk_create_violated_by(self, mock_loader) -> None:
        """_bulk_create_violated_by creates relationships from stored codes."""
        from axiom.graph.loader import Neo4jLoader

        loader, mock_tx, _ = mock_loader

        Neo4jLoader._bulk_create_violated_by(mock_tx)

        mock_tx.run.assert_called_once()
        query = mock_tx.run.call_args[0][0]

        assert "violated_by_codes" in query
        assert "VIOLATED_BY" in query
        assert "UNWIND" in query

    def test_bulk_create_depends_on(self, mock_loader) -> None:
        """_bulk_create_depends_on creates relationships from stored deps."""
        from axiom.graph.loader import Neo4jLoader

        loader, mock_tx, _ = mock_loader

        Neo4jLoader._bulk_create_depends_on(mock_tx)

        mock_tx.run.assert_called_once()
        query = mock_tx.run.call_args[0][0]

        assert "depends_on" in query
        assert "DEPENDS_ON" in query
        assert "UNWIND" in query


class TestLoadCollectionBulk:
    """Tests for load_collection with bulk=True."""

    def test_bulk_mode_is_default(self, mock_loader, sample_collection) -> None:
        """load_collection uses bulk mode by default."""
        loader, mock_tx, mock_session = mock_loader

        loader.load_collection(sample_collection)

        # Should call execute_write 4 times: axioms, errors, violated_by, depends_on
        assert mock_session.execute_write.call_count == 4

    def test_bulk_mode_explicit(self, mock_loader, sample_collection) -> None:
        """load_collection(bulk=True) uses bulk operations."""
        loader, mock_tx, mock_session = mock_loader

        loader.load_collection(sample_collection, bulk=True)

        # Verify UNWIND queries were used
        queries = [c[0][0] for c in mock_tx.run.call_args_list]
        assert any("UNWIND" in q for q in queries)

    def test_sequential_mode(self, mock_loader, sample_collection) -> None:
        """load_collection(bulk=False) uses sequential operations."""
        loader, mock_tx, mock_session = mock_loader

        loader.load_collection(sample_collection, bulk=False)

        # Should call execute_write for each axiom + each error + relationships
        # 2 axioms + 2 errors + 1 relationships = 5
        assert mock_session.execute_write.call_count >= 5

    def test_empty_collection(self, mock_loader) -> None:
        """load_collection handles empty collection gracefully."""
        loader, mock_tx, mock_session = mock_loader

        empty_collection = AxiomCollection(source="empty", axioms=[], error_codes=[])
        loader.load_collection(empty_collection)

        # Should still call relationship creation even with empty data
        assert mock_session.execute_write.call_count >= 2


class TestLoadCollectionPerformance:
    """Tests verifying bulk is more efficient than sequential."""

    def test_bulk_fewer_transactions(self, sample_collection) -> None:
        """Bulk mode uses fewer execute_write calls than sequential."""
        from axiom.graph.loader import Neo4jLoader

        # Setup for bulk
        bulk_tx = MagicMock()
        bulk_session = MagicMock()
        bulk_session.execute_write = MagicMock(side_effect=lambda fn, *args: fn(bulk_tx, *args))
        bulk_driver = MagicMock()
        bulk_driver.session.return_value.__enter__ = MagicMock(return_value=bulk_session)
        bulk_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        bulk_loader = Neo4jLoader.__new__(Neo4jLoader)
        bulk_loader.driver = bulk_driver

        # Setup for sequential
        seq_tx = MagicMock()
        seq_session = MagicMock()
        seq_session.execute_write = MagicMock(side_effect=lambda fn, *args: fn(seq_tx, *args))
        seq_driver = MagicMock()
        seq_driver.session.return_value.__enter__ = MagicMock(return_value=seq_session)
        seq_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        seq_loader = Neo4jLoader.__new__(Neo4jLoader)
        seq_loader.driver = seq_driver

        # Run both
        bulk_loader.load_collection(sample_collection, bulk=True)
        seq_loader.load_collection(sample_collection, bulk=False)

        bulk_calls = bulk_session.execute_write.call_count
        seq_calls = seq_session.execute_write.call_count

        # Bulk should use fewer calls
        assert bulk_calls < seq_calls, f"Bulk ({bulk_calls}) should use fewer calls than sequential ({seq_calls})"
