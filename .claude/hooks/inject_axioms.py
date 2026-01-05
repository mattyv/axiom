#!/usr/bin/env python3
"""Claude Code hook to inject axiom context for C++ files.

This hook runs on UserPromptSubmit and injects relevant axioms
into Claude's context based on C++ files being discussed.
"""

import json
import os
import re
import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR))

# C++ file extensions
CPP_EXTENSIONS = {".cpp", ".cc", ".cxx", ".c", ".hpp", ".hh", ".hxx", ".h"}


def load_config() -> dict:
    """Load hook configuration."""
    config_path = Path(__file__).parent / "config.toml"
    defaults = {
        "mode": "selection",  # "selection" or "comprehensive"
        "max_axioms": 30,
        "show_formal": False,
    }

    if config_path.exists():
        try:
            import tomllib
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
                return {**defaults, **data.get("axiom_injection", {})}
        except Exception:
            pass

    return defaults


def find_cpp_files_in_context(context: dict) -> list[tuple[str, int | None, int | None]]:
    """Find C++ files mentioned in the conversation context.

    Returns list of (file_path, start_line, end_line) tuples.
    start_line/end_line are None if no specific selection.
    """
    files = []

    # Get the user's prompt
    prompt = context.get("prompt", "")

    # Check for ide_selection in the prompt (from VS Code integration)
    # Format: <ide_selection>..file path..lines X to Y..</ide_selection>
    ide_selection_pattern = r"<ide_selection>.*?/([^/\n]+\.(cpp|cc|cxx|c|hpp|hh|hxx|h)).*?lines?\s*(\d+)\s*(?:to|-)\s*(\d+)"
    for match in re.finditer(ide_selection_pattern, prompt, re.IGNORECASE | re.DOTALL):
        filename = match.group(1)
        start = int(match.group(3))
        end = int(match.group(4))
        # Try to find full path
        full_path = find_file_path(filename)
        if full_path:
            files.append((full_path, start, end))

    # Check for explicit file paths in prompt
    file_pattern = r'(?:^|[\s"`\'(])(/[^\s"`\')\n]+\.(?:cpp|cc|cxx|c|hpp|hh|hxx|h))(?:[\s"`\'):]|$)'
    for match in re.finditer(file_pattern, prompt, re.MULTILINE):
        path = match.group(1)
        if os.path.exists(path) and (path, None, None) not in files:
            files.append((path, None, None))

    # Check for relative paths
    rel_pattern = r'(?:^|[\s"`\'(])([a-zA-Z0-9_./]+\.(?:cpp|cc|cxx|c|hpp|hh|hxx|h))(?:[\s"`\'):]|$)'
    for match in re.finditer(rel_pattern, prompt, re.MULTILINE):
        rel_path = match.group(1)
        full_path = find_file_path(rel_path)
        if full_path and (full_path, None, None) not in files:
            files.append((full_path, None, None))

    return files


def find_file_path(filename: str) -> str | None:
    """Find full path for a filename."""
    # Check if it's already an absolute path
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename

    # Check relative to project directory
    project_path = PROJECT_DIR / filename
    if project_path.exists():
        return str(project_path)

    # Check in common locations
    for subdir in ["examples", "src", "include", "tests"]:
        path = PROJECT_DIR / subdir / filename
        if path.exists():
            return str(path)

    return None


def get_axioms_for_file(
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    config: dict = None,
) -> list[dict]:
    """Get axioms for a C++ file, optionally filtered by line range."""
    config = config or {}

    try:
        from axiom.lsp.server import AxiomLanguageServer

        # Create server instance (loads Neo4j axioms)
        server = AxiomLanguageServer()

        # Extract call graph for the file
        collection, call_graph = server._extractor.extract_file_with_call_graph(file_path)

        if not call_graph:
            return []

        # Filter by line range if specified
        if start_line is not None and end_line is not None:
            call_graph = [
                c for c in call_graph
                if start_line <= c.get("line", 0) <= end_line
            ]

        # Get axioms for each callee
        axioms_by_line = {}
        for call in call_graph:
            line = call.get("line", 0)
            callee = call.get("callee", "")

            if not callee:
                continue

            # Get axioms for this callee
            callee_axioms = server.get_axioms_for_callee(callee)

            if callee_axioms:
                if line not in axioms_by_line:
                    axioms_by_line[line] = []

                for axiom in callee_axioms:
                    # Only include PRECONDITION and POSTCONDITION for relevance
                    axiom_type = axiom.axiom_type.value if axiom.axiom_type else ""
                    if axiom_type.upper() in ("PRECONDITION", "POSTCONDITION", "INVARIANT"):
                        axioms_by_line[line].append({
                            "line": line,
                            "callee": callee,
                            "type": axiom_type,
                            "content": axiom.content,
                            "formal": axiom.formal_spec if config.get("show_formal") else None,
                        })

        # Flatten and limit
        all_axioms = []
        for line in sorted(axioms_by_line.keys()):
            all_axioms.extend(axioms_by_line[line])

        # Apply limit for comprehensive mode
        max_axioms = config.get("max_axioms", 30)
        if len(all_axioms) > max_axioms:
            all_axioms = all_axioms[:max_axioms]

        return all_axioms

    except Exception as e:
        # Silently fail - don't break Claude's workflow
        return []


def format_axioms(file_path: str, axioms: list[dict], start_line: int | None, end_line: int | None) -> str:
    """Format axioms for output."""
    if not axioms:
        return ""

    lines = ["## Axiom Context", ""]

    # Header with file and line range
    filename = os.path.basename(file_path)
    if start_line is not None and end_line is not None:
        lines.append(f"### {filename} (lines {start_line}-{end_line})")
    else:
        lines.append(f"### {filename}")
    lines.append("")

    # Group by line
    current_line = None
    for axiom in axioms:
        line = axiom["line"]
        if line != current_line:
            current_line = line

        callee = axiom["callee"]
        content = axiom["content"]
        axiom_type = axiom["type"]

        # Truncate long content
        if len(content) > 100:
            content = content[:97] + "..."

        lines.append(f"- **L{line}** `{callee}` [{axiom_type}]: {content}")

    lines.append("")
    lines.append(f"*{len(axioms)} axiom(s) relevant to this code*")

    return "\n".join(lines)


def main():
    """Main hook entry point."""
    # Read context from stdin
    try:
        context = json.load(sys.stdin)
    except json.JSONDecodeError:
        # No valid JSON context, nothing to do
        sys.exit(0)

    # Load configuration
    config = load_config()

    # Find C++ files in context
    cpp_files = find_cpp_files_in_context(context)

    if not cpp_files:
        # No C++ files, nothing to inject
        sys.exit(0)

    # Get axioms for each file
    output_parts = []
    for file_path, start_line, end_line in cpp_files:
        # In selection mode, skip files without line selection
        if config.get("mode") == "selection" and start_line is None:
            continue

        axioms = get_axioms_for_file(file_path, start_line, end_line, config)
        if axioms:
            formatted = format_axioms(file_path, axioms, start_line, end_line)
            if formatted:
                output_parts.append(formatted)

    # Output to stdout for injection
    if output_parts:
        print("\n\n".join(output_parts))

    sys.exit(0)


if __name__ == "__main__":
    main()
