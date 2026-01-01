// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "Extractors.h"

namespace axiom {

class ConstraintExtractorImpl : public ConstraintExtractor {
public:
    std::vector<Axiom> extractConstraints(const FunctionInfo& func) override {
        std::vector<Axiom> axioms;

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

        return axioms;
    }
};

std::unique_ptr<ConstraintExtractor> createConstraintExtractor() {
    return std::make_unique<ConstraintExtractorImpl>();
}

} // namespace axiom
