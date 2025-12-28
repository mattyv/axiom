#!/usr/bin/env python3
# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""CLI for reviewing extracted axioms.

Usage:
    python scripts/review_axioms.py --list              # List all sessions
    python scripts/review_axioms.py --session <id>      # Review a session
    python scripts/review_axioms.py --export <id> -o out.toml  # Export approved
"""

import argparse
import sys
from datetime import datetime

from axiom.ingestion.reviewer import (
    ReviewDecision,
    ReviewSession,
    ReviewSessionManager,
    format_axiom_for_review,
)
from axiom.models import Axiom, AxiomType


def clear_screen():
    """Clear the terminal screen."""
    print("\033[2J\033[H", end="")


def print_header(session: ReviewSession):
    """Print the review session header."""
    print(f"\n{'=' * 60}")
    print(f"Review Session: {session.session_id}")
    print(f"Source: {session.source_file or 'N/A'}")
    print(f"Progress: {session.reviewed_count}/{session.total_items}")
    print(f"  Approved: {session.approved_count}")
    print(f"  Rejected: {session.rejected_count}")
    print(f"  Modified: {session.modified_count}")
    print(f"{'=' * 60}\n")


def print_help():
    """Print keyboard shortcuts."""
    print("\nCommands:")
    print("  [A] Approve     - Accept this axiom as-is")
    print("  [R] Reject      - Reject this axiom")
    print("  [M] Modify      - Edit and approve")
    print("  [S] Skip        - Skip for now (mark as skipped)")
    print("  [N] Next        - Go to next item")
    print("  [P] Previous    - Go to previous item")
    print("  [J] Jump        - Jump to pending item")
    print("  [Q] Quit        - Save and exit")
    print("  [?] Help        - Show this help")
    print()


def modify_axiom(axiom: Axiom) -> Axiom:
    """Interactive axiom modification.

    Args:
        axiom: The axiom to modify.

    Returns:
        Modified axiom.
    """
    print("\nModify Axiom (press Enter to keep current value)")
    print("-" * 40)

    # Content
    print(f"\nContent [{axiom.content}]:")
    new_content = input("> ").strip()
    content = new_content if new_content else axiom.content

    # Formal spec
    print(f"\nFormal Spec [{axiom.formal_spec}]:")
    new_spec = input("> ").strip()
    formal_spec = new_spec if new_spec else axiom.formal_spec

    # Axiom type
    current_type = axiom.axiom_type.value if axiom.axiom_type else "none"
    print(f"\nAxiom Type [{current_type}]:")
    print("  Options: precondition, postcondition, invariant, exception, effect, constraint")
    new_type = input("> ").strip().lower()
    axiom_type = axiom.axiom_type
    if new_type:
        try:
            axiom_type = AxiomType(new_type)
        except ValueError:
            print(f"  Invalid type '{new_type}', keeping original")

    # On violation
    print(f"\nOn Violation [{axiom.on_violation or 'none'}]:")
    new_violation = input("> ").strip()
    on_violation = new_violation if new_violation else axiom.on_violation

    # Confidence
    print(f"\nConfidence [{axiom.confidence}]:")
    new_conf = input("> ").strip()
    confidence = axiom.confidence
    if new_conf:
        try:
            confidence = float(new_conf)
        except ValueError:
            print(f"  Invalid confidence '{new_conf}', keeping original")

    return Axiom(
        id=axiom.id,
        content=content,
        formal_spec=formal_spec,
        layer=axiom.layer,
        source=axiom.source,
        function=axiom.function,
        header=axiom.header,
        axiom_type=axiom_type,
        on_violation=on_violation,
        confidence=confidence,
        c_standard_refs=axiom.c_standard_refs,
        tags=axiom.tags,
    )


def review_session(session: ReviewSession, manager: ReviewSessionManager):
    """Interactive review loop for a session.

    Args:
        session: The review session.
        manager: Session manager for saving.
    """
    clear_screen()
    print_header(session)
    print_help()

    while True:
        item = session.get_current_item()
        if item is None:
            print("No items to review.")
            break

        # Show current item
        print(f"\nItem {session.current_index + 1} of {session.total_items}")
        print(format_axiom_for_review(item))

        # Get command (Enter = Approve)
        try:
            cmd = input("\nCommand [A/R/M/S/N/P/J/Q/?] (Enter=Approve): ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            cmd = "Q"

        # Default to Approve on empty input
        if cmd == "" or cmd == "A":
            item.decision = ReviewDecision.APPROVED
            item.reviewed_at = datetime.utcnow()
            print("  -> Approved")
            manager.save_session(session)
            if not session.next_pending():
                session.next_item()

        elif cmd == "R":
            item.decision = ReviewDecision.REJECTED
            item.reviewed_at = datetime.utcnow()
            print("  Reason (optional): ", end="")
            try:
                reason = input().strip()
            except (EOFError, KeyboardInterrupt):
                reason = ""
            item.reviewer_notes = reason
            print("  -> Rejected")
            manager.save_session(session)
            if not session.next_pending():
                session.next_item()

        elif cmd == "M":
            modified = modify_axiom(item.axiom)
            item.modified_axiom = modified
            item.decision = ReviewDecision.MODIFIED
            item.reviewed_at = datetime.utcnow()
            print("  -> Modified and approved")
            manager.save_session(session)
            if not session.next_pending():
                session.next_item()

        elif cmd == "S":
            item.decision = ReviewDecision.SKIPPED
            item.reviewed_at = datetime.utcnow()
            print("  -> Skipped")
            manager.save_session(session)
            session.next_item()

        elif cmd == "N":
            if session.next_item() is None:
                print("  Already at last item")

        elif cmd == "P":
            if session.prev_item() is None:
                print("  Already at first item")

        elif cmd == "J":
            if session.next_pending() is None:
                print("  No pending items")

        elif cmd == "Q":
            manager.save_session(session)
            print(f"\nSession saved: {session.session_id}")
            print(f"Progress: {session.reviewed_count}/{session.total_items}")
            print(f"\nTo resume: python scripts/ingest_library.py --review {session.session_id}")
            break

        elif cmd == "?":
            print_help()

        else:
            print(f"  Unknown command: {cmd}")

        # Check if complete
        if session.is_complete:
            print("\n" + "=" * 60)
            print("Review complete!")
            print(f"  Approved: {session.approved_count}")
            print(f"  Rejected: {session.rejected_count}")
            print(f"  Modified: {session.modified_count}")
            print(f"  Skipped:  {session.total_items - session.approved_count - session.rejected_count - session.modified_count}")
            print("=" * 60)

            while True:
                print("\nExport approved axioms? [y/n]: ", end="")
                try:
                    export = input().strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\n")
                    break

                if export == "y":
                    default_file = f"{session.session_id}_approved.toml"
                    print(f"Output file [{default_file}]: ", end="")
                    try:
                        output_path = input().strip()
                    except (EOFError, KeyboardInterrupt):
                        output_path = ""

                    if not output_path:
                        output_path = default_file

                    count = manager.export_approved(session, output_path)
                    print(f"Exported {count} axioms to {output_path}")
                    break
                elif export == "n":
                    break
                else:
                    print("  Please enter 'y' or 'n'")

            break


def list_sessions(manager: ReviewSessionManager):
    """List all available review sessions."""
    sessions = manager.list_sessions()

    if not sessions:
        print("No review sessions found.")
        return

    print("\nAvailable Review Sessions:")
    print("-" * 80)
    print(f"{'ID':<20} {'Created':<20} {'Progress':<15} {'Source':<25}")
    print("-" * 80)

    for s in sessions:
        progress = f"{s['reviewed']}/{s['total_items']}"
        source = s["source_file"][:25] if s["source_file"] else "N/A"
        created = s["created_at"][:19]
        print(f"{s['session_id']:<20} {created:<20} {progress:<15} {source:<25}")

    print("-" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Review extracted axioms",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/review_axioms.py --list
  python scripts/review_axioms.py --session 20231225_143022
  python scripts/review_axioms.py --export 20231225_143022 -o approved.toml
        """,
    )

    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all review sessions",
    )
    parser.add_argument(
        "--session", "-s",
        type=str,
        help="Review a specific session",
    )
    parser.add_argument(
        "--export", "-e",
        type=str,
        help="Export approved axioms from a session",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="approved_axioms.toml",
        help="Output file for export (default: approved_axioms.toml)",
    )
    parser.add_argument(
        "--storage-dir",
        type=str,
        default="./data/reviews",
        help="Directory for review session storage",
    )

    args = parser.parse_args()

    manager = ReviewSessionManager(storage_dir=args.storage_dir)

    if args.list:
        list_sessions(manager)

    elif args.session:
        session = manager.load_session(args.session)
        if session is None:
            print(f"Session '{args.session}' not found.")
            sys.exit(1)
        review_session(session, manager)

    elif args.export:
        session = manager.load_session(args.export)
        if session is None:
            print(f"Session '{args.export}' not found.")
            sys.exit(1)
        count = manager.export_approved(session, args.output)
        print(f"Exported {count} axioms to {args.output}")

    else:
        # Default: show help
        parser.print_help()


if __name__ == "__main__":
    main()
