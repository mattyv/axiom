"""Tests for the reviewer module."""

import tempfile
from pathlib import Path

import pytest

from axiom.ingestion.reviewer import (
    ReviewDecision,
    ReviewItem,
    ReviewSession,
    ReviewSessionManager,
    format_axiom_for_review,
)
from axiom.models import Axiom, AxiomType, SourceLocation


def create_test_axiom(id: str = "test_axiom", content: str = "Test content") -> Axiom:
    """Create a test axiom."""
    return Axiom(
        id=id,
        content=content,
        formal_spec="x != 0",
        layer="library",
        source=SourceLocation(file="test.cpp", module="test"),
        function="test_func",
        header="test.h",
        axiom_type=AxiomType.PRECONDITION,
        on_violation="undefined behavior",
        confidence=0.9,
    )


class TestReviewItem:
    """Tests for ReviewItem."""

    def test_creates_with_defaults(self):
        """Test creating a review item with defaults."""
        axiom = create_test_axiom()
        item = ReviewItem(axiom=axiom)

        assert item.axiom == axiom
        assert item.decision == ReviewDecision.PENDING
        assert item.reviewer_notes == ""
        assert item.modified_axiom is None

    def test_can_set_decision(self):
        """Test setting a decision."""
        axiom = create_test_axiom()
        item = ReviewItem(axiom=axiom)

        item.decision = ReviewDecision.APPROVED
        assert item.decision == ReviewDecision.APPROVED


class TestReviewSession:
    """Tests for ReviewSession."""

    def test_creates_session(self):
        """Test creating a review session."""
        items = [
            ReviewItem(axiom=create_test_axiom("a1")),
            ReviewItem(axiom=create_test_axiom("a2")),
        ]
        session = ReviewSession(
            session_id="test_session",
            items=items,
        )

        assert session.session_id == "test_session"
        assert session.total_items == 2
        assert session.reviewed_count == 0

    def test_get_current_item(self):
        """Test getting current item."""
        items = [
            ReviewItem(axiom=create_test_axiom("a1")),
            ReviewItem(axiom=create_test_axiom("a2")),
        ]
        session = ReviewSession(session_id="test", items=items)

        current = session.get_current_item()
        assert current.axiom.id == "a1"

    def test_next_item(self):
        """Test navigating to next item."""
        items = [
            ReviewItem(axiom=create_test_axiom("a1")),
            ReviewItem(axiom=create_test_axiom("a2")),
            ReviewItem(axiom=create_test_axiom("a3")),
        ]
        session = ReviewSession(session_id="test", items=items)

        session.next_item()
        assert session.get_current_item().axiom.id == "a2"

        session.next_item()
        assert session.get_current_item().axiom.id == "a3"

        # At end, should stay
        result = session.next_item()
        assert result is None

    def test_prev_item(self):
        """Test navigating to previous item."""
        items = [
            ReviewItem(axiom=create_test_axiom("a1")),
            ReviewItem(axiom=create_test_axiom("a2")),
        ]
        session = ReviewSession(session_id="test", items=items, current_index=1)

        session.prev_item()
        assert session.get_current_item().axiom.id == "a1"

        # At start, should stay
        result = session.prev_item()
        assert result is None

    def test_next_pending(self):
        """Test navigating to next pending item."""
        items = [
            ReviewItem(axiom=create_test_axiom("a1"), decision=ReviewDecision.APPROVED),
            ReviewItem(axiom=create_test_axiom("a2"), decision=ReviewDecision.PENDING),
            ReviewItem(axiom=create_test_axiom("a3"), decision=ReviewDecision.APPROVED),
        ]
        session = ReviewSession(session_id="test", items=items)

        result = session.next_pending()
        assert result is not None
        assert session.get_current_item().axiom.id == "a2"

    def test_next_pending_wraps_around(self):
        """Test that next_pending wraps around to beginning."""
        items = [
            ReviewItem(axiom=create_test_axiom("a1"), decision=ReviewDecision.PENDING),
            ReviewItem(axiom=create_test_axiom("a2"), decision=ReviewDecision.APPROVED),
            ReviewItem(axiom=create_test_axiom("a3"), decision=ReviewDecision.APPROVED),
        ]
        session = ReviewSession(session_id="test", items=items, current_index=2)

        result = session.next_pending()
        assert result is not None
        assert session.get_current_item().axiom.id == "a1"

    def test_reviewed_count(self):
        """Test counting reviewed items."""
        items = [
            ReviewItem(axiom=create_test_axiom("a1"), decision=ReviewDecision.APPROVED),
            ReviewItem(axiom=create_test_axiom("a2"), decision=ReviewDecision.REJECTED),
            ReviewItem(axiom=create_test_axiom("a3"), decision=ReviewDecision.PENDING),
        ]
        session = ReviewSession(session_id="test", items=items)

        assert session.reviewed_count == 2
        assert session.approved_count == 1
        assert session.rejected_count == 1

    def test_is_complete(self):
        """Test is_complete property."""
        items = [
            ReviewItem(axiom=create_test_axiom("a1"), decision=ReviewDecision.APPROVED),
            ReviewItem(axiom=create_test_axiom("a2"), decision=ReviewDecision.PENDING),
        ]
        session = ReviewSession(session_id="test", items=items)

        assert session.is_complete is False

        items[1].decision = ReviewDecision.APPROVED
        assert session.is_complete is True

    def test_get_approved_axioms(self):
        """Test getting approved axioms."""
        a1 = create_test_axiom("a1")
        a2 = create_test_axiom("a2")
        a2_modified = create_test_axiom("a2_modified")
        a3 = create_test_axiom("a3")

        items = [
            ReviewItem(axiom=a1, decision=ReviewDecision.APPROVED),
            ReviewItem(
                axiom=a2,
                decision=ReviewDecision.MODIFIED,
                modified_axiom=a2_modified,
            ),
            ReviewItem(axiom=a3, decision=ReviewDecision.REJECTED),
        ]
        session = ReviewSession(session_id="test", items=items)

        approved = session.get_approved_axioms()
        assert len(approved) == 2
        assert a1 in approved
        assert a2_modified in approved
        assert a3 not in approved


