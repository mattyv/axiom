"""Generate proof chains from claims to foundational axioms."""

from dataclasses import dataclass, field
from typing import List, Optional

from axiom.graph import Neo4jLoader
from axiom.vectors import LanceDBLoader


@dataclass
class ProofStep:
    """A single step in a proof chain."""

    axiom_id: str
    content: str
    formal_spec: str
    module: str
    layer: str
    confidence: float
    relationship: str = ""  # How this step relates to the next


@dataclass
class ProofChain:
    """A complete proof chain from claim to foundational axioms."""

    claim: str
    steps: List[ProofStep] = field(default_factory=list)
    grounded: bool = False
    confidence: float = 0.0
    explanation: str = ""

    def add_step(self, step: ProofStep) -> None:
        """Add a step to the proof chain."""
        self.steps.append(step)
        # Update confidence based on chain
        if self.steps:
            self.confidence = min(s.confidence for s in self.steps)

    @property
    def depth(self) -> int:
        """Number of steps in the chain."""
        return len(self.steps)


class ProofChainGenerator:
    """Generate proof chains by traversing the knowledge graph."""

    def __init__(
        self,
        neo4j_loader: Optional[Neo4jLoader] = None,
        lance_loader: Optional[LanceDBLoader] = None,
    ) -> None:
        """Initialize with database connections.

        Args:
            neo4j_loader: Neo4j connection for graph traversal.
            lance_loader: LanceDB connection for semantic search.
        """
        self._neo4j = neo4j_loader
        self._lance = lance_loader

    @property
    def neo4j(self) -> Neo4jLoader:
        """Get or create Neo4j loader."""
        if self._neo4j is None:
            self._neo4j = Neo4jLoader()
        return self._neo4j

    @property
    def lance(self) -> LanceDBLoader:
        """Get or create LanceDB loader."""
        if self._lance is None:
            self._lance = LanceDBLoader()
        return self._lance

    def generate(self, claim: str, max_depth: int = 5) -> ProofChain:
        """Generate a proof chain for a claim.

        Args:
            claim: The claim to prove/validate.
            max_depth: Maximum chain depth.

        Returns:
            ProofChain with steps from claim to axioms.
        """
        chain = ProofChain(claim=claim)

        # Step 1: Find relevant axioms via semantic search
        relevant_axioms = self.lance.search(claim, limit=10)

        if not relevant_axioms:
            chain.explanation = "No relevant axioms found for this claim."
            return chain

        # Step 2: Build proof chain from most relevant axiom
        for axiom in relevant_axioms:
            step = ProofStep(
                axiom_id=axiom["id"],
                content=axiom["content"],
                formal_spec=axiom["formal_spec"],
                module=axiom["module"],
                layer=axiom["layer"],
                confidence=axiom["confidence"],
                relationship="SUPPORTS" if self._claim_matches_axiom(claim, axiom) else "RELATED_TO",
            )
            chain.add_step(step)

            # For now, just add the top result
            # Future: traverse graph for deeper chains
            break

        # Step 3: Determine if claim is grounded
        if chain.steps:
            chain.grounded = chain.steps[0].layer == "c11_core"
            chain.explanation = self._generate_explanation(chain)

        return chain

    def find_supporting_axioms(
        self, claim: str, limit: int = 5
    ) -> List[dict]:
        """Find axioms that support a claim.

        Args:
            claim: The claim to find support for.
            limit: Maximum number of axioms to return.

        Returns:
            List of supporting axiom records.
        """
        return self.lance.search(claim, limit=limit)

    def find_contradicting_axioms(
        self, claim: str, limit: int = 5
    ) -> List[dict]:
        """Find axioms that might contradict a claim.

        This searches for axioms with negation of key terms.

        Args:
            claim: The claim to find contradictions for.
            limit: Maximum number of axioms to return.

        Returns:
            List of potentially contradicting axiom records.
        """
        # Search for negated version of claim
        negated_terms = self._negate_claim(claim)
        contradictions = []

        for term in negated_terms:
            results = self.lance.search(term, limit=limit)
            for r in results:
                if r not in contradictions:
                    contradictions.append(r)

        return contradictions[:limit]

    def _claim_matches_axiom(self, claim: str, axiom: dict) -> bool:
        """Check if a claim matches an axiom's semantics."""
        claim_lower = claim.lower()
        content_lower = axiom["content"].lower()

        # Simple keyword matching for now
        claim_keywords = set(claim_lower.split())
        content_keywords = set(content_lower.split())

        common = claim_keywords & content_keywords
        # Require at least 2 common keywords
        return len(common) >= 2

    def _negate_claim(self, claim: str) -> List[str]:
        """Generate negated versions of a claim for contradiction search."""
        negations = []
        claim_lower = claim.lower()

        # Simple negation patterns
        if "is safe" in claim_lower:
            negations.append(claim_lower.replace("is safe", "is unsafe"))
            negations.append(claim_lower.replace("is safe", "undefined behavior"))
        if "defined" in claim_lower and "undefined" not in claim_lower:
            negations.append(claim_lower.replace("defined", "undefined"))
        if "valid" in claim_lower:
            negations.append(claim_lower.replace("valid", "invalid"))
        if "can" in claim_lower:
            negations.append(claim_lower.replace("can", "cannot"))
        if "will" in claim_lower:
            negations.append(claim_lower.replace("will", "will not"))

        # Add general contradiction terms
        negations.append(f"not {claim}")
        negations.append(f"undefined behavior {claim}")

        return negations

    def _generate_explanation(self, chain: ProofChain) -> str:
        """Generate a human-readable explanation of the proof chain."""
        if not chain.steps:
            return "No proof chain generated."

        step = chain.steps[0]
        if chain.grounded:
            return (
                f"This claim is grounded in C11 formal semantics. "
                f"The axiom '{step.axiom_id}' from module {step.module} states: "
                f"{step.content}"
            )
        else:
            return (
                f"This claim relates to the axiom '{step.axiom_id}' "
                f"(confidence: {step.confidence}): {step.content}"
            )
