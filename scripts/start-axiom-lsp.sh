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
