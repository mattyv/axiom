// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2026 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#pragma once

#include <nlohmann/json.hpp>
#include <optional>
#include <string>
#include <vector>

namespace axiom {

/// Result for a single axiom from query service.
struct AxiomResult {
    std::string id;
    std::string content;
    std::string formal_spec;
    std::string axiom_type;
    double confidence;
    std::string layer;  // "static" or "live"
    std::string function;
    std::string signature;
    std::string header;
    std::vector<std::string> depends_on;
    std::vector<nlohmann::json> proof_chain;
    std::vector<std::string> pairs_with;
};

/// Axioms for a symbol from query service.
struct SymbolAxioms {
    std::string symbol;
    std::string layer;  // "static", "live", "both", or "none"
    std::vector<AxiomResult> axioms;
};

/// Client for communicating with axiom-query-server via Unix socket.
class QueryClient {
public:
    /// Create client with socket path.
    /// @param socket_path Path to Unix socket (default: /tmp/axiom-query.sock)
    explicit QueryClient(std::string socket_path = "/tmp/axiom-query.sock");

    ~QueryClient();

    /// Check if connected to server.
    bool isConnected() const { return connected_; }

    /// Connect to the query server.
    /// @return true if connection successful.
    bool connect();

    /// Disconnect from server.
    void disconnect();

    /// Query axioms for multiple symbols.
    /// @param symbols List of qualified function names.
    /// @return List of SymbolAxioms, one per symbol.
    std::vector<SymbolAxioms> query(const std::vector<std::string>& symbols);

    /// Get a specific axiom by ID.
    /// @param axiom_id Axiom ID.
    /// @return AxiomResult if found, nullopt otherwise.
    std::optional<AxiomResult> getAxiom(const std::string& axiom_id);

    /// Get axioms for a specific file.
    /// @param file_path Path to source file.
    /// @return List of axioms from that file.
    std::vector<AxiomResult> getAxiomsForFile(const std::string& file_path);

private:
    std::string socket_path_;
    int socket_fd_ = -1;
    bool connected_ = false;

    /// Send request and receive response.
    std::optional<nlohmann::json> sendRequest(const nlohmann::json& request);

    /// Parse axiom result from JSON.
    static AxiomResult parseAxiomResult(const nlohmann::json& j);
};

} // namespace axiom
