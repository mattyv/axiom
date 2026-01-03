"""Comprehensive tests for SubgraphBuilder.

These tests ensure the tree-sitter based parser correctly extracts
operations from C/C++ source code with proper guards, operands, and types.
"""


from axiom.ingestion import SubgraphBuilder
from axiom.models import OperationType


class TestSubgraphBuilderBasics:
    """Basic functionality tests."""

    def test_builds_simple_function(self):
        """Test building subgraph for a simple function."""
        code = """
        int add(int a, int b) {
            return a + b;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "add")

        assert sg is not None
        assert sg.name == "add"
        assert sg.return_type == "int"
        assert len(sg.parameters) == 2
        assert sg.parameters[0] == ("a", "int")
        assert sg.parameters[1] == ("b", "int")

    def test_returns_none_for_missing_function(self):
        """Test that None is returned when function doesn't exist."""
        code = "int foo() { return 0; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "bar")

        assert sg is None

    def test_builds_all_functions(self):
        """Test build_all finds all functions in source."""
        code = """
        int foo() { return 1; }
        int bar() { return 2; }
        void baz() { }
        """
        builder = SubgraphBuilder(language="cpp")
        subgraphs = builder.build_all(code)

        assert len(subgraphs) == 3
        names = {sg.name for sg in subgraphs}
        assert names == {"foo", "bar", "baz"}

    def test_handles_function_declaration_without_body(self):
        """Test handling function declarations (no body)."""
        code = "int forward_decl(int x);"
        builder = SubgraphBuilder(language="cpp")
        # Should not crash, returns function with no operations
        subgraphs = builder.build_all(code)
        # Declarations aren't function_definitions, so empty
        assert len(subgraphs) == 0

    def test_c_language_mode(self):
        """Test C language mode works."""
        code = """
        int add(int a, int b) {
            return a + b;
        }
        """
        builder = SubgraphBuilder(language="c")
        sg = builder.build(code, "add")

        assert sg is not None
        assert sg.name == "add"

    def test_signature_excludes_function_body(self):
        """Test that signature only includes declaration, not implementation."""
        code = """
        int simple_func(int x) {
            return x + 1;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "simple_func")

        assert sg is not None
        # Signature should NOT contain the body
        assert "{" not in sg.signature
        assert "return" not in sg.signature
        assert sg.signature.strip() == "int simple_func(int x)"

    def test_signature_excludes_constexpr_function_body(self):
        """Test that constexpr function signatures exclude the body."""
        code = """
        constexpr int compute(int x) {
            if (x < 0) return -x;
            else return x;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "compute")

        assert sg is not None
        # Signature should NOT contain the body or if/else logic
        assert "{" not in sg.signature
        assert "if" not in sg.signature
        assert "return" not in sg.signature
        assert sg.signature.strip() == "constexpr int compute(int x)"

    def test_signature_excludes_large_constexpr_body(self):
        """Test that large constexpr functions only include signature."""
        code = """
        constexpr int factorial(int n) {
            int result = 1;
            for (int i = 2; i <= n; ++i) {
                result *= i;
            }
            return result;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "factorial")

        assert sg is not None
        # Signature should be a single line
        assert sg.signature.count('\n') == 0 or sg.signature.count('\n') == 1
        assert "{" not in sg.signature
        assert "for" not in sg.signature
        assert "result" not in sg.signature
        assert sg.signature.strip() == "constexpr int factorial(int n)"


class TestArithmeticOperations:
    """Tests for arithmetic operation extraction."""

    def test_extracts_addition(self):
        """Test addition operation extraction."""
        code = """
        int add(int a, int b) {
            return a + b;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "add")

        additions = sg.get_operations_of_type(OperationType.ADDITION)
        assert len(additions) == 1
        assert additions[0].operator == "+"
        assert "a" in additions[0].operands
        assert "b" in additions[0].operands

    def test_extracts_subtraction(self):
        """Test subtraction operation extraction."""
        code = """
        int sub(int a, int b) {
            return a - b;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "sub")

        subs = sg.get_operations_of_type(OperationType.SUBTRACTION)
        assert len(subs) == 1
        assert subs[0].operator == "-"

    def test_extracts_multiplication(self):
        """Test multiplication operation extraction."""
        code = """
        int mul(int a, int b) {
            return a * b;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "mul")

        muls = sg.get_operations_of_type(OperationType.MULTIPLICATION)
        assert len(muls) == 1
        assert muls[0].operator == "*"

    def test_extracts_division(self):
        """Test division operation extraction."""
        code = """
        int div(int a, int b) {
            return a / b;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "div")

        divs = sg.get_divisions()
        assert len(divs) == 1
        assert divs[0].operator == "/"
        assert divs[0].op_type == OperationType.DIVISION

    def test_extracts_modulo(self):
        """Test modulo operation extraction."""
        code = """
        int mod(int a, int b) {
            return a % b;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "mod")

        divs = sg.get_divisions()  # get_divisions includes modulo
        assert len(divs) == 1
        assert divs[0].operator == "%"
        assert divs[0].op_type == OperationType.MODULO

    def test_extracts_unary_minus(self):
        """Test unary minus operation extraction."""
        code = """
        int neg(int a) {
            return -a;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "neg")

        negs = sg.get_operations_of_type(OperationType.UNARY_MINUS)
        assert len(negs) == 1
        assert negs[0].operator == "-"

    def test_extracts_increment_decrement(self):
        """Test increment/decrement operation extraction."""
        code = """
        void update(int* x) {
            (*x)++;
            (*x)--;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "update")

        incs = sg.get_operations_of_type(OperationType.INCREMENT)
        decs = sg.get_operations_of_type(OperationType.DECREMENT)
        assert len(incs) == 1
        assert len(decs) == 1


