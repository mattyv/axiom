// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#pragma once

#include <string>

namespace clang {
class FunctionDecl;
}

namespace axiom {

/**
 * Build a clean function signature from a Clang FunctionDecl.
 *
 * Extracts the complete signature including:
 * - Storage class specifiers (static, extern)
 * - Inline specifier
 * - Virtual specifier
 * - Constexpr/consteval/constinit
 * - Return type
 * - Qualified name
 * - Parameters
 * - CV-qualifiers (const, volatile)
 * - Ref-qualifiers (&, &&)
 * - Exception specification (noexcept)
 *
 * Does NOT include:
 * - Function body
 * - Preprocessor directives
 * - Comments
 * - Default arguments
 *
 * @param decl The function declaration to build signature from
 * @return The function signature string
 */
std::string buildFunctionSignature(const clang::FunctionDecl* decl);

} // namespace axiom
