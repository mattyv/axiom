#!/usr/bin/env bash
# Install Axiom MCP server for Claude Code / Claude Desktop

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Installing Axiom MCP server..."
echo "Project directory: $PROJECT_DIR"

# Detect config file location
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS - Claude Desktop
    CONFIG_DIR="$HOME/Library/Application Support/Claude"
    CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"
elif [[ -f "$HOME/.config/claude-code/settings.json" ]]; then
    # Linux - Claude Code
    CONFIG_DIR="$HOME/.config/claude-code"
    CONFIG_FILE="$CONFIG_DIR/settings.json"
else
    # Default to Claude Code config
    CONFIG_DIR="$HOME/.config/claude-code"
    CONFIG_FILE="$CONFIG_DIR/settings.json"
fi

echo "Config file: $CONFIG_FILE"

# Create config directory if needed
mkdir -p "$CONFIG_DIR"

# Check if Python venv exists
if [[ ! -d "$PROJECT_DIR/.venv" ]]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$PROJECT_DIR/.venv"
fi

# Install axiom package
echo "Installing axiom package..."
"$PROJECT_DIR/.venv/bin/pip" install -e "$PROJECT_DIR" --quiet

# Generate MCP server config
MCP_COMMAND="$PROJECT_DIR/.venv/bin/python"
MCP_ARGS="-m axiom.mcp.server"

# Create or update config file
if [[ -f "$CONFIG_FILE" ]]; then
    echo "Updating existing config..."
    # Use Python to safely update JSON
    python3 << EOF
import json
import sys

config_file = "$CONFIG_FILE"

try:
    with open(config_file, 'r') as f:
        config = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    config = {}

if 'mcpServers' not in config:
    config['mcpServers'] = {}

config['mcpServers']['axiom'] = {
    'command': '$MCP_COMMAND',
    'args': ['$MCP_ARGS'],
    'env': {
        'PYTHONPATH': '$PROJECT_DIR'
    }
}

with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)

print(f"Updated {config_file}")
EOF
else
    echo "Creating new config..."
    cat > "$CONFIG_FILE" << EOF
{
  "mcpServers": {
    "axiom": {
      "command": "$MCP_COMMAND",
      "args": ["$MCP_ARGS"],
      "env": {
        "PYTHONPATH": "$PROJECT_DIR"
      }
    }
  }
}
EOF
    echo "Created $CONFIG_FILE"
fi

echo ""
echo "Axiom MCP server installed!"
echo ""
echo "Available tools:"
echo "  - validate_claim: Validate C/C++ claims against formal semantics"
echo "  - search_axioms: Search axioms by semantic similarity"
echo "  - get_axiom: Get a specific axiom by ID"
echo "  - get_stats: Get knowledge base statistics"
echo ""
echo "Restart Claude Code/Desktop to activate the MCP server."
