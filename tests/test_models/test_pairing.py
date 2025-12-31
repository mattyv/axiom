# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for Pairing and Idiom dataclasses."""

import pytest


class TestPairing:
    """Tests for Pairing dataclass."""

    def test_pairing_has_required_fields(self) -> None:
        """Pairing should have opener_id, closer_id, required, source, confidence."""
        from axiom.models.pairing import Pairing

        pairing = Pairing(
            opener_id="axiom_for_mutex_lock",
            closer_id="axiom_for_mutex_unlock",
            required=True,
            source="comment_annotation",
            confidence=1.0,
        )

        assert pairing.opener_id == "axiom_for_mutex_lock"
        assert pairing.closer_id == "axiom_for_mutex_unlock"
        assert pairing.required is True
        assert pairing.source == "comment_annotation"
        assert pairing.confidence == 1.0

    def test_pairing_optional_fields(self) -> None:
        """Pairing should have optional cell and evidence fields."""
        from axiom.models.pairing import Pairing

        pairing = Pairing(
            opener_id="axiom_for_malloc",
            closer_id="axiom_for_free",
            required=True,
            source="k_semantics",
            confidence=1.0,
            cell="malloced",
            evidence="<malloced> cell shared between malloc and free",
        )

        assert pairing.cell == "malloced"
        assert pairing.evidence == "<malloced> cell shared between malloc and free"

    def test_pairing_defaults_for_optional_fields(self) -> None:
        """Pairing optional fields should have sensible defaults."""
        from axiom.models.pairing import Pairing

        pairing = Pairing(
            opener_id="axiom_for_fopen",
            closer_id="axiom_for_fclose",
            required=True,
            source="naming_heuristic",
            confidence=0.7,
        )

        assert pairing.cell is None
        assert pairing.evidence == ""


class TestIdiom:
    """Tests for Idiom dataclass."""

    def test_idiom_has_required_fields(self) -> None:
        """Idiom should have id, name, participants, template, source."""
        from axiom.models.pairing import Idiom

        idiom = Idiom(
            id="idiom_scoped_lock",
            name="scoped_lock",
            participants=["axiom_for_mutex_lock", "axiom_for_mutex_unlock"],
            template="mutex_lock(${m}); { ${body} } mutex_unlock(${m});",
            source="comment_annotation",
        )

        assert idiom.id == "idiom_scoped_lock"
        assert idiom.name == "scoped_lock"
        assert len(idiom.participants) == 2
        assert "axiom_for_mutex_lock" in idiom.participants
        assert "${body}" in idiom.template
        assert idiom.source == "comment_annotation"


class TestPairingSource:
    """Tests for different pairing sources."""

    def test_k_semantics_source(self) -> None:
        """K semantics pairings should have source='k_semantics' and cell."""
        from axiom.models.pairing import Pairing

        pairing = Pairing(
            opener_id="axiom_for_malloc",
            closer_id="axiom_for_free",
            required=True,
            source="k_semantics",
            confidence=1.0,
            cell="malloced",
        )

        assert pairing.source == "k_semantics"
        assert pairing.cell is not None

    def test_comment_annotation_source(self) -> None:
        """Comment annotation pairings have source='comment_annotation'."""
        from axiom.models.pairing import Pairing

        pairing = Pairing(
            opener_id="axiom_for_resource_acquire",
            closer_id="axiom_for_resource_release",
            required=True,
            source="comment_annotation",
            confidence=1.0,
            evidence="@axiom:pairs_with in header.h",
        )

        assert pairing.source == "comment_annotation"
        assert "header.h" in pairing.evidence

    def test_naming_heuristic_source(self) -> None:
        """Naming heuristic pairings have lower confidence."""
        from axiom.models.pairing import Pairing

        pairing = Pairing(
            opener_id="axiom_for_stream_begin",
            closer_id="axiom_for_stream_end",
            required=True,
            source="naming_heuristic",
            confidence=0.7,
            evidence="stream_begin -> stream_end",
        )

        assert pairing.source == "naming_heuristic"
        assert pairing.confidence < 1.0
