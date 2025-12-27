#!/usr/bin/env python3
"""Ingest axioms from a C/C++ library using Claude CLI.

This script provides end-to-end ingestion of library axioms:
1. Parse source files and build function/macro subgraphs
2. Extract axioms using Claude CLI + RAG
3. Create review session for human approval
4. Export approved axioms to TOML

By default, axioms are extracted from BOTH functions AND macros.

Usage:
    # Ingest a single file (functions + macros)
    python scripts/ingest_library.py path/to/source.cpp

    # Ingest a directory recursively (functions + macros)
    python scripts/ingest_library.py path/to/library/ --recursive

    # Only extract from functions (skip macros)
    python scripts/ingest_library.py path/to/source.cpp --functions-only

    # Only extract from macros (skip functions)
    python scripts/ingest_library.py path/to/source.cpp --macros-only

    # Only extract from hazardous macros (with division, pointers, casts, calls)
    python scripts/ingest_library.py path/to/source.cpp --hazardous-only

    # Ingest specific functions
    python scripts/ingest_library.py path/to/source.cpp -f malloc -f free

    # Use existing RAG database
    python scripts/ingest_library.py path/to/source.cpp --rag-db ./data/lancedb

    # Skip extraction, just parse and show subgraphs
    python scripts/ingest_library.py path/to/source.cpp --parse-only

    # Resume a review session
    python scripts/ingest_library.py --review <session_id>

    # Ignore additional patterns
    python scripts/ingest_library.py path/to/lib/ -r --ignore "test*" --ignore "bench/"

Ignore Patterns (.axignore):
    The script automatically loads a .axignore file from the source directory.
    This file uses gitignore-style patterns to exclude files/directories:

        # Directories (trailing slash)
        build/
        tests/

        # File patterns
        *_test.cpp
        *.generated.h

        # Specific paths
        vendor/third_party/

    Use --no-axignore to disable. See .axignore.example for a template.
"""

import argparse
import fnmatch
import itertools
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from axiom.ingestion import (
    AxiomExtractor,
    ExtractionResult,
    ReviewSessionManager,
    SubgraphBuilder,
)
from axiom.ingestion.extractor import MacroExtractionResult
from axiom.ingestion.reviewer import format_axiom_for_review, ReviewItem
from axiom.models import Axiom


