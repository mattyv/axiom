# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Extractors for parsing K semantics and error codes."""

from .c_signatures import CSignatureExtractor, SignatureInfo
from .content_generator import ContentGenerator
from .error_codes import ErrorCodesParser
from .k_dependencies import (
    KDependencyExtractor,
    build_function_index,
    extract_function_calls,
    resolve_depends_on,
)
from .k_semantics import KSemanticsExtractor, ParsedRule
from .linker import AxiomLinker
from .prompts import (
    EXTRACTION_PROMPT,
    HIGH_SIGNAL_LIBRARY_SECTIONS,
    HIGH_SIGNAL_SECTIONS,
    SYSTEM_PROMPT,
    generate_dedup_prompt,
    generate_extraction_prompt,
)

__all__ = [
    "AxiomLinker",
    "build_function_index",
    "ContentGenerator",
    "CSignatureExtractor",
    "ErrorCodesParser",
    "extract_function_calls",
    "EXTRACTION_PROMPT",
    "generate_dedup_prompt",
    "generate_extraction_prompt",
    "HIGH_SIGNAL_LIBRARY_SECTIONS",
    "HIGH_SIGNAL_SECTIONS",
    "KDependencyExtractor",
    "KSemanticsExtractor",
    "ParsedRule",
    "resolve_depends_on",
    "SignatureInfo",
    "SYSTEM_PROMPT",
]
