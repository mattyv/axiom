#!/usr/bin/env python3
"""Claude Code hook to inject axiom context for C++ files.

This hook runs on:
- PostToolUse (Write/Edit): injects axioms for C++ files Claude just wrote/edited
"""

import json
import os
import re
import sys
from pathlib import Path

# Determine project directory - prefer CLAUDE_PROJECT_DIR env var
PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).parent.parent.parent))
sys.path.insert(0, str(PROJECT_DIR))

# Debug log file
DEBUG_LOG = Path("/tmp/axiom_hook_debug.log")


def log_debug(msg: str):
    """Write debug message to log file."""
    import datetime
    with open(DEBUG_LOG, "a") as f:
        f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")

# C++ file extensions
CPP_EXTENSIONS = {".cpp", ".cc", ".cxx", ".c", ".hpp", ".hh", ".hxx", ".h"}

# Internal K Framework patterns to filter out (not useful for developers)
INTERNAL_PATTERNS = [
    # K Framework internal state
    "in_keys(", "Debug()", "isLinkerLoc", "fileScope", "in Opts",
    "NoNativeFallback", "isNativeLoc", "isBlockScope", "isMainScope",
    "ExtTypes", "caseLabel(", "SwitchNum", "popLocals", "structOrUnionAtTop",
    "isInFieldInit", "isAtIndexInit", "byteAlignofType", "wstring(",
    "ordChar(", "lengthString(", "=/=String", "==String", "isSign(",
    "isDigit(", "isCPP", "isPRExpr", "isAggregateOrUnionType", "handlerMatches",
    "FOffset", "isInt(V)", "expression is held for evaluation",
    # Restrict qualifier internals
    "hasRestrict(", "RestrictStack", "RestrictBlocks", "isRestrictConflict",
    "Tag in Restrict", "Restrict",
    # Internal state markers
    "MainTU", ".K", ".List", "#NoName", "emptyValue", "ThreadId",
    "isNCLHold", "isThreadDuration", "isAutoDuration", "Loc in Locs",
    # Held expression internals
    "is a held rvalue", "is not held", "expression is not held",
    # Type checking internals (not actionable)
    "isVariableLengthArrayType", "isVariablyModifiedType", "isFunctionType(",
    # Empty/trivial conditions
    "Requires: \n", "Requires: ", "≠ \"\"", "≠ variadic", "≠ \"builtin\"",
    # Memory location internals
    "value is not a memory location", "SizeofExpression(",
    # Storage class and qualifier internals
    "StorageClass", "storageClass", "getStorageSpecifiers", "getQualifiers",
    "validLocalStorageClass", "validGlobalStorageClass", "validPrototypeStorageClass",
    "noQuals", "isFileScope", "areDeclCompat",
    # Control flow internals
    "controlAtTop", "noMoreFields",
    # Character/string type internals (not safety-critical)
    "wide character type", "character type", "character string literals",
    "size(S) ==Int", "size(S) <",
    # Null pointer when not relevant to the operation
    "is a null pointer constant, and operand is a pointer type",
    # Offset internals
    "Offset ≤ Sz",
    # K Framework variable comparisons (cryptic single-letter vars)
    "B =/=Int", "I =/=Int", "N ==Int", "I ==Int", "W ==Int", "V =/=Int",
    "J =/=Int", "=/=Int 0", "==Int 0", "==Int -1", "==Int Size", "==Int min(",
    # K Framework execution state
    "Execution()", "isEvalVal(", "referenceBindingResult(",
    # K Framework type internals
    "#arePromotedTypesCompat", "isFlexibleType", "utype(", "getParams(T)",
    "isShortCircuit(", "isInt(value(",
    # Generic operator constraints (not actionable)
    "O ≠ operator", "O = operator", "one of: O =",
    "operand types must match", "operand types differ",
    # Comparison internals
    "Comparison requires:",
    # More K Framework internals
    "fromArray(", "isFromArray(", ":/=K", ":=K", "isType(T)",
    "N =/=Int min(T)", "value is indeterminate",
    # Truncated axioms (not useful)
    "...",
]


def is_internal_axiom(content: str) -> bool:
    """Check if axiom content contains internal K Framework symbols."""
    return any(pattern in content for pattern in INTERNAL_PATTERNS)


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


def find_edited_lines(file_path: str, new_string: str) -> tuple[int | None, int | None]:
    """Find the line range where new_string appears in the file."""
    if not new_string or not os.path.exists(file_path):
        return None, None

    try:
        with open(file_path, "r") as f:
            content = f.read()

        # Find where new_string starts in the file
        start_pos = content.find(new_string)
        if start_pos == -1:
            return None, None

        # Count lines
        start_line = content[:start_pos].count("\n") + 1
        end_line = start_line + new_string.count("\n")

        return start_line, end_line
    except Exception:
        return None, None


