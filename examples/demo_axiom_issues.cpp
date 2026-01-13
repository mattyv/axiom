// Axiom LSP Demo File
// Copyright (c) 2026 Matt Varendorff
// SPDX-License-Identifier: BSL-1.0
//
// This file contains intentional issues that Axiom can detect.
// Use this to test the LSP integration.

#include <cstdlib>
#include <cstring>
#include <memory>
#include <optional>
#include <string>
#include <vector>

// =============================================================================
// Issue 1: Division without zero check
// Axiom: PRECONDITION - divisor must not be zero
// =============================================================================

int divide(int a, int b) {
    // BUG: No check for b == 0
    // Axiom should warn: "Division without zero check"
    return a / b;
}

double calculate_average(const std::vector<int>& values) {
    int sum = 0;
    for (int v : values) {
        sum += v;
    }
    // BUG: values.size() could be 0
    // Axiom should warn: "Division without zero check"
    return static_cast<double>(sum) / values.size();
}

// =============================================================================
// Issue 2: Pointer dereference without null check
// Axiom: PRECONDITION - pointer must not be null
// =============================================================================

void process_data(int* data, size_t len) {
    // BUG: No null check for data
    // Axiom should warn: "Pointer dereference without null check"
    for (size_t i = 0; i < len; ++i) {
        data[i] *= 2;
    }
}

int get_value(const int* ptr) {
    // BUG: No null check
    // Axiom should warn: "Pointer dereference without null check"
    return *ptr;
}

// =============================================================================
// Issue 3: Memory allocation without free (unpaired functions)
// Axiom: PAIRS_WITH - malloc must pair with free
// =============================================================================

char* create_buffer(size_t size) {
    // Axiom should note: "malloc pairs with free"
    char* buf = static_cast<char*>(malloc(size));
    if (buf) {
        memset(buf, 0, size);
    }
    return buf;
    // NOTE: Caller must free() - Axiom tracks this pairing
}

void leaky_function() {
    // BUG: malloc without corresponding free
    // Axiom should warn about unpaired allocation
    char* data = static_cast<char*>(malloc(100));
    if (data) {
        strcpy(data, "Hello, World!");
        // Missing: free(data);
    }
}

// =============================================================================
// Issue 4: Ignoring [[nodiscard]] return value
// Axiom: POSTCONDITION - return value must not be ignored
// =============================================================================

[[nodiscard]] bool validate_input(const std::string& input) {
    return !input.empty() && input.size() < 1000;
}

void process_input(const std::string& input) {
    // BUG: Ignoring nodiscard return
    // Axiom should warn: "Return value must not be discarded"
    validate_input(input);

    // ... process input
}

// =============================================================================
// Issue 5: Using deprecated function
// Axiom: ANTI_PATTERN - deprecated function should not be used
// =============================================================================

[[deprecated("Use modern_api() instead")]]
void legacy_api() {
    // Old implementation
}

void caller() {
    // BUG: Using deprecated function
    // Axiom should warn: "Deprecated function"
    legacy_api();
}

// =============================================================================
// Issue 6: Exception safety - noexcept function calling throwing function
// Axiom: EXCEPTION - noexcept function must not call throwing functions
// =============================================================================

void might_throw() {
    throw std::runtime_error("oops");
}

void safe_function() noexcept {
    // BUG: Calling throwing function from noexcept
    // Axiom should warn: "noexcept function calls throwing function"
    // might_throw();  // Uncomment to trigger
}

// =============================================================================
// Issue 7: Integer overflow potential
// Axiom: PRECONDITION - arithmetic operations may overflow
// =============================================================================

int multiply(int a, int b) {
    // Potential overflow not checked
    // Axiom should note: "Integer multiplication may overflow"
    return a * b;
}

size_t calculate_size(size_t count, size_t element_size) {
    // Potential overflow in size calculation
    // Axiom should note: "Size multiplication may overflow"
    return count * element_size;
}

// =============================================================================
// Issue 8: std::optional access without check
// Axiom: PRECONDITION - optional must have value before access
// =============================================================================

std::optional<int> find_value(const std::vector<int>& vec, int target) {
    for (int v : vec) {
        if (v == target) return v;
    }
    return std::nullopt;
}

void use_optional(const std::vector<int>& vec) {
    auto result = find_value(vec, 42);
    // BUG: Accessing optional without checking has_value()
    // Axiom should warn: "Optional access without value check"
    int value = *result;  // Undefined if nullopt!
    (void)value;
}

// =============================================================================
// Issue 9: Container modification during iteration
// Axiom: ANTI_PATTERN - modifying container invalidates iterators
// =============================================================================

void remove_evens(std::vector<int>& vec) {
    // BUG: Modifying vector while iterating
    // Axiom should warn: "Container modification during iteration"
    for (auto it = vec.begin(); it != vec.end(); ++it) {
        if (*it % 2 == 0) {
            vec.erase(it);  // Iterator invalidated!
        }
    }
}

// =============================================================================
// Correct examples (for contrast)
// =============================================================================

int divide_safe(int a, int b) {
    // GOOD: Zero check before division
    if (b == 0) {
        return 0;  // Or throw, or return optional
    }
    return a / b;
}

void process_data_safe(int* data, size_t len) {
    // GOOD: Null check before use
    if (data == nullptr) {
        return;
    }
    for (size_t i = 0; i < len; ++i) {
        data[i] *= 2;
    }
}

void use_optional_safe(const std::vector<int>& vec) {
    auto result = find_value(vec, 42);
    // GOOD: Check before access
    if (result.has_value()) {
        int value = *result;
        (void)value;
    }
}

// =============================================================================
// Main for compilation check
// =============================================================================

int main() {
    // Test the functions
    int x = divide(10, 2);
    (void)x;

    std::vector<int> nums = {1, 2, 3, 4, 5};
    double avg = calculate_average(nums);
    (void)avg;

    return 0;
}
