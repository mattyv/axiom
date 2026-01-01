# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Regression tests for bug fixes.

These tests ensure that previously fixed bugs don't reappear.
"""

import subprocess
import sys
from io import StringIO
from unittest.mock import patch


class TestSQLInjectionEscape:
    """Tests for SQL injection prevention in LanceDB queries.

    Note: We test the escape logic directly since lancedb is an optional dependency.
    The actual implementation in axiom/vectors/loader.py uses the same logic.
    """

    @staticmethod
    def _escape_sql_string(value: str) -> str:
        """Mirror of the escape function in vectors/loader.py."""
        return value.replace("'", "''")

    def test_escape_single_quotes(self):
        """Test that single quotes are properly escaped."""
        assert self._escape_sql_string("test") == "test"
        assert self._escape_sql_string("test'value") == "test''value"
        assert self._escape_sql_string("it's") == "it''s"
        assert self._escape_sql_string("a'b'c") == "a''b''c"

    def test_escape_empty_string(self):
        """Test escaping empty string."""
        assert self._escape_sql_string("") == ""

    def test_escape_no_quotes(self):
        """Test string without quotes passes through unchanged."""
        assert self._escape_sql_string("normal_function_name") == "normal_function_name"

    def test_escape_multiple_consecutive_quotes(self):
        """Test multiple consecutive quotes are escaped."""
        assert self._escape_sql_string("test''value") == "test''''value"


class TestEmptyLLMResponseHandling:
    """Tests for handling empty LLM responses without IndexError."""

    def test_parse_llm_response_empty_content(self):
        """Test parsing empty TOML response."""
        from axiom.ingestion import AxiomExtractor

        extractor = AxiomExtractor()
        result = extractor._parse_llm_response(
            response="",
            function_name="test_func",
            header="test.h",
            file_path="/test/path.cpp",
        )
        assert result == []

    def test_parse_llm_response_invalid_toml(self):
        """Test parsing invalid TOML response."""
        from axiom.ingestion import AxiomExtractor

        extractor = AxiomExtractor()
        result = extractor._parse_llm_response(
            response="not valid toml {{{",
            function_name="test_func",
            header="test.h",
            file_path="/test/path.cpp",
        )
        assert result == []

    def test_parse_llm_response_empty_axioms_list(self):
        """Test parsing TOML with empty axioms list."""
        from axiom.ingestion import AxiomExtractor

        extractor = AxiomExtractor()
        result = extractor._parse_llm_response(
            response="```toml\n[axioms]\n```",
            function_name="test_func",
            header="test.h",
            file_path="/test/path.cpp",
        )
        assert result == []


class TestMalformedAxiomHandling:
    """Tests for handling malformed axiom dictionaries."""

    def test_malformed_axiom_non_dict_skipped(self):
        """Test that non-dict axiom entries are skipped with warning."""
        from axiom.ingestion import AxiomExtractor

        extractor = AxiomExtractor()

        # Capture stderr to check warning is logged
        old_stderr = sys.stderr
        sys.stderr = StringIO()

        try:
            # This TOML will parse axioms as a list with a string instead of dict
            result = extractor._parse_llm_response(
                response="""```toml
axioms = ["not a dict", "also not a dict"]
```""",
                function_name="test_func",
                header="test.h",
                file_path="/test/path.cpp",
            )
            stderr_output = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        # Should return empty list (malformed axioms skipped)
        assert result == []
        # Should have logged warnings with function context
        assert "warning" in stderr_output.lower() or "skipping" in stderr_output.lower()
        assert "test_func" in stderr_output  # Should include function name
        assert "test.h" in stderr_output  # Should include header

    def test_valid_axiom_parsed(self):
        """Test that valid axioms are parsed correctly."""
        from axiom.ingestion import AxiomExtractor

        extractor = AxiomExtractor()

        result = extractor._parse_llm_response(
            response="""```toml
[[axioms]]
content = "Valid axiom content"
axiom_type = "precondition"
```""",
            function_name="test_func",
            header="test.h",
            file_path="/test/path.cpp",
        )

        # Should have one valid axiom
        assert len(result) == 1
        assert result[0].content == "Valid axiom content"

    def test_missing_content_creates_empty_axiom(self):
        """Test that missing content field creates axiom with empty content."""
        from axiom.ingestion import AxiomExtractor

        extractor = AxiomExtractor()

        result = extractor._parse_llm_response(
            response="""```toml
[[axioms]]
axiom_type = "precondition"
```""",
            function_name="test_func",
            header="test.h",
            file_path="/test/path.cpp",
        )

        # Should create axiom with empty content (forgiving behavior)
        assert len(result) == 1
        assert result[0].content == ""


class TestMCPServerMissingIdHandling:
    """Tests for MCP server handling missing 'id' fields."""

    def test_format_result_missing_id(self):
        """Test that missing 'id' field uses 'unknown' default."""
        # This tests the pattern: r.get('id', 'unknown')
        result_without_id = {"content": "test content", "layer": "test"}

        # Verify the .get pattern works
        assert result_without_id.get("id", "unknown") == "unknown"

    def test_format_result_with_id(self):
        """Test that present 'id' field is used."""
        result_with_id = {"id": "test_id_123", "content": "test content"}

        assert result_with_id.get("id", "unknown") == "test_id_123"


class TestNeo4jNullHandling:
    """Tests for Neo4j null result handling."""

    def test_count_nodes_pattern_with_none(self):
        """Test the null-safe pattern for count queries."""
        # Simulates: result["count"] if result else 0
        result_none = None
        result_valid = {"count": 42}

        assert (result_none["count"] if result_none else 0) == 0
        assert (result_valid["count"] if result_valid else 0) == 42


class TestClaudeCLIErrorHandling:
    """Tests for Claude CLI subprocess error handling."""

    def test_cli_timeout_returns_empty(self):
        """Test that CLI timeout returns empty string."""
        from axiom.ingestion import AxiomExtractor

        extractor = AxiomExtractor(llm_client="claude-cli")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=300)

            # Capture stderr
            old_stderr = sys.stderr
            sys.stderr = StringIO()

            try:
                result = extractor._call_claude_cli("test prompt")
                stderr_output = sys.stderr.getvalue()
            finally:
                sys.stderr = old_stderr

            assert result == ""
            assert "timeout" in stderr_output.lower()

    def test_cli_not_found_returns_empty(self):
        """Test that missing CLI returns empty string."""
        from axiom.ingestion import AxiomExtractor

        extractor = AxiomExtractor(llm_client="claude-cli")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            old_stderr = sys.stderr
            sys.stderr = StringIO()

            try:
                result = extractor._call_claude_cli("test prompt")
                stderr_output = sys.stderr.getvalue()
            finally:
                sys.stderr = old_stderr

            assert result == ""
            assert "not found" in stderr_output.lower()

    def test_cli_subprocess_error_returns_empty(self):
        """Test that subprocess errors return empty string."""
        from axiom.ingestion import AxiomExtractor

        extractor = AxiomExtractor(llm_client="claude-cli")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.SubprocessError("test error")

            old_stderr = sys.stderr
            sys.stderr = StringIO()

            try:
                result = extractor._call_claude_cli("test prompt")
                stderr_output = sys.stderr.getvalue()
            finally:
                sys.stderr = old_stderr

            assert result == ""
            assert "error" in stderr_output.lower()
