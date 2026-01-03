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

// Semantic patterns detected in macro bodies
struct MacroSemantics {
    bool has_lambda_capture = false;      // [&] or [=] lambda capture
    bool has_reference_capture = false;   // Specifically [&]
    bool has_template_call = false;       // Calls template<N> function
    bool has_return_statement = false;    // Contains return
    bool is_incomplete = false;           // Ends with open paren/brace
    bool has_loop_construct = false;      // for/while in body
    bool creates_local_vars = false;      // Defines __xyz variables
    std::vector<std::string> local_vars;  // Names of local variables created
    std::string template_param;           // Template parameter if detected
};

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

// Analyze macro for semantic patterns
MacroSemantics analyzeMacroSemantics(const std::string& body, const MacroDefinition& macro) {
    MacroSemantics sem;

    // Lambda capture patterns
    std::regex refCaptureRegex(R"(\[&\])");
    std::regex anyCaptureRegex(R"(\[[&=]\])");
    sem.has_reference_capture = std::regex_search(body, refCaptureRegex);
    sem.has_lambda_capture = std::regex_search(body, anyCaptureRegex);

    // Template call pattern: identifier<N> or identifier<param>
    std::regex templateCallRegex(R"(\b[a-zA-Z_][a-zA-Z_0-9]*\s*<\s*([A-Z_][A-Z_0-9]*|[a-zA-Z_][a-zA-Z_0-9]*)\s*>)");
    std::smatch match;
    if (std::regex_search(body, match, templateCallRegex)) {
        sem.has_template_call = true;
        sem.template_param = match[1].str();
    }

    // Return statement
    std::regex returnRegex(R"(\breturn\b)");
    sem.has_return_statement = std::regex_search(body, returnRegex);

    // Check if macro is incomplete (ends with open syntax)
    if (!body.empty()) {
        // Count braces and parens
        int braces = 0, parens = 0;
        for (char c : body) {
            if (c == '{') braces++;
            else if (c == '}') braces--;
            else if (c == '(') parens++;
            else if (c == ')') parens--;
        }
        sem.is_incomplete = (braces > 0 || parens > 0);
    }

    // Loop constructs
    std::regex loopRegex(R"(\b(for|while)\s*\()");
    sem.has_loop_construct = std::regex_search(body, loopRegex);

    // Local variable creation (__xyz pattern)
    std::regex localVarRegex(R"(\b(__[a-zA-Z_][a-zA-Z_0-9]*)\b)");
    std::string::const_iterator searchStart = body.cbegin();
    while (std::regex_search(searchStart, body.cend(), match, localVarRegex)) {
        sem.local_vars.push_back(match[1].str());
        sem.creates_local_vars = true;
        searchStart = match.suffix().first;
    }

    return sem;
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

// Check if a macro has interesting semantic patterns worth extracting
bool hasSemanticPatterns(const MacroSemantics& sem) {
    return sem.has_lambda_capture ||
           sem.has_template_call ||
           sem.is_incomplete ||
           sem.creates_local_vars ||
           sem.has_loop_construct;
}

// Create axioms from macro definitions
std::vector<Axiom> extractMacroAxioms(const MacroDefinition& macro) {
    std::vector<Axiom> axioms;

    std::string signature = "#define " + macro.to_signature();
    MacroSemantics sem = analyzeMacroSemantics(macro.body, macro);

    // Always create a basic axiom for every function-like macro
    if (macro.is_function_like) {
        Axiom axiom;
        axiom.id = macro.name + ".macro_definition";
        axiom.content = "Macro " + macro.name + " is a function-like macro";
        if (!macro.parameters.empty()) {
            axiom.content += " with parameters: ";
            for (size_t i = 0; i < macro.parameters.size(); ++i) {
                if (i > 0) axiom.content += ", ";
                axiom.content += macro.parameters[i];
            }
        }
        axiom.formal_spec = "is_function_like_macro(" + macro.name + ")";
        axiom.function = macro.name;
        axiom.signature = signature;
        axiom.header = macro.file_path;
        axiom.axiom_type = AxiomType::CONSTRAINT;
        axiom.confidence = 1.0;
        axiom.source_type = SourceType::EXPLICIT;
        axiom.line = macro.line_start;

        // Add referenced macros as context
        if (!macro.referenced_macros.empty()) {
            axiom.content += ". Expands to: ";
            for (size_t i = 0; i < macro.referenced_macros.size() && i < 3; ++i) {
                if (i > 0) axiom.content += ", ";
                axiom.content += macro.referenced_macros[i];
            }
            if (macro.referenced_macros.size() > 3) {
                axiom.content += "...";
            }
        }

        axioms.push_back(std::move(axiom));
    }

    // --- Hazard-based axioms ---

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

    // --- Semantic pattern axioms ---

    // Reference capture [&] -> CONSTRAINT about capture behavior + ANTI_PATTERN for temporaries
    if (sem.has_reference_capture) {
        // Constraint: variables captured by reference
        {
            Axiom axiom;
            axiom.id = macro.name + ".constraint.reference_capture";
            axiom.content = "Variables used in " + macro.name + " are captured by reference ([&]), allowing modifications to affect the outer scope";
            axiom.formal_spec = "capture_mode == by_reference";
            axiom.function = macro.name;
            axiom.signature = signature;
            axiom.header = macro.file_path;
            axiom.axiom_type = AxiomType::CONSTRAINT;
            axiom.confidence = 1.0;
            axiom.source_type = SourceType::EXPLICIT;
            axiom.line = macro.line_start;
            axioms.push_back(std::move(axiom));
        }

        // Anti-pattern: temporaries may dangle
        {
            Axiom axiom;
            axiom.id = macro.name + ".anti_pattern.dangling_reference";
            axiom.content = "Passing temporary objects to " + macro.name + " may cause dangling references due to [&] capture";
            axiom.formal_spec = "isTemporary(arg) -> undefined_behavior";
            axiom.function = macro.name;
            axiom.signature = signature;
            axiom.header = macro.file_path;
            axiom.axiom_type = AxiomType::ANTI_PATTERN;
            axiom.confidence = 0.9;
            axiom.source_type = SourceType::PATTERN;
            axiom.line = macro.line_start;
            axioms.push_back(std::move(axiom));
        }
    }

    // Template call with parameter -> COMPLEXITY about instantiation
    if (sem.has_template_call && !sem.template_param.empty()) {
        Axiom axiom;
        axiom.id = macro.name + ".complexity.template_instantiation";
        axiom.content = "Each unique value of " + sem.template_param + " causes a separate template instantiation, increasing compile time and code size";
        axiom.formal_spec = "compile_time_cost proportional_to distinct_" + sem.template_param + "_values";
        axiom.function = macro.name;
        axiom.signature = signature;
        axiom.header = macro.file_path;
        axiom.axiom_type = AxiomType::COMPLEXITY;
        axiom.confidence = 0.95;
        axiom.source_type = SourceType::PATTERN;
        axiom.line = macro.line_start;
        axioms.push_back(std::move(axiom));
    }

    // Incomplete macro -> CONSTRAINT about companion requirement
    if (sem.is_incomplete) {
        Axiom axiom;
        axiom.id = macro.name + ".constraint.requires_completion";
        axiom.content = "Macro " + macro.name + " is syntactically incomplete and requires a companion macro or closing syntax";
        axiom.formal_spec = "requires_companion_macro(" + macro.name + ")";
        axiom.function = macro.name;
        axiom.signature = signature;
        axiom.header = macro.file_path;
        axiom.axiom_type = AxiomType::CONSTRAINT;
        axiom.confidence = 1.0;
        axiom.source_type = SourceType::EXPLICIT;
        axiom.line = macro.line_start;
        axioms.push_back(std::move(axiom));
    }

    // Creates local variables -> POSTCONDITION about what's available
    if (sem.creates_local_vars && !sem.local_vars.empty()) {
        // Deduplicate local vars
        std::set<std::string> uniqueVars(sem.local_vars.begin(), sem.local_vars.end());
        std::string varList;
        for (const auto& v : uniqueVars) {
            if (!varList.empty()) varList += ", ";
            varList += v;
        }

        Axiom axiom;
        axiom.id = macro.name + ".postcondition.local_vars_available";
        axiom.content = "After " + macro.name + " expansion, the following identifiers are available in scope: " + varList;
        axiom.formal_spec = "in_scope({" + varList + "})";
        axiom.function = macro.name;
        axiom.signature = signature;
        axiom.header = macro.file_path;
        axiom.axiom_type = AxiomType::POSTCONDITION;
        axiom.confidence = 0.95;
        axiom.source_type = SourceType::PATTERN;
        axiom.line = macro.line_start;
        axioms.push_back(std::move(axiom));
    }

    // Loop construct -> EFFECT about iteration
    if (sem.has_loop_construct) {
        Axiom axiom;
        axiom.id = macro.name + ".effect.iteration";
        axiom.content = "Macro " + macro.name + " performs iteration over a range or condition";
        axiom.formal_spec = "has_iteration_semantics";
        axiom.function = macro.name;
        axiom.signature = signature;
        axiom.header = macro.file_path;
        axiom.axiom_type = AxiomType::EFFECT;
        axiom.confidence = 0.9;
        axiom.source_type = SourceType::PATTERN;
        axiom.line = macro.line_start;
        axioms.push_back(std::move(axiom));
    }

    return axioms;
}

} // namespace axiom
