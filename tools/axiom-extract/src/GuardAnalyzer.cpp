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
#include <clang/Analysis/CFG.h>
#include <clang/Analysis/Analyses/Dominators.h>
#include <clang/Basic/SourceManager.h>
#include <optional>
#include <unordered_set>

namespace axiom {

// Helper to extract variable names from expressions
class VariableExtractor : public clang::RecursiveASTVisitor<VariableExtractor> {
public:
    std::unordered_set<std::string> variables;

    bool VisitDeclRefExpr(clang::DeclRefExpr* expr) {
        if (auto* var = llvm::dyn_cast<clang::VarDecl>(expr->getDecl())) {
            variables.insert(var->getNameAsString());
        }
        return true;
    }
};

// Helper to check if a condition guards a hazard
class GuardChecker {
public:
    GuardChecker(clang::ASTContext& ctx) : ctx_(ctx), sm_(ctx.getSourceManager()) {}

    // Check if condition protects against the given hazard type for the operand
    bool isGuardFor(const clang::Expr* cond, const Hazard& hazard) {
        if (!cond) return false;

        // Get variables mentioned in the hazard operand
        VariableExtractor hazardVars;
        // Note: We'd need a non-const Stmt* to traverse, so we work around this
        // by matching based on the operand string
        std::string operand = hazard.operand;

        // Look for null checks, division guards, bound checks
        return checkCondition(cond, hazard.type, operand);
    }

    std::string getConditionText(const clang::Expr* cond) {
        if (!cond) return "";
        auto range = cond->getSourceRange();
        if (range.isValid()) {
            auto begin = sm_.getCharacterData(range.getBegin());
            auto end = sm_.getCharacterData(range.getEnd());
            if (begin && end && end >= begin) {
                size_t len = std::min(static_cast<size_t>(end - begin + 1),
                                      static_cast<size_t>(200));
                return std::string(begin, len);
            }
        }
        return "";
    }

private:
    bool checkCondition(const clang::Expr* cond, HazardType type,
                        const std::string& operand) {
        cond = cond->IgnoreParenImpCasts();

        // Binary operators: ptr != nullptr, divisor != 0, idx < size
        if (const auto* binOp = llvm::dyn_cast<clang::BinaryOperator>(cond)) {
            return checkBinaryOp(binOp, type, operand);
        }

        // Unary not: !ptr
        if (const auto* unaryOp = llvm::dyn_cast<clang::UnaryOperator>(cond)) {
            if (unaryOp->getOpcode() == clang::UO_LNot) {
                // !ptr means we're in the else branch where ptr is non-null
                // For proper analysis, we'd need branch info
                return false;
            }
        }

        // Implicit conversion to bool: if (ptr)
        if (const auto* implicitCast = llvm::dyn_cast<clang::ImplicitCastExpr>(cond)) {
            if (implicitCast->getCastKind() == clang::CK_PointerToBoolean) {
                // Check if it involves our operand
                std::string condText = getConditionText(implicitCast);
                if (condText.find(operand) != std::string::npos &&
                    type == HazardType::POINTER_DEREF) {
                    return true;
                }
            }
        }

        // Logical AND: combine guards
        if (const auto* logAnd = llvm::dyn_cast<clang::BinaryOperator>(cond)) {
            if (logAnd->getOpcode() == clang::BO_LAnd) {
                return checkCondition(logAnd->getLHS(), type, operand) ||
                       checkCondition(logAnd->getRHS(), type, operand);
            }
        }

        return false;
    }

    bool checkBinaryOp(const clang::BinaryOperator* binOp, HazardType type,
                       const std::string& operand) {
        auto opcode = binOp->getOpcode();
        std::string lhsText = getConditionText(binOp->getLHS());
        std::string rhsText = getConditionText(binOp->getRHS());

        // Pointer null checks: ptr != nullptr, ptr != NULL, ptr != 0
        if (type == HazardType::POINTER_DEREF) {
            if (opcode == clang::BO_NE) {
                // ptr != nullptr
                if (lhsText.find(operand) != std::string::npos) {
                    if (isNullLiteral(binOp->getRHS())) {
                        return true;
                    }
                }
                if (rhsText.find(operand) != std::string::npos) {
                    if (isNullLiteral(binOp->getLHS())) {
                        return true;
                    }
                }
            }
        }

        // Division guards: divisor != 0
        if (type == HazardType::DIVISION) {
            if (opcode == clang::BO_NE) {
                // b != 0
                if (lhsText.find(operand) != std::string::npos) {
                    if (isZeroLiteral(binOp->getRHS())) {
                        return true;
                    }
                }
                if (rhsText.find(operand) != std::string::npos) {
                    if (isZeroLiteral(binOp->getLHS())) {
                        return true;
                    }
                }
            }
        }

        // Bounds checks: idx < size, idx < arr.size(), etc.
        if (type == HazardType::ARRAY_ACCESS) {
            if (opcode == clang::BO_LT || opcode == clang::BO_LE) {
                if (lhsText.find(operand) != std::string::npos) {
                    // idx < something
                    return true;
                }
            }
            if (opcode == clang::BO_GT || opcode == clang::BO_GE) {
                if (rhsText.find(operand) != std::string::npos) {
                    // something > idx
                    return true;
                }
            }
        }

        return false;
    }

