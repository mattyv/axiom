#!/bin/bash
# Configure Axiom LSP for VSCode (container-based)
set -e

CONTAINER_NAME="${AXIOM_CONTAINER_NAME:-axiom-app}"
WRAPPER_PATH="$HOME/.local/bin/axiom-lsp"

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

# Check if container runtime is available
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
elif command -v docker &> /dev/null; then
    CONTAINER_CMD="docker"
else
    echo "Error: Neither podman nor docker found. Please install one."
    exit 1
fi

# Check if axiom container is running
if ! $CONTAINER_CMD ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Warning: Container '$CONTAINER_NAME' is not running."
    echo "Start it with: $CONTAINER_CMD start $CONTAINER_NAME"
    echo "Or run the full stack with docker-compose/podman-compose"
fi

# Create wrapper script
mkdir -p "$(dirname "$WRAPPER_PATH")"
cat > "$WRAPPER_PATH" << EOF
#!/bin/bash
# Wrapper to run axiom-lsp from container
exec $CONTAINER_CMD exec -i $CONTAINER_NAME axiom-lsp "\$@"
EOF
chmod +x "$WRAPPER_PATH"
echo "Created wrapper script at $WRAPPER_PATH"

# Update VSCode settings
mkdir -p "$SETTINGS_DIR"

if [ -f "$SETTINGS_FILE" ]; then
    cp "$SETTINGS_FILE" "$SETTINGS_FILE.bak"
    if command -v jq &> /dev/null; then
        jq --arg cmd "$WRAPPER_PATH" \
           '."axiom.serverPath" = $cmd | ."axiom-lsp.path" = $cmd | ."axiom-lsp.mode" = "llm"' \
           "$SETTINGS_FILE.bak" > "$SETTINGS_FILE"
        echo "Updated $SETTINGS_FILE (backup at $SETTINGS_FILE.bak)"
    else
        echo "Warning: jq not found. Please manually add to $SETTINGS_FILE:"
        echo '  "axiom.serverPath": "'$WRAPPER_PATH'",'
        echo '  "axiom-lsp.path": "'$WRAPPER_PATH'",'
        echo '  "axiom-lsp.mode": "llm"'
    fi
else
    cat > "$SETTINGS_FILE" << EOF
{
  "axiom.serverPath": "$WRAPPER_PATH",
  "axiom-lsp.path": "$WRAPPER_PATH",
  "axiom-lsp.mode": "llm"
}
EOF
    echo "Created $SETTINGS_FILE"
fi

echo ""
echo "Axiom LSP configured for VSCode (container-based)!"
echo "Make sure the '$CONTAINER_NAME' container is running, then restart VSCode."
