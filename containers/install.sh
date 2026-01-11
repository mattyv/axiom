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
            echo "Usage: ./install.sh --workspace PATHS [OPTIONS]"
            echo ""
            echo "Required:"
            echo "  --workspace PATHS    Comma-separated paths to mount in the container"
            echo "                       These directories will be accessible to axiom for analysis"
            echo ""
            echo "Options:"
            echo "  --build              Build container from local source (for development)"
            echo "                       Without this flag, pulls pre-built images from registry"
            echo "  --branch NAME        Use specific branch/tag for compose file and image"
            echo "                       (default: main)"
            echo ""
            echo "Examples:"
            echo "  ./install.sh --workspace /Users/me/projects"
            echo "  ./install.sh --workspace /home/me/code,/opt/projects"
            echo "  ./install.sh --workspace /Users --branch rc/v0.3"
            echo "  ./install.sh --workspace /Users --build"
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

# Check available memory for container runtime
PODMAN_MEM=$(podman info --format '{{.Host.MemTotal}}' 2>/dev/null || echo "0")
# Convert to GB with rounding (add half a GB before dividing)
PODMAN_MEM_GB=$(( (PODMAN_MEM + 536870912) / 1024 / 1024 / 1024 ))

if [ "$PODMAN_MEM_GB" -lt 4 ]; then
    echo ""
    echo "Warning: Container runtime has ${PODMAN_MEM_GB}GB RAM (4GB+ recommended)"
    echo "The embedding model requires ~2GB RAM."

    if [[ "$(uname)" == "Darwin" ]]; then
        echo ""
        echo "To increase podman machine memory:"
        echo "  podman machine stop"
        echo "  podman machine set --memory 4096"
        echo "  podman machine start"
    fi

    echo ""
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "Container runtime memory: ${PODMAN_MEM_GB}GB (OK)"
fi

# Create directories
mkdir -p ~/.local/bin
mkdir -p ~/.local/share/axiom

# Determine script directory (for local builds)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Determine host mounts - build proper YAML volume entries
if [ -z "$WORKSPACE_PATHS" ]; then
    echo "Error: --workspace is required"
    echo "Specify the paths that contain your source code, e.g.:"
    echo "  ./install.sh --workspace /Users/you/projects"
    echo "  ./install.sh --workspace /home/you/code,/opt/projects"
    exit 1
fi

WORKSPACE_MOUNTS=""
IFS=',' read -ra PATHS <<< "$WORKSPACE_PATHS"
for path in "${PATHS[@]}"; do
    # Trim whitespace
    path=$(echo "$path" | xargs)
    # Skip /tmp as it's already mounted as tmpfs in the container
    if [ "$path" = "/tmp" ]; then
        echo "Warning: /tmp is already mounted as tmpfs in container, skipping"
        continue
    fi
    if [ -d "$path" ]; then
        WORKSPACE_MOUNTS="${WORKSPACE_MOUNTS}      - ${path}:${path}:ro
"
    else
        echo "Warning: Path does not exist, skipping: $path"
    fi
done

if [ -z "$WORKSPACE_MOUNTS" ]; then
    echo "Error: No valid workspace paths specified"
    exit 1
fi

