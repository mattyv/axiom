# Axiom - Grounded truth validation for LLMs
# Copyright (c) 2025 Matt Varendorff
# https://github.com/mattyv/axiom
# SPDX-License-Identifier: BSL-1.0

# GoogleTest integration
include(FetchContent)
FetchContent_Declare(
    googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.14.0.zip
)
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)

enable_testing()

# Test executable
add_executable(axiom-extract-tests
    test_constraint_extractor.cpp
    test_hazard_detector.cpp
    test_signature_builder.cpp
    test_effect_detector.cpp
    test_macro_extractor.cpp
    ${CMAKE_SOURCE_DIR}/src/SignatureBuilder.cpp
    ${CMAKE_SOURCE_DIR}/src/ConstraintExtractor.cpp
    ${CMAKE_SOURCE_DIR}/src/HazardDetector.cpp
    ${CMAKE_SOURCE_DIR}/src/GuardAnalyzer.cpp
    ${CMAKE_SOURCE_DIR}/src/EffectDetector.cpp
    ${CMAKE_SOURCE_DIR}/src/MacroExtractor.cpp
)

target_include_directories(axiom-extract-tests PRIVATE
    ${CMAKE_SOURCE_DIR}/include
)

# Find clang resource dir for builtin headers
execute_process(
    COMMAND ${LLVM_TOOLS_BINARY_DIR}/clang -print-resource-dir
    OUTPUT_VARIABLE CLANG_RESOURCE_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

# Find libc++ include path
get_filename_component(LLVM_INSTALL_PREFIX "${LLVM_TOOLS_BINARY_DIR}" DIRECTORY)
set(LIBCXX_INCLUDE_DIR "${LLVM_INSTALL_PREFIX}/include/c++/v1")

# Find system SDK include path (platform-specific)
if(APPLE)
    execute_process(
        COMMAND xcrun --show-sdk-path
        OUTPUT_VARIABLE SDK_PATH
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
    set(SYSTEM_INCLUDE_DIR "${SDK_PATH}/usr/include")
else()
    set(SYSTEM_INCLUDE_DIR "/usr/include")
endif()

# Pass include paths to tests as compile definitions
target_compile_definitions(axiom-extract-tests PRIVATE
    CLANG_RESOURCE_DIR="${CLANG_RESOURCE_DIR}"
    LIBCXX_INCLUDE_DIR="${LIBCXX_INCLUDE_DIR}"
    SYSTEM_INCLUDE_DIR="${SYSTEM_INCLUDE_DIR}"
)

target_link_libraries(axiom-extract-tests PRIVATE
    GTest::gtest_main
    GTest::gmock
    clangTooling
    clangASTMatchers
    clangFrontend
    clangSerialization
    clangDriver
    clangParse
    clangSema
    clangAnalysis
    clangAST
    clangBasic
    clangEdit
    clangLex
    clangRewrite
    LLVMSupport
    nlohmann_json::nlohmann_json
)

include(GoogleTest)
gtest_discover_tests(axiom-extract-tests)
