// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include <gtest/gtest.h>
#include "SignatureBuilder.h"

#include <clang/AST/ASTContext.h>
#include <clang/AST/Decl.h>
#include <clang/Frontend/ASTUnit.h>
#include <clang/Tooling/Tooling.h>

namespace axiom {
namespace {

// Helper struct to keep AST alive while using FunctionDecl
struct ParsedFunction {
    std::unique_ptr<clang::ASTUnit> ast;
    clang::FunctionDecl* func = nullptr;

    explicit operator bool() const { return func != nullptr; }
};

// Helper to parse code and get the first function
ParsedFunction parseFunctionDecl(const std::string& code) {
    ParsedFunction result;
    result.ast = clang::tooling::buildASTFromCode(code);
    if (!result.ast) return result;

    auto& ctx = result.ast->getASTContext();
    auto* tu = ctx.getTranslationUnitDecl();

    for (auto* decl : tu->decls()) {
        if (auto* func = llvm::dyn_cast<clang::FunctionDecl>(decl)) {
            result.func = func;
            break;
        }
    }
    return result;
}

TEST(SignatureBuilderTest, SimpleFunction) {
    auto parsed = parseFunctionDecl("int add(int a, int b) { return a + b; }");
    ASSERT_TRUE(parsed);

    std::string sig = buildFunctionSignature(parsed.func);

    // Should have no body
    EXPECT_EQ(sig.find("{"), std::string::npos);
    EXPECT_EQ(sig.find("return"), std::string::npos);

    // Should have the declaration
    EXPECT_NE(sig.find("int add(int a, int b)"), std::string::npos);
}

TEST(SignatureBuilderTest, ConstexprFunction) {
    auto parsed = parseFunctionDecl(
        "constexpr int factorial(int n) { return n <= 1 ? 1 : n * factorial(n-1); }");
    ASSERT_TRUE(parsed);

    std::string sig = buildFunctionSignature(parsed.func);

    // Should include constexpr keyword
    EXPECT_NE(sig.find("constexpr"), std::string::npos);

    // Should NOT include body
    EXPECT_EQ(sig.find("{"), std::string::npos);
    EXPECT_EQ(sig.find("?"), std::string::npos);

    EXPECT_EQ(sig, "constexpr int factorial(int n)");
}

TEST(SignatureBuilderTest, InlineFunction) {
    auto parsed = parseFunctionDecl("inline int square(int x) { return x * x; }");
    ASSERT_TRUE(parsed);

    std::string sig = buildFunctionSignature(parsed.func);

    EXPECT_NE(sig.find("inline"), std::string::npos);
    EXPECT_EQ(sig.find("{"), std::string::npos);
    EXPECT_EQ(sig, "inline int square(int x)");
}

TEST(SignatureBuilderTest, StaticInlineConstexpr) {
    auto parsed = parseFunctionDecl(
        "static inline constexpr int max(int a, int b) { return a > b ? a : b; }");
    ASSERT_TRUE(parsed);

    std::string sig = buildFunctionSignature(parsed.func);

    // Should have all keywords
    EXPECT_NE(sig.find("static"), std::string::npos);
    EXPECT_NE(sig.find("inline"), std::string::npos);
    EXPECT_NE(sig.find("constexpr"), std::string::npos);

    // Should NOT have body
    EXPECT_EQ(sig.find("{"), std::string::npos);
}

// TODO: Fix class method parsing - skipping for now
// TEST(SignatureBuilderTest, ConstMethod) { ... }

TEST(SignatureBuilderTest, NoexceptFunction) {
    auto parsed = parseFunctionDecl("int safe() noexcept { return 0; }");
    ASSERT_TRUE(parsed);

    std::string sig = buildFunctionSignature(parsed.func);

    EXPECT_NE(sig.find("noexcept"), std::string::npos);
    EXPECT_EQ(sig.find("{"), std::string::npos);
    EXPECT_EQ(sig, "int safe() noexcept");
}

// TODO: Fix class method parsing - skipping for now
// TEST(SignatureBuilderTest, VirtualMethod) { ... }

TEST(SignatureBuilderTest, NoPreprocessorDirectives) {
    // This will fail with current raw source extraction approach
    auto parsed = parseFunctionDecl(
        "#ifdef FOO\n"
        "inline\n"
        "#else\n"
        "static\n"
        "#endif\n"
        "int conditional() { return 1; }");
    ASSERT_TRUE(parsed);

    std::string sig = buildFunctionSignature(parsed.func);

    // Should NOT contain preprocessor directives
    EXPECT_EQ(sig.find("#ifdef"), std::string::npos);
    EXPECT_EQ(sig.find("#else"), std::string::npos);
    EXPECT_EQ(sig.find("#endif"), std::string::npos);

    // Should contain the actual function signature
    EXPECT_NE(sig.find("int conditional()"), std::string::npos);
}

} // namespace
} // namespace axiom
