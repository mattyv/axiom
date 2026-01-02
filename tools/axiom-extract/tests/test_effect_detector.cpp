// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include "Extractors.h"

#include <clang/Frontend/ASTUnit.h>
#include <clang/Frontend/CompilerInstance.h>
#include <clang/Tooling/Tooling.h>

namespace axiom {
namespace {

using ::testing::Contains;
using ::testing::Field;
using ::testing::AllOf;

// Helper to parse C++ code and run effect detection
class EffectDetectorTest : public ::testing::Test {
protected:
    void SetUp() override {
        detector_ = createEffectDetector();
    }

    // Parse code and find the function declaration
    std::unique_ptr<clang::ASTUnit> parseCode(const std::string& code) {
        return clang::tooling::buildASTFromCodeWithArgs(
            code, {"-std=c++20"}, "test.cpp");
    }

    const clang::FunctionDecl* findFunction(clang::ASTUnit* ast,
                                            const std::string& name) {
        for (auto* decl : ast->getASTContext().getTranslationUnitDecl()->decls()) {
            if (auto* func = llvm::dyn_cast<clang::FunctionDecl>(decl)) {
                if (func->getNameAsString() == name && func->hasBody()) {
                    return func;
                }
            }
        }
        return nullptr;
    }

    std::unique_ptr<EffectDetector> detector_;
};

TEST_F(EffectDetectorTest, DetectsCallFrequencySingleCall) {
    // RED: This test will fail until we implement call frequency tracking
    auto ast = parseCode(R"(
        #include <vector>
        void process_range() {
            std::vector<int> v;
            auto it = v.begin();  // Called once
            // Use it
            for (auto x = it; x != v.end(); ++x) {
                *x = 0;
            }
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "process_range");
    ASSERT_NE(func, nullptr);

    auto effects = detector_->detectEffects(func, ast->getASTContext());

    // Should have a CALL_FREQUENCY effect for v.begin()
    auto call_freq_effects = std::vector<Effect>();
    for (const auto& e : effects) {
        if (e.kind == EffectKind::CALL_FREQUENCY) {
            call_freq_effects.push_back(e);
        }
    }

    ASSERT_GE(call_freq_effects.size(), 1);

    // Find the begin() call
    bool found_begin = false;
    for (const auto& e : call_freq_effects) {
        if (e.target.find("begin") != std::string::npos) {
            EXPECT_EQ(e.call_count, 1);
            EXPECT_TRUE(e.is_cached);  // Result is stored in 'it'
            EXPECT_TRUE(e.occurs_at_start);  // Before the loop
            found_begin = true;
        }
    }
    EXPECT_TRUE(found_begin);
}

TEST_F(EffectDetectorTest, DetectsRangeEvaluatedOnce) {
    // RED: This test models the ilp_for case from the plan
    auto ast = parseCode(R"(
        #include <ranges>
        template<typename Range>
        void for_loop_range_impl(Range&& range) {
            auto it = std::ranges::begin(range);    // Line 1
            auto size = std::ranges::size(range);   // Line 2
            // Both called exactly once at function start
            for (std::size_t i = 0; i < size; ++i) {
                // Use it
            }
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "for_loop_range_impl");
    ASSERT_NE(func, nullptr);

    auto effects = detector_->detectEffects(func, ast->getASTContext());

    // Should detect two CALL_FREQUENCY effects: std::ranges::begin() and std::ranges::size()
    int begin_count = 0;
    int size_count = 0;

    for (const auto& e : effects) {
        if (e.kind == EffectKind::CALL_FREQUENCY) {
            if (e.target.find("begin") != std::string::npos) {
                EXPECT_EQ(e.call_count, 1);
                EXPECT_TRUE(e.is_cached);
                EXPECT_TRUE(e.occurs_at_start);
                begin_count++;
            }
            if (e.target.find("size") != std::string::npos) {
                EXPECT_EQ(e.call_count, 1);
                EXPECT_TRUE(e.is_cached);
                EXPECT_TRUE(e.occurs_at_start);
                size_count++;
            }
        }
    }

    EXPECT_GE(begin_count, 1) << "Should detect std::ranges::begin() call";
    EXPECT_GE(size_count, 1) << "Should detect std::ranges::size() call";
}

TEST_F(EffectDetectorTest, DetectsMultipleCallsNotCached) {
    // RED: Test detecting when a function is called multiple times
    auto ast = parseCode(R"(
        int get_value();
        void process() {
            int a = get_value();  // First call
            int b = get_value();  // Second call
            int c = a + b;
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "process");
    ASSERT_NE(func, nullptr);

    auto effects = detector_->detectEffects(func, ast->getASTContext());

    // Should detect get_value() called twice, not cached
    for (const auto& e : effects) {
        if (e.kind == EffectKind::CALL_FREQUENCY &&
            e.target.find("get_value") != std::string::npos) {
            EXPECT_EQ(e.call_count, 2);
            EXPECT_FALSE(e.is_cached);  // Called twice, not reusing result
            EXPECT_TRUE(e.occurs_at_start);  // Both before any loops
        }
    }
}

TEST_F(EffectDetectorTest, DetectsCallInsideLoop) {
    // RED: Test detecting when a call occurs inside a loop
    auto ast = parseCode(R"(
        int compute(int x);
        void process() {
            for (int i = 0; i < 10; ++i) {
                int val = compute(i);
            }
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "process");
    ASSERT_NE(func, nullptr);

    auto effects = detector_->detectEffects(func, ast->getASTContext());

    // Should detect compute() called in loop, not at start
    for (const auto& e : effects) {
        if (e.kind == EffectKind::CALL_FREQUENCY &&
            e.target.find("compute") != std::string::npos) {
            EXPECT_FALSE(e.occurs_at_start);  // Inside loop, not at function start
        }
    }
}

} // namespace
} // namespace axiom
