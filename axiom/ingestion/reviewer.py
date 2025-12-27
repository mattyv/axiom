"""Human review workflow for extracted axioms.

This module provides tools for reviewing, approving, modifying, or rejecting
axioms extracted by the LLM. It maintains review state and tracks decisions.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

import toml

from axiom.models import Axiom


class ReviewDecision(str, Enum):
    """Possible decisions for a reviewed axiom."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    SKIPPED = "skipped"


@dataclass
class ReviewItem:
    """A single axiom under review."""

    axiom: Axiom
    decision: ReviewDecision = ReviewDecision.PENDING
    reviewer_notes: str = ""
    modified_axiom: Optional[Axiom] = None
    reviewed_at: Optional[datetime] = None
    source_operation_id: Optional[str] = None
    foundation_axiom_id: Optional[str] = None
    # Function context for review display
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    signature: Optional[str] = None


@dataclass
class ReviewSession:
    """A review session containing multiple axioms to review."""

    session_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    source_file: str = ""
    items: List[ReviewItem] = field(default_factory=list)
    current_index: int = 0

    @property
    def total_items(self) -> int:
        """Total number of items in the session."""
        return len(self.items)

    @property
    def reviewed_count(self) -> int:
        """Number of items that have been reviewed."""
        return sum(
            1 for item in self.items if item.decision != ReviewDecision.PENDING
        )

    @property
    def approved_count(self) -> int:
        """Number of approved items."""
        return sum(
            1 for item in self.items if item.decision == ReviewDecision.APPROVED
        )

    @property
    def rejected_count(self) -> int:
        """Number of rejected items."""
        return sum(
            1 for item in self.items if item.decision == ReviewDecision.REJECTED
        )

    @property
    def modified_count(self) -> int:
        """Number of modified items."""
        return sum(
            1 for item in self.items if item.decision == ReviewDecision.MODIFIED
        )

    @property
    def is_complete(self) -> bool:
        """Check if all items have been reviewed."""
        return self.reviewed_count == self.total_items

    def get_current_item(self) -> Optional[ReviewItem]:
        """Get the current item under review."""
        if 0 <= self.current_index < len(self.items):
            return self.items[self.current_index]
        return None

    def next_item(self) -> Optional[ReviewItem]:
        """Move to the next item."""
        if self.current_index < len(self.items) - 1:
            self.current_index += 1
            return self.get_current_item()
        return None

    def prev_item(self) -> Optional[ReviewItem]:
        """Move to the previous item."""
        if self.current_index > 0:
            self.current_index -= 1
            return self.get_current_item()
        return None

    def next_pending(self) -> Optional[ReviewItem]:
        """Move to the next pending item."""
        for i in range(self.current_index + 1, len(self.items)):
            if self.items[i].decision == ReviewDecision.PENDING:
                self.current_index = i
                return self.items[i]
        # Wrap around to beginning
        for i in range(0, self.current_index):
            if self.items[i].decision == ReviewDecision.PENDING:
                self.current_index = i
                return self.items[i]
        return None

    def get_approved_axioms(self) -> List[Axiom]:
        """Get all approved axioms (including modified ones).

        Sets reviewed=True on all returned axioms to indicate human approval.
        """
        result = []
        for item in self.items:
            if item.decision == ReviewDecision.APPROVED:
                # Mark as reviewed for confidence calculation
                item.axiom.reviewed = True
                result.append(item.axiom)
            elif item.decision == ReviewDecision.MODIFIED and item.modified_axiom:
                # Modified axioms are also considered reviewed
                item.modified_axiom.reviewed = True
                result.append(item.modified_axiom)
        return result


