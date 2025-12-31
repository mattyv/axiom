# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""LLM-based axiom extraction using function subgraphs and RAG.

This module orchestrates the extraction of K-semantic axioms from C/C++ functions
by combining tree-sitter parsing with LLM analysis and RAG-based foundation axiom lookup.
"""

import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import toml

from axiom.models import Axiom, AxiomType, SourceLocation
from axiom.models.operation import FunctionSubgraph, MacroDefinition

from .prompts import (
    MACRO_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_extraction_prompt,
    build_macro_extraction_prompt,
    build_macro_search_queries,
    build_search_queries,
)
from .subgraph_builder import SubgraphBuilder


@dataclass
class ExtractionResult:
    """Result of axiom extraction for a single function."""

    function_name: str
    file_path: str
    axioms: list[Axiom] = field(default_factory=list)
    raw_response: str = ""
    error: str | None = None
    subgraph: FunctionSubgraph | None = None


@dataclass
class MacroExtractionResult:
    """Result of axiom extraction for a single macro."""

    macro_name: str
    file_path: str
    axioms: list[Axiom] = field(default_factory=list)
    raw_response: str = ""
    error: str | None = None
    macro: MacroDefinition | None = None


@dataclass
class ExtractionJob:
    """A batch extraction job for multiple functions."""

    job_id: str
    source_files: list[str]
    results: list[ExtractionResult] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed


class AxiomExtractor:
    """Extract K-semantic axioms from C/C++ functions using LLM + RAG.

    This class combines:
    1. Tree-sitter parsing to build function operation subgraphs
    2. RAG queries to find related foundation axioms
    3. LLM prompting to extract semantic axioms
    """

    def __init__(
        self,
        llm_client=None,
        vector_db=None,
        language: str = "cpp",
    ):
        """Initialize the extractor.

        Args:
            llm_client: LLM client (Anthropic, OpenAI, etc.) - if None, extraction is simulated
            vector_db: LanceDBLoader instance for RAG queries - if None, RAG is skipped
            language: Source language ("c" or "cpp")
        """
        self.llm_client = llm_client
        self.vector_db = vector_db
        self.subgraph_builder = SubgraphBuilder(language=language)
        self.language = language

    def extract_from_source(
        self,
        source_code: str,
        function_name: str,
        file_path: str = "",
        header: str = "",
    ) -> ExtractionResult:
        """Extract axioms from a single function in source code.

        Args:
            source_code: Complete source code containing the function
            function_name: Name of the function to extract from
            file_path: Path to the source file (for metadata)
            header: Header file this function belongs to

        Returns:
            ExtractionResult with extracted axioms or error
        """
        result = ExtractionResult(
            function_name=function_name,
            file_path=file_path,
        )

        # Step 1: Build subgraph
        subgraph = self.subgraph_builder.build(source_code, function_name)
        if subgraph is None:
            result.error = f"Function '{function_name}' not found in source"
            return result

        result.subgraph = subgraph

        # Step 2: Check if function has hazardous operations
        if not self._has_hazardous_ops(subgraph):
            # No axioms needed for this function
            return result

        # Step 3: Query RAG for related axioms
        related_axioms = self._query_rag(subgraph)

        # Step 4: Build prompt and call LLM
        prompt = build_extraction_prompt(
            subgraph=subgraph,
            source_code=self._extract_function_source(source_code, subgraph),
            related_axioms=related_axioms,
            file_path=file_path,
        )

        # Step 5: Call LLM
        raw_response = self._call_llm(prompt)
        result.raw_response = raw_response

        if raw_response:
            # Step 6: Parse response into Axiom objects
            axioms = self._parse_llm_response(
                raw_response, function_name, header, file_path, subgraph.signature
            )
            result.axioms = axioms

        return result

    def extract_from_file(
        self,
        file_path: str,
        function_names: list[str] | None = None,
        progress_callback=None,
    ) -> list[ExtractionResult]:
        """Extract axioms from all functions in a file.

        Args:
            file_path: Path to the source file
            function_names: Optional list of specific functions to extract.
                           If None, extracts from all functions.
            progress_callback: Optional callback(func_name, current, total) for progress

        Returns:
            List of ExtractionResult for each function
        """
        path = Path(file_path)
        if not path.exists():
            return [ExtractionResult(
                function_name="",
                file_path=file_path,
                error=f"File not found: {file_path}",
            )]

        source_code = path.read_text()

        # Find all functions if not specified
        if function_names is None:
            subgraphs = self.subgraph_builder.build_all(source_code)
            function_names = [sg.name for sg in subgraphs]

        # Determine header from file path
        header = self._infer_header(file_path)

        results = []
        total_funcs = len(function_names)
        for i, func_name in enumerate(function_names):
            if progress_callback:
                progress_callback(func_name, i + 1, total_funcs)

            result = self.extract_from_source(
                source_code=source_code,
                function_name=func_name,
                file_path=file_path,
                header=header,
            )
            results.append(result)

        return results

    # =========================================================================
    # Macro extraction methods
    # =========================================================================

    def extract_macros_from_source(
        self,
        source_code: str,
        file_path: str = "",
        header: str = "",
        only_hazardous: bool = True,
    ) -> list[MacroExtractionResult]:
        """Extract axioms from all macros in source code.

        Args:
            source_code: Complete source code
            file_path: Path to the source file (for metadata)
            header: Header file name
            only_hazardous: If True, only extract from macros with hazardous ops

        Returns:
            List of MacroExtractionResult for each macro
        """
        # Extract all macros
        macros = self.subgraph_builder.extract_macros(source_code, file_path)

        results = []
        for macro in macros:
            # Skip non-hazardous if requested
            if only_hazardous and not self.subgraph_builder.has_hazardous_macro(macro):
                continue

            result = self.extract_from_macro(macro, header)
            results.append(result)

        return results

    def extract_from_macro(
        self,
        macro: MacroDefinition,
        header: str = "",
    ) -> MacroExtractionResult:
        """Extract axioms from a single macro.

        Args:
            macro: The MacroDefinition to extract from
            header: Header file name

        Returns:
            MacroExtractionResult with extracted axioms
        """
        result = MacroExtractionResult(
            macro_name=macro.name,
            file_path=macro.file_path or "",
            macro=macro,
        )

        # Query RAG for related axioms
        related_axioms = self._query_macro_rag(macro)

        # Build prompt
        prompt = build_macro_extraction_prompt(
            macro=macro,
            related_axioms=related_axioms,
            file_path=macro.file_path or "",
        )

        # Call LLM
        raw_response = self._call_macro_llm(prompt)
        result.raw_response = raw_response

        if raw_response:
            # Parse response into Axiom objects
            axioms = self._parse_llm_response(
                raw_response,
                macro.name,
                header or self._infer_header(macro.file_path or ""),
                macro.file_path or "",
                macro.to_signature(),
            )
            # Add macro tag to all extracted axioms
            for axiom in axioms:
                if "macro" not in axiom.tags:
                    axiom.tags.append("macro")
            result.axioms = axioms

        return result

    def extract_macros_from_file(
        self,
        file_path: str,
        only_hazardous: bool = True,
        progress_callback=None,
    ) -> list[MacroExtractionResult]:
        """Extract axioms from all macros in a file.

        Args:
            file_path: Path to the source file
            only_hazardous: If True, only extract from macros with hazardous ops
            progress_callback: Optional callback(macro_name, current, total)

        Returns:
            List of MacroExtractionResult for each macro
        """
        path = Path(file_path)
        if not path.exists():
            return [MacroExtractionResult(
                macro_name="",
                file_path=file_path,
                error=f"File not found: {file_path}",
            )]

        source_code = path.read_text()
        header = self._infer_header(file_path)

        # Extract all macros
        macros = self.subgraph_builder.extract_macros(source_code, file_path)

        # Filter to hazardous if requested
        if only_hazardous:
            macros = [m for m in macros if self.subgraph_builder.has_hazardous_macro(m)]

        results = []
        total = len(macros)
        for i, macro in enumerate(macros):
            if progress_callback:
                progress_callback(macro.name, i + 1, total)

            result = self.extract_from_macro(macro, header)
            results.append(result)

        return results

    def _query_macro_rag(self, macro: MacroDefinition) -> list[dict]:
        """Query RAG for related foundation axioms for a macro.

        Args:
            macro: The macro definition

        Returns:
            List of related axiom dicts from vector DB
        """
        if self.vector_db is None:
            return []

        queries = build_macro_search_queries(macro)

        seen_ids = set()
        results = []

        for query in queries:
            search_results = self.vector_db.search(query, limit=5)
            for result in search_results:
                axiom_id = result.get("id")
                if axiom_id and axiom_id not in seen_ids:
                    seen_ids.add(axiom_id)
                    results.append(result)

        return results

    def _call_macro_llm(self, prompt: str) -> str:
        """Call the LLM with the macro extraction prompt.

        Args:
            prompt: The formatted extraction prompt

        Returns:
            Raw LLM response text
        """
        if self.llm_client is None:
            return ""

        # Handle different LLM client types
        if self.llm_client == "claude-cli":
            return self._call_claude_cli(prompt, system_prompt=MACRO_SYSTEM_PROMPT)

        elif hasattr(self.llm_client, "messages"):
            # Anthropic client
            response = self.llm_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=MACRO_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            if response.content:
                return response.content[0].text
            return ""

        elif hasattr(self.llm_client, "chat"):
            # OpenAI-style client
            response = self.llm_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": MACRO_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            if response.choices and response.choices[0].message:
                return response.choices[0].message.content or ""
            return ""

        return ""

    def _has_hazardous_ops(self, subgraph: FunctionSubgraph) -> bool:
        """Check if subgraph has operations requiring axioms.

        Args:
            subgraph: The function subgraph to check

        Returns:
            True if the function has hazardous operations
        """
        # Check for operations that may need semantic constraints
        if subgraph.get_divisions():
            return True
        if subgraph.get_pointer_operations():
            return True
        if subgraph.get_memory_operations():
            return True
        if subgraph.get_function_calls():
            return True
        return False

    def _query_rag(self, subgraph: FunctionSubgraph) -> list[dict]:
        """Query RAG for related foundation axioms.

        Args:
            subgraph: The function subgraph

        Returns:
            List of related axiom dicts from vector DB
        """
        if self.vector_db is None:
            return []

        # Generate search queries based on operations
        queries = build_search_queries(subgraph)

        # Collect unique results
        seen_ids = set()
        results = []

        for query in queries:
            search_results = self.vector_db.search(query, limit=5)
            for result in search_results:
                axiom_id = result.get("id")
                if axiom_id and axiom_id not in seen_ids:
                    seen_ids.add(axiom_id)
                    results.append(result)

        return results

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM with the extraction prompt.

        Args:
            prompt: The formatted extraction prompt

        Returns:
            Raw LLM response text
        """
        if self.llm_client is None:
            # Return empty for testing without LLM
            return ""

        # Handle different LLM client types
        if self.llm_client == "claude-cli":
            # Use Claude CLI via subprocess
            return self._call_claude_cli(prompt)

        elif hasattr(self.llm_client, "messages"):
            # Anthropic client
            response = self.llm_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            if response.content:
                return response.content[0].text
            return ""

        elif hasattr(self.llm_client, "chat"):
            # OpenAI-style client
            response = self.llm_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            if response.choices and response.choices[0].message:
                return response.choices[0].message.content or ""
            return ""

        return ""

    def _call_claude_cli(self, prompt: str, system_prompt: str = None) -> str:
        """Call Claude CLI for extraction.

        Args:
            prompt: The formatted extraction prompt
            system_prompt: Optional system prompt (defaults to SYSTEM_PROMPT)

        Returns:
            Raw response text from Claude CLI
        """
        import subprocess

        if system_prompt is None:
            system_prompt = SYSTEM_PROMPT

        # Use --system-prompt for the system prompt and pass user prompt directly
        try:
            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--system-prompt", system_prompt,
                    "--model", "sonnet",
                    "--dangerously-skip-permissions",
                    prompt,
                ],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes for complex extractions
            )

            if result.returncode != 0:
                # Log error to stderr but return what we got
                if result.stderr:
                    print(f"Claude CLI warning: {result.stderr}", file=sys.stderr)

            return result.stdout

        except subprocess.TimeoutExpired:
            print("Claude CLI timeout after 5 minutes", file=sys.stderr)
            return ""
        except FileNotFoundError:
            print("Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code", file=sys.stderr)
            return ""
        except subprocess.SubprocessError as e:
            print(f"Claude CLI error: {e}", file=sys.stderr)
            return ""

    def _parse_llm_response(
        self,
        response: str,
        function_name: str,
        header: str,
        file_path: str,
        signature: str = "",
    ) -> list[Axiom]:
        """Parse LLM response into Axiom objects.

        Args:
            response: Raw LLM response (should be TOML)
            function_name: Name of the function
            header: Header file
            file_path: Source file path
            signature: Full function/macro signature

        Returns:
            List of parsed Axiom objects
        """
        axioms = []

        # Extract TOML block from response
        toml_match = re.search(r"```toml\s*(.*?)\s*```", response, re.DOTALL)
        if toml_match:
            toml_text = toml_match.group(1)
        else:
            # Try parsing the whole response as TOML
            toml_text = response

        try:
            data = toml.loads(toml_text)
        except toml.TomlDecodeError:
            # Could not parse TOML
            return axioms

        # Extract axioms from parsed data
        raw_axioms = data.get("axioms", [])
        if not raw_axioms and isinstance(data, list):
            raw_axioms = data

        for raw in raw_axioms:
            try:
                axiom = self._create_axiom_from_dict(
                    raw, function_name, header, file_path, signature
                )
                if axiom:
                    axioms.append(axiom)
            except (KeyError, TypeError, ValueError) as e:
                # Skip malformed axioms but log for debugging
                print(f"Warning: skipping malformed axiom: {e}", file=sys.stderr)
                continue

        return axioms

    def _create_axiom_from_dict(
        self,
        data: dict,
        function_name: str,
        header: str,
        file_path: str,
        signature: str = "",
    ) -> Axiom | None:
        """Create an Axiom object from parsed dict.

        Args:
            data: Parsed axiom dict from TOML
            function_name: Function name (fallback)
            header: Header file (fallback)
            file_path: Source file path
            signature: Full function/macro signature

        Returns:
            Axiom object or None if invalid
        """
        # Generate ID if not provided
        axiom_id = data.get("id")
        if not axiom_id:
            content_hash = hashlib.md5(
                f"{function_name}:{data.get('content', '')}".encode()
            ).hexdigest()[:8]
            axiom_id = f"lib_{function_name}_{content_hash}"

        # Parse axiom_type
        axiom_type_str = data.get("axiom_type", "")
        axiom_type = None
        if axiom_type_str:
            try:
                axiom_type = AxiomType(axiom_type_str.lower())
            except ValueError:
                pass

        return Axiom(
            id=axiom_id,
            content=data.get("content", ""),
            formal_spec=data.get("formal_spec", ""),
            layer="library",
            source=SourceLocation(
                file=file_path,
                module=function_name,
            ),
            function=data.get("function", function_name),
            header=data.get("header", header),
            signature=data.get("signature", signature),
            axiom_type=axiom_type,
            on_violation=data.get("on_violation"),
            confidence=data.get("confidence", 0.8),
            c_standard_refs=data.get("c_standard_refs", []),
            tags=data.get("tags", []),
            depends_on=data.get("depends_on", []),
        )

    def _extract_function_source(
        self,
        full_source: str,
        subgraph: FunctionSubgraph,
    ) -> str:
        """Extract just the function source code.

        Args:
            full_source: Complete source file
            subgraph: The function subgraph with line numbers

        Returns:
            Just the function's source code
        """
        lines = full_source.split("\n")
        start = max(0, subgraph.line_start - 1)
        end = min(len(lines), subgraph.line_end)
        return "\n".join(lines[start:end])

    def _infer_header(self, file_path: str) -> str:
        """Infer header file from source path.

        Args:
            file_path: Path to source file

        Returns:
            Inferred header name
        """
        path = Path(file_path)

        # If it's already a header, use it
        if path.suffix in (".h", ".hpp", ".hxx"):
            return path.name

        # Try to find corresponding header
        header_suffixes = [".h", ".hpp", ".hxx"]
        for suffix in header_suffixes:
            header_path = path.with_suffix(suffix)
            if header_path.exists():
                return header_path.name

        # Default to source file name
        return path.name


def extract_axioms(
    source_code: str,
    function_name: str,
    llm_client=None,
    vector_db=None,
    language: str = "cpp",
    file_path: str = "",
    header: str = "",
) -> ExtractionResult:
    """Convenience function to extract axioms from a function.

    Args:
        source_code: Complete source code
        function_name: Name of function to extract from
        llm_client: Optional LLM client
        vector_db: Optional LanceDB loader
        language: "c" or "cpp"
        file_path: Source file path
        header: Header file name

    Returns:
        ExtractionResult with extracted axioms
    """
    extractor = AxiomExtractor(
        llm_client=llm_client,
        vector_db=vector_db,
        language=language,
    )
    return extractor.extract_from_source(
        source_code=source_code,
        function_name=function_name,
        file_path=file_path,
        header=header,
    )
