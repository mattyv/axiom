"""Library ingestion system for extracting axioms from C/C++ source code.

This package provides tools to:
1. Parse C/C++ functions using tree-sitter
2. Build operation subgraphs representing function semantics
3. Use LLM + RAG to extract K-semantic axioms
4. Review and approve extracted axioms
"""

from .subgraph_builder import SubgraphBuilder

__all__ = [
    "SubgraphBuilder",
]
