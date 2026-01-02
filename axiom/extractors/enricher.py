# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""LLM-based axiom enrichment.

This module enriches axioms extracted from code with:
- on_violation descriptions
- Inferred EFFECT and POSTCONDITION axioms
- Enhanced semantic content

Uses batching for efficient LLM calls.
"""

from __future__ import annotations

import itertools
import logging
import subprocess
import sys
import threading
import time
import tomllib
from collections import defaultdict
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from axiom.models import Axiom

logger = logging.getLogger(__name__)


class EnrichmentProgress:
    """Progress tracker with spinner for enrichment."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, total_batches: int, total_axioms: int, width: int = 20):
        self.total_batches = total_batches
        self.total_axioms = total_axioms
        self.current_batch = 0
        self.current_axiom_count = 0
        self.enriched_count = 0
        self.current_functions: list[str] = []
        self.width = width
        self.start_time = time.time()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._status = "Starting..."
        self._last_len = 0

    def _render(self, frame: str) -> str:
        with self._lock:
            percent = self.current_batch / self.total_batches if self.total_batches > 0 else 0
            filled = int(self.width * percent)
            bar = "█" * filled + "░" * (self.width - filled)

            elapsed = time.time() - self.start_time
            if self.current_batch > 0:
                eta = (elapsed / self.current_batch) * (self.total_batches - self.current_batch)
                eta_min = int(eta // 60)
                eta_sec = int(eta % 60)
                eta_str = f"{eta_min}m{eta_sec:02d}s"
            else:
                eta_str = "..."

            # Build compact single-line status
            pct = int(percent * 100)
            parts = [
                f"{frame}",
                f"[{bar}]",
                f"{pct:3d}%",
                f"Batch {self.current_batch}/{self.total_batches}",
                f"ETA {eta_str}",
                f"| {self.enriched_count}/{self.current_axiom_count} enriched",
            ]

            # Add truncated function name if available
            if self.current_functions:
                func = self.current_functions[0]
                if len(func) > 20:
                    func = func[:17] + "..."
                parts.append(f"| {func}")

            return " ".join(parts)

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop_event.is_set():
                break
            line = self._render(frame)
            # Pad to overwrite previous content
            padding = max(0, self._last_len - len(line))
            sys.stdout.write(f"\r{line}{' ' * padding}")
            sys.stdout.flush()
            self._last_len = len(line)
            time.sleep(0.1)

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self, success: bool = True):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        # Clear the line
        sys.stdout.write("\r" + " " * self._last_len + "\r")
        elapsed = time.time() - self.start_time
        if success:
            print(f"✓ Enrichment complete: {self.enriched_count}/{self.total_axioms} axioms enriched ({elapsed:.1f}s)")
        else:
            print(f"✗ Enrichment failed after {elapsed:.1f}s")
        sys.stdout.flush()

    def update_batch(self, batch_num: int, functions: list[str], axiom_count: int):
        with self._lock:
            self.current_batch = batch_num
            self.current_functions = functions
            self.current_axiom_count += axiom_count
            self._status = f"Processing batch {batch_num}..."

    def update_enriched(self, count: int):
        with self._lock:
            self.enriched_count += count
            self._status = f"Enriched {count} axioms in batch"

    def set_status(self, status: str):
        with self._lock:
            self._status = status

# Enrichment configuration
BATCH_SIZE = 15  # Functions per LLM call
DEFAULT_MODEL = "sonnet"


def group_by_function(axioms: list[Axiom]) -> dict[str, list[Axiom]]:
    """Group axioms by their function for context coherence."""
    groups: dict[str, list[Axiom]] = defaultdict(list)
    for axiom in axioms:
        key = axiom.function or "__global__"
        groups[key].append(axiom)
    return dict(groups)


def chunk_functions(
    groups: dict[str, list[Axiom]], max_functions: int = BATCH_SIZE
) -> Iterator[dict[str, list[Axiom]]]:
    """Yield successive chunks of function groups."""
    items = list(groups.items())
    for i in range(0, len(items), max_functions):
        yield dict(items[i : i + max_functions])


