#!/bin/bash
# Configure Axiom LSP for VSCode
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
WRAPPER_PATH="$HOME/.local/bin/axiom-lsp"
EXTENSION_DIR="$REPO_ROOT/editors/vscode-axiom"

# Detect OS for correct settings path
case "$(uname -s)" in
  Darwin)
    SETTINGS_DIR="$HOME/Library/Application Support/Code/User"
    ;;
  Linux)
    SETTINGS_DIR="$HOME/.config/Code/User"
    ;;
  *)
    echo "Error: Unsupported OS"
    exit 1
    ;;
esac

SETTINGS_FILE="$SETTINGS_DIR/settings.json"

# Check if VSCode CLI is available
if ! command -v code &> /dev/null; then
    echo "Error: 'code' command not found."
    echo "Install VSCode and enable the 'code' command from the command palette."
    exit 1
fi

# Check if wrapper script exists
if [ ! -f "$WRAPPER_PATH" ]; then
    echo "Error: axiom-lsp wrapper not found at $WRAPPER_PATH"
    echo "Run install.sh first to set up the container and wrapper scripts."
    exit 1
fi

# Build and install VSCode extension
echo "Building VSCode extension..."
if [ ! -d "$EXTENSION_DIR" ]; then
    echo "Error: VSCode extension directory not found at $EXTENSION_DIR"
    exit 1
fi

cd "$EXTENSION_DIR"

# Check for npm
if ! command -v npm &> /dev/null; then
    echo "Error: npm not found. Install Node.js first."
    exit 1
fi

# Install dependencies and compile
npm install --silent
npm run compile --silent

# Package the extension
echo "Packaging extension..."
npx --yes @vscode/vsce package --out axiom-lsp.vsix 2>/dev/null

# Install the extension
echo "Installing extension..."
code --install-extension axiom-lsp.vsix --force

# Clean up
rm -f axiom-lsp.vsix

cd - > /dev/null

# Update VSCode settings
echo "Updating VSCode settings..."
mkdir -p "$SETTINGS_DIR"

if [ -f "$SETTINGS_FILE" ]; then
    cp "$SETTINGS_FILE" "$SETTINGS_FILE.bak"
    if command -v jq &> /dev/null; then
        jq --arg path "$WRAPPER_PATH" \
           '."axiom-lsp.path" = $path | ."axiom-lsp.mode" = "llm"' \
           "$SETTINGS_FILE.bak" > "$SETTINGS_FILE"
        echo "Updated $SETTINGS_FILE (backup at $SETTINGS_FILE.bak)"
    else
        echo "Warning: jq not found. Please manually add to $SETTINGS_FILE:"
        echo "  \"axiom-lsp.path\": \"$WRAPPER_PATH\","
        echo "  \"axiom-lsp.mode\": \"llm\""
    fi
else
    cat > "$SETTINGS_FILE" << EOF
{
  "axiom-lsp.path": "$WRAPPER_PATH",
  "axiom-lsp.mode": "llm"
}
EOF
    echo "Created $SETTINGS_FILE"
fi

echo ""
echo "=== VSCode Setup Complete ==="
echo ""
echo "Axiom LSP extension installed and configured!"
echo "Restart VSCode to activate the extension."
echo ""
echo "Configuration:"
echo "  Extension: Axiom LSP"
echo "  LSP path:  $WRAPPER_PATH"
echo "  Mode:      llm"
echo ""
echo "Available modes (change in settings.json):"
echo "  - default: Shows axiom hints at call sites"
echo "  - llm:     Compact format optimized for AI assistants"
echo "  - human:   Detailed format with full axiom context"
