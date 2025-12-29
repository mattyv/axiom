# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Tests for C signature extraction from header files (TDD - tests first)."""

from pathlib import Path

import pytest


class TestSignatureInfo:
    """Tests for SignatureInfo dataclass."""

    def test_signature_info_fields(self) -> None:
        """SignatureInfo should have name, signature, return_type, parameters, header."""
        from axiom.extractors.c_signatures import SignatureInfo

        sig = SignatureInfo(
            name="malloc",
            signature="void *malloc(size_t size)",
            return_type="void *",
            parameters=[("size_t", "size")],
            header="stdlib.h",
        )
        assert sig.name == "malloc"
        assert sig.signature == "void *malloc(size_t size)"
        assert sig.return_type == "void *"
        assert sig.parameters == [("size_t", "size")]
        assert sig.header == "stdlib.h"


class TestCSignatureExtractor:
    """Tests for CSignatureExtractor."""

    def test_extract_malloc_signature(self, c_semantics_root: Path) -> None:
        """Should extract malloc signature from stdlib.h."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        if not headers_dir.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor.extract_all()

        assert "malloc" in signatures
        sig = signatures["malloc"]
        assert sig.name == "malloc"
        assert "void" in sig.return_type
        assert "size_t" in sig.signature
        assert sig.header == "stdlib.h"

    def test_extract_free_signature(self, c_semantics_root: Path) -> None:
        """Should extract free signature from stdlib.h."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        if not headers_dir.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor.extract_all()

        assert "free" in signatures
        sig = signatures["free"]
        assert sig.name == "free"
        assert "void" in sig.return_type
        assert "pointer" in sig.signature.lower() or "void *" in sig.signature

    def test_extract_strlen_signature(self, c_semantics_root: Path) -> None:
        """Should extract strlen signature from string.h."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        if not headers_dir.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor.extract_all()

        assert "strlen" in signatures
        sig = signatures["strlen"]
        assert sig.name == "strlen"
        assert "size_t" in sig.return_type
        assert "char" in sig.signature
        assert sig.header == "string.h"

    def test_extract_memcpy_signature(self, c_semantics_root: Path) -> None:
        """Should extract memcpy signature from string.h."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        if not headers_dir.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor.extract_all()

        assert "memcpy" in signatures
        sig = signatures["memcpy"]
        assert sig.name == "memcpy"
        assert "void" in sig.return_type
        assert "destination" in sig.signature or "dest" in sig.signature.lower()

    def test_extract_printf_signature(self, c_semantics_root: Path) -> None:
        """Should extract printf signature from stdio.h."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        if not headers_dir.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor.extract_all()

        assert "printf" in signatures
        sig = signatures["printf"]
        assert sig.name == "printf"
        assert "int" in sig.return_type
        assert "format" in sig.signature
        assert sig.header == "stdio.h"

    def test_extract_all_returns_dict(self, c_semantics_root: Path) -> None:
        """extract_all should return dict mapping function name to SignatureInfo."""
        from axiom.extractors.c_signatures import CSignatureExtractor, SignatureInfo

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        if not headers_dir.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor.extract_all()

        assert isinstance(signatures, dict)
        assert len(signatures) > 0
        for name, sig in signatures.items():
            assert isinstance(name, str)
            assert isinstance(sig, SignatureInfo)
            assert sig.name == name

    def test_handles_variadic_functions(self, c_semantics_root: Path) -> None:
        """Should handle variadic functions like printf(format, ...)."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        if not headers_dir.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor.extract_all()

        # printf is variadic
        assert "printf" in signatures
        assert "..." in signatures["printf"].signature


class TestParseHeader:
    """Tests for parsing individual header files."""

    def test_parse_single_header(self, c_semantics_root: Path) -> None:
        """Should parse a single header file."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        stdlib_h = headers_dir / "stdlib.h"
        if not stdlib_h.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor._parse_header(stdlib_h)

        assert len(signatures) > 0
        func_names = [s.name for s in signatures]
        assert "malloc" in func_names
        assert "free" in func_names
        assert "calloc" in func_names
        assert "realloc" in func_names

    def test_parse_header_sets_header_field(self, c_semantics_root: Path) -> None:
        """Parsed signatures should have header field set to filename."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        string_h = headers_dir / "string.h"
        if not string_h.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor._parse_header(string_h)

        for sig in signatures:
            assert sig.header == "string.h"


class TestEdgeCases:
    """Tests for edge cases and special syntax."""

    def test_handles_restrict_keyword(self, c_semantics_root: Path) -> None:
        """Should handle __restrict__ keyword in parameters."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        if not headers_dir.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor.extract_all()

        # strcpy uses __restrict__
        assert "strcpy" in signatures
        # Signature should be valid (may or may not include __restrict__)
        assert "strcpy" in signatures["strcpy"].signature

    def test_handles_noreturn_attribute(self, c_semantics_root: Path) -> None:
        """Should handle _Noreturn attribute on functions like exit."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        if not headers_dir.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor.extract_all()

        # exit has _Noreturn
        assert "exit" in signatures
        sig = signatures["exit"]
        assert sig.name == "exit"
        assert "int" in sig.signature  # exit takes int status

    def test_handles_function_pointers_in_params(self, c_semantics_root: Path) -> None:
        """Should handle function pointer parameters like in atexit."""
        from axiom.extractors.c_signatures import CSignatureExtractor

        headers_dir = c_semantics_root / "profiles/x86-gcc-limited-libc/include/library"
        if not headers_dir.exists():
            pytest.skip("c-semantics headers not available")

        extractor = CSignatureExtractor(headers_dir)
        signatures = extractor.extract_all()

        # atexit takes a function pointer
        assert "atexit" in signatures
        sig = signatures["atexit"]
        assert sig.name == "atexit"