def build_enrichment_prompt(axioms: list[Axiom]) -> str:
    """Build prompt for axiom enrichment.

    Asks the LLM to:
    1. Add on_violation descriptions
    2. Infer missing postconditions from return types
    3. Enhance semantic content
    """
    axiom_lines = []
    for a in axioms:
        axiom_lines.append(
            f"""[[axioms]]
id = '''{a.id}'''
content = '''{a.content}'''
formal_spec = '''{a.formal_spec or ''}'''
axiom_type = '''{a.axiom_type.name if a.axiom_type else 'UNKNOWN'}'''
function = '''{a.function or ''}'''
"""
        )

    return f"""You are enriching axioms extracted from C++ code.

For each axiom, add an on_violation field describing what error or undefined behavior
occurs when the axiom is violated. Be specific and concise.

For PRECONDITION axioms, describe the runtime error or UB.
For EFFECT axioms, describe what state change occurs.
For CONSTRAINT axioms, describe what compilation or runtime issue arises.

If you can infer a POSTCONDITION from the function signature or axioms,
add it as a new axiom with axiom_type = '''POSTCONDITION'''.

CRITICAL: Your response must contain ONLY the TOML output below. Do NOT include:
- Any explanatory text before or after the TOML
- Markdown code fences (no ```toml)
- Comments or notes about what you changed
- Summaries or "Done!" messages

Start your response with [[axioms]] and use triple-quoted strings for all values:

{chr(10).join(axiom_lines)}

Add 'on_violation = '''...''''' to each axiom. Keep all original fields.
If inferring new axioms, use a new id like "function.inferred.postcond"."""


