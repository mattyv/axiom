# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2026 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Unix socket server for clangd plugin communication.

Exposes the AxiomQueryService via JSON over Unix socket.
The clangd plugin connects to this server to query axioms.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from axiom.query.service import AxiomQueryService

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default socket path
DEFAULT_SOCKET_PATH = "/tmp/axiom-query.sock"


class AxiomQueryServer:
    """Unix socket server for axiom queries.

    Protocol:
    - Request: JSON object with "method" and optional "params"
    - Response: JSON object with "result" or "error"

    Supported methods:
    - query: Query axioms for symbols
      params: {"symbols": ["foo::bar(int)", ...]}
      result: {"axioms": [...]}

    - get_axiom: Get a specific axiom by ID
      params: {"axiom_id": "..."}
      result: {...} or null

    - get_axioms_for_file: Get axioms from a file
      params: {"file_path": "..."}
      result: {"axioms": [...]}
    """

    def __init__(
        self,
        service: AxiomQueryService,
        socket_path: str | Path = DEFAULT_SOCKET_PATH,
    ) -> None:
        """Initialize server.

        Args:
            service: Query service to use.
            socket_path: Path for Unix socket.
        """
        self.service = service
        self.socket_path = Path(socket_path)
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start the server."""
        # Remove existing socket file
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path),
        )

        # Set socket permissions (readable/writable by owner and group)
        os.chmod(self.socket_path, 0o660)

        logger.info("Axiom query server listening on %s", self.socket_path)

    async def stop(self) -> None:
        """Stop the server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Clean up socket file
        if self.socket_path.exists():
            self.socket_path.unlink()

        logger.info("Axiom query server stopped")

    async def serve_forever(self) -> None:
        """Run the server until interrupted."""
        await self.start()

        if self._server is not None:
            await self._server.serve_forever()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        peer = writer.get_extra_info("peername") or "unknown"
        logger.debug("Client connected: %s", peer)

        try:
            while True:
                # Read line-delimited JSON
                line = await reader.readline()
                if not line:
                    break

                try:
                    request = json.loads(line.decode("utf-8"))
                    response = self._handle_request(request)
                except json.JSONDecodeError as e:
                    response = {"error": f"Invalid JSON: {e}"}

                # Send response
                response_bytes = json.dumps(response).encode("utf-8") + b"\n"
                writer.write(response_bytes)
                await writer.drain()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Client handler error: %s", e)
        finally:
            writer.close()
            await writer.wait_closed()
            logger.debug("Client disconnected: %s", peer)

    def _handle_request(self, request: dict) -> dict:
        """Handle a single request."""
        method = request.get("method")
        params = request.get("params", {})

        if method == "query":
            return self._handle_query(params)
        elif method == "get_axiom":
            return self._handle_get_axiom(params)
        elif method == "get_axioms_for_file":
            return self._handle_get_axioms_for_file(params)
        else:
            return {"error": f"Unknown method: {method}"}

    def _handle_query(self, params: dict) -> dict:
        """Handle query method."""
        symbols = params.get("symbols", [])
        if not isinstance(symbols, list):
            return {"error": "symbols must be a list"}

        results = self.service.query(symbols)

        # Convert to JSON-serializable format
        return {
            "result": [
                {
                    "symbol": r.symbol,
                    "layer": r.layer,
                    "axioms": [asdict(a) for a in r.axioms],
                }
                for r in results
            ]
        }

    def _handle_get_axiom(self, params: dict) -> dict:
        """Handle get_axiom method."""
        axiom_id = params.get("axiom_id")
        if not axiom_id:
            return {"error": "axiom_id is required"}

        result = self.service.get_axiom(axiom_id)
        if result is None:
            return {"result": None}

        return {"result": asdict(result)}

    def _handle_get_axioms_for_file(self, params: dict) -> dict:
        """Handle get_axioms_for_file method."""
        file_path = params.get("file_path")
        if not file_path:
            return {"error": "file_path is required"}

        results = self.service.get_axioms_for_file(file_path)
        return {"result": {"axioms": [asdict(a) for a in results]}}


async def run_server(
    socket_path: str = DEFAULT_SOCKET_PATH,
    neo4j_uri: str = "bolt://localhost:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "axiompass",
) -> None:
    """Run the query server with default configuration.

    Args:
        socket_path: Path for Unix socket.
        neo4j_uri: Neo4j connection URI.
        neo4j_user: Neo4j username.
        neo4j_password: Neo4j password.
    """
    from axiom.watcher import InMemoryAxiomStore

    # Try to connect to Neo4j (optional)
    neo4j = None
    try:
        from axiom.graph import Neo4jLoader
        neo4j = Neo4jLoader(uri=neo4j_uri, user=neo4j_user, password=neo4j_password)
        logger.info("Connected to Neo4j at %s", neo4j_uri)
    except Exception as e:
        logger.warning("Neo4j not available: %s", e)

    # Create live store
    live_store = InMemoryAxiomStore()

    # Create service
    service = AxiomQueryService(neo4j=neo4j, live_store=live_store)

    # Create server
    server = AxiomQueryServer(service=service, socket_path=socket_path)

    # Handle shutdown signals
    loop = asyncio.get_running_loop()

    def shutdown() -> None:
        loop.create_task(server.stop())
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    try:
        await server.serve_forever()
    finally:
        if neo4j:
            neo4j.close()


def main() -> None:
    """Entry point for axiom-query-server."""
    import argparse

    parser = argparse.ArgumentParser(description="Axiom query server")
    parser.add_argument(
        "--socket",
        default=DEFAULT_SOCKET_PATH,
        help=f"Unix socket path (default: {DEFAULT_SOCKET_PATH})",
    )
    parser.add_argument(
        "--neo4j-uri",
        default="bolt://localhost:7687",
        help="Neo4j connection URI",
    )
    parser.add_argument(
        "--neo4j-user",
        default="neo4j",
        help="Neo4j username",
    )
    parser.add_argument(
        "--neo4j-password",
        default="axiompass",
        help="Neo4j password",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run server
    try:
        asyncio.run(run_server(
            socket_path=args.socket,
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=args.neo4j_password,
        ))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