class Spinner:
    """A simple terminal spinner for long-running operations."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = ""):
        self.message = message
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop_event.is_set():
                break
            sys.stdout.write(f"\r{frame} {self.message}")
            sys.stdout.flush()
            time.sleep(0.1)

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self, final_message: str = ""):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        # Clear the line and print final message
        sys.stdout.write("\r" + " " * (len(self.message) + 10) + "\r")
        if final_message:
            print(final_message)
        sys.stdout.flush()

    def update(self, message: str):
        self.message = message


class ProgressTracker:
    """Combined progress tracker with file and function info."""

    def __init__(self, total_files: int, width: int = 30):
        self.total_files = total_files
        self.current_file = 0
        self.current_file_name = ""
        self.current_func = ""
        self.func_progress = ""
        self.width = width
        self.start_time = time.time()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _render(self) -> str:
        with self._lock:
            percent = self.current_file / self.total_files if self.total_files > 0 else 0
            filled = int(self.width * percent)
            bar = "█" * filled + "░" * (self.width - filled)

            elapsed = time.time() - self.start_time
            if self.current_file > 0:
                eta = (elapsed / self.current_file) * (self.total_files - self.current_file)
                eta_str = f"ETA: {int(eta)}s"
            else:
                eta_str = "ETA: --"

            # Build status line
            status = f"[{bar}] {self.current_file}/{self.total_files} {eta_str}"

            # Add current operation info
            if self.current_func:
                func_info = f" | {self.current_file_name}: {self.current_func}"
                if self.func_progress:
                    func_info += f" {self.func_progress}"
                status += func_info[:50]  # Truncate to fit

            return status

    def _spin(self):
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        for frame in itertools.cycle(frames):
            if self._stop_event.is_set():
                break
            status = self._render()
            sys.stdout.write(f"\r{frame} {status}" + " " * 20)
            sys.stdout.flush()
            time.sleep(0.1)

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        sys.stdout.write("\r" + " " * 100 + "\r")
        sys.stdout.flush()

    def set_file(self, file_num: int, file_name: str):
        with self._lock:
            self.current_file = file_num
            self.current_file_name = file_name
            self.current_func = ""
            self.func_progress = ""

    def set_function(self, func_name: str, current: int, total: int):
        with self._lock:
            self.current_func = func_name
            self.func_progress = f"({current}/{total})"


def load_axignore(root_path: Path) -> List[str]:
    """Load ignore patterns from .axignore file.

    Args:
        root_path: Root directory to search for .axignore.

    Returns:
        List of ignore patterns (gitignore-style).
    """
    axignore_path = root_path / ".axignore"
    if not axignore_path.exists():
        return []

    patterns = []
    with open(axignore_path) as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            patterns.append(line)

    return patterns


def should_ignore(file_path: Path, root_path: Path, patterns: List[str]) -> bool:
    """Check if a file should be ignored based on patterns.

    Args:
        file_path: Path to check.
        root_path: Root directory for relative path calculation.
        patterns: List of gitignore-style patterns.

    Returns:
        True if the file should be ignored.
    """
    if not patterns:
        return False

    # Get path relative to root
    try:
        rel_path = file_path.relative_to(root_path)
    except ValueError:
        rel_path = file_path

    rel_str = str(rel_path)
    rel_parts = rel_path.parts

    for pattern in patterns:
        # Directory pattern (ends with /)
        if pattern.endswith("/"):
            dir_pattern = pattern.rstrip("/")
            # Check if any part of the path matches
            for i, part in enumerate(rel_parts[:-1]):  # Exclude filename
                if fnmatch.fnmatch(part, dir_pattern):
                    return True
            # Also check full directory paths
            for i in range(len(rel_parts) - 1):
                partial = "/".join(rel_parts[: i + 1])
                if fnmatch.fnmatch(partial, dir_pattern):
                    return True
                if fnmatch.fnmatch(partial + "/", pattern):
                    return True
        # File pattern with path
        elif "/" in pattern:
            if fnmatch.fnmatch(rel_str, pattern):
                return True
        # Simple pattern (match filename or any directory component)
        else:
            # Match filename
            if fnmatch.fnmatch(file_path.name, pattern):
                return True
            # Match any directory in path
            for part in rel_parts:
                if fnmatch.fnmatch(part, pattern):
                    return True

    return False


def find_source_files(
    path: Path,
    recursive: bool = False,
    language: str = "cpp",
    ignore_patterns: Optional[List[str]] = None,
) -> List[Path]:
    """Find C/C++ source files in a path.

    Args:
        path: File or directory path.
        recursive: Whether to search recursively.
        language: "c" or "cpp".
        ignore_patterns: List of gitignore-style patterns to exclude.

    Returns:
        List of source file paths.
    """
    if path.is_file():
        if ignore_patterns and should_ignore(path, path.parent, ignore_patterns):
            return []
        return [path]

    if language == "c":
        file_patterns = ["*.c", "*.h"]
    else:
        file_patterns = ["*.cpp", "*.cc", "*.cxx", "*.hpp", "*.h", "*.hxx"]

    files = []
    for pattern in file_patterns:
        if recursive:
            candidates = path.rglob(pattern)
        else:
            candidates = path.glob(pattern)

        for f in candidates:
            if ignore_patterns and should_ignore(f, path, ignore_patterns):
                continue
            files.append(f)

    return sorted(files)


def discover_functions(source_path: Path, builder: SubgraphBuilder) -> List[str]:
    """Discover all functions in a source file.

    Args:
        source_path: Path to source file.
        builder: SubgraphBuilder instance.

    Returns:
        List of function names.
    """
    source_code = source_path.read_text()
    subgraphs = builder.build_all(source_code)
    return [sg.name for sg in subgraphs]


def extract_from_file(
    source_path: Path,
    extractor: AxiomExtractor,
    function_names: Optional[List[str]] = None,
    verbose: bool = False,
    tracker: Optional[ProgressTracker] = None,
) -> List[ExtractionResult]:
    """Extract axioms from a source file.

    Args:
        source_path: Path to source file.
        extractor: AxiomExtractor instance.
        function_names: Optional list of specific functions.
        verbose: Print progress.
        tracker: Optional progress tracker for updates.

    Returns:
        List of extraction results.
    """
    # Progress callback for function-level updates
    def on_function_progress(func_name: str, current: int, total: int):
        if tracker:
            tracker.set_function(func_name, current, total)

    if verbose:
        print(f"\nProcessing: {source_path}")

    results = extractor.extract_from_file(
        str(source_path),
        function_names,
        progress_callback=on_function_progress if tracker else None,
    )

    for result in results:
        if result.error:
            if verbose:
                print(f"  ERROR: {result.function_name}: {result.error}")
        elif result.axioms:
            if verbose:
                print(f"  {result.function_name}: {len(result.axioms)} axioms extracted")
        else:
            if verbose:
                print(f"  {result.function_name}: no hazardous operations")

    return results


def show_subgraph(source_path: Path, builder: SubgraphBuilder, function_name: str):
    """Display the subgraph for a function.

    Args:
        source_path: Path to source file.
        builder: SubgraphBuilder instance.
        function_name: Name of the function.
    """
    source_code = source_path.read_text()
    subgraph = builder.build(source_code, function_name)

    if subgraph is None:
        print(f"  Function '{function_name}' not found")
        return

    print(f"\n  Function: {function_name}")
    print(f"  Lines: {subgraph.line_start}-{subgraph.line_end}")
    print(f"  Parameters: {', '.join(subgraph.parameters)}")
    print(f"  Return type: {subgraph.return_type}")
    print(f"  Operations: {len(subgraph.operations)}")

    divisions = subgraph.get_divisions()
    pointers = subgraph.get_pointer_operations()
    memory = subgraph.get_memory_operations()
    calls = subgraph.get_function_calls()

    if divisions:
        print(f"    Divisions: {[d.source_text for d in divisions]}")
    if pointers:
        print(f"    Pointer ops: {[p.source_text for p in pointers]}")
    if memory:
        print(f"    Memory ops: {[m.source_text for m in memory]}")
    if calls:
        print(f"    Function calls: {[c.source_text for c in calls]}")

    if not (divisions or pointers or memory or calls):
        print("    No hazardous operations detected")


def create_review_session(
    results: List[ExtractionResult],
    manager: ReviewSessionManager,
    source_file: str,
) -> Optional[str]:
    """Create a review session from extraction results.

    Args:
        results: List of extraction results.
        manager: ReviewSessionManager instance.
        source_file: Source file path for metadata.

    Returns:
        Session ID or None if no axioms.
    """
    all_items = []
    for result in results:
        # Get subgraph info for this function
        subgraph = result.subgraph
        line_start = subgraph.line_start if subgraph else None
        line_end = subgraph.line_end if subgraph else None
        signature = subgraph.signature if subgraph else None

        # Create ReviewItem for each axiom with function context
        for axiom in result.axioms:
            item = ReviewItem(
                axiom=axiom,
                line_start=line_start,
                line_end=line_end,
                signature=signature,
            )
            all_items.append(item)

    if not all_items:
        return None

    session = manager.create_session(items=all_items, source_file=source_file)
    return session.session_id


def extract_macros_from_file(
    source_path: Path,
    extractor: AxiomExtractor,
    only_hazardous: bool = True,
    verbose: bool = False,
    tracker: Optional[ProgressTracker] = None,
) -> List[MacroExtractionResult]:
    """Extract axioms from macros in a source file.

    Args:
        source_path: Path to source file.
        extractor: AxiomExtractor instance.
        only_hazardous: Only extract from hazardous macros.
        verbose: Print progress.
        tracker: Optional progress tracker for updates.

    Returns:
        List of macro extraction results.
    """
    # Progress callback for macro-level updates
    def on_macro_progress(macro_name: str, current: int, total: int):
        if tracker:
            tracker.set_function(macro_name, current, total)

    if verbose:
        print(f"\nProcessing macros: {source_path}")

    results = extractor.extract_macros_from_file(
        str(source_path),
        only_hazardous=only_hazardous,
        progress_callback=on_macro_progress if tracker else None,
    )

    for result in results:
        if result.error:
            if verbose:
                print(f"  ERROR: {result.macro_name}: {result.error}")
        elif result.axioms:
            if verbose:
                print(f"  {result.macro_name}: {len(result.axioms)} axioms extracted")
        else:
            if verbose:
                print(f"  {result.macro_name}: no axioms needed")

    return results


def create_macro_review_session(
    results: List[MacroExtractionResult],
    manager: ReviewSessionManager,
    source_file: str,
) -> Optional[str]:
    """Create a review session from macro extraction results.

    Args:
        results: List of macro extraction results.
        manager: ReviewSessionManager instance.
        source_file: Source file path for metadata.

    Returns:
        Session ID or None if no axioms.
    """
    all_items = []
    for result in results:
        # Get macro info
        macro = result.macro
        line_start = macro.line_start if macro else None
        line_end = macro.line_end if macro else None
        signature = macro.to_signature() if macro else result.macro_name

        # Create ReviewItem for each axiom with macro context
        for axiom in result.axioms:
            item = ReviewItem(
                axiom=axiom,
                line_start=line_start,
                line_end=line_end,
                signature=f"#define {signature}",
            )
            all_items.append(item)

    if not all_items:
        return None

    session = manager.create_session(items=all_items, source_file=source_file)
    return session.session_id


def discover_macros(source_path: Path, builder: SubgraphBuilder, only_hazardous: bool = True) -> List[str]:
    """Discover all macros in a source file.

    Args:
        source_path: Path to source file.
        builder: SubgraphBuilder instance.
        only_hazardous: Only return hazardous macros.

    Returns:
        List of macro names.
    """
    source_code = source_path.read_text()
    macros = builder.extract_macros(source_code, str(source_path))

    if only_hazardous:
        macros = [m for m in macros if builder.has_hazardous_macro(m)]

    return [m.name for m in macros]


def show_macro(source_path: Path, builder: SubgraphBuilder, macro_name: str):
    """Display details of a macro.

    Args:
        source_path: Path to source file.
        builder: SubgraphBuilder instance.
        macro_name: Name of the macro.
    """
    source_code = source_path.read_text()
    macros = builder.extract_macros(source_code, str(source_path))

    macro = next((m for m in macros if m.name == macro_name), None)

    if macro is None:
        print(f"  Macro '{macro_name}' not found")
        return

    print(f"\n  Macro: {macro.to_signature()}")
    print(f"  Line: {macro.line_start}")
    print(f"  Body: {macro.body}")
    print(f"  Function-like: {macro.is_function_like}")

    if macro.has_division:
        print("    Has division: Yes")
    if macro.has_pointer_ops:
        print("    Has pointer ops: Yes")
    if macro.has_casts:
        print("    Has casts: Yes")
    if macro.function_calls:
        print(f"    Function calls: {macro.function_calls}")
    if macro.referenced_macros:
        print(f"    Referenced macros: {macro.referenced_macros}")

    if not builder.has_hazardous_macro(macro):
        print("    No hazardous operations detected")


def run_review(manager: ReviewSessionManager, session_id: str):
    """Run the interactive review for a session.

    Args:
        manager: ReviewSessionManager instance.
        session_id: Session ID to review.
    """
    # Import the review function from the CLI script
    from scripts.review_axioms import review_session

    session = manager.load_session(session_id)
    if session is None:
        print(f"Session '{session_id}' not found.")
        sys.exit(1)

    review_session(session, manager)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest axioms from a C/C++ library",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "source",
        nargs="?",
        type=str,
        help="Source file or directory to ingest",
    )
    parser.add_argument(
        "-f", "--function",
        action="append",
        dest="functions",
        help="Specific function(s) to extract (can be repeated)",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Recursively search directories",
    )
    parser.add_argument(
        "-l", "--language",
        choices=["c", "cpp"],
        default="cpp",
        help="Source language (default: cpp)",
    )
    parser.add_argument(
        "--rag-db",
        type=str,
        default="./data/lancedb",
        help="Path to LanceDB for RAG queries",
    )
    parser.add_argument(
        "--no-rag",
        action="store_true",
        help="Disable RAG (no foundation axiom context)",
    )
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Only parse and show subgraphs, don't extract",
    )
    parser.add_argument(
        "--list-functions",
        action="store_true",
        help="List all functions in source files",
    )
    parser.add_argument(
        "--functions-only",
        action="store_true",
        help="Only extract axioms from functions (skip macros)",
    )
    parser.add_argument(
        "--macros-only",
        action="store_true",
        help="Only extract axioms from macros (skip functions)",
    )
    parser.add_argument(
        "--hazardous-only",
        action="store_true",
        help="Only process hazardous macros (division, pointers, casts, function calls)",
    )
    parser.add_argument(
        "--list-macros",
        action="store_true",
        help="List all macros in source files",
    )
    parser.add_argument(
        "--review",
        type=str,
        metavar="SESSION_ID",
        help="Resume reviewing a session",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List all review sessions",
    )
    parser.add_argument(
        "--export",
        type=str,
        metavar="SESSION_ID",
        help="Export approved axioms from a session",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="extracted_axioms.toml",
        help="Output file for export (default: extracted_axioms.toml)",
    )
    parser.add_argument(
        "--storage-dir",
        type=str,
        default="./data/reviews",
        help="Directory for review sessions",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--ignore",
        type=str,
        metavar="PATTERN",
        action="append",
        dest="ignore_patterns",
        help="Additional ignore pattern (gitignore-style, can be repeated)",
    )
    parser.add_argument(
        "--no-axignore",
        action="store_true",
        help="Don't load .axignore file from source directory",
    )

    args = parser.parse_args()

    # Initialize review manager
    manager = ReviewSessionManager(storage_dir=args.storage_dir)

    # Handle review-only commands
    if args.list_sessions:
        sessions = manager.list_sessions()
        if not sessions:
            print("No review sessions found.")
        else:
            print(f"\n{'ID':<25} {'Created':<20} {'Progress':<12} {'Source'}")
            print("-" * 80)
            for s in sessions:
                progress = f"{s['reviewed']}/{s['total_items']}"
                source = s["source_file"][:30] if s["source_file"] else "N/A"
                created = s["created_at"][:19]
                print(f"{s['session_id']:<25} {created:<20} {progress:<12} {source}")
        return

    if args.review:
        run_review(manager, args.review)
        return

    if args.export:
        session = manager.load_session(args.export)
        if session is None:
            print(f"Session '{args.export}' not found.")
            sys.exit(1)
        count = manager.export_approved(session, args.output)
        print(f"Exported {count} axioms to {args.output}")
        return

    # Require source for extraction commands
    if not args.source:
        parser.print_help()
        sys.exit(1)

    source_path = Path(args.source)
    if not source_path.exists():
        print(f"Error: {args.source} does not exist")
        sys.exit(1)

    # Load ignore patterns
    ignore_patterns = []
    root_path = source_path if source_path.is_dir() else source_path.parent

    # Load .axignore by default (unless --no-axignore)
    if not args.no_axignore:
        axignore_patterns = load_axignore(root_path)
        if axignore_patterns:
            ignore_patterns.extend(axignore_patterns)
            if args.verbose:
                print(f"Loaded {len(axignore_patterns)} patterns from .axignore")

    # Add command-line ignore patterns
    if args.ignore_patterns:
        ignore_patterns.extend(args.ignore_patterns)

    # Find source files
    files = find_source_files(source_path, args.recursive, args.language, ignore_patterns)
    if not files:
        print(f"No source files found in {args.source}")
        sys.exit(1)

    if args.verbose:
        print(f"Found {len(files)} source file(s)")

    # Initialize builder
    builder = SubgraphBuilder(language=args.language)

    # List functions mode
    if args.list_functions:
        for f in files:
            functions = discover_functions(f, builder)
            print(f"\n{f}:")
            for func in functions:
                print(f"  {func}")
        return

    # List macros mode
    if args.list_macros:
        only_hazardous = args.hazardous_only
        for f in files:
            macros = discover_macros(f, builder, only_hazardous=only_hazardous)
            print(f"\n{f}:")
            if macros:
                for macro in macros:
                    print(f"  {macro}")
            else:
                label = "hazardous macros" if args.hazardous_only else "macros"
                print(f"  (no {label})")
        return

    # Parse-only mode
    if args.parse_only:
        for f in files:
            print(f"\n{'=' * 60}")
            print(f"File: {f}")
            print("=" * 60)

            if args.functions:
                for func in args.functions:
                    show_subgraph(f, builder, func)
            else:
                functions = discover_functions(f, builder)
                for func in functions:
                    show_subgraph(f, builder, func)
        return

    # Initialize extractor with Claude CLI
    vector_db = None
    if not args.no_rag:
        try:
            from axiom.vectors.loader import LanceDBLoader
            rag_path = Path(args.rag_db)
            if rag_path.exists():
                vector_db = LanceDBLoader(db_path=str(rag_path))
                if args.verbose:
                    print(f"Using RAG database: {args.rag_db}")
            else:
                if args.verbose:
                    print(f"RAG database not found at {args.rag_db}, proceeding without RAG")
        except Exception as e:
            if args.verbose:
                print(f"Could not load RAG database: {e}")

    extractor = AxiomExtractor(
        llm_client="claude-cli",
        vector_db=vector_db,
        language=args.language,
    )

    # Determine what to extract
    extract_functions = not args.macros_only
    extract_macros = not args.functions_only
    only_hazardous_macros = args.hazardous_only

    # Build description of what we're extracting
    if extract_functions and extract_macros:
        extract_desc = "functions and macros"
    elif extract_functions:
        extract_desc = "functions"
    else:
        extract_desc = "macros"

    # Extract axioms with progress indication
    all_function_results = []
    all_macro_results = []
    total_files = len(files)

    print(f"\nExtracting axioms from {extract_desc} in {total_files} file(s)...")
    print()

    if args.verbose:
        # Verbose mode: no progress bar, detailed output
        for i, f in enumerate(files, 1):
            print(f"[{i}/{total_files}] {f.name}")
            if extract_functions:
                results = extract_from_file(f, extractor, args.functions, args.verbose)
                all_function_results.extend(results)
            if extract_macros:
                macro_results = extract_macros_from_file(
                    f, extractor, only_hazardous_macros, args.verbose
                )
                all_macro_results.extend(macro_results)
    else:
        # Normal mode: unified progress tracker
        tracker = ProgressTracker(total_files)
        tracker.start()

        try:
            for i, f in enumerate(files):
                tracker.set_file(i, f.name)
                if extract_functions:
                    results = extract_from_file(f, extractor, args.functions, tracker=tracker)
                    all_function_results.extend(results)
                if extract_macros:
                    macro_results = extract_macros_from_file(
                        f, extractor, only_hazardous_macros, tracker=tracker
                    )
                    all_macro_results.extend(macro_results)
                tracker.set_file(i + 1, "")  # Update completed count
        finally:
            tracker.stop()

        elapsed = time.time() - tracker.start_time
        print(f"Completed in {elapsed:.1f}s")

    # Count results
    func_axioms = sum(len(r.axioms) for r in all_function_results)
    macro_axioms = sum(len(r.axioms) for r in all_macro_results)
    total_axioms = func_axioms + macro_axioms
    total_functions = len(all_function_results)
    total_macros = len(all_macro_results)
    func_errors = sum(1 for r in all_function_results if r.error)
    macro_errors = sum(1 for r in all_macro_results if r.error)
    total_errors = func_errors + macro_errors

    print(f"\n{'=' * 60}")
    print("Extraction Summary")
    print("=" * 60)
    print(f"Files processed:     {total_files}")
    if extract_functions:
        print(f"Functions analyzed:  {total_functions} ({func_axioms} axioms)")
    if extract_macros:
        print(f"Macros analyzed:     {total_macros} ({macro_axioms} axioms)")
    print(f"Total axioms:        {total_axioms}")
    print(f"Errors:              {total_errors}")

    if total_axioms == 0:
        print("\nNo axioms extracted. Nothing to review.")
        return

    # Create combined review session with all items
    all_items = []

    # Add function axioms
    for result in all_function_results:
        subgraph = result.subgraph
        line_start = subgraph.line_start if subgraph else None
        line_end = subgraph.line_end if subgraph else None
        signature = subgraph.signature if subgraph else None

        for axiom in result.axioms:
            item = ReviewItem(
                axiom=axiom,
                line_start=line_start,
                line_end=line_end,
                signature=signature,
            )
            all_items.append(item)

    # Add macro axioms
    for result in all_macro_results:
        macro = result.macro
        line_start = macro.line_start if macro else None
        line_end = macro.line_end if macro else None
        signature = f"#define {macro.to_signature()}" if macro else f"#define {result.macro_name}"

        for axiom in result.axioms:
            item = ReviewItem(
                axiom=axiom,
                line_start=line_start,
                line_end=line_end,
                signature=signature,
            )
            all_items.append(item)

    # Create review session
    source_label = str(source_path) if source_path.is_file() else f"{source_path}/"
    session = manager.create_session(items=all_items, source_file=source_label)
    session_id = session.session_id

    print(f"\nReview session created: {session_id}")
    print(f"\nTo review axioms:")
    print(f"  python scripts/ingest_library.py --review {session_id}")
    print(f"\nTo export approved axioms:")
    print(f"  python scripts/ingest_library.py --export {session_id} -o approved.toml")

    # Ask if user wants to review now
    try:
        response = input("\nStart review now? [Y/n]: ").strip().lower()
        if response in ("", "y", "yes"):
            run_review(manager, session_id)
    except (EOFError, KeyboardInterrupt):
        print("\n\nReview skipped. Use --review to continue later.")


if __name__ == "__main__":
    main()
