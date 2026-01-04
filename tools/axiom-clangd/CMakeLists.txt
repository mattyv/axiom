cmake_minimum_required(VERSION 3.20)
project(axiom-clangd VERSION 0.1.0 LANGUAGES C CXX)

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
    src/AxiomPlugin.cpp
    src/QueryClient.cpp
    src/DiagnosticEmitter.cpp
    src/HoverProvider.cpp
)

# Shared library (clangd plugin)
add_library(axiom-clangd SHARED ${SOURCES})

target_include_directories(axiom-clangd PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

# Link Clang libraries
target_link_libraries(axiom-clangd PRIVATE
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
install(TARGETS axiom-clangd
    LIBRARY DESTINATION lib
)
