# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Library ingestion system for extracting axioms from C/C++ source code.

This package provides tools to:
1. Parse C/C++ functions using tree-sitter
2. Build operation subgraphs representing function semantics
3. Use LLM + RAG to extract K-semantic axioms
4. Review and approve extracted axioms
5. Integrate approved axioms into the knowledge base
"""

from .extractor import AxiomExtractor, ExtractionJob, ExtractionResult, extract_axioms
from .kb_integrator import IntegrationResult, KBIntegrator, load_approved_axioms_to_kb
from .reviewer import (
    ReviewDecision,
    ReviewItem,
    ReviewSession,
    ReviewSessionManager,
)
from .subgraph_builder import SubgraphBuilder

__all__ = [
    "AxiomExtractor",
    "ExtractionJob",
    "ExtractionResult",
    "IntegrationResult",
    "KBIntegrator",
    "ReviewDecision",
    "ReviewItem",
    "ReviewSession",
    "ReviewSessionManager",
    "SubgraphBuilder",
    "extract_axioms",
    "load_approved_axioms_to_kb",
]
