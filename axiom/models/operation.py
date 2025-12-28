# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

"""Models for function operation subgraphs.

This module defines models for representing a function's operations
as an in-memory graph structure built from tree-sitter parsing.
"""

from enum import Enum

from pydantic import BaseModel, Field


class OperationType(str, Enum):
    """Types of operations that can appear in a function.

    These map to C/C++ language constructs that have semantic meaning
    and may require preconditions or have specific behaviors.
    """

    # Arithmetic operations
    ADDITION = "addition"
    SUBTRACTION = "subtraction"
    MULTIPLICATION = "multiplication"
    DIVISION = "division"
    MODULO = "modulo"
    UNARY_MINUS = "unary_minus"
    INCREMENT = "increment"
    DECREMENT = "decrement"

    # Bitwise operations
    BITWISE_AND = "bitwise_and"
    BITWISE_OR = "bitwise_or"
    BITWISE_XOR = "bitwise_xor"
    BITWISE_NOT = "bitwise_not"
    SHIFT_LEFT = "shift_left"
    SHIFT_RIGHT = "shift_right"

    # Comparison operations
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    LESS_THAN = "less_than"
    GREATER_THAN = "greater_than"
    LESS_EQUAL = "less_equal"
    GREATER_EQUAL = "greater_equal"

    # Logical operations
    LOGICAL_AND = "logical_and"
    LOGICAL_OR = "logical_or"
    LOGICAL_NOT = "logical_not"

    # Memory operations
    POINTER_DEREF = "pointer_deref"
    ADDRESS_OF = "address_of"
    ARRAY_ACCESS = "array_access"
    MEMBER_ACCESS = "member_access"
    ARROW_ACCESS = "arrow_access"

    # Assignment operations
    ASSIGNMENT = "assignment"
    COMPOUND_ASSIGNMENT = "compound_assignment"

    # Control flow
    BRANCH = "branch"
    LOOP = "loop"
    RETURN = "return"
    BREAK = "break"
    CONTINUE = "continue"
    GOTO = "goto"
    SWITCH = "switch"
    CASE = "case"

    # Function-related
    FUNCTION_CALL = "function_call"
    CONSTRUCTOR_CALL = "constructor_call"
    DESTRUCTOR_CALL = "destructor_call"

    # Declarations and allocation
    VARIABLE_DECL = "variable_decl"
    ALLOCATION = "allocation"
    DEALLOCATION = "deallocation"

    # Type operations
    CAST = "cast"
    SIZEOF = "sizeof"
    ALIGNOF = "alignof"

    # C++ specific
    NEW = "new"
    DELETE = "delete"
    THROW = "throw"
    TRY = "try"
    CATCH = "catch"

    # Other
    COMMA = "comma"
    TERNARY = "ternary"
    UNKNOWN = "unknown"


class OperationNode(BaseModel):
    """A single operation in the function graph.

    Represents one operation (expression, statement, or control flow)
    extracted from the AST with semantic context.
    """

    id: str
    """Unique identifier for this operation node."""

    op_type: OperationType
    """The type of operation."""

    code_snippet: str
    """The source code for this operation."""

    line_start: int
    """Starting line number in the source file."""

    line_end: int
    """Ending line number in the source file."""

    column_start: int = 0
    """Starting column in the source file."""

    column_end: int = 0
    """Ending column in the source file."""

    # Structural information from tree-sitter
    operands: list[str] = Field(default_factory=list)
    """Variable names and expressions involved in this operation."""

    operator: str | None = None
    """The operator symbol (e.g., '+', '/', '[]', '->')."""

    # Control flow information
    guards: list[str] = Field(default_factory=list)
    """Conditions that must be true to reach this operation.

    For example, if this operation is inside an if-block,
    the condition of the if statement is a guard.
    """

    predecessors: list[str] = Field(default_factory=list)
    """IDs of operations that come before this one."""

    successors: list[str] = Field(default_factory=list)
    """IDs of operations that come after this one."""

    # Additional context
    parent_id: str | None = None
    """ID of the parent operation (for nested expressions)."""

    is_lvalue: bool = False
    """Whether this expression is used as an lvalue."""

    function_called: str | None = None
    """For FUNCTION_CALL ops, the name of the function being called."""

    call_arguments: list[str] = Field(default_factory=list)
    """For FUNCTION_CALL ops, the argument expressions."""

    ast_node_type: str | None = None
    """The tree-sitter node type (for debugging)."""


