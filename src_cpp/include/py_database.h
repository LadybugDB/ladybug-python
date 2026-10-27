#pragma once

#include <memory>
#include <optional>

#include "main/lbug.h"
#include "main/storage_driver.h"
#include "py_handle_state.h"
#include "pybind_include.h" // IWYU pragma: keep (used for py:: namespace)
#define PYBIND11_DETAILED_ERROR_MESSAGES
using namespace lbug::main;

class PyDatabase {
    friend class PyConnection;

public:
    static void initialize(py::handle& m);

    static py::str getVersion();

    static uint64_t getStorageVersion();

    explicit PyDatabase(const std::string& databasePath,
        std::optional<uint64_t> bufferPoolSize = std::nullopt,
        std::optional<uint64_t> maxNumThreads = std::nullopt,
        std::optional<bool> compression = std::nullopt, std::optional<bool> readOnly = std::nullopt,
        std::optional<uint64_t> maxDBSize = std::nullopt,
        std::optional<bool> autoCheckpoint = std::nullopt,
        std::optional<int64_t> checkpointThreshold = std::nullopt,
        std::optional<bool> throwOnWalReplayFailure = std::nullopt,
        std::optional<bool> enableChecksums = std::nullopt,
        std::optional<bool> enableMultiWrites = std::nullopt);

    ~PyDatabase();

    void close();

    template<class T>
    void scanNodeTable(const std::string& tableName, const std::string& propName,
        const py::array_t<uint64_t>& indices, py::array_t<T>& result, int numThreads);

private:
    std::shared_ptr<PyDatabaseState> state;
};
