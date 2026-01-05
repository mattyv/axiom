// C++20 Language Showcase for Axiom LSP
// Copyright (c) 2026 Matt Varendorff
// SPDX-License-Identifier: BSL-1.0
//
// This file demonstrates all C++ language constructs that Axiom can
// extract and display axioms for. Each section shows a category of
// language features with examples.

#include <algorithm>
#include <array>
#include <concepts>
#include <coroutine>
#include <expected>
#include <format>
#include <functional>
#include <iterator>
#include <map>
#include <memory>
#include <optional>
#include <ranges>
#include <set>
#include <span>
#include <string>
#include <string_view>
#include <tuple>
#include <type_traits>
#include <unordered_map>
#include <variant>
#include <vector>

// =============================================================================
// SECTION 1: Arithmetic Operators
// Tags: addition, subtraction, multiplication, division, modulus
// =============================================================================

int arithmetic_operators(int a, int b) {
    int sum = a + b;           // operator+
    int diff = a - b;          // operator-
    int prod = a * b;          // operator*
    int quot = a / b;          // operator/ (division by zero axiom)
    int rem = a % b;           // operator% (modulus axiom)
    return sum + diff + prod + quot + rem;
}

// =============================================================================
// SECTION 2: Compound Assignment Operators
// Tags: compound-assignment, assignment
// =============================================================================

void compound_assignment(int& x, int y) {
    x += y;    // operator+=
    x -= y;    // operator-=
    x *= y;    // operator*=
    x /= y;    // operator/= (division axiom)
    x %= y;    // operator%=
    x &= y;    // operator&=
    x |= y;    // operator|=
    x ^= y;    // operator^=
    x <<= 1;   // operator<<=
    x >>= 1;   // operator>>=
}

// =============================================================================
// SECTION 3: Increment/Decrement Operators
// Tags: increment, decrement
// =============================================================================

void increment_decrement(int& x) {
    ++x;       // operator++ (prefix)
    x++;       // operator++(int) (postfix)
    --x;       // operator-- (prefix)
    x--;       // operator--(int) (postfix)
}

// =============================================================================
// SECTION 4: Comparison Operators
// Tags: comparison, equality, three-way
// =============================================================================

bool comparison_operators(int a, int b) {
    bool lt = a < b;           // operator<
    bool gt = a > b;           // operator>
    bool le = a <= b;          // operator<=
    bool ge = a >= b;          // operator>=
    bool eq = a == b;          // operator==
    bool ne = a != b;          // operator!=
    auto cmp = a <=> b;        // operator<=> (C++20 spaceship)
    return lt && gt && le && ge && eq && ne && (cmp == 0);
}

// =============================================================================
// SECTION 5: Logical Operators
// Tags: boolean
// =============================================================================

bool logical_operators(bool a, bool b) {
    bool and_result = a && b;  // operator&&
    bool or_result = a || b;   // operator||
    bool not_result = !a;      // operator!
    return and_result || or_result || not_result;
}

// =============================================================================
// SECTION 6: Bitwise Operators
// Tags: bitwise, shift
// =============================================================================

int bitwise_operators(int a, int b) {
    int and_bits = a & b;      // operator&
    int or_bits = a | b;       // operator|
    int xor_bits = a ^ b;      // operator^
    int not_bits = ~a;         // operator~
    int left = a << 2;         // operator<<
    int right = a >> 2;        // operator>>
    return and_bits | or_bits | xor_bits | not_bits | left | right;
}

// =============================================================================
// SECTION 7: Pointer and Reference Operators
// Tags: pointer, dereference, address-of, subscript
// =============================================================================

void pointer_operators(int* ptr, int arr[], size_t idx) {
    int val = *ptr;            // operator* (dereference)
    int* addr = &val;          // operator& (address-of)
    int elem = arr[idx];       // operator[] (subscript/bounds)
    (void)val; (void)addr; (void)elem;
}

// =============================================================================
// SECTION 8: Member Access Operators
// Tags: member-access
// =============================================================================