class FunctionSubgraph(BaseModel):
    """Complete subgraph of a function's operations.

    This is an in-memory representation of all operations
    in a function, built from tree-sitter parsing.
    """

    name: str
    """Simple function name."""

    qualified_name: str = ""
    """Fully qualified name (with namespace/class)."""

    signature: str
    """Full function signature."""

    parameters: list[tuple] = Field(default_factory=list)
    """List of (name, type) tuples for parameters."""

    return_type: str = ""
    """Return type of the function."""

    nodes: list[OperationNode] = Field(default_factory=list)
    """All operation nodes in the function."""

    entry_id: str | None = None
    """ID of the first operation node."""

    exit_ids: list[str] = Field(default_factory=list)
    """IDs of return/exit operation nodes."""

    # Source location
    file_path: str | None = None
    """Path to the source file."""

    line_start: int = 0
    """Starting line of the function definition."""

    line_end: int = 0
    """Ending line of the function definition."""

    # Optional metadata
    is_method: bool = False
    """Whether this is a class method."""

    class_name: str | None = None
    """For methods, the containing class name."""

    is_template: bool = False
    """Whether this is a template function."""

    def get_node(self, node_id: str) -> OperationNode | None:
        """Get an operation node by ID.

        Args:
            node_id: The unique identifier of the node.

        Returns:
            The OperationNode if found, None otherwise.
        """
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_operations_of_type(self, op_type: OperationType) -> list[OperationNode]:
        """Get all operations of a specific type.

        Args:
            op_type: The type of operations to find.

        Returns:
            List of matching OperationNode objects.
        """
        return [node for node in self.nodes if node.op_type == op_type]

    def get_all_operands(self) -> set[str]:
        """Get all unique operand names used in the function.

        Returns:
            Set of operand names (variable names, expressions).
        """
        operands: set[str] = set()
        for node in self.nodes:
            operands.update(node.operands)
        return operands

    def get_function_calls(self) -> list[OperationNode]:
        """Get all function call operations.

        Returns:
            List of FUNCTION_CALL operation nodes.
        """
        return self.get_operations_of_type(OperationType.FUNCTION_CALL)

    def get_divisions(self) -> list[OperationNode]:
        """Get all division operations.

        Useful for finding potential divide-by-zero issues.

        Returns:
            List of DIVISION and MODULO operation nodes.
        """
        return [
            node for node in self.nodes
            if node.op_type in (OperationType.DIVISION, OperationType.MODULO)
        ]

    def get_pointer_operations(self) -> list[OperationNode]:
        """Get all pointer-related operations.

        Useful for finding potential null pointer dereferences.

        Returns:
            List of pointer operation nodes.
        """
        pointer_types = (
            OperationType.POINTER_DEREF,
            OperationType.ARRAY_ACCESS,
            OperationType.ARROW_ACCESS,
        )
        return [node for node in self.nodes if node.op_type in pointer_types]

    def get_memory_operations(self) -> list[OperationNode]:
        """Get all memory allocation/deallocation operations.

        Returns:
            List of allocation and deallocation operation nodes.
        """
        memory_types = (
            OperationType.ALLOCATION,
            OperationType.DEALLOCATION,
            OperationType.NEW,
            OperationType.DELETE,
        )
        return [node for node in self.nodes if node.op_type in memory_types]

    def has_loops(self) -> bool:
        """Check if the function contains any loops.

        Returns:
            True if the function has loop operations.
        """
        return any(node.op_type == OperationType.LOOP for node in self.nodes)

    def get_nodes_with_guards(self) -> list[OperationNode]:
        """Get all operations that have guard conditions.

        These are operations inside conditional blocks.

        Returns:
            List of operation nodes with non-empty guards.
        """
        return [node for node in self.nodes if node.guards]

    def to_summary(self) -> dict:
        """Generate a summary of the function subgraph.

        Useful for LLM prompts - provides high-level overview.

        Returns:
            Dict with operation counts by type.
        """
        counts: dict = {}
        for node in self.nodes:
            op_name = node.op_type.value
            counts[op_name] = counts.get(op_name, 0) + 1

        return {
            "name": self.name,
            "signature": self.signature,
            "total_operations": len(self.nodes),
            "operation_counts": counts,
            "has_divisions": len(self.get_divisions()) > 0,
            "has_pointer_ops": len(self.get_pointer_operations()) > 0,
            "has_loops": self.has_loops(),
            "function_calls": [
                node.function_called for node in self.get_function_calls()
                if node.function_called
            ],
        }


class MacroDefinition(BaseModel):
    """Represents a C/C++ macro definition (#define).

    Macros can have semantic implications such as:
    - Function-like macros that expand to expressions with hazardous operations
    - Object-like macros that define constants used in semantic constraints
    - Macros that abstract away low-level operations
    """

    name: str
    """The macro name (identifier after #define)."""

    parameters: list[str] = Field(default_factory=list)
    """Parameter names for function-like macros. Empty for object-like macros."""

    body: str = ""
    """The macro expansion body (everything after the name/parameters)."""

    is_function_like: bool = False
    """Whether this is a function-like macro (has parentheses after name)."""

    # Source location
    file_path: str | None = None
    """Path to the source file."""

    line_start: int = 0
    """Starting line of the macro definition."""

    line_end: int = 0
    """Ending line of the macro definition (for multi-line macros)."""

    # Semantic analysis hints
    has_division: bool = False
    """Whether the macro body contains division operations."""

    has_pointer_ops: bool = False
    """Whether the macro body contains pointer dereference/address-of."""

    has_casts: bool = False
    """Whether the macro body contains type casts."""

    function_calls: list[str] = Field(default_factory=list)
    """Function calls found in the macro body."""

    referenced_macros: list[str] = Field(default_factory=list)
    """Other macros referenced in the body."""

    def to_signature(self) -> str:
        """Generate a function-like signature for display.

        Returns:
            Signature string like 'MACRO_NAME(a, b)' or 'MACRO_NAME'.
        """
        if self.is_function_like and self.parameters:
            return f"{self.name}({', '.join(self.parameters)})"
        return self.name

    def to_summary(self) -> dict:
        """Generate a summary for LLM prompts.

        Returns:
            Dict with macro metadata.
        """
        return {
            "name": self.name,
            "signature": self.to_signature(),
            "is_function_like": self.is_function_like,
            "body": self.body,
            "has_division": self.has_division,
            "has_pointer_ops": self.has_pointer_ops,
            "has_casts": self.has_casts,
            "function_calls": self.function_calls,
        }
