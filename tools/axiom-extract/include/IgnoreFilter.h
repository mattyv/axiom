// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#pragma once

#include <fstream>
#include <regex>
#include <string>
#include <sys/stat.h>
#include <vector>

namespace axiom {

/// Parses .axignore files and filters paths based on glob patterns.
///
/// Supports two types of patterns:
/// - Regular patterns: ignored during normal extraction
/// - Test patterns (@test: prefix): ignored normally, but included in --test-mode
///
/// Example .axignore:
///   build/           # Always ignored
///   @test: tests/    # Ignored normally, used for test mining
///   @test: *_test.cpp
class IgnoreFilter {
public:
    IgnoreFilter() = default;

    /// Load ignore patterns from a file (typically .axignore)
    bool loadFromFile(const std::string& path) {
        std::ifstream file(path);
        if (!file.is_open()) {
            return false;
        }

        std::string line;
        while (std::getline(file, line)) {
            // Skip empty lines and comments
            if (line.empty() || line[0] == '#') {
                continue;
            }

            // Trim whitespace
            size_t start = line.find_first_not_of(" \t");
            size_t end = line.find_last_not_of(" \t");
            if (start == std::string::npos) {
                continue;
            }
            line = line.substr(start, end - start + 1);

            if (!line.empty()) {
                // Check for @test: prefix
                const std::string testPrefix = "@test:";
                if (line.find(testPrefix) == 0) {
                    std::string pattern = line.substr(testPrefix.length());
                    // Trim leading whitespace from pattern
                    size_t patStart = pattern.find_first_not_of(" \t");
                    if (patStart != std::string::npos) {
                        pattern = pattern.substr(patStart);
                        addTestPattern(pattern);
                    }
                } else {
                    addPattern(line);
                }
            }
        }

        return true;
    }

    /// Add a glob pattern to the ignore list
    void addPattern(const std::string& pattern) {
        patterns_.push_back(pattern);
        regexes_.push_back(globToRegex(pattern));
    }

    /// Add a test-only pattern (ignored normally, included in test mode)
    void addTestPattern(const std::string& pattern) {
        testPatterns_.push_back(pattern);
        testRegexes_.push_back(globToRegex(pattern));
    }

    /// Check if a path should be ignored (normal mode)
    bool shouldIgnore(const std::string& path) const {
        // In normal mode, ignore both regular patterns AND test patterns
        for (const auto& regex : regexes_) {
            if (std::regex_search(path, regex)) {
                return true;
            }
        }
        for (const auto& regex : testRegexes_) {
            if (std::regex_search(path, regex)) {
                return true;
            }
        }
        return false;
    }

    /// Check if a path should be ignored in test mode
    /// In test mode: ignore regular patterns, but INCLUDE test patterns
    bool shouldIgnoreInTestMode(const std::string& path) const {
        // Only check regular patterns, not test patterns
        for (const auto& regex : regexes_) {
            if (std::regex_search(path, regex)) {
                return true;
            }
        }
        return false;
    }

    /// Check if a path is a test path (matches @test: patterns)
    bool isTestPath(const std::string& path) const {
        for (const auto& regex : testRegexes_) {
            if (std::regex_search(path, regex)) {
                return true;
            }
        }
        return false;
    }

    /// Check if a path relative to project root should be ignored
    bool shouldIgnore(const std::string& path, const std::string& projectRoot) const {
        std::string relativePath = makeRelative(path, projectRoot);
        return shouldIgnore(relativePath);
    }

    /// Check if a path relative to project root should be ignored in test mode
    bool shouldIgnoreInTestMode(const std::string& path, const std::string& projectRoot) const {
        std::string relativePath = makeRelative(path, projectRoot);
        return shouldIgnoreInTestMode(relativePath);
    }

    /// Check if a path relative to project root is a test path
    bool isTestPath(const std::string& path, const std::string& projectRoot) const {
        std::string relativePath = makeRelative(path, projectRoot);
        return isTestPath(relativePath);
    }

    /// Get the number of patterns loaded (both regular and test)
    size_t patternCount() const { return patterns_.size() + testPatterns_.size(); }

    /// Get the number of test patterns
    size_t testPatternCount() const { return testPatterns_.size(); }

    /// Get all patterns (for debugging)
    const std::vector<std::string>& patterns() const { return patterns_; }

    /// Get all test patterns (for debugging)
    const std::vector<std::string>& testPatterns() const { return testPatterns_; }

private:
    /// Make a path relative to the project root
    std::string makeRelative(const std::string& path, const std::string& projectRoot) const {
        if (path.find(projectRoot) == 0) {
            size_t start = projectRoot.length();
            if (start < path.length() && path[start] == '/') {
                ++start;
            }
            return path.substr(start);
        }
        return path;
    }

    /// Convert a glob pattern to a regex
    std::regex globToRegex(const std::string& glob) {
        std::string regex;
        regex.reserve(glob.size() * 2);

        for (size_t i = 0; i < glob.size(); ++i) {
            char c = glob[i];
            switch (c) {
                case '*':
                    if (i + 1 < glob.size() && glob[i + 1] == '*') {
                        // ** matches any path (including /)
                        regex += ".*";
                        ++i;
                        // Skip following / if present
                        if (i + 1 < glob.size() && glob[i + 1] == '/') {
                            ++i;
                        }
                    } else {
                        // * matches anything except /
                        regex += "[^/]*";
                    }
                    break;
                case '?':
                    regex += "[^/]";
                    break;
                case '.':
                case '+':
                case '^':
                case '$':
                case '(':
                case ')':
                case '{':
                case '}':
                case '[':
                case ']':
                case '|':
                case '\\':
                    regex += '\\';
                    regex += c;
                    break;
                default:
                    regex += c;
                    break;
            }
        }

        // Pattern can match anywhere in the path
        return std::regex(regex, std::regex::icase);
    }

    std::vector<std::string> patterns_;
    std::vector<std::regex> regexes_;
    std::vector<std::string> testPatterns_;
    std::vector<std::regex> testRegexes_;
};

/// Find .axignore file by walking up from a source file or directory
inline std::string findAxignoreFile(const std::string& sourcePath) {
    std::string dir = sourcePath;

    // Remove trailing slash if present
    while (!dir.empty() && dir.back() == '/') {
        dir.pop_back();
    }

    // Check if path is a directory first - if so, start looking from there
    // Otherwise get the parent directory
    struct stat pathStat;
    if (stat(dir.c_str(), &pathStat) == 0 && S_ISDIR(pathStat.st_mode)) {
        // It's a directory - check for .axignore here first
        std::string axignorePath = dir + "/.axignore";
        std::ifstream test(axignorePath);
        if (test.good()) {
            return axignorePath;
        }
    } else {
        // It's a file - get parent directory
        size_t lastSlash = dir.rfind('/');
        if (lastSlash != std::string::npos) {
            dir = dir.substr(0, lastSlash);
        }
    }

    // Walk up looking for .axignore
    while (!dir.empty() && dir != "/") {
        std::string axignorePath = dir + "/.axignore";
        std::ifstream test(axignorePath);
        if (test.good()) {
            return axignorePath;
        }

        // Move up one directory
        size_t lastSlash = dir.rfind('/');
        if (lastSlash == std::string::npos) {
            break;
        }
        dir = dir.substr(0, lastSlash);
    }

    return "";
}

/// Get project root from .axignore location
inline std::string getProjectRoot(const std::string& axignorePath) {
    size_t lastSlash = axignorePath.rfind('/');
    if (lastSlash != std::string::npos) {
        return axignorePath.substr(0, lastSlash);
    }
    return ".";
}

} // namespace axiom
