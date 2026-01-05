#!/bin/bash
# Install dependencies for Axiom Claude Code hooks
#
# This script ensures the axiom package is available for the hooks.
# Run this once after cloning the repository.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Installing Axiom hook dependencies..."

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not found"
    exit 1
fi

# Check if we're in a virtual environment or if axiom is installed
if python3 -c "import axiom" 2>/dev/null; then
    echo "✓ axiom package is available"
else
    echo "Installing axiom package in development mode..."

    # Check for venv
    if [ -d "$PROJECT_DIR/.venv" ]; then
        echo "  Using existing virtual environment"
        source "$PROJECT_DIR/.venv/bin/activate"
    fi

    # Install in development mode
    pip install -e "$PROJECT_DIR" --quiet

    if python3 -c "import axiom" 2>/dev/null; then
        echo "✓ axiom package installed successfully"
    else
        echo "Error: Failed to install axiom package"
        exit 1
    fi
fi

# Check for Neo4j connection (required for axiom lookup)
echo "Checking Neo4j connection..."
if python3 -c "
from axiom.graph import Neo4jLoader
try:
    neo4j = Neo4jLoader()
    neo4j.driver.verify_connectivity()
    print('✓ Neo4j connection successful')
except Exception as e:
    print(f'⚠ Neo4j not available: {e}')
    print('  Hooks will work but axiom lookup will be limited')
" 2>/dev/null; then
    :
else
    echo "⚠ Could not verify Neo4j - hooks may have limited functionality"
fi

# Make hook script executable
chmod +x "$SCRIPT_DIR/inject_axioms.py"

echo ""
echo "Hook installation complete!"
echo ""
echo "To enable hooks, add this to .claude/settings.local.json:"
echo '  "hooks": {'
echo '    "UserPromptSubmit": [{'
echo '      "hooks": [{'
echo '        "type": "command",'
echo '        "command": "python3 \"$PROJECT_DIR/.claude/hooks/inject_axioms.py\""'
echo '      }]'
echo '    }]'
echo '  }'
