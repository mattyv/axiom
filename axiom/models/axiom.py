"""Pydantic models for axioms and error codes."""

import tomllib
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


class ErrorType(str, Enum):
    """Types of errors in C semantics."""

    UNDEFINED_BEHAVIOR = "undefined_behavior"
    CONSTRAINT_VIOLATION = "constraint_violation"
    IMPLEMENTATION_DEFINED = "implementation_defined"
    UNSPECIFIED = "unspecified"
    SYNTAX_ERROR = "syntax_error"


class SourceLocation(BaseModel):
    """Location of an axiom in K semantic files."""

    file: str
    module: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None


class ViolationRef(BaseModel):
    """Reference to an error that occurs when an axiom is violated."""

    code: str  # e.g., "CEMX1"
    error_type: str  # UNDEF, CV, IMPL, etc.
    message: str


class Axiom(BaseModel):
    """A foundational truth extracted from K semantics."""

    id: str
    content: str  # Human-readable description
    formal_spec: str  # K requires clause
    source: SourceLocation
    violated_by: List[ViolationRef] = Field(default_factory=list)
    c_standard_refs: List[str] = Field(default_factory=list)
    layer: str = "c11_core"
    confidence: float = 1.0
    tags: List[str] = Field(default_factory=list)


class ErrorCode(BaseModel):
    """An error code from the C semantics error catalog."""

    code: str  # Full code like "UB-CEMX1"
    internal_code: str  # Short code like "CEMX1"
    type: ErrorType
    description: str
    c_standard_refs: List[str] = Field(default_factory=list)
    validates_axioms: List[str] = Field(default_factory=list)


class AxiomCollection(BaseModel):
    """A collection of extracted axioms and error codes."""

    version: str = "1.0"
    source: str = "kframework/c-semantics"
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    axioms: List[Axiom] = Field(default_factory=list)
    error_codes: List[ErrorCode] = Field(default_factory=list)

    def to_toml(self) -> str:
        """Serialize collection to TOML string."""

        def to_literal(s: str) -> str:
            """Convert to TOML literal string (no escape interpretation)."""
            # Use literal strings ''' which don't interpret backslashes
            if "'''" in s:
                # Fall back to basic string with escaping
                escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                return f'"{escaped}"'
            return f"'''{s}'''"

        lines = [
            f'version = "{self.version}"',
            f'source = "{self.source}"',
            f'extracted_at = "{self.extracted_at.isoformat()}"',
            "",
        ]

        for axiom in self.axioms:
            lines.append("[[axioms]]")
            lines.append(f'id = "{axiom.id}"')
            lines.append(f"content = {to_literal(axiom.content)}")
            lines.append(f"formal_spec = {to_literal(axiom.formal_spec)}")
            lines.append(f'layer = "{axiom.layer}"')
            lines.append(f"confidence = {axiom.confidence}")
            lines.append(f'source_file = "{axiom.source.file}"')
            lines.append(f'source_module = "{axiom.source.module}"')
            if axiom.source.line_start:
                lines.append(f"source_line_start = {axiom.source.line_start}")
            if axiom.source.line_end:
                lines.append(f"source_line_end = {axiom.source.line_end}")
            if axiom.tags:
                lines.append(f"tags = {axiom.tags!r}")
            if axiom.c_standard_refs:
                lines.append(f"c_standard_refs = {axiom.c_standard_refs!r}")
            if axiom.violated_by:
                codes = [v.code for v in axiom.violated_by]
                lines.append(f"error_codes = {codes!r}")
            lines.append("")

        for error in self.error_codes:
            lines.append("[[error_codes]]")
            lines.append(f'code = "{error.code}"')
            lines.append(f'internal_code = "{error.internal_code}"')
            lines.append(f'type = "{error.type.value}"')
            lines.append(f"description = {to_literal(error.description)}")
            if error.c_standard_refs:
                lines.append(f"c_standard_refs = {error.c_standard_refs!r}")
            if error.validates_axioms:
                lines.append(f"validates_axioms = {error.validates_axioms!r}")
            lines.append("")

        return "\n".join(lines)

    def save_toml(self, path: Path) -> None:
        """Save collection to TOML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_toml())

    @classmethod
    def load_toml(cls, path: Path) -> "AxiomCollection":
        """Load collection from TOML file."""
        data = tomllib.loads(path.read_text())

        axioms = []
        for a in data.get("axioms", []):
            axioms.append(
                Axiom(
                    id=a["id"],
                    content=a["content"],
                    formal_spec=a["formal_spec"],
                    layer=a.get("layer", "c11_core"),
                    confidence=a.get("confidence", 1.0),
                    source=SourceLocation(
                        file=a["source_file"],
                        module=a["source_module"],
                        line_start=a.get("source_line_start"),
                        line_end=a.get("source_line_end"),
                    ),
                    tags=a.get("tags", []),
                    c_standard_refs=a.get("c_standard_refs", []),
                    violated_by=[
                        ViolationRef(code=c, error_type="UNDEF", message="")
                        for c in a.get("error_codes", [])
                    ],
                )
            )

        error_codes = []
        for e in data.get("error_codes", []):
            error_codes.append(
                ErrorCode(
                    code=e["code"],
                    internal_code=e["internal_code"],
                    type=ErrorType(e["type"]),
                    description=e["description"],
                    c_standard_refs=e.get("c_standard_refs", []),
                    validates_axioms=e.get("validates_axioms", []),
                )
            )

        return cls(
            version=data.get("version", "1.0"),
            source=data.get("source", "unknown"),
            extracted_at=datetime.fromisoformat(data["extracted_at"])
            if "extracted_at" in data
            else datetime.utcnow(),
            axioms=axioms,
            error_codes=error_codes,
        )