struct Point { int x, y; };

void member_access(Point p, Point* pp) {
    int a = p.x;               // operator.
    int b = pp->y;             // operator->
    (void)a; (void)b;
}

// =============================================================================
// SECTION 9: Type Casts
// Tags: cast, static_cast, dynamic_cast, const_cast, reinterpret_cast
// =============================================================================

class Base { public: virtual ~Base() = default; };
class Derived : public Base {};

void casts(Base* base, const int* cptr, void* vptr) {
    // Named casts
    Derived* d = static_cast<Derived*>(base);           // static_cast
    Derived* dd = dynamic_cast<Derived*>(base);         // dynamic_cast
    int* mptr = const_cast<int*>(cptr);                 // const_cast
    int* iptr = reinterpret_cast<int*>(vptr);           // reinterpret_cast

    // C-style cast
    int x = (int)3.14;                                  // c_style_cast

    (void)d; (void)dd; (void)mptr; (void)iptr; (void)x;
}

// =============================================================================
// SECTION 10: Memory Operators
// Tags: new, delete, allocation, deallocation
// =============================================================================

void memory_operators() {
    int* p = new int(42);              // operator new
    delete p;                          // operator delete

    int* arr = new int[10];            // operator new[]
    delete[] arr;                      // operator delete[]
}

// =============================================================================
// SECTION 11: sizeof, alignof, typeid
// Tags: sizeof, alignof, typeid
// =============================================================================

void type_info_operators() {
    size_t s1 = sizeof(int);           // sizeof
    size_t s2 = sizeof(Point);         // sizeof
    size_t a1 = alignof(int);          // alignof
    size_t a2 = alignof(Point);        // alignof

    Base b;
    auto& ti = typeid(b);              // typeid
    (void)s1; (void)s2; (void)a1; (void)a2; (void)ti;
}

// =============================================================================
// SECTION 12: Ternary Operator
// Tags: conditional
// =============================================================================

int ternary_operator(bool cond, int a, int b) {
    return cond ? a : b;               // operator?:
}

// =============================================================================
// SECTION 13: Range-based For Loop
// Tags: range, iterator, begin, end
// =============================================================================

int range_for_loop(const std::vector<int>& vec) {
    int sum = 0;
    for (int val : vec) {              // range_for
        sum += val;
    }
    return sum;
}

// =============================================================================
// SECTION 14: Return Statement
// Tags: return, postcondition
// =============================================================================

int return_statement(int x) {
    if (x < 0) {
        return -1;                     // return
    }
    return x * 2;                      // return
}

// =============================================================================
// SECTION 15: Lambda Expressions
// Tags: lambda, capture
// =============================================================================

void lambda_expressions() {
    int x = 10;

    auto by_value = [=]() { return x; };           // lambda[=]
    auto by_ref = [&]() { return x; };             // lambda[&]
    auto explicit_cap = [x]() { return x; };       // lambda[]
    auto generic = [](auto a) { return a; };       // lambda[]

    (void)by_value; (void)by_ref; (void)explicit_cap; (void)generic;
}

// =============================================================================
// SECTION 16: Exception Handling
// Tags: throw, exception
// =============================================================================

void exception_handling(bool error) {
    if (error) {
        throw std::runtime_error("Error occurred");  // throw
    }
}

// =============================================================================
// SECTION 17: noexcept Operator
// Tags: noexcept, exception
// =============================================================================

void noexcept_operator() {
    bool is_noexcept = noexcept(1 + 2);           // noexcept
    (void)is_noexcept;
}

// =============================================================================
// SECTION 18: Initializer Lists
// Tags: initialization, initializer_list
// =============================================================================

void initializer_lists() {
    std::vector<int> v1 = {1, 2, 3, 4, 5};        // braced_init_list
    std::array<int, 3> a1 = {1, 2, 3};            // braced_init_list
    Point p = {10, 20};                            // braced_init_list
    (void)v1; (void)a1; (void)p;
}

