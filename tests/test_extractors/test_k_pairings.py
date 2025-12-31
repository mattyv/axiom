# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for K semantics pairing extraction."""

from pathlib import Path

from axiom.extractors.k_semantics import ParsedRule


class TestCellPatternExtraction:
    """Tests for extracting cell access patterns from K rules."""

    def test_detects_cell_write_pattern(self) -> None:
        """Detects .Map => X pattern indicating a write to cell."""
        from axiom.extractors.k_pairings import extract_cell_patterns

        # malloc writes to <malloced>: .Map => obj(...) |-> Sz
        rhs = """
        <malloced>... .Map => obj(!I, Align, alloc) |-> Sz ...</malloced>
        """
        patterns = extract_cell_patterns(rhs)

        assert len(patterns) >= 1
        malloced_pattern = next((p for p in patterns if p[0] == "malloced"), None)
        assert malloced_pattern is not None
        assert malloced_pattern[1] == "write"

    def test_detects_cell_remove_pattern(self) -> None:
        """Detects X => .Map pattern indicating a remove from cell."""
        from axiom.extractors.k_pairings import extract_cell_patterns

        # free removes from <malloced>: Base |-> _ => .Map
        rhs = """
        <malloced>... Base |-> _ => .Map ...</malloced>
        """
        patterns = extract_cell_patterns(rhs)

        assert len(patterns) >= 1
        malloced_pattern = next((p for p in patterns if p[0] == "malloced"), None)
        assert malloced_pattern is not None
        assert malloced_pattern[1] == "remove"

    def test_detects_cell_modify_pattern(self) -> None:
        """Detects X => Y pattern indicating a modification."""
        from axiom.extractors.k_pairings import extract_cell_patterns

        # realloc modifies <malloced>: OldBase => bnew(...)
        rhs = """
        <malloced>...
            (OldBase => bnew(!I, type(no-type), alloc)) |-> (OldLen:Int => NewLen)
        ...</malloced>
        """
        patterns = extract_cell_patterns(rhs)

        assert len(patterns) >= 1
        malloced_pattern = next((p for p in patterns if p[0] == "malloced"), None)
        assert malloced_pattern is not None
        assert malloced_pattern[1] == "modify"

    def test_detects_in_keys_check_pattern(self) -> None:
        """Detects in_keys(Cell) pattern indicating a read/check."""
        from axiom.extractors.k_pairings import extract_cell_patterns

        # Error check reads <malloced>: notBool Base in_keys(Malloced)
        rhs = """
        <malloced> Malloced:Map </malloced>
        requires notBool Base in_keys(Malloced)
        """
        patterns = extract_cell_patterns(rhs)

        # This is a read pattern (checking if key exists)
        assert len(patterns) >= 1

    def test_returns_empty_for_no_cells(self) -> None:
        """Returns empty list when no cell patterns found."""
        from axiom.extractors.k_pairings import extract_cell_patterns

        rhs = "tv(I1:Int, T::UType) / tv(I2:Int, T'::UType)"
        patterns = extract_cell_patterns(rhs)

        assert patterns == []


