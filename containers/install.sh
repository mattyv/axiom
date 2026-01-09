#!/bin/bash
# Axiom Installation Script
set -e

echo "=== Axiom Installation ==="

# Parse arguments
BUILD_LOCAL=false
BRANCH="main"
WORKSPACE_PATHS=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            BUILD_LOCAL=true
            shift
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --workspace)
            WORKSPACE_PATHS="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: ./install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --build              Build container from local source (for development)"
            echo "                       Without this flag, pulls pre-built images from registry"
            echo "  --branch NAME        Use specific branch/tag for compose file and image"
            echo "                       (default: main)"
            echo "  --workspace PATHS    Comma-separated paths to mount in the container"
            echo "                       (default: /Users on macOS, /home on Linux)"
            echo ""
            echo "Examples:"
            echo "  ./install.sh                                  # Pull from main, default mounts"
            echo "  ./install.sh --branch rc/v0.3                 # Pull from rc/v0.3 branch"
            echo "  ./install.sh --build                          # Build from local source"
            echo "  ./install.sh --workspace /projects,/data      # Custom mount paths"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

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

# Determine script directory (for local builds)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Determine host mounts
if [ -n "$WORKSPACE_PATHS" ]; then
    # User specified custom paths
    HOST_HOME_MOUNT=""
    IFS=',' read -ra PATHS <<< "$WORKSPACE_PATHS"
    for path in "${PATHS[@]}"; do
        # Trim whitespace and add mount
        path=$(echo "$path" | xargs)
        if [ -d "$path" ]; then
            if [ -n "$HOST_HOME_MOUNT" ]; then
                HOST_HOME_MOUNT="$HOST_HOME_MOUNT\n      - $path:$path:ro"
            else
                HOST_HOME_MOUNT="$path:$path:ro"
            fi
        else
            echo "Warning: Path does not exist, skipping: $path"
        fi
    done
    if [ -z "$HOST_HOME_MOUNT" ]; then
        echo "Error: No valid workspace paths specified"
        exit 1
    fi
else
    # Default based on OS
    case "$(uname -s)" in
      Darwin)
        HOST_HOME_MOUNT="/Users:/Users:ro"
        ;;
      Linux)
        HOST_HOME_MOUNT="/home:/home:ro"
        ;;
      *)
        echo "Warning: Unknown OS, using /home mount"
        HOST_HOME_MOUNT="/home:/home:ro"
        ;;
    esac
fi

echo "Workspace mounts: $(echo -e "$HOST_HOME_MOUNT" | tr '\n' ' ')"

if [ "$BUILD_LOCAL" = true ]; then
    echo "Building axiom container from local source..."

    # Verify we're in the right place
    if [ ! -f "$SCRIPT_DIR/Containerfile" ]; then
        echo "Error: Containerfile not found in $SCRIPT_DIR"
        echo "Make sure you're running this from the containers/ directory"
        exit 1
    fi

    # Build the container
    podman build -t axiom:latest -f "$SCRIPT_DIR/Containerfile" "$REPO_ROOT"

    # Copy compose file and update image reference for local build
    sed -e 's|ghcr.io/mattyv/axiom:latest|localhost/axiom:latest|g' \
        -e "s|HOST_HOME_MOUNT|$HOST_HOME_MOUNT|g" \
        "$SCRIPT_DIR/podman-compose.yml" > ~/.local/share/axiom/podman-compose.yml

    echo "Built local image: localhost/axiom:latest"
