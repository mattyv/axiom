#!/bin/bash
# Wrapper for axiom-extract-clang that adds Clang resource directory
# This ensures C++ standard library headers are found correctly

RESOURCE_DIR="/usr/lib/llvm-19/lib/clang/19"

# Pass through all arguments, adding resource-dir after the -- separator
# This handles: axiom-extract-clang file.cpp -- [extra flags]
exec /usr/local/bin/axiom-extract-clang-bin "$@" -resource-dir="$RESOURCE_DIR" -stdlib=libc++
