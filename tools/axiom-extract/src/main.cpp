// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "Axiom.h"
#include "Extractors.h"
#include "IgnoreFilter.h"

#include <clang/ASTMatchers/ASTMatchFinder.h>
#include <clang/ASTMatchers/ASTMatchers.h>
#include <clang/Frontend/FrontendActions.h>
#include <clang/Tooling/CommonOptionsParser.h>
#include <clang/Tooling/Tooling.h>
#include <llvm/Support/CommandLine.h>

#include <chrono>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <sstream>

using namespace clang;
using namespace clang::ast_matchers;
using namespace clang::tooling;

// Command line options
static llvm::cl::OptionCategory AxiomExtractCategory("axiom-extract options");

static llvm::cl::opt<std::string> OutputFile(
    "o",
    llvm::cl::desc("Output JSON file (default: stdout)"),
    llvm::cl::value_desc("filename"),
    llvm::cl::cat(AxiomExtractCategory)
);

static llvm::cl::opt<bool> Verbose(
    "v",
    llvm::cl::desc("Verbose output"),
    llvm::cl::cat(AxiomExtractCategory)
);

static llvm::cl::opt<bool> ExtractHazards(
    "hazards",
    llvm::cl::desc("Extract hazard-based preconditions (requires CFG analysis)"),
    llvm::cl::init(true),
    llvm::cl::cat(AxiomExtractCategory)
);

static llvm::cl::opt<std::string> IgnoreFilePath(
    "ignore",
    llvm::cl::desc("Path to .axignore file (auto-detected if not specified)"),
    llvm::cl::value_desc("filename"),
    llvm::cl::cat(AxiomExtractCategory)
);

static llvm::cl::opt<bool> NoIgnore(
    "no-ignore",
    llvm::cl::desc("Disable .axignore filtering"),
    llvm::cl::cat(AxiomExtractCategory)
);

// Global ignore filter (set up in main)
static axiom::IgnoreFilter* globalIgnoreFilter = nullptr;
static std::string globalProjectRoot;

namespace {

// Callback for matching function declarations
class FunctionCallback : public MatchFinder::MatchCallback {
public:
    FunctionCallback(std::vector<axiom::ExtractionResult>& results,
                     axiom::ConstraintExtractor& constraintExtractor,
                     axiom::HazardDetector* hazardDetector)
        : results_(results)
        , constraintExtractor_(constraintExtractor)
        , hazardDetector_(hazardDetector) {}

