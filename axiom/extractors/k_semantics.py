# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""K Semantics extractor for parsing .k files."""

import re
from dataclasses import dataclass
from pathlib import Path

from axiom.models import Axiom, AxiomType, SourceLocation

# Module name to header file mapping
MODULE_TO_HEADER: dict[str, str] = {
    "LIBC-STDLIB": "stdlib.h",
    "LIBC-STDLIB-SYNTAX": "stdlib.h",
    "LIBC-STRING": "string.h",
    "LIBC-STRING-SYNTAX": "string.h",
    "LIBC-STDIO": "stdio.h",
    "LIBC-STDIO-SYNTAX": "stdio.h",
    "LIBC-MATH": "math.h",
    "LIBC-MATH-SYNTAX": "math.h",
    "LIBC-CTYPE": "ctype.h",
    "LIBC-CTYPE-SYNTAX": "ctype.h",
    "LIBC-STDARG": "stdarg.h",
    "LIBC-STDARG-SYNTAX": "stdarg.h",
    "LIBC-TIME": "time.h",
    "LIBC-TIME-SYNTAX": "time.h",
    "LIBC-LOCALE": "locale.h",
    "LIBC-LOCALE-SYNTAX": "locale.h",
    "LIBC-SIGNAL": "signal.h",
    "LIBC-SIGNAL-SYNTAX": "signal.h",
    "LIBC-SETJMP": "setjmp.h",
    "LIBC-SETJMP-SYNTAX": "setjmp.h",
    "LIBC-ASSERT": "assert.h",
    "LIBC-ASSERT-SYNTAX": "assert.h",
    "LIBC-ERRNO": "errno.h",
    "LIBC-ERRNO-SYNTAX": "errno.h",
}


@dataclass
class ErrorMarker:
    """Error marker extracted from a K rule."""

    error_type: str  # UNDEF, CV, IMPL, UNSPEC, etc.
    code: str  # e.g., "CEMX1"
    message: str  # e.g., "Division by 0."


@dataclass
class StandardRef:
    """C standard reference extracted from K comments."""

    source: str  # e.g., "n1570"
    section: str  # e.g., "7.22.3.4"
    paragraphs: str  # e.g., "2--3"
    text: str  # The standard text from the comment


@dataclass
class ParsedRule:
    """A parsed K rule."""

    lhs: str
    rhs: str
    requires: str | None
    module: str
    source_file: str
    error_marker: ErrorMarker | None
    attributes: list[str]
    line_start: int | None = None
    line_end: int | None = None

    # New K-style fields
    function: str | None = None  # Extracted from builtin("name", ...)
    standard_ref: StandardRef | None = None  # C standard citation
    preceding_comment: str | None = None  # Comment block before rule