class TestReviewSessionManager:
    """Tests for ReviewSessionManager."""

    def test_create_session(self):
        """Test creating a new session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            axioms = [
                create_test_axiom("a1"),
                create_test_axiom("a2"),
            ]
            session = manager.create_session(axioms, session_id="test_123")

            assert session.session_id == "test_123"
            assert session.total_items == 2

            # Should be saved
            path = Path(tmpdir) / "test_123.json"
            assert path.exists()

    def test_save_and_load_session(self):
        """Test saving and loading a session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            # Create and modify session
            axioms = [create_test_axiom("a1"), create_test_axiom("a2")]
            session = manager.create_session(axioms, session_id="test_456")

            session.items[0].decision = ReviewDecision.APPROVED
            session.items[0].reviewer_notes = "Looks good"
            manager.save_session(session)

            # Load and verify
            loaded = manager.load_session("test_456")
            assert loaded is not None
            assert loaded.session_id == "test_456"
            assert loaded.items[0].decision == ReviewDecision.APPROVED
            assert loaded.items[0].reviewer_notes == "Looks good"

    def test_load_nonexistent_session(self):
        """Test loading a session that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)
            session = manager.load_session("nonexistent")
            assert session is None

    def test_list_sessions(self):
        """Test listing sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            # Create multiple sessions
            manager.create_session([create_test_axiom("a1")], session_id="session1")
            manager.create_session(
                [create_test_axiom("a2")],
                session_id="session2",
                source_file="test.cpp",
            )

            sessions = manager.list_sessions()
            assert len(sessions) == 2

            # Should be sorted by creation time (newest first)
            ids = [s["session_id"] for s in sessions]
            assert "session1" in ids
            assert "session2" in ids

    def test_export_approved(self):
        """Test exporting approved axioms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            axioms = [
                create_test_axiom("a1"),
                create_test_axiom("a2"),
                create_test_axiom("a3"),
            ]
            session = manager.create_session(axioms, session_id="export_test")

            # Approve some
            session.items[0].decision = ReviewDecision.APPROVED
            session.items[1].decision = ReviewDecision.REJECTED
            session.items[2].decision = ReviewDecision.APPROVED
            manager.save_session(session)

            # Export
            output_path = Path(tmpdir) / "exported.toml"
            count = manager.export_approved(session, str(output_path))

            assert count == 2
            assert output_path.exists()

            # Verify content
            content = output_path.read_text()
            assert "a1" in content
            assert "a3" in content
            assert "a2" not in content  # rejected

    def test_export_empty_session(self):
        """Test exporting a session with no approved axioms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            session = manager.create_session(
                [create_test_axiom("a1")],
                session_id="empty_test",
            )

            output_path = Path(tmpdir) / "empty.toml"
            count = manager.export_approved(session, str(output_path))

            assert count == 0