    void run(const MatchFinder::MatchResult& result) override {
        const auto* func = result.Nodes.getNodeAs<FunctionDecl>("func");
        if (!func || !func->isThisDeclarationADefinition())
            return;

        // Get source file
        auto& sm = result.Context->getSourceManager();
        auto loc = func->getLocation();
        if (!loc.isValid() || sm.isInSystemHeader(loc))
            return;

        std::string filename = sm.getFilename(loc).str();
        if (filename.empty())
            return;

        // Check if file should be ignored based on .axignore
        if (globalIgnoreFilter && globalIgnoreFilter->shouldIgnore(filename, globalProjectRoot)) {
            if (Verbose) {
                llvm::errs() << "Ignoring file (matched .axignore): " << filename << "\n";
            }
            return;
        }

        // Find or create result for this file
        auto it = std::find_if(results_.begin(), results_.end(),
            [&filename](const axiom::ExtractionResult& r) {
                return r.source_file == filename;
            });

        if (it == results_.end()) {
            results_.push_back({filename, {}, {}});
            it = results_.end() - 1;
        }

        // Extract function info
        axiom::FunctionInfo info;
        info.name = func->getNameAsString();
        info.qualified_name = func->getQualifiedNameAsString();
        info.line_start = sm.getSpellingLineNumber(func->getBeginLoc());
        info.line_end = sm.getSpellingLineNumber(func->getEndLoc());
        info.decl = func;

        // Build signature
        std::string sig;
        llvm::raw_string_ostream sigStream(sig);
        func->print(sigStream);
        info.signature = sig;

        // Extract header from filename
        size_t lastSlash = filename.rfind('/');
        info.header = (lastSlash != std::string::npos)
            ? filename.substr(lastSlash + 1)
            : filename;

        // Check C++20 attributes
        // Note: isNothrow() can crash on dependent noexcept specs in templates,
        // so we check if the exception spec is dependent first
        if (const auto* proto = func->getType()->getAs<FunctionProtoType>()) {
            auto exSpec = proto->getExceptionSpecType();
            // Only call isNothrow() if spec is non-dependent
            if (exSpec != clang::EST_DependentNoexcept &&
                exSpec != clang::EST_Unevaluated &&
                exSpec != clang::EST_Uninstantiated) {
                info.is_noexcept = proto->isNothrow();
            }
        }

        // Check if it's a const method (only for CXXMethodDecl)
        if (const auto* method = llvm::dyn_cast<CXXMethodDecl>(func)) {
            info.is_const = method->isConst();
        }
        info.is_constexpr = func->isConstexpr();
        info.is_consteval = func->isConsteval();
        info.is_deleted = func->isDeleted();
        info.is_defaulted = func->isDefaulted();

        // Check for [[nodiscard]] attribute
        if (func->hasAttr<WarnUnusedResultAttr>()) {
            info.is_nodiscard = true;
        }

        // Check for [[deprecated]] attribute
        if (func->hasAttr<DeprecatedAttr>()) {
            info.is_deprecated = true;
        }

        // Check for [[likely]]/[[unlikely]] in function body (C++20)
        // These are statement attributes, detected during body analysis

        // Check for requires clause (C++20 concepts)
        // Check trailing requires clause on the function itself
        if (auto* req = func->getTrailingRequiresClause()) {
            std::string reqStr;
            llvm::raw_string_ostream reqStream(reqStr);
            req->printPretty(reqStream, nullptr, result.Context->getPrintingPolicy());
            info.requires_clause = reqStr;
        }

        // Extract constraints to axioms
        auto axioms = constraintExtractor_.extractConstraints(info);
        for (auto& axiom : axioms) {
            it->axioms.push_back(std::move(axiom));
        }

        // Extract hazard-based axioms if enabled
        if (hazardDetector_ && func->hasBody()) {
            auto hazards = hazardDetector_->detectHazards(func, *result.Context);
            for (const auto& hazard : hazards) {
                if (!hazard.has_guard) {
                    // Unguarded hazard becomes a precondition
                    axiom::Axiom axiom;
                    axiom.id = info.qualified_name + ".precond." +
                        (hazard.type == axiom::HazardType::DIVISION ? "divisor_nonzero" :
                         hazard.type == axiom::HazardType::POINTER_DEREF ? "ptr_valid" :
                         "bounds_check");
                    axiom.function = info.qualified_name;
                    axiom.signature = info.signature;
                    axiom.header = info.header;
                    axiom.axiom_type = axiom::AxiomType::PRECONDITION;
                    axiom.confidence = 0.95;
                    axiom.source_type = axiom::SourceType::PATTERN;
                    axiom.line = hazard.line;
                    axiom.hazard_type = hazard.type;
                    axiom.hazard_line = hazard.line;
                    axiom.has_guard = false;

                    if (hazard.type == axiom::HazardType::DIVISION) {
                        axiom.content = "Divisor " + hazard.operand + " must not be zero";
                        axiom.formal_spec = hazard.operand + " != 0";
                    } else if (hazard.type == axiom::HazardType::POINTER_DEREF) {
                        axiom.content = "Pointer " + hazard.operand + " must not be null";
                        axiom.formal_spec = hazard.operand + " != nullptr";
                    } else if (hazard.type == axiom::HazardType::ARRAY_ACCESS) {
                        axiom.content = "Index must be within bounds for " + hazard.expression;
                        axiom.formal_spec = "0 <= index && index < size";
                    }

                    it->axioms.push_back(std::move(axiom));
                }
            }
        }

        if (Verbose) {
            llvm::errs() << "Extracted " << it->axioms.size()
                        << " axioms from " << info.qualified_name << "\n";
        }
    }

private:
    std::vector<axiom::ExtractionResult>& results_;
    axiom::ConstraintExtractor& constraintExtractor_;
    axiom::HazardDetector* hazardDetector_;
};

// Callback for matching class/struct declarations
class ClassCallback : public MatchFinder::MatchCallback {
public:
    ClassCallback(std::vector<axiom::ExtractionResult>& results)
        : results_(results) {}

