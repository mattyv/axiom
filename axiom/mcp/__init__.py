# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""MCP server for Axiom validation."""

from .server import create_server, run_server

__all__ = ["create_server", "run_server"]
