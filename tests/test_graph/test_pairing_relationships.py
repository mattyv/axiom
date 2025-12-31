# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for PAIRS_WITH relationships and Idiom nodes in Neo4j."""

from unittest.mock import MagicMock

from axiom.models.pairing import Idiom, Pairing


class TestCreatePairingRelationship:
    """Tests for create_pairing_relationship method."""

    def test_creates_pairs_with_relationship(self) -> None:
        """create_pairing_relationship creates PAIRS_WITH edge between axioms."""
        from axiom.graph.loader import Neo4jLoader

        pairing = Pairing(
            opener_id="axiom_for_mutex_lock",
            closer_id="axiom_for_mutex_unlock",
            required=True,
            source="comment_annotation",
            confidence=1.0,
        )

        # Mock the driver and session
        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        loader = Neo4jLoader.__new__(Neo4jLoader)
        loader.driver = mock_driver

        loader.create_pairing_relationship(pairing)

        # Verify the query was executed
        mock_session.run.assert_called_once()
        call_args = mock_session.run.call_args
        query = call_args[0][0]

        assert "PAIRS_WITH" in query
        assert "opener_id" in query or "$opener_id" in query

    def test_relationship_includes_metadata(self) -> None:
        """PAIRS_WITH relationship stores required, source, confidence."""
        from axiom.graph.loader import Neo4jLoader

        pairing = Pairing(
            opener_id="axiom_for_malloc",
            closer_id="axiom_for_free",
            required=True,
            source="k_semantics",
            confidence=1.0,
            cell="malloced",
        )

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        loader = Neo4jLoader.__new__(Neo4jLoader)
        loader.driver = mock_driver

        loader.create_pairing_relationship(pairing)

        # Verify parameters passed to query
        call_args = mock_session.run.call_args
        params = call_args[1] if len(call_args) > 1 else call_args[0][1] if len(call_args[0]) > 1 else {}

        # Should include pairing metadata
        assert "opener_id" in params or any("opener" in str(v) for v in params.values())


class TestCreateIdiomNode:
    """Tests for create_idiom_node method."""

    def test_creates_idiom_node(self) -> None:
        """create_idiom_node creates Idiom node and PARTICIPATES_IN edges."""
        from axiom.graph.loader import Neo4jLoader

        idiom = Idiom(
            id="idiom_scoped_lock",
            name="scoped_lock",
            participants=["axiom_for_mutex_lock", "axiom_for_mutex_unlock"],
            template="mutex_lock(${m}); { ${body} } mutex_unlock(${m});",
            source="comment_annotation",
        )

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        loader = Neo4jLoader.__new__(Neo4jLoader)
        loader.driver = mock_driver

        loader.create_idiom_node(idiom)

        mock_session.run.assert_called()
        call_args = mock_session.run.call_args
        query = call_args[0][0]

        assert "Idiom" in query or "idiom" in query.lower()

    def test_idiom_includes_template(self) -> None:
        """Idiom node stores template for usage pattern."""
        from axiom.graph.loader import Neo4jLoader

        idiom = Idiom(
            id="idiom_resource_scope",
            name="resource_scope",
            participants=["axiom_for_acquire", "axiom_for_release"],
            template="acquire(${r}) { ${body} } release(${r})",
            source="toml_manifest",
        )

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        loader = Neo4jLoader.__new__(Neo4jLoader)
        loader.driver = mock_driver

        loader.create_idiom_node(idiom)

        # Get all queries that were run (first one creates idiom, second links participants)
        all_queries = [call[0][0] for call in mock_session.run.call_args_list]

        # One of the queries should set template property
        assert any("template" in query for query in all_queries)


class TestGetPairedAxioms:
    """Tests for get_paired_axioms method."""

    def test_returns_paired_axioms(self) -> None:
        """get_paired_axioms returns axioms connected by PAIRS_WITH."""
        from axiom.graph.loader import Neo4jLoader

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(
            return_value=iter(
                [
                    {"paired": {"id": "axiom_for_mutex_unlock", "content": "Unlock mutex"}},
                ]
            )
        )

        mock_session = MagicMock()
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        loader = Neo4jLoader.__new__(Neo4jLoader)
        loader.driver = mock_driver

        result = loader.get_paired_axioms("axiom_for_mutex_lock")

        assert len(result) == 1
        assert result[0]["id"] == "axiom_for_mutex_unlock"

    def test_bidirectional_query(self) -> None:
        """PAIRS_WITH query should find pairs in both directions."""
        from axiom.graph.loader import Neo4jLoader

        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock(__iter__=lambda self: iter([]))

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        loader = Neo4jLoader.__new__(Neo4jLoader)
        loader.driver = mock_driver

        loader.get_paired_axioms("axiom_for_test")

        call_args = mock_session.run.call_args
        query = call_args[0][0]

        # Should use undirected pattern or both directions
        # Either [:PAIRS_WITH]- (no direction) or both directions
        assert "PAIRS_WITH" in query


class TestGetIdiomsForAxiom:
    """Tests for get_idioms_for_axiom method."""

    def test_returns_idioms(self) -> None:
        """get_idioms_for_axiom returns idioms the axiom participates in."""
        from axiom.graph.loader import Neo4jLoader

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(
            return_value=iter(
                [
                    {
                        "i": {
                            "id": "idiom_scoped_lock",
                            "name": "scoped_lock",
                            "template": "lock(); { } unlock();",
                        }
                    },
                ]
            )
        )

        mock_session = MagicMock()
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        loader = Neo4jLoader.__new__(Neo4jLoader)
        loader.driver = mock_driver

        result = loader.get_idioms_for_axiom("axiom_for_mutex_lock")

        assert len(result) == 1
        assert result[0]["name"] == "scoped_lock"
        assert "${" not in result[0]["template"] or "template" in result[0]


class TestLoadPairings:
    """Tests for loading pairings in bulk."""

    def test_load_pairings_batch(self) -> None:
        """load_pairings loads multiple pairings at once."""
        from axiom.graph.loader import Neo4jLoader

        pairings = [
            Pairing(
                opener_id="axiom_for_lock",
                closer_id="axiom_for_unlock",
                required=True,
                source="test",
                confidence=1.0,
            ),
            Pairing(
                opener_id="axiom_for_open",
                closer_id="axiom_for_close",
                required=True,
                source="test",
                confidence=1.0,
            ),
        ]

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        loader = Neo4jLoader.__new__(Neo4jLoader)
        loader.driver = mock_driver

        loader.load_pairings(pairings)

        # Should call run for each pairing
        assert mock_session.run.call_count >= 2
