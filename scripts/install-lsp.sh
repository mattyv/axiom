#!/bin/bash
# Axiom LSP Installation Script
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0
#
# This script sets up the Axiom LSP:
# 1. Builds the axiom-extract C++ tool
# 2. Installs Python dependencies
# 3. Verifies the installation

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Axiom LSP Installation ==="
echo ""

# Detect OS and set platform-specific variables
detect_platform() {
    case "$(uname -s)" in
        Darwin*)
            PLATFORM="macos"
            if [ -d "/opt/homebrew/opt/llvm" ]; then
                LLVM_PATH="/opt/homebrew/opt/llvm"
            elif [ -d "/usr/local/opt/llvm" ]; then
                LLVM_PATH="/usr/local/opt/llvm"
            else
                LLVM_PATH=""
            fi
            ;;
        Linux*)
            PLATFORM="linux"
            # Check common LLVM locations on Linux
            if [ -d "/usr/lib/llvm-18" ]; then
                LLVM_PATH="/usr/lib/llvm-18"
            elif [ -d "/usr/lib/llvm-17" ]; then
                LLVM_PATH="/usr/lib/llvm-17"
            elif [ -d "/usr/lib/llvm-16" ]; then
                LLVM_PATH="/usr/lib/llvm-16"
            elif [ -d "/usr/lib/llvm-15" ]; then
                LLVM_PATH="/usr/lib/llvm-15"
            elif command -v llvm-config &> /dev/null; then
                LLVM_PATH="$(llvm-config --prefix)"
            else
                LLVM_PATH=""
            fi
            ;;
        *)
            echo "Error: Unsupported platform: $(uname -s)"
            exit 1
            ;;
    esac

    echo "Detected platform: $PLATFORM"
    if [ -n "$LLVM_PATH" ]; then
        echo "LLVM path: $LLVM_PATH"
    fi
}

# Check prerequisites
check_prereqs() {
    echo "Checking prerequisites..."

    if ! command -v cmake &> /dev/null; then
        echo "Error: cmake is required but not installed."
        if [ "$PLATFORM" = "macos" ]; then
            echo "Install with: brew install cmake"
        else
            echo "Install with: sudo apt install cmake"
        fi
        exit 1
    fi

    if ! command -v python3 &> /dev/null; then
        echo "Error: python3 is required but not installed."
        if [ "$PLATFORM" = "linux" ]; then
            echo "Install with: sudo apt install python3 python3-venv python3-pip"
        fi
        exit 1
    fi

    # Check for LLVM (needed for axiom-extract)
    if [ -z "$LLVM_PATH" ]; then
        echo "Error: LLVM not found."
        if [ "$PLATFORM" = "macos" ]; then
            echo "Install with: brew install llvm"
        else
            echo "Install with: sudo apt install llvm-18-dev libclang-18-dev clang-18"
            echo "  (or llvm-17-dev, etc.)"
        fi
        exit 1
    fi

    echo "Prerequisites OK"
    echo ""
}

