# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Load axioms from axiom-extract JSON output.

The axiom-extract C++ tool outputs JSON with extracted axioms.
This module converts that JSON to AxiomCollection format.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from axiom.models import Axiom, AxiomCollection, AxiomType, SourceLocation

if TYPE_CHECKING:
    from typing import Any


# Mapping from JSON axiom types to AxiomType enum
AXIOM_TYPE_MAP: dict[str, AxiomType] = {
    "PRECONDITION": AxiomType.PRECONDITION,
    "POSTCONDITION": AxiomType.POSTCONDITION,
    "INVARIANT": AxiomType.INVARIANT,
    "EXCEPTION": AxiomType.EXCEPTION,
    "EFFECT": AxiomType.EFFECT,
    "CONSTRAINT": AxiomType.CONSTRAINT,
    "ANTI_PATTERN": AxiomType.ANTI_PATTERN,
    "COMPLEXITY": AxiomType.COMPLEXITY,
}


def load_from_json(json_path: Path | str) -> AxiomCollection:
    """Load axioms from axiom-extract JSON output file.

    Args:
        json_path: Path to JSON file from axiom-extract

    Returns:
        AxiomCollection with extracted axioms
    """
    json_path = Path(json_path)
    with open(json_path) as f:
        data = json.load(f)

    return parse_json(data, source=str(json_path))


def load_from_string(json_str: str, source: str = "axiom-extract") -> AxiomCollection:
    """Load axioms from axiom-extract JSON string.

    Args:
        json_str: JSON string from axiom-extract stdout
        source: Source identifier for the collection

    Returns:
        AxiomCollection with extracted axioms
    """
    data = json.loads(json_str)
    return parse_json(data, source=source)


def parse_json(data: dict[str, Any], source: str = "axiom-extract") -> AxiomCollection:
    """Parse axiom-extract JSON output to AxiomCollection.

    Args:
        data: Parsed JSON dict from axiom-extract
        source: Source identifier for the collection

    Returns:
        AxiomCollection with extracted axioms
    """
    axioms = []

    for axiom_data in data.get("axioms", []):
        axiom = _parse_axiom(axiom_data)
        axioms.append(axiom)

    # Extract metadata
    extracted_at = data.get("extracted_at")
    created = None
    if extracted_at:
        try:
            created = datetime.fromisoformat(extracted_at.replace("Z", "+00:00"))
        except ValueError:
            created = datetime.now(timezone.utc)

    # Build source files list
    source_files = data.get("source_files", [])
    source_str = ", ".join(source_files[:3])
    if len(source_files) > 3:
        source_str += f" (+{len(source_files) - 3} more)"

    return AxiomCollection(
        version=data.get("version", "1.0"),
        source=source_str or source,
        extracted_at=created or datetime.now(timezone.utc),
        axioms=axioms,
    )


def _parse_axiom(data: dict[str, Any]) -> Axiom:
    """Parse a single axiom from JSON.

    Args:
        data: Single axiom dict from JSON

    Returns:
        Axiom model instance
    """
    axiom_type_str = data.get("axiom_type", "CONSTRAINT")
    axiom_type = AXIOM_TYPE_MAP.get(axiom_type_str, AxiomType.CONSTRAINT)

    # Map source_type to layer
    source_type = data.get("source_type", "explicit")
    layer = "user_library"  # All clang-extracted axioms are user library level

    # Build SourceLocation from header and line
    header = data.get("header", "")
    line = data.get("line")

    return Axiom(
        id=data["id"],
        content=data["content"],
        formal_spec=data.get("formal_spec") or "",  # Required field
        source=SourceLocation(
            file=header,
            module=header.replace("/", ".").replace(".h", "") if header else "unknown",
            line_start=line,
            line_end=line,
        ),
        layer=layer,
        confidence=data.get("confidence", 1.0),
        function=data.get("function"),
        signature=data.get("signature"),
        header=data.get("header"),
        axiom_type=axiom_type,
        depends_on=[],  # Populated by linking step
    )