def call_llm(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Call Claude CLI for enrichment."""
    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--model",
                model,
                "--dangerously-skip-permissions",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.warning("LLM call timed out")
        return ""
    except FileNotFoundError:
        logger.warning("Claude CLI not found")
        return ""


def parse_enrichment_response(response: str, originals: list[Axiom]) -> list[Axiom]:
    """Parse TOML response and update axioms with enrichment.

    Handles:
    - Adding on_violation to existing axioms
    - Updating content/formal_spec if improved
    - Adding new inferred axioms
    """
    if not response or not response.strip():
        return list(originals)

    try:
        # Extract TOML block if wrapped in markdown
        if "```toml" in response:
            start = response.index("```toml") + 7
            end = response.index("```", start)
            response = response[start:end]
        elif "```" in response:
            # Generic code block
            start = response.index("```") + 3
            # Skip language identifier if present
            newline_idx = response.find("\n", start)
            if newline_idx != -1:
                start = newline_idx + 1
            end = response.index("```", start)
            response = response[start:end]
        else:
            # No markdown fences - try to find the TOML start
            # Look for the first [[axioms]] marker
            axiom_start = response.find("[[axioms]]")
            if axiom_start > 0:
                # Strip any leading text before the TOML
                response = response[axiom_start:]

        data = tomllib.loads(response)
        enriched_map = {a["id"]: a for a in data.get("axioms", [])}

        result = []
        for orig in originals:
            if orig.id in enriched_map:
                enriched = enriched_map[orig.id]
                # Update on_violation
                if "on_violation" in enriched:
                    orig.on_violation = enriched["on_violation"]
                # Optionally update content if improved
                if "content" in enriched and enriched["content"] != orig.content:
                    # Keep original unless explicitly improved
                    pass
            result.append(orig)

        # Add any new inferred axioms
        original_ids = {a.id for a in originals}
        for axiom_data in data.get("axioms", []):
            if axiom_data.get("id") not in original_ids:
                # New inferred axiom
                from axiom.models import AxiomType, SourceLocation

                new_axiom = Axiom(
                    id=axiom_data.get("id", ""),
                    content=axiom_data.get("content", ""),
                    formal_spec=axiom_data.get("formal_spec", ""),
                    axiom_type=AxiomType[axiom_data.get("axiom_type", "POSTCONDITION")],
                    confidence=0.85,  # Lower confidence for inferred
                    function=axiom_data.get("function", ""),
                    on_violation=axiom_data.get("on_violation", ""),
                    source=SourceLocation(
                        file="enricher.py",
                        module="llm_inferred",
                        line_start=None,
                        line_end=None,
                    ),
                )
                result.append(new_axiom)

        return result
    except Exception as e:
        logger.warning(f"Failed to parse LLM response: {e}")
        logger.debug(f"Problematic response (first 500 chars):\n{response[:500]}")
        return list(originals)


def enrich_axioms(
    axioms: list[Axiom],
    use_llm: bool = True,
    model: str = DEFAULT_MODEL,
    show_progress: bool = True,
) -> list[Axiom]:
    """Enrich axioms with LLM-generated on_violation and inferred axioms.

    Args:
        axioms: List of axioms to enrich.
        use_llm: Whether to use LLM for enrichment.
        model: Model to use for LLM calls.
        show_progress: Whether to show interactive progress (default: True).

    Returns:
        Enriched axioms with on_violation and any new inferred axioms.
    """
    if not use_llm:
        return list(axioms)

    if not axioms:
        return []

    # Group by function for context coherence
    groups = group_by_function(axioms)
    chunks = list(chunk_functions(groups, BATCH_SIZE))
    total_chunks = len(chunks)

    logger.info(f"Enriching {len(axioms)} axioms across {len(groups)} functions in {total_chunks} batches...")

    # Initialize progress tracker
    progress: EnrichmentProgress | None = None
    if show_progress and sys.stdout.isatty():
        progress = EnrichmentProgress(total_chunks, len(axioms))
        progress.start()

    enriched_all = []
    enriched_count = 0
    start_time = time.time()

    try:
        for i, chunk in enumerate(chunks, 1):
            # Flatten chunk to list
            chunk_axioms = []
            func_names = []
            for func_name, func_axioms in chunk.items():
                chunk_axioms.extend(func_axioms)
                if func_name != "__global__":
                    func_names.append(func_name)

            if progress:
                progress.update_batch(i, func_names, len(chunk_axioms))
                progress.set_status(f"Calling LLM ({model})...")

            prompt = build_enrichment_prompt(chunk_axioms)
            response = call_llm(prompt, model)

            if response:
                if progress:
                    progress.set_status("Parsing response...")
                chunk_enriched = parse_enrichment_response(response, chunk_axioms)
                enriched_all.extend(chunk_enriched)
                batch_enriched = sum(1 for a in chunk_enriched if a.on_violation)
                enriched_count += batch_enriched
                if progress:
                    progress.update_enriched(batch_enriched)
            else:
                # Keep originals if LLM fails
                enriched_all.extend(chunk_axioms)
                if progress:
                    progress.set_status("LLM call failed, keeping originals")

            # Log progress for non-interactive mode
            if not progress:
                elapsed = time.time() - start_time
                avg_per_batch = elapsed / i
                remaining = (total_chunks - i) * avg_per_batch
                eta_min = int(remaining // 60)
                eta_sec = int(remaining % 60)
                logger.info(
                    f"Batch {i}/{total_chunks} ({len(chunk_axioms)} axioms) - "
                    f"{enriched_count} enriched - ETA: {eta_min}m {eta_sec}s"
                )

        if progress:
            progress.stop(success=True)

    except KeyboardInterrupt:
        if progress:
            progress.stop(success=False)
        raise
    except Exception:
        if progress:
            progress.stop(success=False)
        raise

    total_time = time.time() - start_time
    logger.info(
        f"Enrichment complete: {len(enriched_all)} axioms, "
        f"{enriched_count} with on_violation ({total_time:.1f}s)"
    )
    return enriched_all