# Build axiom-extract C++ tool
build_extractor() {
    EXTRACT_DIR="$PROJECT_ROOT/tools/axiom-extract"
    BUILD_DIR="$EXTRACT_DIR/build"
    BINARY="$BUILD_DIR/axiom-extract"

    # Skip if binary already exists
    if [ -x "$BINARY" ]; then
        echo "axiom-extract already built: $BINARY"
        echo "  (delete it to force rebuild)"
        echo ""
        return 0
    fi

    echo "Building axiom-extract..."

    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"

    cmake -DCMAKE_PREFIX_PATH="$LLVM_PATH" ..

    # Use appropriate parallel build command
    if [ "$PLATFORM" = "macos" ]; then
        make -j$(sysctl -n hw.ncpu)
    else
        make -j$(nproc)
    fi

    echo "axiom-extract built: $BINARY"
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

# Create compile_commands.json for C++ standard library support
create_compile_commands() {
    echo "Creating compile_commands.json..."

    CC_BUILD_DIR="$PROJECT_ROOT/build"
    mkdir -p "$CC_BUILD_DIR"

    # Get LLVM version for include paths
    LLVM_VERSION=$("$LLVM_PATH/bin/clang" --version | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    LLVM_MAJOR=$(echo "$LLVM_VERSION" | cut -d. -f1)

    if [ "$PLATFORM" = "macos" ]; then
        # macOS: use libc++ with SDK sysroot
        cat > "$CC_BUILD_DIR/compile_commands.json" << EOF
[
  {
    "directory": "$PROJECT_ROOT",
    "command": "$LLVM_PATH/bin/clang++ -std=c++17 -stdlib=libc++ -isysroot /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk -isystem $LLVM_PATH/include/c++/v1 -isystem $LLVM_PATH/lib/clang/$LLVM_MAJOR/include -c examples/demo_axiom_issues.cpp -o /dev/null",
    "file": "$PROJECT_ROOT/examples/demo_axiom_issues.cpp"
  }
]
EOF
    else
        # Linux: use libstdc++ (default) or libc++ if available
        cat > "$CC_BUILD_DIR/compile_commands.json" << EOF
[
  {
    "directory": "$PROJECT_ROOT",
    "command": "$LLVM_PATH/bin/clang++ -std=c++17 -c examples/demo_axiom_issues.cpp -o /dev/null",
    "file": "$PROJECT_ROOT/examples/demo_axiom_issues.cpp"
  }
]
EOF
    fi

    echo "Created $CC_BUILD_DIR/compile_commands.json"
    echo ""
}

# Verify installation
verify_install() {
    echo "Verifying installation..."

    cd "$PROJECT_ROOT"
    source .venv/bin/activate

    # Check axiom-extract binary exists
    if [ ! -x "$PROJECT_ROOT/tools/axiom-extract/build/axiom-extract" ]; then
        echo "Error: axiom-extract binary not found"
        exit 1
    fi

    # Check axiom-lsp command works
    if ! command -v axiom-lsp &> /dev/null; then
        echo "Error: axiom-lsp command not found"
        exit 1
    fi

    # Check compile_commands.json exists
    if [ ! -f "$PROJECT_ROOT/build/compile_commands.json" ]; then
        echo "Error: build/compile_commands.json not found"
        exit 1
    fi

    echo "Installation verified"
    echo ""
}

# Configure VSCode extension
configure_vscode() {
    echo "Configuring VSCode extension..."

    AXIOM_LSP_PATH="$PROJECT_ROOT/.venv/bin/axiom-lsp"
    VSCODE_SETTINGS="$HOME/.config/Code/User/settings.json"

    # macOS uses different path
    if [ "$PLATFORM" = "macos" ]; then
        VSCODE_SETTINGS="$HOME/Library/Application Support/Code/User/settings.json"
    fi

    # Create settings directory if needed
    mkdir -p "$(dirname "$VSCODE_SETTINGS")"

    if [ -f "$VSCODE_SETTINGS" ]; then
        # Check if axiom-lsp.path already configured
        if grep -q "axiom-lsp.path" "$VSCODE_SETTINGS"; then
            echo "  axiom-lsp.path already configured in VSCode settings"
        else
            # Add axiom-lsp.path to existing settings (before final brace)
            # Use temp file for portability
            TMP_FILE=$(mktemp)
            sed '$ s/}$/,\n    "axiom-lsp.path": "'"$AXIOM_LSP_PATH"'"\n}/' "$VSCODE_SETTINGS" > "$TMP_FILE"
            mv "$TMP_FILE" "$VSCODE_SETTINGS"
            echo "  Added axiom-lsp.path to VSCode settings"
        fi
    else
        # Create new settings file
        cat > "$VSCODE_SETTINGS" << EOF
{
    "axiom-lsp.path": "$AXIOM_LSP_PATH"
}
EOF
        echo "  Created VSCode settings with axiom-lsp.path"
    fi

    # Install/link VSCode extension
    VSCODE_EXT_DIR="$HOME/.vscode/extensions"
    mkdir -p "$VSCODE_EXT_DIR"

    EXT_LINK="$VSCODE_EXT_DIR/axiom-lsp-0.1.0"
    EXT_SRC="$PROJECT_ROOT/editors/vscode-axiom"

    if [ -L "$EXT_LINK" ] || [ -d "$EXT_LINK" ]; then
        echo "  VSCode extension already installed"
    else
        # Build extension if needed
        if [ ! -f "$EXT_SRC/out/extension.js" ]; then
            echo "  Building VSCode extension..."
            cd "$EXT_SRC"
            npm install --quiet 2>/dev/null
            npm run compile --quiet 2>/dev/null
            cd "$PROJECT_ROOT"
        fi

        ln -sfn "$EXT_SRC" "$EXT_LINK"
        echo "  Linked VSCode extension"
    fi

    echo ""
}

# Print usage instructions
print_usage() {
    echo "=== Installation Complete ==="
    echo ""
    echo "Axiom LSP is now configured for VSCode."
    echo ""
    echo "Reload VSCode to activate the extension."
    echo "The LSP will automatically start for any C/C++ file."
    echo ""
    echo "Manual usage (if needed):"
    echo ""
    echo "  axiom-lsp                    # Start LSP server"
    echo "  axiom-lsp --mode human       # Suppress axiom-context hints"
    echo "  axiom-lsp --mode llm         # Emit all diagnostics (default)"
    echo "  axiom-lsp -v                 # Enable debug logging"
    echo ""
    echo "For file watching (live extraction):"
    echo "  axiom-watcher -v"
    echo ""
}

# Main
main() {
    detect_platform
    echo ""
    check_prereqs
    build_extractor
    install_python_deps
    create_compile_commands
    verify_install
    configure_vscode
    print_usage
}

main "$@"
