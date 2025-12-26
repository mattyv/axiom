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
