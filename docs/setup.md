# Axiom Setup Guide

This guide covers setting up Axiom for two use cases:
1. **Claude Code MCP** - Axiom validation tools available in Claude Code CLI
2. **VSCode LSP** - Real-time axiom extraction and hover info in your editor

## Prerequisites

### Required
- Python 3.11+
- Neo4j (via Podman or Docker)
- LLVM/Clang 15+ (for axiom-extract C++ tool)

### Install Dependencies

**Ubuntu/Debian:**
```bash
# Python and build tools
sudo apt update && sudo apt install -y python3 python3-venv python3-pip cmake

# LLVM (pick one version, 15+ required)
sudo apt install -y llvm-18-dev libclang-18-dev clang-18

# Container runtime (pick one)
sudo apt install -y podman podman-compose
# or: sudo apt install -y docker.io docker-compose
```

**macOS:**
```bash
brew install python cmake llvm
brew install podman podman-compose  # or Docker Desktop
```

**Already have LLVM?**

If LLVM is installed but not detected, set the path manually:
```bash
# Find your LLVM installation
llvm-config --prefix   # e.g., /usr/lib/llvm-18

# Build axiom-extract with explicit path
cd tools/axiom-extract
mkdir -p build && cd build
cmake -DCMAKE_PREFIX_PATH=/usr/lib/llvm-18 ..
make -j$(nproc)
```

---

## Quick Start: Database Setup

Before using either MCP or LSP, you need the axiom database running:

```bash
cd /path/to/axiom

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Start Neo4j
podman-compose up -d   # or: docker compose up -d

# Wait ~15 seconds for Neo4j to start, then ingest foundation axioms
python scripts/ingest.py --clear
python scripts/ingest.py
```

This loads ~3,900 axioms from C11, C++, and C++20 specifications into Neo4j and LanceDB.

---

## Option 1: Claude Code MCP Server

The MCP server exposes axiom validation tools to Claude Code CLI.

### Install

```bash
bash scripts/install-mcp.sh
```

This creates `.mcp.json` in the project root, which Claude Code auto-detects.

### Verify

Restart Claude Code, then run `/mcp` to see available tools:
- `validate_claim` - Validate C/C++ claims against formal semantics
- `search_axioms` - Search axioms by semantic similarity
- `get_axiom` - Get a specific axiom by ID
- `get_stats` - Get knowledge base statistics

### Usage Example

In Claude Code:
```
Can you validate: "dereferencing a null pointer is undefined behavior in C"
```

Claude will use the `validate_claim` tool to check this against the axiom database.

---

## Option 2: VSCode LSP

The LSP provides real-time axiom extraction and hover information for C/C++ files.

### Install

```bash
bash scripts/install-lsp.sh
```

This script:
1. Builds the `axiom-extract` C++ tool
2. Installs Python dependencies
3. Configures VSCode settings (`axiom-lsp.path`)
4. Links the VSCode extension

### Reload VSCode

After installation, reload VSCode:
- `Ctrl+Shift+P` → "Developer: Reload Window"

### Verify

1. Open a C/C++ file
2. Check Output panel → "Axiom LSP" for extraction logs
3. Hover over a function with `noexcept` or `const` - you should see axiom info

### Configuration

The LSP reads configuration from `.axiom/config.toml` in your project root:

```toml
[extract]
compile_commands = "build/compile_commands.json"
axiom_extract_path = "/path/to/axiom/tools/axiom-extract/build/axiom-extract"

[static]
neo4j_uri = "bolt://localhost:7687"
neo4j_user = "neo4j"
neo4j_password = "axiompass"
lancedb_path = "/path/to/axiom/data/lancedb"

[diagnostics]
# "llm" = show all diagnostics, "human" = suppress hints
mode = "llm"

[hover]
show_full_chain = true
```

### For External Projects

When working on a C++ project outside the axiom directory:

1. Create `.axiom/config.toml` in your project root (see above)
2. Generate `compile_commands.json`:
   ```bash
   cd your-project
   mkdir build && cd build
   cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON ..
   ```
3. Reload VSCode

### Diagnostic Modes

| Mode | Behavior |
|------|----------|
| `llm` | Emit all diagnostics (hints + warnings) at call sites |
| `human` | Suppress hint-level diagnostics (less noisy) |
| `default` | Same as `llm` |

---

## What Gets Extracted

The axiom-extract tool generates axioms for:

| C++ Feature | Axiom Type | Confidence |
|-------------|------------|------------|
| `noexcept` | EXCEPTION | 1.0 |
| `const` method | EFFECT | 1.0 |
| `[[nodiscard]]` | POSTCONDITION | 1.0 |
| `[[deprecated]]` | ANTI_PATTERN | 1.0 |
| `constexpr` | CONSTRAINT | 1.0 |
| `consteval` | CONSTRAINT | 1.0 |
| `requires` clause | CONSTRAINT | 1.0 |
| `= delete` | CONSTRAINT | 1.0 |
| Trivially copyable types | CONSTRAINT | 1.0 |
| Division in body | PRECONDITION | 0.90 |
| Null dereference | PRECONDITION | 0.90 |

---

## Troubleshooting

### MCP server not showing in Claude Code
- Ensure `.mcp.json` exists in project root
- Restart Claude Code completely
- Check `scripts/install-mcp.sh` output for errors

### LSP not extracting axioms
- Check Output panel → "Axiom LSP" for errors
- Ensure `compile_commands.json` exists
- Verify `axiom-extract` binary is built: `ls tools/axiom-extract/build/axiom-extract`

### Hover shows IntelliSense instead of Axiom
- Axiom hover only appears on lines with extracted axioms
- Check which line has axioms: look at LSP output for "Extracted N axioms"
- Both LSPs respond; IntelliSense may win on lines without axioms

### Neo4j connection failed
- Ensure Neo4j is running: `podman ps` or `docker ps`
- Check credentials in `.axiom/config.toml` match `docker-compose.yml`
- Default: user=`neo4j`, password=`axiompass`

---

## File Locations

| File | Purpose |
|------|---------|
| `.mcp.json` | Claude Code MCP configuration |
| `.axiom/config.toml` | LSP configuration |
| `compile_commands.json` | Clang compilation database |
| `data/lancedb/` | Vector database for semantic search |
| `knowledge/foundations/*.toml` | Foundation axioms (C11, C++, C++20) |
