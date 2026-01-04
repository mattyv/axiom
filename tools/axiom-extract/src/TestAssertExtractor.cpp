// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "Extractors.h"

#include <clang/AST/RecursiveASTVisitor.h>
#include <clang/AST/ASTContext.h>
#include <clang/Lex/Preprocessor.h>

#include <regex>
#include <unordered_set>

namespace axiom {

namespace {

// Patterns for detecting test framework macro expansions after preprocessing
// These match the internal namespace patterns that macros expand to

// Catch2 patterns (after macro expansion)
const std::vector<std::string> CATCH2_NAMESPACES = {
    "Catch::AssertionHandler",
    "Catch::Decomposer",
    "Catch::ResultDisposition"
};

// GoogleTest patterns
const std::vector<std::string> GTEST_NAMESPACES = {
    "testing::internal::AssertHelper",
    "testing::AssertionResult",
    "testing::internal::GetBoolAssertionFailureMessage"
};

// Boost.Test patterns
const std::vector<std::string> BOOST_TEST_NAMESPACES = {
    "boost::test_tools",
    "boost::unit_test"
};

// Assertion type mapping based on expanded code patterns
struct AssertionPattern {
    std::string pattern;        // Regex pattern to match
    AxiomType axiom_type;       // Resulting axiom type
    double base_confidence;     // Base confidence
    bool is_fatal;              // REQUIRE/ASSERT vs CHECK/EXPECT
    TestFramework framework;    // Which framework
};

// Catch2 assertion patterns (match call expressions)
const std::vector<AssertionPattern> CATCH2_PATTERNS = {
    // REQUIRE variants - fatal assertions
    {"REQUIRE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::CATCH2},
    {"REQUIRE_FALSE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::CATCH2},
    {"REQUIRE_THROWS\\s*\\(", AxiomType::EXCEPTION, 0.85, true, TestFramework::CATCH2},
    {"REQUIRE_THROWS_AS\\s*\\(", AxiomType::EXCEPTION, 0.85, true, TestFramework::CATCH2},
    {"REQUIRE_THROWS_WITH\\s*\\(", AxiomType::EXCEPTION, 0.85, true, TestFramework::CATCH2},
    {"REQUIRE_NOTHROW\\s*\\(", AxiomType::CONSTRAINT, 0.85, true, TestFramework::CATCH2},

    // CHECK variants - non-fatal assertions (lower confidence)
    {"CHECK\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::CATCH2},
    {"CHECK_FALSE\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::CATCH2},
    {"CHECK_THROWS\\s*\\(", AxiomType::EXCEPTION, 0.80, false, TestFramework::CATCH2},
    {"CHECK_THROWS_AS\\s*\\(", AxiomType::EXCEPTION, 0.80, false, TestFramework::CATCH2},
    {"CHECK_NOTHROW\\s*\\(", AxiomType::CONSTRAINT, 0.80, false, TestFramework::CATCH2},
};

// GoogleTest patterns
const std::vector<AssertionPattern> GTEST_PATTERNS = {
    // ASSERT variants - fatal
    {"ASSERT_TRUE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::GTEST},
    {"ASSERT_FALSE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::GTEST},
    {"ASSERT_EQ\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::GTEST},
    {"ASSERT_NE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::GTEST},
    {"ASSERT_LT\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::GTEST},
    {"ASSERT_LE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::GTEST},
    {"ASSERT_GT\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::GTEST},
    {"ASSERT_GE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::GTEST},
    {"ASSERT_THROW\\s*\\(", AxiomType::EXCEPTION, 0.85, true, TestFramework::GTEST},
    {"ASSERT_NO_THROW\\s*\\(", AxiomType::CONSTRAINT, 0.85, true, TestFramework::GTEST},

    // EXPECT variants - non-fatal (lower confidence)
    {"EXPECT_TRUE\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::GTEST},
    {"EXPECT_FALSE\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::GTEST},
    {"EXPECT_EQ\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::GTEST},
    {"EXPECT_NE\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::GTEST},
    {"EXPECT_LT\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::GTEST},
    {"EXPECT_LE\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::GTEST},
    {"EXPECT_GT\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::GTEST},
    {"EXPECT_GE\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::GTEST},
    {"EXPECT_THROW\\s*\\(", AxiomType::EXCEPTION, 0.80, false, TestFramework::GTEST},
    {"EXPECT_NO_THROW\\s*\\(", AxiomType::CONSTRAINT, 0.80, false, TestFramework::GTEST},
};

// Boost.Test patterns
const std::vector<AssertionPattern> BOOST_TEST_PATTERNS = {
    // BOOST_REQUIRE variants - fatal
    {"BOOST_REQUIRE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::BOOST_TEST},
    {"BOOST_REQUIRE_EQUAL\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::BOOST_TEST},
    {"BOOST_REQUIRE_NE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::BOOST_TEST},
    {"BOOST_REQUIRE_LT\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::BOOST_TEST},
    {"BOOST_REQUIRE_LE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::BOOST_TEST},
    {"BOOST_REQUIRE_GT\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::BOOST_TEST},
    {"BOOST_REQUIRE_GE\\s*\\(", AxiomType::POSTCONDITION, 0.85, true, TestFramework::BOOST_TEST},
    {"BOOST_REQUIRE_THROW\\s*\\(", AxiomType::EXCEPTION, 0.85, true, TestFramework::BOOST_TEST},
    {"BOOST_REQUIRE_NO_THROW\\s*\\(", AxiomType::CONSTRAINT, 0.85, true, TestFramework::BOOST_TEST},

    // BOOST_CHECK variants - non-fatal (lower confidence)
    {"BOOST_CHECK\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::BOOST_TEST},
    {"BOOST_CHECK_EQUAL\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::BOOST_TEST},
    {"BOOST_CHECK_NE\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::BOOST_TEST},
    {"BOOST_CHECK_LT\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::BOOST_TEST},
    {"BOOST_CHECK_LE\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::BOOST_TEST},
    {"BOOST_CHECK_GT\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::BOOST_TEST},
    {"BOOST_CHECK_GE\\s*\\(", AxiomType::POSTCONDITION, 0.80, false, TestFramework::BOOST_TEST},
    {"BOOST_CHECK_THROW\\s*\\(", AxiomType::EXCEPTION, 0.80, false, TestFramework::BOOST_TEST},
    {"BOOST_CHECK_NO_THROW\\s*\\(", AxiomType::CONSTRAINT, 0.80, false, TestFramework::BOOST_TEST},
};


// AST Visitor for extracting test assertions
class TestAssertVisitor : public clang::RecursiveASTVisitor<TestAssertVisitor> {
public:
    TestAssertVisitor(clang::ASTContext& ctx, TestFramework requested_framework)
        : ctx_(ctx)
        , sm_(ctx.getSourceManager())
        , requested_framework_(requested_framework)
        , detected_framework_(TestFramework::AUTO) {}

    bool VisitCallExpr(clang::CallExpr* call) {
        if (!call)
            return true;

        auto loc = call->getBeginLoc();
        if (!loc.isValid() || sm_.isInSystemHeader(loc))
            return true;

        // Get the callee expression
        clang::Expr* callee = call->getCallee();
        if (!callee)
            return true;

        // Try to extract the function name being called
        std::string calleeStr;
        if (auto* declRef = clang::dyn_cast<clang::DeclRefExpr>(callee->IgnoreParenCasts())) {
            if (auto* fn = declRef->getDecl()) {
                calleeStr = fn->getQualifiedNameAsString();
            }
        } else if (auto* memberCall = clang::dyn_cast<clang::CXXMemberCallExpr>(call)) {
            if (auto* method = memberCall->getMethodDecl()) {
                calleeStr = method->getQualifiedNameAsString();
            }
        }

        // Check for framework namespace patterns
        checkForFrameworkCall(calleeStr, call);

        return true;
    }

    // Visit function declarations to find test case functions
    bool VisitFunctionDecl(clang::FunctionDecl* func) {
        if (!func || !func->hasBody())
            return true;

        auto loc = func->getLocation();
        if (!loc.isValid() || sm_.isInSystemHeader(loc))
            return true;

        std::string funcName = func->getQualifiedNameAsString();

        // Detect test case patterns
        // Catch2: TEST_CASE expands to a function
        // GTest: TEST() expands to a class with TestBody method
        // Boost: BOOST_AUTO_TEST_CASE expands to a function

        if (funcName.find("____C_A_T_C_H____") != std::string::npos ||
            funcName.find("CATCH2_INTERNAL") != std::string::npos) {
            detected_framework_ = TestFramework::CATCH2;
            current_test_name_ = extractCatch2TestName(funcName);
        } else if (funcName.find("_Test::TestBody") != std::string::npos ||
                   funcName.find("testing::Test") != std::string::npos) {
            detected_framework_ = TestFramework::GTEST;
            current_test_name_ = extractGTestName(funcName);
        } else if (funcName.find("boost_auto_test") != std::string::npos ||
                   funcName.find("BOOST_AUTO_TEST") != std::string::npos) {
            detected_framework_ = TestFramework::BOOST_TEST;
            current_test_name_ = extractBoostTestName(funcName);
        }

        current_function_ = func;
        return true;
    }

    std::vector<TestAssertion> getAssertions() const { return assertions_; }
    TestFramework getDetectedFramework() const { return detected_framework_; }

private:
    void checkForFrameworkCall(const std::string& callee, clang::CallExpr* call) {
        // Check Catch2 namespace patterns
        for (const auto& ns : CATCH2_NAMESPACES) {
            if (callee.find(ns) != std::string::npos) {
                detected_framework_ = TestFramework::CATCH2;
                extractCatch2Assertion(call);
                return;
            }
        }

        // Check GoogleTest namespace patterns
        for (const auto& ns : GTEST_NAMESPACES) {
            if (callee.find(ns) != std::string::npos) {
                detected_framework_ = TestFramework::GTEST;
                extractGTestAssertion(call);
                return;
            }
        }

        // Check Boost.Test namespace patterns
        for (const auto& ns : BOOST_TEST_NAMESPACES) {
            if (callee.find(ns) != std::string::npos) {
                detected_framework_ = TestFramework::BOOST_TEST;
                extractBoostTestAssertion(call);
                return;
            }
        }
    }

    void extractCatch2Assertion(clang::CallExpr* call) {
        // Get the source text around the call to find the macro pattern
        auto loc = call->getBeginLoc();
        int line = sm_.getSpellingLineNumber(loc);

        TestAssertion assertion;
        assertion.line = line;
        assertion.framework = TestFramework::CATCH2;
        assertion.test_name = current_test_name_;

        // Extract condition from call arguments
        if (call->getNumArgs() > 0) {
            assertion.condition = getExprAsString(call->getArg(0));
        }

        // Determine assertion type from expanded code patterns
        // Catch2's REQUIRE expands to code with ResultDisposition::Normal for fatal
        // and ResultDisposition::ContinueOnFailure for non-fatal
        std::string sourceText = getSourceTextAround(loc, 200);
        if (sourceText.find("ResultDisposition::Normal") != std::string::npos) {
            assertion.is_fatal = true;
            assertion.confidence = 0.85;
        } else {
            assertion.is_fatal = false;
            assertion.confidence = 0.80;
        }

        // Detect throws assertions
        if (sourceText.find("THROWS") != std::string::npos ||
            sourceText.find("throws") != std::string::npos) {
            assertion.axiom_type = AxiomType::EXCEPTION;
            extractExceptionType(sourceText, assertion);
        } else if (sourceText.find("NOTHROW") != std::string::npos) {
            assertion.axiom_type = AxiomType::CONSTRAINT;
        } else {
            assertion.axiom_type = AxiomType::POSTCONDITION;
        }

        // Try to extract the function being tested
        assertion.function_tested = extractTestedFunction(call);

        assertions_.push_back(assertion);
    }

    void extractGTestAssertion(clang::CallExpr* call) {
        auto loc = call->getBeginLoc();
        int line = sm_.getSpellingLineNumber(loc);

        TestAssertion assertion;
        assertion.line = line;
        assertion.framework = TestFramework::GTEST;
        assertion.test_name = current_test_name_;

        if (call->getNumArgs() > 0) {
            assertion.condition = getExprAsString(call->getArg(0));
        }

        std::string sourceText = getSourceTextAround(loc, 200);

        // GTest uses GTEST_FATAL_FAILURE_ for ASSERT and GTEST_NONFATAL_FAILURE_ for EXPECT
        if (sourceText.find("FATAL_FAILURE") != std::string::npos ||
            sourceText.find("ASSERT_") != std::string::npos) {
            assertion.is_fatal = true;
            assertion.confidence = 0.85;
        } else {
            assertion.is_fatal = false;
            assertion.confidence = 0.80;
        }

        if (sourceText.find("THROW") != std::string::npos) {
            assertion.axiom_type = AxiomType::EXCEPTION;
            extractExceptionType(sourceText, assertion);
        } else if (sourceText.find("NO_THROW") != std::string::npos) {
            assertion.axiom_type = AxiomType::CONSTRAINT;
        } else {
            assertion.axiom_type = AxiomType::POSTCONDITION;
        }

        assertion.function_tested = extractTestedFunction(call);
        assertions_.push_back(assertion);
    }

    void extractBoostTestAssertion(clang::CallExpr* call) {
        auto loc = call->getBeginLoc();
        int line = sm_.getSpellingLineNumber(loc);

        TestAssertion assertion;
        assertion.line = line;
        assertion.framework = TestFramework::BOOST_TEST;
        assertion.test_name = current_test_name_;

        if (call->getNumArgs() > 0) {
            assertion.condition = getExprAsString(call->getArg(0));
        }

        std::string sourceText = getSourceTextAround(loc, 200);

        // Boost uses BOOST_REQUIRE for fatal, BOOST_CHECK for non-fatal
        if (sourceText.find("REQUIRE") != std::string::npos) {
            assertion.is_fatal = true;
            assertion.confidence = 0.85;
        } else {
            assertion.is_fatal = false;
            assertion.confidence = 0.80;
        }

        if (sourceText.find("THROW") != std::string::npos) {
            assertion.axiom_type = AxiomType::EXCEPTION;
            extractExceptionType(sourceText, assertion);
        } else if (sourceText.find("NO_THROW") != std::string::npos) {
            assertion.axiom_type = AxiomType::CONSTRAINT;
        } else {
            assertion.axiom_type = AxiomType::POSTCONDITION;
        }

        assertion.function_tested = extractTestedFunction(call);
        assertions_.push_back(assertion);
    }

    std::string extractTestedFunction(clang::CallExpr* assertionCall) {
        // Look for function calls within the assertion's arguments
        // e.g., REQUIRE(foo(x) == expected) should extract "foo"
        if (assertionCall->getNumArgs() == 0)
            return "";

        // Traverse the first argument looking for call expressions
        class FunctionFinder : public clang::RecursiveASTVisitor<FunctionFinder> {
        public:
            std::string found_function;

            bool VisitCallExpr(clang::CallExpr* call) {
                if (auto* fn = call->getDirectCallee()) {
                    found_function = fn->getNameAsString();
                    return false; // Stop at first function found
                }
                return true;
            }
        };

        FunctionFinder finder;
        finder.TraverseStmt(assertionCall->getArg(0));
        return finder.found_function;
    }

    void extractExceptionType(const std::string& sourceText, TestAssertion& assertion) {
        // Try to extract exception type from patterns like:
        // REQUIRE_THROWS_AS(..., std::invalid_argument)
        // ASSERT_THROW(..., std::out_of_range)
        std::regex exceptionPattern(R"((std::\w+|[\w:]+Exception|[\w:]+Error))");
        std::smatch match;
        if (std::regex_search(sourceText, match, exceptionPattern)) {
            assertion.condition += " throws " + match[1].str();
        }
    }

    std::string extractCatch2TestName(const std::string& funcName) {
        // Extract test name from Catch2's mangled function name
        // Pattern: ____C_A_T_C_H____T_E_S_T____<number>
        return funcName;  // Simplified - would need more parsing
    }

    std::string extractGTestName(const std::string& funcName) {
        // Extract from pattern like "TestSuite_TestName_Test::TestBody"
        auto pos = funcName.rfind("_Test::TestBody");
        if (pos != std::string::npos) {
            return funcName.substr(0, pos);
        }
        return funcName;
    }

    std::string extractBoostTestName(const std::string& funcName) {
        return funcName;  // Simplified
    }

    std::string getExprAsString(clang::Expr* expr) {
        if (!expr)
            return "";

        std::string result;
        llvm::raw_string_ostream stream(result);
        expr->printPretty(stream, nullptr, ctx_.getPrintingPolicy());
        return result;
    }

    std::string getSourceTextAround(clang::SourceLocation loc, unsigned chars) {
        if (!loc.isValid())
            return "";

        // Get spelling location to handle macro expansions
        loc = sm_.getSpellingLoc(loc);

        const char* begin = sm_.getCharacterData(loc);
        if (!begin)
            return "";

        // Get a window of source text
        std::string result(begin, std::min(chars, (unsigned)strlen(begin)));
        return result;
    }

    clang::ASTContext& ctx_;
    clang::SourceManager& sm_;
    TestFramework requested_framework_;
    TestFramework detected_framework_;
    std::string current_test_name_;
    clang::FunctionDecl* current_function_ = nullptr;
    std::vector<TestAssertion> assertions_;
};


// Implementation of TestAssertExtractor
class TestAssertExtractorImpl : public TestAssertExtractor {
public:
    TestAssertExtractorImpl(TestFramework framework)
        : framework_(framework) {}

    std::vector<TestAssertion> extractAssertions(clang::ASTContext& ctx) override {
        TestAssertVisitor visitor(ctx, framework_);
        visitor.TraverseDecl(ctx.getTranslationUnitDecl());
        return visitor.getAssertions();
    }

    std::vector<Axiom> toAxioms(const std::vector<TestAssertion>& assertions) override {
        std::vector<Axiom> axioms;
        axioms.reserve(assertions.size());

        for (const auto& assertion : assertions) {
            Axiom axiom;

            // Generate ID
            axiom.id = "test." + assertion.test_name + ".line" +
                       std::to_string(assertion.line);

            // Generate content based on assertion type
            switch (assertion.axiom_type) {
                case AxiomType::POSTCONDITION:
                    if (!assertion.function_tested.empty()) {
                        axiom.content = assertion.function_tested +
                                       " satisfies: " + assertion.condition;
                    } else {
                        axiom.content = "Postcondition: " + assertion.condition;
                    }
                    break;

                case AxiomType::EXCEPTION:
                    axiom.content = "Throws exception: " + assertion.condition;
                    break;

                case AxiomType::CONSTRAINT:
                    axiom.content = "Does not throw (noexcept behavior)";
                    break;

                default:
                    axiom.content = assertion.condition;
            }

            axiom.formal_spec = assertion.condition;
            axiom.function = assertion.function_tested;
            axiom.header = "";  // Would need source file info
            axiom.axiom_type = assertion.axiom_type;
            axiom.confidence = assertion.confidence;
            axiom.source_type = SourceType::PATTERN;
            axiom.line = assertion.line;

            axioms.push_back(std::move(axiom));
        }

        return axioms;
    }

private:
    TestFramework framework_;
};

} // anonymous namespace

std::unique_ptr<TestAssertExtractor> createTestAssertExtractor(TestFramework framework) {
    return std::make_unique<TestAssertExtractorImpl>(framework);
}

} // namespace axiom
