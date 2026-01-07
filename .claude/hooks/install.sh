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

# Check for LanceDB (used for semantic search)
echo "Checking LanceDB..."
if python3 -c "
from axiom.vectors import LanceDBLoader
try:
    lance = LanceDBLoader()
    count = lance.count()
    if count > 0:
        print(f'✓ LanceDB loaded with {count} axioms for semantic search')
    else:
        print('⚠ LanceDB is empty - run ingestion to enable semantic search')
except Exception as e:
    print(f'⚠ LanceDB not available: {e}')
    print('  Hooks will fall back to tag-based lookup')
" 2>/dev/null; then
    :
else
    echo "⚠ Could not verify LanceDB - semantic search may be unavailable"
fi

# Make hook script executable
chmod +x "$SCRIPT_DIR/inject_axioms.py"

# Configure hooks in settings.local.json
SETTINGS_FILE="$PROJECT_DIR/.claude/settings.local.json"

echo "Configuring Claude Code hooks..."

"$PROJECT_DIR/.venv/bin/python" -c "
import json
from pathlib import Path

settings_file = Path('$SETTINGS_FILE')

hooks_config = {
    'PostToolUse': [
        {
            'matcher': 'Write|Edit',
            'hooks': [
                {
                    'type': 'command',
                    'command': '.venv/bin/python .claude/hooks/inject_axioms.py'
                }
            ]
        }
    ]
}

# Load existing settings or create new
if settings_file.exists():
    with open(settings_file) as f:
        settings = json.load(f)
else:
    settings = {}

# Merge hooks (don't overwrite existing hooks)
if 'hooks' not in settings:
    settings['hooks'] = {}

for hook_type, hook_list in hooks_config.items():
    if hook_type not in settings['hooks']:
        settings['hooks'][hook_type] = hook_list
        print(f'  ✓ Added {hook_type} hook')
    else:
        print(f'  ⚠ {hook_type} hook already configured, skipping')

# Write back
with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print('✓ Hooks configured in .claude/settings.local.json')
"

echo ""
echo "Hook installation complete!"
echo ""
echo "Restart Claude Code for hooks to take effect."
