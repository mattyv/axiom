// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2026 Matt Varendorff
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

    // TODO: Replace hardcoded operators with tag-based matching from Neo4j axioms
    // C++ named casts: static_cast, dynamic_cast, const_cast, reinterpret_cast
    bool VisitCXXNamedCastExpr(clang::CXXNamedCastExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        if (llvm::isa<clang::CXXStaticCastExpr>(expr)) {
            call.callee = "static_cast";
        } else if (llvm::isa<clang::CXXDynamicCastExpr>(expr)) {
            call.callee = "dynamic_cast";
        } else if (llvm::isa<clang::CXXConstCastExpr>(expr)) {
            call.callee = "const_cast";
        } else if (llvm::isa<clang::CXXReinterpretCastExpr>(expr)) {
            call.callee = "reinterpret_cast";
        } else {
            return true;
        }

        std::string targetType = expr->getTypeAsWritten().getAsString();
        call.callee_signature = call.callee + "<" + targetType + ">";
        call.arguments.push_back(getExprText(expr->getSubExpr()));

        calls_.push_back(std::move(call));
        return true;
    }

    // C-style casts
    bool VisitCStyleCastExpr(clang::CStyleCastExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "c_style_cast";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        std::string targetType = expr->getTypeAsWritten().getAsString();
        call.callee_signature = "(" + targetType + ")";
        call.arguments.push_back(getExprText(expr->getSubExpr()));

        calls_.push_back(std::move(call));
        return true;
    }

    // TODO: Replace hardcoded operators with tag-based matching from Neo4j axioms
    // All binary operators
    bool VisitBinaryOperator(clang::BinaryOperator* expr) {
        auto opcode = expr->getOpcode();
        std::string opName;

        switch (opcode) {
            // Arithmetic
            case clang::BO_Add: opName = "operator+"; break;
            case clang::BO_Sub: opName = "operator-"; break;
            case clang::BO_Mul: opName = "operator*"; break;
            case clang::BO_Div: opName = "operator/"; break;
            case clang::BO_Rem: opName = "operator%"; break;
            // Bitwise
            case clang::BO_And: opName = "operator&"; break;
            case clang::BO_Or: opName = "operator|"; break;
            case clang::BO_Xor: opName = "operator^"; break;
            case clang::BO_Shl: opName = "operator<<"; break;
            case clang::BO_Shr: opName = "operator>>"; break;
            // Comparison
            case clang::BO_LT: opName = "operator<"; break;
            case clang::BO_GT: opName = "operator>"; break;
            case clang::BO_LE: opName = "operator<="; break;
            case clang::BO_GE: opName = "operator>="; break;
            case clang::BO_EQ: opName = "operator=="; break;
            case clang::BO_NE: opName = "operator!="; break;
            case clang::BO_Cmp: opName = "operator<=>"; break;
            // Logical
            case clang::BO_LAnd: opName = "operator&&"; break;
            case clang::BO_LOr: opName = "operator||"; break;
            // Assignment
            case clang::BO_Assign: opName = "operator="; break;
            case clang::BO_AddAssign: opName = "operator+="; break;
            case clang::BO_SubAssign: opName = "operator-="; break;
            case clang::BO_MulAssign: opName = "operator*="; break;
            case clang::BO_DivAssign: opName = "operator/="; break;
            case clang::BO_RemAssign: opName = "operator%="; break;
            case clang::BO_AndAssign: opName = "operator&="; break;
            case clang::BO_OrAssign: opName = "operator|="; break;
            case clang::BO_XorAssign: opName = "operator^="; break;
            case clang::BO_ShlAssign: opName = "operator<<="; break;
            case clang::BO_ShrAssign: opName = "operator>>="; break;
            // Comma
            case clang::BO_Comma: opName = "operator,"; break;
            // Pointer-to-member
            case clang::BO_PtrMemD: opName = "operator.*"; break;
            case clang::BO_PtrMemI: opName = "operator->*"; break;
            default:
                return true;
        }

        FunctionCall call;
        call.caller = caller_;
        call.callee = opName;
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        std::string lhsType = expr->getLHS()->getType().getAsString();
        std::string rhsType = expr->getRHS()->getType().getAsString();
        call.callee_signature = lhsType + " " + opName + " " + rhsType;
        call.arguments.push_back(getExprText(expr->getLHS()));
        call.arguments.push_back(getExprText(expr->getRHS()));

        calls_.push_back(std::move(call));
        return true;
    }

    // Unary operators
    bool VisitUnaryOperator(clang::UnaryOperator* expr) {
        auto opcode = expr->getOpcode();
        std::string opName;

        switch (opcode) {
            case clang::UO_PostInc: opName = "operator++(int)"; break;
            case clang::UO_PostDec: opName = "operator--(int)"; break;
            case clang::UO_PreInc: opName = "operator++"; break;
            case clang::UO_PreDec: opName = "operator--"; break;
            case clang::UO_AddrOf: opName = "operator&"; break;
            case clang::UO_Deref: opName = "operator*"; break;
            case clang::UO_Plus: opName = "unary+"; break;
            case clang::UO_Minus: opName = "unary-"; break;
            case clang::UO_Not: opName = "operator~"; break;
            case clang::UO_LNot: opName = "operator!"; break;
            case clang::UO_Real: opName = "__real__"; break;
            case clang::UO_Imag: opName = "__imag__"; break;
            case clang::UO_Extension: opName = "__extension__"; break;
            case clang::UO_Coawait: opName = "co_await"; break;
            default:
                return true;
        }

        FunctionCall call;
        call.caller = caller_;
        call.callee = opName;
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        std::string subType = expr->getSubExpr()->getType().getAsString();
        call.callee_signature = opName + " " + subType;
        call.arguments.push_back(getExprText(expr->getSubExpr()));

        calls_.push_back(std::move(call));
        return true;
    }

    // Array subscript operator
    bool VisitArraySubscriptExpr(clang::ArraySubscriptExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "operator[]";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        std::string baseType = expr->getBase()->getType().getAsString();
        std::string idxType = expr->getIdx()->getType().getAsString();
        call.callee_signature = baseType + "[" + idxType + "]";
        call.arguments.push_back(getExprText(expr->getBase()));
        call.arguments.push_back(getExprText(expr->getIdx()));

        calls_.push_back(std::move(call));
        return true;
    }

    // Conditional operator (ternary)
    bool VisitConditionalOperator(clang::ConditionalOperator* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "operator?:";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = "? :";
        call.arguments.push_back(getExprText(expr->getCond()));
        call.arguments.push_back(getExprText(expr->getTrueExpr()));
        call.arguments.push_back(getExprText(expr->getFalseExpr()));

        calls_.push_back(std::move(call));
        return true;
    }

    // sizeof, alignof
    bool VisitUnaryExprOrTypeTraitExpr(clang::UnaryExprOrTypeTraitExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        switch (expr->getKind()) {
            case clang::UETT_SizeOf: call.callee = "sizeof"; break;
            case clang::UETT_AlignOf: call.callee = "alignof"; break;
            case clang::UETT_PreferredAlignOf: call.callee = "__alignof__"; break;
            default: return true;
        }

        if (expr->isArgumentType()) {
            call.callee_signature = call.callee + "(" + expr->getArgumentType().getAsString() + ")";
        } else {
            call.callee_signature = call.callee + "(expr)";
            call.arguments.push_back(getExprText(expr->getArgumentExpr()));
        }

        calls_.push_back(std::move(call));
        return true;
    }

    // new/delete expressions
    bool VisitCXXNewExpr(clang::CXXNewExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = expr->isArray() ? "operator new[]" : "operator new";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = call.callee + " " + expr->getAllocatedType().getAsString();

        calls_.push_back(std::move(call));
        return true;
    }

    bool VisitCXXDeleteExpr(clang::CXXDeleteExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = expr->isArrayForm() ? "operator delete[]" : "operator delete";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = call.callee;
        call.arguments.push_back(getExprText(expr->getArgument()));

        calls_.push_back(std::move(call));
        return true;
    }

    // throw expression
    bool VisitCXXThrowExpr(clang::CXXThrowExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "throw";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        if (expr->getSubExpr()) {
            call.callee_signature = "throw " + expr->getSubExpr()->getType().getAsString();
            call.arguments.push_back(getExprText(expr->getSubExpr()));
        } else {
            call.callee_signature = "throw"; // rethrow
        }

        calls_.push_back(std::move(call));
        return true;
    }

    // typeid
    bool VisitCXXTypeidExpr(clang::CXXTypeidExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "typeid";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        if (expr->isTypeOperand()) {
            call.callee_signature = "typeid(" + expr->getTypeOperand(ctx_).getAsString() + ")";
        } else {
            call.callee_signature = "typeid(expr)";
            call.arguments.push_back(getExprText(expr->getExprOperand()));
        }

        calls_.push_back(std::move(call));
        return true;
    }

    // noexcept operator
    bool VisitCXXNoexceptExpr(clang::CXXNoexceptExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "noexcept";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = "noexcept(expr)";
        call.arguments.push_back(getExprText(expr->getOperand()));

        calls_.push_back(std::move(call));
        return true;
    }

    // Lambda expressions
    bool VisitLambdaExpr(clang::LambdaExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "lambda";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        // Describe capture mode
        std::string captureDesc;
        switch (expr->getCaptureDefault()) {
            case clang::LCD_None: captureDesc = "[]"; break;
            case clang::LCD_ByCopy: captureDesc = "[=]"; break;
            case clang::LCD_ByRef: captureDesc = "[&]"; break;
        }
        call.callee_signature = "lambda" + captureDesc;

        calls_.push_back(std::move(call));
        return true;
    }

    // Requires expression (C++20 concepts)
    bool VisitRequiresExpr(clang::RequiresExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "requires";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = "requires { ... }";

        calls_.push_back(std::move(call));
        return true;
    }

    // Concept specialization (C++20)
    bool VisitConceptSpecializationExpr(clang::ConceptSpecializationExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        if (auto* conceptDecl = expr->getNamedConcept()) {
            call.callee = conceptDecl->getQualifiedNameAsString();
            call.callee_signature = call.callee + "<...>";
        } else {
            call.callee = "concept";
            call.callee_signature = "concept<...>";
        }

        calls_.push_back(std::move(call));
        return true;
    }

    // co_yield (C++20 coroutines)
    bool VisitCoyieldExpr(clang::CoyieldExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "co_yield";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = "co_yield";
        call.arguments.push_back(getExprText(expr->getOperand()));

        calls_.push_back(std::move(call));
        return true;
    }

    // co_return (C++20 coroutines)
    bool VisitCoreturnStmt(clang::CoreturnStmt* stmt) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "co_return";
        call.line = sm_.getSpellingLineNumber(stmt->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = "co_return";
        if (stmt->getOperand()) {
            call.arguments.push_back(getExprText(stmt->getOperand()));
        }

        calls_.push_back(std::move(call));
        return true;
    }

    // decltype
    // Note: decltype is a type specifier, not typically in expression context,
    // but we can catch it via DecltypeType in certain expressions

    // Member access (-> and .)
    bool VisitMemberExpr(clang::MemberExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = expr->isArrow() ? "operator->" : "operator.";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        std::string baseType = expr->getBase()->getType().getAsString();
        std::string memberName = expr->getMemberDecl()->getNameAsString();
        call.callee_signature = baseType + (expr->isArrow() ? "->" : ".") + memberName;
        call.arguments.push_back(getExprText(expr->getBase()));

        calls_.push_back(std::move(call));
        return true;
    }

    // Initializer list
    bool VisitCXXStdInitializerListExpr(clang::CXXStdInitializerListExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "std::initializer_list";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = "std::initializer_list<" +
            expr->getType().getAsString() + ">";

        calls_.push_back(std::move(call));
        return true;
    }

    // Brace-enclosed initializer list
    bool VisitInitListExpr(clang::InitListExpr* expr) {
        // Only track explicit initializer lists, not implicit ones
        if (expr->isExplicit()) {
            FunctionCall call;
            call.caller = caller_;
            call.callee = "braced_init_list";
            call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
            call.is_virtual = false;

            call.callee_signature = "{ ... }";

            calls_.push_back(std::move(call));
        }
        return true;
    }

    // Range-based for loop (C++11)
    bool VisitCXXForRangeStmt(clang::CXXForRangeStmt* stmt) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "range_for";
        call.line = sm_.getSpellingLineNumber(stmt->getBeginLoc());
        call.is_virtual = false;

        // Get the range expression type
        if (stmt->getRangeInit()) {
            std::string rangeType = stmt->getRangeInit()->getType().getAsString();
            call.callee_signature = "for(: " + rangeType + ")";
            call.arguments.push_back(getExprText(stmt->getRangeInit()));
        } else {
            call.callee_signature = "for(:)";
        }

        calls_.push_back(std::move(call));
        return true;
    }

    // Return statement
    bool VisitReturnStmt(clang::ReturnStmt* stmt) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "return";
        call.line = sm_.getSpellingLineNumber(stmt->getBeginLoc());
        call.is_virtual = false;

        if (stmt->getRetValue()) {
            std::string retType = stmt->getRetValue()->getType().getAsString();
            call.callee_signature = "return " + retType;
            call.arguments.push_back(getExprText(stmt->getRetValue()));
        } else {
            call.callee_signature = "return void";
        }

        calls_.push_back(std::move(call));
        return true;
    }

    // co_await expression (C++20 coroutines)
    bool VisitCoawaitExpr(clang::CoawaitExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "co_await";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = "co_await";
        call.arguments.push_back(getExprText(expr->getOperand()));

        calls_.push_back(std::move(call));
        return true;
    }

    // static_assert (C++11/17)
    bool VisitStaticAssertDecl(clang::StaticAssertDecl* decl) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "static_assert";
        call.line = sm_.getSpellingLineNumber(decl->getBeginLoc());
        call.is_virtual = false;

        if (decl->getMessage()) {
            call.callee_signature = "static_assert(expr, msg)";
        } else {
            call.callee_signature = "static_assert(expr)";
        }

        calls_.push_back(std::move(call));
        return true;
    }

    // if constexpr (C++17) - ConstantExpr wraps compile-time evaluated expressions
    bool VisitIfStmt(clang::IfStmt* stmt) {
        if (stmt->isConstexpr()) {
            FunctionCall call;
            call.caller = caller_;
            call.callee = "if_constexpr";
            call.line = sm_.getSpellingLineNumber(stmt->getBeginLoc());
            call.is_virtual = false;

            call.callee_signature = "if constexpr";
            call.arguments.push_back(getExprText(stmt->getCond()));

            calls_.push_back(std::move(call));
        }
        return true;
    }

    // Structured bindings (C++17) - via DecompositionDecl
    bool VisitDecompositionDecl(clang::DecompositionDecl* decl) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "structured_binding";
        call.line = sm_.getSpellingLineNumber(decl->getBeginLoc());
        call.is_virtual = false;

        std::string bindingNames;
        for (auto* binding : decl->bindings()) {
            if (!bindingNames.empty()) bindingNames += ", ";
            bindingNames += binding->getNameAsString();
        }
        call.callee_signature = "auto [" + bindingNames + "]";

        calls_.push_back(std::move(call));
        return true;
    }

    // nullptr literal
    bool VisitCXXNullPtrLiteralExpr(clang::CXXNullPtrLiteralExpr* expr) {
        FunctionCall call;
        call.caller = caller_;
        call.callee = "nullptr";
        call.line = sm_.getSpellingLineNumber(expr->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = "nullptr";

        calls_.push_back(std::move(call));
        return true;
    }

    // Variable declarations - emit the type being used
    bool VisitVarDecl(clang::VarDecl* decl) {
        // Skip parameters (handled separately), implicit decls, and decls without a location
        if (decl->isImplicit() || !decl->getLocation().isValid()) {
            return true;
        }
        // Skip if this is a parameter
        if (llvm::isa<clang::ParmVarDecl>(decl)) {
            return true;
        }

        clang::QualType type = decl->getType();
        std::string typeName = getCanonicalTypeName(type);

        // Only emit for types we care about (built-ins and common std types)
        if (typeName.empty()) {
            return true;
        }

        FunctionCall call;
        call.caller = caller_;
        call.callee = "type:" + typeName;
        call.line = sm_.getSpellingLineNumber(decl->getBeginLoc());
        call.is_virtual = false;

        call.callee_signature = type.getAsString() + " " + decl->getNameAsString();

        calls_.push_back(std::move(call));
        return true;
    }

    // C++20 three-way comparison result types
    // (These are tracked via operator<=> above)

    // declval (typically in unevaluated context - hard to track)
    // We rely on std::declval being a function call

private:
    // Get canonical type name for built-in and common types
    std::string getCanonicalTypeName(clang::QualType type) {
        // Get string representation first for pattern matching
        std::string typeStr = type.getAsString();

        // Get the canonical (unqualified) type for built-in checks
        clang::QualType canonType = type.getCanonicalType().getUnqualifiedType();

        // Check for built-in types
        if (canonType->isBuiltinType()) {
            if (canonType->isBooleanType()) return "bool";
            if (canonType->isCharType()) return "char";
            if (canonType->isIntegerType()) {
                if (canonType->isSignedIntegerType()) {
                    if (canonType->isSpecificBuiltinType(clang::BuiltinType::Short)) return "short";
                    if (canonType->isSpecificBuiltinType(clang::BuiltinType::Int)) return "int";
                    if (canonType->isSpecificBuiltinType(clang::BuiltinType::Long)) return "long";
                    if (canonType->isSpecificBuiltinType(clang::BuiltinType::LongLong)) return "long long";
                    return "int";  // default signed
                } else {
                    if (canonType->isSpecificBuiltinType(clang::BuiltinType::UShort)) return "unsigned short";
                    if (canonType->isSpecificBuiltinType(clang::BuiltinType::UInt)) return "unsigned int";
                    if (canonType->isSpecificBuiltinType(clang::BuiltinType::ULong)) return "unsigned long";
                    if (canonType->isSpecificBuiltinType(clang::BuiltinType::ULongLong)) return "unsigned long long";
                    return "unsigned";  // default unsigned
                }
            }
            if (canonType->isFloatingType()) {
                if (canonType->isSpecificBuiltinType(clang::BuiltinType::Float)) return "float";
                if (canonType->isSpecificBuiltinType(clang::BuiltinType::Double)) return "double";
                if (canonType->isSpecificBuiltinType(clang::BuiltinType::LongDouble)) return "long double";
                return "double";  // default float
            }
            if (canonType->isVoidType()) return "void";
        }

        // Check for pointer types
        if (canonType->isPointerType()) {
            return "pointer";
        }

        // Check for reference types
        if (canonType->isReferenceType()) {
            return "reference";
        }

        // Check for array types
        if (canonType->isArrayType()) {
            return "array";
        }

        // Check for enum types
        if (canonType->isEnumeralType()) {
            return "enum";
        }

        // Pattern matching for std:: types (order matters - check specific before general)
        // Concurrency types
        if (typeStr.find("atomic") != std::string::npos) return "atomic";
        if (typeStr.find("mutex") != std::string::npos) return "mutex";
        if (typeStr.find("jthread") != std::string::npos) return "jthread";
        if (typeStr.find("thread") != std::string::npos) return "thread";
        if (typeStr.find("condition_variable") != std::string::npos) return "condition_variable";
        if (typeStr.find("lock_guard") != std::string::npos) return "lock";
        if (typeStr.find("unique_lock") != std::string::npos) return "lock";
        if (typeStr.find("shared_lock") != std::string::npos) return "lock";
        if (typeStr.find("scoped_lock") != std::string::npos) return "lock";

        // Smart pointers
        if (typeStr.find("unique_ptr") != std::string::npos) return "unique_ptr";
        if (typeStr.find("shared_ptr") != std::string::npos) return "shared_ptr";
        if (typeStr.find("weak_ptr") != std::string::npos) return "weak_ptr";

        // Utility types
        if (typeStr.find("optional") != std::string::npos) return "optional";
        if (typeStr.find("expected") != std::string::npos) return "expected";
        if (typeStr.find("variant") != std::string::npos) return "variant";
        if (typeStr.find("tuple") != std::string::npos) return "tuple";
        if (typeStr.find("pair") != std::string::npos) return "pair";
        if (typeStr.find("span") != std::string::npos) return "span";

        // String types
        if (typeStr.find("string_view") != std::string::npos) return "string_view";
        if (typeStr.find("string") != std::string::npos) return "string";

        // Container types
        if (typeStr.find("vector") != std::string::npos) return "vector";
        if (typeStr.find("array") != std::string::npos) return "array";
        if (typeStr.find("deque") != std::string::npos) return "deque";
        if (typeStr.find("forward_list") != std::string::npos) return "forward_list";
        if (typeStr.find("list") != std::string::npos) return "list";
        if (typeStr.find("unordered_map") != std::string::npos) return "unordered_map";
        if (typeStr.find("unordered_set") != std::string::npos) return "unordered_set";
        if (typeStr.find("map") != std::string::npos) return "map";
        if (typeStr.find("set") != std::string::npos) return "set";

        // Function types
        if (typeStr.find("function") != std::string::npos) return "function";
        if (typeStr.find("move_only_function") != std::string::npos) return "function";

        // Iterator types
        if (typeStr.find("iterator") != std::string::npos) return "iterator";

        // Common typedefs
        if (typeStr.find("size_t") != std::string::npos) return "size_t";
        if (typeStr.find("ptrdiff_t") != std::string::npos) return "ptrdiff_t";
        if (typeStr.find("intptr_t") != std::string::npos) return "intptr_t";
        if (typeStr.find("uintptr_t") != std::string::npos) return "uintptr_t";

        // Fixed-width integers
        if (typeStr.find("int8_t") != std::string::npos) return "int8_t";
        if (typeStr.find("int16_t") != std::string::npos) return "int16_t";
        if (typeStr.find("int32_t") != std::string::npos) return "int32_t";
        if (typeStr.find("int64_t") != std::string::npos) return "int64_t";
        if (typeStr.find("uint8_t") != std::string::npos) return "uint8_t";
        if (typeStr.find("uint16_t") != std::string::npos) return "uint16_t";
        if (typeStr.find("uint32_t") != std::string::npos) return "uint32_t";
        if (typeStr.find("uint64_t") != std::string::npos) return "uint64_t";

        // Not a type we track
        return "";
    }

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