// =============================================================================
// SECTION 19: nullptr
// Tags: nullptr, null, null_pointer
// =============================================================================

void nullptr_usage() {
    int* p = nullptr;                              // nullptr
    if (p == nullptr) {                            // nullptr
        // null check
    }
}

// =============================================================================
// SECTION 20: Structured Bindings (C++17)
// Tags: binding, structured_binding
// =============================================================================

void structured_bindings() {
    std::pair<int, std::string> p{42, "hello"};
    auto [num, str] = p;                           // structured_binding

    std::tuple<int, double, char> t{1, 2.0, 'c'};
    auto [a, b, c] = t;                            // structured_binding

    int arr[3] = {1, 2, 3};
    auto [x, y, z] = arr;                          // structured_binding

    (void)num; (void)str; (void)a; (void)b; (void)c; (void)x; (void)y; (void)z;
}

// =============================================================================
// SECTION 21: static_assert
// Tags: static_assert, constexpr
// =============================================================================

static_assert(sizeof(int) >= 4, "int must be at least 4 bytes");
static_assert(sizeof(void*) == 8);  // C++17 no message

template<typename T>
void static_assert_in_function() {
    static_assert(std::is_integral_v<T>, "T must be integral");
}

// =============================================================================
// SECTION 22: if constexpr (C++17)
// Tags: constexpr, constant_expression
// =============================================================================

template<typename T>
auto if_constexpr_example(T value) {
    if constexpr (std::is_integral_v<T>) {         // if_constexpr
        return value * 2;
    } else if constexpr (std::is_floating_point_v<T>) {  // if_constexpr
        return value * 2.0;
    } else {
        return value;
    }
}

// =============================================================================
// SECTION 23: Concepts (C++20)
// Tags: concepts, requires
// =============================================================================

template<typename T>
concept Numeric = std::integral<T> || std::floating_point<T>;

template<typename T>
concept Addable = requires(T a, T b) {             // requires
    { a + b } -> std::same_as<T>;
};

template<Numeric T>
T add_numeric(T a, T b) {
    return a + b;
}

template<typename T>
    requires Addable<T>                            // requires
T add_constrained(T a, T b) {
    return a + b;
}

// =============================================================================
// SECTION 24: Coroutines (C++20)
// Tags: coroutine, await, co_await, co_yield, co_return
// =============================================================================

// Simple coroutine promise type
struct Task {
    struct promise_type {
        Task get_return_object() { return {}; }
        std::suspend_never initial_suspend() { return {}; }
        std::suspend_never final_suspend() noexcept { return {}; }
        void return_void() {}
        void unhandled_exception() {}
    };
};

struct Generator {
    struct promise_type {
        int current_value;
        Generator get_return_object() {
            return Generator{std::coroutine_handle<promise_type>::from_promise(*this)};
        }
        std::suspend_always initial_suspend() { return {}; }
        std::suspend_always final_suspend() noexcept { return {}; }
        std::suspend_always yield_value(int value) {
            current_value = value;
            return {};
        }
        void return_void() {}
        void unhandled_exception() {}
    };

    std::coroutine_handle<promise_type> handle;
};

Generator generate_numbers() {
    co_yield 1;                                    // co_yield
    co_yield 2;                                    // co_yield
    co_yield 3;                                    // co_yield
    co_return;                                     // co_return
}

// =============================================================================
// SECTION 25: STL Containers
// Tags: container, sequence-container, associative-container
// =============================================================================

