# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Extract C function signatures from header files using tree-sitter."""

from dataclasses import dataclass
from pathlib import Path

import tree_sitter_c as tsc
from tree_sitter import Language, Parser, Node


@dataclass
class SignatureInfo:
    """Information about a C function signature."""

    name: str  # e.g., "malloc"
    signature: str  # e.g., "void *malloc(size_t size)"
    return_type: str  # e.g., "void *"
    parameters: list[tuple[str, str]]  # e.g., [("size_t", "size")]
    header: str  # e.g., "stdlib.h"


class CSignatureExtractor:
    """Extract C function signatures from header files using tree-sitter."""

    def __init__(self, headers_dir: Path) -> None:
        """Initialize extractor.

        Args:
            headers_dir: Directory containing C header files.
        """
        self.headers_dir = Path(headers_dir)
        self.parser = self._init_parser()

    def _init_parser(self) -> Parser:
        """Initialize tree-sitter parser for C."""
        c_language = Language(tsc.language())
        parser = Parser(c_language)
        return parser

    def extract_all(self) -> dict[str, SignatureInfo]:
        """Extract all function signatures from header files.

        Returns:
            Dictionary mapping function name to SignatureInfo.
        """
        signatures: dict[str, SignatureInfo] = {}

        for header_path in self.headers_dir.rglob("*.h"):
            try:
                header_sigs = self._parse_header(header_path)
                for sig in header_sigs:
                    signatures[sig.name] = sig
            except Exception:
                # Skip files that fail to parse
                pass

        return signatures

    def _parse_header(self, header_path: Path) -> list[SignatureInfo]:
        """Parse a single header file for function declarations.

        Args:
            header_path: Path to header file.

        Returns:
            List of SignatureInfo for functions in this header.
        """
        content = header_path.read_bytes()
        tree = self.parser.parse(content)

        signatures: list[SignatureInfo] = []
        header_name = header_path.name

        # Walk the tree looking for function declarations
        self._extract_declarations(tree.root_node, content, header_name, signatures)

        return signatures

    def _extract_declarations(
        self,
        node: Node,
        content: bytes,
        header_name: str,
        signatures: list[SignatureInfo],
    ) -> None:
        """Recursively extract function declarations from AST.

        Args:
            node: Current AST node.
            content: Source file content.
            header_name: Name of header file.
            signatures: List to append signatures to.
        """
        if node.type == "declaration":
            sig = self._parse_declaration(node, content, header_name)
            if sig:
                signatures.append(sig)

        # Recurse into children
        for child in node.children:
            self._extract_declarations(child, content, header_name, signatures)

    def _parse_declaration(
        self, node: Node, content: bytes, header_name: str
    ) -> SignatureInfo | None:
        """Parse a declaration node into SignatureInfo.

        Args:
            node: Declaration AST node.
            content: Source file content.
            header_name: Name of header file.

        Returns:
            SignatureInfo if this is a function declaration, None otherwise.
        """
        # Find function_declarator in the declaration
        func_declarator = self._find_child_by_type(node, "function_declarator")
        if not func_declarator:
            return None

        # Get function name
        func_name = self._get_function_name(func_declarator, content)
        if not func_name:
            return None

        # Get return type (everything before the declarator)
        return_type = self._get_return_type(node, func_declarator, content)

        # Get parameters
        parameters = self._get_parameters(func_declarator, content)

        # Build full signature string
        signature = self._build_signature_string(node, content)

        return SignatureInfo(
            name=func_name,
            signature=signature,
            return_type=return_type,
            parameters=parameters,
            header=header_name,
        )

    def _find_child_by_type(self, node: Node, type_name: str) -> Node | None:
        """Find first child node of given type (recursive)."""
        for child in node.children:
            if child.type == type_name:
                return child
            result = self._find_child_by_type(child, type_name)
            if result:
                return result
        return None

    def _get_function_name(self, func_declarator: Node, content: bytes) -> str | None:
        """Extract function name from function_declarator node."""
        # The identifier is typically the first child or nested in pointer_declarator
        for child in func_declarator.children:
            if child.type == "identifier":
                return content[child.start_byte : child.end_byte].decode("utf-8")
            if child.type == "pointer_declarator":
                return self._get_function_name(child, content)
            if child.type == "parenthesized_declarator":
                # Handle (*func)(...) style
                inner = self._find_child_by_type(child, "identifier")
                if inner:
                    return content[inner.start_byte : inner.end_byte].decode("utf-8")
        return None

    def _get_return_type(
        self, decl_node: Node, func_declarator: Node, content: bytes
    ) -> str:
        """Extract return type from declaration."""
        # Return type is everything from start of declaration to start of function name
        # But we need to handle type specifiers and modifiers

        type_parts: list[str] = []

        for child in decl_node.children:
            if child == func_declarator:
                break
            if child.type == "pointer_declarator":
                break
            if child.type in (
                "primitive_type",
                "type_identifier",
                "sized_type_specifier",
                "struct_specifier",
                "union_specifier",
                "enum_specifier",
            ):
                type_parts.append(
                    content[child.start_byte : child.end_byte].decode("utf-8")
                )
            elif child.type == "type_qualifier":
                type_parts.append(
                    content[child.start_byte : child.end_byte].decode("utf-8")
                )
            elif child.type == "storage_class_specifier":
                # Skip storage class like extern, static
                text = content[child.start_byte : child.end_byte].decode("utf-8")
                if text not in ("extern", "static", "_Noreturn"):
                    type_parts.append(text)

        # Check if the declarator itself has pointer markers
        decl_text = content[func_declarator.start_byte : func_declarator.end_byte].decode("utf-8")
        if decl_text.startswith("*"):
            type_parts.append("*")

        return " ".join(type_parts).strip()

    def _get_parameters(
        self, func_declarator: Node, content: bytes
    ) -> list[tuple[str, str]]:
        """Extract parameter list from function_declarator."""
        parameters: list[tuple[str, str]] = []

        param_list = self._find_child_by_type(func_declarator, "parameter_list")
        if not param_list:
            return parameters

        for child in param_list.children:
            if child.type == "parameter_declaration":
                param_type, param_name = self._parse_parameter(child, content)
                if param_type:
                    parameters.append((param_type, param_name or ""))

        return parameters

    def _parse_parameter(
        self, param_node: Node, content: bytes
    ) -> tuple[str, str | None]:
        """Parse a parameter_declaration node.

        Returns:
            Tuple of (type, name) where name may be None for unnamed params.
        """
        type_parts: list[str] = []
        name: str | None = None

        for child in param_node.children:
            if child.type in (
                "primitive_type",
                "type_identifier",
                "sized_type_specifier",
            ):
                type_parts.append(
                    content[child.start_byte : child.end_byte].decode("utf-8")
                )
            elif child.type == "type_qualifier":
                type_parts.append(
                    content[child.start_byte : child.end_byte].decode("utf-8")
                )
            elif child.type == "identifier":
                name = content[child.start_byte : child.end_byte].decode("utf-8")
            elif child.type == "pointer_declarator":
                # Handle pointer parameters like "void *ptr"
                type_parts.append("*")
                inner_name = self._find_child_by_type(child, "identifier")
                if inner_name:
                    name = content[inner_name.start_byte : inner_name.end_byte].decode(
                        "utf-8"
                    )
            elif child.type == "abstract_pointer_declarator":
                type_parts.append("*")

        return " ".join(type_parts).strip(), name

    def _build_signature_string(self, decl_node: Node, content: bytes) -> str:
        """Build the full signature string from declaration node."""
        # Get the full text and clean it up
        text = content[decl_node.start_byte : decl_node.end_byte].decode("utf-8")

        # Remove trailing semicolon
        text = text.rstrip(";").strip()

        # Normalize whitespace
        text = " ".join(text.split())

        return text
