// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include "Axiom.h"

namespace axiom {

// Declare the function from MacroExtractor.cpp
std::vector<Axiom> extractMacroAxioms(const MacroDefinition& macro);

namespace {

using ::testing::Contains;
using ::testing::Field;
using ::testing::HasSubstr;
using ::testing::SizeIs;
using ::testing::Ge;

class MacroExtractorTest : public ::testing::Test {
protected:
    MacroDefinition createMacro(const std::string& name,
                                 const std::vector<std::string>& params,
                                 const std::string& body) {
        MacroDefinition macro;
        macro.name = name;
        macro.parameters = params;
        macro.body = body;
        macro.is_function_like = !params.empty() || body.find("(") != std::string::npos;
        macro.file_path = "test.h";
        macro.line_start = 1;
        macro.line_end = 1;
        return macro;
    }
};

// Test that ALL function-like macros get at least a basic axiom
TEST_F(MacroExtractorTest, ExtractsAllFunctionLikeMacros) {
    // A simple wrapper macro like ASSERT_EQ
    auto macro = createMacro("ASSERT_EQ", {"val1", "val2"}, "GTEST_ASSERT_EQ(val1, val2)");
    macro.is_function_like = true;
    macro.referenced_macros = {"GTEST_ASSERT_EQ"};

    auto axioms = extractMacroAxioms(macro);

    // Should get at least one axiom for ANY function-like macro
    ASSERT_THAT(axioms, SizeIs(Ge(1)));

    // Should have the macro definition axiom
    EXPECT_THAT(axioms, Contains(Field(&Axiom::id, "ASSERT_EQ.macro_definition")));
}

TEST_F(MacroExtractorTest, ExtractsSimpleWrapperMacro) {
    // EXPECT_TRUE is a simple wrapper
    auto macro = createMacro("EXPECT_TRUE", {"condition"}, "GTEST_EXPECT_TRUE(condition)");
    macro.is_function_like = true;
    macro.referenced_macros = {"GTEST_EXPECT_TRUE"};

    auto axioms = extractMacroAxioms(macro);

    ASSERT_THAT(axioms, SizeIs(Ge(1)));

    // Check content mentions the parameter
    auto it = std::find_if(axioms.begin(), axioms.end(), [](const Axiom& a) {
        return a.id == "EXPECT_TRUE.macro_definition";
    });
    ASSERT_NE(it, axioms.end());
    EXPECT_THAT(it->content, HasSubstr("condition"));
}

TEST_F(MacroExtractorTest, IncludesReferencedMacrosInContent) {
    auto macro = createMacro("ASSERT_EQ", {"val1", "val2"}, "GTEST_ASSERT_EQ(val1, val2)");
    macro.is_function_like = true;
    macro.referenced_macros = {"GTEST_ASSERT_EQ"};

    auto axioms = extractMacroAxioms(macro);

    auto it = std::find_if(axioms.begin(), axioms.end(), [](const Axiom& a) {
        return a.id == "ASSERT_EQ.macro_definition";
    });
    ASSERT_NE(it, axioms.end());
    EXPECT_THAT(it->content, HasSubstr("GTEST_ASSERT_EQ"));
}

// Existing behavior: hazard macros still get hazard axioms
TEST_F(MacroExtractorTest, DivisionHazardStillExtracted) {
    auto macro = createMacro("DIVIDE", {"a", "b"}, "((a) / (b))");
    macro.is_function_like = true;
    macro.has_division = true;

    auto axioms = extractMacroAxioms(macro);

    // Should have both base axiom AND hazard axiom
    EXPECT_THAT(axioms, Contains(Field(&Axiom::id, "DIVIDE.macro_definition")));
    EXPECT_THAT(axioms, Contains(Field(&Axiom::id, "DIVIDE.precond.divisor_nonzero")));
}

// Non-function-like macros (object macros) should be skipped
TEST_F(MacroExtractorTest, SkipsObjectMacros) {
    MacroDefinition macro;
    macro.name = "MAX_SIZE";
    macro.body = "1024";
    macro.is_function_like = false;
    macro.file_path = "test.h";
    macro.line_start = 1;
    macro.line_end = 1;

    auto axioms = extractMacroAxioms(macro);

    // Object macros don't get the base macro_definition axiom
    // (but could still get hazard axioms if they have hazards)
    EXPECT_TRUE(axioms.empty() ||
                std::none_of(axioms.begin(), axioms.end(), [](const Axiom& a) {
                    return a.id.find(".macro_definition") != std::string::npos;
                }));
}

} // namespace
} // namespace axiom
