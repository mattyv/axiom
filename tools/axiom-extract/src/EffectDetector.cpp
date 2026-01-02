// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "Extractors.h"

#include <clang/AST/ASTContext.h>
#include <clang/AST/Decl.h>
#include <clang/AST/DeclCXX.h>
#include <clang/AST/Expr.h>
#include <clang/AST/ExprCXX.h>
#include <clang/AST/ParentMapContext.h>
#include <clang/AST/RecursiveASTVisitor.h>
#include <clang/AST/Stmt.h>
#include <clang/Basic/SourceManager.h>
#include <map>
#include <set>
#include <unordered_set>

namespace axiom {

// Container modification method names
static const std::unordered_set<std::string> CONTAINER_MODIFY_METHODS = {
    "push_back", "push_front", "pop_back", "pop_front",
    "insert", "emplace", "emplace_back", "emplace_front",
    "erase", "clear", "resize", "reserve",
    "assign", "swap", "append", "replace"
};

class EffectVisitor : public clang::RecursiveASTVisitor<EffectVisitor> {
public:
    EffectVisitor(clang::ASTContext& ctx, const clang::FunctionDecl* func)
        : ctx_(ctx), sm_(ctx.getSourceManager()), func_(func) {
        // Collect non-const reference/pointer parameters
        for (const auto* param : func->parameters()) {
            auto type = param->getType();
            // Non-const reference
            if (type->isReferenceType() && !type.getNonReferenceType().isConstQualified()) {
                modifiableParams_.insert(param->getNameAsString());
            }
            // Non-const pointer (for *ptr = x)
            if (type->isPointerType() && !type->getPointeeType().isConstQualified()) {
                pointerParams_.insert(param->getNameAsString());
            }
        }

        // Check if this is a const method
        if (const auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(func)) {
            isConstMethod_ = method->isConst();
        }
    }

    std::vector<Effect> getEffects() {
        // Generate call frequency effects before returning
        generateCallFrequencyEffects();
        return std::move(effects_);
    }

    // Track loop statements to determine occurs_at_start
    bool VisitForStmt(clang::ForStmt* loop) {
        int line = sm_.getSpellingLineNumber(loop->getBeginLoc());
        loop_start_lines_.insert(line);
        return true;
    }

    bool VisitWhileStmt(clang::WhileStmt* loop) {
        int line = sm_.getSpellingLineNumber(loop->getBeginLoc());
        loop_start_lines_.insert(line);
        return true;
    }

    bool VisitCXXForRangeStmt(clang::CXXForRangeStmt* loop) {
        int line = sm_.getSpellingLineNumber(loop->getBeginLoc());
        loop_start_lines_.insert(line);
        return true;
    }

    // Assignment operators: x = y, x += y, etc.
    bool VisitBinaryOperator(clang::BinaryOperator* op) {
        if (!op->isAssignmentOp()) {
            return true;
        }

        auto* lhs = op->getLHS()->IgnoreParenImpCasts();

        // Check for parameter modification: param = x
        if (auto* declRef = llvm::dyn_cast<clang::DeclRefExpr>(lhs)) {
            if (auto* varDecl = llvm::dyn_cast<clang::VarDecl>(declRef->getDecl())) {
                std::string name = varDecl->getNameAsString();
                if (modifiableParams_.count(name)) {
                    Effect e;
                    e.kind = EffectKind::PARAM_MODIFY;
                    e.target = name;
                    e.expression = getExprText(op);
                    e.line = sm_.getSpellingLineNumber(op->getOperatorLoc());
                    e.confidence = 0.95;
                    effects_.push_back(std::move(e));
                    return true;
                }
            }
        }

        // Check for member modification: this->x = y, x_ = y
        if (auto* memberExpr = llvm::dyn_cast<clang::MemberExpr>(lhs)) {
            if (!isConstMethod_) {
                if (isMemberOfThis(memberExpr)) {
                    Effect e;
                    e.kind = EffectKind::MEMBER_WRITE;
                    e.target = memberExpr->getMemberDecl()->getNameAsString();
                    e.expression = getExprText(op);
                    e.line = sm_.getSpellingLineNumber(op->getOperatorLoc());
                    e.confidence = 0.95;
                    effects_.push_back(std::move(e));
                    return true;
                }
            }
        }

        // Check for pointer dereference assignment: *ptr = x
        if (auto* unary = llvm::dyn_cast<clang::UnaryOperator>(lhs)) {
            if (unary->getOpcode() == clang::UO_Deref) {
                if (auto* declRef = llvm::dyn_cast<clang::DeclRefExpr>(
                        unary->getSubExpr()->IgnoreParenImpCasts())) {
                    if (auto* varDecl = llvm::dyn_cast<clang::VarDecl>(declRef->getDecl())) {
                        std::string name = varDecl->getNameAsString();
                        if (pointerParams_.count(name)) {
                            Effect e;
                            e.kind = EffectKind::PARAM_MODIFY;
                            e.target = "*" + name;
                            e.expression = getExprText(op);
                            e.line = sm_.getSpellingLineNumber(op->getOperatorLoc());
                            e.confidence = 0.95;
                            effects_.push_back(std::move(e));
                            return true;
                        }
                    }
                }
            }
        }

        return true;
    }

