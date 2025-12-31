# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Dataclasses for function pairings and usage idioms.

Pairings represent functions that must be used together (e.g., malloc/free,
lock/unlock). Idioms represent common usage patterns showing correct composition.
"""

from dataclasses import dataclass, field


@dataclass
class Pairing:
    """A pairing between two functions that must be used together.

    Examples:
        - malloc/free (K semantics cell sharing)
        - lock/unlock (naming heuristic)
        - resource_acquire/resource_release (comment annotation)

    Attributes:
        opener_id: Axiom ID of the function that "opens" the resource/state.
        closer_id: Axiom ID of the function that "closes" the resource/state.
        required: Whether the pairing is mandatory (vs. optional cleanup).
        source: How this pairing was detected (k_semantics, comment_annotation,
            naming_heuristic, spec, toml_manifest).
        confidence: Confidence level (0.0-1.0). K semantics = 1.0, naming = 0.7.
        cell: For K semantics pairings, the shared configuration cell name.
        evidence: Human-readable evidence for why this pairing exists.
    """

    opener_id: str
    closer_id: str
    required: bool
    source: str
    confidence: float
    cell: str | None = None
    evidence: str = ""


@dataclass
class Idiom:
    """A usage idiom showing how multiple functions compose correctly.

    Idioms are templates that show correct usage patterns. They help LLMs
    generate code that follows established patterns.

    Example:
        name: "scoped_lock"
        template: "mutex_lock(${m}); { ${body} } mutex_unlock(${m});"

    Attributes:
        id: Unique identifier for this idiom.
        name: Human-readable name for the idiom.
        participants: List of axiom IDs that participate in this idiom.
        template: Usage template with ${placeholders} for variable parts.
        source: How this idiom was defined (comment_annotation, toml_manifest).
    """

    id: str
    name: str
    participants: list[str] = field(default_factory=list)
    template: str = ""
    source: str = ""