class ReviewSessionManager:
    """Manage review sessions with persistence."""

    def __init__(self, storage_dir: str = "./data/reviews"):
        """Initialize the session manager.

        Args:
            storage_dir: Directory to store review sessions.
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def create_session(
        self,
        axioms: Optional[List[Axiom]] = None,
        session_id: Optional[str] = None,
        source_file: str = "",
        items: Optional[List[ReviewItem]] = None,
        group_by_function: bool = True,
    ) -> ReviewSession:
        """Create a new review session.

        Args:
            axioms: List of axioms to review (creates ReviewItem for each).
            session_id: Optional session ID (auto-generated if not provided).
            source_file: Source file the axioms came from.
            items: Optional list of ReviewItem objects (if provided, axioms is ignored).
            group_by_function: If True, sort items so axioms from the same function
                are grouped together (default: True).

        Returns:
            New ReviewSession object.
        """
        if session_id is None:
            session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        if items is None:
            items = [ReviewItem(axiom=axiom) for axiom in (axioms or [])]

        # Group items by function so related axioms are reviewed together
        if group_by_function and items:
            items = self._sort_items_by_function(items)

        session = ReviewSession(
            session_id=session_id,
            source_file=source_file,
            items=items,
        )

        self.save_session(session)
        return session

    def _sort_items_by_function(self, items: List[ReviewItem]) -> List[ReviewItem]:
        """Sort review items so axioms from the same function are grouped together.

        Sorting order:
        1. By source file (axiom.source.file)
        2. By line number (item.line_start) within each file
        3. By function name as fallback

        This ensures axioms are reviewed in a logical order that follows
        the structure of the source code.

        Args:
            items: List of review items to sort.

        Returns:
            Sorted list of review items.
        """
        def sort_key(item: ReviewItem):
            axiom = item.axiom
            # Primary: source file
            source_file = axiom.source.file if axiom.source else ""
            # Secondary: line number (use 0 if not available)
            line_num = item.line_start if item.line_start is not None else 0
            # Tertiary: function name
            func_name = axiom.function or ""
            return (source_file, line_num, func_name)

        return sorted(items, key=sort_key)

    def save_session(self, session: ReviewSession) -> None:
        """Save a review session to disk.

        Args:
            session: The session to save.
        """
        path = self.storage_dir / f"{session.session_id}.json"

        data = {
            "session_id": session.session_id,
            "created_at": session.created_at.isoformat(),
            "source_file": session.source_file,
            "current_index": session.current_index,
            "items": [
                {
                    "axiom": self._axiom_to_dict(item.axiom),
                    "decision": item.decision.value,
                    "reviewer_notes": item.reviewer_notes,
                    "modified_axiom": (
                        self._axiom_to_dict(item.modified_axiom)
                        if item.modified_axiom
                        else None
                    ),
                    "reviewed_at": (
                        item.reviewed_at.isoformat() if item.reviewed_at else None
                    ),
                    "source_operation_id": item.source_operation_id,
                    "foundation_axiom_id": item.foundation_axiom_id,
                    "line_start": item.line_start,
                    "line_end": item.line_end,
                    "signature": item.signature,
                }
                for item in session.items
            ],
        }

        path.write_text(json.dumps(data, indent=2))

    def load_session(self, session_id: str) -> Optional[ReviewSession]:
        """Load a review session from disk.

        Args:
            session_id: The session ID to load.

        Returns:
            ReviewSession if found, None otherwise.
        """
        path = self.storage_dir / f"{session_id}.json"
        if not path.exists():
            return None

        data = json.loads(path.read_text())

        items = []
        for item_data in data["items"]:
            axiom = self._dict_to_axiom(item_data["axiom"])
            modified = (
                self._dict_to_axiom(item_data["modified_axiom"])
                if item_data["modified_axiom"]
                else None
            )
            reviewed_at = (
                datetime.fromisoformat(item_data["reviewed_at"])
                if item_data["reviewed_at"]
                else None
            )

            items.append(
                ReviewItem(
                    axiom=axiom,
                    decision=ReviewDecision(item_data["decision"]),
                    reviewer_notes=item_data["reviewer_notes"],
                    modified_axiom=modified,
                    reviewed_at=reviewed_at,
                    source_operation_id=item_data.get("source_operation_id"),
                    foundation_axiom_id=item_data.get("foundation_axiom_id"),
                    line_start=item_data.get("line_start"),
                    line_end=item_data.get("line_end"),
                    signature=item_data.get("signature"),
                )
            )

        return ReviewSession(
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            source_file=data["source_file"],
            items=items,
            current_index=data["current_index"],
        )

    def list_sessions(self) -> List[dict]:
        """List all available review sessions.

        Returns:
            List of session summaries.
        """
        sessions = []
        for path in self.storage_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                sessions.append(
                    {
                        "session_id": data["session_id"],
                        "created_at": data["created_at"],
                        "source_file": data["source_file"],
                        "total_items": len(data["items"]),
                        "reviewed": sum(
                            1
                            for item in data["items"]
                            if item["decision"] != "pending"
                        ),
                    }
                )
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x["created_at"], reverse=True)

    def export_approved(
        self,
        session: ReviewSession,
        output_path: str,
    ) -> int:
        """Export approved axioms to TOML file.

        Args:
            session: The review session.
            output_path: Path to output TOML file.

        Returns:
            Number of axioms exported.
        """
        axioms = session.get_approved_axioms()

        if not axioms:
            return 0

        # Convert to TOML format
        data = {"axioms": []}
        for axiom in axioms:
            axiom_dict = {
                "id": axiom.id,
                "content": axiom.content,
                "formal_spec": axiom.formal_spec,
                "layer": axiom.layer,
            }

            if axiom.function:
                axiom_dict["function"] = axiom.function
            if axiom.header:
                axiom_dict["header"] = axiom.header
            if axiom.axiom_type:
                axiom_dict["axiom_type"] = axiom.axiom_type.value
            if axiom.on_violation:
                axiom_dict["on_violation"] = axiom.on_violation
            if axiom.c_standard_refs:
                axiom_dict["c_standard_refs"] = axiom.c_standard_refs
            if axiom.confidence != 1.0:
                axiom_dict["confidence"] = axiom.confidence
            if axiom.reviewed:
                axiom_dict["reviewed"] = True
            if axiom.depends_on:
                axiom_dict["depends_on"] = axiom.depends_on

            data["axioms"].append(axiom_dict)

        Path(output_path).write_text(toml.dumps(data))
        return len(axioms)

    @staticmethod
    def _axiom_to_dict(axiom: Axiom) -> dict:
        """Convert an Axiom to a serializable dict."""
        return {
            "id": axiom.id,
            "content": axiom.content,
            "formal_spec": axiom.formal_spec,
            "layer": axiom.layer,
            "source_file": axiom.source.file,
            "source_module": axiom.source.module,
            "function": axiom.function,
            "header": axiom.header,
            "axiom_type": axiom.axiom_type.value if axiom.axiom_type else None,
            "on_violation": axiom.on_violation,
            "confidence": axiom.confidence,
            "c_standard_refs": axiom.c_standard_refs,
            "tags": axiom.tags,
            "reviewed": axiom.reviewed,
            "depends_on": axiom.depends_on,
        }

    @staticmethod
    def _dict_to_axiom(data: dict) -> Axiom:
        """Convert a dict back to an Axiom."""
        from axiom.models import AxiomType, SourceLocation

        axiom_type = None
        if data.get("axiom_type"):
            try:
                axiom_type = AxiomType(data["axiom_type"])
            except ValueError:
                pass

        return Axiom(
            id=data["id"],
            content=data["content"],
            formal_spec=data["formal_spec"],
            layer=data["layer"],
            source=SourceLocation(
                file=data.get("source_file", ""),
                module=data.get("source_module", ""),
            ),
            function=data.get("function"),
            header=data.get("header"),
            axiom_type=axiom_type,
            on_violation=data.get("on_violation"),
            confidence=data.get("confidence", 1.0),
            c_standard_refs=data.get("c_standard_refs", []),
            tags=data.get("tags", []),
            reviewed=data.get("reviewed", False),
            depends_on=data.get("depends_on", []),
        )


def format_axiom_for_review(item: ReviewItem) -> str:
    """Format a review item for display.

    Args:
        item: The review item to format.

    Returns:
        Formatted string for terminal display.
    """
    axiom = item.axiom
    lines = [
        "=" * 60,
        f"AXIOM: {axiom.id}",
        "=" * 60,
        "",
    ]

    # Show function signature if available
    if item.signature:
        lines.append(f"Signature: {item.signature}")
    else:
        lines.append(f"Function:  {axiom.function or 'N/A'}")

    # Show line numbers if available
    if item.line_start is not None and item.line_end is not None:
        lines.append(f"Lines:     {item.line_start}-{item.line_end}")
    elif item.line_start is not None:
        lines.append(f"Line:      {item.line_start}")

    lines.extend([
        f"Header:    {axiom.header or 'N/A'}",
        f"Type:      {axiom.axiom_type.value if axiom.axiom_type else 'N/A'}",
        "",
        "Content:",
        f"  {axiom.content}",
        "",
    ])

    if axiom.formal_spec:
        lines.extend([
            "Formal Spec:",
            f"  {axiom.formal_spec}",
            "",
        ])

    if axiom.on_violation:
        lines.extend([
            "On Violation:",
            f"  {axiom.on_violation}",
            "",
        ])

    # Show depends_on from axiom (1:many relationship)
    if axiom.depends_on:
        lines.extend([
            "Depends On:",
        ])
        for dep_id in axiom.depends_on:
            lines.append(f"  - {dep_id}")
        lines.append("")
    elif item.foundation_axiom_id:
        # Fallback for legacy single dependency
        lines.extend([
            "Depends On:",
            f"  {item.foundation_axiom_id}",
            "",
        ])

    lines.extend([
        f"Confidence: {axiom.confidence:.0%}",
        f"Status:     {item.decision.value.upper()}",
    ])

    if item.reviewer_notes:
        lines.extend([
            "",
            "Reviewer Notes:",
            f"  {item.reviewer_notes}",
        ])

    lines.append("=" * 60)

    return "\n".join(lines)
