# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Neo4j graph database components.

Note: Requires optional dependency: pip install axiom[full]
"""


def __getattr__(name: str):
    """Lazy import to avoid requiring neo4j when not needed."""
    if name == "Neo4jLoader":
        from .loader import Neo4jLoader

        return Neo4jLoader
    if name in ("SCHEMA_CONSTRAINTS", "apply_schema", "clear_graph"):
        from . import schema

        return getattr(schema, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Neo4jLoader",
    "SCHEMA_CONSTRAINTS",
    "apply_schema",
    "clear_graph",
]