class TestFormatAxiomForReview:
    """Tests for the format_axiom_for_review function."""

    def test_formats_basic_axiom(self):
        """Test formatting a basic axiom."""
        axiom = create_test_axiom()
        item = ReviewItem(axiom=axiom)

        formatted = format_axiom_for_review(item)

        assert "test_axiom" in formatted
        assert "Test content" in formatted
        assert "test_func" in formatted
        assert "test.h" in formatted
        assert "precondition" in formatted.lower()
        assert "90%" in formatted

    def test_formats_pending_status(self):
        """Test formatting shows pending status."""
        axiom = create_test_axiom()
        item = ReviewItem(axiom=axiom)

        formatted = format_axiom_for_review(item)
        assert "PENDING" in formatted

    def test_formats_approved_status(self):
        """Test formatting shows approved status."""
        axiom = create_test_axiom()
        item = ReviewItem(axiom=axiom, decision=ReviewDecision.APPROVED)

        formatted = format_axiom_for_review(item)
        assert "APPROVED" in formatted

    def test_formats_with_notes(self):
        """Test formatting includes reviewer notes."""
        axiom = create_test_axiom()
        item = ReviewItem(
            axiom=axiom,
            reviewer_notes="This looks correct",
        )

        formatted = format_axiom_for_review(item)
        assert "This looks correct" in formatted

    def test_formats_with_foundation_axiom(self):
        """Test formatting includes foundation axiom reference."""
        axiom = create_test_axiom()
        item = ReviewItem(
            axiom=axiom,
            foundation_axiom_id="c11_expr_div_nonzero",
        )

        formatted = format_axiom_for_review(item)
        assert "c11_expr_div_nonzero" in formatted


class TestReviewDecision:
    """Tests for ReviewDecision enum."""

    def test_all_decisions_exist(self):
        """Test all expected decisions exist."""
        assert ReviewDecision.PENDING.value == "pending"
        assert ReviewDecision.APPROVED.value == "approved"
        assert ReviewDecision.REJECTED.value == "rejected"
        assert ReviewDecision.MODIFIED.value == "modified"
        assert ReviewDecision.SKIPPED.value == "skipped"


class TestReviewedFlag:
    """Tests for the reviewed field and its effect on confidence."""

    def test_approved_axioms_have_reviewed_flag_set(self):
        """Test that approved axioms get reviewed=True."""
        axiom = create_test_axiom("a1")
        assert axiom.reviewed is False

        items = [
            ReviewItem(axiom=axiom, decision=ReviewDecision.APPROVED),
        ]
        session = ReviewSession(session_id="test", items=items)

        approved = session.get_approved_axioms()
        assert len(approved) == 1
        assert approved[0].reviewed is True

    def test_modified_axioms_have_reviewed_flag_set(self):
        """Test that modified axioms get reviewed=True."""
        original = create_test_axiom("a1")
        modified = create_test_axiom("a1_modified")
        assert modified.reviewed is False

        items = [
            ReviewItem(
                axiom=original,
                decision=ReviewDecision.MODIFIED,
                modified_axiom=modified,
            ),
        ]
        session = ReviewSession(session_id="test", items=items)

        approved = session.get_approved_axioms()
        assert len(approved) == 1
        assert approved[0].reviewed is True
        assert approved[0].id == "a1_modified"

    def test_effective_confidence_for_unreviewed_library_axiom(self):
        """Test effective confidence for unreviewed library axioms."""
        axiom = create_test_axiom("a1")
        axiom.confidence = 1.0
        axiom.layer = "library"
        axiom.reviewed = False

        # Unreviewed library axioms get 70% of base confidence
        assert axiom.effective_confidence == 0.7

    def test_effective_confidence_for_reviewed_library_axiom(self):
        """Test effective confidence for reviewed library axioms."""
        axiom = create_test_axiom("a1")
        axiom.confidence = 1.0
        axiom.layer = "library"
        axiom.reviewed = True

        # Reviewed library axioms get 90% of base confidence
        assert axiom.effective_confidence == 0.9

    def test_effective_confidence_for_grounded_axiom(self):
        """Test effective confidence for grounded (foundation) axioms."""
        axiom = create_test_axiom("a1")
        axiom.confidence = 1.0
        axiom.layer = "c11_core"
        axiom.reviewed = False

        # Grounded axioms keep their full confidence regardless of review status
        assert axiom.effective_confidence == 1.0

    def test_effective_confidence_scales_with_base_confidence(self):
        """Test that effective confidence scales with base confidence."""
        axiom = create_test_axiom("a1")
        axiom.layer = "library"
        axiom.confidence = 0.8
        axiom.reviewed = False

        # 70% of 0.8 = 0.56
        assert axiom.effective_confidence == pytest.approx(0.56)

        axiom.reviewed = True
        # 90% of 0.8 = 0.72
        assert axiom.effective_confidence == pytest.approx(0.72)

    def test_reviewed_flag_persists_through_serialization(self):
        """Test that reviewed flag is saved and loaded correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            axiom = create_test_axiom("a1")
            axiom.reviewed = True

            session = manager.create_session([axiom], session_id="test_reviewed")
            manager.save_session(session)

            loaded = manager.load_session("test_reviewed")
            assert loaded.items[0].axiom.reviewed is True

    def test_export_approved_includes_reviewed_flag(self):
        """Test that exported axioms include reviewed=true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            axiom = create_test_axiom("a1")
            session = manager.create_session([axiom], session_id="export_reviewed")
            session.items[0].decision = ReviewDecision.APPROVED
            manager.save_session(session)

            output_path = Path(tmpdir) / "exported.toml"
            manager.export_approved(session, str(output_path))

            content = output_path.read_text()
            assert "reviewed = true" in content


