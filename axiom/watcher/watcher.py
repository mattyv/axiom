# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""File system watcher for live axiom extraction.

Watches source files for changes and triggers incremental extraction on save.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable

try:
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object  # type: ignore
    Observer = None  # type: ignore

from axiom.watcher.extractor import AxiomExtractor, ExtractorError
from axiom.watcher.store import AxiomStore, InMemoryAxiomStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# File extensions to watch
CPP_EXTENSIONS = {".cpp", ".cc", ".cxx", ".c", ".hpp", ".hh", ".hxx", ".h"}


class AxiomFileHandler(FileSystemEventHandler):
    """Handle file system events for axiom extraction."""

    def __init__(
        self,
        store: AxiomStore,
        extractor: AxiomExtractor,
        on_update: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize handler.

        Args:
            store: Axiom store to update.
            extractor: Extractor to use for extraction.
            on_update: Optional callback when axioms are updated (receives file path).
        """
        super().__init__()
        self.store = store
        self.extractor = extractor
        self.on_update = on_update
        self._lock = threading.Lock()

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Handle file modification event."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Only process C/C++ files
        if file_path.suffix.lower() not in CPP_EXTENSIONS:
            return

        # Only process files in the live layer (in compile_commands.json)
        if not self.extractor.is_live_layer_file(file_path):
            return

        self._extract_and_update(file_path)

    def _extract_and_update(self, file_path: Path) -> None:
        """Extract axioms from file and update store."""
        with self._lock:
            logger.info("Extracting axioms from %s", file_path)

            try:
                # Clear old axioms from this file
                self.store.delete_by_file(str(file_path))

                # Extract new axioms
                collection = self.extractor.extract_file(file_path)

                # Store new axioms
                if collection.axioms:
                    self.store.upsert(collection.axioms)
                    logger.info("Extracted %d axioms from %s", len(collection.axioms), file_path)
                else:
                    logger.debug("No axioms found in %s", file_path)

                # Notify callback
                if self.on_update:
                    self.on_update(str(file_path))

            except ExtractorError as e:
                logger.error("Extraction failed for %s: %s", file_path, e)


class AxiomWatcher:
    """Watch directories for source file changes and extract axioms.

    This is the main entry point for the live layer extraction system.
    """

    def __init__(
        self,
        watch_paths: list[str | Path] | None = None,
        store: AxiomStore | None = None,
        extractor: AxiomExtractor | None = None,
        on_update: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize watcher.

        Args:
            watch_paths: Directories to watch. Defaults to current directory.
            store: Axiom store. Defaults to InMemoryAxiomStore.
            extractor: Extractor to use. Defaults to AxiomExtractor with defaults.
            on_update: Optional callback when axioms are updated.
        """
        if not WATCHDOG_AVAILABLE:
            raise ImportError(
                "watchdog is required for file watching. "
                "Install with: pip install watchdog"
            )

        if watch_paths is None:
            watch_paths = [Path.cwd()]

        self.watch_paths = [Path(p).resolve() for p in watch_paths]
        self.store = store or InMemoryAxiomStore()
        self.extractor = extractor or AxiomExtractor()
        self.on_update = on_update

        self._observer: Observer | None = None
        self._handler: AxiomFileHandler | None = None

    def start(self) -> None:
        """Start watching for file changes."""
        if self._observer is not None:
            logger.warning("Watcher already started")
            return

        self._handler = AxiomFileHandler(
            store=self.store,
            extractor=self.extractor,
            on_update=self.on_update,
        )

        self._observer = Observer()

        for path in self.watch_paths:
            if path.exists():
                self._observer.schedule(self._handler, str(path), recursive=True)
                logger.info("Watching %s for changes", path)
            else:
                logger.warning("Watch path does not exist: %s", path)

        self._observer.start()
        logger.info("Axiom watcher started")

    def stop(self) -> None:
        """Stop watching for file changes."""
        if self._observer is None:
            return

        self._observer.stop()
        self._observer.join(timeout=5)
        self._observer = None
        self._handler = None
        logger.info("Axiom watcher stopped")

    def extract_all(self) -> int:
        """Extract axioms from all files in live layer.

        Includes files from compile_commands.json and live override paths.

        Returns:
            Number of axioms extracted.
        """
        total_axioms = 0
        live_files = self.extractor.get_all_live_files()

        for file_path in live_files:
            path = Path(file_path)
            if path.suffix.lower() in CPP_EXTENSIONS and path.exists():
                try:
                    collection = self.extractor.extract_file(path)
                    if collection.axioms:
                        self.store.upsert(collection.axioms)
                        total_axioms += len(collection.axioms)
                except ExtractorError as e:
                    logger.error("Failed to extract %s: %s", path, e)

        logger.info("Initial extraction complete: %d axioms from %d files",
                    total_axioms, len(live_files))
        return total_axioms

    def __enter__(self) -> AxiomWatcher:
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.stop()


def main() -> None:
    """Entry point for axiom-watcher command."""
    import argparse
    import signal
    import sys

    parser = argparse.ArgumentParser(description="Axiom file watcher for live extraction")
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Directories to watch (default: current directory)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--no-initial",
        action="store_true",
        help="Skip initial extraction of all files",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create watcher
    watcher = AxiomWatcher(watch_paths=args.paths)

    # Handle shutdown
    def shutdown(signum: int, frame: object) -> None:
        logger.info("Shutting down...")
        watcher.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Initial extraction
    if not args.no_initial:
        logger.info("Performing initial extraction...")
        count = watcher.extract_all()
        logger.info("Extracted %d axioms", count)

    # Start watching
    watcher.start()
    logger.info("Watching for changes. Press Ctrl+C to stop.")

    # Keep running
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()


if __name__ == "__main__":
    main()
