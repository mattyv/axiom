# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""FastAPI application for Axiom validation service."""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from axiom.graph import Neo4jLoader
from axiom.reasoning import AxiomValidator
from axiom.vectors import LanceDBLoader

from .models import (
    AxiomResponse,
    ContradictionResponse,
    ProofChainResponse,
    ProofStepResponse,
    SearchRequest,
    SearchResponse,
    StatsResponse,
    ValidateRequest,
    ValidateResponse,
)


# Global instances
_validator: Optional[AxiomValidator] = None
_neo4j: Optional[Neo4jLoader] = None
_lance: Optional[LanceDBLoader] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global _validator, _neo4j, _lance

    # Initialize on startup
    try:
        _lance = LanceDBLoader()
        print(f"LanceDB connected: {_lance.count()} axioms")
    except Exception as e:
        print(f"Warning: LanceDB not available: {e}")

    try:
        _neo4j = Neo4jLoader()
        counts = _neo4j.count_nodes()
        print(f"Neo4j connected: {counts}")
    except Exception as e:
        print(f"Warning: Neo4j not available: {e}")

    _validator = AxiomValidator()
    print("Validator initialized")

    yield

    # Cleanup on shutdown
    if _neo4j:
        _neo4j.close()


app = FastAPI(
    title="Axiom Validation API",
    description="Validate LLM outputs against formal C/C++ semantics",
    version="0.1.0",
    lifespan=lifespan,
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Axiom Validation API",
        "version": "0.1.0",
        "description": "Validate LLM outputs against formal C/C++ semantics",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/validate", response_model=ValidateResponse)
async def validate(request: ValidateRequest):
    """Validate a claim against formal axioms.

    This endpoint checks if an LLM claim contradicts formal C/C++ semantics.
    """
    if not _validator:
        raise HTTPException(status_code=503, detail="Validator not initialized")

    result = _validator.validate(request.claim)

    # Convert to response model
    contradictions = [
        ContradictionResponse(
            axiom_id=c.axiom_id,
            axiom_content=c.axiom_content,
            formal_spec=c.formal_spec,
            contradiction_type=c.contradiction_type,
            confidence=c.confidence,
            explanation=c.explanation,
        )
        for c in result.contradictions
    ]

    proof_chain = None
    if result.proof_chain and result.proof_chain.steps:
        proof_chain = ProofChainResponse(
            claim=result.proof_chain.claim,
            steps=[
                ProofStepResponse(
                    axiom_id=s.axiom_id,
                    content=s.content,
                    module=s.module,
                    layer=s.layer,
                    confidence=s.confidence,
                )
                for s in result.proof_chain.steps
            ],
            grounded=result.proof_chain.grounded,
            confidence=result.proof_chain.confidence,
            explanation=result.proof_chain.explanation,
        )

    return ValidateResponse(
        claim=result.claim,
        valid=result.is_valid,
        confidence=result.confidence,
        contradictions=contradictions,
        proof_chain=proof_chain,
        explanation=result.explanation,
        warnings=result.warnings,
    )


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """Search for axioms by semantic similarity."""
    if not _lance:
        raise HTTPException(status_code=503, detail="LanceDB not initialized")

    results = _lance.search(request.query, limit=request.limit)

    axioms = [
        AxiomResponse(
            id=r["id"],
            content=r["content"],
            formal_spec=r["formal_spec"],
            module=r["module"],
            layer=r["layer"],
            confidence=r["confidence"],
            tags=r.get("tags", []),
        )
        for r in results
    ]

    return SearchResponse(
        query=request.query,
        results=axioms,
        count=len(axioms),
    )


@app.get("/stats", response_model=StatsResponse)
async def stats():
    """Get knowledge base statistics."""
    neo4j_counts = {"axioms": 0, "error_codes": 0, "modules": 0}
    vector_count = 0

    if _neo4j:
        try:
            neo4j_counts = _neo4j.count_nodes()
        except Exception:
            pass

    if _lance:
        try:
            vector_count = _lance.count()
        except Exception:
            pass

    return StatsResponse(
        axioms=neo4j_counts.get("axioms", 0),
        error_codes=neo4j_counts.get("error_codes", 0),
        modules=neo4j_counts.get("modules", 0),
        vector_count=vector_count,
    )


@app.get("/axiom/{axiom_id}", response_model=AxiomResponse)
async def get_axiom(axiom_id: str):
    """Get a specific axiom by ID."""
    if not _neo4j:
        raise HTTPException(status_code=503, detail="Neo4j not initialized")

    axiom = _neo4j.get_axiom(axiom_id)
    if not axiom:
        raise HTTPException(status_code=404, detail=f"Axiom {axiom_id} not found")

    return AxiomResponse(
        id=axiom["id"],
        content=axiom["content"],
        formal_spec=axiom["formal_spec"],
        module=axiom["module_name"],
        layer=axiom["layer"],
        confidence=axiom["confidence"],
        tags=axiom.get("tags", []),
    )


def run():
    """Run the API server."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
