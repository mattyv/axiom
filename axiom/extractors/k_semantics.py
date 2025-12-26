"""K Semantics extractor for parsing .k files."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from axiom.models import Axiom, SourceLocation, ViolationRef


@dataclass
class ErrorMarker:
    """Error marker extracted from a K rule."""

    error_type: str  # UNDEF, CV, IMPL, UNSPEC, etc.
    code: str  # e.g., "CEMX1"
    message: str  # e.g., "Division by 0."


@dataclass
class ParsedRule:
    """A parsed K rule."""

    lhs: str
    rhs: str
    requires: Optional[str]
    module: str
    source_file: str
    error_marker: Optional[ErrorMarker]
    attributes: List[str]
    line_start: Optional[int] = None
    line_end: Optional[int] = None


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

    def __init__(self, semantics_root: Path) -> None:
        """Initialize extractor with path to semantics directory.

        Args:
            semantics_root: Root directory of K semantics files.
        """
        self.semantics_root = Path(semantics_root)

    def parse_file(self, k_file: Path) -> List[ParsedRule]:
        """Parse a single K file and extract rules.

        Args:
            k_file: Path to .k file.

        Returns:
            List of parsed rules.
        """
        content = k_file.read_text(encoding="utf-8")
        module_name = self._extract_module_name(content)
        source_file = str(k_file.name)

        rules: List[ParsedRule] = []

        # Split content into rule blocks
        rule_blocks = self._split_into_rules(content)

        for block, line_start in rule_blocks:
            parsed = self._parse_rule_block(
                block, module_name, source_file, line_start
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

    def _split_into_rules(self, content: str) -> List[tuple]:
        """Split K file content into individual rule blocks.

        Returns:
            List of (rule_text, line_number) tuples.
        """
        rules = []
        lines = content.split("\n")
        current_rule = []
        rule_start = 0
        in_rule = False

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Detect rule start
            if stripped.startswith("rule ") or (stripped.startswith("rule(") and not in_rule):
                if current_rule and in_rule:
                    rules.append(("\n".join(current_rule), rule_start))
                current_rule = [line]
                rule_start = i
                in_rule = True
            elif in_rule:
                # Continue collecting rule
                current_rule.append(line)

                # Check for rule end (attribute or next rule or endmodule)
                if stripped.startswith("[") and stripped.endswith("]"):
                    rules.append(("\n".join(current_rule), rule_start))
                    current_rule = []
                    in_rule = False
                elif stripped.startswith("endmodule"):
                    if current_rule:
                        rules.append(("\n".join(current_rule), rule_start))
                    current_rule = []
                    in_rule = False

        # Don't forget last rule
        if current_rule and in_rule:
            rules.append(("\n".join(current_rule), rule_start))

        return rules

    def _parse_rule_block(
        self, block: str, module: str, source_file: str, line_start: int
    ) -> Optional[ParsedRule]:
        """Parse a single rule block.

        Args:
            block: Rule text block.
            module: Module name.
            source_file: Source file name.
            line_start: Starting line number.

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

    def _extract_requires(self, block: str) -> Optional[str]:
        """Extract requires clause from rule block."""
        match = re.search(r"requires\s+(.+?)(?=\s+\[|\s*$)", block, re.DOTALL)
        if match:
            req = match.group(1).strip()
            # Clean up multiline requires
            req = " ".join(line.strip() for line in req.split("\n"))
            return req
        return None

    def extract_axioms_from_file(self, k_file: Path) -> List[Axiom]:
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
        axioms: List[Axiom] = []

        for rule in rules:
            # Only extract axioms from rules with requires clauses and no error markers
            if rule.requires and not rule.error_marker:
                axiom_id = generator.generate_axiom_id(
                    module=rule.module,
                    operation=self._infer_operation(rule.lhs),
                    formal_spec=rule.requires,
                )

                content = generator.generate(
                    rule.requires,
                    operation=self._infer_operation(rule.lhs),
                )

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
                )
                axioms.append(axiom)

        return axioms

    def extract_all(self) -> List[Axiom]:
        """Extract axioms from all K files in the semantics directory.

        Returns:
            List of all extracted Axiom objects.
        """
        axioms: List[Axiom] = []

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

    def _infer_tags(self, rule: ParsedRule) -> List[str]:
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
