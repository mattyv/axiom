// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2026 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

/// @file AxiomPlugin.cpp
/// @brief Clangd plugin for axiom-based code intelligence.
///
/// This plugin provides:
/// - Diagnostics for axiom violations and context
/// - Hover information with axiom trees
///
/// It communicates with axiom-query-server via Unix socket.

#include "DiagnosticEmitter.h"
#include "HoverProvider.h"
#include "QueryClient.h"

#include <clang/AST/ASTConsumer.h>
#include <clang/AST/RecursiveASTVisitor.h>
#include <clang/Frontend/CompilerInstance.h>
#include <clang/Frontend/FrontendAction.h>
#include <clang/Tooling/Tooling.h>

#include <memory>
#include <string>
#include <vector>

namespace axiom {

/// Visitor that collects function call expressions.
class CallExprVisitor : public clang::RecursiveASTVisitor<CallExprVisitor> {
public:
    explicit CallExprVisitor(clang::ASTContext& context)
        : context_(context) {}

    bool VisitCallExpr(clang::CallExpr* call) {
        if (auto* callee = call->getDirectCallee()) {
            std::string qualified_name = callee->getQualifiedNameAsString();

            // Include parameter types for overload resolution
            std::string full_sig = qualified_name + "(";
            bool first = true;
            for (const auto* param : callee->parameters()) {
                if (!first) full_sig += ", ";
                full_sig += param->getType().getAsString();
                first = false;
            }
            full_sig += ")";

            clang::SourceLocation loc = call->getBeginLoc();
            if (loc.isValid()) {
                symbols_.emplace_back(full_sig, loc);
            }
        }
        return true;
    }

    const std::vector<std::pair<std::string, clang::SourceLocation>>& getSymbols() const {
        return symbols_;
    }

private:
    clang::ASTContext& context_;
    std::vector<std::pair<std::string, clang::SourceLocation>> symbols_;
};

/// AST consumer that processes the translation unit.
class AxiomASTConsumer : public clang::ASTConsumer {
public:
    explicit AxiomASTConsumer(QueryClient& client)
        : client_(client), emitter_(client), hover_(client) {}

    void HandleTranslationUnit(clang::ASTContext& context) override {
        // Visit all call expressions
        CallExprVisitor visitor(context);
        visitor.TraverseDecl(context.getTranslationUnitDecl());

        const auto& symbols = visitor.getSymbols();
        if (symbols.empty()) {
            return;
        }

        // Generate diagnostics
        auto diagnostics = emitter_.generateDiagnostics(symbols);

        // In a real clangd plugin, we would emit these via clangd's diagnostic API.
        // For now, this demonstrates the architecture.
        // TODO: Integrate with clangd's FeatureModules or TidyProvider
        for (const auto& diag : diagnostics) {
            // Placeholder: In production, emit via clang::DiagnosticsEngine
            // or clangd's Diagnostic structures
            (void)diag;
        }
    }

private:
    QueryClient& client_;
    DiagnosticEmitter emitter_;
    HoverProvider hover_;
};

/// Frontend action that creates our AST consumer.
class AxiomAction : public clang::ASTFrontendAction {
public:
    explicit AxiomAction(QueryClient& client) : client_(client) {}

    std::unique_ptr<clang::ASTConsumer> CreateASTConsumer(
        clang::CompilerInstance& ci,
        llvm::StringRef file) override {
        return std::make_unique<AxiomASTConsumer>(client_);
    }

private:
    QueryClient& client_;
};

} // namespace axiom

//-----------------------------------------------------------------------------
// Plugin Registration
//-----------------------------------------------------------------------------
// Note: Clangd plugin API is not yet stable. This file provides the core
// components (QueryClient, DiagnosticEmitter, HoverProvider) that can be
// integrated once clangd's plugin system is finalized.
//
// Current integration options:
// 1. Use as a standalone clang-tidy check
// 2. Fork clangd and integrate directly
// 3. Wait for clangd's FeatureModules API to stabilize
//
// The components are designed to be reusable across these approaches.
//-----------------------------------------------------------------------------
