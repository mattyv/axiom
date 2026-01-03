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