    bool isNullLiteral(const clang::Expr* expr) {
        expr = expr->IgnoreParenImpCasts();
        if (llvm::isa<clang::CXXNullPtrLiteralExpr>(expr)) {
            return true;
        }
        if (const auto* intLit = llvm::dyn_cast<clang::IntegerLiteral>(expr)) {
            return intLit->getValue().isZero();
        }
        // Check for NULL macro
        std::string text = getConditionText(expr);
        return text == "NULL" || text == "nullptr";
    }

    bool isZeroLiteral(const clang::Expr* expr) {
        expr = expr->IgnoreParenImpCasts();
        if (const auto* intLit = llvm::dyn_cast<clang::IntegerLiteral>(expr)) {
            return intLit->getValue().isZero();
        }
        if (const auto* floatLit = llvm::dyn_cast<clang::FloatingLiteral>(expr)) {
            return floatLit->getValue().isZero();
        }
        return false;
    }

    clang::ASTContext& ctx_;
    clang::SourceManager& sm_;
};

class GuardAnalyzerImpl : public GuardAnalyzer {
public:
    bool isGuarded(
        const Hazard& hazard,
        clang::CFG* cfg,
        clang::ASTContext& ctx
    ) override {
        if (!cfg) return false;

        auto& sm = ctx.getSourceManager();
        GuardChecker checker(ctx);

        // Find the CFG block containing the hazard
        const clang::CFGBlock* hazardBlock = nullptr;
        for (const auto* block : *cfg) {
            for (const auto& elem : *block) {
                if (auto stmt = elem.getAs<clang::CFGStmt>()) {
                    auto loc = stmt->getStmt()->getBeginLoc();
                    if (sm.getSpellingLineNumber(loc) == static_cast<unsigned>(hazard.line)) {
                        hazardBlock = block;
                        break;
                    }
                }
            }
            if (hazardBlock) break;
        }

        if (!hazardBlock) return false;

        // Walk predecessors looking for guarding conditions
        return checkPredecessorsForGuard(hazardBlock, hazard, checker, ctx);
    }

    std::optional<std::string> findGuard(
        const Hazard& hazard,
        clang::CFG* cfg,
        clang::ASTContext& ctx
    ) override {
        if (!cfg) return std::nullopt;

        auto& sm = ctx.getSourceManager();
        GuardChecker checker(ctx);

        // Find the CFG block containing the hazard
        const clang::CFGBlock* hazardBlock = nullptr;
        for (const auto* block : *cfg) {
            for (const auto& elem : *block) {
                if (auto stmt = elem.getAs<clang::CFGStmt>()) {
                    auto loc = stmt->getStmt()->getBeginLoc();
                    if (sm.getSpellingLineNumber(loc) == static_cast<unsigned>(hazard.line)) {
                        hazardBlock = block;
                        break;
                    }
                }
            }
            if (hazardBlock) break;
        }

        if (!hazardBlock) return std::nullopt;

        // Walk predecessors looking for guarding conditions
        return findGuardInPredecessors(hazardBlock, hazard, checker, ctx);
    }

private:
    bool checkPredecessorsForGuard(
        const clang::CFGBlock* block,
        const Hazard& hazard,
        GuardChecker& checker,
        clang::ASTContext& ctx
    ) {
        std::unordered_set<unsigned> visited;
        return checkPredecessorsImpl(block, hazard, checker, ctx, visited);
    }

    bool checkPredecessorsImpl(
        const clang::CFGBlock* block,
        const Hazard& hazard,
        GuardChecker& checker,
        clang::ASTContext& ctx,
        std::unordered_set<unsigned>& visited
    ) {
        if (!block || visited.count(block->getBlockID())) {
            return false;
        }
        visited.insert(block->getBlockID());

        // Check terminator condition of predecessors
        for (const auto& pred : block->preds()) {
            if (!pred) continue;

            if (auto* term = pred->getTerminatorCondition()) {
                if (auto* expr = llvm::dyn_cast<clang::Expr>(term)) {
                    if (checker.isGuardFor(expr, hazard)) {
                        return true;
                    }
                }
            }

            // Recurse into predecessors (limited depth)
            if (visited.size() < 10) {
                if (checkPredecessorsImpl(pred, hazard, checker, ctx, visited)) {
                    return true;
                }
            }
        }

        return false;
    }

    std::optional<std::string> findGuardInPredecessors(
        const clang::CFGBlock* block,
        const Hazard& hazard,
        GuardChecker& checker,
        clang::ASTContext& ctx
    ) {
        std::unordered_set<unsigned> visited;
        return findGuardImpl(block, hazard, checker, ctx, visited);
    }

    std::optional<std::string> findGuardImpl(
        const clang::CFGBlock* block,
        const Hazard& hazard,
        GuardChecker& checker,
        clang::ASTContext& ctx,
        std::unordered_set<unsigned>& visited
    ) {
        if (!block || visited.count(block->getBlockID())) {
            return std::nullopt;
        }
        visited.insert(block->getBlockID());

        for (const auto& pred : block->preds()) {
            if (!pred) continue;

            if (auto* term = pred->getTerminatorCondition()) {
                if (auto* expr = llvm::dyn_cast<clang::Expr>(term)) {
                    if (checker.isGuardFor(expr, hazard)) {
                        return checker.getConditionText(expr);
                    }
                }
            }

            if (visited.size() < 10) {
                if (auto guard = findGuardImpl(pred, hazard, checker, ctx, visited)) {
                    return guard;
                }
            }
        }

        return std::nullopt;
    }
};

std::unique_ptr<GuardAnalyzer> createGuardAnalyzer() {
    return std::make_unique<GuardAnalyzerImpl>();
}

} // namespace axiom
