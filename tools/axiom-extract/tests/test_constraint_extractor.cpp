// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include <gtest/gtest.h>
#include "Extractors.h"

namespace axiom {
namespace {

class ConstraintExtractorTest : public ::testing::Test {
protected:
    void SetUp() override {
        extractor_ = createConstraintExtractor();
    }

    std::unique_ptr<ConstraintExtractor> extractor_;
};

TEST_F(ConstraintExtractorTest, ExtractsNoexceptAxiom) {
    FunctionInfo func;
    func.name = "getValue";
    func.qualified_name = "MyClass::getValue";
    func.signature = "int MyClass::getValue() const noexcept";
    func.header = "myclass.h";
    func.is_noexcept = true;
    func.line_start = 42;

    auto axioms = extractor_->extractConstraints(func);

    ASSERT_EQ(axioms.size(), 1);
    EXPECT_EQ(axioms[0].id, "MyClass::getValue.noexcept");
    EXPECT_EQ(axioms[0].axiom_type, AxiomType::EXCEPTION);
    EXPECT_EQ(axioms[0].confidence, 1.0);
    EXPECT_EQ(axioms[0].source_type, SourceType::EXPLICIT);
    EXPECT_EQ(axioms[0].formal_spec, "noexcept == true");
}

TEST_F(ConstraintExtractorTest, ExtractsNodeiscardAxiom) {
    FunctionInfo func;
    func.name = "compute";
    func.qualified_name = "compute";
    func.signature = "int compute()";
    func.header = "math.h";
    func.is_nodiscard = true;
    func.line_start = 10;

    auto axioms = extractor_->extractConstraints(func);

    ASSERT_EQ(axioms.size(), 1);
    EXPECT_EQ(axioms[0].id, "compute.nodiscard");
    EXPECT_EQ(axioms[0].axiom_type, AxiomType::POSTCONDITION);
    EXPECT_TRUE(axioms[0].content.find("must not be discarded") != std::string::npos);
}

TEST_F(ConstraintExtractorTest, ExtractsConstMethodAxiom) {
    FunctionInfo func;
    func.name = "size";
    func.qualified_name = "Container::size";
    func.signature = "size_t Container::size() const";
    func.header = "container.h";
    func.is_const = true;
    func.line_start = 25;

    auto axioms = extractor_->extractConstraints(func);

    ASSERT_EQ(axioms.size(), 1);
    EXPECT_EQ(axioms[0].id, "Container::size.const");
    EXPECT_EQ(axioms[0].axiom_type, AxiomType::EFFECT);
    EXPECT_EQ(axioms[0].formal_spec, "this->state == old(this->state)");
}

TEST_F(ConstraintExtractorTest, ExtractsDeletedFunctionAxiom) {
    FunctionInfo func;
    func.name = "copy";
    func.qualified_name = "Unique::copy";
    func.signature = "Unique Unique::copy() = delete";
    func.header = "unique.h";
    func.is_deleted = true;
    func.line_start = 15;

    auto axioms = extractor_->extractConstraints(func);

    ASSERT_EQ(axioms.size(), 1);
    EXPECT_EQ(axioms[0].id, "Unique::copy.deleted");
    EXPECT_EQ(axioms[0].axiom_type, AxiomType::CONSTRAINT);
    EXPECT_EQ(axioms[0].formal_spec, "callable == false");
}

TEST_F(ConstraintExtractorTest, ExtractsConstexprAxiom) {
    FunctionInfo func;
    func.name = "factorial";
    func.qualified_name = "factorial";
    func.signature = "constexpr int factorial(int n)";
    func.header = "math.h";
    func.is_constexpr = true;
    func.is_consteval = false;
    func.line_start = 5;

    auto axioms = extractor_->extractConstraints(func);

    ASSERT_EQ(axioms.size(), 1);
    EXPECT_EQ(axioms[0].id, "factorial.constexpr");
    EXPECT_EQ(axioms[0].axiom_type, AxiomType::CONSTRAINT);
    EXPECT_TRUE(axioms[0].content.find("compile time") != std::string::npos);
}

TEST_F(ConstraintExtractorTest, ExtractsConstevalAxiom) {
    FunctionInfo func;
    func.name = "compileTimeOnly";
    func.qualified_name = "compileTimeOnly";
    func.signature = "consteval int compileTimeOnly()";
    func.header = "meta.h";
    func.is_constexpr = true;  // consteval implies constexpr
    func.is_consteval = true;
    func.line_start = 8;

    auto axioms = extractor_->extractConstraints(func);

    // Should only produce consteval, not constexpr
    ASSERT_EQ(axioms.size(), 1);
    EXPECT_EQ(axioms[0].id, "compileTimeOnly.consteval");
    EXPECT_EQ(axioms[0].formal_spec, "consteval == true");
    EXPECT_TRUE(axioms[0].content.find("must be evaluated") != std::string::npos);
}

TEST_F(ConstraintExtractorTest, ExtractsDeprecatedAxiom) {
    FunctionInfo func;
    func.name = "oldFunction";
    func.qualified_name = "oldFunction";
    func.signature = "void oldFunction()";
    func.header = "legacy.h";
    func.is_deprecated = true;
    func.line_start = 100;

    auto axioms = extractor_->extractConstraints(func);

    ASSERT_EQ(axioms.size(), 1);
    EXPECT_EQ(axioms[0].id, "oldFunction.deprecated");
    EXPECT_EQ(axioms[0].axiom_type, AxiomType::ANTI_PATTERN);
}

TEST_F(ConstraintExtractorTest, ExtractsRequiresClauseAxiom) {
    FunctionInfo func;
    func.name = "process";
    func.qualified_name = "process";
    func.signature = "template<typename T> void process(T val)";
    func.header = "generic.h";
    func.requires_clause = "std::integral<T>";
    func.line_start = 20;

    auto axioms = extractor_->extractConstraints(func);

    ASSERT_EQ(axioms.size(), 1);
    EXPECT_EQ(axioms[0].id, "process.requires");
    EXPECT_EQ(axioms[0].axiom_type, AxiomType::CONSTRAINT);
    EXPECT_EQ(axioms[0].formal_spec, "std::integral<T>");
}

TEST_F(ConstraintExtractorTest, ExtractsMultipleConstraints) {
    FunctionInfo func;
    func.name = "safeGet";
    func.qualified_name = "Container::safeGet";
    func.signature = "int Container::safeGet() const noexcept";
    func.header = "container.h";
    func.is_noexcept = true;
    func.is_const = true;
    func.is_nodiscard = true;
    func.line_start = 50;

    auto axioms = extractor_->extractConstraints(func);

    EXPECT_EQ(axioms.size(), 3);

    // Verify all expected axioms are present
    bool hasNoexcept = false, hasConst = false, hasNodiscard = false;
    for (const auto& axiom : axioms) {
        if (axiom.id.find(".noexcept") != std::string::npos) hasNoexcept = true;
        if (axiom.id.find(".const") != std::string::npos) hasConst = true;
        if (axiom.id.find(".nodiscard") != std::string::npos) hasNodiscard = true;
    }
    EXPECT_TRUE(hasNoexcept);
    EXPECT_TRUE(hasConst);
    EXPECT_TRUE(hasNodiscard);
}

TEST_F(ConstraintExtractorTest, ReturnsEmptyForPlainFunction) {
    FunctionInfo func;
    func.name = "plainFunction";
    func.qualified_name = "plainFunction";
    func.signature = "void plainFunction()";
    func.header = "plain.h";
    func.line_start = 1;
    // No special attributes

    auto axioms = extractor_->extractConstraints(func);

    EXPECT_TRUE(axioms.empty());
}

}  // namespace
}  // namespace axiom
