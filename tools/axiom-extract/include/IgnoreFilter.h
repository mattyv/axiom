// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#pragma once

#include <fstream>
#include <regex>
#include <string>
#include <vector>

namespace axiom {

/// Parses .axignore files and filters paths based on glob patterns.
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
                addPattern(line);
            }
        }

        return true;
    }

    /// Add a glob pattern to the ignore list
    void addPattern(const std::string& pattern) {
        patterns_.push_back(pattern);
        regexes_.push_back(globToRegex(pattern));
    }

    /// Check if a path should be ignored
    bool shouldIgnore(const std::string& path) const {
        for (const auto& regex : regexes_) {
            if (std::regex_search(path, regex)) {
                return true;
            }
        }
        return false;
    }

    /// Check if a path relative to project root should be ignored
    bool shouldIgnore(const std::string& path, const std::string& projectRoot) const {
        // Make path relative to project root
        std::string relativePath = path;
        if (path.find(projectRoot) == 0) {
            relativePath = path.substr(projectRoot.length());
            if (!relativePath.empty() && relativePath[0] == '/') {
                relativePath = relativePath.substr(1);
            }
        }
        return shouldIgnore(relativePath);
    }

    /// Get the number of patterns loaded
    size_t patternCount() const { return patterns_.size(); }

    /// Get all patterns (for debugging)
    const std::vector<std::string>& patterns() const { return patterns_; }

private:
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
};

/// Find .axignore file by walking up from a source file
inline std::string findAxignoreFile(const std::string& sourcePath) {
    std::string dir = sourcePath;

    // Get directory part
    size_t lastSlash = dir.rfind('/');
    if (lastSlash != std::string::npos) {
        dir = dir.substr(0, lastSlash);
    }

    // Walk up looking for .axignore
    while (!dir.empty() && dir != "/") {
        std::string axignorePath = dir + "/.axignore";
        std::ifstream test(axignorePath);
        if (test.good()) {
            return axignorePath;
        }

        // Move up one directory
        lastSlash = dir.rfind('/');
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
