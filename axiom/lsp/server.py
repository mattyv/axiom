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
    INITIALIZED,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_SAVE,
    TEXT_DOCUMENT_HOVER,
    Diagnostic,
    DiagnosticSeverity,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
    Hover,
    HoverParams,
    InitializedParams,
    MarkupContent,
    MarkupKind,
    MessageType,
    Position,
    ProgressToken,
    PublishDiagnosticsParams,
    Range,
    WorkDoneProgressBegin,
    WorkDoneProgressEnd,
    WorkDoneProgressReport,
)
from pygls.lsp.server import LanguageServer

from axiom.config import AxiomConfig
from axiom.graph import Neo4jLoader
from axiom.lsp.call_sites import CallSiteIndex, build_axiom_tree
from axiom.lsp.diagnostics import DiagnosticMode, call_site_diagnostics
from axiom.lsp.hover import format_axiom_tree, format_hover
from axiom.lsp.query_builder import build_axiom_query
from axiom.models import Axiom, AxiomCollection, AxiomType, SourceLocation
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

        # Track initialization state - heavy loading deferred to post-initialize
        self._initialized = False

        # Load config (lightweight)
        try:
            self._config = AxiomConfig.load()
        except Exception as e:
            logger.warning("Could not load config: %s", e)
            self._config = AxiomConfig()

        # Initialize extractor (lightweight)
        self._extractor = AxiomExtractor(config=self._config)

        # In-memory store for extracted axioms
        self._store = InMemoryAxiomStore()

        # Call site index for tracking function calls
        self._call_site_index = CallSiteIndex()

        # Track file extraction status for error reporting
        # Maps file_path -> (status, message) where status is one of:
        # "ok", "no_compile_commands", "parse_errors", "extractor_error"
        self._file_status: dict[str, tuple[str, str]] = {}

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

        # LanceDB initialized lazily in _do_heavy_initialization
        self._lance: LanceDBLoader | None = None

        # Register handlers
        self._register_handlers()

    def _send_progress(
        self,
        token: ProgressToken,
        value: WorkDoneProgressBegin | WorkDoneProgressReport | WorkDoneProgressEnd,
    ) -> None:
        """Send a progress notification to the client."""
        try:
            if isinstance(value, WorkDoneProgressBegin):
                self.progress.begin(token, value)
            elif isinstance(value, WorkDoneProgressReport):
                self.progress.report(token, value)
            elif isinstance(value, WorkDoneProgressEnd):
                self.progress.end(token, value)
        except Exception as e:
            logger.debug("Failed to send progress: %s", e)

    def _do_heavy_initialization(self) -> None:
        """Perform heavy initialization with progress reporting.

        Called after the client sends 'initialized' notification, so we can
        send progress updates to show status in the IDE.
        """
        if self._initialized:
            return

        # Use a fixed token for initialization progress
        token: ProgressToken = "axiom-init"

        # Create progress token - try both sync and async APIs
        # pygls v2 has create_async, but we may be in sync context
        try:
            # Try sync create first (pygls v1 style)
            if hasattr(self.progress, "create"):
                self.progress.create(token)
        except Exception as e:
            logger.debug("Could not create progress token: %s", e)

        # Begin progress
        self._send_progress(
            token,
            WorkDoneProgressBegin(
                title="Axiom LSP",
                message="Initializing...",
                cancellable=False,
                percentage=0,
            ),
        )

        try:
            # Load Neo4j axioms (40%)
            self._send_progress(
                token,
                WorkDoneProgressReport(
                    message="Loading axioms from Neo4j...",
                    percentage=10,
                ),
            )
            self._load_foundation_axioms()

            # Load LanceDB (40%)
            self._send_progress(
                token,
                WorkDoneProgressReport(
                    message="Loading semantic search index...",
                    percentage=50,
                ),
            )
            self._load_lancedb()

            # Done
            self._send_progress(
                token,
                WorkDoneProgressEnd(message="Ready"),
            )

            self._initialized = True
            logger.info("Axiom LSP initialization complete")

        except Exception as e:
            logger.error("Initialization failed: %s", e)
            self._send_progress(
                token,
                WorkDoneProgressEnd(message=f"Initialization failed: {e}"),
            )
            # Mark as initialized anyway to avoid repeated attempts
            self._initialized = True

    def _load_lancedb(self) -> None:
        """Initialize LanceDB for semantic search."""
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

        @self.feature(INITIALIZED)
        def on_initialized(params: InitializedParams) -> None:
            """Handle initialized notification - perform heavy initialization."""
            # Show a status message immediately
            from lsprotocol.types import ShowMessageParams
            self.window_show_message(
                ShowMessageParams(type=MessageType.Info, message="Axiom LSP: Loading axiom database...")
            )
            self._do_heavy_initialization()

        @self.feature(TEXT_DOCUMENT_DID_OPEN)
        def did_open(params: DidOpenTextDocumentParams) -> None:
            """Handle file open - extract axioms and publish diagnostics."""
            # Ensure initialization is complete before processing files
            if not self._initialized:
                self._do_heavy_initialization()
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

        diagnostics: list[Diagnostic] = []

        try:
            # Check if file is in compile_commands.json before extraction
            file_in_compile_commands = self._extractor.is_live_layer_file(file_path)

            # Extract axioms and call graph
            collection, call_graph, stderr = self._extract_with_stderr(file_path)

            # Determine extraction status based on results
            if stderr and ("error:" in stderr or "fatal error:" in stderr):
                # Parse errors occurred - count them
                error_count = stderr.count("error:")
                if not file_in_compile_commands:
                    # No compile_commands.json - this is the likely cause
                    self._file_status[file_path] = (
                        "no_compile_commands",
                        f"File not in compile_commands.json. Parsing failed with {error_count} error(s). "
                        f"Run 'cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON' to generate it.",
                    )
                else:
                    # Has compile_commands but still errors
                    # Extract first error for context
                    first_error = self._extract_first_error(stderr)
                    self._file_status[file_path] = (
                        "parse_errors",
                        f"Parsing failed with {error_count} error(s): {first_error}",
                    )

                # Add a diagnostic at line 1 to inform user
                diagnostics.append(
                    Diagnostic(
                        range=Range(
                            start=Position(line=0, character=0),
                            end=Position(line=0, character=1),
                        ),
                        message=f"Axiom: {self._file_status[file_path][1]}",
                        severity=DiagnosticSeverity.Information,
                        source="axiom",
                    )
                )
            elif not collection.axioms and not call_graph:
                # No errors but no results - might be ok or might indicate issues
                if not file_in_compile_commands:
                    self._file_status[file_path] = (
                        "no_compile_commands",
                        "File not in compile_commands.json. Include paths may be missing.",
                    )
                else:
                    self._file_status[file_path] = ("ok", "No axioms extracted")
            else:
                self._file_status[file_path] = ("ok", "")

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
            call_diagnostics = call_site_diagnostics(
                file_path,
                self._call_site_index,
                self.get_axioms_for_callee,
                mode=self._diagnostic_mode,
            )
            diagnostics.extend(call_diagnostics)

            logger.info(
                "Extracted %d axioms, %d call sites, publishing %d diagnostics for %s (mode=%s, status=%s)",
                len(collection.axioms),
                len(call_graph),
                len(diagnostics),
                file_path,
                self._diagnostic_mode,
                self._file_status.get(file_path, ("unknown", ""))[0],
            )
            self._publish_diagnostics(uri, diagnostics)

        except Exception as e:
            error_msg = str(e)
            logger.warning("Failed to extract axioms from %s: %s", file_path, error_msg)
            self._file_status[file_path] = ("extractor_error", error_msg)

            # Publish error diagnostic
            diagnostics.append(
                Diagnostic(
                    range=Range(
                        start=Position(line=0, character=0),
                        end=Position(line=0, character=1),
                    ),
                    message=f"Axiom: Extraction failed - {error_msg}",
                    severity=DiagnosticSeverity.Warning,
                    source="axiom",
                )
            )
            self._publish_diagnostics(uri, diagnostics)

    def _extract_with_stderr(
        self, file_path: str
    ) -> tuple[AxiomCollection, list[dict], str]:
        """Extract axioms and return stderr for error analysis.

        Returns:
            Tuple of (collection, call_graph, stderr_output).
        """
        import json
        import subprocess

        from axiom.extractors.clang_loader import parse_json_with_call_graph

        file_path_obj = Path(file_path).resolve()

        # Build command - always use --no-ignore for LSP (we want to analyze any file)
        # and --call-graph to get function call information
        cmd = [
            str(self._extractor.axiom_extract_path),
            str(file_path_obj),
            "--no-ignore",
            "--call-graph",
        ]

        file_in_compile_commands = (
            str(file_path_obj) in self._extractor._load_compile_commands_files()
        )

        if (
            self._extractor.compile_commands_path.exists()
            and file_in_compile_commands
        ):
            cmd.extend(["-p", str(self._extractor.compile_commands_path.parent)])
        else:
            # Fallback mode: add platform-specific stdlib paths
            cmd.extend(["--"] + self._get_fallback_compiler_args())

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        stderr = result.stderr or ""

        if not result.stdout.strip():
            return AxiomCollection(axioms=[], source=str(file_path_obj)), [], stderr

        try:
            data = json.loads(result.stdout)
            collection, call_graph = parse_json_with_call_graph(
                data, source=str(file_path_obj)
            )
            return collection, call_graph, stderr
        except json.JSONDecodeError:
            return AxiomCollection(axioms=[], source=str(file_path_obj)), [], stderr

    def _get_fallback_compiler_args(self) -> list[str]:
        """Get fallback compiler arguments for files not in compile_commands.json.

        On macOS with Homebrew LLVM, we need specific include paths to make
        axiom-extract (built with libTooling) work with the system headers.

        Returns:
            List of compiler arguments.
        """
        import platform
        import shutil

        args = ["-std=c++20"]

        if platform.system() != "Darwin":
            return args

        # On macOS, axiom-extract is built with Homebrew LLVM but needs to
        # work with a mix of libc++ and macOS SDK headers
        llvm_prefix = Path("/opt/homebrew/opt/llvm")
        if not llvm_prefix.exists():
            # Try Intel Mac path
            llvm_prefix = Path("/usr/local/opt/llvm")

        if not llvm_prefix.exists():
            logger.debug("Homebrew LLVM not found, using basic fallback")
            return args

        # Find LLVM version for clang builtin headers
        llvm_lib_clang = llvm_prefix / "lib" / "clang"
        clang_version = None
        if llvm_lib_clang.exists():
            versions = sorted(llvm_lib_clang.iterdir(), reverse=True)
            if versions:
                clang_version = versions[0].name

        # Get macOS SDK path
        sdk_path = None
        xcrun = shutil.which("xcrun")
        if xcrun:
            import subprocess
            try:
                result = subprocess.run(
                    [xcrun, "--show-sdk-path"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    sdk_path = result.stdout.strip()
            except Exception:
                pass

        # Build the include path order that works:
        # 1. -nostdinc++ to disable default C++ stdlib search
        # 2. Homebrew libc++ headers
        # 3. Clang builtin headers (for stddef.h, etc.)
        # 4. macOS SDK headers (for C library)
        args.append("-nostdinc++")

        libcxx_include = llvm_prefix / "include" / "c++" / "v1"
        if libcxx_include.exists():
            args.extend(["-isystem", str(libcxx_include)])

        if clang_version:
            builtin_include = llvm_lib_clang / clang_version / "include"
            if builtin_include.exists():
                args.extend(["-isystem", str(builtin_include)])

        if sdk_path:
            args.extend(["-isystem", f"{sdk_path}/usr/include"])

        logger.debug("Fallback compiler args: %s", args)
        return args

    def _extract_first_error(self, stderr: str) -> str:
        """Extract the first error message from stderr.

        Args:
            stderr: Full stderr output.

        Returns:
            First error line, truncated if needed.
        """
        for line in stderr.split("\n"):
            if "error:" in line:
                # Truncate long error messages
                if len(line) > 100:
                    return line[:100] + "..."
                return line.strip()
        return "Unknown error"

    def _publish_diagnostics(self, uri: str, diagnostics: list[Diagnostic]) -> None:
        """Publish diagnostics to the client."""
        self.text_document_publish_diagnostics(
            PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
        )

    def _uri_to_path(self, uri: str) -> str:
        """Convert file:// URI to file path.

        Also translates host paths to container paths when running in a container
        with AXIOM_HOST_WORKSPACE and AXIOM_CONTAINER_WORKSPACE set.
        """
        import os

        if uri.startswith("file://"):
            path = uri[7:]
        else:
            path = uri

        # Translate host workspace to container workspace if configured
        host_ws = os.environ.get("AXIOM_HOST_WORKSPACE")
        container_ws = os.environ.get("AXIOM_CONTAINER_WORKSPACE")
        if host_ws and container_ws and path.startswith(host_ws):
            path = container_ws + path[len(host_ws):]

        return path

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
        # Check if this file has extraction issues
        file_status = self._file_status.get(file_path)
        if file_status and file_status[0] != "ok":
            status_type, message = file_status
            if status_type == "no_compile_commands":
                return (
                    "**Axiom: Unable to analyze file**\n\n"
                    f"_{message}_\n\n"
                    "To enable axiom analysis, generate `compile_commands.json`:\n"
                    "```bash\n"
                    "cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON\n"
                    "```"
                )
            elif status_type == "parse_errors":
                return f"**Axiom: Parse errors**\n\n_{message}_"
            elif status_type == "extractor_error":
                return f"**Axiom: Extraction error**\n\n_{message}_"

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


def _check_stdin() -> bool:
    """Check if stdin is connected and ready for LSP communication.

    Returns True if stdin appears to be connected to a proper client,
    False if stdin is closed, connected to /dev/null, or otherwise
    unsuitable for LSP communication.
    """
    import select
    import sys

    # Check if stdin is a valid file descriptor
    try:
        fileno = sys.stdin.fileno()
        if fileno < 0:
            return False
    except (ValueError, OSError):
        return False

    # Use select to check if stdin is immediately readable (EOF or data)
    # A real LSP client won't have data ready until we start the protocol
    readable, _, _ = select.select([sys.stdin], [], [], 0)

    if readable:
        # If stdin is immediately readable, peek to see if it's EOF
        # For a real LSP client, stdin should be blocking until the client sends
        try:
            data = sys.stdin.buffer.peek(1)
            if not data:
                # Empty peek means EOF - stdin is closed/disconnected
                return False
        except (OSError, AttributeError):
            # peek not available or error, try non-blocking read approach
            pass

    return True


def main() -> None:
    """Entry point for axiom-lsp command."""
    import sys

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

    # Check if stdin is properly connected before starting server
    if not _check_stdin():
        print(
            "Error: stdin is not connected. The LSP server requires a client "
            "to communicate with over stdin/stdout.",
            file=sys.stderr,
        )
        print(
            "If running in a container, use: podman exec -i <container> axiom-lsp",
            file=sys.stderr,
        )
        sys.exit(1)

    # Create and configure server
    server = AxiomLanguageServer()
    server.set_diagnostic_mode(args.mode)

    # Run server
    logger.info("Starting Axiom LSP server")
    server.start_io()


if __name__ == "__main__":
    main()
