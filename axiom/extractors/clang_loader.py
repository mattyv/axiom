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
from datetime import UTC, datetime
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
    collection, _ = parse_json_with_call_graph(data, source)
    return collection


def parse_json_with_call_graph(
    data: dict[str, Any], source: str = "axiom-extract"
) -> tuple[AxiomCollection, list[dict[str, Any]]]:
    """Parse axiom-extract JSON output to AxiomCollection with call graph.

    Args:
        data: Parsed JSON dict from axiom-extract
        source: Source identifier for the collection

    Returns:
        Tuple of (AxiomCollection, call_graph list)
    """
    axioms = []
    seen_ids: set[str] = set()

    # Handle both flat "axioms" array and nested "files[].axioms[]" format
    if "axioms" in data:
        # Flat format
        for axiom_data in data.get("axioms", []):
            axiom = _parse_axiom(axiom_data)
            if axiom.id not in seen_ids:
                axioms.append(axiom)
                seen_ids.add(axiom.id)
    elif "files" in data:
        # Nested format from axiom-extract recursive mode
        for file_data in data.get("files", []):
            for axiom_data in file_data.get("axioms", []):
                axiom = _parse_axiom(axiom_data)
                # Deduplicate: same header may be processed from multiple TUs
                if axiom.id not in seen_ids:
                    axioms.append(axiom)
                    seen_ids.add(axiom.id)

    # Extract call graph
    call_graph: list[dict[str, Any]] = data.get("call_graph", [])

    # Extract metadata
    extracted_at = data.get("extracted_at")
    created = None
    if extracted_at:
        try:
            created = datetime.fromisoformat(extracted_at.replace("Z", "+00:00"))
        except ValueError:
            created = datetime.now(UTC)

    # Build source files list
    source_files = data.get("source_files", [])
    # Handle nested format: extract source files from "files" array
    if not source_files and "files" in data:
        source_files = [f.get("source_file", "") for f in data.get("files", []) if f.get("source_file")]
    source_str = ", ".join(source_files[:3])
    if len(source_files) > 3:
        source_str += f" (+{len(source_files) - 3} more)"

    collection = AxiomCollection(
        version=data.get("version", "1.0"),
        source=source_str or source,
        extracted_at=created or datetime.now(UTC),
        axioms=axioms,
    )

    return collection, call_graph


def _parse_axiom(data: dict[str, Any]) -> Axiom:
    """Parse a single axiom from JSON.

    Args:
        data: Single axiom dict from JSON

    Returns:
        Axiom model instance
    """
    axiom_type_str = data.get("axiom_type", "CONSTRAINT")
    axiom_type = AXIOM_TYPE_MAP.get(axiom_type_str, AxiomType.CONSTRAINT)

    # All clang-extracted axioms are user library level
    layer = "user_library"

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