    void run(const MatchFinder::MatchResult& result) override {
        const auto* decl = result.Nodes.getNodeAs<CXXRecordDecl>("class");
        if (!decl || !decl->isThisDeclarationADefinition())
            return;

        auto& sm = result.Context->getSourceManager();
        auto loc = decl->getLocation();
        if (!loc.isValid() || sm.isInSystemHeader(loc))
            return;

        std::string filename = sm.getFilename(loc).str();
        if (filename.empty())
            return;

        if (globalIgnoreFilter && globalIgnoreFilter->shouldIgnore(filename, globalProjectRoot))
            return;

        // Find or create result for this file
        auto it = std::find_if(results_.begin(), results_.end(),
            [&filename](const axiom::ExtractionResult& r) {
                return r.source_file == filename;
            });
        if (it == results_.end()) {
            results_.push_back({filename, {}, {}});
            it = results_.end() - 1;
        }

        std::string name = decl->getNameAsString();
        std::string qualName = decl->getQualifiedNameAsString();
        size_t lastSlash = filename.rfind('/');
        std::string header = (lastSlash != std::string::npos)
            ? filename.substr(lastSlash + 1) : filename;
        int line = sm.getSpellingLineNumber(loc);

        // Extract class properties as axioms
        if (decl->hasAttr<FinalAttr>()) {
            axiom::Axiom ax;
            ax.id = qualName + ".final";
            ax.content = name + " cannot be inherited from (final class)";
            ax.formal_spec = "is_final(" + name + ")";
            ax.function = qualName;
            ax.header = header;
            ax.axiom_type = axiom::AxiomType::CONSTRAINT;
            ax.confidence = 1.0;
            ax.source_type = axiom::SourceType::EXPLICIT;
            ax.line = line;
            it->axioms.push_back(std::move(ax));
        }

        if (decl->isAbstract()) {
            axiom::Axiom ax;
            ax.id = qualName + ".abstract";
            ax.content = name + " is abstract and cannot be instantiated directly";
            ax.formal_spec = "is_abstract(" + name + ")";
            ax.function = qualName;
            ax.header = header;
            ax.axiom_type = axiom::AxiomType::CONSTRAINT;
            ax.confidence = 1.0;
            ax.source_type = axiom::SourceType::EXPLICIT;
            ax.line = line;
            it->axioms.push_back(std::move(ax));
        }

        // Check for virtual destructor
        if (const auto* dtor = decl->getDestructor()) {
            if (dtor->isVirtual()) {
                axiom::Axiom ax;
                ax.id = qualName + ".virtual_dtor";
                ax.content = name + " has virtual destructor (safe for polymorphic use)";
                ax.formal_spec = "has_virtual_destructor(" + name + ")";
                ax.function = qualName;
                ax.header = header;
                ax.axiom_type = axiom::AxiomType::CONSTRAINT;
                ax.confidence = 1.0;
                ax.source_type = axiom::SourceType::EXPLICIT;
                ax.line = line;
                it->axioms.push_back(std::move(ax));
            }
        }

        // Trivially copyable/destructible - useful for memcpy safety
        if (decl->isTriviallyCopyable()) {
            axiom::Axiom ax;
            ax.id = qualName + ".trivially_copyable";
            ax.content = name + " is trivially copyable (safe for memcpy/memmove)";
            ax.formal_spec = "is_trivially_copyable(" + name + ")";
            ax.function = qualName;
            ax.header = header;
            ax.axiom_type = axiom::AxiomType::CONSTRAINT;
            ax.confidence = 1.0;
            ax.source_type = axiom::SourceType::EXPLICIT;
            ax.line = line;
            it->axioms.push_back(std::move(ax));
        }

        if (Verbose) {
            llvm::errs() << "Extracted class: " << qualName << "\n";
        }
    }

private:
    std::vector<axiom::ExtractionResult>& results_;
};

// Callback for matching enum declarations
class EnumCallback : public MatchFinder::MatchCallback {
public:
    EnumCallback(std::vector<axiom::ExtractionResult>& results)
        : results_(results) {}

