// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "Extractors.h"

#include <regex>

namespace axiom {

// Helper to analyze return type for postcondition generation
struct ReturnTypeInfo {
    bool is_void = false;
    bool is_bool = false;
    bool is_optional = false;      // std::optional<T>
    bool is_expected = false;      // std::expected<T, E>
    bool is_pointer = false;
    bool is_reference = false;
    std::string type_name;
};

ReturnTypeInfo analyzeReturnType(const std::string& signature) {
    ReturnTypeInfo info;

    // Extract return type from signature (before qualified name)
    // Pattern: "return_type qualified::name("
    std::regex returnTypeRegex(R"(^(.+?)\s+\S+::\S+\(|^(.+?)\s+\S+\()");
    std::smatch match;
    if (!std::regex_search(signature, match, returnTypeRegex)) {
        return info;
    }

    info.type_name = match[1].matched ? match[1].str() : match[2].str();

    // Trim whitespace
    size_t start = info.type_name.find_first_not_of(" \t");
    size_t end = info.type_name.find_last_not_of(" \t");
    if (start != std::string::npos && end != std::string::npos) {
        info.type_name = info.type_name.substr(start, end - start + 1);
    }

    // Strip leading qualifiers (constexpr, inline, static, virtual, explicit)
    // These don't affect the actual type for our purposes
    static const std::vector<std::string> qualifiers = {
        "constexpr ", "consteval ", "inline ", "static ", "virtual ", "explicit ",
        "friend ", "mutable ", "volatile ", "const "
    };
    bool changed = true;
    while (changed) {
        changed = false;
        for (const auto& qual : qualifiers) {
            if (info.type_name.find(qual) == 0) {
                info.type_name = info.type_name.substr(qual.length());
                changed = true;
            }
        }
    }

    // Trim again after stripping qualifiers
    start = info.type_name.find_first_not_of(" \t");
    end = info.type_name.find_last_not_of(" \t");
    if (start != std::string::npos && end != std::string::npos) {
        info.type_name = info.type_name.substr(start, end - start + 1);
    }

    // Check for void
    info.is_void = (info.type_name == "void");

    // Check for bool
    info.is_bool = (info.type_name == "bool" || info.type_name == "_Bool");

    // Check for optional (handles std::optional, optional, etc.)
    info.is_optional = (info.type_name.find("optional") != std::string::npos);

    // Check for expected (C++23)
    info.is_expected = (info.type_name.find("expected") != std::string::npos);

    // Check for pointer
    info.is_pointer = (!info.type_name.empty() && info.type_name.back() == '*');

    // Check for reference
    info.is_reference = (!info.type_name.empty() && info.type_name.back() == '&');

    return info;
}

class ConstraintExtractorImpl : public ConstraintExtractor {
public:
    std::vector<Axiom> extractConstraints(const FunctionInfo& func) override {
        std::vector<Axiom> axioms;

        // Analyze return type for postconditions
        ReturnTypeInfo returnInfo = analyzeReturnType(func.signature);

        // noexcept -> EXCEPTION axiom
        if (func.is_noexcept) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".noexcept";
            axiom.content = func.name + " is guaranteed not to throw exceptions";
            axiom.formal_spec = "noexcept == true";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::EXCEPTION;
            axiom.confidence = 1.0;
            axiom.source_type = SourceType::EXPLICIT;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // [[nodiscard]] -> POSTCONDITION axiom
        if (func.is_nodiscard) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".nodiscard";
            axiom.content = "Return value of " + func.name + " must not be discarded";
            axiom.formal_spec = "[[nodiscard]]";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::POSTCONDITION;
            axiom.confidence = 1.0;
            axiom.source_type = SourceType::EXPLICIT;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // const method -> EFFECT axiom
        if (func.is_const) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".const";
            axiom.content = func.name + " does not modify object state";
            axiom.formal_spec = "this->state == old(this->state)";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::EFFECT;
            axiom.confidence = 1.0;
            axiom.source_type = SourceType::EXPLICIT;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // = delete -> CONSTRAINT axiom
        if (func.is_deleted) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".deleted";
            axiom.content = func.name + " is explicitly deleted and cannot be called";
            axiom.formal_spec = "callable == false";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::CONSTRAINT;
            axiom.confidence = 1.0;
            axiom.source_type = SourceType::EXPLICIT;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // constexpr -> CONSTRAINT axiom
        if (func.is_constexpr && !func.is_consteval) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".constexpr";
            axiom.content = func.name + " can be evaluated at compile time";
            axiom.formal_spec = "constexpr == true";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::CONSTRAINT;
            axiom.confidence = 1.0;
            axiom.source_type = SourceType::EXPLICIT;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // consteval -> CONSTRAINT axiom (stronger than constexpr)
        if (func.is_consteval) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".consteval";
            axiom.content = func.name + " must be evaluated at compile time";
            axiom.formal_spec = "consteval == true";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::CONSTRAINT;
            axiom.confidence = 1.0;
            axiom.source_type = SourceType::EXPLICIT;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // [[deprecated]] -> CONSTRAINT axiom
        if (func.is_deprecated) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".deprecated";
            axiom.content = func.name + " is deprecated and should not be used";
            axiom.formal_spec = "[[deprecated]]";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::ANTI_PATTERN;
            axiom.confidence = 1.0;
            axiom.source_type = SourceType::EXPLICIT;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // requires clause -> CONSTRAINT axiom
        if (!func.requires_clause.empty()) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".requires";
            axiom.content = "Template parameters must satisfy: " + func.requires_clause;
            axiom.formal_spec = func.requires_clause;
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::CONSTRAINT;
            axiom.confidence = 1.0;
            axiom.source_type = SourceType::EXPLICIT;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // --- Return type-based POSTCONDITION axioms ---

        // std::optional<T> return -> POSTCONDITION about value presence
        if (returnInfo.is_optional) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".postcond.optional_value";
            axiom.content = func.name + " returns std::optional which may or may not contain a value; caller must check has_value() before accessing";
            axiom.formal_spec = "result.has_value() || result == std::nullopt";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::POSTCONDITION;
            axiom.confidence = 0.95;
            axiom.source_type = SourceType::PATTERN;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // bool return -> POSTCONDITION about boolean semantics
        if (returnInfo.is_bool) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".postcond.bool_result";
            axiom.content = func.name + " returns a boolean indicating success/validity; true typically indicates success or valid state";
            axiom.formal_spec = "result in {true, false}";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::POSTCONDITION;
            axiom.confidence = 0.85;
            axiom.source_type = SourceType::PATTERN;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // std::expected<T, E> return -> POSTCONDITION about error handling
        if (returnInfo.is_expected) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".postcond.expected_value";
            axiom.content = func.name + " returns std::expected which contains either a value or an error; caller must check has_value() before accessing value";
            axiom.formal_spec = "result.has_value() xor result.error()";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::POSTCONDITION;
            axiom.confidence = 0.95;
            axiom.source_type = SourceType::PATTERN;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // Pointer return -> POSTCONDITION about null possibility
        if (returnInfo.is_pointer && !returnInfo.is_void) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".postcond.pointer_nullable";
            axiom.content = func.name + " returns a pointer that may be null; caller should check for nullptr before dereferencing";
            axiom.formal_spec = "result == nullptr || is_valid_pointer(result)";
            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::POSTCONDITION;
            axiom.confidence = 0.80;
            axiom.source_type = SourceType::PATTERN;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        // --- Template COMPLEXITY axioms ---

        // Template function -> COMPLEXITY about instantiation
        if (func.is_template) {
            Axiom axiom;
            axiom.id = func.qualified_name + ".complexity.template_instantiation";

            if (func.is_variadic_template) {
                axiom.content = func.name + " is a variadic template; each unique parameter pack expansion causes a separate instantiation, potentially increasing code size";
                axiom.formal_spec = "instantiation_count = O(unique_pack_expansions)";
                axiom.confidence = 0.90;
            } else if (func.template_param_count > 0) {
                axiom.content = func.name + " is a template function; each unique combination of template arguments causes a separate instantiation";
                axiom.formal_spec = "instantiation_count = O(unique_template_args^" + std::to_string(func.template_param_count) + ")";
                axiom.confidence = 0.95;
            } else {
                axiom.content = func.name + " is a template function that may generate multiple instantiations";
                axiom.formal_spec = "instantiation_count >= 1";
                axiom.confidence = 0.90;
            }

            axiom.function = func.qualified_name;
            axiom.signature = func.signature;
            axiom.header = func.header;
            axiom.axiom_type = AxiomType::COMPLEXITY;
            axiom.source_type = SourceType::PATTERN;
            axiom.line = func.line_start;
            axioms.push_back(std::move(axiom));
        }

        return axioms;
    }
};

std::unique_ptr<ConstraintExtractor> createConstraintExtractor() {
    return std::make_unique<ConstraintExtractorImpl>();
}

} // namespace axiom
