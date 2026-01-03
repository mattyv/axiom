// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "Axiom.h"
#include "Extractors.h"
#include "IgnoreFilter.h"

#include <clang/AST/DeclTemplate.h>
#include <clang/ASTMatchers/ASTMatchFinder.h>
#include <clang/ASTMatchers/ASTMatchers.h>
#include <clang/Frontend/CompilerInstance.h>
#include <clang/Frontend/FrontendActions.h>
#include <clang/Lex/MacroInfo.h>
#include <clang/Lex/PPCallbacks.h>
#include <clang/Lex/Preprocessor.h>
#include <clang/Tooling/CommonOptionsParser.h>
#include <clang/Tooling/Tooling.h>
#include <clang/Tooling/CompilationDatabase.h>
#include <llvm/Support/CommandLine.h>
#include <llvm/Support/FileSystem.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <ctime>
#include <fcntl.h>
#include <filesystem>
#include <future>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <regex>
#include <set>
#include <sstream>
#include <thread>
#include <unistd.h>

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

static llvm::cl::opt<bool> Quiet(
    "q",
    llvm::cl::desc("Suppress informational messages (compilation database warnings, etc.)"),
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

static llvm::cl::opt<bool> Recursive(
    "r",
    llvm::cl::desc("Recursively scan directories for C++ source files"),
    llvm::cl::cat(AxiomExtractCategory)
);

static llvm::cl::alias RecursiveAlias(
    "recursive",
    llvm::cl::desc("Alias for -r"),
    llvm::cl::aliasopt(Recursive)
);

static llvm::cl::opt<bool> ExtractCallGraph(
    "call-graph",
    llvm::cl::desc("Extract function call graph for precondition propagation"),
    llvm::cl::init(true),
    llvm::cl::cat(AxiomExtractCategory)
);

static llvm::cl::opt<bool> TestMode(
    "test-mode",
    llvm::cl::desc("Enable test mining mode to extract axioms from test assertions"),
    llvm::cl::init(false),
    llvm::cl::cat(AxiomExtractCategory)
);

static llvm::cl::opt<std::string> TestFrameworkOpt(
    "test-framework",
    llvm::cl::desc("Test framework to use (auto, catch2, gtest, boost). Default: auto"),
    llvm::cl::value_desc("framework"),
    llvm::cl::init("auto"),
    llvm::cl::cat(AxiomExtractCategory)
);

static llvm::cl::opt<unsigned> NumJobs(
    "j",
    llvm::cl::desc("Number of parallel jobs (default: number of CPU cores)"),
    llvm::cl::value_desc("N"),
    llvm::cl::init(0),
    llvm::cl::cat(AxiomExtractCategory)
);

// C++ source file extensions
const std::vector<std::string> CPP_EXTENSIONS = {
    ".cpp", ".cc", ".cxx", ".hpp", ".h", ".hxx", ".C", ".H"
};

// Check if a file has a C++ extension
bool isCppSourceFile(const std::filesystem::path& path) {
    std::string ext = path.extension().string();
    for (const auto& cppExt : CPP_EXTENSIONS) {
        if (ext == cppExt) return true;
    }
    return false;
}

// Helper to check if a path should be ignored based on mode
bool shouldIgnorePath(axiom::IgnoreFilter* filter, const std::string& path,
                      const std::string& projectRoot, bool testMode) {
    if (!filter) return false;
    return testMode ? filter->shouldIgnoreInTestMode(path, projectRoot)
                    : filter->shouldIgnore(path, projectRoot);
}

// Recursively find all C++ source files in a directory
std::vector<std::string> findSourceFiles(
    const std::string& path,
    bool recursive,
    axiom::IgnoreFilter* ignoreFilter = nullptr,
    const std::string& projectRoot = "",
    bool testMode = false
) {
    std::vector<std::string> files;
    std::filesystem::path fsPath(path);

    // If it's a file, just return it
    if (std::filesystem::is_regular_file(fsPath)) {
        if (isCppSourceFile(fsPath)) {
            std::string absPath = std::filesystem::absolute(fsPath).string();
            if (!shouldIgnorePath(ignoreFilter, absPath, projectRoot, testMode)) {
                files.push_back(absPath);
            }
        }
        return files;
    }

    // If it's a directory, scan for source files
    if (std::filesystem::is_directory(fsPath)) {
        auto iterator = recursive
            ? std::filesystem::recursive_directory_iterator(fsPath)
            : std::filesystem::recursive_directory_iterator(fsPath,
                std::filesystem::directory_options::none);

        // For non-recursive, we need to use a different approach
        if (recursive) {
            for (const auto& entry : std::filesystem::recursive_directory_iterator(fsPath)) {
                if (entry.is_regular_file() && isCppSourceFile(entry.path())) {
                    std::string absPath = std::filesystem::absolute(entry.path()).string();
                    if (!shouldIgnorePath(ignoreFilter, absPath, projectRoot, testMode)) {
                        files.push_back(absPath);
                    }
                }
            }
        } else {
            for (const auto& entry : std::filesystem::directory_iterator(fsPath)) {
                if (entry.is_regular_file() && isCppSourceFile(entry.path())) {
                    std::string absPath = std::filesystem::absolute(entry.path()).string();
                    if (!shouldIgnorePath(ignoreFilter, absPath, projectRoot, testMode)) {
                        files.push_back(absPath);
                    }
                }
            }
        }
    }

    // Sort for consistent output
    std::sort(files.begin(), files.end());
    return files;
}

// Global ignore filter (set up in main)
static axiom::IgnoreFilter* globalIgnoreFilter = nullptr;
static std::string globalProjectRoot;

// Global storage for call graph (collected across all files)
static std::vector<axiom::FunctionCall> globalCallGraph;

// Global storage for macros (collected across all files)
static std::vector<axiom::MacroDefinition> globalMacros;
static std::mutex globalMacrosMutex;

// Forward declarations for macro extraction
namespace axiom {
    std::vector<Axiom> extractMacroAxioms(const MacroDefinition& macro);
}

// Semantic patterns detected in macro bodies
struct MacroSemantics {
    bool has_lambda_capture = false;
    bool has_reference_capture = false;
    bool has_template_call = false;
    bool has_return_statement = false;
    bool is_incomplete = false;
    bool has_loop_construct = false;
    bool creates_local_vars = false;
    std::vector<std::string> local_vars;
    std::string template_param;
};

// Analyze macro body for hazardous operations
void analyzeMacroBody(const std::string& body, axiom::MacroDefinition& macro) {
    // Division: / not followed by / or * (avoid comments)
    std::regex divRegex(R"([^/]/[^/*]|%)");
    macro.has_division = std::regex_search(body, divRegex);

    // Pointer operations: * or & followed by identifier
    std::regex ptrRegex(R"(\*[a-zA-Z_]|&[a-zA-Z_])");
    macro.has_pointer_ops = std::regex_search(body, ptrRegex);

    // Cast expressions: (type) or (type*)
    std::regex castRegex(R"(\([a-zA-Z_][a-zA-Z_0-9]*\s*\*?\s*\))");
    macro.has_casts = std::regex_search(body, castRegex);

    // Function calls: identifier followed by (
    std::regex funcRegex(R"(\b([a-z_][a-zA-Z_0-9]*)\s*\()");
    std::smatch match;
    std::string::const_iterator searchStart = body.cbegin();
    std::set<std::string> keywords = {"if", "while", "for", "switch", "sizeof", "typeof", "alignof"};

    while (std::regex_search(searchStart, body.cend(), match, funcRegex)) {
        std::string funcName = match[1].str();
        if (keywords.find(funcName) == keywords.end()) {
            macro.function_calls.push_back(funcName);
        }
        searchStart = match.suffix().first;
    }

    // Macro references: UPPERCASE identifiers (3+ chars)
    std::regex macroRefRegex(R"(\b([A-Z_][A-Z_0-9]{2,})\b)");
    searchStart = body.cbegin();
    while (std::regex_search(searchStart, body.cend(), match, macroRefRegex)) {
        macro.referenced_macros.push_back(match[1].str());
        searchStart = match.suffix().first;
    }
}

// Analyze macro for semantic patterns
MacroSemantics analyzeMacroSemantics(const std::string& body) {
    MacroSemantics sem;

    // Lambda capture patterns
    std::regex refCaptureRegex(R"(\[&\])");
    std::regex anyCaptureRegex(R"(\[[&=]\])");
    sem.has_reference_capture = std::regex_search(body, refCaptureRegex);
    sem.has_lambda_capture = std::regex_search(body, anyCaptureRegex);

    // Template call pattern: identifier<N> or identifier<param>
    std::regex templateCallRegex(R"(\b[a-zA-Z_][a-zA-Z_0-9]*\s*<\s*([A-Z_][A-Z_0-9]*|[a-zA-Z_][a-zA-Z_0-9]*)\s*>)");
    std::smatch match;
    if (std::regex_search(body, match, templateCallRegex)) {
        sem.has_template_call = true;
        sem.template_param = match[1].str();
    }

    // Return statement
    std::regex returnRegex(R"(\breturn\b)");
    sem.has_return_statement = std::regex_search(body, returnRegex);

    // Check if macro is incomplete (ends with open syntax)
    if (!body.empty()) {
        int braces = 0, parens = 0;
        for (char c : body) {
            if (c == '{') braces++;
            else if (c == '}') braces--;
            else if (c == '(') parens++;
            else if (c == ')') parens--;
        }
        sem.is_incomplete = (braces > 0 || parens > 0);
    }

    // Loop constructs
    std::regex loopRegex(R"(\b(for|while)\s*\()");
    sem.has_loop_construct = std::regex_search(body, loopRegex);

    // Local variable creation (__xyz pattern)
    std::regex localVarRegex(R"(\b(__[a-zA-Z_][a-zA-Z_0-9]*)\b)");
    std::string::const_iterator searchStart = body.cbegin();
    while (std::regex_search(searchStart, body.cend(), match, localVarRegex)) {
        sem.local_vars.push_back(match[1].str());
        sem.creates_local_vars = true;
        searchStart = match.suffix().first;
    }

    return sem;
}

// Check if a macro has hazardous operations
bool hasHazardousMacro(const axiom::MacroDefinition& macro) {
    return macro.has_division ||
           macro.has_pointer_ops ||
           macro.has_casts ||
           !macro.function_calls.empty();
}

// Check if a macro has interesting semantic patterns worth extracting
bool hasSemanticPatterns(const MacroSemantics& sem) {
    return sem.has_lambda_capture ||
           sem.has_template_call ||
           sem.is_incomplete ||
           sem.creates_local_vars ||
           sem.has_loop_construct;
}

// Create axioms from macro definitions (local copy to avoid linking issues)
std::vector<axiom::Axiom> createMacroAxioms(const axiom::MacroDefinition& macro) {
    std::vector<axiom::Axiom> axioms;

    std::string signature = "#define " + macro.to_signature();
    MacroSemantics sem = analyzeMacroSemantics(macro.body);

    // Always create a basic axiom for every function-like macro
    if (macro.is_function_like) {
        axiom::Axiom ax;
        ax.id = macro.name + ".macro_definition";
        ax.content = "Macro " + macro.name + " is a function-like macro";
        if (!macro.parameters.empty()) {
            ax.content += " with parameters: ";
            for (size_t i = 0; i < macro.parameters.size(); ++i) {
                if (i > 0) ax.content += ", ";
                ax.content += macro.parameters[i];
            }
        }
        ax.formal_spec = "is_function_like_macro(" + macro.name + ")";
        ax.function = macro.name;
        ax.signature = signature;
        ax.header = macro.file_path;
        ax.axiom_type = axiom::AxiomType::CONSTRAINT;
        ax.confidence = 1.0;
        ax.source_type = axiom::SourceType::EXPLICIT;
        ax.line = macro.line_start;

        // Add referenced macros as context
        if (!macro.referenced_macros.empty()) {
            ax.content += ". Expands to: ";
            for (size_t i = 0; i < macro.referenced_macros.size() && i < 3; ++i) {
                if (i > 0) ax.content += ", ";
                ax.content += macro.referenced_macros[i];
            }
            if (macro.referenced_macros.size() > 3) {
                ax.content += "...";
            }
        }

        axioms.push_back(std::move(ax));
    }

    // Division hazard -> precondition
    if (macro.has_division) {
        axiom::Axiom ax;
        ax.id = macro.name + ".precond.divisor_nonzero";
        ax.content = "Divisor in macro " + macro.name + " must not be zero";
        ax.formal_spec = "divisor != 0";
        ax.function = macro.name;
        ax.signature = signature;
        ax.header = macro.file_path;
        ax.axiom_type = axiom::AxiomType::PRECONDITION;
        ax.confidence = 0.9;
        ax.source_type = axiom::SourceType::PATTERN;
        ax.line = macro.line_start;
        ax.hazard_type = axiom::HazardType::DIVISION;
        ax.hazard_line = macro.line_start;
        ax.has_guard = false;
        axioms.push_back(std::move(ax));
    }

    // Reference capture [&] -> CONSTRAINT + ANTI_PATTERN
    if (sem.has_reference_capture) {
        {
            axiom::Axiom ax;
            ax.id = macro.name + ".constraint.reference_capture";
            ax.content = "Variables used in " + macro.name + " are captured by reference ([&]), allowing modifications to affect the outer scope";
            ax.formal_spec = "capture_mode == by_reference";
            ax.function = macro.name;
            ax.signature = signature;
            ax.header = macro.file_path;
            ax.axiom_type = axiom::AxiomType::CONSTRAINT;
            ax.confidence = 1.0;
            ax.source_type = axiom::SourceType::EXPLICIT;
            ax.line = macro.line_start;
            axioms.push_back(std::move(ax));
        }
        {
            axiom::Axiom ax;
            ax.id = macro.name + ".anti_pattern.dangling_reference";
            ax.content = "Passing temporary objects to " + macro.name + " may cause dangling references due to [&] capture";
            ax.formal_spec = "isTemporary(arg) -> undefined_behavior";
            ax.function = macro.name;
            ax.signature = signature;
            ax.header = macro.file_path;
            ax.axiom_type = axiom::AxiomType::ANTI_PATTERN;
            ax.confidence = 0.9;
            ax.source_type = axiom::SourceType::PATTERN;
            ax.line = macro.line_start;
            axioms.push_back(std::move(ax));
        }
    }

    // Template call with parameter -> COMPLEXITY
    if (sem.has_template_call && !sem.template_param.empty()) {
        axiom::Axiom ax;
        ax.id = macro.name + ".complexity.template_instantiation";
        ax.content = "Each unique value of " + sem.template_param + " causes a separate template instantiation, increasing compile time and code size";
        ax.formal_spec = "compile_time_cost proportional_to distinct_" + sem.template_param + "_values";
        ax.function = macro.name;
        ax.signature = signature;
        ax.header = macro.file_path;
        ax.axiom_type = axiom::AxiomType::COMPLEXITY;
        ax.confidence = 0.95;
        ax.source_type = axiom::SourceType::PATTERN;
        ax.line = macro.line_start;
        axioms.push_back(std::move(ax));
    }

    // Incomplete macro -> CONSTRAINT
    if (sem.is_incomplete) {
        axiom::Axiom ax;
        ax.id = macro.name + ".constraint.requires_completion";
        ax.content = "Macro " + macro.name + " is syntactically incomplete and requires a companion macro or closing syntax";
        ax.formal_spec = "requires_companion_macro(" + macro.name + ")";
        ax.function = macro.name;
        ax.signature = signature;
        ax.header = macro.file_path;
        ax.axiom_type = axiom::AxiomType::CONSTRAINT;
        ax.confidence = 1.0;
        ax.source_type = axiom::SourceType::EXPLICIT;
        ax.line = macro.line_start;
        axioms.push_back(std::move(ax));
    }

    // Creates local variables -> POSTCONDITION
    if (sem.creates_local_vars && !sem.local_vars.empty()) {
        std::set<std::string> uniqueVars(sem.local_vars.begin(), sem.local_vars.end());
        std::string varList;
        for (const auto& v : uniqueVars) {
            if (!varList.empty()) varList += ", ";
            varList += v;
        }

        axiom::Axiom ax;
        ax.id = macro.name + ".postcondition.local_vars_available";
        ax.content = "After " + macro.name + " expansion, the following identifiers are available in scope: " + varList;
        ax.formal_spec = "in_scope({" + varList + "})";
        ax.function = macro.name;
        ax.signature = signature;
        ax.header = macro.file_path;
        ax.axiom_type = axiom::AxiomType::POSTCONDITION;
        ax.confidence = 0.95;
        ax.source_type = axiom::SourceType::PATTERN;
        ax.line = macro.line_start;
        axioms.push_back(std::move(ax));
    }

    // Loop construct -> EFFECT
    if (sem.has_loop_construct) {
        axiom::Axiom ax;
        ax.id = macro.name + ".effect.iteration";
        ax.content = "Macro " + macro.name + " performs iteration over a range or condition";
        ax.formal_spec = "has_iteration_semantics";
        ax.function = macro.name;
        ax.signature = signature;
        ax.header = macro.file_path;
        ax.axiom_type = axiom::AxiomType::EFFECT;
        ax.confidence = 0.9;
        ax.source_type = axiom::SourceType::PATTERN;
        ax.line = macro.line_start;
        axioms.push_back(std::move(ax));
    }

    return axioms;
}

// PPCallbacks implementation to capture macro definitions
class MacroPPCallbacks : public PPCallbacks {
public:
    MacroPPCallbacks(SourceManager& sm, std::vector<axiom::MacroDefinition>& macros)
        : sm_(sm), macros_(macros) {}

    void MacroDefined(const Token& MacroNameTok,
                      const MacroDirective* MD) override {
        if (!MD) return;

        const MacroInfo* MI = MD->getMacroInfo();
        if (!MI) return;

        // Skip built-in macros
        auto loc = MI->getDefinitionLoc();
        if (!loc.isValid() || sm_.isInSystemHeader(loc)) {
            return;
        }

        axiom::MacroDefinition macro;
        macro.name = MacroNameTok.getIdentifierInfo()->getName().str();
        macro.is_function_like = MI->isFunctionLike();
        macro.file_path = sm_.getFilename(loc).str();
        macro.line_start = sm_.getSpellingLineNumber(loc);
        macro.line_end = sm_.getSpellingLineNumber(MI->getDefinitionEndLoc());

        // Check if file should be ignored
        if (globalIgnoreFilter && shouldIgnorePath(globalIgnoreFilter, macro.file_path, globalProjectRoot, TestMode)) {
            return;
        }

        // Get parameters for function-like macros
        if (MI->isFunctionLike()) {
            for (const auto* param : MI->params()) {
                macro.parameters.push_back(param->getName().str());
            }
        }

        // Build body from tokens
        std::string body;
        for (const auto& tok : MI->tokens()) {
            if (!body.empty() && tok.hasLeadingSpace()) {
                body += " ";
            }
            if (tok.isLiteral() && tok.getLiteralData()) {
                body += std::string(tok.getLiteralData(), tok.getLength());
            } else if (tok.getIdentifierInfo()) {
                body += tok.getIdentifierInfo()->getName().str();
            } else {
                auto spelling = tok::getPunctuatorSpelling(tok.getKind());
                if (spelling) {
                    body += spelling;
                }
            }
        }
        macro.body = body;

        // Analyze for hazards
        analyzeMacroBody(body, macro);

        macros_.push_back(std::move(macro));
    }

private:
    SourceManager& sm_;
    std::vector<axiom::MacroDefinition>& macros_;
};

// Custom FrontendAction that adds macro extraction
class MacroExtractAction : public ASTFrontendAction {
public:
    MacroExtractAction(std::vector<axiom::MacroDefinition>& macros)
        : macros_(macros) {}

protected:
    std::unique_ptr<ASTConsumer> CreateASTConsumer(CompilerInstance& CI,
                                                    llvm::StringRef) override {
        // Add PPCallbacks to capture macros
        auto& PP = CI.getPreprocessor();
        auto& SM = CI.getSourceManager();
        PP.addPPCallbacks(std::make_unique<MacroPPCallbacks>(SM, macros_));

        // Return empty consumer - we just want the preprocessor callbacks
        return std::make_unique<ASTConsumer>();
    }

private:
    std::vector<axiom::MacroDefinition>& macros_;
};

class MacroExtractActionFactory : public FrontendActionFactory {
public:
    MacroExtractActionFactory(std::vector<axiom::MacroDefinition>& macros)
        : macros_(macros) {}

    std::unique_ptr<FrontendAction> create() override {
        return std::make_unique<MacroExtractAction>(macros_);
    }

private:
    std::vector<axiom::MacroDefinition>& macros_;
};

namespace {

// Callback for matching function declarations
class FunctionCallback : public MatchFinder::MatchCallback {
public:
    FunctionCallback(std::vector<axiom::ExtractionResult>& results,
                     axiom::ConstraintExtractor& constraintExtractor,
                     axiom::HazardDetector* hazardDetector,
                     axiom::CallGraphExtractor* callGraphExtractor,
                     axiom::EffectDetector* effectDetector)
        : results_(results)
        , constraintExtractor_(constraintExtractor)
        , hazardDetector_(hazardDetector)
        , callGraphExtractor_(callGraphExtractor)
        , effectDetector_(effectDetector) {}

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
        if (globalIgnoreFilter && shouldIgnorePath(globalIgnoreFilter, filename, globalProjectRoot, TestMode)) {
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

        // Build signature by extracting source text up to the body
        std::string signature;

        // Get the body (compound statement)
        if (const auto* body = func->getBody()) {
            // Extract source text from function start to just before the opening brace
            auto funcStart = func->getBeginLoc();
            auto bodyStart = body->getBeginLoc();

            if (funcStart.isValid() && bodyStart.isValid()) {
                // Get the character data
                auto startOffset = sm.getFileOffset(funcStart);
                auto endOffset = sm.getFileOffset(bodyStart);

                if (endOffset > startOffset) {
                    const char* startPtr = sm.getCharacterData(funcStart);
                    signature = std::string(startPtr, endOffset - startOffset);

                    // Trim trailing whitespace and newlines
                    size_t end = signature.find_last_not_of(" \t\n\r");
                    if (end != std::string::npos) {
                        signature = signature.substr(0, end + 1);
                    }
                }
            }
        }

        // Fallback: if no body or extraction failed, build signature manually
        if (signature.empty()) {
            std::ostringstream ss;
            ss << func->getReturnType().getAsString() << " "
               << func->getQualifiedNameAsString() << "(";

            bool first = true;
            for (const auto* param : func->parameters()) {
                if (!first) ss << ", ";
                first = false;
                ss << param->getType().getAsString();
                if (!param->getName().empty()) {
                    ss << " " << param->getNameAsString();
                }
            }
            ss << ")";

            if (const auto* method = llvm::dyn_cast<CXXMethodDecl>(func)) {
                if (method->isConst()) ss << " const";
            }

            signature = ss.str();
        }

        info.signature = signature;

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

        // Check if this is a template function
        if (const auto* ftd = func->getDescribedFunctionTemplate()) {
            info.is_template = true;
            auto* tpl = ftd->getTemplateParameters();
            if (tpl) {
                info.template_param_count = tpl->size();
                for (const auto* param : *tpl) {
                    if (param->isParameterPack()) {
                        info.is_variadic_template = true;
                    }
                }
            }
        }
        // Also check if this is a member of a template class
        else if (const auto* method = llvm::dyn_cast<CXXMethodDecl>(func)) {
            if (const auto* parent = method->getParent()) {
                if (const auto* ctd = parent->getDescribedClassTemplate()) {
                    info.is_template = true;
                    auto* tpl = ctd->getTemplateParameters();
                    if (tpl) {
                        info.template_param_count = tpl->size();
                        for (const auto* param : *tpl) {
                            if (param->isParameterPack()) {
                                info.is_variadic_template = true;
                            }
                        }
                    }
                }
            }
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

        // Extract call graph if enabled
        if (callGraphExtractor_ && func->hasBody()) {
            auto calls = callGraphExtractor_->extractCalls(func, *result.Context);
            for (auto& call : calls) {
                globalCallGraph.push_back(std::move(call));
            }
        }

        // Extract effects (dataflow analysis)
        if (effectDetector_ && func->hasBody()) {
            auto effects = effectDetector_->detectEffects(func, *result.Context);
            for (const auto& effect : effects) {
                axiom::Axiom axiom;
                axiom.function = info.qualified_name;
                axiom.signature = info.signature;
                axiom.header = info.header;
                axiom.axiom_type = axiom::AxiomType::EFFECT;
                axiom.confidence = effect.confidence;
                axiom.source_type = axiom::SourceType::PATTERN;
                axiom.line = effect.line;

                switch (effect.kind) {
                    case axiom::EffectKind::PARAM_MODIFY:
                        axiom.id = info.qualified_name + ".effect.modifies_" + effect.target;
                        axiom.content = "Modifies parameter " + effect.target;
                        axiom.formal_spec = "modifies(" + effect.target + ")";
                        break;
                    case axiom::EffectKind::MEMBER_WRITE:
                        axiom.id = info.qualified_name + ".effect.writes_" + effect.target;
                        axiom.content = "Writes to member " + effect.target;
                        axiom.formal_spec = "modifies(this." + effect.target + ")";
                        break;
                    case axiom::EffectKind::MEMORY_ALLOC:
                        axiom.id = info.qualified_name + ".effect.allocates";
                        axiom.content = "Allocates memory for " + effect.target;
                        axiom.formal_spec = "allocates(" + effect.target + ")";
                        break;
                    case axiom::EffectKind::MEMORY_FREE:
                        axiom.id = info.qualified_name + ".effect.deallocates";
                        axiom.content = "Deallocates memory for " + effect.target;
                        axiom.formal_spec = "deallocates(" + effect.target + ")";
                        break;
                    case axiom::EffectKind::CONTAINER_MODIFY:
                        axiom.id = info.qualified_name + ".effect.modifies_container";
                        axiom.content = "Modifies container " + effect.target;
                        axiom.formal_spec = "modifies(" + effect.target + ")";
                        break;
                }

                it->axioms.push_back(std::move(axiom));
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
    axiom::CallGraphExtractor* callGraphExtractor_;
    axiom::EffectDetector* effectDetector_;
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

        if (globalIgnoreFilter && shouldIgnorePath(globalIgnoreFilter, filename, globalProjectRoot, TestMode))
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

        if (globalIgnoreFilter && shouldIgnorePath(globalIgnoreFilter, filename, globalProjectRoot, TestMode))
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

        if (globalIgnoreFilter && shouldIgnorePath(globalIgnoreFilter, filename, globalProjectRoot, TestMode))
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

        if (globalIgnoreFilter && shouldIgnorePath(globalIgnoreFilter, filename, globalProjectRoot, TestMode))
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

        if (globalIgnoreFilter && shouldIgnorePath(globalIgnoreFilter, filename, globalProjectRoot, TestMode))
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

// Callback for test mode - extracts assertions from test frameworks
class TestModeCallback : public MatchFinder::MatchCallback {
public:
    TestModeCallback(std::vector<axiom::ExtractionResult>& results,
                     axiom::TestAssertExtractor& extractor)
        : results_(results)
        , extractor_(extractor) {}

    void run(const MatchFinder::MatchResult& result) override {
        // Extract test assertions from the translation unit
        auto assertions = extractor_.extractAssertions(*result.Context);
        if (assertions.empty())
            return;

        // Convert to axioms
        auto axioms = extractor_.toAxioms(assertions);

        // Get source file from first assertion
        auto& sm = result.Context->getSourceManager();
        std::string filename;
        if (!axioms.empty() && axioms[0].line > 0) {
            // Try to get filename from source manager
            auto mainFileID = sm.getMainFileID();
            // Use getFilename() which returns StringRef directly
            filename = sm.getFilename(sm.getLocForStartOfFile(mainFileID)).str();
        }

        if (filename.empty() && !assertions.empty()) {
            filename = "unknown";
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

        // Add extracted axioms
        for (auto& axiom : axioms) {
            if (axiom.header.empty()) {
                size_t lastSlash = filename.rfind('/');
                axiom.header = (lastSlash != std::string::npos)
                    ? filename.substr(lastSlash + 1)
                    : filename;
            }
            it->axioms.push_back(std::move(axiom));
        }

        if (Verbose) {
            llvm::errs() << "Extracted " << axioms.size()
                        << " test axioms from " << filename << "\n";
        }
    }

private:
    std::vector<axiom::ExtractionResult>& results_;
    axiom::TestAssertExtractor& extractor_;
};

} // anonymous namespace

// Parse test framework from command line option
axiom::TestFramework parseTestFramework(const std::string& opt) {
    if (opt == "catch2") return axiom::TestFramework::CATCH2;
    if (opt == "gtest") return axiom::TestFramework::GTEST;
    if (opt == "boost") return axiom::TestFramework::BOOST_TEST;
    return axiom::TestFramework::AUTO;
}

std::string getCurrentTimestamp() {
    auto now = std::chrono::system_clock::now();
    auto time = std::chrono::system_clock::to_time_t(now);
    std::stringstream ss;
    ss << std::put_time(std::gmtime(&time), "%Y-%m-%dT%H:%M:%SZ");
    return ss.str();
}

// Thread-safe progress counter for parallel processing
struct ParallelProgress {
    std::atomic<size_t> filesProcessed{0};
    size_t totalFiles{0};
    std::mutex outputMutex;
};

// Process a batch of files and return extracted results
// Each thread gets its own extractors and callbacks to avoid sharing mutable state
struct BatchResult {
    std::vector<axiom::ExtractionResult> results;
    std::vector<std::pair<std::string, std::string>> callGraphEntries;
    int exitCode = 0;
};

BatchResult processBatch(
    const std::vector<std::string>& files,
    CompilationDatabase& compDb,
    bool extractHazards,
    bool extractCallGraph,
    bool testMode,
    axiom::TestFramework testFramework,
    ParallelProgress* progress = nullptr
) {
    BatchResult batch;

    if (files.empty()) {
        return batch;
    }

    // Create per-thread extractors
    auto constraintExtractor = axiom::createConstraintExtractor();
    std::unique_ptr<axiom::HazardDetector> hazardDetector;
    if (extractHazards) {
        hazardDetector = axiom::createHazardDetector();
    }
    std::unique_ptr<axiom::CallGraphExtractor> callGraphExtractor;
    if (extractCallGraph) {
        callGraphExtractor = axiom::createCallGraphExtractor();
    }
    std::unique_ptr<axiom::EffectDetector> effectDetector = axiom::createEffectDetector();
    std::unique_ptr<axiom::TestAssertExtractor> testExtractor;
    if (testMode) {
        testExtractor = axiom::createTestAssertExtractor(testFramework);
    }

    // Set up matchers with per-thread results
    FunctionCallback funcCallback(batch.results, *constraintExtractor,
                                   hazardDetector.get(), callGraphExtractor.get(),
                                   effectDetector.get());
    ClassCallback classCallback(batch.results);
    EnumCallback enumCallback(batch.results);
    StaticAssertCallback staticAssertCallback(batch.results);
    ConceptCallback conceptCallback(batch.results);
    TypeAliasCallback typeAliasCallback(batch.results);
    std::unique_ptr<TestModeCallback> testModeCallback;
    if (testMode && testExtractor) {
        testModeCallback = std::make_unique<TestModeCallback>(batch.results, *testExtractor);
    }

    MatchFinder finder;
    finder.addMatcher(functionDecl(isDefinition()).bind("func"), &funcCallback);
    finder.addMatcher(cxxRecordDecl(isDefinition()).bind("class"), &classCallback);
    finder.addMatcher(enumDecl(isDefinition()).bind("enum"), &enumCallback);
    finder.addMatcher(staticAssertDecl().bind("static_assert"), &staticAssertCallback);
    finder.addMatcher(conceptDecl().bind("concept"), &conceptCallback);
    finder.addMatcher(typeAliasDecl().bind("alias"), &typeAliasCallback);
    if (testMode && testModeCallback) {
        finder.addMatcher(functionDecl(isDefinition()).bind("test_func"), testModeCallback.get());
    }

    // Process files for AST extraction
    ClangTool tool(compDb, files);
    batch.exitCode = tool.run(newFrontendActionFactory(&finder).get());

    // Run macro extraction pass
    std::vector<axiom::MacroDefinition> localMacros;
    ClangTool macroTool(compDb, files);
    MacroExtractActionFactory macroFactory(localMacros);
    macroTool.run(&macroFactory);

    // Convert macros to axioms and add to results
    for (const auto& macro : localMacros) {
        auto macroAxioms = createMacroAxioms(macro);
        if (!macroAxioms.empty()) {
            // Find or create result for this file
            auto it = std::find_if(batch.results.begin(), batch.results.end(),
                [&macro](const axiom::ExtractionResult& r) {
                    return r.source_file == macro.file_path;
                });

            if (it == batch.results.end()) {
                batch.results.push_back({macro.file_path, {}, {}});
                it = batch.results.end() - 1;
            }

            for (auto& axiom : macroAxioms) {
                it->axioms.push_back(std::move(axiom));
            }
        }
    }

    // Update progress if tracking
    if (progress) {
        size_t done = progress->filesProcessed.fetch_add(files.size()) + files.size();
        if (Verbose) {
            std::lock_guard<std::mutex> lock(progress->outputMutex);
            llvm::errs() << "[" << done << "/" << progress->totalFiles << "] Processed "
                        << files.size() << " file(s)\n";
        }
    }

    return batch;
}

// Merge batch results into final results
void mergeResults(std::vector<axiom::ExtractionResult>& target,
                  std::vector<axiom::ExtractionResult>&& source) {
    for (auto& result : source) {
        // Check if we already have results for this file
        auto it = std::find_if(target.begin(), target.end(),
            [&result](const axiom::ExtractionResult& r) {
                return r.source_file == result.source_file;
            });

        if (it != target.end()) {
            // Merge axioms into existing result
            for (auto& axiom : result.axioms) {
                it->axioms.push_back(std::move(axiom));
            }
        } else {
            target.push_back(std::move(result));
        }
    }
}

int main(int argc, const char** argv) {
    // Check for -q/--quiet flag early to suppress compilation database warnings
    bool quietMode = false;
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "-q" || std::string(argv[i]) == "--quiet") {
            quietMode = true;
            break;
        }
    }

    // Suppress stderr during option parsing if quiet mode
    // (CommonOptionsParser prints noisy "compilation database not found" warnings)
    int savedStderr = -1;
    if (quietMode) {
        savedStderr = dup(STDERR_FILENO);
        int devNull = open("/dev/null", O_WRONLY);
        if (devNull >= 0) {
            dup2(devNull, STDERR_FILENO);
            close(devNull);
        }
    }

    auto expectedParser = CommonOptionsParser::create(
        argc, argv, AxiomExtractCategory);

    // Restore stderr
    if (savedStderr >= 0) {
        dup2(savedStderr, STDERR_FILENO);
        close(savedStderr);
    }

    if (!expectedParser) {
        llvm::errs() << expectedParser.takeError();
        return 1;
    }

    CommonOptionsParser& optionsParser = *expectedParser;

    // Set up ignore filter from .axignore first (needed for file discovery)
    axiom::IgnoreFilter ignoreFilter;
    if (!NoIgnore) {
        std::string axignorePath;

        if (!IgnoreFilePath.empty()) {
            axignorePath = IgnoreFilePath;
        } else if (!optionsParser.getSourcePathList().empty()) {
            // Auto-detect .axignore from first source file/directory
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

    // Get source files - either from command line or by scanning directories
    std::vector<std::string> sourceFiles;
    auto inputPaths = optionsParser.getSourcePathList();

    if (Recursive || std::any_of(inputPaths.begin(), inputPaths.end(),
            [](const std::string& p) { return std::filesystem::is_directory(p); })) {
        // Recursive mode or directory input: find all source files
        for (const auto& inputPath : inputPaths) {
            auto found = findSourceFiles(inputPath, Recursive,
                NoIgnore ? nullptr : &ignoreFilter, globalProjectRoot, TestMode);
            sourceFiles.insert(sourceFiles.end(), found.begin(), found.end());
        }

        if (sourceFiles.empty()) {
            llvm::errs() << "No C++ source files found in specified paths\n";
            return 1;
        }

        if (Verbose) {
            llvm::errs() << "Found " << sourceFiles.size() << " source file(s)\n";
            for (const auto& f : sourceFiles) {
                llvm::errs() << "  " << f << "\n";
            }
        }
    } else {
        // Normal mode: use files as specified
        sourceFiles = inputPaths;
    }

    // Create the ClangTool
    // When in recursive/directory mode, use a fixed compilation database
    // When files are specified directly, use the provided compilation database
    std::unique_ptr<CompilationDatabase> ownedCompDb;
    CompilationDatabase* compDb = nullptr;

    if (Recursive || std::any_of(inputPaths.begin(), inputPaths.end(),
            [](const std::string& p) { return std::filesystem::is_directory(p); })) {
        // Recursive mode: use fixed compilation database with C++20
        // Users can override with -- -std=c++17 etc. on command line
        std::vector<std::string> defaultArgs = {"-std=c++20"};
        ownedCompDb = std::make_unique<FixedCompilationDatabase>(".", defaultArgs);
        compDb = ownedCompDb.get();
    } else {
        // Normal mode: use provided compilation database
        compDb = &optionsParser.getCompilations();
    }

    // Determine number of parallel jobs
    unsigned numJobs = NumJobs;
    if (numJobs == 0) {
        numJobs = std::thread::hardware_concurrency();
        if (numJobs == 0) numJobs = 1;  // Fallback if detection fails
    }

    // Parse test framework once
    axiom::TestFramework testFramework = parseTestFramework(TestFrameworkOpt);
    if (TestMode && Verbose) {
        llvm::errs() << "Test mode enabled with framework: " << TestFrameworkOpt << "\n";
    }

    // Storage for results
    std::vector<axiom::ExtractionResult> results;
    globalCallGraph.clear();  // Clear from any previous runs
    int exitCode = 0;

    // Use parallel processing if we have multiple files and multiple jobs
    if (numJobs > 1 && sourceFiles.size() > 1) {
        if (Verbose) {
            llvm::errs() << "Processing " << sourceFiles.size() << " files with "
                        << numJobs << " parallel jobs\n";
        }

        // Split files into batches
        std::vector<std::vector<std::string>> batches(numJobs);
        for (size_t i = 0; i < sourceFiles.size(); ++i) {
            batches[i % numJobs].push_back(sourceFiles[i]);
        }

        // Progress tracking
        ParallelProgress progress;
        progress.totalFiles = sourceFiles.size();

        // Launch parallel tasks
        std::vector<std::future<BatchResult>> futures;
        for (unsigned i = 0; i < numJobs; ++i) {
            if (!batches[i].empty()) {
                futures.push_back(std::async(std::launch::async,
                    processBatch,
                    std::cref(batches[i]),
                    std::ref(*compDb),
                    ExtractHazards.getValue(),
                    ExtractCallGraph.getValue(),
                    TestMode.getValue(),
                    testFramework,
                    &progress
                ));
            }
        }

        // Collect results
        for (auto& future : futures) {
            BatchResult batch = future.get();
            mergeResults(results, std::move(batch.results));
            if (batch.exitCode != 0) {
                exitCode = batch.exitCode;
            }
        }
    } else {
        // Single-threaded processing (original code path)
        if (Verbose && sourceFiles.size() > 1) {
            llvm::errs() << "Processing " << sourceFiles.size() << " files (single-threaded)\n";
        }

        BatchResult batch = processBatch(
            sourceFiles, *compDb,
            ExtractHazards, ExtractCallGraph, TestMode, testFramework
        );
        results = std::move(batch.results);
        exitCode = batch.exitCode;
    }

    // Note: We don't fail on exitCode != 0 because some files may have parse errors
    // (missing includes, etc.) but we still want to output what we extracted.
    // The errors are already printed to stderr by clang.
    if (exitCode != 0 && Verbose) {
        llvm::errs() << "Warning: Clang tool reported errors (some files may not have been fully processed)\n";
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

    // Add call graph if extracted
    if (ExtractCallGraph && !globalCallGraph.empty()) {
        output["call_graph"] = globalCallGraph;
        output["total_calls"] = globalCallGraph.size();
    }

    // Add test mode info
    if (TestMode) {
        output["test_mode"] = true;
        output["test_framework"] = TestFrameworkOpt.getValue();
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
