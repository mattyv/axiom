// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "Axiom.h"

#include <clang/Lex/MacroInfo.h>
#include <clang/Lex/PPCallbacks.h>
#include <clang/Lex/Preprocessor.h>
#include <regex>
#include <set>

namespace axiom {

// Analyze macro body for hazardous operations
void analyzeMacroBody(const std::string& body, MacroDefinition& macro) {
    // Division: / not followed by / or * (avoid comments)
    std::regex divRegex(R"([^/]/[^/*]|%)");
    macro.has_division = std::regex_search(body, divRegex);

    // Pointer operations: * or & followed by identifier
    std::regex ptrRegex(R"(\*[a-zA-Z_]|&[a-zA-Z_])");
    macro.has_pointer_ops = std::regex_search(body, ptrRegex);

    // Cast expressions: (type) or (type*)
    std::regex castRegex(R"(\([a-zA-Z_][a-zA-Z_0-9]*\s*\*?\s*\))");
    macro.has_casts = std::regex_search(body, castRegex);

    // Function calls: identifier followed by (
    std::regex funcRegex(R"(\b([a-z_][a-zA-Z_0-9]*)\s*\()");
    std::smatch match;
    std::string::const_iterator searchStart = body.cbegin();
    std::set<std::string> keywords = {"if", "while", "for", "switch", "sizeof", "typeof", "alignof"};

    while (std::regex_search(searchStart, body.cend(), match, funcRegex)) {
        std::string funcName = match[1].str();
        if (keywords.find(funcName) == keywords.end()) {
            macro.function_calls.push_back(funcName);
        }
        searchStart = match.suffix().first;
    }

    // Macro references: UPPERCASE identifiers (3+ chars)
    std::regex macroRefRegex(R"(\b([A-Z_][A-Z_0-9]{2,})\b)");
    searchStart = body.cbegin();
    while (std::regex_search(searchStart, body.cend(), match, macroRefRegex)) {
        macro.referenced_macros.push_back(match[1].str());
        searchStart = match.suffix().first;
    }
}

// PPCallbacks implementation to capture macro definitions
class MacroPPCallbacks : public clang::PPCallbacks {
public:
    MacroPPCallbacks(clang::SourceManager& sm, std::vector<MacroDefinition>& macros)
        : sm_(sm), macros_(macros) {}

    void MacroDefined(const clang::Token& MacroNameTok,
                      const clang::MacroDirective* MD) override {
        if (!MD) return;

        const clang::MacroInfo* MI = MD->getMacroInfo();
        if (!MI) return;

        // Skip built-in macros
        auto loc = MI->getDefinitionLoc();
        if (!loc.isValid() || sm_.isInSystemHeader(loc)) {
            return;
        }

        MacroDefinition macro;
        macro.name = MacroNameTok.getIdentifierInfo()->getName().str();
        macro.is_function_like = MI->isFunctionLike();
        macro.file_path = sm_.getFilename(loc).str();
        macro.line_start = sm_.getSpellingLineNumber(loc);
        macro.line_end = sm_.getSpellingLineNumber(MI->getDefinitionEndLoc());

        // Get parameters for function-like macros
        if (MI->isFunctionLike()) {
            for (const auto* param : MI->params()) {
                macro.parameters.push_back(param->getName().str());
            }
        }

        // Build body from tokens
        std::string body;
        for (const auto& tok : MI->tokens()) {
            if (!body.empty() && tok.hasLeadingSpace()) {
                body += " ";
            }
            if (tok.isLiteral() && tok.getLiteralData()) {
                body += std::string(tok.getLiteralData(), tok.getLength());
            } else if (tok.getIdentifierInfo()) {
                body += tok.getIdentifierInfo()->getName().str();
            } else {
                body += clang::tok::getPunctuatorSpelling(tok.getKind());
            }
        }
        macro.body = body;

        // Analyze for hazards
        analyzeMacroBody(body, macro);

        macros_.push_back(std::move(macro));
    }

private:
    clang::SourceManager& sm_;
    std::vector<MacroDefinition>& macros_;
};

// Check if a macro has hazardous operations
bool hasHazardousMacro(const MacroDefinition& macro) {
    return macro.has_division ||
           macro.has_pointer_ops ||
           macro.has_casts ||
           !macro.function_calls.empty();
}

// Create axioms from macro definitions
std::vector<Axiom> extractMacroAxioms(const MacroDefinition& macro) {
    std::vector<Axiom> axioms;

    // Only extract from hazardous macros
    if (!hasHazardousMacro(macro)) {
        return axioms;
    }

    std::string signature = "#define " + macro.to_signature();

    // Division hazard -> precondition
    if (macro.has_division) {
        Axiom axiom;
        axiom.id = macro.name + ".precond.divisor_nonzero";
        axiom.content = "Divisor in macro " + macro.name + " must not be zero";
        axiom.formal_spec = "divisor != 0";
        axiom.function = macro.name;
        axiom.signature = signature;
        axiom.header = macro.file_path;
        axiom.axiom_type = AxiomType::PRECONDITION;
        axiom.confidence = 0.9;
        axiom.source_type = SourceType::PATTERN;
        axiom.line = macro.line_start;
        axiom.hazard_type = HazardType::DIVISION;
        axiom.hazard_line = macro.line_start;
        axiom.has_guard = false;
        axioms.push_back(std::move(axiom));
    }

    // Pointer ops hazard -> precondition
    if (macro.has_pointer_ops) {
        Axiom axiom;
        axiom.id = macro.name + ".precond.ptr_valid";
        axiom.content = "Pointer arguments to macro " + macro.name + " must be valid";
        axiom.formal_spec = "ptr != nullptr";
        axiom.function = macro.name;
        axiom.signature = signature;
        axiom.header = macro.file_path;
        axiom.axiom_type = AxiomType::PRECONDITION;
        axiom.confidence = 0.85;
        axiom.source_type = SourceType::PATTERN;
        axiom.line = macro.line_start;
        axiom.hazard_type = HazardType::POINTER_DEREF;
        axiom.hazard_line = macro.line_start;
        axiom.has_guard = false;
        axioms.push_back(std::move(axiom));
    }

    // Cast hazard -> constraint
    if (macro.has_casts) {
        Axiom axiom;
        axiom.id = macro.name + ".constraint.cast_safety";
        axiom.content = "Type cast in macro " + macro.name + " requires compatible types";
        axiom.formal_spec = "is_compatible(source_type, target_type)";
        axiom.function = macro.name;
        axiom.signature = signature;
        axiom.header = macro.file_path;
        axiom.axiom_type = AxiomType::CONSTRAINT;
        axiom.confidence = 0.8;
        axiom.source_type = SourceType::PATTERN;
        axiom.line = macro.line_start;
        axiom.hazard_type = HazardType::CAST;
        axiom.hazard_line = macro.line_start;
        axiom.has_guard = false;
        axioms.push_back(std::move(axiom));
    }

    return axioms;
}

} // namespace axiom
