# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for TOML pairing manifest loading."""

import tempfile
from pathlib import Path

import pytest

# Import from script (add scripts to path for testing)
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


class TestLoadPairingsFromToml:
    """Test loading pairings and idioms from TOML files."""

    def test_load_simple_pairing(self, tmp_path: Path) -> None:
        """Test loading a simple pairing from TOML."""
        toml_content = """
[metadata]
layer = "test"

[[pairing]]
opener = "foo"
closer = "bar"
required = true
evidence = "test evidence"
"""
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(toml_content)

        from load_pairings import load_pairings_from_toml

        pairings, idioms = load_pairings_from_toml(toml_file)

        assert len(pairings) == 1
        assert pairings[0].opener_id == "foo"
        assert pairings[0].closer_id == "bar"
        assert pairings[0].required is True
        assert pairings[0].evidence == "test evidence"
        assert pairings[0].source == "toml_manifest"
        assert pairings[0].confidence == 1.0

    def test_load_multiple_pairings(self, tmp_path: Path) -> None:
        """Test loading multiple pairings from TOML."""
        toml_content = """
[[pairing]]
opener = "std::make_shared"
closer = "std::shared_ptr::~shared_ptr"
required = true
evidence = "Memory: allocation/deallocation"

[[pairing]]
opener = "push_back"
closer = "pop_back"
required = false
evidence = "Container: add/remove from back"
"""
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(toml_content)

        from load_pairings import load_pairings_from_toml

        pairings, idioms = load_pairings_from_toml(toml_file)

        assert len(pairings) == 2
        assert pairings[0].opener_id == "std::make_shared"
        assert pairings[0].required is True
        assert pairings[1].opener_id == "push_back"
        assert pairings[1].required is False

    def test_load_idiom(self, tmp_path: Path) -> None:
        """Test loading an idiom from TOML."""
        toml_content = '''
[[idiom]]
name = "shared_ptr_scope"
participants = ["std::make_shared", "std::shared_ptr::~shared_ptr"]
template = """
auto ptr = std::make_shared<T>(args...);
// use ptr
// destructor called automatically
"""
'''
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(toml_content)

        from load_pairings import load_pairings_from_toml

        pairings, idioms = load_pairings_from_toml(toml_file)

        assert len(idioms) == 1
        assert idioms[0].name == "shared_ptr_scope"
        assert idioms[0].id == "idiom_shared_ptr_scope"
        assert len(idioms[0].participants) == 2
        assert "std::make_shared" in idioms[0].participants
        assert "destructor called automatically" in idioms[0].template
        assert idioms[0].source == "toml_manifest"

    def test_load_mixed_content(self, tmp_path: Path) -> None:
        """Test loading both pairings and idioms from same file."""
        toml_content = '''
[metadata]
layer = "cpp20_stdlib"

[[pairing]]
opener = "cv::wait"
closer = "cv::notify_one"
required = false
evidence = "Sync: wait/notify"

[[idiom]]
name = "condition_wait"
participants = ["cv::wait", "cv::notify_one"]
template = "cv.wait(lock, pred); cv.notify_one();"
'''
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(toml_content)

        from load_pairings import load_pairings_from_toml

        pairings, idioms = load_pairings_from_toml(toml_file)

        assert len(pairings) == 1
        assert len(idioms) == 1
        assert pairings[0].opener_id == "cv::wait"
        assert idioms[0].name == "condition_wait"

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """Test loading from empty TOML file."""
        toml_content = "[metadata]\nlayer = 'empty'"
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(toml_content)

        from load_pairings import load_pairings_from_toml

        pairings, idioms = load_pairings_from_toml(toml_file)

        assert len(pairings) == 0
        assert len(idioms) == 0

    def test_default_required_value(self, tmp_path: Path) -> None:
        """Test that required defaults to True if not specified."""
        toml_content = """
[[pairing]]
opener = "foo"
closer = "bar"
"""
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(toml_content)

        from load_pairings import load_pairings_from_toml

        pairings, idioms = load_pairings_from_toml(toml_file)

        assert pairings[0].required is True


class TestCpp20StdlibToml:
    """Test that the cpp20_stdlib.toml file loads correctly."""

    def test_load_cpp20_stdlib_toml(self) -> None:
        """Test loading the actual cpp20_stdlib.toml file."""
        toml_path = Path(__file__).parent.parent.parent / "knowledge" / "pairings" / "cpp20_stdlib.toml"

        if not toml_path.exists():
            pytest.skip("cpp20_stdlib.toml not found")

        from load_pairings import load_pairings_from_toml

        pairings, idioms = load_pairings_from_toml(toml_path)

        # Should have pairings
        assert len(pairings) > 0

        # Check some expected pairings exist
        pairing_pairs = [(p.opener_id, p.closer_id) for p in pairings]

        # RAII pairs
        assert any("std::make_shared" in o for o, c in pairing_pairs)

        # Container pairs
        assert any("push_back" in o and "pop_back" in c for o, c in pairing_pairs)

        # Should have idioms
        assert len(idioms) > 0
        idiom_names = [i.name for i in idioms]
        assert "shared_ptr_scope" in idiom_names
