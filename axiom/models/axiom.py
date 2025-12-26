"""Pydantic models for axioms and error codes."""

from datetime import datetime
from enum import Enum
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
