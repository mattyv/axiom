// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2026 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#pragma once

#include "QueryClient.h"

#include <clang/Basic/Diagnostic.h>
#include <clang/Basic/SourceLocation.h>
#include <string>
#include <vector>

namespace axiom {

/// Diagnostic severity levels matching LSP.
enum class DiagnosticSeverity {
    Error = 1,
    Warning = 2,
    Information = 3,
    Hint = 4
};

/// A diagnostic to emit.
struct AxiomDiagnostic {
    clang::SourceLocation location;
    DiagnosticSeverity severity;
    std::string message;
    std::string source;  // "axiom" or "axiom-context"
    std::string axiom_id;  // For cross-reference with MCP
};

/// Emits diagnostics for axiom context and warnings.
class DiagnosticEmitter {
public:
    /// Create emitter with query client.
    explicit DiagnosticEmitter(QueryClient& client);

    /// Generate diagnostics for symbols at given locations.
    /// @param symbols Map of symbol name -> source location.
    /// @return List of diagnostics to emit.
    std::vector<AxiomDiagnostic> generateDiagnostics(
        const std::vector<std::pair<std::string, clang::SourceLocation>>& symbols);

    /// Format a single axiom as diagnostic message.
    /// @param axiom The axiom result.
    /// @param include_chain Whether to include dependency chain (for LLM mode).
    /// @return Formatted message string.
    static std::string formatAxiomMessage(
        const AxiomResult& axiom,
        bool include_chain = true);

private:
    QueryClient& client_;

    /// Create warning diagnostic for hazard/violation.
    AxiomDiagnostic createWarningDiagnostic(
        const AxiomResult& axiom,
        clang::SourceLocation location);

    /// Create context diagnostic (hint) for axiom info.
    AxiomDiagnostic createContextDiagnostic(
        const AxiomResult& axiom,
        clang::SourceLocation location);
};

} // namespace axiom
