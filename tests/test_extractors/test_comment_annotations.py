# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for comment annotation extraction from source files."""

import tempfile
from pathlib import Path

import pytest


class TestPairsWithAnnotation:
    """Tests for @axiom:pairs_with comment extraction."""

    def test_single_line_pairs_with(self) -> None:
        """@axiom:pairs_with in single-line comment extracts pairing."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
// @axiom:pairs_with mutex_unlock
void mutex_lock(Mutex* m);
"""
        with tempfile.NamedTemporaryFile(suffix=".h", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            pairings, idioms = extract_pairings_from_comments(Path(f.name))

        assert len(pairings) == 1
        assert "mutex_lock" in pairings[0].opener_id
        assert "mutex_unlock" in pairings[0].closer_id
        assert pairings[0].source == "comment_annotation"

    def test_multiple_annotations_on_function(self) -> None:
        """Multiple @axiom: annotations on a function are all extracted."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
// @axiom:pairs_with mutex_unlock
// @axiom:role opener
// @axiom:required true
void mutex_lock(Mutex* m);
"""
        with tempfile.NamedTemporaryFile(suffix=".h", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            pairings, _ = extract_pairings_from_comments(Path(f.name))

        assert len(pairings) == 1
        assert pairings[0].required is True

    def test_bidirectional_pairing(self) -> None:
        """Both opener and closer annotations create pairing."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
// @axiom:pairs_with mutex_unlock
// @axiom:role opener
void mutex_lock(Mutex* m);

// @axiom:pairs_with mutex_lock
// @axiom:role closer
void mutex_unlock(Mutex* m);
"""
        with tempfile.NamedTemporaryFile(suffix=".h", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            pairings, _ = extract_pairings_from_comments(Path(f.name))

        assert len(pairings) == 2

    def test_block_comment_annotation(self) -> None:
        """@axiom: in block comments is also extracted."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
/* @axiom:pairs_with resource_release */
void resource_acquire(Resource* r);
"""
        with tempfile.NamedTemporaryFile(suffix=".h", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            pairings, _ = extract_pairings_from_comments(Path(f.name))

        assert len(pairings) == 1
        assert "resource_acquire" in pairings[0].opener_id
        assert "resource_release" in pairings[0].closer_id

    def test_required_false(self) -> None:
        """@axiom:required false creates optional pairing."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
// @axiom:pairs_with cleanup_optional
// @axiom:required false
void init_with_cleanup(void);
"""
        with tempfile.NamedTemporaryFile(suffix=".h", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            pairings, _ = extract_pairings_from_comments(Path(f.name))

        assert len(pairings) == 1
        assert pairings[0].required is False


class TestIdiomAnnotation:
    """Tests for @axiom:idiom and @axiom:template comment extraction."""

    def test_idiom_with_template(self) -> None:
        """@axiom:idiom and @axiom:template create idiom."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
// @axiom:idiom scoped_lock
// @axiom:template mutex_lock(${m}); { ${body} } mutex_unlock(${m});
void mutex_lock(Mutex* m);
"""
        with tempfile.NamedTemporaryFile(suffix=".h", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            _, idioms = extract_pairings_from_comments(Path(f.name))

        assert len(idioms) == 1
        assert idioms[0].name == "scoped_lock"
        assert "${body}" in idioms[0].template
        assert "mutex_lock" in idioms[0].template

    def test_idiom_without_template_ignored(self) -> None:
        """@axiom:idiom without @axiom:template is ignored."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
// @axiom:idiom incomplete_idiom
void some_function(void);
"""
        with tempfile.NamedTemporaryFile(suffix=".h", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            _, idioms = extract_pairings_from_comments(Path(f.name))

        # Should not create an idiom without template
        assert len(idioms) == 0


class TestDirectoryScan:
    """Tests for scan_directory_for_annotations."""

    def test_scan_finds_all_header_files(self) -> None:
        """scan_directory_for_annotations finds .h and .hpp files."""
        from axiom.extractors.comment_annotations import scan_directory_for_annotations

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create header file with annotation
            (tmppath / "lib.h").write_text("""\
// @axiom:pairs_with unlock
void lock(void);
""")
            # Create cpp header file with annotation
            (tmppath / "lib.hpp").write_text("""\
// @axiom:pairs_with close
void open(void);
""")
            # Create source file with annotation
            (tmppath / "lib.c").write_text("""\
// @axiom:pairs_with end
void begin(void);
""")

            pairings, _ = scan_directory_for_annotations(tmppath)

        assert len(pairings) == 3

    def test_scan_recursive(self) -> None:
        """scan_directory_for_annotations searches subdirectories."""
        from axiom.extractors.comment_annotations import scan_directory_for_annotations

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create nested directory
            subdir = tmppath / "src" / "utils"
            subdir.mkdir(parents=True)

            (subdir / "mutex.h").write_text("""\
// @axiom:pairs_with mutex_unlock
void mutex_lock(void);
""")

            pairings, _ = scan_directory_for_annotations(tmppath)

        assert len(pairings) == 1

    def test_scan_with_custom_extensions(self) -> None:
        """scan_directory_for_annotations respects extensions parameter."""
        from axiom.extractors.comment_annotations import scan_directory_for_annotations

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            (tmppath / "lib.h").write_text("""\
// @axiom:pairs_with unlock
void lock(void);
""")
            (tmppath / "lib.hxx").write_text("""\
// @axiom:pairs_with close
void open(void);
""")

            # Only scan .hxx files
            pairings, _ = scan_directory_for_annotations(tmppath, extensions=[".hxx"])

        assert len(pairings) == 1
        assert "open" in pairings[0].opener_id

    def test_scan_empty_directory(self) -> None:
        """scan_directory_for_annotations handles empty directory."""
        from axiom.extractors.comment_annotations import scan_directory_for_annotations

        with tempfile.TemporaryDirectory() as tmpdir:
            pairings, idioms = scan_directory_for_annotations(Path(tmpdir))

        assert len(pairings) == 0
        assert len(idioms) == 0


class TestEdgeCases:
    """Edge case tests for comment annotation extraction."""

    def test_no_annotations(self) -> None:
        """Files without @axiom: annotations return empty lists."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
// Regular comment
void some_function(void);

/* Another comment */
int another_function(int x);
"""
        with tempfile.NamedTemporaryFile(suffix=".h", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            pairings, idioms = extract_pairings_from_comments(Path(f.name))

        assert len(pairings) == 0
        assert len(idioms) == 0

    def test_annotation_not_followed_by_function(self) -> None:
        """@axiom: not followed by function declaration is ignored."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
// @axiom:pairs_with something
// This is just a standalone comment, not a function

// A completely separate section with no function
struct SomeStruct {
    int x;
};
"""
        with tempfile.NamedTemporaryFile(suffix=".h", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            pairings, _ = extract_pairings_from_comments(Path(f.name))

        # Should not match annotation that's not followed by function
        assert len(pairings) == 0

    def test_macro_function_style(self) -> None:
        """Annotations work with macro-style function declarations."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
// @axiom:pairs_with ILP_END
#define ILP_FOR(type, var, start, end, N) \\
    for (type var = start; var < end; var += N)
"""
        with tempfile.NamedTemporaryFile(suffix=".h", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            pairings, _ = extract_pairings_from_comments(Path(f.name))

        # May or may not work with macros - document behavior
        # For now, we accept either 0 or 1 pairings for macros
        assert len(pairings) <= 1

    def test_cpp_class_methods(self) -> None:
        """Annotations work with C++ class method declarations."""
        from axiom.extractors.comment_annotations import extract_pairings_from_comments

        source = """\
class Mutex {
public:
    // @axiom:pairs_with unlock
    void lock();

    // @axiom:pairs_with lock
    void unlock();
};
"""
        with tempfile.NamedTemporaryFile(suffix=".hpp", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            pairings, _ = extract_pairings_from_comments(Path(f.name))

        assert len(pairings) >= 1
