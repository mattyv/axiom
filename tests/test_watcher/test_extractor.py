# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Tests for the axiom extractor wrapper."""

import tempfile
from pathlib import Path

import pytest

from axiom.config import AxiomConfig, ExtractConfig, OverridesConfig
from axiom.watcher.extractor import AxiomExtractor


class TestAxiomExtractorLayerDetection:
    """Tests for layer detection logic."""

    def test_live_override_takes_precedence(self, tmp_path: Path) -> None:
        """Files in live override are detected as live layer."""
        # Create config with live override for examples/
        config = AxiomConfig(
            root_dir=tmp_path,
            overrides=OverridesConfig(live=["examples/"]),
        )

        # Create examples directory and a file
        examples_dir = tmp_path / "examples"
        examples_dir.mkdir()
        demo_file = examples_dir / "demo.cpp"
        demo_file.write_text("int main() { return 0; }")

        extractor = AxiomExtractor(config=config)

        # File should be detected as live layer
        assert extractor.is_live_layer_file(demo_file)

    def test_static_override_takes_precedence_over_live(self, tmp_path: Path) -> None:
        """Static override takes precedence over live override."""
        # Create config with both overrides
        config = AxiomConfig(
            root_dir=tmp_path,
            overrides=OverridesConfig(
                live=["examples/"],
                static=["examples/legacy/"],
            ),
        )

        # Create nested directory
        legacy_dir = tmp_path / "examples" / "legacy"
        legacy_dir.mkdir(parents=True)
        legacy_file = legacy_dir / "old.cpp"
        legacy_file.write_text("int main() { return 0; }")

        extractor = AxiomExtractor(config=config)

        # File should NOT be live (static override takes precedence)
        assert not extractor.is_live_layer_file(legacy_file)

    def test_get_all_live_files_includes_overrides(self, tmp_path: Path) -> None:
        """get_all_live_files includes files from live override directories."""
        # Create config with live override
        config = AxiomConfig(
            root_dir=tmp_path,
            overrides=OverridesConfig(live=["examples/"]),
        )

        # Create examples directory with files
        examples_dir = tmp_path / "examples"
        examples_dir.mkdir()
        (examples_dir / "demo.cpp").write_text("int main() {}")
        (examples_dir / "test.h").write_text("#pragma once")
        (examples_dir / "readme.txt").write_text("not a C++ file")

        extractor = AxiomExtractor(config=config)
        live_files = extractor.get_all_live_files()

        # Should include the C++ files but not txt
        file_names = {Path(f).name for f in live_files}
        assert "demo.cpp" in file_names
        assert "test.h" in file_names
        assert "readme.txt" not in file_names

    def test_file_not_in_any_layer_is_static(self, tmp_path: Path) -> None:
        """Files not in compile_commands or overrides are static layer."""
        config = AxiomConfig(root_dir=tmp_path)

        some_file = tmp_path / "random" / "file.cpp"
        some_file.parent.mkdir(parents=True)
        some_file.write_text("int main() {}")

        extractor = AxiomExtractor(config=config)

        # File should NOT be live layer
        assert not extractor.is_live_layer_file(some_file)


class TestAxiomExtractorConfig:
    """Tests for config-based path resolution."""

    def test_uses_config_paths(self, tmp_path: Path) -> None:
        """Extractor uses paths from config."""
        config = AxiomConfig(
            root_dir=tmp_path,
            extract=ExtractConfig(
                compile_commands="my/compile_commands.json",
                axiom_extract_path="my/axiom-extract",
            ),
        )

        extractor = AxiomExtractor(config=config)

        assert extractor.compile_commands_path == tmp_path / "my" / "compile_commands.json"
        assert extractor.axiom_extract_path == tmp_path / "my" / "axiom-extract"

    def test_explicit_paths_override_config(self, tmp_path: Path) -> None:
        """Explicit paths in constructor override config."""
        config = AxiomConfig(
            root_dir=tmp_path,
            extract=ExtractConfig(
                compile_commands="config/compile_commands.json",
                axiom_extract_path="config/axiom-extract",
            ),
        )

        extractor = AxiomExtractor(
            config=config,
            compile_commands_path="/explicit/compile_commands.json",
            axiom_extract_path="/explicit/axiom-extract",
        )

        assert extractor.compile_commands_path == Path("/explicit/compile_commands.json")
        assert extractor.axiom_extract_path == Path("/explicit/axiom-extract")
