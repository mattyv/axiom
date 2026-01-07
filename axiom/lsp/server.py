# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# SPDX-License-Identifier: BSL-1.0

"""Axiom LSP server using pygls.

Provides C++ code intelligence based on extracted axioms:
- Diagnostics on file open/save
- Hover for function axioms

Usage:
    axiom-lsp [--verbose]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from lsprotocol.types import (
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_SAVE,
    TEXT_DOCUMENT_HOVER,
    Diagnostic,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
    Hover,
    HoverParams,
    MarkupContent,
    MarkupKind,
    PublishDiagnosticsParams,
)
from pygls.lsp.server import LanguageServer

from axiom.config import AxiomConfig
from axiom.graph import Neo4jLoader
from axiom.lsp.call_sites import CallSiteIndex, build_axiom_tree
from axiom.lsp.diagnostics import DiagnosticMode, call_site_diagnostics
from axiom.lsp.hover import format_axiom_tree, format_hover
from axiom.lsp.query_builder import build_axiom_query
from axiom.models import Axiom, AxiomType, SourceLocation
from axiom.vectors import LanceDBLoader
from axiom.watcher.extractor import AxiomExtractor
from axiom.watcher.store import InMemoryAxiomStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AxiomLanguageServer(LanguageServer):
    """Axiom Language Server for C++ code intelligence.

    Extracts axioms from C++ files and provides:
    - Diagnostics: Shows axiom context as hints
    - Hover: Shows formatted axiom details
    """

    def __init__(self) -> None:
        """Initialize the Axiom language server."""
        super().__init__(name="axiom-lsp", version="0.1.0")

        # Load config
        try:
            self._config = AxiomConfig.load()
        except Exception as e:
            logger.warning("Could not load config: %s", e)
            self._config = AxiomConfig()

        # Initialize extractor
        self._extractor = AxiomExtractor(config=self._config)

        # In-memory store for extracted axioms
        self._store = InMemoryAxiomStore()

        # Call site index for tracking function calls
        self._call_site_index = CallSiteIndex()

        # Axioms indexed by function name for call site lookups
        self._axioms_by_function: dict[str, list[Axiom]] = {}

        # Axioms indexed by tag for operator/language construct lookups
        self._axioms_by_tag: dict[str, list[Axiom]] = {}

        # TODO: Replace hardcoded mapping with data-driven approach
        # Maps operator names (from extractor) to axiom tags
        self._operator_to_tags: dict[str, list[str]] = {
            # Arithmetic operators
            "operator/": ["division"],
            "operator%": ["modulus"],
            "operator+": ["addition"],
            "operator-": ["subtraction"],
            "operator*": ["multiplication", "pointer", "dereference"],
            # Compound assignment operators
            "operator=": ["assignment"],
            "operator+=": ["compound-assignment", "addition", "assignment"],
            "operator-=": ["compound-assignment", "subtraction", "assignment"],
            "operator*=": ["compound-assignment", "multiplication", "assignment"],
            "operator/=": ["compound-assignment", "division", "assignment"],
            "operator%=": ["compound-assignment", "modulus", "assignment"],
            "operator&=": ["compound-assignment", "bitwise", "assignment"],
            "operator|=": ["compound-assignment", "bitwise", "assignment"],
            "operator^=": ["compound-assignment", "bitwise", "assignment"],
            "operator<<=": ["compound-assignment", "shift", "assignment"],
            "operator>>=": ["compound-assignment", "shift", "assignment"],
            # Increment/decrement
            "operator++": ["increment"],
            "operator++(int)": ["increment"],
            "operator--": ["decrement"],
            "operator--(int)": ["decrement"],
            # Subscript and access
            "operator[]": ["array", "subscript"],
            "operator->": ["pointer", "member-access"],
            "operator.": ["member-access"],
            # Comparison operators
            "operator<": ["comparison"],
            "operator>": ["comparison"],
            "operator<=": ["comparison"],
            "operator>=": ["comparison"],
            "operator==": ["comparison", "equality"],
            "operator!=": ["comparison", "equality"],
            "operator<=>": ["comparison", "spaceship", "three-way"],
            # Bitwise operators
            "operator<<": ["shift", "bitwise"],
            "operator>>": ["shift", "bitwise"],
            "operator&": ["bitwise", "pointer", "address-of"],
            "operator|": ["bitwise"],
            "operator^": ["bitwise"],
            "operator~": ["bitwise"],
            # Logical operators
            "operator!": ["boolean"],
            "operator&&": ["boolean"],
            "operator||": ["boolean"],
            # Casts
            "static_cast": ["static_cast", "cast", "conversion"],
            "dynamic_cast": ["dynamic_cast", "cast", "polymorphism"],
            "const_cast": ["const_cast", "cast", "const"],
            "reinterpret_cast": ["reinterpret_cast", "cast"],
            "c_style_cast": ["cast"],
            # Memory operators
            "operator new": ["new", "allocation"],
            "operator new[]": ["new", "allocation", "array"],
            "operator delete": ["delete", "deallocation"],
            "operator delete[]": ["delete", "deallocation", "array"],
            # Other operators/keywords
            "throw": ["exception", "throw"],
            "sizeof": ["sizeof"],
            "alignof": ["alignof", "alignment"],
            "typeid": ["typeid", "rtti"],
            "noexcept": ["noexcept", "exception"],
            "lambda": ["lambda", "capture"],
            "requires": ["concepts", "requires"],
            "co_await": ["coroutine", "await"],
            "co_yield": ["coroutine", "yield"],
            "co_return": ["coroutine"],
            # Initialization
            "braced_init_list": ["initialization", "initializer_list"],
            "std::initializer_list": ["initializer_list"],
            # Range-based for loop
            "range_for": ["range", "iterator", "begin", "end"],
            # Return statement
            "return": ["return", "return-value", "return_value", "postcondition"],
            # C++17/20 language constructs
            "static_assert": ["static_assert", "constexpr", "constant_expression"],
            "if_constexpr": ["constexpr", "constant_expression"],
            "structured_binding": ["binding", "structured_binding"],
            "nullptr": ["nullptr", "null", "null_pointer", "null-pointer"],
            # Built-in types (from type:X declarations)
            "type:bool": ["bool", "boolean"],
            "type:char": ["char", "character"],
            "type:int": ["int", "integer", "integral", "signed"],
            "type:short": ["int", "integer", "integral", "signed"],
            "type:long": ["int", "integer", "integral", "signed"],
            "type:long long": ["int", "integer", "integral", "signed"],
            "type:unsigned": ["int", "integer", "integral", "unsigned"],
            "type:unsigned int": ["int", "integer", "integral", "unsigned"],
            "type:unsigned short": ["int", "integer", "integral", "unsigned"],
            "type:unsigned long": ["int", "integer", "integral", "unsigned"],
            "type:unsigned long long": ["int", "integer", "integral", "unsigned"],
            "type:float": ["float", "floating-point", "floating_point"],
            "type:double": ["float", "double", "floating-point", "floating_point"],
            "type:long double": ["float", "double", "floating-point", "floating_point"],
            "type:void": ["void"],
            "type:pointer": ["pointer"],
            "type:reference": ["reference"],
            "type:enum": ["enum", "enumeration"],
            # Fixed-width integers
            "type:int8_t": ["integer", "integral", "signed"],
            "type:int16_t": ["integer", "integral", "signed"],
            "type:int32_t": ["integer", "integral", "signed"],
            "type:int64_t": ["integer", "integral", "signed"],
            "type:uint8_t": ["integer", "integral", "unsigned"],
            "type:uint16_t": ["integer", "integral", "unsigned"],
            "type:uint32_t": ["integer", "integral", "unsigned"],
            "type:uint64_t": ["integer", "integral", "unsigned"],
            "type:size_t": ["size", "integer", "unsigned"],
            "type:ptrdiff_t": ["integer", "signed"],
            "type:intptr_t": ["integer", "pointer", "signed"],
            "type:uintptr_t": ["integer", "pointer", "unsigned"],
            # Concurrency types
            "type:atomic": ["atomic", "atomics", "atomicity", "memory_order"],
            "type:mutex": ["mutex", "lock", "thread"],
            "type:thread": ["thread", "jthread"],
            "type:jthread": ["thread", "jthread"],
            "type:condition_variable": ["condition_variable", "thread"],
            "type:lock": ["lock", "mutex", "thread"],
            # Smart pointers
            "type:unique_ptr": ["unique_ptr", "smart_pointer"],
            "type:shared_ptr": ["shared_ptr", "smart_pointer"],
            "type:weak_ptr": ["weak_ptr", "smart_pointer"],
            # Utility types
            "type:optional": ["optional"],
            "type:expected": ["expected"],
            "type:variant": ["variant"],
            "type:tuple": ["tuple"],
            "type:pair": ["pair"],
            "type:span": ["span"],
            "type:string": ["string", "container"],
            "type:string_view": ["string_view", "string"],
            # Container types
            "type:vector": ["vector", "container", "sequence-container"],
            "type:array": ["array", "container", "sequence-container"],
            "type:deque": ["deque", "container", "sequence-container"],
            "type:list": ["list", "container", "sequence-container"],
            "type:forward_list": ["forward_list", "container", "sequence-container"],
            "type:map": ["map", "container", "associative-container"],
            "type:set": ["set", "container", "associative-container"],
            "type:unordered_map": ["unordered_map", "container", "associative-container"],
            "type:unordered_set": ["unordered_set", "container", "associative-container"],
            # Function types
            "type:function": ["function", "callable"],
            # Iterator types
            "type:iterator": ["iterator"],
        }

        # Patterns for STL container methods (matched by suffix)
        # TODO: Replace with data-driven approach
        self._method_suffix_to_tags: dict[str, list[str]] = {
            "::size": ["size", "container"],
            "::empty": ["container"],
            "::begin": ["begin", "iterator", "range"],
            "::end": ["end", "iterator", "range"],
            "::cbegin": ["begin", "iterator", "range"],
            "::cend": ["end", "iterator", "range"],
            "::rbegin": ["begin", "iterator", "range"],
            "::rend": ["end", "iterator", "range"],
            "::front": ["container", "element_access"],
            "::back": ["container", "element_access"],
            "::at": ["container", "element_access", "bounds_check"],
            "::data": ["container", "pointer"],
            "::push_back": ["container", "push_back", "sequence-container"],
            "::pop_back": ["container", "pop_back", "sequence-container"],
            "::push_front": ["container", "push_front", "sequence-container"],
            "::pop_front": ["container", "pop_front", "sequence-container"],
            "::insert": ["container", "insert"],
            "::erase": ["container", "erase"],
            "::clear": ["container"],
            "::resize": ["container", "size"],
            "::reserve": ["container"],
            "::capacity": ["container"],
            "::emplace": ["container", "emplace"],
            "::emplace_back": ["container", "emplace", "sequence-container"],
            "::emplace_front": ["container", "emplace", "sequence-container"],
            "::find": ["container", "algorithm"],
            "::count": ["container", "algorithm"],
            "::contains": ["container"],
            "::vector": ["container", "sequence-container", "constructor"],
            "::string": ["container", "sequence-container", "constructor"],
            "::array": ["container", "sequence-container", "constructor"],
            "::deque": ["container", "sequence-container", "constructor"],
            "::list": ["container", "sequence-container", "constructor"],
            "::map": ["container", "associative-container", "constructor"],
            "::set": ["container", "associative-container", "constructor"],
            "::unordered_map": ["container", "associative-container", "constructor"],
            "::unordered_set": ["container", "associative-container", "constructor"],
            "::optional": ["optional", "constructor"],
            "::unique_ptr": ["smart_pointer", "unique_ptr", "constructor"],
            "::shared_ptr": ["smart_pointer", "shared_ptr", "constructor"],
            "::weak_ptr": ["smart_pointer", "weak_ptr", "constructor"],
            "::get": ["get", "tuple"],
            "::value": ["optional", "value"],
            "::value_or": ["optional", "value_or"],
            "::has_value": ["optional", "has_value"],
            "::reset": ["smart_pointer", "reset"],
            "::release": ["smart_pointer", "release"],
        }

        # Diagnostic mode
        self._diagnostic_mode: DiagnosticMode = "default"

        # Load foundation axioms from Neo4j
        self._load_foundation_axioms()

        # Initialize LanceDB for semantic search (optional, used when available)
        self._lance: LanceDBLoader | None = None
        try:
            # Resolve lancedb_path relative to config root
            lancedb_path = self._config.resolve_path(self._config.static.lancedb_path)
            self._lance = LanceDBLoader(db_path=str(lancedb_path))
            if self._lance.count() > 0:
                logger.info("LanceDB loaded with %d axioms for semantic search", self._lance.count())
            else:
                logger.warning("LanceDB is empty, falling back to tag-based lookup")
                self._lance = None
        except Exception as e:
            logger.warning("Could not load LanceDB: %s, falling back to tag-based lookup", e)
            self._lance = None

        # Register handlers
        self._register_handlers()

    def _load_foundation_axioms(self) -> None:
        """Load foundation/library axioms from Neo4j into function and tag indices."""
        try:
            neo4j = Neo4jLoader(
                uri=self._config.static.neo4j_uri,
                user=self._config.static.neo4j_user,
                password=self._config.static.neo4j_password,
            )

            function_count = 0
            tag_count = 0

            with neo4j.driver.session() as session:
                # Load all axioms (not just those with function names)
                result = session.run("MATCH (a:Axiom) RETURN a")

                for record in result:
                    axiom_dict = dict(record["a"])
                    axiom = self._dict_to_axiom(axiom_dict)

                    # Index by function name if present
                    if axiom.function:
                        if axiom.function not in self._axioms_by_function:
                            self._axioms_by_function[axiom.function] = []
                        self._axioms_by_function[axiom.function].append(axiom)
                        function_count += 1

                    # Index by tags
                    tags = axiom_dict.get("tags", []) or []
                    for tag in tags:
                        if tag not in self._axioms_by_tag:
                            self._axioms_by_tag[tag] = []
                        self._axioms_by_tag[tag].append(axiom)
                        tag_count += 1

            neo4j.close()
            logger.info(
                "Loaded axioms: %d by function (%d functions), %d by tag (%d tags)",
                function_count,
                len(self._axioms_by_function),
                tag_count,
                len(self._axioms_by_tag),
            )
        except Exception as e:
            logger.warning("Could not load foundation axioms from Neo4j: %s", e)

    def _dict_to_axiom(self, data: dict) -> Axiom:
        """Convert a Neo4j axiom dict to an Axiom model.

        Args:
            data: Dict from Neo4j with axiom properties.

        Returns:
            Axiom model instance.
        """
        # Parse axiom type
        axiom_type_str = data.get("axiom_type", "")
        axiom_type = None
        if axiom_type_str:
            try:
                axiom_type = AxiomType(axiom_type_str)
            except ValueError:
                pass

        return Axiom(
            id=data.get("id", ""),
            content=data.get("content", ""),
            formal_spec=data.get("formal_spec", ""),
            source=SourceLocation(
                file=data.get("source_file", ""),
                module=data.get("module_name", ""),
            ),
            layer=data.get("layer", ""),
            confidence=data.get("confidence", 1.0),
            function=data.get("function"),
            header=data.get("header"),
            axiom_type=axiom_type,
            depends_on=data.get("depends_on", []) or [],
        )

    def get_axioms_for_callee(
        self, callee: str, signature: str | None = None
    ) -> list[Axiom]:
        """Get axioms for a callee using semantic search or fallback to tags.

        Lookup order:
        1. Direct function name match (for std library functions)
        2. Semantic search using LanceDB (if available)
        3. Fallback to tag-based lookup (legacy)

        Args:
            callee: The callee name (function name or operator).
            signature: Optional signature with type info (e.g., "int operator/ int").

        Returns:
            List of matching axioms (deduplicated).
        """
        # 1. Check function name directly (fast path for std library functions)
        # Skip this for operators - they need semantic search for type context
        if callee in self._axioms_by_function and not callee.startswith("operator"):
            return self._axioms_by_function[callee]

        # 2. Try semantic search if LanceDB is available (preferred for operators)
        if self._lance is not None:
            query = build_axiom_query(callee, signature)
            results = self._lance.search(query, limit=10)

            if results:
                axioms = []
                seen_ids: set[str] = set()

                for r in results:
                    # Filter to preconditions/postconditions/invariants, or untyped axioms
                    # (untyped axioms are language semantics rules from C++ spec)
                    axiom_type = r.get("axiom_type", "") or ""
                    if axiom_type and axiom_type.upper() not in (
                        "PRECONDITION", "POSTCONDITION", "INVARIANT"
                    ):
                        continue

                    axiom_id = r.get("id", "")
                    if axiom_id in seen_ids:
                        continue
                    seen_ids.add(axiom_id)

                    # Convert dict to Axiom
                    axiom = self._dict_to_axiom(r)
                    axioms.append(axiom)

                if axioms:
                    logger.debug(
                        "Semantic search for '%s' (sig=%s) found %d axioms",
                        callee, signature, len(axioms)
                    )
                    return axioms

        # 3. Fallback to tag-based lookup
        return self._get_axioms_by_tags(callee)

    def _get_axioms_by_tags(self, callee: str) -> list[Axiom]:
        """Legacy tag-based axiom lookup (fallback).

        Args:
            callee: The callee name (function name or operator).

        Returns:
            List of matching axioms (deduplicated).
        """
        axioms: list[Axiom] = []
        seen_ids: set[str] = set()

        def add_axiom(axiom: Axiom) -> None:
            if axiom.id not in seen_ids:
                axioms.append(axiom)
                seen_ids.add(axiom.id)

        def add_axioms_for_tag(tag: str) -> None:
            if tag in self._axioms_by_tag:
                for axiom in self._axioms_by_tag[tag]:
                    add_axiom(axiom)

        # Check tags via exact operator mapping
        if callee in self._operator_to_tags:
            for tag in self._operator_to_tags[callee]:
                add_axioms_for_tag(tag)

        # Check method suffix patterns (e.g., std::vector<int>::size -> ::size)
        for suffix, tags in self._method_suffix_to_tags.items():
            if callee.endswith(suffix):
                for tag in tags:
                    add_axioms_for_tag(tag)
                break  # Only match one suffix pattern

        return axioms

    def _register_handlers(self) -> None:
        """Register LSP event handlers."""

        @self.feature(TEXT_DOCUMENT_DID_OPEN)
        def did_open(params: DidOpenTextDocumentParams) -> None:
            """Handle file open - extract axioms and publish diagnostics."""
            self._handle_file_change(params.text_document.uri)

        @self.feature(TEXT_DOCUMENT_DID_SAVE)
        def did_save(params: DidSaveTextDocumentParams) -> None:
            """Handle file save - re-extract axioms and publish diagnostics."""
            self._handle_file_change(params.text_document.uri)

        @self.feature(TEXT_DOCUMENT_HOVER)
        def hover(params: HoverParams) -> Hover | None:
            """Handle hover request - return axiom details."""
            uri = params.text_document.uri
            file_path = self._uri_to_path(uri)

            content = self.get_hover_for_position(
                file_path,
                line=params.position.line,
                character=params.position.character,
            )

            if content is None:
                return None

            return Hover(
                contents=MarkupContent(kind=MarkupKind.Markdown, value=content)
            )

    def _handle_file_change(self, uri: str) -> None:
        """Handle file open or save - extract and publish diagnostics."""
        file_path = self._uri_to_path(uri)

        # Only process C++ files
        if not self._is_cpp_file(file_path):
            return

        try:
            # Extract axioms and call graph
            collection, call_graph = self._extractor.extract_file_with_call_graph(
                Path(file_path)
            )

            # Update store (remove old axioms for this file, add new ones)
            self._store.delete_by_file(file_path)
            self._store.upsert(collection.axioms)

            # Index call sites for this file
            self._call_site_index.clear_file(file_path)
            self._call_site_index.add_call_graph(file_path, call_graph)

            # Update axioms by function index
            for axiom in collection.axioms:
                if axiom.function:
                    if axiom.function not in self._axioms_by_function:
                        self._axioms_by_function[axiom.function] = []
                    self._axioms_by_function[axiom.function].append(axiom)

            # Generate diagnostics at call sites only (not definitions)
            diagnostics = call_site_diagnostics(
                file_path,
                self._call_site_index,
                self.get_axioms_for_callee,
                mode=self._diagnostic_mode,
            )

            logger.info(
                "Extracted %d axioms, %d call sites, publishing %d diagnostics for %s (mode=%s)",
                len(collection.axioms),
                len(call_graph),
                len(diagnostics),
                file_path,
                self._diagnostic_mode,
            )
            self._publish_diagnostics(uri, diagnostics)

        except Exception as e:
            logger.warning("Failed to extract axioms from %s: %s", file_path, e)
            # Clear diagnostics on error
            self._publish_diagnostics(uri, [])

    def _publish_diagnostics(self, uri: str, diagnostics: list[Diagnostic]) -> None:
        """Publish diagnostics to the client."""
        self.text_document_publish_diagnostics(
            PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
        )

    def _uri_to_path(self, uri: str) -> str:
        """Convert file:// URI to file path."""
        if uri.startswith("file://"):
            return uri[7:]
        return uri

    def _is_cpp_file(self, file_path: str) -> bool:
        """Check if file is a C++ source file."""
        return Path(file_path).suffix.lower() in {
            ".cpp",
            ".cc",
            ".cxx",
            ".c",
            ".hpp",
            ".hh",
            ".hxx",
            ".h",
        }

    def get_hover_for_position(
        self,
        file_path: str,
        line: int,
        character: int,
    ) -> str | None:
        """Get hover content for a position.

        Prioritizes call sites over definition sites:
        1. First check if there are function calls at this line
        2. If so, show the axiom tree for the called function(s)
        3. Otherwise, fall back to definition-site axioms

        Args:
            file_path: Path to the source file.
            line: 0-indexed line number.
            character: 0-indexed character position.

        Returns:
            Markdown hover content, or None if no axioms match.
        """
        # LSP uses 0-indexed lines, call site index uses 1-indexed
        lsp_line = line + 1

        # Check for call sites at this line first
        callees = self._call_site_index.get_callees_at_line(file_path, lsp_line)
        if callees:
            parts: list[str] = []
            for call in callees:
                callee = call.get("callee")
                if not callee:
                    continue

                # Build axiom tree for this callee
                tree = build_axiom_tree(
                    callee,
                    self._call_site_index,
                    self.get_axioms_for_callee,
                    max_depth=3,
                )

                # Only show if there are axioms
                if tree.axioms or tree.children:
                    parts.append(format_axiom_tree(tree))
                    parts.append("")

            if parts:
                return "\n".join(parts).strip()

        # Fall back to definition-site axioms
        axioms = self._store.query_by_file(file_path)

        if not axioms:
            return None

        # Find axioms that overlap with this line
        matching_axioms = [
            a
            for a in axioms
            if a.source.line_start is not None
            and a.source.line_start <= lsp_line
            and (a.source.line_end is None or a.source.line_end >= lsp_line)
        ]

        if not matching_axioms:
            return None

        return format_hover(matching_axioms)

    def set_diagnostic_mode(self, mode: DiagnosticMode) -> None:
        """Set the diagnostic mode.

        Args:
            mode: "default", "llm", or "human".
        """
        self._diagnostic_mode = mode


def main() -> None:
    """Entry point for axiom-lsp command."""
    parser = argparse.ArgumentParser(description="Axiom LSP server")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--mode",
        choices=["default", "llm", "human"],
        default="default",
        help="Diagnostic mode (default: default)",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create and configure server
    server = AxiomLanguageServer()
    server.set_diagnostic_mode(args.mode)

    # Run server
    logger.info("Starting Axiom LSP server")
    server.start_io()


if __name__ == "__main__":
    main()
