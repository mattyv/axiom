// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "Extractors.h"

#include <clang/AST/ASTContext.h>
#include <clang/AST/Expr.h>
#include <clang/AST/ExprCXX.h>
#include <clang/AST/RecursiveASTVisitor.h>
#include <clang/AST/Stmt.h>
#include <clang/Basic/SourceManager.h>

namespace axiom {

class CallVisitor : public clang::RecursiveASTVisitor<CallVisitor> {
public:
    CallVisitor(clang::ASTContext& ctx, const std::string& caller)
        : ctx_(ctx), sm_(ctx.getSourceManager()), caller_(caller) {}

    std::vector<FunctionCall> getCalls() { return std::move(calls_); }

    // Regular function calls: foo(), bar(x, y)
    bool VisitCallExpr(clang::CallExpr* expr) {
        // Skip if this is actually a member call (handled separately)
        if (llvm::isa<clang::CXXMemberCallExpr>(expr)) {
            return true;
        }

        if (auto* callee = expr->getDirectCallee()) {
            FunctionCall call;
            call.caller = caller_;
            call.callee = callee->getQualifiedNameAsString();
            call.callee_signature = getSignature(callee);
            call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
            call.is_virtual = false;

            // Extract arguments
            for (unsigned i = 0; i < expr->getNumArgs(); ++i) {
                call.arguments.push_back(getExprText(expr->getArg(i)));
            }

            calls_.push_back(std::move(call));
        }
        return true;
    }

    // Member function calls: obj.method(), ptr->method()
    bool VisitCXXMemberCallExpr(clang::CXXMemberCallExpr* expr) {
        if (auto* method = expr->getMethodDecl()) {
            FunctionCall call;
            call.caller = caller_;
            call.callee = method->getQualifiedNameAsString();
            call.callee_signature = getSignature(method);
            call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
            call.is_virtual = method->isVirtual();

            // Extract arguments (excluding implicit 'this')
            for (unsigned i = 0; i < expr->getNumArgs(); ++i) {
                call.arguments.push_back(getExprText(expr->getArg(i)));
            }

            calls_.push_back(std::move(call));
        }
        return true;
    }

    // Operator calls: a + b, a[i], etc.
    bool VisitCXXOperatorCallExpr(clang::CXXOperatorCallExpr* expr) {
        if (auto* callee = expr->getDirectCallee()) {
            // Only track user-defined operators, not built-ins
            if (auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(callee)) {
                FunctionCall call;
                call.caller = caller_;
                call.callee = callee->getQualifiedNameAsString();
                call.callee_signature = getSignature(callee);
                call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
                call.is_virtual = method->isVirtual();

                // Extract arguments
                for (unsigned i = 0; i < expr->getNumArgs(); ++i) {
                    call.arguments.push_back(getExprText(expr->getArg(i)));
                }

                calls_.push_back(std::move(call));
            }
        }
        return true;
    }

    // Constructor calls in new expressions: new Foo(x)
    bool VisitCXXConstructExpr(clang::CXXConstructExpr* expr) {
        if (auto* ctor = expr->getConstructor()) {
            // Skip implicit default constructors
            if (expr->getNumArgs() == 0 && ctor->isDefaultConstructor()) {
                return true;
            }

            FunctionCall call;
            call.caller = caller_;
            call.callee = ctor->getQualifiedNameAsString();
            call.callee_signature = getSignature(ctor);
            call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
            call.is_virtual = false;

            for (unsigned i = 0; i < expr->getNumArgs(); ++i) {
                call.arguments.push_back(getExprText(expr->getArg(i)));
            }

            calls_.push_back(std::move(call));
        }
        return true;
    }

private:
    std::string getSignature(const clang::FunctionDecl* func) {
        std::string sig;
        llvm::raw_string_ostream os(sig);

        // Return type
        func->getReturnType().print(os, ctx_.getPrintingPolicy());
        os << " ";

        // Function name
        os << func->getQualifiedNameAsString();

        // Parameters
        os << "(";
        for (unsigned i = 0; i < func->getNumParams(); ++i) {
            if (i > 0) os << ", ";
            func->getParamDecl(i)->getType().print(os, ctx_.getPrintingPolicy());
        }
        os << ")";

        // const/noexcept qualifiers for methods
        if (auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(func)) {
            if (method->isConst()) {
                os << " const";
            }
        }

        // Check for noexcept specification
        if (const auto* proto = func->getType()->getAs<clang::FunctionProtoType>()) {
            if (proto->isNothrow()) {
                os << " noexcept";
            }
        }

        return sig;
    }

    std::string getExprText(const clang::Expr* expr) {
        auto range = expr->getSourceRange();
        if (range.isValid()) {
            auto begin = sm_.getCharacterData(range.getBegin());
            auto end = sm_.getCharacterData(range.getEnd());
            if (begin && end && end >= begin) {
                // Get a reasonable length, max 100 chars
                size_t len = std::min(static_cast<size_t>(end - begin + 1),
                                      static_cast<size_t>(100));
                return std::string(begin, len);
            }
        }
        return "<unknown>";
    }

    clang::ASTContext& ctx_;
    clang::SourceManager& sm_;
    std::string caller_;
    std::vector<FunctionCall> calls_;
};

class CallGraphExtractorImpl : public CallGraphExtractor {
public:
    std::vector<FunctionCall> extractCalls(
        const clang::FunctionDecl* func,
        clang::ASTContext& ctx
    ) override {
        if (!func->hasBody()) {
            return {};
        }

        std::string caller = func->getQualifiedNameAsString();
        CallVisitor visitor(ctx, caller);
        visitor.TraverseStmt(func->getBody());
        return visitor.getCalls();
    }
};

std::unique_ptr<CallGraphExtractor> createCallGraphExtractor() {
    return std::make_unique<CallGraphExtractorImpl>();
}

} // namespace axiom
