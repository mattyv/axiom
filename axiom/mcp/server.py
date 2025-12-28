# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""MCP server for Axiom validation.

This server exposes axiom validation tools to LLMs via the Model Context Protocol.
"""

from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from axiom.graph import Neo4jLoader
from axiom.reasoning import AxiomValidator
from axiom.vectors import LanceDBLoader

# Global instances (lazy-loaded)
_validator: Optional[AxiomValidator] = None
_neo4j: Optional[Neo4jLoader] = None
_lance: Optional[LanceDBLoader] = None


def _get_validator() -> AxiomValidator:
    """Get or create the validator instance."""
    global _validator
    if _validator is None:
        _validator = AxiomValidator()
    return _validator


def _get_lance() -> Optional[LanceDBLoader]:
    """Get or create the LanceDB instance."""
    global _lance
    if _lance is None:
        try:
            _lance = LanceDBLoader()
        except Exception:
            pass
    return _lance


def _get_neo4j() -> Optional[Neo4jLoader]:
    """Get or create the Neo4j instance."""
    global _neo4j
    if _neo4j is None:
        try:
            _neo4j = Neo4jLoader()
        except Exception:
            pass
    return _neo4j


def create_server() -> Server:
    """Create and configure the MCP server."""
    server = Server("axiom")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available tools."""
        return [
            Tool(
                name="validate_claim",
                description=(
                    "Validate a claim about C/C++ behavior against formal C11 semantics. "
                    "Returns whether the claim is valid, any contradictions found, "
                    "and a proof chain grounding the claim in formal axioms."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "claim": {
                            "type": "string",
                            "description": "The claim to validate (e.g., 'dividing by zero is undefined behavior in C')",
                        }
                    },
                    "required": ["claim"],
                },
            ),
            Tool(
                name="search_axioms",
                description=(
                    "Search for axioms by semantic similarity. "
                    "Use this to find formal rules related to a C/C++ concept."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language query (e.g., 'integer overflow', 'pointer arithmetic')",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default: 5)",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_axiom",
                description="Get a specific axiom by its ID.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "axiom_id": {
                            "type": "string",
                            "description": "The axiom ID",
                        }
                    },
                    "required": ["axiom_id"],
                },
            ),
            Tool(
                name="get_stats",
                description="Get statistics about the axiom knowledge base.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="check_duplicates",
                description=(
                    "Check if a proposed axiom is a duplicate of existing axioms. "
                    "Use this BEFORE adding new axioms to avoid duplicates. "
                    "Returns similar existing axioms for comparison."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The human-readable content of the proposed axiom",
                        },
                        "formal_spec": {
                            "type": "string",
                            "description": "The formal specification (optional)",
                        },
                        "threshold": {
                            "type": "number",
                            "description": "Similarity threshold 0-1 (default: 0.7)",
                            "default": 0.7,
                        },
                    },
                    "required": ["content"],
                },
            ),
            Tool(
                name="search_by_section",
                description=(
                    "Find all axioms from a specific spec section. "
                    "Use this to check what axioms already exist for a section before extraction."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "section": {
                            "type": "string",
                            "description": "Section reference (e.g., 'basic.life', '[dcl.init]')",
                        },
                    },
                    "required": ["section"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle tool calls."""
        if name == "validate_claim":
            return await _handle_validate(arguments)
        elif name == "search_axioms":
            return await _handle_search(arguments)
        elif name == "get_axiom":
            return await _handle_get_axiom(arguments)
        elif name == "get_stats":
            return await _handle_stats(arguments)
        elif name == "check_duplicates":
            return await _handle_check_duplicates(arguments)
        elif name == "search_by_section":
            return await _handle_search_by_section(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


async def _handle_validate(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle validate_claim tool."""
    claim = arguments.get("claim", "")
    if not claim:
        return [TextContent(type="text", text="Error: claim is required")]

    validator = _get_validator()
    result = validator.validate(claim)

    # Format response
    lines = [
        f"## Validation Result",
        f"",
        f"**Claim**: {result.claim}",
        f"**Valid**: {result.is_valid}",
        f"**Confidence**: {result.confidence:.2f}",
        f"",
    ]

    if result.contradictions:
        lines.append("### Contradictions Found")
        for c in result.contradictions:
            lines.append(f"- **{c.axiom_id}** ({c.contradiction_type})")
            lines.append(f"  - Axiom: {c.axiom_content}")
            lines.append(f"  - Confidence: {c.confidence:.2f}")
        lines.append("")

    if result.proof_chain and result.proof_chain.steps:
        lines.append("### Proof Chain")
        lines.append(f"Grounded: {result.proof_chain.grounded}")
        for i, step in enumerate(result.proof_chain.steps, 1):
            lines.append(f"{i}. **{step.axiom_id}** [{step.module}]")
            lines.append(f"   {step.content}")
        lines.append("")

    lines.append(f"### Explanation")
    lines.append(result.explanation)

    if result.warnings:
        lines.append("")
        lines.append("### Warnings")
        for w in result.warnings:
            lines.append(f"- {w}")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_search(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle search_axioms tool."""
    query = arguments.get("query", "")
    limit = arguments.get("limit", 5)

    if not query:
        return [TextContent(type="text", text="Error: query is required")]

    lance = _get_lance()
    if not lance:
        return [TextContent(type="text", text="Error: LanceDB not available")]

    results = lance.search(query, limit=limit)

    if not results:
        return [TextContent(type="text", text=f"No axioms found for: {query}")]

    lines = [f"## Axioms matching: {query}", ""]
    for r in results:
        lines.append(f"### {r['id']}")
        lines.append(f"**Module**: {r['module']} | **Layer**: {r['layer']}")
        lines.append(f"**Content**: {r['content']}")
        if r.get("formal_spec"):
            lines.append(f"**Formal**: `{r['formal_spec']}`")
        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_get_axiom(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle get_axiom tool."""
    axiom_id = arguments.get("axiom_id", "")

    if not axiom_id:
        return [TextContent(type="text", text="Error: axiom_id is required")]

    neo4j = _get_neo4j()
    if not neo4j:
        return [TextContent(type="text", text="Error: Neo4j not available")]

    axiom = neo4j.get_axiom(axiom_id)
    if not axiom:
        return [TextContent(type="text", text=f"Axiom not found: {axiom_id}")]

    lines = [
        f"## Axiom: {axiom['id']}",
        "",
        f"**Module**: {axiom.get('module_name', 'unknown')}",
        f"**Layer**: {axiom.get('layer', 'unknown')}",
        f"**Confidence**: {axiom.get('confidence', 0.0):.2f}",
        "",
        f"### Content",
        axiom.get("content", ""),
        "",
    ]

    if axiom.get("formal_spec"):
        lines.append("### Formal Specification")
        lines.append(f"```")
        lines.append(axiom["formal_spec"])
        lines.append("```")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_stats(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle get_stats tool."""
    neo4j_counts = {"axioms": 0, "error_codes": 0, "modules": 0}
    vector_count = 0

    neo4j = _get_neo4j()
    if neo4j:
        try:
            neo4j_counts = neo4j.count_nodes()
        except Exception:
            pass

    lance = _get_lance()
    if lance:
        try:
            vector_count = lance.count()
        except Exception:
            pass

    lines = [
        "## Axiom Knowledge Base Statistics",
        "",
        f"- **Axioms**: {neo4j_counts.get('axioms', 0)}",
        f"- **Error Codes**: {neo4j_counts.get('error_codes', 0)}",
        f"- **Modules**: {neo4j_counts.get('modules', 0)}",
        f"- **Vector Embeddings**: {vector_count}",
    ]

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_check_duplicates(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle check_duplicates tool."""
    content = arguments.get("content", "")
    formal_spec = arguments.get("formal_spec", "")
    threshold = arguments.get("threshold", 0.7)

    if not content:
        return [TextContent(type="text", text="Error: content is required")]

    lance = _get_lance()
    if not lance:
        return [TextContent(type="text", text="Error: LanceDB not available")]

    # Search for similar axioms using the content
    query = content
    if formal_spec:
        query = f"{content} {formal_spec}"

    results = lance.search(query, limit=10)

    if not results:
        return [TextContent(type="text", text="## Duplicate Check: UNIQUE\n\nNo similar axioms found. Safe to add.")]

    # Check similarity scores
    duplicates = []
    similar = []
    for r in results:
        score = r.get("_distance", 1.0)
        # LanceDB returns L2 distance, lower is more similar
        # Convert to similarity: 1 / (1 + distance)
        similarity = 1 / (1 + score) if score is not None else 0

        if similarity >= 0.9:
            duplicates.append((r, similarity))
        elif similarity >= threshold:
            similar.append((r, similarity))

    lines = ["## Duplicate Check Results", ""]

    if duplicates:
        lines.append("### LIKELY DUPLICATES (>90% similar)")
        lines.append("")
        for r, sim in duplicates:
            lines.append(f"- **{r['id']}** (similarity: {sim:.2%})")
            lines.append(f"  Content: {r['content'][:100]}...")
            lines.append("")
        lines.append("**Recommendation**: DO NOT ADD - likely duplicate")
    elif similar:
        lines.append(f"### SIMILAR AXIOMS (>{threshold:.0%} similar)")
        lines.append("")
        for r, sim in similar:
            lines.append(f"- **{r['id']}** (similarity: {sim:.2%})")
            lines.append(f"  Content: {r['content'][:100]}...")
            lines.append("")
        lines.append("**Recommendation**: Review manually before adding")
    else:
        lines.append("### UNIQUE")
        lines.append("")
        lines.append("No similar axioms found above threshold. Safe to add.")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_search_by_section(arguments: dict[str, Any]) -> list[TextContent]:
    """Handle search_by_section tool."""
    section = arguments.get("section", "")

    if not section:
        return [TextContent(type="text", text="Error: section is required")]

    # Clean up section reference
    section = section.strip("[]")

    neo4j = _get_neo4j()
    if not neo4j:
        return [TextContent(type="text", text="Error: Neo4j not available")]

    # Search for axioms with this section in source_file or module
    with neo4j.driver.session() as session:
        result = session.run(
            """
            MATCH (a:Axiom)
            WHERE a.source_file CONTAINS $section
               OR a.module_name CONTAINS $section
               OR a.id CONTAINS $section
            RETURN a
            ORDER BY a.id
            LIMIT 50
            """,
            section=section,
        )
        axioms = [dict(record["a"]) for record in result]

    if not axioms:
        return [TextContent(
            type="text",
            text=f"## Section: {section}\n\nNo axioms found for this section."
        )]

    lines = [f"## Axioms for section: {section}", "", f"Found {len(axioms)} axioms:", ""]
    for a in axioms:
        lines.append(f"### {a['id']}")
        lines.append(f"**Content**: {a.get('content', 'N/A')[:150]}...")
        if a.get("formal_spec"):
            lines.append(f"**Formal**: `{a['formal_spec'][:80]}...`")
        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def run_server() -> None:
    """Run the MCP server."""
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Entry point for the MCP server."""
    import asyncio
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
