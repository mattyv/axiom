# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Library ingestion system for axioms from C/C++ source code.

Terminology:
- Extraction: Creating TOML files from source code (axiom/extractors/)
- Ingestion: Loading TOML files into databases (this package)
- Linking: Creating depends_on relationships

This package provides tools to:
1. Parse C/C++ functions using tree-sitter
2. Build operation subgraphs representing function semantics
3. Use LLM + RAG to extract K-semantic axioms
4. Review and approve extracted axioms
5. Ingest approved axioms into the knowledge base (Neo4j + LanceDB)
"""

from .extractor import AxiomExtractor, ExtractionJob, ExtractionResult, extract_axioms
from .kb_integrator import (
    IngestionResult,
    IntegrationResult,  # Deprecated alias
    KBIntegrator,
    ingest_axioms_to_kb,
    load_approved_axioms_to_kb,  # Deprecated alias
)
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
    "ingest_axioms_to_kb",
    "IngestionResult",
    "IntegrationResult",  # Deprecated alias
    "KBIntegrator",
    "load_approved_axioms_to_kb",  # Deprecated alias
    "ReviewDecision",
    "ReviewItem",
    "ReviewSession",
    "ReviewSessionManager",
    "SubgraphBuilder",
    "extract_axioms",
]
