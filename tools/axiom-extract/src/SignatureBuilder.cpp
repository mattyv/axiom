// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "SignatureBuilder.h"

#include <clang/AST/Decl.h>
#include <clang/AST/DeclCXX.h>
#include <clang/AST/Type.h>
#include <sstream>

namespace axiom {

std::string buildFunctionSignature(const clang::FunctionDecl* decl) {
    std::ostringstream sig;

    // Storage class specifiers (static, extern)
    switch (decl->getStorageClass()) {
        case clang::SC_Static:
            sig << "static ";
            break;
        case clang::SC_Extern:
            sig << "extern ";
            break;
        default:
            break;
    }

    // Inline specifier
    if (decl->isInlineSpecified()) {
        sig << "inline ";
    }

    // Virtual specifier (for methods)
    if (const auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(decl)) {
        if (method->isVirtual()) {
            sig << "virtual ";
        }
    }

    // Explicit specifier (for constructors/conversion operators)
    if (const auto* ctor = llvm::dyn_cast<clang::CXXConstructorDecl>(decl)) {
        if (ctor->isExplicit()) {
            sig << "explicit ";
        }
    }
    if (const auto* conv = llvm::dyn_cast<clang::CXXConversionDecl>(decl)) {
        if (conv->isExplicit()) {
            sig << "explicit ";
        }
    }

    // Consteval (C++20) - must come before constexpr
    if (decl->isConsteval()) {
        sig << "consteval ";
    }
    // Constexpr
    else if (decl->isConstexpr()) {
        sig << "constexpr ";
    }

    // Return type (skip for constructors/destructors)
    if (!llvm::isa<clang::CXXConstructorDecl>(decl) &&
        !llvm::isa<clang::CXXDestructorDecl>(decl)) {
        sig << decl->getReturnType().getAsString() << " ";
    }

    // Qualified name
    sig << decl->getQualifiedNameAsString();

    // Parameters
    sig << "(";
    bool first = true;
    for (const auto* param : decl->parameters()) {
        if (!first) {
            sig << ", ";
        }
        first = false;

        sig << param->getType().getAsString();

        // Include parameter name if available
        if (!param->getName().empty()) {
            sig << " " << param->getNameAsString();
        }
    }
    sig << ")";

    // CV-qualifiers (const, volatile) for methods
    if (const auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(decl)) {
        if (method->isConst()) {
            sig << " const";
        }
        if (method->isVolatile()) {
            sig << " volatile";
        }
    }

    // Ref-qualifiers (&, &&) for methods (C++11)
    if (const auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(decl)) {
        switch (method->getRefQualifier()) {
            case clang::RQ_LValue:
                sig << " &";
                break;
            case clang::RQ_RValue:
                sig << " &&";
                break;
            default:
                break;
        }
    }

    // Exception specification
    if (const auto* proto = decl->getType()->getAs<clang::FunctionProtoType>()) {
        auto exSpec = proto->getExceptionSpecType();
        if (exSpec == clang::EST_BasicNoexcept || exSpec == clang::EST_NoexceptTrue) {
            sig << " noexcept";
        }
        // Could also handle noexcept(expr), throw(), etc. if needed
    }

    // Deleted/defaulted (C++11)
    if (decl->isDeleted()) {
        sig << " = delete";
    } else if (decl->isDefaulted()) {
        sig << " = default";
    }

    return sig.str();
}

} // namespace axiom
