# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for search_with_pairings functionality."""

import pytest
from unittest.mock import MagicMock, patch


class TestSearchWithPairings:
    """Tests for search_with_pairings method."""

    def test_basic_search_returns_results(self) -> None:
        """search_with_pairings returns base search results."""
        from axiom.vectors.loader import LanceDBLoader

        # Mock the base search
        mock_table = MagicMock()
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {"id": "axiom_for_mutex_lock", "content": "Lock mutex"},
        ]

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["axioms"]
        mock_db.open_table.return_value = mock_table

        # Mock Neo4j loader
        mock_neo4j = MagicMock()
        mock_neo4j.get_paired_axioms.return_value = []
        mock_neo4j.get_idioms_for_axiom.return_value = []

        with patch.object(LanceDBLoader, "__init__", lambda self, **kwargs: None):
            loader = LanceDBLoader()
            loader.db = mock_db
            loader._model = MagicMock()
            loader._model.encode.return_value.tolist.return_value = [0.1] * 384
            loader.neo4j = mock_neo4j

            results = loader.search_with_pairings("mutex lock", limit=10)

        assert len(results) >= 1
        assert results[0]["id"] == "axiom_for_mutex_lock"

    def test_expands_to_paired_axioms(self) -> None:
        """search_with_pairings includes paired axioms in results."""
        from axiom.vectors.loader import LanceDBLoader

        mock_table = MagicMock()
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {"id": "axiom_for_mutex_lock", "content": "Lock mutex"},
        ]

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["axioms"]
        mock_db.open_table.return_value = mock_table

        # Mock Neo4j to return paired axiom
        mock_neo4j = MagicMock()
        mock_neo4j.get_paired_axioms.return_value = [
            {"id": "axiom_for_mutex_unlock", "content": "Unlock mutex"},
        ]
        mock_neo4j.get_idioms_for_axiom.return_value = []

        with patch.object(LanceDBLoader, "__init__", lambda self, **kwargs: None):
            loader = LanceDBLoader()
            loader.db = mock_db
            loader._model = MagicMock()
            loader._model.encode.return_value.tolist.return_value = [0.1] * 384
            loader.neo4j = mock_neo4j

            results = loader.search_with_pairings("mutex lock", limit=10)

        # Should include both lock and unlock
        ids = [r.get("id") for r in results if "id" in r]
        assert "axiom_for_mutex_lock" in ids
        assert "axiom_for_mutex_unlock" in ids

    def test_marks_expanded_results(self) -> None:
        """Expanded results are marked with _paired_with field."""
        from axiom.vectors.loader import LanceDBLoader

        mock_table = MagicMock()
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {"id": "axiom_for_lock", "content": "Lock"},
        ]

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["axioms"]
        mock_db.open_table.return_value = mock_table

        mock_neo4j = MagicMock()
        mock_neo4j.get_paired_axioms.return_value = [
            {"id": "axiom_for_unlock", "content": "Unlock"},
        ]
        mock_neo4j.get_idioms_for_axiom.return_value = []

        with patch.object(LanceDBLoader, "__init__", lambda self, **kwargs: None):
            loader = LanceDBLoader()
            loader.db = mock_db
            loader._model = MagicMock()
            loader._model.encode.return_value.tolist.return_value = [0.1] * 384
            loader.neo4j = mock_neo4j

            results = loader.search_with_pairings("lock", limit=10)

        # Find the expanded result
        expanded = [r for r in results if r.get("_paired_with")]
        assert len(expanded) == 1
        assert expanded[0]["_paired_with"] == "axiom_for_lock"

    def test_includes_idiom_templates(self) -> None:
        """search_with_pairings includes idiom templates in results."""
        from axiom.vectors.loader import LanceDBLoader

        mock_table = MagicMock()
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {"id": "axiom_for_lock", "content": "Lock"},
        ]

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["axioms"]
        mock_db.open_table.return_value = mock_table

        mock_neo4j = MagicMock()
        mock_neo4j.get_paired_axioms.return_value = []
        mock_neo4j.get_idioms_for_axiom.return_value = [
            {
                "id": "idiom_scoped_lock",
                "name": "scoped_lock",
                "template": "lock(${m}); { ${body} } unlock(${m});",
            }
        ]

        with patch.object(LanceDBLoader, "__init__", lambda self, **kwargs: None):
            loader = LanceDBLoader()
            loader.db = mock_db
            loader._model = MagicMock()
            loader._model.encode.return_value.tolist.return_value = [0.1] * 384
            loader.neo4j = mock_neo4j

            results = loader.search_with_pairings("lock", limit=10)

        # Find idiom result
        idiom_results = [r for r in results if "_idiom" in r]
        assert len(idiom_results) == 1
        assert idiom_results[0]["_idiom"]["name"] == "scoped_lock"

    def test_no_duplicates_in_expansion(self) -> None:
        """search_with_pairings doesn't return duplicate axioms."""
        from axiom.vectors.loader import LanceDBLoader

        # Simulate: lock and unlock both in base results
        mock_table = MagicMock()
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {"id": "axiom_for_lock", "content": "Lock"},
            {"id": "axiom_for_unlock", "content": "Unlock"},
        ]

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["axioms"]
        mock_db.open_table.return_value = mock_table

        # Pairs: lock -> unlock, unlock -> lock
        mock_neo4j = MagicMock()
        mock_neo4j.get_paired_axioms.side_effect = [
            [{"id": "axiom_for_unlock", "content": "Unlock"}],  # pairs for lock
            [{"id": "axiom_for_lock", "content": "Lock"}],  # pairs for unlock
        ]
        mock_neo4j.get_idioms_for_axiom.return_value = []

        with patch.object(LanceDBLoader, "__init__", lambda self, **kwargs: None):
            loader = LanceDBLoader()
            loader.db = mock_db
            loader._model = MagicMock()
            loader._model.encode.return_value.tolist.return_value = [0.1] * 384
            loader.neo4j = mock_neo4j

            results = loader.search_with_pairings("lock unlock", limit=10)

        # Should only have 2 axioms, no duplicates
        axiom_results = [r for r in results if "id" in r and "_idiom" not in r]
        ids = [r["id"] for r in axiom_results]
        assert len(ids) == len(set(ids)), "Should have no duplicate IDs"

    def test_works_without_neo4j(self) -> None:
        """search_with_pairings works when neo4j is not configured."""
        from axiom.vectors.loader import LanceDBLoader

        mock_table = MagicMock()
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {"id": "axiom_for_lock", "content": "Lock"},
        ]

        mock_db = MagicMock()
        mock_db.table_names.return_value = ["axioms"]
        mock_db.open_table.return_value = mock_table

        with patch.object(LanceDBLoader, "__init__", lambda self, **kwargs: None):
            loader = LanceDBLoader()
            loader.db = mock_db
            loader._model = MagicMock()
            loader._model.encode.return_value.tolist.return_value = [0.1] * 384
            loader.neo4j = None  # Not configured

            results = loader.search_with_pairings("lock", limit=10)

        # Should still return base results
        assert len(results) == 1
        assert results[0]["id"] == "axiom_for_lock"
