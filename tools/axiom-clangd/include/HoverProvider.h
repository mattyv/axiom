// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2026 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#pragma once

#include "QueryClient.h"

#include <string>
#include <vector>

namespace axiom {

/// Provides hover content for axioms.
class HoverProvider {
public:
    /// Create provider with query client.
    explicit HoverProvider(QueryClient& client);

    /// Generate hover content for a symbol.
    /// @param symbol Qualified function name.
    /// @return Markdown-formatted hover content.
    std::string getHoverContent(const std::string& symbol);

    /// Generate hover content for multiple symbols (e.g., all on a line).
    /// @param symbols List of qualified function names.
    /// @return Markdown-formatted hover content for all symbols.
    std::string getHoverContentMultiple(const std::vector<std::string>& symbols);

private:
    QueryClient& client_;

    /// Format axiom tree as markdown.
    /// @param symbol_axioms Axioms for a symbol.
    /// @return Markdown string.
    static std::string formatAxiomTree(const SymbolAxioms& symbol_axioms);

    /// Format a single axiom as markdown.
    /// @param axiom The axiom result.
    /// @return Markdown string.
    static std::string formatAxiom(const AxiomResult& axiom);

    /// Format proof chain as markdown.
    /// @param chain The proof chain (list of axiom nodes).
    /// @return Markdown string.
    static std::string formatProofChain(const std::vector<nlohmann::json>& chain);
};

} // namespace axiom