class TestBitwiseOperations:
    """Tests for bitwise operation extraction."""

    def test_extracts_bitwise_and(self):
        """Test bitwise AND extraction."""
        code = "int f(int a, int b) { return a & b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.BITWISE_AND)
        assert len(ops) == 1
        assert ops[0].operator == "&"

    def test_extracts_bitwise_or(self):
        """Test bitwise OR extraction."""
        code = "int f(int a, int b) { return a | b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.BITWISE_OR)
        assert len(ops) == 1
        assert ops[0].operator == "|"

    def test_extracts_bitwise_xor(self):
        """Test bitwise XOR extraction."""
        code = "int f(int a, int b) { return a ^ b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.BITWISE_XOR)
        assert len(ops) == 1
        assert ops[0].operator == "^"

    def test_extracts_bitwise_not(self):
        """Test bitwise NOT extraction."""
        code = "int f(int a) { return ~a; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.BITWISE_NOT)
        assert len(ops) == 1
        assert ops[0].operator == "~"

    def test_extracts_shift_left(self):
        """Test left shift extraction."""
        code = "int f(int a, int b) { return a << b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.SHIFT_LEFT)
        assert len(ops) == 1
        assert ops[0].operator == "<<"

    def test_extracts_shift_right(self):
        """Test right shift extraction."""
        code = "int f(int a, int b) { return a >> b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.SHIFT_RIGHT)
        assert len(ops) == 1
        assert ops[0].operator == ">>"


class TestComparisonOperations:
    """Tests for comparison operation extraction."""

    def test_extracts_equal(self):
        """Test equality comparison extraction."""
        code = "bool f(int a, int b) { return a == b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.EQUAL)
        assert len(ops) == 1
        assert ops[0].operator == "=="

    def test_extracts_not_equal(self):
        """Test not-equal comparison extraction."""
        code = "bool f(int a, int b) { return a != b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.NOT_EQUAL)
        assert len(ops) == 1
        assert ops[0].operator == "!="

    def test_extracts_less_than(self):
        """Test less-than comparison extraction."""
        code = "bool f(int a, int b) { return a < b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.LESS_THAN)
        assert len(ops) == 1
        assert ops[0].operator == "<"

    def test_extracts_greater_than(self):
        """Test greater-than comparison extraction."""
        code = "bool f(int a, int b) { return a > b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.GREATER_THAN)
        assert len(ops) == 1
        assert ops[0].operator == ">"

    def test_extracts_less_equal(self):
        """Test less-or-equal comparison extraction."""
        code = "bool f(int a, int b) { return a <= b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.LESS_EQUAL)
        assert len(ops) == 1
        assert ops[0].operator == "<="

    def test_extracts_greater_equal(self):
        """Test greater-or-equal comparison extraction."""
        code = "bool f(int a, int b) { return a >= b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.GREATER_EQUAL)
        assert len(ops) == 1
        assert ops[0].operator == ">="


