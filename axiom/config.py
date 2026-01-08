# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Configuration loader for Axiom LSP.

Reads .axiom/config.toml from workspace root.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


import shutil


def _find_axiom_extract() -> str:
    """Find axiom-extract binary, checking multiple locations."""
    # Check environment variable first
    if env_path := os.environ.get("AXIOM_EXTRACT_PATH"):
        return env_path
    # Check for axiom-extract-clang in PATH (container install)
    if clang_path := shutil.which("axiom-extract-clang"):
        return clang_path
    # Default to local build path
    return "tools/axiom-extract/build/axiom-extract"


@dataclass
class ExtractConfig:
    """Extraction configuration."""

    compile_commands: str = "build/compile_commands.json"
    axiom_extract_path: str = field(default_factory=_find_axiom_extract)


@dataclass
class LiveConfig:
    """Live layer configuration."""

    storage: str = "memory"
    sqlite_path: str = ".axiom/live.db"


@dataclass
class StaticConfig:
    """Static layer configuration."""

    neo4j_uri: str = field(
        default_factory=lambda: os.environ.get("AXIOM_NEO4J_URI", "bolt://localhost:7687")
    )
    neo4j_user: str = field(
        default_factory=lambda: os.environ.get("AXIOM_NEO4J_USER", "neo4j")
    )
    neo4j_password: str = field(
        default_factory=lambda: os.environ.get("AXIOM_NEO4J_PASSWORD", "axiompass")
    )
    lancedb_path: str = field(
        default_factory=lambda: os.environ.get("AXIOM_LANCEDB_PATH", "data/lancedb")
    )


@dataclass
class DiagnosticsConfig:
    """Diagnostics configuration."""

    mode: str = "default"  # "default", "llm", "human"


@dataclass
class HoverConfig:
    """Hover configuration."""

    max_depth: int | None = None
    show_full_chain: bool = True


@dataclass
class OverridesConfig:
    """Path override configuration."""

    static: list[str] = field(default_factory=list)
    live: list[str] = field(default_factory=list)


@dataclass
class AxiomConfig:
    """Full Axiom configuration."""

    extract: ExtractConfig = field(default_factory=ExtractConfig)
    live: LiveConfig = field(default_factory=LiveConfig)
    static: StaticConfig = field(default_factory=StaticConfig)
    diagnostics: DiagnosticsConfig = field(default_factory=DiagnosticsConfig)
    hover: HoverConfig = field(default_factory=HoverConfig)
    overrides: OverridesConfig = field(default_factory=OverridesConfig)

    # Root directory where config was found
    root_dir: Path = field(default_factory=Path.cwd)

    @classmethod
    def load(cls, workspace_root: Path | None = None) -> AxiomConfig:
        """Load configuration from .axiom/config.toml.

        Args:
            workspace_root: Workspace root directory. If not specified,
                checks AXIOM_PROJECT_DIR or CLAUDE_PROJECT_DIR env vars,
                then falls back to cwd.

        Returns:
            AxiomConfig with loaded or default values.
        """
        if workspace_root is None:
            # Check environment variables first
            env_root = os.environ.get("AXIOM_PROJECT_DIR") or os.environ.get("CLAUDE_PROJECT_DIR")
            if env_root:
                workspace_root = Path(env_root)
            else:
                workspace_root = Path.cwd()

        config_path = workspace_root / ".axiom" / "config.toml"

        if not config_path.exists():
            return cls(root_dir=workspace_root)

        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return cls(root_dir=workspace_root)

        return cls._from_dict(data, workspace_root)

    @classmethod
    def _from_dict(cls, data: dict[str, Any], root_dir: Path) -> AxiomConfig:
        """Create config from parsed TOML dict."""
        extract_data = data.get("extract", {})
        live_data = data.get("live", {})
        static_data = data.get("static", {})
        diag_data = data.get("diagnostics", {})
        hover_data = data.get("hover", {})
        overrides_data = data.get("overrides", {})

        return cls(
            extract=ExtractConfig(
                compile_commands=extract_data.get("compile_commands", "build/compile_commands.json"),
                axiom_extract_path=extract_data.get("axiom_extract_path", "tools/axiom-extract/build/axiom-extract"),
            ),
            live=LiveConfig(
                storage=live_data.get("storage", "memory"),
                sqlite_path=live_data.get("sqlite_path", ".axiom/live.db"),
            ),
            static=StaticConfig(
                neo4j_uri=os.environ.get("AXIOM_NEO4J_URI") or static_data.get("neo4j_uri", "bolt://localhost:7687"),
                neo4j_user=os.environ.get("AXIOM_NEO4J_USER") or static_data.get("neo4j_user", "neo4j"),
                neo4j_password=os.environ.get("AXIOM_NEO4J_PASSWORD") or static_data.get("neo4j_password", "axiompass"),
                lancedb_path=os.environ.get("AXIOM_LANCEDB_PATH") or static_data.get("lancedb_path", "data/lancedb"),
            ),
            diagnostics=DiagnosticsConfig(
                mode=diag_data.get("mode", "default"),
            ),
            hover=HoverConfig(
                max_depth=hover_data.get("max_depth"),
                show_full_chain=hover_data.get("show_full_chain", True),
            ),
            overrides=OverridesConfig(
                static=overrides_data.get("static", []),
                live=overrides_data.get("live", []),
            ),
            root_dir=root_dir,
        )

    def resolve_path(self, path: str) -> Path:
        """Resolve a config path relative to workspace root."""
        p = Path(path)
        if p.is_absolute():
            return p
        return self.root_dir / p

    def is_live_override(self, file_path: Path) -> bool:
        """Check if file is in live override list."""
        file_str = str(file_path)
        for pattern in self.overrides.live:
            if file_str.startswith(str(self.root_dir / pattern)):
                return True
        return False

    def is_static_override(self, file_path: Path) -> bool:
        """Check if file is in static override list."""
        file_str = str(file_path)
        for pattern in self.overrides.static:
            if file_str.startswith(str(self.root_dir / pattern)):
                return True
        return False