# Remove trailing newline for display
MOUNTS_DISPLAY=$(echo "$WORKSPACE_MOUNTS" | sed 's/^      - //g' | tr '\n' ' ')
echo "Workspace mounts: $MOUNTS_DISPLAY"

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
    # Write mounts to temp file, then use sed to replace placeholder
    MOUNTS_FILE=$(mktemp)
    printf '%s' "$WORKSPACE_MOUNTS" > "$MOUNTS_FILE"

    # Replace placeholder with mounts file content, then fix image reference
    sed -e '/# WORKSPACE_MOUNTS_PLACEHOLDER/{
        r '"$MOUNTS_FILE"'
        d
    }' -e 's|ghcr.io/mattyv/axiom:latest|localhost/axiom:latest|g' \
        "$SCRIPT_DIR/podman-compose.yml" > ~/.local/share/axiom/podman-compose.yml

    rm -f "$MOUNTS_FILE"

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

    # Replace placeholder comment with actual mount lines
    MOUNTS_FILE=$(mktemp)
    printf '%s' "$WORKSPACE_MOUNTS" > "$MOUNTS_FILE"

    sed -e '/# WORKSPACE_MOUNTS_PLACEHOLDER/{
        r '"$MOUNTS_FILE"'
        d
    }' ~/.local/share/axiom/podman-compose.yml.tmp > ~/.local/share/axiom/podman-compose.yml

    rm -f "$MOUNTS_FILE" ~/.local/share/axiom/podman-compose.yml.tmp

    # Get the latest commit SHA from the branch
    echo "Fetching latest commit from branch '$BRANCH'..."
    COMMIT_SHA=$(curl -sSL "https://api.github.com/repos/mattyv/axiom/commits/$BRANCH_ENCODED" | grep '"sha"' | head -1 | cut -d'"' -f4)

    if [ -z "$COMMIT_SHA" ]; then
        echo "Warning: Could not fetch commit SHA, trying branch name as tag..."
        IMAGE_TAG="$BRANCH_ENCODED"
    else
        # Detect architecture
        ARCH=$(uname -m)
        case "$ARCH" in
            x86_64|amd64)
                ARCH_SUFFIX="amd64"
                ;;
            arm64|aarch64)
                ARCH_SUFFIX="arm64"
                ;;
            *)
                echo "Warning: Unknown architecture $ARCH, defaulting to amd64"
                ARCH_SUFFIX="amd64"
                ;;
        esac
        IMAGE_TAG="${COMMIT_SHA}-${ARCH_SUFFIX}"
        echo "Using image tag: $IMAGE_TAG"
    fi

    # Pull images
    echo "Pulling axiom image (tag: $IMAGE_TAG)..."
    if ! podman pull "ghcr.io/mattyv/axiom:$IMAGE_TAG"; then
        echo "Warning: Could not pull ghcr.io/mattyv/axiom:$IMAGE_TAG"
        echo "Falling back to 'latest' tag..."
        if ! podman pull ghcr.io/mattyv/axiom:latest; then
            echo "Error: Could not pull any axiom image"
            exit 1
        fi
        IMAGE_TAG="latest"
    fi

    # Update compose file with the actual image tag
    sed -i '' "s|ghcr.io/mattyv/axiom:latest|ghcr.io/mattyv/axiom:$IMAGE_TAG|g" \
        ~/.local/share/axiom/podman-compose.yml 2>/dev/null || \
    sed -i "s|ghcr.io/mattyv/axiom:latest|ghcr.io/mattyv/axiom:$IMAGE_TAG|g" \
        ~/.local/share/axiom/podman-compose.yml 2>/dev/null || true
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

cat > ~/.local/bin/axiom-ingest << 'EOF'
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

# Run ingestion script with container's database paths
exec podman exec axiom-app python -m scripts.ingest \
    --lancedb-path /home/axiom/data/lancedb \
    --neo4j-uri bolt://neo4j:7687 \
    --neo4j-user neo4j \
    --neo4j-password axiompass \
    "$@"
EOF

cat > ~/.local/bin/axiom-workspace << 'EOF'
#!/bin/bash
# Manage workspace mounts for axiom container

COMPOSE_FILE="$HOME/.local/share/axiom/podman-compose.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: $COMPOSE_FILE not found. Run install.sh first." >&2
    exit 1
fi

show_help() {
    echo "Usage: axiom-workspace <command> [path]"
    echo ""
    echo "Commands:"
    echo "  list          Show current workspace mounts"
    echo "  add <path>    Add a new workspace path"
    echo "  remove <path> Remove a workspace path"
    echo ""
    echo "Examples:"
    echo "  axiom-workspace list"
    echo "  axiom-workspace add /Users/me/projects"
    echo "  axiom-workspace remove /Users/me/old-projects"
}