class TestPairingExtraction:
    """Tests for extracting pairings from K rules."""

    def test_extracts_malloc_free_pairing(self) -> None:
        """malloc and free are paired via shared <malloced> cell."""
        from axiom.extractors.k_pairings import extract_pairings_from_rules

        rules = [
            ParsedRule(
                lhs="alignedAlloc(Align::Int, Sz::Int)",
                rhs="<malloced>... .Map => obj(!I, Align, alloc) |-> Sz ...</malloced>",
                requires=None,
                module="LIBC-STDLIB",
                source_file="stdlib.k",
                error_marker=None,
                attributes=[],
                function="malloc",
            ),
            ParsedRule(
                lhs="builtin(\"free\", tv(loc(Base:SymBase, 0), _))",
                rhs="<malloced>... Base |-> _ => .Map ...</malloced>",
                requires=None,
                module="LIBC-STDLIB",
                source_file="stdlib.k",
                error_marker=None,
                attributes=[],
                function="free",
            ),
        ]

        pairings = extract_pairings_from_rules(rules)

        assert len(pairings) >= 1
        # malloc (writer) should be paired with free (remover)
        malloc_free = next(
            (p for p in pairings if "malloc" in p.opener_id and "free" in p.closer_id),
            None,
        )
        assert malloc_free is not None
        assert malloc_free.cell == "malloced"
        assert malloc_free.source == "k_semantics"
        assert malloc_free.confidence == 1.0

    def test_extracts_realloc_as_both_opener_and_closer(self) -> None:
        """realloc modifies <malloced>, acting as both opener and closer."""
        from axiom.extractors.k_pairings import extract_pairings_from_rules

        rules = [
            ParsedRule(
                lhs="alignedAlloc(Align::Int, Sz::Int)",
                rhs="<malloced>... .Map => obj(!I, Align, alloc) |-> Sz ...</malloced>",
                requires=None,
                module="LIBC-STDLIB",
                source_file="stdlib.k",
                error_marker=None,
                attributes=[],
                function="malloc",
            ),
            ParsedRule(
                lhs="builtin(\"realloc\", ...)",
                rhs="<malloced>... (OldBase => bnew(!I, type(no-type), alloc)) |-> (OldLen => NewLen) ...</malloced>",
                requires=None,
                module="LIBC-STDLIB",
                source_file="stdlib.k",
                error_marker=None,
                attributes=[],
                function="realloc",
            ),
            ParsedRule(
                lhs="builtin(\"free\", tv(loc(Base:SymBase, 0), _))",
                rhs="<malloced>... Base |-> _ => .Map ...</malloced>",
                requires=None,
                module="LIBC-STDLIB",
                source_file="stdlib.k",
                error_marker=None,
                attributes=[],
                function="free",
            ),
        ]

        pairings = extract_pairings_from_rules(rules)

        # realloc should be paired with both malloc and free
        realloc_pairings = [p for p in pairings if "realloc" in p.opener_id or "realloc" in p.closer_id]
        assert len(realloc_pairings) >= 1

    def test_ignores_rules_without_cell_access(self) -> None:
        """Rules without cell access don't generate pairings."""
        from axiom.extractors.k_pairings import extract_pairings_from_rules

        rules = [
            ParsedRule(
                lhs="tv(I1:Int, T::UType) / tv(I2:Int, T'::UType)",
                rhs="intArithInterpret(T, I1 /Int I2)",
                requires="isPromoted(T)",
                module="C-COMMON-EXPR-MULTIPLICATIVE",
                source_file="multiplicative.k",
                error_marker=None,
                attributes=[],
                function=None,
            ),
        ]

        pairings = extract_pairings_from_rules(rules)
        assert len(pairings) == 0

    def test_handles_multiple_cells(self) -> None:
        """Functions can access multiple cells, creating multiple pairings."""
        from axiom.extractors.k_pairings import extract_pairings_from_rules

        # Hypothetical rule accessing two cells
        rules = [
            ParsedRule(
                lhs="foo()",
                rhs="""
                <malloced>... .Map => obj(X) |-> 1 ...</malloced>
                <opened>... .Map => fd(Y) |-> stream ...</opened>
                """,
                requires=None,
                module="TEST",
                source_file="test.k",
                error_marker=None,
                attributes=[],
                function="foo",
            ),
            ParsedRule(
                lhs="bar()",
                rhs="""
                <malloced>... obj(X) |-> _ => .Map ...</malloced>
                """,
                requires=None,
                module="TEST",
                source_file="test.k",
                error_marker=None,
                attributes=[],
                function="bar",
            ),
            ParsedRule(
                lhs="baz()",
                rhs="""
                <opened>... fd(Y) |-> _ => .Map ...</opened>
                """,
                requires=None,
                module="TEST",
                source_file="test.k",
                error_marker=None,
                attributes=[],
                function="baz",
            ),
        ]

        pairings = extract_pairings_from_rules(rules)

        # foo writes to both cells, bar removes from malloced, baz removes from opened
        assert len(pairings) >= 2
        cells = {p.cell for p in pairings}
        assert "malloced" in cells
        assert "opened" in cells