    // Unary operators: ++x, x++, --x, x--
    bool VisitUnaryOperator(clang::UnaryOperator* op) {
        auto opcode = op->getOpcode();
        if (opcode != clang::UO_PreInc && opcode != clang::UO_PostInc &&
            opcode != clang::UO_PreDec && opcode != clang::UO_PostDec) {
            return true;
        }

        auto* sub = op->getSubExpr()->IgnoreParenImpCasts();

        // Parameter increment/decrement
        if (auto* declRef = llvm::dyn_cast<clang::DeclRefExpr>(sub)) {
            if (auto* varDecl = llvm::dyn_cast<clang::VarDecl>(declRef->getDecl())) {
                std::string name = varDecl->getNameAsString();
                if (modifiableParams_.count(name)) {
                    Effect e;
                    e.kind = EffectKind::PARAM_MODIFY;
                    e.target = name;
                    e.expression = getExprText(op);
                    e.line = sm_.getSpellingLineNumber(op->getOperatorLoc());
                    e.confidence = 0.95;
                    effects_.push_back(std::move(e));
                    return true;
                }
            }
        }

        // Member increment/decrement
        if (auto* memberExpr = llvm::dyn_cast<clang::MemberExpr>(sub)) {
            if (!isConstMethod_ && isMemberOfThis(memberExpr)) {
                Effect e;
                e.kind = EffectKind::MEMBER_WRITE;
                e.target = memberExpr->getMemberDecl()->getNameAsString();
                e.expression = getExprText(op);
                e.line = sm_.getSpellingLineNumber(op->getOperatorLoc());
                e.confidence = 0.95;
                effects_.push_back(std::move(e));
                return true;
            }
        }

        return true;
    }

    // new expressions
    bool VisitCXXNewExpr(clang::CXXNewExpr* expr) {
        Effect e;
        e.kind = EffectKind::MEMORY_ALLOC;
        e.target = expr->getAllocatedType().getAsString();
        e.expression = getExprText(expr);
        e.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        e.confidence = 0.95;
        effects_.push_back(std::move(e));
        return true;
    }

    // delete expressions
    bool VisitCXXDeleteExpr(clang::CXXDeleteExpr* expr) {
        Effect e;
        e.kind = EffectKind::MEMORY_FREE;
        e.target = getExprText(expr->getArgument());
        e.expression = getExprText(expr);
        e.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        e.confidence = 0.95;
        effects_.push_back(std::move(e));
        return true;
    }

    // Method calls on containers
    bool VisitCXXMemberCallExpr(clang::CXXMemberCallExpr* call) {
        auto* methodDecl = call->getMethodDecl();
        if (!methodDecl) {
            return true;
        }

        std::string methodName = methodDecl->getNameAsString();
        std::string qualified_name = methodDecl->getQualifiedNameAsString();
        int line = sm_.getSpellingLineNumber(call->getBeginLoc());

        // Track this member call for frequency analysis
        CallInfo info;
        info.expression = getExprText(call);
        info.line = line;
        info.result_is_cached = isCallResultCached(call);
        call_frequencies_[qualified_name].push_back(info);

        // Check if it's a container modification method
        if (CONTAINER_MODIFY_METHODS.count(methodName)) {
            Effect e;
            e.kind = EffectKind::CONTAINER_MODIFY;
            e.target = getExprText(call->getImplicitObjectArgument());
            e.expression = getExprText(call);
            e.line = line;
            e.confidence = 0.90;
            effects_.push_back(std::move(e));
        }

        return true;
    }

