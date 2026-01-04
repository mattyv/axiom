# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for .axiom.toml discovery and loading functionality."""

from pathlib import Path


class TestDiscoverAxiomToml:
    """Tests for discover_axiom_toml function."""

    def test_discovers_axiom_toml_in_same_directory(self, tmp_path: Path):
        """Test discovery of .axiom.toml in the same directory as source."""
        from scripts.extract_clang import discover_axiom_toml

        # Create .axiom.toml in tmp_path
        axiom_file = tmp_path / ".axiom.toml"
        axiom_file.write_text("[metadata]\nlayer = 'test'\n")

        # Create a source file
        source = tmp_path / "source.cpp"
        source.write_text("int main() {}")

        result = discover_axiom_toml(source)

        assert result == axiom_file

    def test_discovers_axiom_toml_in_parent_directory(self, tmp_path: Path):
        """Test discovery of .axiom.toml in parent directory."""
        from scripts.extract_clang import discover_axiom_toml

        # Create project structure: root/.axiom.toml, root/src/source.cpp
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        axiom_file = tmp_path / ".axiom.toml"
        axiom_file.write_text("[metadata]\nlayer = 'test'\n")

        source = src_dir / "source.cpp"
        source.write_text("int main() {}")

        result = discover_axiom_toml(source)

        assert result == axiom_file

    def test_discovers_axiom_toml_in_grandparent_directory(self, tmp_path: Path):
        """Test discovery of .axiom.toml in grandparent directory."""
        from scripts.extract_clang import discover_axiom_toml

        # Create: root/.axiom.toml, root/src/lib/source.cpp
        lib_dir = tmp_path / "src" / "lib"
        lib_dir.mkdir(parents=True)

        axiom_file = tmp_path / ".axiom.toml"
        axiom_file.write_text("[metadata]\nlayer = 'test'\n")

        source = lib_dir / "source.cpp"
        source.write_text("int main() {}")

        result = discover_axiom_toml(source)

        assert result == axiom_file

    def test_returns_none_when_not_found(self, tmp_path: Path):
        """Test that None is returned when no .axiom.toml exists."""
        from scripts.extract_clang import discover_axiom_toml

        # Create source file without any .axiom.toml
        source = tmp_path / "source.cpp"
        source.write_text("int main() {}")

        result = discover_axiom_toml(source)

        assert result is None

    def test_discovers_axiom_toml_from_directory(self, tmp_path: Path):
        """Test discovery when given a directory instead of file."""
        from scripts.extract_clang import discover_axiom_toml

        axiom_file = tmp_path / ".axiom.toml"
        axiom_file.write_text("[metadata]\nlayer = 'test'\n")

        result = discover_axiom_toml(tmp_path)

        assert result == axiom_file

    def test_prefers_closest_axiom_toml(self, tmp_path: Path):
        """Test that the closest .axiom.toml takes precedence."""
        from scripts.extract_clang import discover_axiom_toml

        # Create two .axiom.toml files at different levels
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        root_axiom = tmp_path / ".axiom.toml"
        root_axiom.write_text("[metadata]\nlayer = 'root'\n")

        src_axiom = src_dir / ".axiom.toml"
        src_axiom.write_text("[metadata]\nlayer = 'src'\n")

        source = src_dir / "source.cpp"
        source.write_text("int main() {}")

        result = discover_axiom_toml(source)

        # Should find the one in src/ directory, not root
        assert result == src_axiom


class TestLoadAxiomToml:
    """Tests for loading and parsing .axiom.toml files."""

    def test_loads_pairings_from_axiom_toml(self, tmp_path: Path):
        """Test loading pairings from .axiom.toml format."""
        from scripts.load_pairings import load_pairings_from_toml

        axiom_file = tmp_path / ".axiom.toml"
        axiom_file.write_text('''
[metadata]
layer = "test"
version = "1.0.0"

[[pairing]]
opener = "SetUp"
closer = "TearDown"
required = true
evidence = "Test lifecycle"
''')

        pairings, idioms = load_pairings_from_toml(axiom_file)

        assert len(pairings) == 1
        assert pairings[0].opener_id == "SetUp"
        assert pairings[0].closer_id == "TearDown"
        assert pairings[0].required is True
        assert pairings[0].evidence == "Test lifecycle"

    def test_loads_idioms_from_axiom_toml(self, tmp_path: Path):
        """Test loading idioms from .axiom.toml format."""
        from scripts.load_pairings import load_pairings_from_toml

        axiom_file = tmp_path / ".axiom.toml"
        axiom_file.write_text('''
[metadata]
layer = "test"

[[idiom]]
name = "fixture_pattern"
participants = ["SetUp", "TearDown"]
template = "class Test { void SetUp(); void TearDown(); }"
''')

        pairings, idioms = load_pairings_from_toml(axiom_file)

        assert len(idioms) == 1
        assert idioms[0].name == "fixture_pattern"
        assert idioms[0].participants == ["SetUp", "TearDown"]
        assert "SetUp" in idioms[0].template

    def test_loads_both_pairings_and_idioms(self, tmp_path: Path):
        """Test loading both pairings and idioms from same file."""
        from scripts.load_pairings import load_pairings_from_toml

        axiom_file = tmp_path / ".axiom.toml"
        axiom_file.write_text('''
[metadata]
layer = "test"

[[pairing]]
opener = "A"
closer = "B"
required = true
evidence = "Pair AB"

[[pairing]]
opener = "C"
closer = "D"
required = false
evidence = "Pair CD"

[[idiom]]
name = "pattern1"
participants = ["A", "B"]
template = "A(); B();"

[[idiom]]
name = "pattern2"
participants = ["C", "D"]
template = "C(); D();"
''')

        pairings, idioms = load_pairings_from_toml(axiom_file)

        assert len(pairings) == 2
        assert len(idioms) == 2


class TestMergePairingsWithAxioms:
    """Tests for merging pairings with extracted axioms."""

    def test_merge_pairings_with_axiom_collection(self, tmp_path: Path):
        """Test that pairings can be associated with axiom collections."""
        from axiom.models import Axiom, AxiomCollection, SourceLocation
        from scripts.load_pairings import load_pairings_from_toml

        # Create axiom collection with functions that match pairings
        axioms = [
            Axiom(
                id="gtest.SetUp.lifecycle",
                content="SetUp is called before each test",
                formal_spec="SetUp() invoked before TestBody()",
                source=SourceLocation(file="gtest.h", module="testing"),
                function="SetUp",
                header="gtest.h",
            ),
            Axiom(
                id="gtest.TearDown.lifecycle",
                content="TearDown is called after each test",
                formal_spec="TearDown() invoked after TestBody()",
                source=SourceLocation(file="gtest.h", module="testing"),
                function="TearDown",
                header="gtest.h",
            ),
        ]
        collection = AxiomCollection(axioms=axioms)

        # Create .axiom.toml with matching pairing
        axiom_file = tmp_path / ".axiom.toml"
        axiom_file.write_text('''
[[pairing]]
opener = "SetUp"
closer = "TearDown"
required = true
evidence = "GTest fixture lifecycle"
''')

        pairings, _idioms = load_pairings_from_toml(axiom_file)

        # Verify pairing references match axiom functions
        assert len(pairings) == 1
        pairing = pairings[0]

        # Find matching axioms
        opener_axioms = [a for a in collection.axioms if a.function == pairing.opener_id]
        closer_axioms = [a for a in collection.axioms if a.function == pairing.closer_id]

        assert len(opener_axioms) == 1
        assert len(closer_axioms) == 1
        assert opener_axioms[0].function == "SetUp"
        assert closer_axioms[0].function == "TearDown"