class TestLogicalOperations:
    """Tests for logical operation extraction."""

    def test_extracts_logical_and(self):
        """Test logical AND extraction."""
        code = "bool f(bool a, bool b) { return a && b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.LOGICAL_AND)
        assert len(ops) == 1
        assert ops[0].operator == "&&"

    def test_extracts_logical_or(self):
        """Test logical OR extraction."""
        code = "bool f(bool a, bool b) { return a || b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.LOGICAL_OR)
        assert len(ops) == 1
        assert ops[0].operator == "||"

    def test_extracts_logical_not(self):
        """Test logical NOT extraction."""
        code = "bool f(bool a) { return !a; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        ops = sg.get_operations_of_type(OperationType.LOGICAL_NOT)
        assert len(ops) == 1
        assert ops[0].operator == "!"


class TestPointerOperations:
    """Tests for pointer operation extraction."""

    def test_extracts_pointer_dereference(self):
        """Test pointer dereference extraction."""
        code = """
        int deref(int* p) {
            return *p;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "deref")

        ops = sg.get_pointer_operations()
        deref_ops = [op for op in ops if op.op_type == OperationType.POINTER_DEREF]
        assert len(deref_ops) >= 1
        assert deref_ops[0].operator == "*"

    def test_extracts_address_of(self):
        """Test address-of operation extraction."""
        code = """
        int* addr(int x) {
            return &x;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "addr")

        ops = sg.get_operations_of_type(OperationType.ADDRESS_OF)
        assert len(ops) == 1
        assert ops[0].operator == "&"

    def test_extracts_array_access(self):
        """Test array access extraction."""
        code = """
        int get(int arr[], int i) {
            return arr[i];
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "get")

        ops = sg.get_pointer_operations()
        arr_ops = [op for op in ops if op.op_type == OperationType.ARRAY_ACCESS]
        assert len(arr_ops) == 1
        assert arr_ops[0].operator == "[]"
        assert "arr" in arr_ops[0].operands
        assert "i" in arr_ops[0].operands

    def test_extracts_member_access(self):
        """Test member access (dot) extraction."""
        code = """
        struct Point { int x; int y; };
        int getX(struct Point p) {
            return p.x;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "getX")

        ops = sg.get_operations_of_type(OperationType.MEMBER_ACCESS)
        assert len(ops) == 1
        assert ops[0].operator == "."

    def test_extracts_arrow_access(self):
        """Test arrow access extraction."""
        code = """
        struct Point { int x; int y; };
        int getX(struct Point* p) {
            return p->x;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "getX")

        ops = sg.get_pointer_operations()
        arrow_ops = [op for op in ops if op.op_type == OperationType.ARROW_ACCESS]
        assert len(arrow_ops) == 1
        assert arrow_ops[0].operator == "->"


class TestAssignmentOperations:
    """Tests for assignment operation extraction."""

    def test_extracts_simple_assignment(self):
        """Test simple assignment extraction."""
        code = """
        void assign(int* x) {
            *x = 5;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "assign")

        ops = sg.get_operations_of_type(OperationType.ASSIGNMENT)
        assert len(ops) == 1
        assert ops[0].operator == "="
        assert ops[0].is_lvalue is True

    def test_extracts_compound_assignment(self):
        """Test compound assignment extraction."""
        code = """
        void update(int* x) {
            *x += 5;
            *x -= 3;
            *x *= 2;
            *x /= 4;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "update")

        ops = sg.get_operations_of_type(OperationType.COMPOUND_ASSIGNMENT)
        assert len(ops) == 4
        operators = {op.operator for op in ops}
        assert operators == {"+=", "-=", "*=", "/="}


class TestControlFlowOperations:
    """Tests for control flow operation extraction."""

    def test_extracts_if_branch(self):
        """Test if statement branch extraction."""
        code = """
        int abs(int x) {
            if (x < 0) {
                return -x;
            }
            return x;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "abs")

        branches = sg.get_operations_of_type(OperationType.BRANCH)
        assert len(branches) == 1
        assert "x < 0" in branches[0].code_snippet or "(x < 0)" in branches[0].operands

    def test_extracts_for_loop(self):
        """Test for loop extraction."""
        code = """
        int sum(int n) {
            int s = 0;
            for (int i = 0; i < n; i++) {
                s += i;
            }
            return s;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "sum")

        loops = sg.get_operations_of_type(OperationType.LOOP)
        assert len(loops) == 1
        assert sg.has_loops() is True

    def test_extracts_while_loop(self):
        """Test while loop extraction."""
        code = """
        int countdown(int n) {
            while (n > 0) {
                n--;
            }
            return n;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "countdown")

        loops = sg.get_operations_of_type(OperationType.LOOP)
        assert len(loops) == 1
        assert sg.has_loops() is True

    def test_extracts_return(self):
        """Test return statement extraction."""
        code = """
        int get() {
            return 42;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "get")

        returns = sg.get_operations_of_type(OperationType.RETURN)
        assert len(returns) == 1
        assert "42" in returns[0].operands or "42" in returns[0].code_snippet

    def test_extracts_switch(self):
        """Test switch statement extraction."""
        code = """
        int handle(int x) {
            switch (x) {
                case 0: return 0;
                case 1: return 1;
                default: return -1;
            }
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "handle")

        switches = sg.get_operations_of_type(OperationType.SWITCH)
        assert len(switches) == 1


