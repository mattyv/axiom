// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2026 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "DiagnosticEmitter.h"

#include <sstream>

namespace axiom {

DiagnosticEmitter::DiagnosticEmitter(QueryClient& client)
    : client_(client) {}

std::vector<AxiomDiagnostic> DiagnosticEmitter::generateDiagnostics(
    const std::vector<std::pair<std::string, clang::SourceLocation>>& symbols) {

    std::vector<AxiomDiagnostic> diagnostics;

    // Collect all symbol names for batch query
    std::vector<std::string> symbol_names;
    symbol_names.reserve(symbols.size());
    for (const auto& [name, _] : symbols) {
        symbol_names.push_back(name);
    }

    // Query axioms for all symbols
    auto results = client_.query(symbol_names);

    // Generate diagnostics for each symbol
    for (size_t i = 0; i < results.size() && i < symbols.size(); ++i) {
        const auto& symbol_axioms = results[i];
        const auto& location = symbols[i].second;

        for (const auto& axiom : symbol_axioms.axioms) {
            // Determine if this is a warning (hazard) or context (info)
            bool is_warning = (axiom.axiom_type == "precondition" ||
                              axiom.axiom_type == "anti_pattern");

            if (is_warning) {
                diagnostics.push_back(createWarningDiagnostic(axiom, location));
            }

            // Always emit context diagnostic (for LLM visibility)
            diagnostics.push_back(createContextDiagnostic(axiom, location));
        }
    }

    return diagnostics;
}

std::string DiagnosticEmitter::formatAxiomMessage(
    const AxiomResult& axiom,
    bool include_chain) {

    std::ostringstream ss;

    // Main axiom info
    ss << axiom.function << " — ";

    // Type prefix
    if (!axiom.axiom_type.empty()) {
        std::string type_upper = axiom.axiom_type;
        for (auto& c : type_upper) c = std::toupper(c);
        ss << type_upper << ": ";
    }

    ss << axiom.content;

    // Confidence
    ss << " (conf: " << static_cast<int>(axiom.confidence * 100) << "%)";

    // Dependency chain (for LLM context)
    if (include_chain && !axiom.proof_chain.empty()) {
        ss << "\n    Grounded in:";
        for (const auto& step : axiom.proof_chain) {
            if (step.contains("id")) {
                ss << "\n      - " << step["id"].get<std::string>();
            }
        }
    }

    // Paired functions
    if (!axiom.pairs_with.empty()) {
        ss << "\n    Pairs with:";
        for (const auto& pair : axiom.pairs_with) {
            ss << " " << pair;
        }
    }

    return ss.str();
}

AxiomDiagnostic DiagnosticEmitter::createWarningDiagnostic(
    const AxiomResult& axiom,
    clang::SourceLocation location) {

    AxiomDiagnostic diag;
    diag.location = location;
    diag.severity = DiagnosticSeverity::Warning;
    diag.message = formatAxiomMessage(axiom, false);  // Brief for warning
    diag.source = "axiom";
    diag.axiom_id = axiom.id;
    return diag;
}

AxiomDiagnostic DiagnosticEmitter::createContextDiagnostic(
    const AxiomResult& axiom,
    clang::SourceLocation location) {

    AxiomDiagnostic diag;
    diag.location = location;
    diag.severity = DiagnosticSeverity::Hint;
    diag.message = formatAxiomMessage(axiom, true);  // Full chain for context
    diag.source = "axiom-context";
    diag.axiom_id = axiom.id;
    return diag;
}

} // namespace axiom
