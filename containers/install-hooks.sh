#!/bin/bash
# Install Claude Code hooks for Axiom (container version)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$SCRIPT_DIR/hooks"

# Check if container is available
if ! command -v podman &> /dev/null; then
    echo "Error: podman not found"
    exit 1
fi

# Check if axiom container exists
if ! podman ps -a --format '{{.Names}}' | grep -q "^axiom-app$"; then
    echo "Error: axiom-app container not found"
    echo "Run install.sh first to set up the container"
    exit 1
fi

echo "Installing Claude Code hooks..."

# Make hook script executable
chmod +x "$HOOKS_DIR/inject_axioms.py"

# Determine project directory (where Claude Code is running)
# This is typically the current working directory when using Claude Code
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Create .claude directory if it doesn't exist
mkdir -p "$PROJECT_DIR/.claude"

# Copy hook files to project
cp "$HOOKS_DIR/inject_axioms.py" "$PROJECT_DIR/.claude/"
cp "$HOOKS_DIR/config.toml" "$PROJECT_DIR/.claude/"
chmod +x "$PROJECT_DIR/.claude/inject_axioms.py"

# Configure hooks in settings.local.json
SETTINGS_FILE="$PROJECT_DIR/.claude/settings.local.json"

echo "Configuring Claude Code hooks..."

python3 -c "
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
                    'command': 'python3 .claude/inject_axioms.py'
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

# Merge hooks
if 'hooks' not in settings:
    settings['hooks'] = {}

for hook_type, hook_list in hooks_config.items():
    if hook_type not in settings['hooks']:
        settings['hooks'][hook_type] = hook_list
        print(f'  Added {hook_type} hook')
    else:
        # Check if axiom hook already exists
        existing = settings['hooks'][hook_type]
        has_axiom = any('inject_axioms' in str(h) for h in existing)
        if not has_axiom:
            settings['hooks'][hook_type].extend(hook_list)
            print(f'  Added axiom to existing {hook_type} hooks')
        else:
            print(f'  {hook_type} axiom hook already configured')

# Write back
with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print('Hooks configured in .claude/settings.local.json')
"

echo ""
echo "=== Hook Installation Complete ==="
echo ""
echo "Hooks installed to: $PROJECT_DIR/.claude/"
echo ""
echo "The hook will automatically inject axiom context when you edit C++ files."
echo "Restart Claude Code for hooks to take effect."
echo ""
echo "Configuration options in .claude/config.toml:"
echo "  mode: edit|selection|comprehensive"
echo "  max_axioms: maximum axioms per file"
echo "  show_formal: include formal specifications"
