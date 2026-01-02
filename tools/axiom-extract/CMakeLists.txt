cmake_minimum_required(VERSION 3.20)
project(axiom-extract VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Find LLVM and Clang
find_package(LLVM REQUIRED CONFIG)
find_package(Clang REQUIRED CONFIG)

message(STATUS "Found LLVM ${LLVM_PACKAGE_VERSION}")
message(STATUS "Using LLVMConfig.cmake in: ${LLVM_DIR}")
message(STATUS "Found Clang in: ${Clang_DIR}")

# Add LLVM definitions and include directories
add_definitions(${LLVM_DEFINITIONS})
include_directories(${LLVM_INCLUDE_DIRS})
include_directories(${CLANG_INCLUDE_DIRS})

# Link directories
link_directories(${LLVM_LIBRARY_DIRS})

# Find nlohmann_json (header-only)
find_package(nlohmann_json 3.11 QUIET)
if(NOT nlohmann_json_FOUND)
    message(STATUS "nlohmann_json not found, fetching...")
    include(FetchContent)
    FetchContent_Declare(
        json
        URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
    )
    FetchContent_MakeAvailable(json)
endif()

# Source files
set(SOURCES
    src/main.cpp
    src/FunctionExtractor.cpp
    src/ConstraintExtractor.cpp
    src/HazardDetector.cpp
    src/GuardAnalyzer.cpp
    src/CallGraphExtractor.cpp
    src/JsonEmitter.cpp
    src/MacroExtractor.cpp
)

# Main executable
add_executable(axiom-extract ${SOURCES})

target_include_directories(axiom-extract PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

# Link Clang libraries
target_link_libraries(axiom-extract PRIVATE
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

# Install
install(TARGETS axiom-extract
    RUNTIME DESTINATION bin
)

# Testing (optional)
option(BUILD_TESTING "Build tests" OFF)
if(BUILD_TESTING)
    enable_testing()
    find_package(GTest QUIET)
    if(GTest_FOUND)
        add_subdirectory(tests)
    endif()
endif()