list_workspaces() {
    echo "Current workspace mounts:"
    grep -E '^\s+- /.*:.*:ro$' "$COMPOSE_FILE" | sed 's/^[[:space:]]*- /  /' | sed 's/:ro$//'
}

add_workspace() {
    local path="$1"

    # Validate path exists
    if [ ! -d "$path" ]; then
        echo "Error: Directory does not exist: $path" >&2
        exit 1
    fi

    # Get absolute path
    path=$(cd "$path" && pwd)

    # Check if already mounted
    if grep -q "- ${path}:${path}:ro" "$COMPOSE_FILE"; then
        echo "Workspace already mounted: $path"
        exit 0
    fi

    # Find the line with axiom-hf-cache volume and add after it
    if grep -q "axiom-hf-cache" "$COMPOSE_FILE"; then
        sed -i.bak "/axiom-hf-cache/a\\
      - ${path}:${path}:ro" "$COMPOSE_FILE"
        rm -f "$COMPOSE_FILE.bak"
    else
        echo "Error: Could not find insertion point in compose file" >&2
        exit 1
    fi

    echo "Added workspace: $path"
    echo ""
    echo "Restart services to apply:"
    echo "  podman-compose -f $COMPOSE_FILE down"
    echo "  podman-compose -f $COMPOSE_FILE up -d"
}

remove_workspace() {
    local path="$1"

    # Get absolute path if it exists
    if [ -d "$path" ]; then
        path=$(cd "$path" && pwd)
    fi

    # Check if mounted
    if ! grep -q "- ${path}:${path}:ro" "$COMPOSE_FILE"; then
        echo "Workspace not found: $path" >&2
        exit 1
    fi

    # Remove the line
    sed -i.bak "\|- ${path}:${path}:ro|d" "$COMPOSE_FILE"
    rm -f "$COMPOSE_FILE.bak"

    echo "Removed workspace: $path"
    echo ""
    echo "Restart services to apply:"
    echo "  podman-compose -f $COMPOSE_FILE down"
    echo "  podman-compose -f $COMPOSE_FILE up -d"
}

case "${1:-}" in
    list)
        list_workspaces
        ;;
    add)
        if [ -z "${2:-}" ]; then
            echo "Error: Path required" >&2
            show_help
            exit 1
        fi
        add_workspace "$2"
        ;;
    remove)
        if [ -z "${2:-}" ]; then
            echo "Error: Path required" >&2
            show_help
            exit 1
        fi
        remove_workspace "$2"
        ;;
    -h|--help|help)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac
EOF

chmod +x ~/.local/bin/axiom-mcp ~/.local/bin/axiom-lsp ~/.local/bin/axiom-ingest ~/.local/bin/axiom-workspace

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
echo "  - axiom-mcp:       MCP server for Claude Code"
echo "  - axiom-lsp:       LSP server for VSCode"
echo "  - axiom-ingest:    Ingest library axioms into databases"
echo "  - axiom-workspace: Manage workspace mounts"
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
echo "  - axiom-mcp:       MCP server for Claude Code"
echo "  - axiom-lsp:       LSP server for VSCode"
echo "  - axiom-ingest:    Ingest library axioms into databases"
echo "  - axiom-workspace: Manage workspace mounts"
echo ""
echo "Managing workspaces:"
echo "  axiom-workspace list                  # Show current mounts"
echo "  axiom-workspace add /path/to/code     # Add workspace"
echo "  axiom-workspace remove /path/to/code  # Remove workspace"
echo ""
echo "Ingesting library axioms:"
echo "  axiom-ingest /path/to/mylib.toml      # Add axioms (additive)"
echo "  axiom-ingest --clear                  # Reset to foundations only"
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
