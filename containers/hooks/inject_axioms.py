#!/usr/bin/env python3
"""Claude Code hook to inject axiom context for C++ files (container version).

This hook runs on:
- PostToolUse (Write/Edit): injects axioms for C++ files Claude just wrote/edited

This version calls the axiom container via podman exec.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

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
    "in_keys(", "Debug()", "isLinkerLoc", "fileScope", "in Opts",
    "NoNativeFallback", "isNativeLoc", "isBlockScope", "isMainScope",
    "ExtTypes", "caseLabel(", "SwitchNum", "popLocals", "structOrUnionAtTop",
    "isInFieldInit", "isAtIndexInit", "byteAlignofType", "wstring(",
    "ordChar(", "lengthString(", "=/=String", "==String", "isSign(",
    "isDigit(", "isCPP", "isPRExpr", "isAggregateOrUnionType", "handlerMatches",
    "FOffset", "isInt(V)", "expression is held for evaluation",
    "hasRestrict(", "RestrictStack", "RestrictBlocks", "isRestrictConflict",
    "Tag in Restrict", "Restrict",
    "MainTU", ".K", ".List", "#NoName", "emptyValue", "ThreadId",
    "isNCLHold", "isThreadDuration", "isAutoDuration", "Loc in Locs",
    "is a held rvalue", "is not held", "expression is not held",
    "isVariableLengthArrayType", "isVariablyModifiedType", "isFunctionType(",
    "Requires: \n", "Requires: ", "≠ \"\"", "≠ variadic", "≠ \"builtin\"",
    "value is not a memory location", "SizeofExpression(",
    "StorageClass", "storageClass", "getStorageSpecifiers", "getQualifiers",
    "validLocalStorageClass", "validGlobalStorageClass", "validPrototypeStorageClass",
    "noQuals", "isFileScope", "areDeclCompat",
    "controlAtTop", "noMoreFields",
    "wide character type", "character type", "character string literals",
    "size(S) ==Int", "size(S) <",
    "is a null pointer constant, and operand is a pointer type",
    "Offset ≤ Sz",
    "B =/=Int", "I =/=Int", "N ==Int", "I ==Int", "W ==Int", "V =/=Int",
    "J =/=Int", "=/=Int 0", "==Int 0", "==Int -1", "==Int Size", "==Int min(",
    "Execution()", "isEvalVal(", "referenceBindingResult(",
    "#arePromotedTypesCompat", "isFlexibleType", "utype(", "getParams(T)",
    "isShortCircuit(", "isInt(value(",
    "O ≠ operator", "O = operator", "one of: O =",
    "operand types must match", "operand types differ",
    "Comparison requires:",
    "fromArray(", "isFromArray(", ":/=K", ":=K", "isType(T)",
    "N =/=Int min(T)", "value is indeterminate",
    "...",
]


def is_internal_axiom(content: str) -> bool:
    """Check if axiom content contains internal K Framework symbols."""
    return any(pattern in content for pattern in INTERNAL_PATTERNS)


def load_config() -> dict:
    """Load hook configuration."""
    config_path = Path(__file__).parent / "config.toml"
    defaults = {
        "mode": "edit",
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

        start_pos = content.find(new_string)
        if start_pos == -1:
            return None, None

        start_line = content[:start_pos].count("\n") + 1
        end_line = start_line + new_string.count("\n")

        return start_line, end_line
    except Exception:
        return None, None


def find_cpp_files_in_context(context: dict, mode: str = "edit") -> list[tuple[str, int | None, int | None]]:
    """Find C++ files mentioned in the conversation context."""
    files = []

    tool_input = context.get("tool_input", {})
    if tool_input:
        file_path = tool_input.get("file_path", "")
        if file_path and any(file_path.endswith(ext) for ext in CPP_EXTENSIONS):
            if os.path.exists(file_path):
                start_line, end_line = None, None

                if mode == "edit":
                    new_string = tool_input.get("new_string", "")
                    content = tool_input.get("content", "")

                    if new_string:
                        start_line, end_line = find_edited_lines(file_path, new_string)
                    elif content:
                        line_count = content.count("\n") + 1
                        start_line, end_line = 1, line_count

                files.append((file_path, start_line, end_line))

    prompt = context.get("prompt", "")

    ide_selection_pattern = r"<ide_selection>.*?/([^/\n]+\.(cpp|cc|cxx|c|hpp|hh|hxx|h)).*?lines?\s*(\d+)\s*(?:to|-)\s*(\d+)"
    for match in re.finditer(ide_selection_pattern, prompt, re.IGNORECASE | re.DOTALL):
        filename = match.group(1)
        start = int(match.group(3))
        end = int(match.group(4))
        full_path = find_file_path(filename)
        if full_path:
            files.append((full_path, start, end))

    file_pattern = r'(?:^|[\s"`\'(])(/[^\s"`\')\n]+\.(?:cpp|cc|cxx|c|hpp|hh|hxx|h))(?:[\s"`\'):]|$)'
    for match in re.finditer(file_pattern, prompt, re.MULTILINE):
        path = match.group(1)
        if os.path.exists(path) and (path, None, None) not in files:
            files.append((path, None, None))

    return files


def find_file_path(filename: str) -> str | None:
    """Find full path for a filename."""
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename

    cwd = os.getcwd()
    project_path = Path(cwd) / filename
    if project_path.exists():
        return str(project_path)

    for subdir in ["examples", "src", "include", "tests"]:
        path = Path(cwd) / subdir / filename
        if path.exists():
            return str(path)

    return None


def get_axioms_via_container(
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    config: dict = None,
) -> list[dict]:
    """Get axioms for a C++ file by calling the container."""
    config = config or {}

    try:
        # Build the Python code to run inside the container
        python_code = f'''
import json
from axiom.lsp.server import AxiomLanguageServer

file_path = "{file_path}"
start_line = {start_line if start_line is not None else 'None'}
end_line = {end_line if end_line is not None else 'None'}
show_formal = {config.get('show_formal', False)}
max_axioms = {config.get('max_axioms', 30)}

server = AxiomLanguageServer()
collection, call_graph = server._extractor.extract_file_with_call_graph(file_path)

if not call_graph:
    print(json.dumps([]))
else:
    if start_line is not None and end_line is not None:
        call_graph = [c for c in call_graph if start_line <= c.get("line", 0) <= end_line]

    axioms_by_line = {{}}
    for call in call_graph:
        line = call.get("line", 0)
        callee = call.get("callee", "")
        signature = call.get("callee_signature")

        if not callee:
            continue

        callee_axioms = server.get_axioms_for_callee(callee, signature)
        if callee_axioms:
            if line not in axioms_by_line:
                axioms_by_line[line] = []

            for axiom in callee_axioms:
                axiom_type = axiom.axiom_type.value if axiom.axiom_type else ""
                if axiom_type and axiom_type.upper() not in ("PRECONDITION", "POSTCONDITION", "INVARIANT"):
                    continue

                axioms_by_line[line].append({{
                    "line": line,
                    "callee": callee,
                    "type": axiom_type,
                    "content": axiom.content or "",
                    "formal": axiom.formal_spec if show_formal else None,
                }})

    all_axioms = []
    for line in sorted(axioms_by_line.keys()):
        all_axioms.extend(axioms_by_line[line])

    if len(all_axioms) > max_axioms:
        all_axioms = all_axioms[:max_axioms]

    print(json.dumps(all_axioms))
'''

        # Run in the container
        result = subprocess.run(
            ["podman", "exec", "-i", "axiom-app", "python", "-c", python_code],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            log_debug(f"Container error: {result.stderr}")
            return []

        axioms = json.loads(result.stdout.strip())

        # Filter internal axioms
        return [a for a in axioms if not is_internal_axiom(a.get("content", ""))]

    except subprocess.TimeoutExpired:
        log_debug("Container timeout")
        return []
    except Exception as e:
        log_debug(f"Error getting axioms: {e}")
        return []


def format_axioms(file_path: str, axioms: list[dict], start_line: int | None, end_line: int | None) -> str:
    """Format axioms for output."""
    if not axioms:
        return ""

    lines = ["## Axiom Context", ""]

    filename = os.path.basename(file_path)
    if start_line is not None and end_line is not None:
        lines.append(f"### {filename} (lines {start_line}-{end_line})")
    else:
        lines.append(f"### {filename}")
    lines.append("")

    current_line = None
    for axiom in axioms:
        line = axiom["line"]
        if line != current_line:
            current_line = line

        callee = axiom["callee"]
        content = axiom["content"]
        axiom_type = axiom["type"]

        if len(content) > 100:
            content = content[:97] + "..."

        lines.append(f"- **L{line}** `{callee}` [{axiom_type}]: {content}")

    lines.append("")
    lines.append(f"*{len(axioms)} axiom(s) relevant to this code*")

    return "\n".join(lines)


def main():
    """Main hook entry point."""
    log_debug("=== Container Hook triggered ===")

    # Check if container is running
    result = subprocess.run(
        ["podman", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    if "axiom-app" not in result.stdout:
        log_debug("Container not running, exiting")
        sys.exit(0)

    try:
        stdin_data = sys.stdin.read()
        log_debug(f"stdin length: {len(stdin_data)}")
        if not stdin_data.strip():
            sys.exit(0)
        context = json.loads(stdin_data)
    except Exception as e:
        log_debug(f"Error reading stdin: {e}")
        sys.exit(0)

    is_post_tool_use = "tool_input" in context

    config = load_config()
    mode = config.get("mode", "edit")

    cpp_files = find_cpp_files_in_context(context, mode)

    if not cpp_files:
        sys.exit(0)

    output_parts = []
    for file_path, start_line, end_line in cpp_files:
        log_debug(f"Processing {file_path} lines {start_line}-{end_line}")

        if mode in ("selection", "edit") and start_line is None:
            log_debug(f"  Skipping - no line range in {mode} mode")
            continue

        axioms = get_axioms_via_container(file_path, start_line, end_line, config)
        log_debug(f"  Found {len(axioms)} axioms")
        if axioms:
            formatted = format_axioms(file_path, axioms, start_line, end_line)
            if formatted:
                output_parts.append(formatted)

    if output_parts:
        axiom_context = "\n\n".join(output_parts)
        log_debug(f"Outputting {len(output_parts)} formatted sections")

        if is_post_tool_use:
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": axiom_context
                }
            }
            print(json.dumps(output))
        else:
            print(axiom_context)
    else:
        log_debug("No axioms to output")

    sys.exit(0)


if __name__ == "__main__":
    main()
