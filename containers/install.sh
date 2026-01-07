#!/bin/bash
# Axiom Installation Script
set -e

echo "=== Axiom Installation ==="

# Check for podman
if ! command -v podman &> /dev/null; then
    echo "Error: podman not found. Install from https://podman.io"
    exit 1
fi

# Check for podman-compose
if ! command -v podman-compose &> /dev/null; then
    echo "Error: podman-compose not found. Install with: pip install podman-compose"
    exit 1
fi

# Create directories
mkdir -p ~/.local/bin
mkdir -p ~/.local/share/axiom

# Download podman-compose.yml
echo "Downloading compose file..."
curl -sSL https://raw.githubusercontent.com/mattyv/axiom/main/containers/podman-compose.yml \
  -o ~/.local/share/axiom/podman-compose.yml

# Pull images
echo "Pulling axiom images..."
podman pull ghcr.io/mattyv/axiom:latest
podman pull docker.io/library/neo4j:5.15

# Create wrapper scripts
cat > ~/.local/bin/axiom-mcp << 'EOF'
#!/bin/bash
COMPOSE_FILE="$HOME/.local/share/axiom/podman-compose.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: $COMPOSE_FILE not found. Run axiom-install first." >&2
    exit 1
fi

# Start services if not running
podman-compose -f "$COMPOSE_FILE" up -d 2>/dev/null

# Wait for initialization on first run
while ! podman exec axiom-app test -f /home/axiom/data/.initialized 2>/dev/null; do
  echo "Waiting for axiom to initialize..." >&2
  sleep 2
done

# Run MCP server
podman exec -i axiom-app python -m axiom.mcp.server
EOF

cat > ~/.local/bin/axiom-lsp << 'EOF'
#!/bin/bash
COMPOSE_FILE="$HOME/.local/share/axiom/podman-compose.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: $COMPOSE_FILE not found. Run axiom-install first." >&2
    exit 1
fi

# Start services if not running
podman-compose -f "$COMPOSE_FILE" up -d 2>/dev/null

# Wait for initialization on first run
while ! podman exec axiom-app test -f /home/axiom/data/.initialized 2>/dev/null; do
  echo "Waiting for axiom to initialize..." >&2
  sleep 2
done

# Run LSP server
podman exec -i axiom-app python -m axiom.lsp.server "$@"
EOF

chmod +x ~/.local/bin/axiom-mcp ~/.local/bin/axiom-lsp

echo "Installed wrapper scripts to ~/.local/bin/"
echo ""
echo "Next steps:"
echo "  - For Claude Code: run '~/.local/bin/axiom-install-mcp'"
echo "  - For VSCode:      run '~/.local/bin/axiom-install-vscode'"
echo ""
echo "Note: First run will take ~30s to download model and ingest axioms."
