# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""LanceDB vector database components.

Note: Requires optional dependency: pip install axiom[full]
"""


def __getattr__(name: str):
    """Lazy import to avoid requiring lancedb/sentence-transformers when not needed."""
    if name == "LanceDBLoader":
        from .loader import LanceDBLoader

        return LanceDBLoader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "LanceDBLoader",
]
