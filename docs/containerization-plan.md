# Axiom Podman Containerization Plan

## Goal
Package the fundamentals layer (C11/C++ axioms) using **podman-compose** for easy shipping and deployment.

**Using Podman** - fully open source, no license required.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Host Machine                                       │
│  ┌───────────────┐  ┌───────────────────────────┐  │
│  │ Claude Code   │  │ VSCode/Editor             │  │
│  │ (MCP client)  │  │ (LSP client)              │  │
│  └───────┬───────┘  └───────────┬───────────────┘  │
│          │ stdio                │ stdio            │
│          ▼                      ▼                  │
│  ┌─────────────────────────────────────────────┐   │
│  │  podman-compose (axiom-network)             │   │
│  │  ┌─────────────────────────────────────┐    │   │
│  │  │ axiom-app container                 │    │   │
│  │  │ - Python App (MCP/LSP)              │    │   │
│  │  │ - LanceDB (embedded)                │    │   │
│  │  │ - TOML knowledge files              │    │   │
│  │  └──────────────┬──────────────────────┘    │   │
│  │                 │ bolt://neo4j:7687         │   │
│  │  ┌──────────────▼──────────────────────┐    │   │
│  │  │ neo4j container                     │    │   │
│  │  │ - Neo4j 5.15 (graph DB)             │    │   │
│  │  │ - Proof chains & relationships      │    │   │
│  │  └─────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  Volumes:                                           │
│  - axiom-data (LanceDB + init flag)                │
│  - axiom-hf-cache (sentence-transformer model)     │
│  - neo4j-data (graph database)                     │
└─────────────────────────────────────────────────────┘
```

## Multi-Container Approach

Two containers managed by podman-compose:

1. **axiom-app**: Python app + LanceDB (embedded) + TOML knowledge files
2. **neo4j**: Official Neo4j 5.15 image for graph database

Users run `podman-compose up -d` to start both containers.

## Limitations

### MCP Server (Full Support)
The containerized MCP server provides full functionality:
- Validate claims against C11/C++20 semantics
- Search axioms by semantic similarity
- Get axiom details and proof chains

### LSP Server (Static Layer Only)
The containerized LSP server has limited functionality:
- **Works**: Hover info for stdlib/language constructs from foundation axioms
- **Does NOT work**: Live extraction of user's project code

Live extraction requires the `axiom-extract` C++ tool (built with LLVM LibTooling) to have filesystem access to user source files. The container cannot see host files.

**For full LSP functionality**, users should run axiom-lsp natively:
```bash
pip install axiom[lsp]
axiom-lsp
```

## Implementation Steps

### 1. Create Containerfile
**File**: `containers/Containerfile`

```dockerfile
FROM python:3.12-slim

# Install build deps for sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash axiom
WORKDIR /home/axiom/app

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[full,lsp]"

# Copy app code and TOML knowledge files (NOT pre-loaded DBs)
COPY axiom/ axiom/
COPY scripts/ scripts/
COPY knowledge/ knowledge/
# Note: data/lancedb/ is NOT copied - will be created on first startup

# Fix permissions
RUN chown -R axiom:axiom /home/axiom

USER axiom

COPY containers/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

### 2. Create Entrypoint Script
**File**: `containers/entrypoint.sh`

```bash
#!/bin/bash
set -e

DATA_DIR="/home/axiom/data"
LANCEDB_DIR="$DATA_DIR/lancedb"
INITIALIZED_FLAG="$DATA_DIR/.initialized"

# Wait for Neo4j to be ready
echo "Waiting for Neo4j..."
until python -c "from neo4j import GraphDatabase; d=GraphDatabase.driver('$AXIOM_NEO4J_URI', auth=('$AXIOM_NEO4J_USER','$AXIOM_NEO4J_PASSWORD')); d.verify_connectivity(); d.close()" 2>/dev/null; do
    sleep 2
done
echo "Neo4j ready!"

# First-run initialization
if [ ! -f "$INITIALIZED_FLAG" ]; then
    echo "First startup - initializing axiom database..."

    # Download embedding model
    echo "Downloading embedding model..."
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

    # Run ingestion from TOML files into both LanceDB and Neo4j
    echo "Ingesting axioms from TOML files..."
    python -m scripts.ingest --lancedb-path "$LANCEDB_DIR"

    touch "$INITIALIZED_FLAG"
    echo "Initialization complete!"
fi

# Keep container running
echo "Axiom server ready"
exec tail -f /dev/null
```

