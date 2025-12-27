"""Library ingestion system for extracting axioms from C/C++ source code.

This package provides tools to:
1. Parse C/C++ functions using tree-sitter
2. Build operation subgraphs representing function semantics
3. Use LLM + RAG to extract K-semantic axioms
4. Review and approve extracted axioms
"""

from .extractor import AxiomExtractor, ExtractionJob, ExtractionResult, extract_axioms
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
    "ReviewDecision",
    "ReviewItem",
    "ReviewSession",
    "ReviewSessionManager",
    "SubgraphBuilder",
    "extract_axioms",
]