void stl_containers() {
    // Sequence containers
    std::vector<int> vec{1, 2, 3};
    std::array<int, 3> arr{1, 2, 3};
    std::string str = "hello";

    // Associative containers
    std::map<std::string, int> map{{"a", 1}};
    std::set<int> set{1, 2, 3};
    std::unordered_map<std::string, int> umap{{"b", 2}};

    // Container operations
    vec.push_back(4);                              // ::push_back
    vec.pop_back();                                // ::pop_back
    vec.emplace_back(5);                           // ::emplace_back
    auto it = vec.begin();                         // ::begin
    auto end = vec.end();                          // ::end
    size_t sz = vec.size();                        // ::size
    bool empty = vec.empty();                      // ::empty
    int& front = vec.front();                      // ::front
    int& back = vec.back();                        // ::back
    int& at = vec.at(0);                           // ::at (bounds check)
    vec.clear();                                   // ::clear

    (void)it; (void)end; (void)sz; (void)empty;
    (void)front; (void)back; (void)at;
    (void)arr; (void)str; (void)map; (void)set; (void)umap;
}

// =============================================================================
// SECTION 26: Smart Pointers
// Tags: smart_pointer, unique_ptr, shared_ptr, weak_ptr
// =============================================================================

void smart_pointers() {
    // unique_ptr
    auto uptr = std::make_unique<int>(42);
    int* raw = uptr.get();                         // ::get
    uptr.reset();                                  // ::reset
    uptr.reset(new int(10));
    int* released = uptr.release();                // ::release
    delete released;

    // shared_ptr
    auto sptr = std::make_shared<int>(42);
    long count = sptr.use_count();                 // ::use_count
    sptr.reset();                                  // ::reset

    // weak_ptr
    std::weak_ptr<int> wptr = sptr;
    auto locked = wptr.lock();                     // ::lock
    bool expired = wptr.expired();                 // ::expired

    (void)raw; (void)count; (void)locked; (void)expired;
}

// =============================================================================
// SECTION 27: std::optional
// Tags: optional, value, value_or, has_value
// =============================================================================

void optional_operations() {
    std::optional<int> opt = 42;

    bool has = opt.has_value();                    // ::has_value
    int val = opt.value();                         // ::value (may throw)
    int or_val = opt.value_or(-1);                 // ::value_or
    int deref = *opt;                              // operator*
    opt.reset();                                   // ::reset
    opt.emplace(100);                              // ::emplace

    (void)has; (void)val; (void)or_val; (void)deref;
}

// =============================================================================
// SECTION 28: std::variant
// Tags: variant
// =============================================================================

void variant_operations() {
    std::variant<int, std::string> v = 42;

    bool holds = std::holds_alternative<int>(v);
    int* ptr = std::get_if<int>(&v);
    int val = std::get<int>(v);                    // std::get (may throw)

    std::visit([](auto&& arg) { (void)arg; }, v);  // std::visit

    (void)holds; (void)ptr; (void)val;
}

// =============================================================================
// SECTION 29: std::tuple
// Tags: tuple, get
// =============================================================================

void tuple_operations() {
    std::tuple<int, double, std::string> t{1, 2.0, "three"};

    int first = std::get<0>(t);                    // std::get
    double second = std::get<1>(t);                // std::get
    auto size = std::tuple_size_v<decltype(t)>;

    auto made = std::make_tuple(1, 2, 3);
    auto tied = std::tie(first, second);

    (void)first; (void)second; (void)size; (void)made; (void)tied;
}

// =============================================================================
// SECTION 30: std::span (C++20)
// Tags: span
// =============================================================================

void span_operations(std::span<int> s) {
    size_t sz = s.size();                          // ::size
    bool empty = s.empty();                        // ::empty
    int* data = s.data();                          // ::data
    int first = s.front();                         // ::front
    int last = s.back();                           // ::back
    auto sub = s.subspan(1, 2);                    // ::subspan

    (void)sz; (void)empty; (void)data; (void)first; (void)last; (void)sub;
}

// =============================================================================
// SECTION 31: std::ranges (C++20)
// Tags: range, algorithm
// =============================================================================