    // Regular function calls (malloc, free, etc.)
    bool VisitCallExpr(clang::CallExpr* call) {
        // Skip member calls (handled separately)
        if (llvm::isa<clang::CXXMemberCallExpr>(call)) {
            return true;
        }

        auto* callee = call->getDirectCallee();
        if (!callee) {
            return true;
        }

        std::string name = callee->getNameAsString();
        std::string qualified_name = callee->getQualifiedNameAsString();
        int line = sm_.getSpellingLineNumber(call->getBeginLoc());

        // Track this call for frequency analysis
        CallInfo info;
        info.expression = getExprText(call);
        info.line = line;
        info.result_is_cached = isCallResultCached(call);
        call_frequencies_[qualified_name].push_back(info);

        // malloc, calloc, realloc
        if (name == "malloc" || name == "calloc" || name == "realloc") {
            Effect e;
            e.kind = EffectKind::MEMORY_ALLOC;
            e.target = name;
            e.expression = getExprText(call);
            e.line = line;
            e.confidence = 0.95;
            effects_.push_back(std::move(e));
        }

        // free
        if (name == "free") {
            Effect e;
            e.kind = EffectKind::MEMORY_FREE;
            e.target = call->getNumArgs() > 0 ? getExprText(call->getArg(0)) : "unknown";
            e.expression = getExprText(call);
            e.line = line;
            e.confidence = 0.95;
            effects_.push_back(std::move(e));
        }

        return true;
    }

private:
    bool isMemberOfThis(const clang::MemberExpr* memberExpr) {
        auto* base = memberExpr->getBase()->IgnoreParenImpCasts();
        // this->member
        if (llvm::isa<clang::CXXThisExpr>(base)) {
            return true;
        }
        // Implicit this (just member_)
        if (memberExpr->isImplicitAccess()) {
            return true;
        }
        return false;
    }

    // Check if call result is stored in a variable (cached)
    bool isCallResultCached(const clang::CallExpr* call) {
        // Walk up the AST to find if this call is on the RHS of an assignment/declaration
        clang::DynTypedNodeList parents = ctx_.getParents(*call);
        if (parents.empty()) {
            return false;
        }

        const clang::DynTypedNode& parent = parents[0];

        // Check if parent is a variable declaration: auto x = call();
        if (parent.get<clang::VarDecl>()) {
            return true;
        }

        // Check if parent is assignment operator RHS: x = call();
        if (const auto* binOp = parent.get<clang::BinaryOperator>()) {
            if (binOp->isAssignmentOp()) {
                return true;
            }
        }

        return false;
    }

    // Generate CALL_FREQUENCY effects from collected call data
    void generateCallFrequencyEffects() {
        if (!func_->hasBody()) {
            return;
        }

        // Find the first line of actual code (after declarations)
        int function_start_line = sm_.getSpellingLineNumber(func_->getBody()->getBeginLoc());

        for (const auto& [func_name, calls] : call_frequencies_) {
            // Skip if no calls (shouldn't happen)
            if (calls.empty()) {
                continue;
            }

            Effect e;
            e.kind = EffectKind::CALL_FREQUENCY;
            e.target = func_name;
            e.call_count = static_cast<int>(calls.size());

            // Check if result is cached and reused (single call with stored result)
            // Multiple calls means NOT cached/reused, even if each individual result is stored
            e.is_cached = (calls.size() == 1 && calls[0].result_is_cached);

            // Check if all calls occur before any loops
            e.occurs_at_start = true;
            if (!loop_start_lines_.empty()) {
                int first_loop_line = *loop_start_lines_.begin();
                for (const auto& call_info : calls) {
                    if (call_info.line >= first_loop_line) {
                        e.occurs_at_start = false;
                        break;
                    }
                }
            }

            // Use first call's info for expression and line
            e.expression = calls[0].expression;
            e.line = calls[0].line;
            e.confidence = 0.90;

            effects_.push_back(std::move(e));
        }
    }

    std::string getExprText(const clang::Expr* expr) {
        auto range = expr->getSourceRange();
        if (range.isValid()) {
            auto begin = sm_.getCharacterData(range.getBegin());
            auto end = sm_.getCharacterData(range.getEnd());
            if (begin && end && end >= begin) {
                size_t len = std::min(static_cast<size_t>(end - begin + 1),
                                      static_cast<size_t>(100));
                return std::string(begin, len);
            }
        }
        return "<unknown>";
    }

    clang::ASTContext& ctx_;
    clang::SourceManager& sm_;
    const clang::FunctionDecl* func_;
    std::unordered_set<std::string> modifiableParams_;
    std::unordered_set<std::string> pointerParams_;
    bool isConstMethod_ = false;
    std::vector<Effect> effects_;

    // Call frequency tracking
    struct CallInfo {
        std::string expression;
        int line;
        bool result_is_cached;  // Result stored in a variable
    };
    std::map<std::string, std::vector<CallInfo>> call_frequencies_;  // function name -> call sites
    std::set<int> loop_start_lines_;  // Track which lines are inside loops
};

class EffectDetectorImpl : public EffectDetector {
public:
    std::vector<Effect> detectEffects(
        const clang::FunctionDecl* func,
        clang::ASTContext& ctx
    ) override {
        if (!func->hasBody()) {
            return {};
        }

        EffectVisitor visitor(ctx, func);
        visitor.TraverseStmt(func->getBody());
        return visitor.getEffects();
    }
};

std::unique_ptr<EffectDetector> createEffectDetector() {
    return std::make_unique<EffectDetectorImpl>();
}

} // namespace axiom
