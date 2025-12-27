"""Build FunctionSubgraph from C/C++ source using tree-sitter.

This module parses C/C++ source code and builds an in-memory graph
of all operations in a function for semantic analysis.
"""

import hashlib
from typing import List, Optional, Tuple

import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
from tree_sitter import Language, Node, Parser

from axiom.models.operation import FunctionSubgraph, OperationNode, OperationType


class SubgraphBuilder:
    """Build FunctionSubgraph from C/C++ source using tree-sitter.

    Parses C or C++ source code and extracts all operations from
    a specified function, building an operation subgraph.
    """

    # Binary operators and their operation types
    BINARY_OP_MAP = {
        "+": OperationType.ADDITION,
        "-": OperationType.SUBTRACTION,
        "*": OperationType.MULTIPLICATION,
        "/": OperationType.DIVISION,
        "%": OperationType.MODULO,
        "&": OperationType.BITWISE_AND,
        "|": OperationType.BITWISE_OR,
        "^": OperationType.BITWISE_XOR,
        "<<": OperationType.SHIFT_LEFT,
        ">>": OperationType.SHIFT_RIGHT,
        "==": OperationType.EQUAL,
        "!=": OperationType.NOT_EQUAL,
        "<": OperationType.LESS_THAN,
        ">": OperationType.GREATER_THAN,
        "<=": OperationType.LESS_EQUAL,
        ">=": OperationType.GREATER_EQUAL,
        "&&": OperationType.LOGICAL_AND,
        "||": OperationType.LOGICAL_OR,
        ",": OperationType.COMMA,
    }

    # Unary operators and their operation types
    UNARY_OP_MAP = {
        "-": OperationType.UNARY_MINUS,
        "!": OperationType.LOGICAL_NOT,
        "~": OperationType.BITWISE_NOT,
        "*": OperationType.POINTER_DEREF,
        "&": OperationType.ADDRESS_OF,
        "++": OperationType.INCREMENT,
        "--": OperationType.DECREMENT,
    }

    # Compound assignment operators
    COMPOUND_ASSIGN_OPS = {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}

    def __init__(self, language: str = "cpp"):
        """Initialize the parser.

        Args:
            language: Either "c" or "cpp" (default: "cpp").
        """
        self.language = language
        if language == "cpp":
            self.parser = Parser(Language(tscpp.language()))
        else:
            self.parser = Parser(Language(tsc.language()))

        self._node_counter = 0

    def _generate_node_id(self, node: Node) -> str:
        """Generate a unique ID for an operation node.

        Args:
            node: The tree-sitter node.

        Returns:
            A unique ID string.
        """
        self._node_counter += 1
        # Use position and counter for uniqueness
        content = f"{node.start_point}:{node.end_point}:{self._node_counter}"
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def build(self, source: str, function_name: str) -> Optional[FunctionSubgraph]:
        """Parse a function and build its operation subgraph.

        Args:
            source: The complete source code.
            function_name: Name of the function to extract.

        Returns:
            FunctionSubgraph if the function is found, None otherwise.
        """
        self._node_counter = 0
        tree = self.parser.parse(bytes(source, "utf8"))

        func_node = self._find_function(tree.root_node, function_name)
        if func_node is None:
            return None

        # Extract function metadata
        signature = self._extract_signature(func_node)
        params = self._extract_parameters(func_node)
        return_type = self._extract_return_type(func_node)
        is_method, class_name = self._check_if_method(func_node)

        # Get the function body
        body = func_node.child_by_field_name("body")
        if body is None:
            # Function declaration without body
            return FunctionSubgraph(
                name=function_name,
                signature=signature,
                parameters=params,
                return_type=return_type,
                is_method=is_method,
                class_name=class_name,
                line_start=func_node.start_point[0] + 1,
                line_end=func_node.end_point[0] + 1,
            )

        # Walk the AST and extract all operations
        operations: List[OperationNode] = []
        self._walk_all_nodes(body, source, operations, guards=[], parent_id=None)

        # Link predecessors/successors (simple linear for now)
        for i, op in enumerate(operations):
            if i > 0:
                op.predecessors.append(operations[i - 1].id)
            if i < len(operations) - 1:
                op.successors.append(operations[i + 1].id)

        # Find entry and exit points
        entry_id = operations[0].id if operations else None
        exit_ids = [op.id for op in operations if op.op_type == OperationType.RETURN]

        return FunctionSubgraph(
            name=function_name,
            signature=signature,
            parameters=params,
            return_type=return_type,
            nodes=operations,
            entry_id=entry_id,
            exit_ids=exit_ids,
            is_method=is_method,
            class_name=class_name,
            line_start=func_node.start_point[0] + 1,
            line_end=func_node.end_point[0] + 1,
        )

    def build_all(self, source: str) -> List[FunctionSubgraph]:
        """Build subgraphs for all functions in the source.

        Args:
            source: The complete source code.

        Returns:
            List of FunctionSubgraph for each function found.
        """
        tree = self.parser.parse(bytes(source, "utf8"))
        functions = self._find_all_functions(tree.root_node)

        results = []
        for func_name in functions:
            subgraph = self.build(source, func_name)
            if subgraph:
                results.append(subgraph)

        return results

    def _find_function(self, root: Node, function_name: str) -> Optional[Node]:
        """Find a function definition by name.

        Args:
            root: Root AST node.
            function_name: Name to search for.

        Returns:
            The function_definition node if found, None otherwise.
        """
        if root.type == "function_definition":
            declarator = root.child_by_field_name("declarator")
            if declarator:
                name = self._get_function_name_from_declarator(declarator)
                if name == function_name:
                    return root

        for child in root.children:
            result = self._find_function(child, function_name)
            if result:
                return result

        return None

    def _find_all_functions(self, root: Node) -> List[str]:
        """Find all function names in the source.

        Args:
            root: Root AST node.

        Returns:
            List of function names.
        """
        functions = []

        if root.type == "function_definition":
            declarator = root.child_by_field_name("declarator")
            if declarator:
                name = self._get_function_name_from_declarator(declarator)
                if name:
                    functions.append(name)

        for child in root.children:
            functions.extend(self._find_all_functions(child))

        return functions

    def _get_function_name_from_declarator(self, declarator: Node) -> Optional[str]:
        """Extract function name from a declarator node.

        Args:
            declarator: The declarator node.

        Returns:
            Function name or None.
        """
        # Handle function_declarator
        if declarator.type == "function_declarator":
            name_node = declarator.child_by_field_name("declarator")
            if name_node:
                if name_node.type in ("identifier", "field_identifier"):
                    return name_node.text.decode("utf8")
                elif name_node.type == "qualified_identifier":
                    # Get the last part of qualified name
                    for child in reversed(name_node.children):
                        if child.type in ("identifier", "field_identifier"):
                            return child.text.decode("utf8")
                # Recurse for pointer declarators etc.
                return self._get_function_name_from_declarator(name_node)

        # Handle pointer_declarator (for functions returning pointers)
        if declarator.type == "pointer_declarator":
            inner = declarator.child_by_field_name("declarator")
            if inner:
                return self._get_function_name_from_declarator(inner)

        # Handle reference_declarator
        if declarator.type == "reference_declarator":
            for child in declarator.children:
                if child.type in ("function_declarator", "identifier", "field_identifier"):
                    return self._get_function_name_from_declarator(child)

        if declarator.type in ("identifier", "field_identifier"):
            return declarator.text.decode("utf8")

        return None

    def _extract_signature(self, func_node: Node) -> str:
        """Extract the full function signature.

        Args:
            func_node: The function_definition node.

        Returns:
            The function signature as a string.
        """
        # Get everything except the body
        body = func_node.child_by_field_name("body")
        if body:
            end_pos = body.start_byte
            return func_node.text[:end_pos - func_node.start_byte].decode("utf8").strip()
        return func_node.text.decode("utf8")

    def _extract_parameters(self, func_node: Node) -> List[Tuple[str, str]]:
        """Extract function parameters.

        Args:
            func_node: The function_definition node.

        Returns:
            List of (name, type) tuples.
        """
        params = []
        declarator = func_node.child_by_field_name("declarator")

        if declarator:
            # Find the parameter_list
            param_list = self._find_child_recursive(declarator, "parameter_list")
            if param_list:
                for child in param_list.children:
                    if child.type == "parameter_declaration":
                        param_name = ""
                        param_type = ""

                        # Get type
                        type_node = child.child_by_field_name("type")
                        if type_node:
                            param_type = type_node.text.decode("utf8")

                        # Get name from declarator
                        decl = child.child_by_field_name("declarator")
                        if decl:
                            if decl.type == "identifier":
                                param_name = decl.text.decode("utf8")
                            else:
                                # Handle pointer/reference declarators
                                ident = self._find_child_recursive(decl, "identifier")
                                if ident:
                                    param_name = ident.text.decode("utf8")
                                # Adjust type for pointer/reference
                                if decl.type == "pointer_declarator":
                                    param_type += "*"
                                elif decl.type == "reference_declarator":
                                    param_type += "&"

                        if param_name or param_type:
                            params.append((param_name, param_type))

        return params

    def _extract_return_type(self, func_node: Node) -> str:
        """Extract function return type.

        Args:
            func_node: The function_definition node.

        Returns:
            The return type as a string.
        """
        type_node = func_node.child_by_field_name("type")
        if type_node:
            return type_node.text.decode("utf8")
        return ""

    def _check_if_method(self, func_node: Node) -> Tuple[bool, Optional[str]]:
        """Check if function is a class method.

        Args:
            func_node: The function_definition node.

        Returns:
            Tuple of (is_method, class_name).
        """
        # Check if parent is a class_specifier
        parent = func_node.parent
        while parent:
            if parent.type in ("class_specifier", "struct_specifier"):
                name_node = parent.child_by_field_name("name")
                if name_node:
                    return True, name_node.text.decode("utf8")
                return True, None
            parent = parent.parent

        # Check for qualified name (Class::method)
        declarator = func_node.child_by_field_name("declarator")
        if declarator:
            qualified = self._find_child_recursive(declarator, "qualified_identifier")
            if qualified:
                # Get class name (first part before ::)
                for child in qualified.children:
                    if child.type == "namespace_identifier":
                        return True, child.text.decode("utf8")

        return False, None

    def _find_child_recursive(self, node: Node, node_type: str) -> Optional[Node]:
        """Recursively find a child node of a specific type.

        Args:
            node: Parent node.
            node_type: Type to search for.

        Returns:
            The found node or None.
        """
        if node.type == node_type:
            return node

        for child in node.children:
            result = self._find_child_recursive(child, node_type)
            if result:
                return result

        return None

    def _walk_all_nodes(
        self,
        node: Node,
        source: str,
        operations: List[OperationNode],
        guards: List[str],
        parent_id: Optional[str],
    ) -> None:
        """Recursively walk AST and extract all operations.

        This extracts every operation that defines semantics:
        - Assignments, arithmetic, comparisons
        - Pointer operations, array access
        - Function calls
        - Control flow (if, for, while, return)
        - Declarations

        Args:
            node: Current AST node.
            source: Original source code.
            operations: List to append operations to.
            guards: List of guard conditions (for conditional blocks).
            parent_id: ID of parent operation node.
        """
        op_node = None

        # Binary expressions
        if node.type == "binary_expression":
            op_node = self._create_binary_op(node, source, guards, parent_id)

        # Assignment expressions
        elif node.type == "assignment_expression":
            op_node = self._create_assignment_op(node, source, guards, parent_id)

        # Unary expressions
        elif node.type == "unary_expression":
            op_node = self._create_unary_op(node, source, guards, parent_id)

        # Update expressions (++, --)
        elif node.type == "update_expression":
            op_node = self._create_update_op(node, source, guards, parent_id)

        # Subscript (array access)
        elif node.type == "subscript_expression":
            op_node = self._create_subscript_op(node, source, guards, parent_id)

        # Pointer expression (*, &)
        elif node.type == "pointer_expression":
            op_node = self._create_pointer_op(node, source, guards, parent_id)

        # Field expression (obj.field)
        elif node.type == "field_expression":
            op_node = self._create_field_op(node, source, guards, parent_id)

        # Function call
        elif node.type == "call_expression":
            op_node = self._create_call_op(node, source, guards, parent_id)

        # Return statement
        elif node.type == "return_statement":
            op_node = self._create_return_op(node, source, guards, parent_id)

        # Variable declaration
        elif node.type == "declaration":
            op_node = self._create_declaration_op(node, source, guards, parent_id)

        # If statement (branch)
        elif node.type == "if_statement":
            op_node = self._create_branch_op(node, source, guards, parent_id)
            if op_node:
                operations.append(op_node)
                # Get the condition for guard
                condition = node.child_by_field_name("condition")
                cond_text = condition.text.decode("utf8") if condition else ""

                # Process consequence with positive guard
                consequence = node.child_by_field_name("consequence")
                if consequence:
                    new_guards = guards + [cond_text] if cond_text else guards
                    self._walk_all_nodes(
                        consequence, source, operations, new_guards, op_node.id
                    )

                # Process alternative with negative guard
                alternative = node.child_by_field_name("alternative")
                if alternative:
                    new_guards = guards + [f"!({cond_text})"] if cond_text else guards
                    self._walk_all_nodes(
                        alternative, source, operations, new_guards, op_node.id
                    )
                return  # Don't recurse normally

        # For/while loops
        elif node.type in ("for_statement", "while_statement", "do_statement"):
            op_node = self._create_loop_op(node, source, guards, parent_id)
            if op_node:
                operations.append(op_node)
                # Get loop body
                body = node.child_by_field_name("body")
                if body:
                    self._walk_all_nodes(
                        body, source, operations, guards, op_node.id
                    )
                return  # Don't recurse normally

        # Switch statement
        elif node.type == "switch_statement":
            op_node = self._create_switch_op(node, source, guards, parent_id)

        # Conditional expression (ternary)
        elif node.type == "conditional_expression":
            op_node = self._create_ternary_op(node, source, guards, parent_id)

        # Cast expression
        elif node.type == "cast_expression":
            op_node = self._create_cast_op(node, source, guards, parent_id)

        # Sizeof expression
        elif node.type == "sizeof_expression":
            op_node = self._create_sizeof_op(node, source, guards, parent_id)

        # New expression (C++)
        elif node.type == "new_expression":
            op_node = self._create_new_op(node, source, guards, parent_id)

        # Delete expression (C++)
        elif node.type == "delete_expression":
            op_node = self._create_delete_op(node, source, guards, parent_id)

        # Throw expression (C++)
        elif node.type == "throw_statement":
            op_node = self._create_throw_op(node, source, guards, parent_id)

        # Add the operation if created
        if op_node:
            operations.append(op_node)

        # Recurse into children
        for child in node.children:
            self._walk_all_nodes(child, source, operations, guards, parent_id)

    def _create_binary_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for binary expression."""
        operator = ""
        for child in node.children:
            if child.is_named is False and child.type in self.BINARY_OP_MAP:
                operator = child.type
                break

        # Get operands
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        operands = []
        if left:
            operands.append(left.text.decode("utf8"))
        if right:
            operands.append(right.text.decode("utf8"))

        op_type = self.BINARY_OP_MAP.get(operator, OperationType.UNKNOWN)

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=op_type,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            operator=operator,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_assignment_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for assignment expression."""
        operator = "="
        for child in node.children:
            if child.is_named is False:
                op_text = child.type
                if op_text in self.COMPOUND_ASSIGN_OPS or op_text == "=":
                    operator = op_text
                    break

        op_type = (
            OperationType.COMPOUND_ASSIGNMENT
            if operator in self.COMPOUND_ASSIGN_OPS
            else OperationType.ASSIGNMENT
        )

        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        operands = []
        if left:
            operands.append(left.text.decode("utf8"))
        if right:
            operands.append(right.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=op_type,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            operator=operator,
            guards=guards.copy(),
            parent_id=parent_id,
            is_lvalue=True,
            ast_node_type=node.type,
        )

    def _create_unary_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for unary expression."""
        operator = ""
        for child in node.children:
            if child.is_named is False and child.type in self.UNARY_OP_MAP:
                operator = child.type
                break

        operand = node.child_by_field_name("argument")
        operands = [operand.text.decode("utf8")] if operand else []

        op_type = self.UNARY_OP_MAP.get(operator, OperationType.UNKNOWN)

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=op_type,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            operator=operator,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_update_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for update expression (++/--)."""
        operator = ""
        for child in node.children:
            if child.type in ("++", "--"):
                operator = child.type
                break

        op_type = (
            OperationType.INCREMENT if operator == "++" else OperationType.DECREMENT
        )

        operand = node.child_by_field_name("argument")
        operands = [operand.text.decode("utf8")] if operand else []

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=op_type,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            operator=operator,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_subscript_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for subscript/array access."""
        argument = node.child_by_field_name("argument")
        operands = []
        if argument:
            operands.append(argument.text.decode("utf8"))

        # Index may be in 'index' field or inside subscript_argument_list
        index = node.child_by_field_name("index")
        if index:
            operands.append(index.text.decode("utf8"))
        else:
            # Look for subscript_argument_list and extract index from it
            for child in node.children:
                if child.type == "subscript_argument_list":
                    for subchild in child.named_children:
                        operands.append(subchild.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.ARRAY_ACCESS,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            operator="[]",
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_pointer_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for pointer expression (* or &)."""
        operator = ""
        for child in node.children:
            if child.type in ("*", "&"):
                operator = child.type
                break

        op_type = (
            OperationType.POINTER_DEREF if operator == "*" else OperationType.ADDRESS_OF
        )

        operand = node.child_by_field_name("argument")
        operands = [operand.text.decode("utf8")] if operand else []

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=op_type,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            operator=operator,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_field_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for field access (. or ->)."""
        operator = "."
        for child in node.children:
            if child.type == "->":
                operator = "->"
                break

        op_type = (
            OperationType.ARROW_ACCESS
            if operator == "->"
            else OperationType.MEMBER_ACCESS
        )

        argument = node.child_by_field_name("argument")
        field = node.child_by_field_name("field")
        operands = []
        if argument:
            operands.append(argument.text.decode("utf8"))
        if field:
            operands.append(field.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=op_type,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            operator=operator,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_call_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for function call."""
        func_node = node.child_by_field_name("function")
        func_name = func_node.text.decode("utf8") if func_node else ""

        # Get arguments
        args = node.child_by_field_name("arguments")
        call_args = []
        if args:
            for child in args.children:
                if child.is_named:
                    call_args.append(child.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.FUNCTION_CALL,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=call_args,
            function_called=func_name,
            call_arguments=call_args,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_return_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for return statement."""
        # Get return value
        operands = []
        for child in node.children:
            if child.is_named and child.type != "return":
                operands.append(child.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.RETURN,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_declaration_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for variable declaration."""
        # Get declared variable names
        operands = []
        for child in node.children:
            if child.type == "init_declarator":
                declarator = child.child_by_field_name("declarator")
                if declarator:
                    ident = self._find_child_recursive(declarator, "identifier")
                    if ident:
                        operands.append(ident.text.decode("utf8"))
            elif child.type == "identifier":
                operands.append(child.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.VARIABLE_DECL,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_branch_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for if statement."""
        condition = node.child_by_field_name("condition")
        cond_text = condition.text.decode("utf8") if condition else ""

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.BRANCH,
            code_snippet=f"if {cond_text}",
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=[cond_text] if cond_text else [],
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_loop_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for loop statement."""
        # Extract loop condition
        condition = node.child_by_field_name("condition")
        cond_text = condition.text.decode("utf8") if condition else ""

        loop_type = node.type.replace("_statement", "")

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.LOOP,
            code_snippet=f"{loop_type} ({cond_text})" if cond_text else loop_type,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=[cond_text] if cond_text else [],
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_switch_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for switch statement."""
        condition = node.child_by_field_name("condition")
        cond_text = condition.text.decode("utf8") if condition else ""

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.SWITCH,
            code_snippet=f"switch ({cond_text})",
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=[cond_text] if cond_text else [],
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_ternary_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for ternary expression."""
        condition = node.child_by_field_name("condition")
        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")

        operands = []
        if condition:
            operands.append(condition.text.decode("utf8"))
        if consequence:
            operands.append(consequence.text.decode("utf8"))
        if alternative:
            operands.append(alternative.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.TERNARY,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            operator="?:",
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_cast_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for cast expression."""
        type_node = node.child_by_field_name("type")
        value_node = node.child_by_field_name("value")

        operands = []
        if type_node:
            operands.append(type_node.text.decode("utf8"))
        if value_node:
            operands.append(value_node.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.CAST,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_sizeof_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for sizeof expression."""
        operands = []
        for child in node.children:
            if child.is_named:
                operands.append(child.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.SIZEOF,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_new_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for new expression (C++)."""
        type_node = node.child_by_field_name("type")
        operands = [type_node.text.decode("utf8")] if type_node else []

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.NEW,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_delete_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for delete expression (C++)."""
        operands = []
        for child in node.children:
            if child.is_named and child.type != "delete":
                operands.append(child.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.DELETE,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )

    def _create_throw_op(
        self, node: Node, source: str, guards: List[str], parent_id: Optional[str]
    ) -> OperationNode:
        """Create operation node for throw statement (C++)."""
        operands = []
        for child in node.children:
            if child.is_named:
                operands.append(child.text.decode("utf8"))

        return OperationNode(
            id=self._generate_node_id(node),
            op_type=OperationType.THROW,
            code_snippet=node.text.decode("utf8"),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            column_start=node.start_point[1],
            column_end=node.end_point[1],
            operands=operands,
            guards=guards.copy(),
            parent_id=parent_id,
            ast_node_type=node.type,
        )
