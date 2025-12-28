# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""API request and response models."""

from typing import List, Optional

from pydantic import BaseModel, Field


class ValidateRequest(BaseModel):
    """Request to validate a claim or LLM output."""

    claim: str = Field(..., description="The claim or LLM output to validate")
    context: str = Field(
        default="c11", description="Context for validation (c11, cpp17, etc.)"
    )


class ContradictionResponse(BaseModel):
    """A detected contradiction."""

    axiom_id: str
    axiom_content: str
    formal_spec: str
    contradiction_type: str
    confidence: float
    explanation: str


class ProofStepResponse(BaseModel):
    """A step in a proof chain."""

    axiom_id: str
    content: str
    module: str
    layer: str
    confidence: float


class ProofChainResponse(BaseModel):
    """A proof chain response."""

    claim: str
    steps: List[ProofStepResponse]
    grounded: bool
    confidence: float
    explanation: str


class ValidateResponse(BaseModel):
    """Response from validation endpoint."""

    claim: str
    valid: bool
    confidence: float
    contradictions: List[ContradictionResponse] = Field(default_factory=list)
    proof_chain: Optional[ProofChainResponse] = None
    explanation: str
    warnings: List[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """Request to search for axioms."""

    query: str = Field(..., description="Search query")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum results")


class AxiomResponse(BaseModel):
    """An axiom response."""

    id: str
    content: str
    formal_spec: str
    module: str
    layer: str
    confidence: float
    tags: List[str]


class SearchResponse(BaseModel):
    """Response from search endpoint."""

    query: str
    results: List[AxiomResponse]
    count: int


class StatsResponse(BaseModel):
    """Statistics about the knowledge base."""

    axioms: int
    error_codes: int
    modules: int
    vector_count: int