    void run(const MatchFinder::MatchResult& result) override {
        const auto* decl = result.Nodes.getNodeAs<EnumDecl>("enum");
        if (!decl || !decl->isThisDeclarationADefinition())
            return;

        auto& sm = result.Context->getSourceManager();
        auto loc = decl->getLocation();
        if (!loc.isValid() || sm.isInSystemHeader(loc))
            return;

        std::string filename = sm.getFilename(loc).str();
        if (filename.empty())
            return;

        if (globalIgnoreFilter && globalIgnoreFilter->shouldIgnore(filename, globalProjectRoot))
            return;

        auto it = std::find_if(results_.begin(), results_.end(),
            [&filename](const axiom::ExtractionResult& r) {
                return r.source_file == filename;
            });
        if (it == results_.end()) {
            results_.push_back({filename, {}, {}});
            it = results_.end() - 1;
        }

        std::string name = decl->getNameAsString();
        std::string qualName = decl->getQualifiedNameAsString();
        size_t lastSlash = filename.rfind('/');
        std::string header = (lastSlash != std::string::npos)
            ? filename.substr(lastSlash + 1) : filename;
        int line = sm.getSpellingLineNumber(loc);

        // Scoped enum (enum class)
        if (decl->isScoped()) {
            axiom::Axiom ax;
            ax.id = qualName + ".scoped";
            ax.content = name + " is a scoped enum (enum class) - values require qualification";
            ax.formal_spec = "is_scoped_enum(" + name + ")";
            ax.function = qualName;
            ax.header = header;
            ax.axiom_type = axiom::AxiomType::CONSTRAINT;
            ax.confidence = 1.0;
            ax.source_type = axiom::SourceType::EXPLICIT;
            ax.line = line;
            it->axioms.push_back(std::move(ax));
        }

        if (Verbose) {
            llvm::errs() << "Extracted enum: " << qualName << "\n";
        }
    }

private:
    std::vector<axiom::ExtractionResult>& results_;
};

// Callback for matching static_assert declarations
class StaticAssertCallback : public MatchFinder::MatchCallback {
public:
    StaticAssertCallback(std::vector<axiom::ExtractionResult>& results)
        : results_(results) {}

    void run(const MatchFinder::MatchResult& result) override {
        const auto* decl = result.Nodes.getNodeAs<StaticAssertDecl>("static_assert");
        if (!decl)
            return;

        auto& sm = result.Context->getSourceManager();
        auto loc = decl->getLocation();
        if (!loc.isValid() || sm.isInSystemHeader(loc))
            return;

        std::string filename = sm.getFilename(loc).str();
        if (filename.empty())
            return;

        if (globalIgnoreFilter && globalIgnoreFilter->shouldIgnore(filename, globalProjectRoot))
            return;

        auto it = std::find_if(results_.begin(), results_.end(),
            [&filename](const axiom::ExtractionResult& r) {
                return r.source_file == filename;
            });
        if (it == results_.end()) {
            results_.push_back({filename, {}, {}});
            it = results_.end() - 1;
        }

        size_t lastSlash = filename.rfind('/');
        std::string header = (lastSlash != std::string::npos)
            ? filename.substr(lastSlash + 1) : filename;
        int line = sm.getSpellingLineNumber(loc);

        // Get the assertion expression
        std::string condStr;
        if (auto* cond = decl->getAssertExpr()) {
            llvm::raw_string_ostream condStream(condStr);
            cond->printPretty(condStream, nullptr, result.Context->getPrintingPolicy());
        }

        // Get the message if present
        std::string message;
        if (auto msg = decl->getMessage()) {
            // getMessage returns StringLiteral* in newer Clang
            if (auto* strLit = llvm::dyn_cast<StringLiteral>(msg)) {
                message = strLit->getString().str();
            }
        }

        axiom::Axiom ax;
        ax.id = header + ".static_assert." + std::to_string(line);
        ax.content = message.empty()
            ? "Static assertion: " + condStr
            : message;
        ax.formal_spec = condStr;
        ax.function = "";
        ax.header = header;
        ax.axiom_type = axiom::AxiomType::INVARIANT;
        ax.confidence = 1.0;
        ax.source_type = axiom::SourceType::EXPLICIT;
        ax.line = line;
        it->axioms.push_back(std::move(ax));

        if (Verbose) {
            llvm::errs() << "Extracted static_assert at line " << line << "\n";
        }
    }

private:
    std::vector<axiom::ExtractionResult>& results_;
};

// Callback for matching concept declarations (C++20)
class ConceptCallback : public MatchFinder::MatchCallback {
public:
    ConceptCallback(std::vector<axiom::ExtractionResult>& results)
        : results_(results) {}