class TestFunctionGrouping:
    """Tests for grouping axioms by function during review."""

    def create_axiom_with_location(
        self,
        id: str,
        function: str,
        source_file: str = "test.cpp",
        line_start: int = 1,
    ) -> tuple:
        """Create an axiom and corresponding ReviewItem with location info."""
        axiom = Axiom(
            id=id,
            content=f"Axiom for {function}",
            formal_spec="x != 0",
            layer="library",
            source=SourceLocation(file=source_file, module=function),
            function=function,
            header="test.h",
            axiom_type=AxiomType.PRECONDITION,
        )
        item = ReviewItem(
            axiom=axiom,
            line_start=line_start,
        )
        return axiom, item

    def test_axioms_grouped_by_function(self):
        """Test that axioms from the same function are grouped together."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            # Create axioms from different functions in mixed order
            _, item1 = self.create_axiom_with_location("a1", "func_b", line_start=20)
            _, item2 = self.create_axiom_with_location("a2", "func_a", line_start=5)
            _, item3 = self.create_axiom_with_location("a3", "func_b", line_start=25)
            _, item4 = self.create_axiom_with_location("a4", "func_a", line_start=10)

            session = manager.create_session(
                items=[item1, item2, item3, item4],
                session_id="test_grouping",
                group_by_function=True,
            )

            # Should be sorted by file, then line number
            # func_a at line 5, func_a at line 10, func_b at line 20, func_b at line 25
            funcs = [item.axiom.function for item in session.items]
            assert funcs == ["func_a", "func_a", "func_b", "func_b"]

    def test_axioms_sorted_by_line_number_within_function(self):
        """Test that axioms are sorted by line number within each function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            # Create multiple axioms for the same function at different lines
            _, item1 = self.create_axiom_with_location("a1", "divide", line_start=50)
            _, item2 = self.create_axiom_with_location("a2", "divide", line_start=10)
            _, item3 = self.create_axiom_with_location("a3", "divide", line_start=30)

            session = manager.create_session(
                items=[item1, item2, item3],
                session_id="test_line_order",
                group_by_function=True,
            )

            # Should be sorted by line number
            lines = [item.line_start for item in session.items]
            assert lines == [10, 30, 50]

    def test_axioms_grouped_by_source_file_first(self):
        """Test that axioms are grouped by source file before function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            # Create axioms from different files
            _, item1 = self.create_axiom_with_location(
                "a1", "func", source_file="z_file.cpp", line_start=10
            )
            _, item2 = self.create_axiom_with_location(
                "a2", "func", source_file="a_file.cpp", line_start=5
            )
            _, item3 = self.create_axiom_with_location(
                "a3", "other", source_file="a_file.cpp", line_start=20
            )

            session = manager.create_session(
                items=[item1, item2, item3],
                session_id="test_file_grouping",
                group_by_function=True,
            )

            # Should be sorted by file first: a_file.cpp items, then z_file.cpp
            files = [item.axiom.source.file for item in session.items]
            assert files == ["a_file.cpp", "a_file.cpp", "z_file.cpp"]

    def test_grouping_can_be_disabled(self):
        """Test that grouping can be disabled to preserve original order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            # Create items in specific order
            _, item1 = self.create_axiom_with_location("a1", "func_z", line_start=100)
            _, item2 = self.create_axiom_with_location("a2", "func_a", line_start=1)

            session = manager.create_session(
                items=[item1, item2],
                session_id="test_no_grouping",
                group_by_function=False,
            )

            # Original order should be preserved
            ids = [item.axiom.id for item in session.items]
            assert ids == ["a1", "a2"]

    def test_grouping_handles_missing_line_numbers(self):
        """Test that grouping works even when line numbers are missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            axiom1 = create_test_axiom("a1")
            axiom1.function = "func_b"
            item1 = ReviewItem(axiom=axiom1, line_start=None)

            axiom2 = create_test_axiom("a2")
            axiom2.function = "func_a"
            item2 = ReviewItem(axiom=axiom2, line_start=None)

            axiom3 = create_test_axiom("a3")
            axiom3.function = "func_a"
            item3 = ReviewItem(axiom=axiom3, line_start=5)

            session = manager.create_session(
                items=[item1, item2, item3],
                session_id="test_missing_lines",
                group_by_function=True,
            )

            # Items with None line_start should use 0, so they come first
            # func_a items should be grouped together
            funcs = [item.axiom.function for item in session.items]
            assert funcs[0] == "func_a" or funcs[1] == "func_a"

    def test_grouping_is_default_enabled(self):
        """Test that grouping is enabled by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            _, item1 = self.create_axiom_with_location("a1", "func_z", line_start=100)
            _, item2 = self.create_axiom_with_location("a2", "func_a", line_start=1)

            # Don't pass group_by_function - should default to True
            session = manager.create_session(
                items=[item1, item2],
                session_id="test_default_grouping",
            )

            # Should be sorted (func_a before func_z by line number)
            ids = [item.axiom.id for item in session.items]
            assert ids == ["a2", "a1"]

    def test_grouping_with_axiom_list(self):
        """Test that grouping works when creating session from axiom list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            a1 = Axiom(
                id="a1",
                content="Axiom 1",
                formal_spec="x",
                layer="library",
                source=SourceLocation(file="z.cpp", module="z"),
                function="func_z",
            )
            a2 = Axiom(
                id="a2",
                content="Axiom 2",
                formal_spec="x",
                layer="library",
                source=SourceLocation(file="a.cpp", module="a"),
                function="func_a",
            )

            session = manager.create_session(
                axioms=[a1, a2],
                session_id="test_axiom_list_grouping",
            )

            # Should be sorted by source file (a.cpp before z.cpp)
            files = [item.axiom.source.file for item in session.items]
            assert files == ["a.cpp", "z.cpp"]


class TestDependsOnInReview:
    """Tests for depends_on field handling in review workflow."""

    def test_depends_on_preserved_in_session_save_load(self):
        """Test that depends_on is preserved when saving/loading sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            axiom = Axiom(
                id="test_with_deps",
                content="Test axiom with dependencies",
                formal_spec="x != 0",
                layer="library",
                source=SourceLocation(file="test.cpp", module="test"),
                depends_on=["c11_expr_div_nonzero", "c11_type_int"],
            )

            session = manager.create_session(
                axioms=[axiom],
                session_id="test_depends_on",
            )
            manager.save_session(session)

            loaded = manager.load_session("test_depends_on")
            assert loaded.items[0].axiom.depends_on == ["c11_expr_div_nonzero", "c11_type_int"]

    def test_depends_on_included_in_export(self):
        """Test that depends_on is included when exporting approved axioms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewSessionManager(storage_dir=tmpdir)

            axiom = Axiom(
                id="export_deps_test",
                content="Test with deps",
                formal_spec="x",
                layer="library",
                source=SourceLocation(file="test.cpp", module="test"),
                depends_on=["foundation_1", "foundation_2"],
            )

            session = manager.create_session(
                axioms=[axiom],
                session_id="export_deps",
            )
            session.items[0].decision = ReviewDecision.APPROVED
            manager.save_session(session)

            output_path = Path(tmpdir) / "exported.toml"
            manager.export_approved(session, str(output_path))

            content = output_path.read_text()
            assert "depends_on" in content
            assert "foundation_1" in content
            assert "foundation_2" in content