class TestGuardConditions:
    """Tests for guard condition tracking."""

    def test_operations_inside_if_have_guard(self):
        """Test that operations inside if blocks have guard conditions."""
        code = """
        int safe_div(int x, int y) {
            if (y != 0) {
                return x / y;
            }
            return 0;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "safe_div")

        divs = sg.get_divisions()
        assert len(divs) == 1
        assert len(divs[0].guards) == 1
        assert "(y != 0)" in divs[0].guards[0] or "y != 0" in divs[0].guards[0]

    def test_operations_in_else_have_negated_guard(self):
        """Test that operations in else blocks have negated guard."""
        code = """
        int check(int* p) {
            if (p != nullptr) {
                return *p;
            } else {
                return -1;
            }
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "check")

        # Find the return -1 operation
        returns = sg.get_operations_of_type(OperationType.RETURN)
        else_return = [r for r in returns if "-1" in r.code_snippet]
        assert len(else_return) == 1
        # Should have negated guard
        assert len(else_return[0].guards) == 1
        assert "!" in else_return[0].guards[0]

    def test_nested_if_accumulates_guards(self):
        """Test that nested ifs accumulate guard conditions."""
        code = """
        int nested(int* p, int* q) {
            if (p != nullptr) {
                if (q != nullptr) {
                    return *p + *q;
                }
            }
            return 0;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "nested")

        # Find the addition operation
        additions = sg.get_operations_of_type(OperationType.ADDITION)
        assert len(additions) == 1
        # Should have two guards
        assert len(additions[0].guards) == 2

    def test_pointer_deref_with_null_check_guard(self):
        """Test pointer dereference has null check as guard."""
        code = """
        void process(int* ptr) {
            if (ptr != nullptr) {
                *ptr = *ptr + 1;
            }
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "process")

        derefs = [op for op in sg.get_pointer_operations()
                  if op.op_type == OperationType.POINTER_DEREF]
        assert len(derefs) >= 1
        for deref in derefs:
            assert len(deref.guards) >= 1
            # Guard should contain the null check
            guard_text = " ".join(deref.guards)
            assert "ptr" in guard_text and "nullptr" in guard_text