void ranges_operations(std::vector<int>& vec) {
    // Range algorithms
    std::ranges::sort(vec);
    auto it = std::ranges::find(vec, 42);
    bool has = std::ranges::contains(vec, 42);
    auto [min, max] = std::ranges::minmax(vec);

    // Range views (lazy evaluation)
    auto filtered = vec | std::views::filter([](int x) { return x > 0; });
    auto transformed = vec | std::views::transform([](int x) { return x * 2; });
    auto taken = vec | std::views::take(5);

    (void)it; (void)has; (void)min; (void)max;
    (void)filtered; (void)transformed; (void)taken;
}

// =============================================================================
// SECTION 32: std::format (C++20)
// Tags: format
// =============================================================================

std::string format_operations() {
    std::string s1 = std::format("Hello, {}!", "World");
    std::string s2 = std::format("Value: {0}, hex: {0:#x}", 255);
    std::string s3 = std::format("{:.2f}", 3.14159);
    return s1 + s2 + s3;
}

// =============================================================================
// SECTION 33: std::expected (C++23, but commonly available)
// Tags: expected
// =============================================================================

#if __cpp_lib_expected >= 202202L
std::expected<int, std::string> expected_operations(int x) {
    if (x < 0) {
        return std::unexpected("negative value");
    }
    return x * 2;
}
#endif

// =============================================================================
// SECTION 34: Concurrency Types
// Tags: atomic, mutex, thread, lock, condition_variable
// =============================================================================

#include <atomic>
#include <mutex>
#include <thread>
#include <condition_variable>

void concurrency_types() {
    // Atomic types
    std::atomic<int> counter{0};
    counter.store(42);
    int val = counter.load();
    counter.fetch_add(1);
    bool exchanged = counter.compare_exchange_strong(val, 100);

    // Mutex and locks
    std::mutex mtx;
    {
        std::lock_guard<std::mutex> lock(mtx);
        // critical section
    }
    {
        std::unique_lock<std::mutex> ulock(mtx);
        // can unlock/relock
    }

    // Condition variable
    std::condition_variable cv;
    bool ready = false;

    (void)val; (void)exchanged; (void)ready; (void)cv;
}

// Thread creation (declaration only to avoid actual thread spawn)
void thread_example() {
    auto task = []() { /* work */ };
    // std::thread t(task);  // Would spawn thread
    // t.join();

    // std::jthread (C++20) - auto-joining
    // std::jthread jt(task);

    (void)task;
}

// =============================================================================
// SECTION 35: Built-in Type Declarations
// Tags: int, bool, float, pointer, reference, array, enum
// =============================================================================

enum class Color { Red, Green, Blue };

void builtin_types() {
    // Integer types
    int i = 42;
    short s = 10;
    long l = 100000L;
    long long ll = 1000000000LL;

    // Unsigned variants
    unsigned int ui = 42u;
    unsigned long ul = 100000UL;
    size_t sz = 100;

    // Floating point
    float f = 3.14f;
    double d = 3.14159;
    long double ld = 3.14159265358979L;

    // Character types
    char c = 'A';
    bool b = true;

    // Pointer and reference
    int* ptr = &i;
    int& ref = i;

    // Array
    int arr[10];

    // Enum
    Color color = Color::Red;

    // Fixed-width integers
    int32_t i32 = 42;
    uint64_t u64 = 100;

    (void)i; (void)s; (void)l; (void)ll;
    (void)ui; (void)ul; (void)sz;
    (void)f; (void)d; (void)ld;
    (void)c; (void)b;
    (void)ptr; (void)ref; (void)arr;
    (void)color; (void)i32; (void)u64;
}

// =============================================================================
// MAIN
// =============================================================================

int main() {
    // Quick smoke test of various features
    arithmetic_operators(10, 3);
    comparison_operators(5, 5);
    logical_operators(true, false);

    std::vector<int> nums{1, 2, 3, 4, 5};
    range_for_loop(nums);

    stl_containers();
    smart_pointers();
    optional_operations();

    structured_bindings();

    // Concepts
    add_numeric(1, 2);
    add_numeric(1.0, 2.0);

    // if constexpr
    if_constexpr_example(42);
    if_constexpr_example(3.14);

    return 0;
}
