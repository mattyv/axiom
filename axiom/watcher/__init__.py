# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Live axiom extraction and watching.

This package provides:
- File watching for source changes
- Incremental axiom extraction on save
- In-memory axiom storage for the live layer
"""

from axiom.watcher.extractor import AxiomExtractor, ExtractorError
from axiom.watcher.store import AxiomStore, InMemoryAxiomStore
from axiom.watcher.watcher import AxiomWatcher

__all__ = [
    "AxiomStore",
    "InMemoryAxiomStore",
    "AxiomExtractor",
    "ExtractorError",
    "AxiomWatcher",
]
