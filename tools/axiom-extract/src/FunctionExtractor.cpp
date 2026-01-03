// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "Extractors.h"

#include <clang/AST/ASTContext.h>
#include <clang/AST/Attr.h>
#include <clang/AST/DeclCXX.h>
#include <clang/AST/DeclTemplate.h>
#include <clang/AST/Expr.h>
#include <clang/AST/ExprCXX.h>
#include <clang/AST/RecursiveASTVisitor.h>
#include <clang/Basic/SourceManager.h>
#include <sstream>

namespace axiom {

class FunctionExtractorImpl : public FunctionExtractor,
                               public clang::RecursiveASTVisitor<FunctionExtractorImpl> {
public:
    std::vector<FunctionInfo> extractFunctions(clang::ASTContext& ctx) override {
        functions_.clear();
        ctx_ = &ctx;
        TraverseDecl(ctx.getTranslationUnitDecl());
        return std::move(functions_);
    }

    bool VisitFunctionDecl(clang::FunctionDecl* decl) {
        // Skip implicit declarations
        if (decl->isImplicit()) {
            return true;
        }

        // Skip if this is a templated function - we'll handle it in VisitFunctionTemplateDecl
        if (decl->getDescribedFunctionTemplate()) {
            return true;
        }

        // Skip template specializations/instantiations - handle in template visitor
        if (decl->isFunctionTemplateSpecialization()) {
            return true;
        }

        // Skip if not first declaration (but allow template pattern)
        if (!decl->isFirstDecl()) {
            return true;
        }

        // Skip functions not in user code (system headers)
        auto& sm = ctx_->getSourceManager();
        if (sm.isInSystemHeader(decl->getLocation())) {
            return true;
        }

        FunctionInfo info;
        info.decl = decl;
        info.name = decl->getNameAsString();
        info.qualified_name = decl->getQualifiedNameAsString();
        info.signature = buildSignature(decl);
        info.header = getHeaderPath(decl, sm);
        info.line_start = sm.getSpellingLineNumber(decl->getBeginLoc());
        info.line_end = sm.getSpellingLineNumber(decl->getEndLoc());

        // Extract C++20 attributes
        extractAttributes(decl, info);

        functions_.push_back(std::move(info));
        return true;
    }

    bool VisitFunctionTemplateDecl(clang::FunctionTemplateDecl* decl) {
        // Skip if in system header
        auto& sm = ctx_->getSourceManager();
        if (sm.isInSystemHeader(decl->getLocation())) {
            return true;
        }

        // Get the templated function
        clang::FunctionDecl* func = decl->getTemplatedDecl();
        if (!func) {
            return true;
        }

        FunctionInfo info;
        info.decl = func;
        info.name = func->getNameAsString();
        info.qualified_name = func->getQualifiedNameAsString();
        info.signature = buildSignature(func);
        info.header = getHeaderPath(func, sm);
        info.line_start = sm.getSpellingLineNumber(decl->getBeginLoc());
        info.line_end = sm.getSpellingLineNumber(decl->getEndLoc());

        // Mark as template and extract template params
        info.is_template = true;
        auto* tpl = decl->getTemplateParameters();
        if (tpl) {
            info.template_param_count = tpl->size();
            for (const auto* param : *tpl) {
                if (param->isParameterPack()) {
                    info.is_variadic_template = true;
                }
                // Get parameter name and type
                std::string paramStr;
                if (const auto* ttp = llvm::dyn_cast<clang::TemplateTypeParmDecl>(param)) {
                    paramStr = "typename";
                    if (!ttp->getName().empty()) {
                        paramStr += " " + ttp->getNameAsString();
                    }
                    if (ttp->isParameterPack()) {
                        paramStr += "...";
                    }
                } else if (const auto* nttp = llvm::dyn_cast<clang::NonTypeTemplateParmDecl>(param)) {
                    paramStr = nttp->getType().getAsString();
                    if (!nttp->getName().empty()) {
                        paramStr += " " + nttp->getNameAsString();
                    }
                }
                info.template_params.push_back(paramStr);
            }
        }

        // Extract C++20 attributes from the function
        extractAttributes(func, info);

        functions_.push_back(std::move(info));
        return true;
    }

private:
    std::string buildSignature(const clang::FunctionDecl* decl) {
        std::ostringstream ss;

        // Return type
        ss << decl->getReturnType().getAsString() << " ";

        // Qualified name
        ss << decl->getQualifiedNameAsString() << "(";

        // Parameters
        bool first = true;
        for (const auto* param : decl->parameters()) {
            if (!first) ss << ", ";
            first = false;
            ss << param->getType().getAsString();
            if (!param->getName().empty()) {
                ss << " " << param->getNameAsString();
            }
        }
        ss << ")";

        // Const qualifier
        if (const auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(decl)) {
            if (method->isConst()) ss << " const";
        }

        // noexcept specifier
        if (isNoexcept(decl)) {
            ss << " noexcept";
        }

        return ss.str();
    }

    std::string getHeaderPath(const clang::FunctionDecl* decl,
                               const clang::SourceManager& sm) {
        auto loc = decl->getLocation();
        if (loc.isValid()) {
            auto file = sm.getFilename(loc);
            return file.str();
        }
        return "";
    }

    bool isNoexcept(const clang::FunctionDecl* decl) {
        auto* proto = decl->getType()->getAs<clang::FunctionProtoType>();
        if (proto) {
            switch (proto->getExceptionSpecType()) {
                case clang::EST_BasicNoexcept:
                case clang::EST_NoexceptTrue:
                    return true;
                default:
                    return false;
            }
        }
        return false;
    }

    void extractAttributes(const clang::FunctionDecl* decl, FunctionInfo& info) {
        // noexcept
        info.is_noexcept = isNoexcept(decl);

        // [[nodiscard]]
        info.is_nodiscard = decl->hasAttr<clang::WarnUnusedResultAttr>();

        // [[deprecated]]
        info.is_deprecated = decl->hasAttr<clang::DeprecatedAttr>();

        // const method
        if (const auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(decl)) {
            info.is_const = method->isConst();
        }

        // constexpr
        info.is_constexpr = decl->isConstexpr();

        // consteval (C++20)
        info.is_consteval = decl->isConsteval();

        // deleted
        info.is_deleted = decl->isDeleted();

        // defaulted
        info.is_defaulted = decl->isDefaulted();

        // requires clause (C++20)
        if (auto trail = decl->getTrailingRequiresClause(); trail.ConstraintExpr) {
            std::string requiresStr;
            llvm::raw_string_ostream os(requiresStr);
            trail.ConstraintExpr->printPretty(os, nullptr, ctx_->getPrintingPolicy());
            info.requires_clause = os.str();
        }

        // Template info
        if (const auto* ftd = decl->getDescribedFunctionTemplate()) {
            info.is_template = true;
            auto* tpl = ftd->getTemplateParameters();
            if (tpl) {
                info.template_param_count = tpl->size();
                for (const auto* param : *tpl) {
                    // Check for parameter pack
                    if (param->isParameterPack()) {
                        info.is_variadic_template = true;
                    }
                    // Get parameter name and type
                    std::string paramStr;
                    if (const auto* ttp = llvm::dyn_cast<clang::TemplateTypeParmDecl>(param)) {
                        paramStr = "typename";
                        if (!ttp->getName().empty()) {
                            paramStr += " " + ttp->getNameAsString();
                        }
                        if (ttp->isParameterPack()) {
                            paramStr += "...";
                        }
                    } else if (const auto* nttp = llvm::dyn_cast<clang::NonTypeTemplateParmDecl>(param)) {
                        paramStr = nttp->getType().getAsString();
                        if (!nttp->getName().empty()) {
                            paramStr += " " + nttp->getNameAsString();
                        }
                    }
                    info.template_params.push_back(paramStr);
                }
            }
        }
        // Also check if this is a member of a template class
        else if (const auto* method = llvm::dyn_cast<clang::CXXMethodDecl>(decl)) {
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
    }

    clang::ASTContext* ctx_ = nullptr;
    std::vector<FunctionInfo> functions_;
};

std::unique_ptr<FunctionExtractor> createFunctionExtractor() {
    return std::make_unique<FunctionExtractorImpl>();
}

} // namespace axiom
