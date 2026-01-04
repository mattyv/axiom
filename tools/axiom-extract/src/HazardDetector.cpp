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

class HazardVisitor : public clang::RecursiveASTVisitor<HazardVisitor> {
public:
    HazardVisitor(clang::ASTContext& ctx) : ctx_(ctx), sm_(ctx.getSourceManager()) {}

    std::vector<Hazard> getHazards() { return std::move(hazards_); }

    // Division operations: a / b, a % b
    bool VisitBinaryOperator(clang::BinaryOperator* op) {
        if (op->getOpcode() == clang::BO_Div || op->getOpcode() == clang::BO_Rem) {
            // Check if divisor could be zero
            auto* rhs = op->getRHS()->IgnoreParenImpCasts();

            // Skip if divisor is a literal non-zero value
            if (const auto* lit = llvm::dyn_cast<clang::IntegerLiteral>(rhs)) {
                if (!lit->getValue().isZero()) {
                    return true;
                }
            }

            Hazard h;
            h.type = HazardType::DIVISION;
            h.expression = getExprText(op);
            h.operand = getExprText(op->getRHS());
            h.line = sm_.getSpellingLineNumber(op->getOperatorLoc());
            hazards_.push_back(std::move(h));
        }
        return true;
    }

    // Pointer dereference: *p
    bool VisitUnaryOperator(clang::UnaryOperator* op) {
        if (op->getOpcode() == clang::UO_Deref) {
            auto* sub = op->getSubExpr()->IgnoreParenImpCasts();

            // Skip if 'this' pointer
            if (llvm::isa<clang::CXXThisExpr>(sub)) {
                return true;
            }

            Hazard h;
            h.type = HazardType::POINTER_DEREF;
            h.expression = getExprText(op);
            h.operand = getExprText(sub);
            h.line = sm_.getSpellingLineNumber(op->getOperatorLoc());
            hazards_.push_back(std::move(h));
        }
        return true;
    }

    // Member access through pointer: p->member
    bool VisitMemberExpr(clang::MemberExpr* expr) {
        if (expr->isArrow()) {
            auto* base = expr->getBase()->IgnoreParenImpCasts();

            // Skip if 'this' pointer
            if (llvm::isa<clang::CXXThisExpr>(base)) {
                return true;
            }

            Hazard h;
            h.type = HazardType::POINTER_DEREF;
            h.expression = getExprText(expr);
            h.operand = getExprText(base);
            h.line = sm_.getSpellingLineNumber(expr->getOperatorLoc());
            hazards_.push_back(std::move(h));
        }
        return true;
    }

    // Array subscript: a[i]
    bool VisitArraySubscriptExpr(clang::ArraySubscriptExpr* expr) {
        Hazard h;
        h.type = HazardType::ARRAY_ACCESS;
        h.expression = getExprText(expr);
        h.operand = getExprText(expr->getIdx());
        h.line = sm_.getSpellingLineNumber(expr->getRBracketLoc());
        hazards_.push_back(std::move(h));
        return true;
    }

    // Casts that might be unsafe: reinterpret_cast, C-style casts
    bool VisitCXXReinterpretCastExpr(clang::CXXReinterpretCastExpr* expr) {
        Hazard h;
        h.type = HazardType::CAST;
        h.expression = getExprText(expr);
        h.operand = getExprText(expr->getSubExpr());
        h.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        hazards_.push_back(std::move(h));
        return true;
    }

private:
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
    std::vector<Hazard> hazards_;
};

class HazardDetectorImpl : public HazardDetector {
public:
    std::vector<Hazard> detectHazards(
        const clang::FunctionDecl* func,
        clang::ASTContext& ctx
    ) override {
        if (!func->hasBody()) {
            return {};
        }

        HazardVisitor visitor(ctx);
        visitor.TraverseStmt(func->getBody());
        return visitor.getHazards();
    }
};

std::unique_ptr<HazardDetector> createHazardDetector() {
    return std::make_unique<HazardDetectorImpl>();
}

} // namespace axiom