class TestNamingHeuristics:
    """Tests for naming-based pairing detection."""

    def test_begin_end_pattern(self) -> None:
        """Functions with begin/end naming are paired."""
        from axiom.extractors.k_pairings import detect_naming_pairings

        functions = ["stream_begin", "stream_end", "stream_write"]
        pairings = detect_naming_pairings(functions)

        assert len(pairings) >= 1
        begin_end = next(
            (p for p in pairings if "stream_begin" in p.opener_id and "stream_end" in p.closer_id),
            None,
        )
        assert begin_end is not None
        assert begin_end.source == "naming_heuristic"
        assert begin_end.confidence < 1.0  # Lower confidence than K semantics

    def test_lock_unlock_pattern(self) -> None:
        """Functions with lock/unlock naming are paired."""
        from axiom.extractors.k_pairings import detect_naming_pairings

        functions = ["mutex_lock", "mutex_unlock", "mutex_trylock"]
        pairings = detect_naming_pairings(functions)

        lock_unlock = next(
            (p for p in pairings if "mutex_lock" in p.opener_id and "mutex_unlock" in p.closer_id),
            None,
        )
        assert lock_unlock is not None

    def test_init_destroy_pattern(self) -> None:
        """Functions with init/destroy naming are paired."""
        from axiom.extractors.k_pairings import detect_naming_pairings

        functions = ["context_init", "context_destroy", "context_update"]
        pairings = detect_naming_pairings(functions)

        init_destroy = next(
            (p for p in pairings if "context_init" in p.opener_id and "context_destroy" in p.closer_id),
            None,
        )
        assert init_destroy is not None

    def test_open_close_pattern(self) -> None:
        """Functions with open/close naming are paired."""
        from axiom.extractors.k_pairings import detect_naming_pairings

        functions = ["file_open", "file_close", "file_read"]
        pairings = detect_naming_pairings(functions)

        open_close = next(
            (p for p in pairings if "file_open" in p.opener_id and "file_close" in p.closer_id),
            None,
        )
        assert open_close is not None

    def test_acquire_release_pattern(self) -> None:
        """Functions with acquire/release naming are paired."""
        from axiom.extractors.k_pairings import detect_naming_pairings

        functions = ["resource_acquire", "resource_release"]
        pairings = detect_naming_pairings(functions)

        acquire_release = next(
            (p for p in pairings if "resource_acquire" in p.opener_id and "resource_release" in p.closer_id),
            None,
        )
        assert acquire_release is not None

    def test_create_destroy_pattern(self) -> None:
        """Functions with create_X/destroy_X naming are paired."""
        from axiom.extractors.k_pairings import detect_naming_pairings

        functions = ["create_buffer", "destroy_buffer", "resize_buffer"]
        pairings = detect_naming_pairings(functions)

        create_destroy = next(
            (p for p in pairings if "create_buffer" in p.opener_id and "destroy_buffer" in p.closer_id),
            None,
        )
        assert create_destroy is not None

    def test_no_false_positives(self) -> None:
        """Don't create pairings for unrelated functions."""
        from axiom.extractors.k_pairings import detect_naming_pairings

        functions = ["printf", "scanf", "strlen", "memcpy"]
        pairings = detect_naming_pairings(functions)

        assert len(pairings) == 0


class TestIntegration:
    """Integration tests with real K semantics files."""

    def test_extract_from_stdlib_k(self, stdlib_k: Path) -> None:
        """Extract pairings from real stdlib.k file."""
        from axiom.extractors.k_pairings import extract_pairings_from_rules
        from axiom.extractors.k_semantics import KSemanticsExtractor

        extractor = KSemanticsExtractor(stdlib_k.parent)
        rules = extractor.parse_file(stdlib_k)

        pairings = extract_pairings_from_rules(rules)

        # Should find malloc/free pairing
        malloc_free = next(
            (p for p in pairings if "malloc" in str(p) and "free" in str(p)),
            None,
        )
        assert malloc_free is not None, f"Should find malloc/free pairing. Found: {pairings}"
