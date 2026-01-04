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

// Helper to parse C++ code and run hazard detection
class HazardDetectorTest : public ::testing::Test {
protected:
    void SetUp() override {
        detector_ = createHazardDetector();
    }

    // Parse code and find the function declaration
    std::unique_ptr<clang::ASTUnit> parseCode(const std::string& code) {
        return clang::tooling::buildASTFromCode(code, "test.cpp");
    }

    const clang::FunctionDecl* findFunction(clang::ASTUnit* ast,
                                            const std::string& name) {
        for (auto* decl : ast->getASTContext().getTranslationUnitDecl()->decls()) {
            if (auto* func = llvm::dyn_cast<clang::FunctionDecl>(decl)) {
                if (func->getNameAsString() == name) {
                    return func;
                }
            }
        }
        return nullptr;
    }

    std::unique_ptr<HazardDetector> detector_;
};

TEST_F(HazardDetectorTest, DetectsDivisionHazard) {
    auto ast = parseCode(R"(
        int divide(int a, int b) {
            return a / b;
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "divide");
    ASSERT_NE(func, nullptr);

    auto hazards = detector_->detectHazards(func, ast->getASTContext());

    ASSERT_GE(hazards.size(), 1);
    EXPECT_EQ(hazards[0].type, HazardType::DIVISION);
}

TEST_F(HazardDetectorTest, DetectsModuloHazard) {
    auto ast = parseCode(R"(
        int modulo(int a, int b) {
            return a % b;
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "modulo");
    ASSERT_NE(func, nullptr);

    auto hazards = detector_->detectHazards(func, ast->getASTContext());

    ASSERT_GE(hazards.size(), 1);
    EXPECT_EQ(hazards[0].type, HazardType::DIVISION);
}

TEST_F(HazardDetectorTest, SkipsLiteralNonZeroDivisor) {
    auto ast = parseCode(R"(
        int divideByTwo(int a) {
            return a / 2;
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "divideByTwo");
    ASSERT_NE(func, nullptr);

    auto hazards = detector_->detectHazards(func, ast->getASTContext());

    // Should not detect hazard for literal non-zero divisor
    EXPECT_TRUE(hazards.empty());
}

TEST_F(HazardDetectorTest, DetectsPointerDereference) {
    auto ast = parseCode(R"(
        int deref(int* p) {
            return *p;
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "deref");
    ASSERT_NE(func, nullptr);

    auto hazards = detector_->detectHazards(func, ast->getASTContext());

    ASSERT_GE(hazards.size(), 1);
    EXPECT_EQ(hazards[0].type, HazardType::POINTER_DEREF);
}

TEST_F(HazardDetectorTest, DetectsArrowOperator) {
    auto ast = parseCode(R"(
        struct S { int x; };
        int getX(S* s) {
            return s->x;
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "getX");
    ASSERT_NE(func, nullptr);

    auto hazards = detector_->detectHazards(func, ast->getASTContext());

    ASSERT_GE(hazards.size(), 1);
    EXPECT_EQ(hazards[0].type, HazardType::POINTER_DEREF);
}

TEST_F(HazardDetectorTest, DetectsArrayAccess) {
    auto ast = parseCode(R"(
        int getElement(int* arr, int i) {
            return arr[i];
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "getElement");
    ASSERT_NE(func, nullptr);

    auto hazards = detector_->detectHazards(func, ast->getASTContext());

    // Should detect both pointer deref and array access
    bool hasArrayAccess = false;
    for (const auto& h : hazards) {
        if (h.type == HazardType::ARRAY_ACCESS) {
            hasArrayAccess = true;
            break;
        }
    }
    EXPECT_TRUE(hasArrayAccess);
}

TEST_F(HazardDetectorTest, DetectsMultipleHazards) {
    auto ast = parseCode(R"(
        int multiHazard(int* arr, int idx, int divisor) {
            return arr[idx] / divisor;
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "multiHazard");
    ASSERT_NE(func, nullptr);

    auto hazards = detector_->detectHazards(func, ast->getASTContext());

    // Should detect array access and division
    EXPECT_GE(hazards.size(), 2);
}

TEST_F(HazardDetectorTest, ReturnsEmptyForSafeFunction) {
    auto ast = parseCode(R"(
        int add(int a, int b) {
            return a + b;
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "add");
    ASSERT_NE(func, nullptr);

    auto hazards = detector_->detectHazards(func, ast->getASTContext());

    EXPECT_TRUE(hazards.empty());
}

TEST_F(HazardDetectorTest, HandlesEmptyFunction) {
    auto ast = parseCode(R"(
        void empty() {}
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "empty");
    ASSERT_NE(func, nullptr);

    auto hazards = detector_->detectHazards(func, ast->getASTContext());

    EXPECT_TRUE(hazards.empty());
}

TEST_F(HazardDetectorTest, DetectsReinterpretCast) {
    auto ast = parseCode(R"(
        int* unsafeCast(long addr) {
            return reinterpret_cast<int*>(addr);
        }
    )");
    ASSERT_NE(ast, nullptr);

    auto* func = findFunction(ast.get(), "unsafeCast");
    ASSERT_NE(func, nullptr);

    auto hazards = detector_->detectHazards(func, ast->getASTContext());

    bool hasCast = false;
    for (const auto& h : hazards) {
        if (h.type == HazardType::CAST) {
            hasCast = true;
            break;
        }
    }
    EXPECT_TRUE(hasCast);
}

}  // namespace
}  // namespace axiom
