"""Tests for the KB integrator module."""

import tempfile
from pathlib import Path

import pytest

from axiom.ingestion.kb_integrator import IntegrationResult, KBIntegrator
from axiom.ingestion.reviewer import ReviewDecision, ReviewItem, ReviewSession
from axiom.models import Axiom, AxiomCollection, AxiomType, SourceLocation


def create_test_axiom(
    id: str = "test_axiom",
    content: str = "Test content",
    depends_on: list = None,
    function: str = None,
    header: str = None,
) -> Axiom:
    """Create a test axiom."""
    return Axiom(
        id=id,
        content=content,
        formal_spec="x != 0",
        layer="library",
        source=SourceLocation(file="test.cpp", module="test"),
        function=function or "test_func",
        header=header or "test.h",
        axiom_type=AxiomType.PRECONDITION,
        on_violation="undefined behavior",
        confidence=0.9,
        depends_on=depends_on or [],
    )


class TestIntegrationResult:
    """Tests for IntegrationResult dataclass."""

    def test_creates_result(self):
        """Test creating an integration result."""
        result = IntegrationResult(
            axioms_loaded=5,
            neo4j_nodes_created=5,
            lancedb_records_created=5,
            dependencies_created=3,
            errors=[],
        )

        assert result.axioms_loaded == 5
        assert result.neo4j_nodes_created == 5
        assert result.lancedb_records_created == 5
        assert result.dependencies_created == 3
        assert result.errors == []

    def test_result_with_errors(self):
        """Test result with errors."""
        result = IntegrationResult(
            axioms_loaded=0,
            neo4j_nodes_created=0,
            lancedb_records_created=0,
            dependencies_created=0,
            errors=["Connection failed"],
        )

        assert len(result.errors) == 1
        assert "Connection failed" in result.errors[0]


class TestKBIntegrator:
    """Tests for KBIntegrator class."""

    def test_creates_integrator(self):
        """Test creating an integrator."""
        integrator = KBIntegrator()

        assert integrator.neo4j_loader is None
        assert integrator.lancedb_loader is None
        assert integrator.review_manager is not None

    def test_integrate_empty_list(self):
        """Test integrating an empty list of axioms."""
        integrator = KBIntegrator()
        result = integrator.integrate_axioms([])

        assert result.axioms_loaded == 0
        assert result.errors == []

    def test_integrate_axioms_without_loaders(self):
        """Test integrating axioms without any loaders configured."""
        integrator = KBIntegrator()
        axioms = [
            create_test_axiom("a1"),
            create_test_axiom("a2"),
        ]

        result = integrator.integrate_axioms(axioms)

        # Without loaders, nothing is loaded but no errors either
        assert result.axioms_loaded == 2
        assert result.neo4j_nodes_created == 0
        assert result.lancedb_records_created == 0
        assert result.errors == []

    def test_integrate_from_nonexistent_session(self):
        """Test integrating from a session that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from axiom.ingestion.reviewer import ReviewSessionManager

            manager = ReviewSessionManager(storage_dir=tmpdir)
            integrator = KBIntegrator(review_manager=manager)

            result = integrator.integrate_from_session("nonexistent")

            assert result.axioms_loaded == 0
            assert "not found" in result.errors[0]

    def test_integrate_from_toml_nonexistent(self):
        """Test integrating from a TOML file that doesn't exist."""
        integrator = KBIntegrator()
        result = integrator.integrate_from_toml("/nonexistent/path.toml")

        assert result.axioms_loaded == 0
        assert "not found" in result.errors[0]

    def test_integrate_from_toml(self):
        """Test integrating from a TOML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test TOML file
            collection = AxiomCollection(
                axioms=[
                    create_test_axiom("a1", "First axiom"),
                    create_test_axiom("a2", "Second axiom"),
                ]
            )
            toml_path = Path(tmpdir) / "test.toml"
            collection.save_toml(toml_path)

            integrator = KBIntegrator()
            result = integrator.integrate_from_toml(str(toml_path))

            assert result.axioms_loaded == 2
            assert result.errors == []

    def test_integrate_from_session(self):
        """Test integrating from a review session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from axiom.ingestion.reviewer import ReviewSessionManager

            manager = ReviewSessionManager(storage_dir=tmpdir)

            # Create a session with approved axioms
            axioms = [
                create_test_axiom("a1"),
                create_test_axiom("a2"),
                create_test_axiom("a3"),
            ]
            session = manager.create_session(axioms, session_id="test_session")

            # Approve some axioms
            session.items[0].decision = ReviewDecision.APPROVED
            session.items[1].decision = ReviewDecision.REJECTED
            session.items[2].decision = ReviewDecision.APPROVED
            manager.save_session(session)

            integrator = KBIntegrator(review_manager=manager)
            result = integrator.integrate_from_session("test_session")

            # Only 2 approved axioms should be integrated
            assert result.axioms_loaded == 2
            assert result.errors == []

    def test_get_integration_stats_without_loaders(self):
        """Test getting stats without any loaders."""
        integrator = KBIntegrator()
        stats = integrator.get_integration_stats()

        assert stats["neo4j"] is None
        assert stats["lancedb"] is None

    def test_validate_dependencies_without_loader(self):
        """Test validating dependencies without Neo4j loader."""
        integrator = KBIntegrator()
        axioms = [create_test_axiom("a1", depends_on=["c11_div_nonzero"])]

        missing = integrator.validate_dependencies(axioms)

        # Without a loader, returns empty (can't validate)
        assert missing == []