    void run(const MatchFinder::MatchResult& result) override {
        const auto* decl = result.Nodes.getNodeAs<ConceptDecl>("concept");
        if (!decl)
            return;

        auto& sm = result.Context->getSourceManager();
        auto loc = decl->getLocation();
        if (!loc.isValid() || sm.isInSystemHeader(loc))
            return;

        std::string filename = sm.getFilename(loc).str();
        if (filename.empty())
            return;

        if (globalIgnoreFilter && globalIgnoreFilter->shouldIgnore(filename, globalProjectRoot))
            return;

        auto it = std::find_if(results_.begin(), results_.end(),
            [&filename](const axiom::ExtractionResult& r) {
                return r.source_file == filename;
            });
        if (it == results_.end()) {
            results_.push_back({filename, {}, {}});
            it = results_.end() - 1;
        }

        std::string name = decl->getNameAsString();
        std::string qualName = decl->getQualifiedNameAsString();
        size_t lastSlash = filename.rfind('/');
        std::string header = (lastSlash != std::string::npos)
            ? filename.substr(lastSlash + 1) : filename;
        int line = sm.getSpellingLineNumber(loc);

        // Get the constraint expression
        std::string constraintStr;
        if (auto* constraint = decl->getConstraintExpr()) {
            llvm::raw_string_ostream cStream(constraintStr);
            constraint->printPretty(cStream, nullptr, result.Context->getPrintingPolicy());
        }

        axiom::Axiom ax;
        ax.id = qualName + ".concept";
        ax.content = "Concept " + name + " requires: " + constraintStr;
        ax.formal_spec = constraintStr;
        ax.function = qualName;
        ax.header = header;
        ax.axiom_type = axiom::AxiomType::CONSTRAINT;
        ax.confidence = 1.0;
        ax.source_type = axiom::SourceType::EXPLICIT;
        ax.line = line;
        it->axioms.push_back(std::move(ax));

        if (Verbose) {
            llvm::errs() << "Extracted concept: " << qualName << "\n";
        }
    }

private:
    std::vector<axiom::ExtractionResult>& results_;
};

// Callback for matching type alias declarations (using/typedef)
class TypeAliasCallback : public MatchFinder::MatchCallback {
public:
    TypeAliasCallback(std::vector<axiom::ExtractionResult>& results)
        : results_(results) {}

    void run(const MatchFinder::MatchResult& result) override {
        const auto* decl = result.Nodes.getNodeAs<TypeAliasDecl>("alias");
        if (!decl)
            return;

        auto& sm = result.Context->getSourceManager();
        auto loc = decl->getLocation();
        if (!loc.isValid() || sm.isInSystemHeader(loc))
            return;

        std::string filename = sm.getFilename(loc).str();
        if (filename.empty())
            return;

        if (globalIgnoreFilter && globalIgnoreFilter->shouldIgnore(filename, globalProjectRoot))
            return;

        auto it = std::find_if(results_.begin(), results_.end(),
            [&filename](const axiom::ExtractionResult& r) {
                return r.source_file == filename;
            });
        if (it == results_.end()) {
            results_.push_back({filename, {}, {}});
            it = results_.end() - 1;
        }

        std::string name = decl->getNameAsString();
        std::string qualName = decl->getQualifiedNameAsString();
        size_t lastSlash = filename.rfind('/');
        std::string header = (lastSlash != std::string::npos)
            ? filename.substr(lastSlash + 1) : filename;
        int line = sm.getSpellingLineNumber(loc);

        // Get the aliased type
        std::string aliasedType;
        auto type = decl->getUnderlyingType();
        if (!type.isNull()) {
            aliasedType = type.getAsString();
        }

        // Only create axiom if it's a meaningful type alias
        if (!aliasedType.empty()) {
            axiom::Axiom ax;
            ax.id = qualName + ".type_alias";
            ax.content = name + " is an alias for " + aliasedType;
            ax.formal_spec = "type(" + name + ") == " + aliasedType;
            ax.function = qualName;
            ax.header = header;
            ax.axiom_type = axiom::AxiomType::CONSTRAINT;
            ax.confidence = 1.0;
            ax.source_type = axiom::SourceType::EXPLICIT;
            ax.line = line;
            it->axioms.push_back(std::move(ax));

            if (Verbose) {
                llvm::errs() << "Extracted type alias: " << qualName << " = " << aliasedType << "\n";
            }
        }
    }

private:
    std::vector<axiom::ExtractionResult>& results_;
};

} // anonymous namespace

std::string getCurrentTimestamp() {
    auto now = std::chrono::system_clock::now();
    auto time = std::chrono::system_clock::to_time_t(now);
    std::stringstream ss;
    ss << std::put_time(std::gmtime(&time), "%Y-%m-%dT%H:%M:%SZ");
    return ss.str();
}

