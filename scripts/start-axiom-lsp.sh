#!/bin/bash
# Start Axiom LSP server
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "Error: Virtual environment not found. Run scripts/install-lsp.sh first."
    exit 1
fi

# Parse arguments
MODE="llm"
VERBOSE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE="-v"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--mode default|llm|human] [-v|--verbose]"
            exit 1
            ;;
    esac
done

echo "Starting Axiom LSP server (mode: $MODE)..."
exec axiom-lsp --mode "$MODE" $VERBOSE
