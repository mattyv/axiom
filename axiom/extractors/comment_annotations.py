# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Extract pairing, idiom, and axiom annotations from source code comments.

Library authors can annotate their headers with structured comments to define
function pairings, usage idioms, and semantic constraints:

    // @axiom:pairs_with resource_release
    // @axiom:role opener
    // @axiom:required true
    void resource_acquire(Resource* r);

    // @axiom:pre ptr != nullptr
    // @axiom:post return >= 0
    // @axiom:throws std::bad_alloc on allocation failure
    // @axiom:invariant size() <= capacity()
    // @axiom:effect modifies container
    // @axiom:complexity O(n)
    void process(void* ptr);

    // @axiom:idiom scoped_resource
    // @axiom:template resource_acquire(${r}) { ${body} } resource_release(${r})
"""

import re
from pathlib import Path

from axiom.models import Axiom, AxiomType, SourceLocation
from axiom.models.pairing import Idiom, Pairing

# Mapping from @axiom: tag to (AxiomType, confidence)
AXIOM_TAG_MAPPING: dict[str, tuple[AxiomType, float]] = {
    "pre": (AxiomType.PRECONDITION, 0.90),
    "post": (AxiomType.POSTCONDITION, 0.90),
    "throws": (AxiomType.EXCEPTION, 0.90),
    "invariant": (AxiomType.INVARIANT, 0.90),
    "effect": (AxiomType.EFFECT, 0.85),
    "complexity": (AxiomType.COMPLEXITY, 0.90),
}

# Regex patterns for @axiom: annotations
AXIOM_TAG_PATTERN = re.compile(r"@axiom:(\w+)\s+(.+?)(?=\s*(?:\*/|$))", re.MULTILINE)

# Pattern to find function declarations following annotations
# Matches: optional whitespace, return type(s), function name, opening paren
FUNCTION_DECL_PATTERN = re.compile(
    r"(?:[\w*&:<>,\s]+)\s+(\w+)\s*\(",
    re.MULTILINE,
)


def extract_pairings_from_comments(source_path: Path) -> tuple[list[Pairing], list[Idiom]]:
    """Parse specially formatted comments from source files.

    Supports C/C++ style comments:
    - Single-line: // @axiom:pairs_with function_name
    - Block: /* @axiom:pairs_with function_name */

    Args:
        source_path: Path to source file (.h, .c, .hpp, .cpp)

    Returns:
        Tuple of (pairings, idioms) extracted from comments
    """
    content = source_path.read_text()
    pairings = []
    idioms = []

    # Find all comment blocks that contain @axiom annotations
    # Match both // and /* */ style comments
    comment_blocks = _find_annotated_comment_blocks(content)

    for _block_start, block_end, annotations in comment_blocks:
        # Look for function declaration after this comment block
        func_match = FUNCTION_DECL_PATTERN.search(content, block_end)
        if not func_match:
            continue

        # Make sure the function follows closely after the comment
        gap = content[block_end : func_match.start()]
        if len(gap.strip()) > 0 and not gap.strip().startswith("//"):
            # Too much content between comment and function
            continue

        function_name = func_match.group(1)
        ann_dict = {key.lower(): value.strip() for key, value in annotations}

        # Create pairing if pairs_with is specified
        if "pairs_with" in ann_dict:
            required_str = ann_dict.get("required", "true").lower()
            required = required_str == "true"

            pairings.append(
                Pairing(
                    opener_id=f"axiom_for_{function_name}",
                    closer_id=f"axiom_for_{ann_dict['pairs_with']}",
                    required=required,
                    source="comment_annotation",
                    confidence=1.0,
                    evidence=f"@axiom:pairs_with in {source_path.name}",
                )
            )

        # Create idiom if both idiom name and template are specified
        if "idiom" in ann_dict and "template" in ann_dict:
            idiom_name = ann_dict["idiom"]
            idioms.append(
                Idiom(
                    id=f"idiom_{idiom_name}",
                    name=idiom_name,
                    participants=[f"axiom_for_{function_name}"],
                    template=ann_dict["template"],
                    source="comment_annotation",
                )
            )

    return pairings, idioms


def _find_annotated_comment_blocks(content: str) -> list[tuple[int, int, list[tuple[str, str]]]]:
    """Find comment blocks containing @axiom annotations.

    Args:
        content: Source file content

    Returns:
        List of (start_pos, end_pos, annotations) tuples
    """
    blocks = []

    # Find single-line comment sequences with @axiom
    # Match consecutive // lines
    single_line_pattern = re.compile(
        r"((?://[^\n]*@axiom:[^\n]*\n)+(?://[^\n]*\n)*)", re.MULTILINE
    )

    for match in single_line_pattern.finditer(content):
        block_text = match.group(1)
        annotations = AXIOM_TAG_PATTERN.findall(block_text)
        if annotations:
            blocks.append((match.start(), match.end(), annotations))

    # Find block comments with @axiom
    block_comment_pattern = re.compile(r"/\*.*?@axiom:.*?\*/", re.DOTALL)

    for match in block_comment_pattern.finditer(content):
        block_text = match.group(0)
        annotations = AXIOM_TAG_PATTERN.findall(block_text)
        if annotations:
            blocks.append((match.start(), match.end(), annotations))

    return blocks


def scan_directory_for_annotations(
    directory: Path, extensions: list[str] | None = None
) -> tuple[list[Pairing], list[Idiom]]:
    """Recursively scan directory for axiom annotations in source files.

    Args:
        directory: Root directory to scan
        extensions: File extensions to scan (default: .h, .hpp, .c, .cpp, .hxx, .cxx)

    Returns:
        Aggregated (pairings, idioms) from all source files
    """
    if extensions is None:
        extensions = [".h", ".hpp", ".c", ".cpp", ".hxx", ".cxx"]

    all_pairings: list[Pairing] = []
    all_idioms: list[Idiom] = []

    for ext in extensions:
        for source_file in directory.rglob(f"*{ext}"):
            try:
                pairings, idioms = extract_pairings_from_comments(source_file)
                all_pairings.extend(pairings)
                all_idioms.extend(idioms)
            except Exception:
                # Skip files that can't be read (permissions, encoding issues)
                pass

    return all_pairings, all_idioms


def extract_axioms_from_comments(source_path: Path) -> list[Axiom]:
    """Extract axiom annotations from source file comments.

    Supports annotations:
    - @axiom:pre <condition> -> PRECONDITION
    - @axiom:post <condition> -> POSTCONDITION
    - @axiom:throws <exception> <description> -> EXCEPTION
    - @axiom:invariant <condition> -> INVARIANT
    - @axiom:effect <description> -> EFFECT
    - @axiom:complexity <complexity> -> COMPLEXITY

    Args:
        source_path: Path to source file (.h, .c, .hpp, .cpp)

    Returns:
        List of Axiom objects extracted from comments
    """
    content = source_path.read_text()
    axioms: list[Axiom] = []

    # Find all comment blocks that contain @axiom annotations
    comment_blocks = _find_annotated_comment_blocks(content)

    for _block_start, block_end, annotations in comment_blocks:
        # Look for function declaration after this comment block
        func_match = FUNCTION_DECL_PATTERN.search(content, block_end)
        if not func_match:
            continue

        # Make sure the function follows closely after the comment
        gap = content[block_end : func_match.start()]
        if len(gap.strip()) > 0 and not gap.strip().startswith("//"):
            continue

        function_name = func_match.group(1)

        # Process each annotation that maps to an axiom type
        for tag, value in annotations:
            tag_lower = tag.lower()
            if tag_lower not in AXIOM_TAG_MAPPING:
                continue

            axiom_type, confidence = AXIOM_TAG_MAPPING[tag_lower]
            value = value.strip()

            # Build axiom ID
            axiom_id = f"{function_name}.{tag_lower}.{_hash_short(value)}"

            # Build content based on type
            if axiom_type == AxiomType.PRECONDITION:
                content_text = f"Precondition: {value}"
            elif axiom_type == AxiomType.POSTCONDITION:
                content_text = f"Postcondition: {value}"
            elif axiom_type == AxiomType.EXCEPTION:
                content_text = f"May throw: {value}"
            elif axiom_type == AxiomType.INVARIANT:
                content_text = f"Invariant: {value}"
            elif axiom_type == AxiomType.EFFECT:
                content_text = f"Effect: {value}"
            elif axiom_type == AxiomType.COMPLEXITY:
                content_text = f"Complexity: {value}"
            else:
                content_text = value

            axiom = Axiom(
                id=axiom_id,
                content=content_text,
                formal_spec=value,
                source=SourceLocation(
                    file=str(source_path),
                    module="comment_annotation",
                ),
                axiom_type=axiom_type,
                confidence=confidence,
                function=function_name,
                header=source_path.name,
                layer="user_library",
            )
            axioms.append(axiom)

    return axioms


def _hash_short(text: str) -> str:
    """Generate a short hash for deduplication."""
    import hashlib

    return hashlib.md5(text.encode()).hexdigest()[:8]


def scan_directory_for_axioms(
    directory: Path, extensions: list[str] | None = None
) -> list[Axiom]:
    """Recursively scan directory for axiom annotations in source files.

    Args:
        directory: Root directory to scan
        extensions: File extensions to scan (default: .h, .hpp, .c, .cpp, .hxx, .cxx)

    Returns:
        List of Axiom objects from all source files
    """
    if extensions is None:
        extensions = [".h", ".hpp", ".c", ".cpp", ".hxx", ".cxx"]

    all_axioms: list[Axiom] = []

    for ext in extensions:
        for source_file in directory.rglob(f"*{ext}"):
            try:
                axioms = extract_axioms_from_comments(source_file)
                all_axioms.extend(axioms)
            except Exception:
                # Skip files that can't be read (permissions, encoding issues)
                pass

    return all_axioms