### 3. Create podman-compose.yml
**File**: `containers/podman-compose.yml`

```yaml
version: '3.8'

services:
  axiom-app:
    image: ghcr.io/mattyv/axiom:latest
    container_name: axiom-app
    depends_on:
      neo4j:
        condition: service_healthy
    environment:
      - AXIOM_NEO4J_URI=bolt://neo4j:7687
      - AXIOM_NEO4J_USER=neo4j
      - AXIOM_NEO4J_PASSWORD=axiompass
      - AXIOM_LANCEDB_PATH=/home/axiom/data/lancedb
    volumes:
      - axiom-data:/home/axiom/data
      - axiom-hf-cache:/home/axiom/.cache/huggingface
    read_only: true
    tmpfs:
      - /tmp
    # No ports - stdio only via podman exec

  neo4j:
    image: docker.io/library/neo4j:5.15
    container_name: axiom-neo4j
    environment:
      - NEO4J_AUTH=neo4j/axiompass
      - NEO4J_PLUGINS=["apoc"]
      - NEO4J_dbms_memory_heap_max__size=512M
      - NEO4J_dbms_memory_pagecache_size=256M
    volumes:
      - neo4j-data:/data
      - neo4j-logs:/logs
    healthcheck:
      test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider localhost:7474 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    # No ports exposed by default - only accessible within network

volumes:
  axiom-data:
  axiom-hf-cache:
  neo4j-data:
  neo4j-logs:

networks:
  default:
    name: axiom-network
```

## Usage

```bash
# Start both containers
podman-compose -f ~/.local/share/axiom/podman-compose.yml up -d

# First startup takes ~30s (downloads model + ingests axioms)
# Subsequent starts are <2s

# MCP - Claude Code invokes axiom-mcp wrapper
# LSP - Editor invokes axiom-lsp wrapper

# Stop when done
podman-compose -f ~/.local/share/axiom/podman-compose.yml down
```

## Data Handling

- **TOML files**: Baked into axiom-app image (immutable, versioned)
- **LanceDB vectors**: Generated on first startup, persisted in `axiom-data` volume
- **Neo4j data**: Generated on first startup, persisted in `neo4j-data` volume
- **Sentence-transformer model**: Downloaded on first use, cached in `axiom-hf-cache` volume

## Image Size

```
axiom-app container:
- python:3.12-slim base:           ~120MB
- Python deps (torch, lancedb):    ~350MB
- TOML knowledge files:            ~5MB
---
Image size:                        ~475MB

neo4j container:
- Official neo4j:5.15 image:       ~500MB

Runtime volumes (created on first startup):
- Sentence-transformer model:      ~90MB (downloaded to volume)
- LanceDB vectors:                 ~15MB (generated from TOMLs)
- Neo4j data:                      ~50MB (generated from TOMLs)

First startup: ~30s (download model + ingest axioms)
Subsequent starts: <2s
```

## Multi-Architecture Support

Build for both amd64 (Intel/AMD) and arm64 (Apple Silicon, ARM servers):

```bash
# Build for both architectures
podman manifest create ghcr.io/mattyv/axiom:latest

podman build --platform linux/amd64 \
  -t ghcr.io/mattyv/axiom:latest-amd64 \
  -f containers/Containerfile .

podman build --platform linux/arm64 \
  -t ghcr.io/mattyv/axiom:latest-arm64 \
  -f containers/Containerfile .

podman manifest add ghcr.io/mattyv/axiom:latest \
  ghcr.io/mattyv/axiom:latest-amd64
podman manifest add ghcr.io/mattyv/axiom:latest \
  ghcr.io/mattyv/axiom:latest-arm64

podman manifest push ghcr.io/mattyv/axiom:latest
```

## CI/CD

**File**: `.github/workflows/container.yml`

