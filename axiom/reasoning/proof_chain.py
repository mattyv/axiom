# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Generate proof chains from claims to foundational axioms."""

from dataclasses import dataclass, field

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
    steps: list[ProofStep] = field(default_factory=list)
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
        neo4j_loader: Neo4jLoader | None = None,
        lance_loader: LanceDBLoader | None = None,
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

        # Step 2: Build proof chain from relevant axioms
        # Add top 3 matching axioms for stronger evidence
        added = 0
        for axiom in relevant_axioms:
            if not self._claim_matches_axiom(claim, axiom):
                continue

            step = ProofStep(
                axiom_id=axiom["id"],
                content=axiom["content"],
                formal_spec=axiom["formal_spec"],
                module=axiom["module"],
                layer=axiom["layer"],
                confidence=axiom["confidence"],
                relationship="SUPPORTS",
            )
            chain.add_step(step)
            added += 1

            if added >= 3:  # Limit to top 3 supporting axioms
                break

        # If no strong matches, add top result as RELATED_TO
        if added == 0 and relevant_axioms:
            axiom = relevant_axioms[0]
            step = ProofStep(
                axiom_id=axiom["id"],
                content=axiom["content"],
                formal_spec=axiom["formal_spec"],
                module=axiom["module"],
                layer=axiom["layer"],
                confidence=axiom["confidence"],
                relationship="RELATED_TO",
            )
            chain.add_step(step)

        # Step 3: Determine if claim is grounded
        # All formal semantic layers are considered "grounded"
        grounded_layers = {
            "c11_core", "c11_stdlib",
            "cpp_core", "cpp_stdlib",
            "cpp20_language", "cpp20_stdlib",
        }
        if chain.steps:
            first_step = chain.steps[0]
            if first_step.layer in grounded_layers:
                # Directly grounded
                chain.grounded = True
            else:
                # Check if there's a depends_on path to a grounded layer
                graph_chain = self.neo4j.get_proof_chain(first_step.axiom_id)
                if graph_chain:
                    # Add foundation axioms to the proof chain
                    for node in graph_chain[1:]:  # Skip first (already added)
                        if node.get("layer") in grounded_layers:
                            step = ProofStep(
                                axiom_id=node["id"],
                                content=node.get("content", ""),
                                formal_spec=node.get("formal_spec", ""),
                                module=node.get("module_name", ""),
                                layer=node["layer"],
                                confidence=node.get("confidence", 1.0),
                                relationship="DEPENDS_ON",
                            )
                            chain.add_step(step)
                            chain.grounded = True
                            break
            chain.explanation = self._generate_explanation(chain)

        return chain

    def find_supporting_axioms(
        self, claim: str, limit: int = 5
    ) -> list[dict]:
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
    ) -> list[dict]:
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
        """Check if a claim matches an axiom's semantics.

        Uses vector similarity distance from LanceDB search results.
        Falls back to keyword matching if distance not available.
        """
        # Prefer vector similarity if available (from LanceDB search)
        distance = axiom.get("_distance")
        if distance is not None:
            # LanceDB L2 distance: lower = more similar
            # Convert to similarity: 1 / (1 + distance)
            similarity = 1 / (1 + distance)
            return similarity >= 0.4  # Threshold for semantic match

        # Fallback to keyword matching
        claim_lower = claim.lower()
        content_lower = axiom["content"].lower()

        claim_keywords = set(claim_lower.split())
        content_keywords = set(content_lower.split())

        common = claim_keywords & content_keywords
        return len(common) >= 2

    def _negate_claim(self, claim: str) -> list[str]:
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
                f"This claim is grounded in formal semantics ({step.layer}). "
                f"The axiom '{step.axiom_id}' from module {step.module} states: "
                f"{step.content}"
            )
        else:
            return (
                f"This claim relates to the axiom '{step.axiom_id}' "
                f"(confidence: {step.confidence}): {step.content}"
            )
