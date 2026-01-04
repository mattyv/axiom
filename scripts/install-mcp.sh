#!/usr/bin/env bash
# Install Axiom MCP server for Claude Code / Claude Desktop

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Installing Axiom MCP server..."
echo "Project directory: $PROJECT_DIR"

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

# Function to update a config file
update_config() {
    local config_file="$1"

    if [[ -f "$config_file" ]]; then
        echo "Updating: $config_file"
        python3 << EOF
import json

config_file = "$config_file"

try:
    with open(config_file, 'r') as f:
        config = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    config = {}

if 'mcpServers' not in config:
    config['mcpServers'] = {}

config['mcpServers']['axiom'] = {
    'command': '$MCP_COMMAND',
    'args': ['-m', 'axiom.mcp.server'],
    'env': {
        'PYTHONPATH': '$PROJECT_DIR'
    }
}

with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)
EOF
    else
        echo "Creating: $config_file"
        cat > "$config_file" << EOF
{
  "mcpServers": {
    "axiom": {
      "command": "$MCP_COMMAND",
      "args": ["-m", "axiom.mcp.server"],
      "env": {
        "PYTHONPATH": "$PROJECT_DIR"
      }
    }
  }
}
EOF
    fi
}

# Always update .mcp.json in project root (for Claude Code)
update_config "$PROJECT_DIR/.mcp.json"

# Also update Claude Desktop config on macOS if the directory exists
if [[ "$OSTYPE" == "darwin"* ]] && [[ -d "$HOME/Library/Application Support/Claude" ]]; then
    mkdir -p "$HOME/Library/Application Support/Claude"
    update_config "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
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
