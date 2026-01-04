#!/bin/bash
# Axiom LSP Installation Script
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0
#
# This script sets up the Axiom LSP for VS Code:
# 1. Builds the clangd plugin
# 2. Installs Python dependencies
# 3. Configures VS Code settings

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Axiom LSP Installation ==="
echo ""

# Check prerequisites
check_prereqs() {
    echo "Checking prerequisites..."

    if ! command -v cmake &> /dev/null; then
        echo "Error: cmake is required but not installed."
        echo "Install with: brew install cmake"
        exit 1
    fi

    if ! command -v clangd &> /dev/null; then
        echo "Warning: clangd not found in PATH."
        echo "VS Code clangd extension will need to be installed."
    fi

    if [ ! -d "/opt/homebrew/opt/llvm" ] && [ ! -d "/usr/local/opt/llvm" ]; then
        echo "Error: LLVM not found. Install with: brew install llvm"
        exit 1
    fi

    echo "Prerequisites OK"
    echo ""
}

# Build clangd plugin
build_plugin() {
    echo "Building axiom-clangd plugin..."

    PLUGIN_DIR="$PROJECT_ROOT/tools/axiom-clangd"
    BUILD_DIR="$PLUGIN_DIR/build"

    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"

    # Determine LLVM path
    if [ -d "/opt/homebrew/opt/llvm" ]; then
        LLVM_PATH="/opt/homebrew/opt/llvm"
    else
        LLVM_PATH="/usr/local/opt/llvm"
    fi

    cmake -DCMAKE_PREFIX_PATH="$LLVM_PATH" ..
    make -j$(sysctl -n hw.ncpu)

    echo "Plugin built: $BUILD_DIR/libaxiom-clangd.dylib"
    echo ""
}

# Install Python dependencies
install_python_deps() {
    echo "Installing Python dependencies..."

    cd "$PROJECT_ROOT"

    if [ -d ".venv" ]; then
        source .venv/bin/activate
    else
        echo "Creating virtual environment..."
        python3 -m venv .venv
        source .venv/bin/activate
    fi

    pip install -e ".[lsp]" --quiet

    echo "Python dependencies installed"
    echo ""
}

# Configure VS Code
configure_vscode() {
    echo "Configuring VS Code..."

    VSCODE_SETTINGS_DIR="$PROJECT_ROOT/.vscode"
    mkdir -p "$VSCODE_SETTINGS_DIR"

    SETTINGS_FILE="$VSCODE_SETTINGS_DIR/settings.json"

    # Check if settings.json exists
    if [ -f "$SETTINGS_FILE" ]; then
        echo "VS Code settings already exist at $SETTINGS_FILE"
        echo "Please manually add the clangd configuration if needed."
    else
        cat > "$SETTINGS_FILE" << 'EOF'
{
    "clangd.path": "clangd",
    "clangd.arguments": [
        "--background-index",
        "--clang-tidy",
        "--header-insertion=iwyu",
        "--completion-style=detailed"
    ],
    "[cpp]": {
        "editor.defaultFormatter": "llvm-vs-code-extensions.vscode-clangd"
    },
    "[c]": {
        "editor.defaultFormatter": "llvm-vs-code-extensions.vscode-clangd"
    }
}
EOF
        echo "Created $SETTINGS_FILE"
    fi

    echo ""
}

# Create launch script for query server
create_launch_script() {
    echo "Creating launch script..."

    LAUNCH_SCRIPT="$PROJECT_ROOT/scripts/start-axiom-lsp.sh"

    cat > "$LAUNCH_SCRIPT" << 'EOF'
#!/bin/bash
# Start Axiom LSP services
# Run this before opening VS Code

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"
source .venv/bin/activate

echo "Starting Axiom Query Server..."
axiom-query-server &
QUERY_PID=$!

echo "Query server started (PID: $QUERY_PID)"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for interrupt
trap "kill $QUERY_PID 2>/dev/null; exit 0" INT TERM

wait $QUERY_PID
EOF

    chmod +x "$LAUNCH_SCRIPT"
    echo "Created $LAUNCH_SCRIPT"
    echo ""
}

# Print usage instructions
print_usage() {
    echo "=== Installation Complete ==="
    echo ""
    echo "To use Axiom LSP:"
    echo ""
    echo "1. Start the query server (in a terminal):"
    echo "   ./scripts/start-axiom-lsp.sh"
    echo ""
    echo "2. Open VS Code in this directory"
    echo ""
    echo "3. Install the clangd extension if not already installed:"
    echo "   code --install-extension llvm-vs-code-extensions.vscode-clangd"
    echo ""
    echo "Note: The clangd plugin integration is experimental."
    echo "Currently, axiom diagnostics require running axiom-query-server"
    echo "and the full clangd plugin integration is pending clangd's"
    echo "plugin API stabilization."
    echo ""
    echo "For Claude Code integration:"
    echo "   export ENABLE_LSP_TOOL=1"
    echo "   claude"
    echo ""
}

# Main
main() {
    check_prereqs
    build_plugin
    install_python_deps
    configure_vscode
    create_launch_script
    print_usage
}

main "$@"