class TestFunctionCalls:
    """Tests for function call extraction."""

    def test_extracts_function_call(self):
        """Test function call extraction."""
        code = """
        int wrapper(int x) {
            return printf("%d", x);
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "wrapper")

        calls = sg.get_function_calls()
        assert len(calls) == 1
        assert calls[0].function_called == "printf"
        assert len(calls[0].call_arguments) == 2

    def test_extracts_method_call(self):
        """Test method call extraction."""
        code = """
        class Foo { public: int bar(); };
        int test(Foo* f) {
            return f->bar();
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "test")

        calls = sg.get_function_calls()
        assert len(calls) == 1

    def test_extracts_multiple_calls(self):
        """Test multiple function calls extraction."""
        code = """
        int multi() {
            int a = foo();
            int b = bar();
            int c = baz();
            return a + b + c;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "multi")

        calls = sg.get_function_calls()
        assert len(calls) == 3
        called = {c.function_called for c in calls}
        assert called == {"foo", "bar", "baz"}


class TestCppSpecificOperations:
    """Tests for C++ specific operations."""

    def test_extracts_new_expression(self):
        """Test new expression extraction."""
        code = """
        int* alloc() {
            return new int(42);
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "alloc")

        ops = sg.get_memory_operations()
        new_ops = [op for op in ops if op.op_type == OperationType.NEW]
        assert len(new_ops) == 1

    def test_extracts_delete_expression(self):
        """Test delete expression extraction."""
        code = """
        void dealloc(int* p) {
            delete p;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "dealloc")

        ops = sg.get_memory_operations()
        del_ops = [op for op in ops if op.op_type == OperationType.DELETE]
        assert len(del_ops) == 1

    def test_extracts_throw_statement(self):
        """Test throw statement extraction."""
        code = """
        void fail() {
            throw 42;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "fail")

        throws = sg.get_operations_of_type(OperationType.THROW)
        assert len(throws) == 1


class TestTypeOperations:
    """Tests for type-related operations."""

    def test_extracts_cast(self):
        """Test cast expression extraction."""
        code = """
        int cast(void* p) {
            return (int)(long)p;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "cast")

        casts = sg.get_operations_of_type(OperationType.CAST)
        assert len(casts) >= 1

    def test_extracts_sizeof(self):
        """Test sizeof expression extraction."""
        code = """
        int getsize() {
            return sizeof(int);
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "getsize")

        ops = sg.get_operations_of_type(OperationType.SIZEOF)
        assert len(ops) == 1


class TestTernaryOperations:
    """Tests for ternary expression extraction."""

    def test_extracts_ternary(self):
        """Test ternary expression extraction."""
        code = """
        int max(int a, int b) {
            return a > b ? a : b;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "max")

        ternaries = sg.get_operations_of_type(OperationType.TERNARY)
        assert len(ternaries) == 1
        assert ternaries[0].operator == "?:"
        assert len(ternaries[0].operands) == 3


class TestVariableDeclarations:
    """Tests for variable declaration extraction."""

    def test_extracts_declaration(self):
        """Test variable declaration extraction."""
        code = """
        void func() {
            int x = 5;
            int y = 10;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "func")

        decls = sg.get_operations_of_type(OperationType.VARIABLE_DECL)
        assert len(decls) == 2

    def test_declaration_captures_variable_name(self):
        """Test that declarations capture variable names."""
        code = """
        void func() {
            int counter = 0;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "func")

        decls = sg.get_operations_of_type(OperationType.VARIABLE_DECL)
        assert len(decls) == 1
        assert "counter" in decls[0].operands


class TestFunctionMetadata:
    """Tests for function metadata extraction."""

    def test_extracts_signature(self):
        """Test signature extraction."""
        code = "int add(int a, int b) { return a + b; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "add")

        assert "int add(int a, int b)" in sg.signature

    def test_extracts_void_return(self):
        """Test void return type extraction."""
        code = "void doNothing() { }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "doNothing")

        assert sg.return_type == "void"

    def test_extracts_pointer_parameter(self):
        """Test pointer parameter extraction."""
        code = "void process(int* data) { }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "process")

        assert len(sg.parameters) == 1
        name, type_ = sg.parameters[0]
        assert name == "data"
        assert "int" in type_

    def test_extracts_line_numbers(self):
        """Test line number extraction."""
        code = """
        int func() {
            return 42;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "func")

        assert sg.line_start > 0
        assert sg.line_end >= sg.line_start

    def test_tracks_entry_and_exit(self):
        """Test entry and exit point tracking."""
        code = """
        int decide(int x) {
            if (x > 0) {
                return 1;
            }
            return 0;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "decide")

        assert sg.entry_id is not None
        assert len(sg.exit_ids) == 2  # Two return statements


class TestSubgraphMethods:
    """Tests for FunctionSubgraph helper methods."""

    def test_get_node(self):
        """Test get_node method."""
        code = "int f() { return 1 + 2; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        first_node = sg.nodes[0]
        found = sg.get_node(first_node.id)
        assert found is not None
        assert found.id == first_node.id

    def test_get_node_returns_none_for_missing(self):
        """Test get_node returns None for missing ID."""
        code = "int f() { return 1; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        found = sg.get_node("nonexistent")
        assert found is None

    def test_get_all_operands(self):
        """Test get_all_operands method."""
        code = """
        int calc(int a, int b, int c) {
            return a + b * c;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "calc")

        operands = sg.get_all_operands()
        assert "a" in operands
        assert "b" in operands
        assert "c" in operands

    def test_get_nodes_with_guards(self):
        """Test get_nodes_with_guards method."""
        code = """
        int f(int x) {
            if (x > 0) {
                return x * 2;
            }
            return 0;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "f")

        guarded = sg.get_nodes_with_guards()
        assert len(guarded) >= 1

    def test_to_summary(self):
        """Test to_summary method."""
        code = """
        int divide(int x, int y) {
            if (y != 0) {
                return x / y;
            }
            return 0;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "divide")

        summary = sg.to_summary()
        assert summary["name"] == "divide"
        assert summary["has_divisions"] is True
        assert summary["total_operations"] > 0
        assert "operation_counts" in summary


