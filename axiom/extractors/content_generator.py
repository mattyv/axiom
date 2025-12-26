"""Generate human-readable content from K formal specifications."""

import hashlib
import re
from typing import List, Optional


class ContentGenerator:
    """Generate human-readable axiom content from K formal specs."""

    # Templates for common K predicates
    PREDICATE_TEMPLATES = {
        "notBool isZero": "operand must be non-zero",
        "isZero": "operand is zero",
        "isPromoted": "operand must be a promoted type",
        "==Type": "operand types must match",
        "=/=Type": "operand types must differ",
        "notBool isConstType": "operand must not be const-qualified",
        "isConstType": "operand must be const-qualified",
        "isCompleteType": "operand must be a complete type",
        "isPointerType": "operand must be a pointer type",
        "isIntegerType": "operand must be an integer type",
        "hasIntegerType": "operand must have integer type",
        "isFloatType": "operand must be a floating-point type",
        "notBool isVoidType": "operand must not be void",
        "isVoidType": "operand must be void type",
        "isArithmeticType": "operand must be an arithmetic type",
        "isScalarType": "operand must be a scalar type",
        "isUnknown": "operand value is unknown",
        "notBool isUnknown": "operand value must be known",
        "min(T) <=Int": "result must be within minimum bound",
        "max(T) >=Int": "result must be within maximum bound",
    }

    # Operation name mappings
    OPERATION_NAMES = {
        "division": "Integer division",
        "modulus": "Modulus operation",
        "multiplication": "Integer multiplication",
        "addition": "Addition",
        "subtraction": "Subtraction",
        "shift": "Bit shift operation",
        "bitwise": "Bitwise operation",
        "comparison": "Comparison",
        "assignment": "Assignment",
        "operation": "Operation",
    }

    def generate(
        self, formal_spec: str, operation: Optional[str] = None
    ) -> str:
        """Generate human-readable content from K formal spec.

        Args:
            formal_spec: K requires clause.
            operation: Optional operation name for context.

        Returns:
            Human-readable description.
        """
        if not formal_spec:
            return "No preconditions specified."

        conditions = self.parse_conditions(formal_spec)
        descriptions = [self._describe_condition(c) for c in conditions]

        # Filter out empty descriptions
        descriptions = [d for d in descriptions if d]

        if not descriptions:
            # Fallback: just clean up the formal spec
            return f"Requires: {self._clean_formal_spec(formal_spec)}"

        # Build the description
        op_name = self.OPERATION_NAMES.get(operation, "Operation") if operation else "Operation"

        if len(descriptions) == 1:
            return f"{op_name} requires: {descriptions[0]}."
        else:
            return f"{op_name} requires: {', '.join(descriptions[:-1])}, and {descriptions[-1]}."

    def parse_conditions(self, formal_spec: str) -> List[str]:
        """Parse formal spec into individual conditions.

        Args:
            formal_spec: K requires clause.

        Returns:
            List of individual conditions.
        """
        if not formal_spec:
            return []

        # Normalize whitespace
        spec = " ".join(formal_spec.split())

        # Split on 'andBool' first
        parts = re.split(r"\s+andBool\s+", spec)

        conditions = []
        for part in parts:
            # Handle 'orBool' within parts
            if " orBool " in part:
                # Keep orBool conditions together but note them
                conditions.append(part.strip())
            else:
                conditions.append(part.strip())

        return [c for c in conditions if c]

    def _describe_condition(self, condition: str) -> str:
        """Generate description for a single condition.

        Args:
            condition: Single K condition.

        Returns:
            Human-readable description.
        """
        condition = condition.strip()

        # Check against known templates (order matters - check specific first)
        for pattern, description in sorted(
            self.PREDICATE_TEMPLATES.items(),
            key=lambda x: -len(x[0]),  # Longer patterns first
        ):
            if pattern in condition:
                return description

        # Handle orBool conditions
        if " orBool " in condition:
            parts = condition.split(" orBool ")
            described = [self._describe_condition(p.strip()) for p in parts]
            described = [d for d in described if d]
            if described:
                return f"either {' or '.join(described)}"

        # Handle negation
        if condition.startswith("notBool "):
            inner = condition[8:].strip()
            inner_desc = self._describe_condition(inner)
            if inner_desc:
                return f"NOT ({inner_desc})"

        # Fallback: clean up and return
        cleaned = self._clean_formal_spec(condition)
        if cleaned and len(cleaned) < 100:
            return cleaned

        return ""

    def _clean_formal_spec(self, spec: str) -> str:
        """Clean up formal spec for display.

        Args:
            spec: K formal specification.

        Returns:
            Cleaned string.
        """
        # Remove parentheses around simple expressions
        spec = spec.strip()
        if spec.startswith("(") and spec.endswith(")"):
            spec = spec[1:-1].strip()

        # Replace K-specific syntax
        spec = spec.replace("::UType", "")
        spec = spec.replace("::CValue", "")
        spec = spec.replace("::Type", "")
        spec = spec.replace(":Int", "")
        spec = spec.replace(":Float", "")

        return spec.strip()

    def generate_axiom_id(
        self,
        module: str,
        operation: str,
        formal_spec: str,
    ) -> str:
        """Generate a unique axiom ID.

        Args:
            module: K module name.
            operation: Operation type.
            formal_spec: K requires clause.

        Returns:
            Unique axiom ID.
        """
        # Create a deterministic ID based on content
        content = f"{module}:{operation}:{formal_spec}"
        content_hash = hashlib.md5(content.encode()).hexdigest()[:8]

        # Clean module name
        module_part = module.lower().replace("-", "_")

        # Shorten module name if too long
        if len(module_part) > 30:
            parts = module_part.split("_")
            # Keep significant parts
            module_part = "_".join(p for p in parts if p not in ("c", "common", "syntax"))[:25]

        # Create ID
        return f"c11_{module_part}_{operation}_{content_hash}"
