// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2026 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "HoverProvider.h"

#include <sstream>

namespace axiom {

HoverProvider::HoverProvider(QueryClient& client)
    : client_(client) {}

std::string HoverProvider::getHoverContent(const std::string& symbol) {
    return getHoverContentMultiple({symbol});
}

std::string HoverProvider::getHoverContentMultiple(const std::vector<std::string>& symbols) {
    auto results = client_.query(symbols);

    if (results.empty()) {
        return "";
    }

    std::ostringstream ss;

    for (const auto& symbol_axioms : results) {
        if (symbol_axioms.axioms.empty()) {
            continue;
        }

        ss << formatAxiomTree(symbol_axioms);
        ss << "\n";
    }

    return ss.str();
}

std::string HoverProvider::formatAxiomTree(const SymbolAxioms& symbol_axioms) {
    std::ostringstream ss;

    // Header with symbol name
    ss << "## `" << symbol_axioms.symbol << "`\n\n";

    // Layer indicator
    if (symbol_axioms.layer == "live") {
        ss << "*Live extraction*\n\n";
    } else if (symbol_axioms.layer == "both") {
        ss << "*Static + Live*\n\n";
    }

    // Group axioms by type
    std::vector<const AxiomResult*> preconditions;
    std::vector<const AxiomResult*> postconditions;
    std::vector<const AxiomResult*> effects;
    std::vector<const AxiomResult*> exceptions;
    std::vector<const AxiomResult*> constraints;
    std::vector<const AxiomResult*> other;

    for (const auto& axiom : symbol_axioms.axioms) {
        if (axiom.axiom_type == "precondition") {
            preconditions.push_back(&axiom);
        } else if (axiom.axiom_type == "postcondition") {
            postconditions.push_back(&axiom);
        } else if (axiom.axiom_type == "effect") {
            effects.push_back(&axiom);
        } else if (axiom.axiom_type == "exception") {
            exceptions.push_back(&axiom);
        } else if (axiom.axiom_type == "constraint") {
            constraints.push_back(&axiom);
        } else {
            other.push_back(&axiom);
        }
    }

    // Format each section
    auto formatSection = [&](const char* title,
                             const std::vector<const AxiomResult*>& axioms) {
        if (axioms.empty()) return;
        ss << "### " << title << "\n";
        for (const auto* axiom : axioms) {
            ss << formatAxiom(*axiom);
        }
        ss << "\n";
    };

    formatSection("Preconditions", preconditions);
    formatSection("Postconditions", postconditions);
    formatSection("Effects", effects);
    formatSection("Exceptions", exceptions);
    formatSection("Constraints", constraints);
    formatSection("Other", other);

    // Show grounded-in section if any axiom has proof chain
    bool has_proof_chain = false;
    for (const auto& axiom : symbol_axioms.axioms) {
        if (!axiom.proof_chain.empty()) {
            has_proof_chain = true;
            break;
        }
    }

    if (has_proof_chain) {
        ss << "### Grounded In\n";
        for (const auto& axiom : symbol_axioms.axioms) {
            if (!axiom.proof_chain.empty()) {
                ss << formatProofChain(axiom.proof_chain);
            }
        }
        ss << "\n";
    }

    // Show pairs section if any axiom has pairs
    std::vector<std::string> all_pairs;
    for (const auto& axiom : symbol_axioms.axioms) {
        for (const auto& pair : axiom.pairs_with) {
            // Avoid duplicates
            if (std::find(all_pairs.begin(), all_pairs.end(), pair) == all_pairs.end()) {
                all_pairs.push_back(pair);
            }
        }
    }

    if (!all_pairs.empty()) {
        ss << "### Pairs With\n";
        for (const auto& pair : all_pairs) {
            ss << "- `" << pair << "`\n";
        }
    }

    return ss.str();
}

std::string HoverProvider::formatAxiom(const AxiomResult& axiom) {
    std::ostringstream ss;

    // Bullet with axiom ID and confidence
    ss << "- **" << axiom.id << "** (conf: "
       << static_cast<int>(axiom.confidence * 100) << "%)\n";

    // Content
    ss << "  > " << axiom.content << "\n";

    // Formal spec if available
    if (!axiom.formal_spec.empty() && axiom.formal_spec != "true") {
        ss << "  > `" << axiom.formal_spec << "`\n";
    }

    return ss.str();
}

std::string HoverProvider::formatProofChain(const std::vector<nlohmann::json>& chain) {
    std::ostringstream ss;

    for (const auto& step : chain) {
        std::string id = step.value("id", "unknown");
        std::string layer = step.value("layer", "");

        ss << "- `" << id << "`";
        if (!layer.empty()) {
            ss << " [" << layer << "]";
        }
        ss << "\n";
    }

    return ss.str();
}

} // namespace axiom
