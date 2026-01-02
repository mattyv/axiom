// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#pragma once

#include "Axiom.h"

#include <clang/AST/ASTContext.h>
#include <clang/AST/Decl.h>
#include <clang/Analysis/CFG.h>
#include <memory>
#include <string>
#include <vector>

namespace axiom {

// Forward declarations
class FunctionExtractor;
class ConstraintExtractor;
class HazardDetector;
class GuardAnalyzer;
class CallGraphExtractor;
class JsonEmitter;

// Function information extracted from AST
struct FunctionInfo {
    std::string name;
    std::string qualified_name;
    std::string signature;
    std::string header;
    int line_start = 0;
    int line_end = 0;

    // C++11/14/17 attributes
    bool is_noexcept = false;
    bool is_nodiscard = false;
    bool is_deprecated = false;
    bool is_const = false;
    bool is_constexpr = false;
    bool is_deleted = false;
    bool is_defaulted = false;

    // C++20 attributes
    bool is_consteval = false;
    bool is_constinit = false;
    bool has_likely = false;
    bool has_unlikely = false;
    bool is_coroutine = false;  // uses co_await/co_yield/co_return

    // Requires clause (C++20 concepts)
    std::string requires_clause;

    // Template constraints
    std::vector<std::string> template_constraints;

    // For method analysis
    const clang::FunctionDecl* decl = nullptr;
};

// Class/struct information
struct ClassInfo {
    std::string name;
    std::string qualified_name;
    std::string header;
    int line_start = 0;
    int line_end = 0;

    bool is_struct = false;
    bool is_union = false;
    bool is_final = false;
    bool is_abstract = false;
    bool has_virtual_destructor = false;
    bool is_trivially_copyable = false;
    bool is_trivially_destructible = false;

    std::vector<std::string> base_classes;
    std::vector<std::string> template_params;
};

// Enum information
struct EnumInfo {
    std::string name;
    std::string qualified_name;
    std::string header;
    int line_start = 0;
    int line_end = 0;

    bool is_scoped = false;  // enum class
    std::string underlying_type;
    std::vector<std::pair<std::string, std::optional<int64_t>>> enumerators;
};

// Concept information (C++20)
struct ConceptInfo {
    std::string name;
    std::string qualified_name;
    std::string header;
    int line_start = 0;
    int line_end = 0;

    std::vector<std::string> template_params;
    std::string constraint_expr;
};

// Static assert information
struct StaticAssertInfo {
    std::string condition;
    std::string message;
    std::string header;
    int line = 0;
};

// Type alias information
struct TypeAliasInfo {
    std::string name;
    std::string qualified_name;
    std::string aliased_type;
    std::string header;
    int line = 0;
    bool is_template = false;
    std::vector<std::string> template_params;
};

// Hazard detected in code
struct Hazard {
    HazardType type;
    std::string expression;
    std::string operand;
    int line;
    bool has_guard = false;
    std::string guard_expression;
    int guard_line = 0;
};

// Interface for extracting function information
class FunctionExtractor {
public:
    virtual ~FunctionExtractor() = default;

    // Extract all function info from a translation unit
    virtual std::vector<FunctionInfo> extractFunctions(clang::ASTContext& ctx) = 0;
};

// Interface for extracting explicit constraints
class ConstraintExtractor {
public:
    virtual ~ConstraintExtractor() = default;

    // Extract axioms from explicit constraints (noexcept, nodiscard, etc.)
    virtual std::vector<Axiom> extractConstraints(const FunctionInfo& func) = 0;
};

// Interface for detecting hazardous operations
class HazardDetector {
public:
    virtual ~HazardDetector() = default;

    // Detect hazards in a function body using CFG
    virtual std::vector<Hazard> detectHazards(
        const clang::FunctionDecl* func,
        clang::ASTContext& ctx
    ) = 0;
};

// Interface for analyzing guards
class GuardAnalyzer {
public:
    virtual ~GuardAnalyzer() = default;

    // Check if a hazard is protected by a guard
    virtual bool isGuarded(
        const Hazard& hazard,
        clang::CFG* cfg,
        clang::ASTContext& ctx
    ) = 0;

    // Find the guard expression for a hazard
    virtual std::optional<std::string> findGuard(
        const Hazard& hazard,
        clang::CFG* cfg,
        clang::ASTContext& ctx
    ) = 0;
};

// Interface for extracting call graph
class CallGraphExtractor {
public:
    virtual ~CallGraphExtractor() = default;

    // Extract function calls from a function body
    virtual std::vector<FunctionCall> extractCalls(
        const clang::FunctionDecl* func,
        clang::ASTContext& ctx
    ) = 0;
};

// Interface for JSON output
class JsonEmitter {
public:
    virtual ~JsonEmitter() = default;

    // Emit extraction results as JSON
    virtual std::string emit(const std::vector<ExtractionResult>& results) = 0;
};

// Test framework enumeration
enum class TestFramework {
    AUTO,       // Auto-detect from includes
    CATCH2,     // Catch2 test framework
    GTEST,      // Google Test
    BOOST_TEST  // Boost.Test
};

// Test assertion information
struct TestAssertion {
    std::string condition;       // The assertion condition
    std::string function_tested; // Function being tested (if detectable)
    std::string test_name;       // Name of the test case
    std::string section_name;    // Section/fixture name (optional)
    AxiomType axiom_type;        // Inferred axiom type
    double confidence;           // Confidence level
    int line;                    // Source line
    TestFramework framework;     // Which framework
    bool is_fatal;               // REQUIRE/ASSERT vs CHECK/EXPECT
};

// Interface for extracting test assertions
class TestAssertExtractor {
public:
    virtual ~TestAssertExtractor() = default;

    // Extract test assertions from a translation unit
    virtual std::vector<TestAssertion> extractAssertions(clang::ASTContext& ctx) = 0;

    // Convert assertions to axioms
    virtual std::vector<Axiom> toAxioms(const std::vector<TestAssertion>& assertions) = 0;
};

// Factory functions (implemented in .cpp files)
std::unique_ptr<FunctionExtractor> createFunctionExtractor();
std::unique_ptr<ConstraintExtractor> createConstraintExtractor();
std::unique_ptr<HazardDetector> createHazardDetector();
std::unique_ptr<GuardAnalyzer> createGuardAnalyzer();
std::unique_ptr<CallGraphExtractor> createCallGraphExtractor();
std::unique_ptr<JsonEmitter> createJsonEmitter();
std::unique_ptr<TestAssertExtractor> createTestAssertExtractor(TestFramework framework = TestFramework::AUTO);

} // namespace axiom