class TestComplexExamples:
    """Tests with more complex, realistic code examples."""

    def test_malloc_pattern(self):
        """Test typical malloc usage pattern."""
        code = """
        int* allocate(int size) {
            int* ptr = (int*)malloc(size * sizeof(int));
            if (ptr == nullptr) {
                return nullptr;
            }
            for (int i = 0; i < size; i++) {
                ptr[i] = 0;
            }
            return ptr;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "allocate")

        # Should find malloc call
        calls = sg.get_function_calls()
        malloc_calls = [c for c in calls if c.function_called == "malloc"]
        assert len(malloc_calls) == 1

        # Should find array access
        arr_access = [op for op in sg.get_pointer_operations()
                      if op.op_type == OperationType.ARRAY_ACCESS]
        assert len(arr_access) >= 1

        # Should have loop
        assert sg.has_loops()

    def test_linked_list_traversal(self):
        """Test linked list traversal pattern."""
        code = """
        struct Node { int val; Node* next; };
        int sum_list(Node* head) {
            int sum = 0;
            while (head != nullptr) {
                sum += head->val;
                head = head->next;
            }
            return sum;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "sum_list")

        # Should have loop
        assert sg.has_loops()

        # Should have arrow access
        arrow_ops = [op for op in sg.get_pointer_operations()
                     if op.op_type == OperationType.ARROW_ACCESS]
        assert len(arrow_ops) >= 2

    def test_error_handling_pattern(self):
        """Test error handling with multiple returns."""
        code = """
        int process(int* data, int size) {
            if (data == nullptr) {
                return -1;
            }
            if (size <= 0) {
                return -2;
            }
            int sum = 0;
            for (int i = 0; i < size; i++) {
                sum += data[i];
            }
            return sum;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "process")

        # Should have multiple returns
        returns = sg.get_operations_of_type(OperationType.RETURN)
        assert len(returns) == 3

        # Should have multiple branches
        branches = sg.get_operations_of_type(OperationType.BRANCH)
        assert len(branches) == 2

        # Exit IDs should match returns
        assert len(sg.exit_ids) == 3


class TestCppAdvancedFeatures:
    """Tests for advanced C++ features."""

    def test_qualified_method_name(self):
        """Test method defined outside class with qualified name."""
        code = """
        class Foo {
        public:
            int getValue();
        };
        int Foo::getValue() {
            return 42;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "getValue")

        assert sg is not None
        assert sg.name == "getValue"
        assert sg.is_method is True
        assert sg.class_name == "Foo"

    def test_method_inside_class(self):
        """Test method defined inside class body."""
        code = """
        class Counter {
        public:
            int value;
            int get() {
                return value;
            }
        };
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "get")

        assert sg is not None
        assert sg.is_method is True
        assert sg.class_name == "Counter"

    def test_function_returning_pointer(self):
        """Test function that returns a pointer."""
        code = """
        int* getPointer(int* arr) {
            return arr;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "getPointer")

        assert sg is not None
        assert sg.name == "getPointer"

    def test_function_returning_reference(self):
        """Test function that returns a reference."""
        code = """
        int& getRef(int& x) {
            return x;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "getRef")

        assert sg is not None
        assert sg.name == "getRef"

    def test_do_while_loop(self):
        """Test do-while loop extraction."""
        code = """
        int countdown(int n) {
            do {
                n--;
            } while (n > 0);
            return n;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "countdown")

        loops = sg.get_operations_of_type(OperationType.LOOP)
        assert len(loops) == 1
        assert sg.has_loops()

    def test_namespace_qualified_function(self):
        """Test function in namespace."""
        code = """
        namespace myns {
            int helper() {
                return 1;
            }
        }
        """
        builder = SubgraphBuilder(language="cpp")
        # Tree-sitter should still find it
        subgraphs = builder.build_all(code)
        assert len(subgraphs) == 1
        assert subgraphs[0].name == "helper"

    def test_struct_method(self):
        """Test method inside struct."""
        code = """
        struct Point {
            int x, y;
            int sum() {
                return x + y;
            }
        };
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "sum")

        assert sg is not None
        assert sg.is_method is True
        assert sg.class_name == "Point"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_function(self):
        """Test empty function body."""
        code = "void empty() { }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "empty")

        assert sg is not None
        assert sg.name == "empty"
        assert len(sg.nodes) == 0

    def test_function_with_only_return(self):
        """Test function with only return statement."""
        code = "int get() { return 42; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "get")

        assert len(sg.nodes) == 1
        assert sg.nodes[0].op_type == OperationType.RETURN

    def test_deeply_nested_expression(self):
        """Test deeply nested expression parsing."""
        code = """
        int nested(int a, int b, int c, int d) {
            return ((a + b) * (c - d)) / ((a - b) + (c * d));
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "nested")

        # Should find division at the top level
        divs = sg.get_divisions()
        assert len(divs) >= 1

    def test_multiline_function(self):
        """Test function spanning many lines."""
        code = """
        int
        long_function_name
        (
            int parameter_one,
            int parameter_two
        )
        {
            return parameter_one + parameter_two;
        }
        """
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "long_function_name")

        assert sg is not None
        assert len(sg.parameters) == 2

    def test_unicode_in_strings(self):
        """Test code with unicode in strings doesn't crash."""
        code = '''
        void print_unicode() {
            printf("Hello \u4e16\u754c");
        }
        '''
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "print_unicode")

        assert sg is not None

    def test_no_parameters(self):
        """Test function with no parameters."""
        code = "int get_value() { return 42; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "get_value")

        assert sg.parameters == []

    def test_many_parameters(self):
        """Test function with many parameters."""
        code = "int many(int a, int b, int c, int d, int e) { return a; }"
        builder = SubgraphBuilder(language="cpp")
        sg = builder.build(code, "many")

        assert len(sg.parameters) == 5


