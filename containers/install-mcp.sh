#!/bin/bash
# Configure Axiom MCP for Claude Code
set -e

MCP_DIR="$HOME/.config/claude-code"
MCP_FILE="$MCP_DIR/mcp.json"

mkdir -p "$MCP_DIR"

# Get path to axiom-mcp
AXIOM_MCP="$HOME/.local/bin/axiom-mcp"
if [ ! -x "$AXIOM_MCP" ]; then
    echo "Error: axiom-mcp not found. Run install.sh first."
    exit 1
fi

# Create or merge mcp.json
if [ -f "$MCP_FILE" ]; then
    cp "$MCP_FILE" "$MCP_FILE.bak"
    if command -v jq &> /dev/null; then
        jq --arg cmd "$AXIOM_MCP" '.mcpServers.axiom = {"command": $cmd}' "$MCP_FILE.bak" > "$MCP_FILE"
        echo "Updated $MCP_FILE (backup at $MCP_FILE.bak)"
    else
        echo "Warning: jq not found. Please manually add to $MCP_FILE:"
        echo '  "axiom": {"command": "'$AXIOM_MCP'"}'
    fi
else
    cat > "$MCP_FILE" << EOF
{
  "mcpServers": {
    "axiom": {
      "command": "$AXIOM_MCP"
    }
  }
}
EOF
    echo "Created $MCP_FILE"
fi

echo ""
echo "Axiom MCP configured for Claude Code!"
echo "Restart Claude Code to activate."
