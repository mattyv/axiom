// Axiom - Grounded truth validation for LLMs
// Copyright (c) 2025 Matt Varendorff
// https://github.com/mattyv/axiom
// SPDX-License-Identifier: BSL-1.0

#include "Extractors.h"

#include <chrono>
#include <iomanip>
#include <nlohmann/json.hpp>
#include <sstream>

namespace axiom {

class JsonEmitterImpl : public JsonEmitter {
public:
    std::string emit(const std::vector<ExtractionResult>& results) override {
        nlohmann::json output;

        // Version and metadata
        output["version"] = "1.0";
        output["extracted_at"] = getCurrentTimestamp();
        output["tool"] = "axiom-extract";
        output["tool_version"] = "0.1.0";

        // Aggregate all axioms from all results
        nlohmann::json allAxioms = nlohmann::json::array();
        nlohmann::json allErrors = nlohmann::json::array();
        std::vector<std::string> sourceFiles;

        for (const auto& result : results) {
            sourceFiles.push_back(result.source_file);

            for (const auto& axiom : result.axioms) {
                allAxioms.push_back(axiom);
            }

            for (const auto& error : result.errors) {
                nlohmann::json errObj;
                errObj["file"] = result.source_file;
                errObj["message"] = error;
                allErrors.push_back(errObj);
            }
        }

        output["source_files"] = sourceFiles;
        output["axioms"] = allAxioms;
        output["errors"] = allErrors;

        // Statistics
        nlohmann::json stats;
        stats["files_processed"] = results.size();
        stats["axioms_extracted"] = allAxioms.size();
        stats["errors_encountered"] = allErrors.size();

        // Count by type
        std::map<std::string, int> byType;
        std::map<std::string, int> bySource;

        for (const auto& axiom : allAxioms) {
            std::string type = axiom["axiom_type"];
            std::string source = axiom["source_type"];
            byType[type]++;
            bySource[source]++;
        }

        stats["by_type"] = byType;
        stats["by_source"] = bySource;
        output["statistics"] = stats;

        return output.dump(2);
    }

private:
    std::string getCurrentTimestamp() {
        auto now = std::chrono::system_clock::now();
        auto time = std::chrono::system_clock::to_time_t(now);
        std::stringstream ss;
        ss << std::put_time(std::gmtime(&time), "%Y-%m-%dT%H:%M:%SZ");
        return ss.str();
    }
};

std::unique_ptr<JsonEmitter> createJsonEmitter() {
    return std::make_unique<JsonEmitterImpl>();
}

} // namespace axiom
