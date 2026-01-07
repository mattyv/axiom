# Axiom Podman Containerization Plan

## Goal
Package the fundamentals layer (C11/C++ axioms) in a **single container** for easy shipping and deployment. One command to run.

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
│  │  axiom-server container (long-running)      │   │
│  │  ┌─────────────┐  ┌──────────────────────┐  │   │
│  │  │ Neo4j       │  │ Python App           │  │   │
│  │  │ (embedded)  │  │ (MCP/LSP on demand)  │  │   │
│  │  └─────────────┘  └──────────────────────┘  │   │
│  │  LanceDB (embedded)                         │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

## Single Container Approach

Everything in one container:
- Neo4j (embedded mode or lightweight graph DB)
- LanceDB (file-based, no server)
- Python app with MCP/LSP servers
- Pre-loaded foundations axioms
- Sentence-transformer model downloads on first use (~400MB, cached in volume)

## Implementation Steps

### 1. Create Containerfile
**File**: `containers/Containerfile`

```dockerfile
FROM python:3.12-slim

# Install Neo4j (or use embedded alternative like kuzu/memgraph)
# Install Python deps
# Bake in model + axioms
# Pre-ingest data during build

ENTRYPOINT ["/app/containers/entrypoint.sh"]
```

### 2. Create Entrypoint Script
**File**: `containers/entrypoint.sh`

- Start Neo4j in background
- Wait for ready
- Exec requested service (mcp/lsp)

### 3. Create wrapper scripts
**Files**: `containers/run-mcp.sh`, `containers/run-lsp.sh`

```bash
#!/bin/bash
podman exec -i axiom-server python -m axiom.mcp.server
```

## Usage

```bash
# Start the container (once)
podman run -d --name axiom-server ghcr.io/mattyv/axiom:latest

# MCP - Claude Code invokes run-mcp.sh
# LSP - Editor invokes run-lsp.sh

# Stop when done
podman stop axiom-server
```

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

Users install with:
```bash
podman pull ghcr.io/mattyv/axiom:latest
podman run -d --name axiom-server ghcr.io/mattyv/axiom:latest
```

## Data Handling

- **TOML files**: Baked into image (immutable, versioned)
- **Neo4j data**: Baked into image (pre-ingested during build)
- **LanceDB vectors**: Baked into image (pre-computed during build)
- **Sentence-transformer model**: Downloads on first use, cached in `~/.cache/huggingface` volume

## Image Size

- Without model: ~350MB
- Model download on first use: ~400MB (one-time, cached)

Run with cache volume:
```bash
podman run -d --name axiom-server \
  -v axiom-hf-cache:/root/.cache/huggingface \
  ghcr.io/mattyv/axiom:latest
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

# Pull image
echo "Pulling axiom image..."
podman pull ghcr.io/mattyv/axiom:latest

# Create wrapper scripts in ~/.local/bin
mkdir -p ~/.local/bin

cat > ~/.local/bin/axiom-mcp << 'EOF'
#!/bin/bash
podman start axiom-server 2>/dev/null || \
  podman run -d --name axiom-server \
    -v axiom-hf-cache:/root/.cache/huggingface \
    ghcr.io/mattyv/axiom:latest
podman exec -i axiom-server python -m axiom.mcp.server
EOF

cat > ~/.local/bin/axiom-lsp << 'EOF'
#!/bin/bash
podman start axiom-server 2>/dev/null || \
  podman run -d --name axiom-server \
    -v axiom-hf-cache:/root/.cache/huggingface \
    ghcr.io/mattyv/axiom:latest
podman exec -i axiom-server python -m axiom.lsp.server "$@"
EOF

chmod +x ~/.local/bin/axiom-mcp ~/.local/bin/axiom-lsp

echo "Installed wrapper scripts to ~/.local/bin/"
echo ""
echo "Next steps:"
echo "  - For Claude Code: run 'axiom-install-mcp'"
echo "  - For VSCode:      run 'axiom-install-vscode'"
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
    # Backup existing
    cp "$MCP_FILE" "$MCP_FILE.bak"
    # Merge using jq if available, otherwise warn
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

VSCODE_DIR="$HOME/.config/Code/User"
SETTINGS_FILE="$VSCODE_DIR/settings.json"

# Get path to axiom-lsp
AXIOM_LSP="$HOME/.local/bin/axiom-lsp"
if [ ! -x "$AXIOM_LSP" ]; then
    echo "Error: axiom-lsp not found. Run install.sh first."
    exit 1
fi

mkdir -p "$VSCODE_DIR"

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
# 1. Install base (pulls image, creates wrappers)
curl -sSL https://raw.githubusercontent.com/mattyv/axiom/main/containers/install.sh | bash

# 2. Configure for Claude Code
~/.local/bin/axiom-install-mcp

# 3. Configure for VSCode
~/.local/bin/axiom-install-vscode
```

## Files to Create

| File | Description |
|------|-------------|
| `containers/Containerfile` | All-in-one image with Neo4j + Python app |
| `containers/entrypoint.sh` | Starts Neo4j, waits for ready, execs command |
| `containers/install.sh` | Main install script (pulls image, creates wrappers) |
| `containers/install-mcp.sh` | Configures Claude Code mcp.json |
| `containers/install-vscode.sh` | Configures VSCode settings.json |
