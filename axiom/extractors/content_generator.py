# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Generate human-readable content from K formal specifications."""

import hashlib
import re


class ContentGenerator:
    """Generate human-readable axiom content from K formal specs.

    This class transforms K Framework formal specifications into natural
    language descriptions that are better suited for semantic search.
    """

    # Templates for common K predicates -> human-readable descriptions
    # Organized by category for clarity
    PREDICATE_TEMPLATES = {
        # Zero/null checks
        "notBool isZero": "divisor must be non-zero",
        "isZero": "value must be zero",
        "isNullPointerConstant": "value is a null pointer constant",
        "notBool isNullPointerConstant": "value must not be null",
        "==K NullPointer": "is a null pointer",
        "=/=K NullPointer": "must not be a null pointer",

        # Type predicates - promoted types
        "isPromoted": "operand must be integer-promoted",
        "notBool isPromoted": "operand requires integer promotion",
        "==Type": "operand types must match",
        "=/=Type": "operand types differ",

        # Completeness
        "isCompleteType": "type must be complete",
        "notBool isCompleteType": "type is incomplete",
        "isCompletePointerType": "pointer must point to complete type",

        # Pointer types
        "isPointerType": "operand is a pointer type",
        "isPointerUType": "operand is a pointer type",
        "notBool isPointerUType": "operand must not be a pointer",
        "isFunctionPointerType": "operand is a function pointer",
        "notBool isFunctionPointerType": "operand must not be a function pointer",

        # Integer types
        "isIntegerType": "operand is an integer type",
        "isIntegerUType": "operand is an integer type",
        "hasIntegerType": "operand has integer type",
        "isSignedIntegerType": "operand is a signed integer",
        "isUnsignedIntegerType": "operand is an unsigned integer",

        # Floating-point types
        "isFloatType": "operand is a floating-point type",
        "isFloatUType": "operand is a floating-point type",

        # Other type categories
        "isVoidType": "type is void",
        "notBool isVoidType": "type must not be void",
        "isArithmeticType": "operand is an arithmetic type",
        "isScalarType": "operand is a scalar type",
        "isBoolType": "operand is a boolean type",
        "isCharType": "operand is a character type",
        "isWCharType": "operand is a wide character type",
        "isStructOrUnionType": "operand is a struct or union",
        "notBool isStructOrUnionType": "operand must not be a struct or union",
        "isArrayType": "operand is an array type",
        "isBasicType": "operand is a basic type",
        "isBitfieldType": "operand is a bitfield type",

        # Qualifier predicates
        "notBool isConstType": "operand must not be const-qualified",
        "isConstType": "operand is const-qualified",
        "isVolatileType": "operand is volatile-qualified",

        # Value state predicates
        "isUnknown": "value is indeterminate",
        "notBool isUnknown": "value must be determinate",
        "hasUnknown": "contains indeterminate value",
        "notBool hasUnknown": "must not contain indeterminate values",
        "isTrap": "value is a trap representation",
        "notBool isTrap": "value must not be a trap representation",
        "hasTrap": "contains trap representation",
        "notBool hasTrap": "must not contain trap representations",
        "isOpaque": "value is opaque",
        "notBool isOpaque": "value must not be opaque",

        # Bounds checking - these indicate overflow/underflow conditions
        ">Int max(T)": "value exceeds maximum for type (overflow)",
        "<Int min(T)": "value below minimum for type (underflow)",
        "<=Int max(T)": "value must not exceed type maximum",
        ">=Int min(T)": "value must not be below type minimum",

        # Expression context
        "fromConstantExpr": "must be a constant expression",
        "notBool fromConstantExpr": "is not a constant expression",
        "isHold": "expression is held for evaluation",
        "notBool isHold": "expression is not held",
        "isSymLoc": "value is a symbolic location",
        "notBool isSymLoc": "value must not be a symbolic location",
        "isLocation": "value is a memory location",
        "notBool isLocation": "value is not a memory location",

        # K-specific evaluation state
        "isKResult": "is a K result",
        "notBool isKResult": "is not yet a K result",
        "isRHold": "is a held rvalue",
        "notBool isRHold": "is not a held rvalue",

        # Lvalue/object predicates
        "isLValue": "must be an lvalue",
        "isModifiableLValue": "must be a modifiable lvalue",
        "isNPC": "is a null pointer constant",

        # Alignment and representation
        "hasFloat": "contains floating-point value",
        "notBool hasFloat": "must not contain floating-point",
        "hasInt": "contains integer value",
        "notBool hasInt": "must not contain integer",
    }

    # Operation name mappings
    OPERATION_NAMES = {
        "division": "Integer division",
        "modulus": "Modulus operation",
        "multiplication": "Integer multiplication",
        "addition": "Addition",
        "subtraction": "Subtraction",
        "shift": "Bit shift",
        "bitwise": "Bitwise operation",
        "comparison": "Comparison",
        "assignment": "Assignment",
        "cast": "Type conversion",
        "conversion": "Type conversion",
        "dereference": "Pointer dereference",
        "subscript": "Array subscript",
        "member": "Member access",
        "call": "Function call",
        "operation": "Operation",
    }

    def generate(
        self, formal_spec: str, operation: str | None = None
    ) -> str:
        """Generate human-readable content from K formal spec.

        Args:
            formal_spec: K requires clause (may include C standard comments).
            operation: Optional operation name for context.

        Returns:
            Human-readable description.
        """
        if not formal_spec:
            return "No preconditions specified."

        # First, try to extract C standard text from comments
        standard_text = self._extract_standard_text(formal_spec)
        if standard_text:
            return standard_text

        # Clean the spec of comments before parsing
        clean_spec = self._remove_comments(formal_spec)

        conditions = self.parse_conditions(clean_spec)
        descriptions = [self._describe_condition(c) for c in conditions]

        # Filter out empty descriptions
        descriptions = [d for d in descriptions if d]

        if not descriptions:
            # Fallback: just clean up the formal spec
            cleaned = self._clean_formal_spec(clean_spec)
            if len(cleaned) > 100:
                cleaned = cleaned[:97] + "..."
            return f"Requires: {cleaned}"

        # Build the description
        op_name = self.OPERATION_NAMES.get(operation, "Operation") if operation else "Operation"

        if len(descriptions) == 1:
            return f"{op_name} requires: {descriptions[0]}."
        else:
            return f"{op_name} requires: {', '.join(descriptions[:-1])}, and {descriptions[-1]}."

    def _extract_standard_text(self, formal_spec: str) -> str | None:
        """Extract human-readable text from C standard comments.

        K semantics often embed C standard quotes like:
        /*@ \\fromStandard{\\source[n1570]{\\para{6.3.1.4}{1}}}{...text...}*/

        Args:
            formal_spec: K formal specification with possible comments.

        Returns:
            Extracted standard text if found, None otherwise.
        """
        # Pattern for K Framework standard citations
        # Matches: /*@ \fromStandard{\source[n1570]{\para{X.X.X}{N}}}{TEXT}*/
        pattern = r'/\*@\s*\\fromStandard\{[^}]+\}\{([^}]+)\}\s*\*/'
        match = re.search(pattern, formal_spec)
        if match:
            text = match.group(1).strip()
            # Clean up inline C code markers
            text = re.sub(r'\\cinline\{([^}]+)\}', r'`\1`', text)
            return text

        # Also check for simpler comment patterns with UB descriptions
        ub_pattern = r'//\s*(.*(?:undefined behavior|the behavior is undefined).*)'
        match = re.search(ub_pattern, formal_spec, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return None

    def _remove_comments(self, spec: str) -> str:
        """Remove K Framework comments from specification.

        Args:
            spec: K formal specification.

        Returns:
            Specification without comments.
        """
        # Remove /*@ ... */ comments
        spec = re.sub(r'/\*@?[^*]*\*+(?:[^/*][^*]*\*+)*/', '', spec)
        # Remove // comments to end of line
        spec = re.sub(r'//[^\n]*', '', spec)
        # Remove syntax declarations
        spec = re.sub(r'syntax\s+\w+\s*::=\s*[^\n]+', '', spec)
        # Remove endmodule markers
        spec = re.sub(r'\s*endmodule\s*', '', spec)
        # Remove context declarations
        spec = re.sub(r'context\s+[^\n]+', '', spec)
        return spec.strip()

    def parse_conditions(self, formal_spec: str) -> list[str]:
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
            part = part.strip()
            if part:
                conditions.append(part)

        return conditions

    def _describe_condition(self, condition: str) -> str:
        """Generate description for a single condition.

        Args:
            condition: Single K condition.

        Returns:
            Human-readable description.
        """
        condition = condition.strip()

        # Handle parenthesized conditions
        while condition.startswith("(") and condition.endswith(")"):
            # Check if these are balanced outer parens
            depth = 0
            balanced = True
            for i, c in enumerate(condition):
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                if depth == 0 and i < len(condition) - 1:
                    balanced = False
                    break
            if balanced:
                condition = condition[1:-1].strip()
            else:
                break

        # Handle orBool conditions first
        if " orBool " in condition:
            parts = re.split(r"\s+orBool\s+", condition)
            described = [self._describe_condition(p.strip()) for p in parts]
            described = [d for d in described if d]
            if len(described) == 2:
                return f"either {described[0]} or {described[1]}"
            elif described:
                return f"one of: {', '.join(described)}"
            return ""

        # Handle impliesBool
        if " impliesBool " in condition:
            parts = condition.split(" impliesBool ", 1)
            if len(parts) == 2:
                antecedent = self._describe_condition(parts[0].strip())
                consequent = self._describe_condition(parts[1].strip())
                if antecedent and consequent:
                    return f"if {antecedent} then {consequent}"

        # Handle xorBool
        if " xorBool " in condition:
            parts = condition.split(" xorBool ", 1)
            if len(parts) == 2:
                left = self._describe_condition(parts[0].strip())
                right = self._describe_condition(parts[1].strip())
                if left and right:
                    return f"exactly one of ({left}) or ({right})"

        # Check against known templates (order matters - check specific first)
        for pattern, description in sorted(
            self.PREDICATE_TEMPLATES.items(),
            key=lambda x: -len(x[0]),  # Longer patterns first
        ):
            if pattern in condition:
                return description

        # Handle negation as fallback
        if condition.startswith("notBool "):
            inner = condition[8:].strip()
            # Remove parens if present
            if inner.startswith("(") and inner.endswith(")"):
                inner = inner[1:-1].strip()
            inner_desc = self._describe_condition(inner)
            if inner_desc:
                return f"NOT: {inner_desc}"

        # Fallback: clean up and return simplified version
        cleaned = self._clean_formal_spec(condition)
        if cleaned and len(cleaned) < 80:
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

        # Replace K-specific type annotations
        spec = re.sub(r'::(?:UType|CValue|Type|KItem)', '', spec)
        spec = re.sub(r':(?:Int|Float|Bool|K)\b', '', spec)

        # Replace K operators with readable versions
        spec = spec.replace("=/=K", "≠")
        spec = spec.replace("==K", "=")
        spec = spec.replace("=/=Type", "types differ")
        spec = spec.replace("==Type", "types match")
        spec = spec.replace("<=Int", "≤")
        spec = spec.replace(">=Int", "≥")
        spec = spec.replace(">Int", ">")
        spec = spec.replace("<Int", "<")
        spec = spec.replace("<=Quals", "qualifiers ⊆")

        # Clean up HOLE markers from contexts
        spec = re.sub(r'HOLE\s*=>\s*\w+\([^)]*\)', '', spec)

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

    def extract_c_standard_ref(self, formal_spec: str) -> str | None:
        """Extract C standard section reference from K comments.

        Args:
            formal_spec: K formal specification.

        Returns:
            C standard reference like "6.3.1.4/1" if found.
        """
        # Pattern: \para{6.3.1.4}{1}
        pattern = r'\\para\{([^}]+)\}\{([^}]+)\}'
        match = re.search(pattern, formal_spec)
        if match:
            section = match.group(1)
            para = match.group(2)
            return f"{section}/{para}"
        return None