def find_cpp_files_in_context(context: dict, mode: str = "comprehensive") -> list[tuple[str, int | None, int | None]]:
    """Find C++ files mentioned in the conversation context.

    Returns list of (file_path, start_line, end_line) tuples.
    start_line/end_line are None if no specific selection.
    """
    files = []

    # Check for PostToolUse context (Write/Edit tool)
    tool_input = context.get("tool_input", {})
    if tool_input:
        file_path = tool_input.get("file_path", "")
        if file_path and any(file_path.endswith(ext) for ext in CPP_EXTENSIONS):
            if os.path.exists(file_path):
                start_line, end_line = None, None

                # In edit mode, find the lines that were edited
                if mode == "edit":
                    # Edit tool uses new_string, Write tool uses content
                    new_string = tool_input.get("new_string", "")
                    content = tool_input.get("content", "")

                    if new_string:
                        start_line, end_line = find_edited_lines(file_path, new_string)
                    elif content:
                        # For Write, analyze the whole file
                        line_count = content.count("\n") + 1
                        start_line, end_line = 1, line_count

                files.append((file_path, start_line, end_line))

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
            signature = call.get("callee_signature")  # For semantic search

            if not callee:
                continue

            # Get axioms for this callee (uses semantic search if signature available)
            callee_axioms = server.get_axioms_for_callee(callee, signature)

            if callee_axioms:
                if line not in axioms_by_line:
                    axioms_by_line[line] = []

                for axiom in callee_axioms:
                    # Include PRECONDITION, POSTCONDITION, INVARIANT, or untyped axioms
                    # (untyped axioms are language semantics rules from C++ spec)
                    axiom_type = axiom.axiom_type.value if axiom.axiom_type else ""
                    if axiom_type and axiom_type.upper() not in ("PRECONDITION", "POSTCONDITION", "INVARIANT"):
                        continue

                    # Filter out internal K Framework axioms
                    content = axiom.content or ""
                    if is_internal_axiom(content):
                        continue

                    axioms_by_line[line].append({
                        "line": line,
                        "callee": callee,
                        "type": axiom_type,
                        "content": content,
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
        # Log error but don't break Claude's workflow
        log_debug(f"Error getting axioms for {file_path}: {e}")
        import traceback
        log_debug(traceback.format_exc())
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
    log_debug("=== Hook triggered ===")
    log_debug(f"CWD: {os.getcwd()}")
    log_debug(f"PROJECT_DIR: {PROJECT_DIR}")
    log_debug(f"CLAUDE_PROJECT_DIR env: {os.environ.get('CLAUDE_PROJECT_DIR', 'not set')}")

    # Read context from stdin
    try:
        stdin_data = sys.stdin.read()
        log_debug(f"stdin length: {len(stdin_data)}")
        if not stdin_data.strip():
            log_debug("Empty stdin, exiting")
            sys.exit(0)
        context = json.loads(stdin_data)
        log_debug(f"Context keys: {list(context.keys())}")
        if "tool_input" in context:
            log_debug(f"tool_input: {json.dumps(context['tool_input'])[:200]}")
    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        sys.exit(0)
    except Exception as e:
        log_debug(f"Error reading stdin: {e}")
        sys.exit(0)

    # Determine if this is a PostToolUse hook (has tool_input) or UserPromptSubmit
    is_post_tool_use = "tool_input" in context

    # Load configuration
    config = load_config()
    mode = config.get("mode", "edit")

    # Find C++ files in context
    cpp_files = find_cpp_files_in_context(context, mode)

    if not cpp_files:
        # No C++ files, nothing to inject
        sys.exit(0)

    # Get axioms for each file
    output_parts = []
    for file_path, start_line, end_line in cpp_files:
        log_debug(f"Processing {file_path} lines {start_line}-{end_line}")

        # In selection/edit mode, skip files without line range
        if mode in ("selection", "edit") and start_line is None:
            log_debug(f"  Skipping - no line range in {mode} mode")
            continue

        axioms = get_axioms_for_file(file_path, start_line, end_line, config)
        log_debug(f"  Found {len(axioms)} axioms")
        if axioms:
            formatted = format_axioms(file_path, axioms, start_line, end_line)
            if formatted:
                output_parts.append(formatted)

    # Output to stdout for injection
    if output_parts:
        axiom_context = "\n\n".join(output_parts)
        log_debug(f"Outputting {len(output_parts)} formatted sections")

        if is_post_tool_use:
            # PostToolUse requires JSON with additionalContext for Claude to see it
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": axiom_context
                }
            }
            print(json.dumps(output))
        else:
            # UserPromptSubmit can use plain text
            print(axiom_context)
    else:
        log_debug("No axioms to output")

    sys.exit(0)


if __name__ == "__main__":
    main()
