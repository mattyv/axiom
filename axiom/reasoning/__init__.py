# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Reasoning module for axiom validation and proof chains."""

from .validator import AxiomValidator
from .proof_chain import ProofChainGenerator
from .contradiction import ContradictionDetector

__all__ = [
    "AxiomValidator",
    "ProofChainGenerator",
    "ContradictionDetector",
]
