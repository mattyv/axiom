// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2026 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "QueryClient.h"

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <cstring>
#include <sstream>

namespace axiom {

QueryClient::QueryClient(std::string socket_path)
    : socket_path_(std::move(socket_path)) {}

QueryClient::~QueryClient() {
    disconnect();
}

bool QueryClient::connect() {
    if (connected_) {
        return true;
    }

    // Create Unix socket
    socket_fd_ = socket(AF_UNIX, SOCK_STREAM, 0);
    if (socket_fd_ < 0) {
        return false;
    }

    // Connect to server
    struct sockaddr_un addr;
    std::memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);

    if (::connect(socket_fd_, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        close(socket_fd_);
        socket_fd_ = -1;
        return false;
    }

    connected_ = true;
    return true;
}

void QueryClient::disconnect() {
    if (socket_fd_ >= 0) {
        close(socket_fd_);
        socket_fd_ = -1;
    }
    connected_ = false;
}

std::optional<nlohmann::json> QueryClient::sendRequest(const nlohmann::json& request) {
    if (!connected_ && !connect()) {
        return std::nullopt;
    }

    // Send request (newline-delimited JSON)
    std::string request_str = request.dump() + "\n";
    ssize_t sent = write(socket_fd_, request_str.c_str(), request_str.size());
    if (sent < 0 || static_cast<size_t>(sent) != request_str.size()) {
        disconnect();
        return std::nullopt;
    }

    // Read response (newline-delimited JSON)
    std::string response_str;
    char buffer[4096];
    while (true) {
        ssize_t received = read(socket_fd_, buffer, sizeof(buffer) - 1);
        if (received <= 0) {
            disconnect();
            return std::nullopt;
        }
        buffer[received] = '\0';
        response_str += buffer;

        // Check for newline (end of response)
        if (response_str.find('\n') != std::string::npos) {
            break;
        }
    }

    try {
        return nlohmann::json::parse(response_str);
    } catch (const nlohmann::json::exception&) {
        return std::nullopt;
    }
}

AxiomResult QueryClient::parseAxiomResult(const nlohmann::json& j) {
    AxiomResult result;
    result.id = j.value("id", "");
    result.content = j.value("content", "");
    result.formal_spec = j.value("formal_spec", "");
    result.axiom_type = j.value("axiom_type", "");
    result.confidence = j.value("confidence", 0.0);
    result.layer = j.value("layer", "");
    result.function = j.value("function", "");
    result.signature = j.value("signature", "");
    result.header = j.value("header", "");

    if (j.contains("depends_on") && j["depends_on"].is_array()) {
        for (const auto& dep : j["depends_on"]) {
            if (dep.is_string()) {
                result.depends_on.push_back(dep.get<std::string>());
            }
        }
    }

    if (j.contains("proof_chain") && j["proof_chain"].is_array()) {
        result.proof_chain = j["proof_chain"].get<std::vector<nlohmann::json>>();
    }

    if (j.contains("pairs_with") && j["pairs_with"].is_array()) {
        for (const auto& pair : j["pairs_with"]) {
            if (pair.is_string()) {
                result.pairs_with.push_back(pair.get<std::string>());
            }
        }
    }

    return result;
}

std::vector<SymbolAxioms> QueryClient::query(const std::vector<std::string>& symbols) {
    nlohmann::json request = {
        {"method", "query"},
        {"params", {{"symbols", symbols}}}
    };

    auto response = sendRequest(request);
    if (!response || !response->contains("result")) {
        return {};
    }

    std::vector<SymbolAxioms> results;
    for (const auto& item : (*response)["result"]) {
        SymbolAxioms sa;
        sa.symbol = item.value("symbol", "");
        sa.layer = item.value("layer", "none");

        if (item.contains("axioms") && item["axioms"].is_array()) {
            for (const auto& axiom_json : item["axioms"]) {
                sa.axioms.push_back(parseAxiomResult(axiom_json));
            }
        }

        results.push_back(std::move(sa));
    }

    return results;
}

std::optional<AxiomResult> QueryClient::getAxiom(const std::string& axiom_id) {
    nlohmann::json request = {
        {"method", "get_axiom"},
        {"params", {{"axiom_id", axiom_id}}}
    };

    auto response = sendRequest(request);
    if (!response || !response->contains("result") || (*response)["result"].is_null()) {
        return std::nullopt;
    }

    return parseAxiomResult((*response)["result"]);
}

std::vector<AxiomResult> QueryClient::getAxiomsForFile(const std::string& file_path) {
    nlohmann::json request = {
        {"method", "get_axioms_for_file"},
        {"params", {{"file_path", file_path}}}
    };

    auto response = sendRequest(request);
    if (!response || !response->contains("result")) {
        return {};
    }

    std::vector<AxiomResult> results;
    const auto& result = (*response)["result"];
    if (result.contains("axioms") && result["axioms"].is_array()) {
        for (const auto& axiom_json : result["axioms"]) {
            results.push_back(parseAxiomResult(axiom_json));
        }
    }

    return results;
}

} // namespace axiom