class TestMacroExtraction:
    """Tests for macro extraction functionality."""

    def test_extracts_simple_object_macro(self):
        """Test extraction of simple object-like macro."""
        code = """
        #define MAX_SIZE 100
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert macros[0].name == "MAX_SIZE"
        assert macros[0].body == "100"
        assert macros[0].is_function_like is False
        assert len(macros[0].parameters) == 0

    def test_extracts_function_like_macro(self):
        """Test extraction of function-like macro."""
        code = """
        #define ADD(a, b) ((a) + (b))
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert macros[0].name == "ADD"
        assert macros[0].is_function_like is True
        assert macros[0].parameters == ["a", "b"]
        assert "+" in macros[0].body

    def test_extracts_multiple_macros(self):
        """Test extraction of multiple macros."""
        code = """
        #define PI 3.14159
        #define DOUBLE(x) ((x) * 2)
        #define MAX(a, b) ((a) > (b) ? (a) : (b))
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 3
        names = {m.name for m in macros}
        assert names == {"PI", "DOUBLE", "MAX"}

    def test_detects_division_in_macro(self):
        """Test detection of division in macro body."""
        code = """
        #define DIV(a, b) ((a) / (b))
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert macros[0].has_division is True

    def test_detects_modulo_in_macro(self):
        """Test detection of modulo in macro body."""
        code = """
        #define MOD(a, b) ((a) % (b))
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert macros[0].has_division is True

    def test_detects_pointer_ops_in_macro(self):
        """Test detection of pointer operations in macro body."""
        code = """
        #define DEREF(p) (*p)
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert macros[0].has_pointer_ops is True

    def test_detects_casts_in_macro(self):
        """Test detection of casts in macro body."""
        code = """
        #define TO_INT(x) ((int)(x))
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert macros[0].has_casts is True

    def test_detects_function_calls_in_macro(self):
        """Test detection of function calls in macro body."""
        code = """
        #define SAFE_FREE(p) do { free(p); p = NULL; } while(0)
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert "free" in macros[0].function_calls

    def test_detects_referenced_macros(self):
        """Test detection of referenced macros in body."""
        code = """
        #define USE_LIMIT(x) ((x) < MAX_VALUE ? (x) : MAX_VALUE)
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert "MAX_VALUE" in macros[0].referenced_macros

    def test_has_hazardous_macro_with_division(self):
        """Test has_hazardous_macro returns True for division."""
        code = """
        #define DIV(a, b) ((a) / (b))
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert builder.has_hazardous_macro(macros[0]) is True

    def test_has_hazardous_macro_false_for_simple(self):
        """Test has_hazardous_macro returns False for simple macro."""
        code = """
        #define VERSION 1
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert builder.has_hazardous_macro(macros[0]) is False

    def test_macro_line_numbers(self):
        """Test that macro line numbers are captured."""
        code = """
        // Comment
        #define FIRST 1
        // Another comment
        #define SECOND 2
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 2
        # Line numbers should be different
        lines = {m.line_start for m in macros}
        assert len(lines) == 2

    def test_macro_file_path(self):
        """Test that file path is stored in macro."""
        code = "#define TEST 1"
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "/path/to/header.h")

        assert len(macros) == 1
        assert macros[0].file_path == "/path/to/header.h"

    def test_macro_signature(self):
        """Test macro signature generation."""
        code = """
        #define SIMPLE 42
        #define FUNC(x, y, z) ((x) + (y) + (z))
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        by_name = {m.name: m for m in macros}

        assert by_name["SIMPLE"].to_signature() == "SIMPLE"
        assert by_name["FUNC"].to_signature() == "FUNC(x, y, z)"

    def test_macro_summary(self):
        """Test macro summary generation."""
        code = """
        #define DIV(a, b) ((a) / (b))
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        summary = macros[0].to_summary()
        assert summary["name"] == "DIV"
        assert summary["is_function_like"] is True
        assert summary["has_division"] is True

    def test_empty_macro_body(self):
        """Test macro with empty body."""
        code = """
        #define EMPTY
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert macros[0].name == "EMPTY"
        assert macros[0].body == ""

    def test_c_language_macros(self):
        """Test macro extraction works with C language."""
        code = """
        #define BUFFER_SIZE 1024
        #define SQUARE(x) ((x) * (x))
        """
        builder = SubgraphBuilder(language="c")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 2

    def test_real_world_macro_patterns(self):
        """Test extraction of real-world macro patterns."""
        code = """
        #define MIN(a, b) ((a) < (b) ? (a) : (b))
        #define MAX(a, b) ((a) > (b) ? (a) : (b))
        #define ABS(x) ((x) < 0 ? -(x) : (x))
        #define ARRAY_SIZE(arr) (sizeof(arr) / sizeof((arr)[0]))
        #define UNUSED(x) (void)(x)
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 5

        by_name = {m.name: m for m in macros}

        # MIN and MAX should not have division (ternary, not division)
        assert by_name["MIN"].has_division is False
        assert by_name["MAX"].has_division is False

        # ABS should not have division
        assert by_name["ABS"].has_division is False

        # ARRAY_SIZE has division
        assert by_name["ARRAY_SIZE"].has_division is True

    def test_macro_with_function_calls_multiple(self):
        """Test macro with multiple function calls."""
        code = """
        #define LOG_AND_RETURN(msg, val) do { printf("%s", msg); return val; } while(0)
        """
        builder = SubgraphBuilder(language="cpp")
        macros = builder.extract_macros(code, "test.h")

        assert len(macros) == 1
        assert "printf" in macros[0].function_calls
