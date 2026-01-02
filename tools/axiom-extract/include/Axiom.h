// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#pragma once

#include <nlohmann/json.hpp>
#include <string>
#include <vector>

namespace axiom {

// Axiom types matching Python AxiomType enum
enum class AxiomType {
    PRECONDITION,
    POSTCONDITION,
    INVARIANT,
    EXCEPTION,
    EFFECT,
    CONSTRAINT,
    ANTI_PATTERN,
    COMPLEXITY
};

// Source type for confidence tracking
enum class SourceType {
    EXPLICIT,    // Compiler-enforced (noexcept, nodiscard, etc.)
    PATTERN,     // CFG-based hazard detection
    PROPAGATED,  // Inherited from callee
    LLM          // LLM fallback
};

// Hazard types for pattern-based detection
enum class HazardType {
    DIVISION,
    POINTER_DEREF,
    ARRAY_ACCESS,
    CAST
};

// Macro definition structure
struct MacroDefinition {
    std::string name;
    std::vector<std::string> parameters;
    std::string body;
    bool is_function_like = false;
    std::string file_path;
    int line_start = 0;
    int line_end = 0;

    // Hazard analysis
    bool has_division = false;
    bool has_pointer_ops = false;
    bool has_casts = false;
    std::vector<std::string> function_calls;
    std::vector<std::string> referenced_macros;

    std::string to_signature() const {
        if (is_function_like) {
            std::string sig = name + "(";
            for (size_t i = 0; i < parameters.size(); ++i) {
                if (i > 0) sig += ", ";
                sig += parameters[i];
            }
            sig += ")";
            return sig;
        }
        return name;
    }
};

inline void to_json(nlohmann::json& j, const MacroDefinition& m) {
    j = nlohmann::json{
        {"name", m.name},
        {"parameters", m.parameters},
        {"body", m.body},
        {"is_function_like", m.is_function_like},
        {"file_path", m.file_path},
        {"line_start", m.line_start},
        {"line_end", m.line_end},
        {"has_division", m.has_division},
        {"has_pointer_ops", m.has_pointer_ops},
        {"has_casts", m.has_casts},
        {"function_calls", m.function_calls},
        {"referenced_macros", m.referenced_macros}
    };
}

// Function call information for call graph extraction
struct FunctionCall {
    std::string caller;           // Qualified name of calling function
    std::string callee;           // Qualified name of called function
    std::string callee_signature; // Full signature of callee
    int line = 0;                 // Line number of call
    std::vector<std::string> arguments;  // Argument expressions
    bool is_virtual = false;      // True if virtual dispatch
};

inline void to_json(nlohmann::json& j, const FunctionCall& c) {
    j = nlohmann::json{
        {"caller", c.caller},
        {"callee", c.callee},
        {"callee_signature", c.callee_signature},
        {"line", c.line},
        {"arguments", c.arguments},
        {"is_virtual", c.is_virtual}
    };
}

// Extracted axiom structure
struct Axiom {
    std::string id;
    std::string content;
    std::string formal_spec;
    std::string function;
    std::string signature;
    std::string header;
    AxiomType axiom_type;
    double confidence;
    SourceType source_type;
    int line;

    // Hazard-specific fields (optional)
    std::optional<HazardType> hazard_type;
    std::optional<int> hazard_line;
    std::optional<bool> has_guard;
    std::optional<std::string> guard_expression;
};

// JSON serialization
NLOHMANN_JSON_SERIALIZE_ENUM(AxiomType, {
    {AxiomType::PRECONDITION, "PRECONDITION"},
    {AxiomType::POSTCONDITION, "POSTCONDITION"},
    {AxiomType::INVARIANT, "INVARIANT"},
    {AxiomType::EXCEPTION, "EXCEPTION"},
    {AxiomType::EFFECT, "EFFECT"},
    {AxiomType::CONSTRAINT, "CONSTRAINT"},
    {AxiomType::ANTI_PATTERN, "ANTI_PATTERN"},
    {AxiomType::COMPLEXITY, "COMPLEXITY"}
})

NLOHMANN_JSON_SERIALIZE_ENUM(SourceType, {
    {SourceType::EXPLICIT, "explicit"},
    {SourceType::PATTERN, "pattern"},
    {SourceType::PROPAGATED, "propagated"},
    {SourceType::LLM, "llm"}
})

NLOHMANN_JSON_SERIALIZE_ENUM(HazardType, {
    {HazardType::DIVISION, "division"},
    {HazardType::POINTER_DEREF, "pointer_deref"},
    {HazardType::ARRAY_ACCESS, "array_access"},
    {HazardType::CAST, "cast"}
})

inline void to_json(nlohmann::json& j, const Axiom& a) {
    j = nlohmann::json{
        {"id", a.id},
        {"content", a.content},
        {"formal_spec", a.formal_spec},
        {"function", a.function},
        {"signature", a.signature},
        {"header", a.header},
        {"axiom_type", a.axiom_type},
        {"confidence", a.confidence},
        {"source_type", a.source_type},
        {"line", a.line}
    };

    if (a.hazard_type) {
        j["hazard_type"] = *a.hazard_type;
    }
    if (a.hazard_line) {
        j["hazard_line"] = *a.hazard_line;
    }
    if (a.has_guard) {
        j["has_guard"] = *a.has_guard;
    }
    if (a.guard_expression) {
        j["guard_expression"] = *a.guard_expression;
    }
}

// Extraction result for a single file
struct ExtractionResult {
    std::string source_file;
    std::vector<Axiom> axioms;
    std::vector<std::string> errors;
};

inline void to_json(nlohmann::json& j, const ExtractionResult& r) {
    j = nlohmann::json{
        {"source_file", r.source_file},
        {"axioms", r.axioms},
        {"errors", r.errors}
    };
}

} // namespace axiom