class KSemanticsExtractor:
    """Extract axioms from K semantic files."""

    # Regex patterns
    MODULE_PATTERN = re.compile(r"module\s+([A-Z0-9_-]+)")
    RULE_PATTERN = re.compile(
        r"rule\s+(.+?)\s*=>\s*(.+?)(?=\s+requires|\s+\[|\s*$)",
        re.DOTALL | re.MULTILINE,
    )
    REQUIRES_PATTERN = re.compile(
        r"requires\s+(.+?)(?=\s+\[|\s*$)",
        re.DOTALL | re.MULTILINE,
    )
    ERROR_MARKER_PATTERN = re.compile(
        r"(UNDEF|CV|IMPL|UNSPEC|SE|IMPLUB)\s*\(\s*\"([^\"]+)\"\s*,\s*\"([^\"]+)\"",
    )
    ATTRIBUTE_PATTERN = re.compile(r"\[([^\]]+)\]")

    # New patterns for K-style extraction
    # Matches: builtin("malloc", ...) or builtin("free", ...)
    BUILTIN_PATTERN = re.compile(r'builtin\s*\(\s*"([^"]+)"')

    # Matches: \fromStandard{\source[n1570]{\para{7.22.3.4}{2--3}}}{...}
    STANDARD_REF_PATTERN = re.compile(
        r"\\fromStandard\s*\{\s*\\source\s*\[([^\]]+)\]\s*\{\s*\\para\s*\{([^}]+)\}\s*\{([^}]+)\}\s*\}\s*\}\s*\{([^}]+)\}",
        re.DOTALL,
    )

    # Simpler pattern for just the paragraph reference: \para{7.22.3.4}{2--3}
    PARA_PATTERN = re.compile(r"\\para\s*\{([^}]+)\}\s*\{([^}]+)\}")

    # Comment block pattern: /*@ ... */
    COMMENT_BLOCK_PATTERN = re.compile(r"/\*@(.*?)\*/", re.DOTALL)

    def __init__(self, semantics_root: Path) -> None:
        """Initialize extractor with path to semantics directory.

        Args:
            semantics_root: Root directory of K semantics files.
        """
        self.semantics_root = Path(semantics_root)

    def parse_file(self, k_file: Path) -> list[ParsedRule]:
        """Parse a single K file and extract rules.

        Args:
            k_file: Path to .k file.

        Returns:
            List of parsed rules.
        """
        content = k_file.read_text(encoding="utf-8")
        module_name = self._extract_module_name(content)
        source_file = str(k_file.name)

        rules: list[ParsedRule] = []

        # Split content into rule blocks
        rule_blocks = self._split_into_rules(content)

        for block, line_start, preceding_comment in rule_blocks:
            parsed = self._parse_rule_block(
                block, module_name, source_file, line_start, preceding_comment
            )
            if parsed:
                rules.append(parsed)

        return rules

    def _extract_module_name(self, content: str) -> str:
        """Extract module name from K file content."""
        match = self.MODULE_PATTERN.search(content)
        if match:
            return match.group(1)
        return "UNKNOWN"

    def _split_into_rules(self, content: str) -> list[tuple]:
        """Split K file content into individual rule blocks.

        Returns:
            List of (rule_text, line_number, preceding_comment) tuples.
        """
        rules = []
        lines = content.split("\n")
        current_rule: list[str] = []
        current_comment: list[str] = []
        rule_start = 0
        in_rule = False
        in_comment = False
        preceding_for_rule: str | None = None

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Track comment blocks (/*@ ... */)
            if "/*@" in line:
                # A documentation comment starts - end current rule if any
                if in_rule and current_rule:
                    rules.append(("\n".join(current_rule), rule_start, preceding_for_rule))
                    current_rule = []
                    in_rule = False
                    preceding_for_rule = None
                in_comment = True
                current_comment = [line]
            elif in_comment:
                current_comment.append(line)
                if "*/" in line:
                    in_comment = False
            # Detect rule start
            elif stripped.startswith("rule ") or stripped.startswith("rule("):
                if current_rule and in_rule:
                    # Save the previous rule
                    rules.append(("\n".join(current_rule), rule_start, preceding_for_rule))
                current_rule = [line]
                rule_start = i
                in_rule = True
                # Attach the preceding comment to this rule
                preceding_for_rule = "\n".join(current_comment) if current_comment else None
                current_comment = []
            elif in_rule:
                # Continue collecting rule
                current_rule.append(line)

                # Check for rule end (attribute or endmodule)
                if stripped.startswith("[") and stripped.endswith("]"):
                    rules.append(("\n".join(current_rule), rule_start, preceding_for_rule))
                    current_rule = []
                    in_rule = False
                    preceding_for_rule = None
                elif stripped.startswith("endmodule"):
                    if current_rule:
                        rules.append(("\n".join(current_rule), rule_start, preceding_for_rule))
                    current_rule = []
                    in_rule = False
                    preceding_for_rule = None

        # Don't forget last rule
        if current_rule and in_rule:
            rules.append(("\n".join(current_rule), rule_start, preceding_for_rule))

        return rules

    def _parse_rule_block(
        self,
        block: str,
        module: str,
        source_file: str,
        line_start: int,
        preceding_comment: str | None = None,
    ) -> ParsedRule | None:
        """Parse a single rule block.

        Args:
            block: Rule text block.
            module: Module name.
            source_file: Source file name.
            line_start: Starting line number.
            preceding_comment: Comment block preceding this rule.

        Returns:
            ParsedRule if valid, None otherwise.
        """
        # Extract error marker if present
        error_match = self.ERROR_MARKER_PATTERN.search(block)
        error_marker = None
        if error_match:
            error_marker = ErrorMarker(
                error_type=error_match.group(1),
                code=error_match.group(2),
                message=error_match.group(3),
            )

        # Extract LHS => RHS
        lhs, rhs = self._extract_lhs_rhs(block)
        if not lhs:
            return None

        # Extract requires clause
        requires = self._extract_requires(block)

        # Extract attributes
        attr_match = self.ATTRIBUTE_PATTERN.findall(block)
        attributes = attr_match if attr_match else []

        # Extract function name from builtin("name", ...)
        function = self._extract_function_name(block)

        # Extract standard reference from preceding comment
        standard_ref = None
        if preceding_comment:
            standard_ref = self._extract_standard_ref(preceding_comment)

        return ParsedRule(
            lhs=lhs.strip(),
            rhs=rhs.strip() if rhs else "",
            requires=requires.strip() if requires else None,
            module=module,
            source_file=source_file,
            error_marker=error_marker,
            attributes=attributes,
            line_start=line_start,
            line_end=line_start + block.count("\n"),
            function=function,
            standard_ref=standard_ref,
            preceding_comment=preceding_comment,
        )

    # Pattern to extract K function name from LHS like "alignedAlloc(Align, Sz)"
    # or "<k> alignedAlloc(Align::Int, Sz::Int)"
    LHS_FUNCTION_PATTERN = re.compile(
        r"(?:<[^>]+>\s*)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\("
    )

    def _extract_function_name(self, block: str) -> str | None:
        """Extract function name from builtin("name", ...) or LHS pattern."""
        # First try builtin("name", ...) pattern
        match = self.BUILTIN_PATTERN.search(block)
        if match:
            return match.group(1)

        # Try to extract from LHS pattern like "alignedAlloc(Align, Sz)"
        # Find the rule keyword and extract what comes after
        rule_match = re.search(r"rule\s+(.+?)\s*=>", block, re.DOTALL)
        if rule_match:
            lhs = rule_match.group(1).strip()
            # Extract function name from LHS
            func_match = self.LHS_FUNCTION_PATTERN.match(lhs)
            if func_match:
                func_name = func_match.group(1)
                # Skip K primitives and cell names
                if func_name not in {"tv", "utype", "type", "lval", "reval", "K"}:
                    return func_name

        return None

    def _extract_standard_ref(self, comment: str) -> StandardRef | None:
        """Extract C standard reference from comment block."""
        # First try to find the paragraph reference
        para_match = self.PARA_PATTERN.search(comment)
        if not para_match:
            return None

        section = para_match.group(1)  # e.g., "7.22.3.4"
        paragraphs = para_match.group(2)  # e.g., "2--3"

        # Try to find the source (e.g., "n1570")
        source_match = re.search(r"\\source\s*\[([^\]]+)\]", comment)
        source = source_match.group(1) if source_match else "unknown"

        # Extract the text between the second-to-last { and the closing }*/
        # The pattern is: ...}}{<text>}*/
        text_match = re.search(r"\}\}\s*\{([^}]+(?:\}[^}]+)*)\}\s*\*/", comment, re.DOTALL)
        if text_match:
            text = text_match.group(1).strip()
            # Clean up LaTeX commands like \cinline{...}
            text = re.sub(r"\\cinline\{([^}]+)\}", r"\1", text)
            text = re.sub(r"\s+", " ", text)  # Normalize whitespace
        else:
            text = ""

        return StandardRef(
            source=source,
            section=section,
            paragraphs=paragraphs,
            text=text,
        )

    def _extract_lhs_rhs(self, block: str) -> tuple:
        """Extract LHS and RHS from rule block."""
        # Find 'rule' keyword and '=>'
        match = re.search(r"rule\s+(.+?)\s*=>\s*(.+?)(?=\s+requires|\s+\[|\s*$)", block, re.DOTALL)
        if match:
            return match.group(1).strip(), match.group(2).strip()

        # Try alternative: rule may have (.K => ...) pattern
        match = re.search(r"rule\s+\(\.K\s*=>\s*([^)]+)\)", block, re.DOTALL)
        if match:
            return "(.K)", match.group(1).strip()

        return "", ""

    def _extract_requires(self, block: str) -> str | None:
        """Extract requires clause from rule block."""
        match = re.search(r"requires\s+(.+?)(?=\s+\[|\s*$)", block, re.DOTALL)
        if match:
            req = match.group(1).strip()
            # Clean up multiline requires
            req = " ".join(line.strip() for line in req.split("\n"))
            return req
        return None

    def extract_axioms_from_file(self, k_file: Path) -> list[Axiom]:
        """Extract axioms from a K file.

        Axioms are rules with requires clauses that don't have error markers.

        Args:
            k_file: Path to .k file.

        Returns:
            List of Axiom objects.
        """
        from axiom.extractors.content_generator import ContentGenerator

        rules = self.parse_file(k_file)
        generator = ContentGenerator()
        axioms: list[Axiom] = []

        for rule in rules:
            # Extract axioms from rules with requires clauses (no error markers)
            if rule.requires and not rule.error_marker:
                axiom_id = generator.generate_axiom_id(
                    module=rule.module,
                    operation=self._infer_operation(rule.lhs),
                    formal_spec=rule.requires,
                )

                # Use standard text as content if available, otherwise generate
                if rule.standard_ref and rule.standard_ref.text:
                    content = rule.standard_ref.text
                else:
                    content = generator.generate(
                        rule.requires,
                        operation=self._infer_operation(rule.lhs),
                    )

                # Build C standard refs list
                c_standard_refs: list[str] = []
                if rule.standard_ref:
                    ref = f"{rule.standard_ref.section}/{rule.standard_ref.paragraphs}"
                    c_standard_refs.append(ref)

                # Determine header from module
                header = MODULE_TO_HEADER.get(rule.module)

                # Infer axiom type (most K rules with requires are preconditions)
                axiom_type = AxiomType.PRECONDITION

                axiom = Axiom(
                    id=axiom_id,
                    content=content,
                    formal_spec=rule.requires,
                    source=SourceLocation(
                        file=str(k_file.relative_to(self.semantics_root))
                        if k_file.is_relative_to(self.semantics_root)
                        else str(k_file),
                        module=rule.module,
                        line_start=rule.line_start,
                        line_end=rule.line_end,
                    ),
                    tags=self._infer_tags(rule),
                    c_standard_refs=c_standard_refs,
                    # New K-style fields
                    function=rule.function,
                    header=header,
                    axiom_type=axiom_type,
                )
                axioms.append(axiom)

            # Also extract axioms from rules with standard refs (even without requires)
            # These are function definitions from the C standard
            elif rule.standard_ref and rule.function and not rule.error_marker:
                axiom_id = generator.generate_axiom_id(
                    module=rule.module,
                    operation=rule.function,
                    formal_spec=rule.standard_ref.text[:100] if rule.standard_ref.text else "",
                )

                header = MODULE_TO_HEADER.get(rule.module)
                c_standard_refs = [f"{rule.standard_ref.section}/{rule.standard_ref.paragraphs}"]

                axiom = Axiom(
                    id=axiom_id,
                    content=rule.standard_ref.text,
                    formal_spec=rule.requires or "",
                    source=SourceLocation(
                        file=str(k_file.relative_to(self.semantics_root))
                        if k_file.is_relative_to(self.semantics_root)
                        else str(k_file),
                        module=rule.module,
                        line_start=rule.line_start,
                        line_end=rule.line_end,
                    ),
                    tags=self._infer_tags(rule),
                    c_standard_refs=c_standard_refs,
                    function=rule.function,
                    header=header,
                    axiom_type=AxiomType.POSTCONDITION,  # These describe what functions do
                )
                axioms.append(axiom)

            # Also extract axioms from error rules (they define on_violation behavior)
            elif rule.error_marker and rule.function:
                # This is an error case for a function
                axiom_id = generator.generate_axiom_id(
                    module=rule.module,
                    operation=rule.function,
                    formal_spec=rule.error_marker.message,
                )

                header = MODULE_TO_HEADER.get(rule.module)

                axiom = Axiom(
                    id=axiom_id,
                    content=rule.error_marker.message,
                    formal_spec=rule.requires or "",
                    source=SourceLocation(
                        file=str(k_file.relative_to(self.semantics_root))
                        if k_file.is_relative_to(self.semantics_root)
                        else str(k_file),
                        module=rule.module,
                        line_start=rule.line_start,
                        line_end=rule.line_end,
                    ),
                    tags=self._infer_tags(rule),
                    function=rule.function,
                    header=header,
                    axiom_type=AxiomType.CONSTRAINT,
                    on_violation=f"{rule.error_marker.error_type}: {rule.error_marker.code}",
                )
                axioms.append(axiom)

            # Extract axioms from function rules without requires/standard_ref/error
            # Only for C library functions (LIBC-* modules) or known stdlib functions
            elif rule.function and not rule.error_marker and self._is_library_function(rule):
                axiom_id = generator.generate_axiom_id(
                    module=rule.module,
                    operation=rule.function,
                    formal_spec=rule.rhs[:100] if rule.rhs else "",
                )

                header = MODULE_TO_HEADER.get(rule.module)

                # Generate content from the rule transformation
                content = f"{rule.function} transforms to {rule.rhs[:80]}"
                if rule.requires:
                    content += f" when {rule.requires[:50]}"

                axiom = Axiom(
                    id=axiom_id,
                    content=content,
                    formal_spec=rule.requires or "",
                    source=SourceLocation(
                        file=str(k_file.relative_to(self.semantics_root))
                        if k_file.is_relative_to(self.semantics_root)
                        else str(k_file),
                        module=rule.module,
                        line_start=rule.line_start,
                        line_end=rule.line_end,
                    ),
                    tags=self._infer_tags(rule),
                    function=rule.function,
                    header=header,
                    axiom_type=AxiomType.EFFECT,  # These describe what functions do
                )
                axioms.append(axiom)

        return axioms

    def extract_all(self) -> list[Axiom]:
        """Extract axioms from all K files in the semantics directory.

        Returns:
            List of all extracted Axiom objects.
        """
        axioms: list[Axiom] = []

        for k_file in self.semantics_root.rglob("*.k"):
            try:
                file_axioms = self.extract_axioms_from_file(k_file)
                axioms.extend(file_axioms)
            except Exception as e:
                # Log but continue on parse errors
                print(f"Warning: Failed to parse {k_file}: {e}")

        return axioms

    def _infer_operation(self, lhs: str) -> str:
        """Infer operation type from LHS of rule."""
        lhs_lower = lhs.lower()

        if "/" in lhs and "div" not in lhs_lower:
            return "division"
        elif "%" in lhs:
            return "modulus"
        elif "*" in lhs and "mult" not in lhs_lower:
            return "multiplication"
        elif "+" in lhs:
            return "addition"
        elif "-" in lhs:
            return "subtraction"
        elif "<<" in lhs or ">>" in lhs:
            return "shift"
        elif "&" in lhs or "|" in lhs or "^" in lhs:
            return "bitwise"
        elif "==" in lhs or "!=" in lhs or "<" in lhs or ">" in lhs:
            return "comparison"
        elif ":=" in lhs or "=" in lhs:
            return "assignment"
        else:
            return "operation"

    def _is_library_function(self, rule: ParsedRule) -> bool:
        """Check if rule represents a C library function (not a K helper).

        Args:
            rule: The parsed rule to check.

        Returns:
            True if this is likely a C library function.
        """
        # Check if module is a LIBC module
        if rule.module.startswith("LIBC-"):
            return True

        # Check if function has a known header mapping
        if rule.module in MODULE_TO_HEADER:
            return True

        # Check if function is a builtin (extracted from builtin("name", ...))
        # These are definitely C functions
        if rule.function and 'builtin("' in (rule.lhs or ""):
            return True

        return False

    def _infer_tags(self, rule: ParsedRule) -> list[str]:
        """Infer tags for a rule based on content."""
        tags = []

        if rule.requires:
            if "isPromoted" in rule.requires:
                tags.append("type_promotion")
            if "isZero" in rule.requires:
                tags.append("zero_check")
            if "==Type" in rule.requires or "=/=Type" in rule.requires:
                tags.append("type_compatibility")
            if "isPointer" in rule.requires:
                tags.append("pointer")
            if "isInteger" in rule.requires:
                tags.append("integer")
            if "isFloat" in rule.requires:
                tags.append("float")

        operation = self._infer_operation(rule.lhs)
        if operation != "operation":
            tags.append(operation)

        return tags
