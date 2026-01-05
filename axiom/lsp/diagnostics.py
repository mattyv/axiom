# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Convert axioms to LSP diagnostics.

Two diagnostic sources are emitted:
- axiom-context (Hint): Informational context for LLMs, shows all axioms
- axiom (Warning): Actionable warnings for hazards/violations

The mode parameter controls filtering:
- "default"/"llm": Emit both sources
- "human": Suppress axiom-context, only emit warnings
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from lsprotocol.types import Diagnostic, DiagnosticSeverity, Position, Range

if TYPE_CHECKING:
    from axiom.lsp.call_sites import CallSiteIndex
    from axiom.models import Axiom


DiagnosticMode = Literal["default", "llm", "human"]


def axiom_to_diagnostics(
    axiom: Axiom,
    mode: DiagnosticMode = "default",
) -> list[Diagnostic]:
    """Convert an axiom to LSP diagnostics.

    Args:
        axiom: The axiom to convert.
        mode: Diagnostic mode. "human" suppresses context hints.

    Returns:
        List of LSP Diagnostic objects.
    """
    diagnostics: list[Diagnostic] = []

    # Calculate line (LSP uses 0-indexed lines)
    line = (axiom.source.line_start or 1) - 1

    # Create range - use whole line since we don't have column info
    range_ = Range(
        start=Position(line=line, character=0),
        end=Position(line=line, character=999),
    )

    # Format message
    function_name = axiom.function or "unknown"
    axiom_type = axiom.axiom_type.value.upper() if axiom.axiom_type else "AXIOM"
    message = f"{function_name} — {axiom_type}: {axiom.content}"

    # Emit axiom-context diagnostic (informational, for LLM context)
    if mode in ("default", "llm"):
        diagnostics.append(
            Diagnostic(
                range=range_,
                message=message,
                severity=DiagnosticSeverity.Information,
                source="axiom-context",
                code=axiom.id,
            )
        )

    # TODO: Emit axiom warning diagnostic for hazards/violations
    # This would be based on axiom.on_violation or specific axiom types

    return diagnostics


def axioms_to_diagnostics(
    axioms: list[Axiom],
    mode: DiagnosticMode = "default",
) -> list[Diagnostic]:
    """Convert multiple axioms to LSP diagnostics.

    Args:
        axioms: List of axioms to convert.
        mode: Diagnostic mode. "human" suppresses context hints.

    Returns:
        Combined list of LSP Diagnostic objects.
    """
    diagnostics: list[Diagnostic] = []
    for axiom in axioms:
        diagnostics.extend(axiom_to_diagnostics(axiom, mode=mode))
    return diagnostics


from typing import Callable

AxiomLookup = Callable[[str], list["Axiom"]]


def call_site_diagnostics(
    file_path: str,
    index: CallSiteIndex,
    axiom_lookup: AxiomLookup,
    mode: DiagnosticMode = "default",
) -> list[Diagnostic]:
    """Generate diagnostics at call sites.

    For each call site, emit diagnostics for the callee's axioms
    at the call line (not the definition line).

    Args:
        file_path: Source file path.
        index: CallSiteIndex with call graph data.
        axiom_lookup: Callable that takes callee name and returns axioms.
        mode: Diagnostic mode. "human" suppresses context hints.

    Returns:
        List of LSP Diagnostic objects at call site lines.
    """
    if mode == "human":
        return []

    diagnostics: list[Diagnostic] = []

    # Get all lines with calls in this file
    file_index = index._index.get(file_path, {})

    for line, calls in file_index.items():
        for call in calls:
            callee = call.get("callee")
            if not callee:
                continue

            # Get axioms for this callee (by function name or tags)
            callee_axioms = axiom_lookup(callee)

            # Create range at call site line (LSP is 0-indexed)
            range_ = Range(
                start=Position(line=line - 1, character=0),
                end=Position(line=line - 1, character=999),
            )

            for axiom in callee_axioms:
                axiom_type = axiom.axiom_type.value.upper() if axiom.axiom_type else "AXIOM"
                message = f"{callee} — {axiom_type}: {axiom.content}"

                diagnostics.append(
                    Diagnostic(
                        range=range_,
                        message=message,
                        severity=DiagnosticSeverity.Information,
                        source="axiom-context",
                        code=axiom.id,
                    )
                )

    return diagnostics
