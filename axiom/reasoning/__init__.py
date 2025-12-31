# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Reasoning module for axiom validation and proof chains."""

__all__ = [
    "AxiomValidator",
    "ProofChainGenerator",
    "ContradictionDetector",
]


def __getattr__(name: str):
    """Lazy import to avoid loading optional dependencies at module import time."""
    if name == "ContradictionDetector":
        from .contradiction import ContradictionDetector

        return ContradictionDetector
    if name == "ProofChainGenerator":
        from .proof_chain import ProofChainGenerator

        return ProofChainGenerator
    if name == "AxiomValidator":
        from .validator import AxiomValidator

        return AxiomValidator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