class TestAxiomDependsOn:
    """Tests for the depends_on field in axioms."""

    def test_axiom_with_depends_on(self):
        """Test creating an axiom with dependencies."""
        axiom = create_test_axiom(
            "lib_divide_precond",
            depends_on=["c11_expr_div_nonzero", "c11_int_overflow"],
        )

        assert axiom.depends_on == ["c11_expr_div_nonzero", "c11_int_overflow"]

    def test_axiom_default_empty_depends_on(self):
        """Test that depends_on defaults to empty list."""
        axiom = Axiom(
            id="test",
            content="Test",
            formal_spec="x",
            layer="library",
            source=SourceLocation(file="test.cpp", module="test"),
        )

        assert axiom.depends_on == []

    def test_axiom_collection_toml_with_depends_on(self):
        """Test TOML serialization preserves depends_on."""
        axiom = create_test_axiom(
            "test_axiom",
            depends_on=["c11_div_nonzero", "c11_ptr_valid"],
        )
        collection = AxiomCollection(axioms=[axiom])

        toml_str = collection.to_toml()

        assert "depends_on" in toml_str
        assert "c11_div_nonzero" in toml_str
        assert "c11_ptr_valid" in toml_str

    def test_axiom_collection_load_toml_with_depends_on(self):
        """Test TOML deserialization loads depends_on."""
        with tempfile.TemporaryDirectory() as tmpdir:
            axiom = create_test_axiom(
                "test_axiom",
                depends_on=["c11_div_nonzero"],
            )
            collection = AxiomCollection(axioms=[axiom])

            path = Path(tmpdir) / "test.toml"
            collection.save_toml(path)

            loaded = AxiomCollection.load_toml(path)

            assert len(loaded.axioms) == 1
            assert loaded.axioms[0].depends_on == ["c11_div_nonzero"]


class TestAxiomLibraryFields:
    """Tests for library-specific axiom fields."""

    def test_axiom_with_function(self):
        """Test axiom with function field."""
        axiom = create_test_axiom(function="malloc")
        assert axiom.function == "malloc"

    def test_axiom_with_header(self):
        """Test axiom with header field."""
        axiom = create_test_axiom(header="stdlib.h")
        assert axiom.header == "stdlib.h"

    def test_axiom_collection_toml_preserves_fields(self):
        """Test TOML serialization preserves all library fields."""
        axiom = create_test_axiom(
            function="free",
            header="stdlib.h",
        )
        axiom.axiom_type = AxiomType.PRECONDITION
        axiom.on_violation = "double free is undefined behavior"
        collection = AxiomCollection(axioms=[axiom])

        toml_str = collection.to_toml()

        assert 'function = "free"' in toml_str
        assert 'header = "stdlib.h"' in toml_str
        assert 'axiom_type = "precondition"' in toml_str
        assert "double free" in toml_str

    def test_axiom_collection_load_toml_library_fields(self):
        """Test TOML deserialization loads library fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            axiom = create_test_axiom(
                function="memcpy",
                header="string.h",
            )
            axiom.axiom_type = AxiomType.PRECONDITION
            axiom.on_violation = "buffer overlap is undefined"
            collection = AxiomCollection(axioms=[axiom])

            path = Path(tmpdir) / "test.toml"
            collection.save_toml(path)

            loaded = AxiomCollection.load_toml(path)

            assert loaded.axioms[0].function == "memcpy"
            assert loaded.axioms[0].header == "string.h"
            assert loaded.axioms[0].axiom_type == AxiomType.PRECONDITION
            assert "buffer overlap" in loaded.axioms[0].on_violation