int main(int argc, const char** argv) {
    auto expectedParser = CommonOptionsParser::create(
        argc, argv, AxiomExtractCategory);

    if (!expectedParser) {
        llvm::errs() << expectedParser.takeError();
        return 1;
    }

    CommonOptionsParser& optionsParser = *expectedParser;
    ClangTool tool(optionsParser.getCompilations(),
                   optionsParser.getSourcePathList());

    // Set up ignore filter from .axignore
    axiom::IgnoreFilter ignoreFilter;
    if (!NoIgnore) {
        std::string axignorePath;

        if (!IgnoreFilePath.empty()) {
            axignorePath = IgnoreFilePath;
        } else if (!optionsParser.getSourcePathList().empty()) {
            // Auto-detect .axignore from first source file
            axignorePath = axiom::findAxignoreFile(optionsParser.getSourcePathList()[0]);
        }

        if (!axignorePath.empty()) {
            if (ignoreFilter.loadFromFile(axignorePath)) {
                globalIgnoreFilter = &ignoreFilter;
                globalProjectRoot = axiom::getProjectRoot(axignorePath);
                if (Verbose) {
                    llvm::errs() << "Loaded " << ignoreFilter.patternCount()
                                << " ignore patterns from " << axignorePath << "\n";
                    llvm::errs() << "Project root: " << globalProjectRoot << "\n";
                }
            } else if (!IgnoreFilePath.empty()) {
                llvm::errs() << "Warning: Could not load ignore file: " << axignorePath << "\n";
            }
        }
    }

    // Create extractors
    auto constraintExtractor = axiom::createConstraintExtractor();
    std::unique_ptr<axiom::HazardDetector> hazardDetector;
    if (ExtractHazards) {
        hazardDetector = axiom::createHazardDetector();
    }

    // Storage for results
    std::vector<axiom::ExtractionResult> results;

    // Set up matchers
    FunctionCallback funcCallback(results, *constraintExtractor, hazardDetector.get());
    ClassCallback classCallback(results);
    EnumCallback enumCallback(results);
    StaticAssertCallback staticAssertCallback(results);
    ConceptCallback conceptCallback(results);
    TypeAliasCallback typeAliasCallback(results);

    MatchFinder finder;

    // Match functions
    finder.addMatcher(
        functionDecl(isDefinition()).bind("func"),
        &funcCallback
    );

    // Match classes and structs
    finder.addMatcher(
        cxxRecordDecl(isDefinition()).bind("class"),
        &classCallback
    );

    // Match enums
    finder.addMatcher(
        enumDecl(isDefinition()).bind("enum"),
        &enumCallback
    );

    // Match static_assert declarations
    finder.addMatcher(
        staticAssertDecl().bind("static_assert"),
        &staticAssertCallback
    );

    // Match concept declarations (C++20)
    finder.addMatcher(
        conceptDecl().bind("concept"),
        &conceptCallback
    );

    // Match type alias declarations (using)
    finder.addMatcher(
        typeAliasDecl().bind("alias"),
        &typeAliasCallback
    );

    // Run the tool
    int exitCode = tool.run(newFrontendActionFactory(&finder).get());

    if (exitCode != 0) {
        llvm::errs() << "Error running clang tool\n";
        return exitCode;
    }

    // Build output JSON
    nlohmann::json output;
    output["version"] = "1.0";
    output["extracted_at"] = getCurrentTimestamp();
    output["files"] = results;

    // Count total axioms
    size_t totalAxioms = 0;
    for (const auto& result : results) {
        totalAxioms += result.axioms.size();
    }
    output["total_axioms"] = totalAxioms;

    // Add ignore filter info
    if (globalIgnoreFilter) {
        output["ignore_patterns"] = globalIgnoreFilter->patternCount();
        output["project_root"] = globalProjectRoot;
    }

    // Output
    std::string jsonStr = output.dump(2);

    if (OutputFile.empty()) {
        std::cout << jsonStr << std::endl;
    } else {
        std::ofstream out(OutputFile);
        if (!out) {
            llvm::errs() << "Error: Could not open output file: " << OutputFile << "\n";
            return 1;
        }
        out << jsonStr;
        if (Verbose) {
            llvm::errs() << "Wrote " << totalAxioms << " axioms to " << OutputFile << "\n";
        }
    }

    return 0;
}