```yaml
name: Container Build

on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        run: echo "${{ secrets.GITHUB_TOKEN }}" | podman login ghcr.io -u ${{ github.actor }} --password-stdin

      - name: Build image
        run: podman build -t ghcr.io/mattyv/axiom:${{ github.sha }} -f containers/Containerfile .

      - name: Test MCP server
        run: |
          podman run --rm ghcr.io/mattyv/axiom:${{ github.sha }} \
            python -c "from axiom.mcp.server import main"

      - name: Push
        run: |
          podman push ghcr.io/mattyv/axiom:${{ github.sha }}
          podman tag ghcr.io/mattyv/axiom:${{ github.sha }} ghcr.io/mattyv/axiom:latest
          podman push ghcr.io/mattyv/axiom:latest
```

## Security

Security is handled in podman-compose.yml:
- `read_only: true` on axiom-app container
- `tmpfs` for /tmp (ephemeral scratch space)
- Non-root user (`axiom`) in Containerfile
- Internal network only (no exposed ports by default)
- Named volumes for persistent data

Note: axiom-app needs network access to reach neo4j container.

## Publishing

Push to GitHub Container Registry:

```bash
# Build
podman build -t ghcr.io/mattyv/axiom:latest -f containers/Containerfile .

# Login (once)
podman login ghcr.io -u mattyv

# Push
podman push ghcr.io/mattyv/axiom:latest
```

## User Installation

### Main install script
**File**: `containers/install.sh`

```bash
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
echo "  - For Claude Code: run 'axiom-install-mcp'"
echo "  - For VSCode:      run 'axiom-install-vscode'"
echo ""
echo "Note: First run will take ~30s to download model and ingest axioms."
```

### MCP install script
**File**: `containers/install-mcp.sh`

```bash
#!/bin/bash
# Configure Axiom MCP for Claude Code
set -e

MCP_DIR="$HOME/.config/claude-code"
MCP_FILE="$MCP_DIR/mcp.json"

mkdir -p "$MCP_DIR"

# Get path to axiom-mcp
AXIOM_MCP="$HOME/.local/bin/axiom-mcp"
if [ ! -x "$AXIOM_MCP" ]; then
    echo "Error: axiom-mcp not found. Run install.sh first."
    exit 1
fi

# Create or merge mcp.json
if [ -f "$MCP_FILE" ]; then
    cp "$MCP_FILE" "$MCP_FILE.bak"
    if command -v jq &> /dev/null; then
        jq --arg cmd "$AXIOM_MCP" '.mcpServers.axiom = {"command": $cmd}' "$MCP_FILE.bak" > "$MCP_FILE"
        echo "Updated $MCP_FILE (backup at $MCP_FILE.bak)"
    else
        echo "Warning: jq not found. Please manually add to $MCP_FILE:"
        echo '  "axiom": {"command": "'$AXIOM_MCP'"}'
    fi
else
    cat > "$MCP_FILE" << EOF
{
  "mcpServers": {
    "axiom": {
      "command": "$AXIOM_MCP"
    }
  }
}
EOF
    echo "Created $MCP_FILE"
fi

echo ""
echo "Axiom MCP configured for Claude Code!"
echo "Restart Claude Code to activate."
```

### VSCode install script
**File**: `containers/install-vscode.sh`

```bash
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
```

### User Installation Flow

```bash
# 1. Install base (pulls images, creates wrappers, downloads compose file)
curl -sSL https://raw.githubusercontent.com/mattyv/axiom/main/containers/install.sh | bash

# 2. Configure for Claude Code
~/.local/bin/axiom-install-mcp

# 3. Configure for VSCode
~/.local/bin/axiom-install-vscode
```

## Files to Create

| File | Description |
|------|-------------|
| `containers/Containerfile` | Python app image with LanceDB + TOML files |
| `containers/entrypoint.sh` | Waits for Neo4j, runs first-time initialization |
| `containers/podman-compose.yml` | Two-container setup (axiom-app + neo4j) |
| `containers/install.sh` | Main install script (pulls images, creates wrappers) |
| `containers/install-mcp.sh` | Configures Claude Code mcp.json |
| `containers/install-vscode.sh` | Configures VSCode settings.json (with OS detection) |
| `.github/workflows/container.yml` | CI/CD for building and pushing to GHCR |
