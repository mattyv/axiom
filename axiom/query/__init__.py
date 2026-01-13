# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Query service for axiom lookups.

This package provides:
- Unified query interface for static + live layers
- Unix socket server for clangd plugin communication
"""

from axiom.query.server import AxiomQueryServer, run_server
from axiom.query.service import AxiomQueryService, AxiomResult, SymbolAxioms

__all__ = [
    "AxiomQueryService",
    "AxiomQueryServer",
    "AxiomResult",
    "SymbolAxioms",
    "run_server",
]
