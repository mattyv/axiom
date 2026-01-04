# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Wrapper for axiom-extract C++ binary.

Runs axiom-extract as a subprocess and parses JSON output.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from axiom.config import AxiomConfig
from axiom.extractors.clang_loader import parse_json

if TYPE_CHECKING:
    from axiom.models import AxiomCollection

logger = logging.getLogger(__name__)


class ExtractorError(Exception):
    """Error during axiom extraction."""

    pass


class AxiomExtractor:
    """Wrapper for the axiom-extract C++ tool.

    Runs extraction on single files and returns parsed axioms.
    """

    def __init__(
        self,
        axiom_extract_path: str | Path | None = None,
        compile_commands_path: str | Path | None = None,
        config: AxiomConfig | None = None,
    ) -> None:
        """Initialize extractor.

        Args:
            axiom_extract_path: Path to axiom-extract binary.
                If config is provided, uses config.extract.axiom_extract_path.
                Otherwise defaults to tools/axiom-extract/build/axiom-extract.
            compile_commands_path: Path to compile_commands.json.
                If config is provided, uses config.extract.compile_commands.
                Otherwise defaults to build/compile_commands.json.
            config: Optional AxiomConfig for path resolution and layer overrides.
        """
        # Load config if not provided
        if config is None:
            config = AxiomConfig.load()
        self.config = config

        # Resolve axiom-extract path
        if axiom_extract_path is None:
            axiom_extract_path = config.resolve_path(config.extract.axiom_extract_path)
        self.axiom_extract_path = Path(axiom_extract_path)

        # Resolve compile_commands.json path
        if compile_commands_path is None:
            compile_commands_path = config.resolve_path(config.extract.compile_commands)
        self.compile_commands_path = Path(compile_commands_path)

        # Cache the set of files in compile_commands.json
        self._compile_commands_files: set[str] | None = None

    def _load_compile_commands_files(self) -> set[str]:
        """Load the set of files from compile_commands.json."""
        if self._compile_commands_files is not None:
            return self._compile_commands_files

        self._compile_commands_files = set()

        if not self.compile_commands_path.exists():
            logger.warning("compile_commands.json not found at %s", self.compile_commands_path)
            return self._compile_commands_files

        try:
            with open(self.compile_commands_path) as f:
                commands = json.load(f)
                for entry in commands:
                    file_path = entry.get("file", "")
                    if file_path:
                        # Normalize to absolute path
                        self._compile_commands_files.add(str(Path(file_path).resolve()))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to parse compile_commands.json: %s", e)

        return self._compile_commands_files

    def is_live_layer_file(self, file_path: str | Path) -> bool:
        """Check if a file belongs to the live layer.

        Layer detection priority:
        1. Static override in config → static layer
        2. Live override in config → live layer
        3. Files in compile_commands.json → live layer
        4. Everything else → static layer

        Args:
            file_path: Path to check.

        Returns:
            True if file is in live layer.
        """
        file_path = Path(file_path).resolve()

        # Check static override first (takes priority)
        if self.config.is_static_override(file_path):
            return False

        # Check live override
        if self.config.is_live_override(file_path):
            return True

        # Check compile_commands.json
        return str(file_path) in self._load_compile_commands_files()

    def extract_file(self, file_path: str | Path) -> AxiomCollection:
        """Extract axioms from a single source file.

        Args:
            file_path: Path to the C/C++ source file.

        Returns:
            AxiomCollection with extracted axioms.

        Raises:
            ExtractorError: If extraction fails.
        """
        file_path = Path(file_path).resolve()

        if not file_path.exists():
            raise ExtractorError(f"Source file not found: {file_path}")

        if not self.axiom_extract_path.exists():
            raise ExtractorError(f"axiom-extract binary not found: {self.axiom_extract_path}")

        # Build command
        cmd = [
            str(self.axiom_extract_path),
            str(file_path),
        ]

        # Add compile_commands.json if it exists
        if self.compile_commands_path.exists():
            cmd.extend(["-p", str(self.compile_commands_path.parent)])

        logger.debug("Running axiom-extract: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,  # 1 minute timeout per file
            )
        except subprocess.TimeoutExpired as e:
            raise ExtractorError(f"axiom-extract timed out for {file_path}") from e
        except OSError as e:
            raise ExtractorError(f"Failed to run axiom-extract: {e}") from e

        if result.returncode != 0:
            # Log stderr but don't fail - axiom-extract may emit warnings
            if result.stderr:
                logger.warning("axiom-extract stderr: %s", result.stderr)

        if not result.stdout.strip():
            # Empty output - no axioms found (valid case)
            from axiom.models import AxiomCollection
            return AxiomCollection(axioms=[], source=str(file_path))

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise ExtractorError(f"Failed to parse axiom-extract output: {e}") from e

        return parse_json(data, source=str(file_path))

    def invalidate_compile_commands_cache(self) -> None:
        """Invalidate the compile_commands.json cache.

        Call this when compile_commands.json changes.
        """
        self._compile_commands_files = None

    def get_all_live_files(self) -> set[str]:
        """Get all files in the live layer.

        Combines files from compile_commands.json with live override paths.

        Returns:
            Set of absolute file paths in the live layer.
        """
        live_files = set(self._load_compile_commands_files())

        # Add files from live override directories
        for pattern in self.config.overrides.live:
            override_path = self.config.root_dir / pattern
            if override_path.is_dir():
                # Find all C/C++ files in the directory
                for ext in (".cpp", ".cc", ".cxx", ".c", ".hpp", ".hh", ".hxx", ".h"):
                    for file_path in override_path.rglob(f"*{ext}"):
                        resolved = str(file_path.resolve())
                        # Skip if in static override
                        if not self.config.is_static_override(file_path):
                            live_files.add(resolved)
            elif override_path.is_file():
                live_files.add(str(override_path.resolve()))

        return live_files
