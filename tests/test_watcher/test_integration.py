# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Integration tests for the LSP watcher + query system."""

from pathlib import Path

import pytest

from axiom.config import AxiomConfig
from axiom.query.server import AxiomQueryServer
from axiom.query.service import AxiomQueryService
from axiom.watcher.extractor import AxiomExtractor
from axiom.watcher.store import InMemoryAxiomStore
from axiom.watcher.watcher import AxiomWatcher


class TestLiveLayerIntegration:
    """Tests for live layer detection and extraction."""

    def test_demo_file_detected_as_live(self) -> None:
        """Demo file in examples/ should be detected as live layer."""
        # Load actual project config
        config = AxiomConfig.load(Path.cwd())
        extractor = AxiomExtractor(config=config)

        demo_file = Path("examples/demo_axiom_issues.cpp").resolve()

        # Should be live due to examples/ override in config
        assert extractor.is_live_layer_file(demo_file)

    def test_demo_file_extraction(self) -> None:
        """Demo file should extract axioms successfully."""
        config = AxiomConfig.load(Path.cwd())
        extractor = AxiomExtractor(config=config)

        demo_file = Path("examples/demo_axiom_issues.cpp")

        # Skip if axiom-extract not built
        if not extractor.axiom_extract_path.exists():
            pytest.skip("axiom-extract not built")

        collection = extractor.extract_file(demo_file)

        # Should have extracted axioms for the buggy functions
        assert len(collection.axioms) > 0

        # Check for expected axioms
        functions = {ax.function for ax in collection.axioms if ax.function}
        assert "divide" in functions
        assert "get_value" in functions

    def test_query_service_with_extracted_axioms(self) -> None:
        """Query service should return axioms after extraction."""
        config = AxiomConfig.load(Path.cwd())
        extractor = AxiomExtractor(config=config)
        store = InMemoryAxiomStore()
        service = AxiomQueryService(live_store=store)

        demo_file = Path("examples/demo_axiom_issues.cpp")

        if not extractor.axiom_extract_path.exists():
            pytest.skip("axiom-extract not built")

        # Extract and store
        collection = extractor.extract_file(demo_file)
        store.upsert(collection.axioms)

        # Query for divide function
        results = service.query(["divide"])

        assert len(results) == 1
        assert results[0].symbol == "divide"
        assert len(results[0].axioms) > 0
        assert any("zero" in ax.content.lower() for ax in results[0].axioms)


class TestQueryServerProtocol:
    """Tests for the query server JSON protocol."""

    @pytest.fixture
    def service_with_axioms(self) -> AxiomQueryService:
        """Create service with test axioms."""
        from axiom.models import Axiom, AxiomType, SourceLocation

        store = InMemoryAxiomStore()
        store.upsert([
            Axiom(
                id="test.divide.precond",
                content="Divisor must not be zero",
                formal_spec="b != 0",
                source=SourceLocation(file="/test/file.cpp", module="test"),
                function="divide",
                axiom_type=AxiomType.PRECONDITION,
                confidence=0.95,
            )
        ])
        return AxiomQueryService(live_store=store)

    def test_server_query_method(self, service_with_axioms: AxiomQueryService) -> None:
        """Server responds to query method correctly."""
        server = AxiomQueryServer(service=service_with_axioms)

        # Test the query handler directly (not async)
        request = {"method": "query", "params": {"symbols": ["divide"]}}
        response = server._handle_request(request)

        assert "result" in response
        assert len(response["result"]) == 1
        assert response["result"][0]["symbol"] == "divide"

    def test_server_get_axiom_method(self, service_with_axioms: AxiomQueryService) -> None:
        """Server responds to get_axiom method correctly."""
        server = AxiomQueryServer(service=service_with_axioms)

        request = {"method": "get_axiom", "params": {"axiom_id": "test.divide.precond"}}
        response = server._handle_request(request)

        assert "result" in response
        assert response["result"]["id"] == "test.divide.precond"
        assert "zero" in response["result"]["content"].lower()

    def test_server_unknown_method(self, service_with_axioms: AxiomQueryService) -> None:
        """Server returns error for unknown method."""
        server = AxiomQueryServer(service=service_with_axioms)

        request = {"method": "unknown"}
        response = server._handle_request(request)

        assert "error" in response


class TestEndToEndFlow:
    """End-to-end tests for the complete LSP flow."""

    def test_watcher_extracts_demo_file(self) -> None:
        """Watcher should extract axioms from demo file."""
        config = AxiomConfig.load(Path.cwd())
        extractor = AxiomExtractor(config=config)
        store = InMemoryAxiomStore()

        if not extractor.axiom_extract_path.exists():
            pytest.skip("axiom-extract not built")

        _watcher = AxiomWatcher(  # noqa: F841 - verifying constructor works
            watch_paths=[Path.cwd() / "examples"],
            store=store,
            extractor=extractor,
        )

        # Demo file is in live layer
        demo_file = Path("examples/demo_axiom_issues.cpp").resolve()
        assert extractor.is_live_layer_file(demo_file)

        # Extract just the demo file manually (extract_all would try to extract all compile_commands files)
        collection = extractor.extract_file(demo_file)
        store.upsert(collection.axioms)

        # Should have axioms
        assert len(store) > 0

        # Query should work
        from axiom.query.service import AxiomQueryService
        service = AxiomQueryService(live_store=store)
        results = service.query(["divide"])
        assert len(results) == 1
        assert any("zero" in ax.content.lower() for ax in results[0].axioms)