else
    # URL-encode the branch name (replace / with %2F)
    BRANCH_ENCODED="${BRANCH//\//%2F}"

    # Download podman-compose.yml
    echo "Downloading compose file from branch '$BRANCH'..."
    COMPOSE_URL="https://raw.githubusercontent.com/mattyv/axiom/${BRANCH}/containers/podman-compose.yml"
    if ! curl -sSLf "$COMPOSE_URL" -o ~/.local/share/axiom/podman-compose.yml.tmp; then
        echo "Error: Failed to download compose file from $COMPOSE_URL"
        echo "Check that the branch '$BRANCH' exists and contains containers/podman-compose.yml"
        exit 1
    fi

    # Replace host mount placeholder with correct path for this OS
    sed "s|HOST_HOME_MOUNT|$HOST_HOME_MOUNT|g" \
        ~/.local/share/axiom/podman-compose.yml.tmp > ~/.local/share/axiom/podman-compose.yml
    rm -f ~/.local/share/axiom/podman-compose.yml.tmp

    # Determine image tag based on branch
    if [ "$BRANCH" = "main" ]; then
        IMAGE_TAG="latest"
    else
        # For branches like rc/v0.3, use the branch name as tag
        IMAGE_TAG="$BRANCH_ENCODED"
    fi

    # Pull images
    echo "Pulling axiom image (tag: $IMAGE_TAG)..."
    if ! podman pull "ghcr.io/mattyv/axiom:$IMAGE_TAG"; then
        echo "Warning: Could not pull ghcr.io/mattyv/axiom:$IMAGE_TAG"
        echo "Falling back to 'latest' tag..."
        podman pull ghcr.io/mattyv/axiom:latest
        # Update compose file to use latest
        sed -i '' "s|ghcr.io/mattyv/axiom:$IMAGE_TAG|ghcr.io/mattyv/axiom:latest|g" \
            ~/.local/share/axiom/podman-compose.yml 2>/dev/null || true
    fi
fi

# Always pull neo4j
echo "Pulling neo4j image..."
podman pull docker.io/library/neo4j:5.15

# Create wrapper scripts
cat > ~/.local/bin/axiom-mcp << 'EOF'
#!/bin/bash
COMPOSE_FILE="$HOME/.local/share/axiom/podman-compose.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: $COMPOSE_FILE not found. Run install.sh first." >&2
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
exec podman exec -i axiom-app axiom-mcp
EOF

cat > ~/.local/bin/axiom-lsp << 'EOF'
#!/bin/bash
COMPOSE_FILE="$HOME/.local/share/axiom/podman-compose.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: $COMPOSE_FILE not found. Run install.sh first." >&2
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
exec podman exec -i axiom-app axiom-lsp "$@"
EOF

chmod +x ~/.local/bin/axiom-mcp ~/.local/bin/axiom-lsp

# Start the services
echo "Starting axiom services..."
podman-compose -f ~/.local/share/axiom/podman-compose.yml up -d

# Wait for neo4j to be healthy
echo "Waiting for Neo4j to be ready..."
while ! podman exec axiom-neo4j wget --no-verbose --tries=1 --spider localhost:7474 2>/dev/null; do
    sleep 2
done
echo "Neo4j is ready."

# Wait for axiom initialization (model download + axiom ingestion)
echo "Waiting for Axiom to initialize (downloading model, ingesting axioms)..."
echo "This may take 30-60 seconds on first run..."
while ! podman exec axiom-app test -f /home/axiom/data/.initialized 2>/dev/null; do
    # Show progress from container logs
    podman logs --tail 1 axiom-app 2>/dev/null | grep -v "^$" || true
    sleep 3
done
echo "Axiom initialization complete."

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Services are running:"
podman-compose -f ~/.local/share/axiom/podman-compose.yml ps
echo ""
echo "Wrapper scripts installed to ~/.local/bin/"
echo "  - axiom-mcp: MCP server for Claude Code"
echo "  - axiom-lsp: LSP server for VSCode"
echo ""
echo "Next steps (run from this directory):"
echo ""
echo "  1. Claude Code (MCP server):"
echo "     ./install-mcp.sh"
echo ""
echo "  2. Claude Code (auto-inject hooks):"
echo "     ./install-hooks.sh"
echo ""
echo "  3. VSCode (LSP + extension):"
echo "     ./install-vscode.sh"
echo ""
echo "=== Configuration ==="
echo ""
echo "Wrapper scripts: ~/.local/bin/"
echo "  - axiom-mcp: MCP server for Claude Code"
echo "  - axiom-lsp: LSP server for VSCode"
echo ""
echo "Diagnostic modes (set in VSCode settings or hook config):"
echo "  - default: Shows axiom hints at call sites"
echo "  - llm:     Compact format optimized for AI assistants"
echo "  - human:   Detailed format with full axiom context"
echo ""
echo "Settings file locations:"
echo "  VSCode (macOS):  ~/Library/Application Support/Code/User/settings.json"
echo "  VSCode (Linux):  ~/.config/Code/User/settings.json"
echo "  Claude Code:     ~/.config/claude-code/mcp.json"
echo "  Hooks config:    <project>/.claude/config.toml"
