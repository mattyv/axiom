#!/bin/bash
# Configure Axiom LSP for VSCode
set -e

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

# Get path to axiom-lsp
AXIOM_LSP="$HOME/.local/bin/axiom-lsp"
if [ ! -x "$AXIOM_LSP" ]; then
    echo "Error: axiom-lsp not found. Run install.sh first."
    exit 1
fi

mkdir -p "$SETTINGS_DIR"

if [ -f "$SETTINGS_FILE" ]; then
    cp "$SETTINGS_FILE" "$SETTINGS_FILE.bak"
    if command -v jq &> /dev/null; then
        jq --arg cmd "$AXIOM_LSP" '."axiom.serverPath" = $cmd' "$SETTINGS_FILE.bak" > "$SETTINGS_FILE"
        echo "Updated $SETTINGS_FILE (backup at $SETTINGS_FILE.bak)"
    else
        echo "Warning: jq not found. Please manually add to $SETTINGS_FILE:"
        echo '  "axiom.serverPath": "'$AXIOM_LSP'"'
    fi
else
    cat > "$SETTINGS_FILE" << EOF
{
  "axiom.serverPath": "$AXIOM_LSP"
}
EOF
    echo "Created $SETTINGS_FILE"
fi

echo ""
echo "Axiom LSP configured for VSCode!"
echo "Install the Axiom extension from marketplace, then restart VSCode."
