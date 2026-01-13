#!/bin/bash
# Configure Axiom MCP for Claude Code
set -e

# Get path to axiom-mcp
AXIOM_MCP="$HOME/.local/bin/axiom-mcp"
if [ ! -x "$AXIOM_MCP" ]; then
    echo "Error: axiom-mcp not found. Run install.sh first."
    exit 1
fi

# Check if claude CLI is available
if ! command -v claude &> /dev/null; then
    echo "Error: claude CLI not found."
    echo "Install Claude Code from https://claude.ai/code"
    exit 1
fi

# Remove existing axiom server if present (to allow re-running)
claude mcp remove axiom 2>/dev/null || true

# Add axiom MCP server at user scope
echo "Adding axiom MCP server..."
claude mcp add -s user axiom "$AXIOM_MCP"

echo ""
echo "Axiom MCP configured for Claude Code!"
echo "Run 'claude' or restart VSCode Claude extension to use."
echo ""
echo "Verify with: claude mcp list"
