#!/bin/bash
# Axiom Uninstall Script
set -e

echo "=== Axiom Uninstall ==="

# Parse arguments
KEEP_DATA=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --keep-data)
            KEEP_DATA=true
            shift
            ;;
        --help|-h)
            echo "Usage: ./uninstall.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --keep-data    Keep podman volumes (axiom data, neo4j database)"
            echo "                 Without this flag, all data is deleted"
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

COMPOSE_FILE="$HOME/.local/share/axiom/podman-compose.yml"

# Stop and remove containers
if [ -f "$COMPOSE_FILE" ]; then
    echo "Stopping containers..."
    podman-compose -f "$COMPOSE_FILE" down 2>/dev/null || true
fi

# Remove wrapper scripts
echo "Removing wrapper scripts..."
rm -f ~/.local/bin/axiom-mcp
rm -f ~/.local/bin/axiom-lsp

# Remove compose file and axiom directory
echo "Removing axiom config..."
rm -rf ~/.local/share/axiom

# Remove Claude Code MCP config
if [ -f ~/.config/claude-code/mcp.json ]; then
    echo "Removing Claude Code MCP config..."
    # Check if axiom is the only entry, if so remove file, otherwise just remove axiom entry
    if grep -q '"axiom"' ~/.config/claude-code/mcp.json; then
        # Simple approach: just remove the file (user may need to reconfigure other MCPs)
        rm -f ~/.config/claude-code/mcp.json
        echo "  Removed ~/.config/claude-code/mcp.json"
    fi
fi

# Remove VSCode LSP config
VSCODE_SETTINGS="$HOME/Library/Application Support/Code/User/settings.json"
if [ -f "$VSCODE_SETTINGS" ]; then
    if grep -q 'axiom-lsp' "$VSCODE_SETTINGS"; then
        echo "Note: VSCode settings.json contains axiom-lsp config."
        echo "  You may want to manually remove the axiom-lsp entry from:"
        echo "  $VSCODE_SETTINGS"
    fi
fi

# Remove volumes (unless --keep-data)
if [ "$KEEP_DATA" = false ]; then
    echo "Removing data volumes..."
    podman volume rm axiom-data 2>/dev/null || true
    podman volume rm axiom-hf-cache 2>/dev/null || true
    podman volume rm neo4j-data 2>/dev/null || true
    podman volume rm neo4j-logs 2>/dev/null || true
    # Also try with underscores (podman-compose naming)
    podman volume rm axiom_axiom-data 2>/dev/null || true
    podman volume rm axiom_axiom-hf-cache 2>/dev/null || true
    podman volume rm axiom_neo4j-data 2>/dev/null || true
    podman volume rm axiom_neo4j-logs 2>/dev/null || true
else
    echo "Keeping data volumes (--keep-data specified)"
fi

# Optionally remove images
echo ""
read -p "Remove container images (ghcr.io/mattyv/axiom, neo4j)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Removing images..."
    podman rmi ghcr.io/mattyv/axiom:latest 2>/dev/null || true
    podman rmi localhost/axiom:latest 2>/dev/null || true
    podman rmi docker.io/library/neo4j:5.15 2>/dev/null || true
fi

echo ""
echo "=== Uninstall Complete ==="
echo ""
if [ "$KEEP_DATA" = true ]; then
    echo "Data volumes were preserved. To remove them later:"
    echo "  podman volume rm axiom-data axiom-hf-cache neo4j-data neo4j-logs"
fi
