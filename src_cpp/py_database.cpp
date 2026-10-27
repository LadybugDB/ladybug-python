#include "include/py_database.h"

#include <memory>
#include <mutex>
#include <optional>

#include "common/exception/runtime.h"
#include "extension/extension.h"
#include "include/cached_import/py_cached_import.h"
#include "main/version.h"
#include "pandas/pandas_scan.h"

using namespace lbug::common;

void PyDatabase::initialize(py::handle& m) {
    py::class_<PyDatabase>(m, "Database")
        .def(py::init<const std::string&, std::optional<uint64_t>, std::optional<uint64_t>,
                 std::optional<bool>, std::optional<bool>, std::optional<uint64_t>,
                 std::optional<bool>, std::optional<int64_t>, std::optional<bool>,
                 std::optional<bool>, std::optional<bool>>(),
            py::arg("database_path"), py::arg("buffer_pool_size") = py::none(),
            py::arg("max_num_threads") = py::none(), py::arg("compression") = py::none(),
            py::arg("read_only") = py::none(), py::arg("max_db_size") = py::none(),
            py::arg("auto_checkpoint") = py::none(), py::arg("checkpoint_threshold") = py::none(),
            py::arg("throw_on_wal_replay_failure") = py::none(),
            py::arg("enable_checksums") = py::none(),
            py::arg("enable_multi_writes") = py::none())
        .def("scan_node_table_as_int64", &PyDatabase::scanNodeTable<std::int64_t>,
            py::arg("table_name"), py::arg("prop_name"), py::arg("indices"), py::arg("np_array"),
            py::arg("num_threads"))
        .def("scan_node_table_as_int32", &PyDatabase::scanNodeTable<std::int32_t>,
            py::arg("table_name"), py::arg("prop_name"), py::arg("indices"), py::arg("np_array"),
            py::arg("num_threads"))
        .def("scan_node_table_as_int16", &PyDatabase::scanNodeTable<std::int16_t>,
            py::arg("table_name"), py::arg("prop_name"), py::arg("indices"), py::arg("np_array"),
            py::arg("num_threads"))
        .def("scan_node_table_as_double", &PyDatabase::scanNodeTable<double>, py::arg("table_name"),
            py::arg("prop_name"), py::arg("indices"), py::arg("np_array"), py::arg("num_threads"))
        .def("scan_node_table_as_float", &PyDatabase::scanNodeTable<float>, py::arg("table_name"),
            py::arg("prop_name"), py::arg("indices"), py::arg("np_array"), py::arg("num_threads"))
        .def("scan_node_table_as_bool", &PyDatabase::scanNodeTable<bool>, py::arg("table_name"),
            py::arg("prop_name"), py::arg("indices"), py::arg("np_array"), py::arg("num_threads"))
        .def("close", &PyDatabase::close)
        .def_static("get_version", &PyDatabase::getVersion)
        .def_static("get_storage_version", &PyDatabase::getStorageVersion);
}

py::str PyDatabase::getVersion() {
    return py::str(Version::getVersion());
}

uint64_t PyDatabase::getStorageVersion() {
    return Version::getStorageVersion();
}

PyDatabase::PyDatabase(const std::string& databasePath, std::optional<uint64_t> bufferPoolSize,
    std::optional<uint64_t> maxNumThreads, std::optional<bool> compression,
    std::optional<bool> readOnly, std::optional<uint64_t> maxDBSize,
    std::optional<bool> autoCheckpoint, std::optional<int64_t> checkpointThreshold,
    std::optional<bool> throwOnWalReplayFailure, std::optional<bool> enableChecksums,
    std::optional<bool> enableMultiWrites) {
    // Start from the engine defaults and only apply explicitly set settings,
    // so engine-side default changes propagate automatically.
    auto systemConfig = SystemConfig();
    if (bufferPoolSize.has_value()) {
        systemConfig.bufferPoolSize = bufferPoolSize.value();
    }
    if (maxNumThreads.has_value()) {
        systemConfig.maxNumThreads = maxNumThreads.value();
    }
    if (compression.has_value()) {
        systemConfig.enableCompression = compression.value();
    }
    if (readOnly.has_value()) {
        systemConfig.readOnly = readOnly.value();
    }
    if (maxDBSize.has_value()) {
        systemConfig.maxDBSize = maxDBSize.value();
    }
    if (autoCheckpoint.has_value()) {
        systemConfig.autoCheckpoint = autoCheckpoint.value();
    }
    if (checkpointThreshold.has_value() && checkpointThreshold.value() >= 0) {
        systemConfig.checkpointThreshold =
            static_cast<uint64_t>(checkpointThreshold.value());
    }
    if (throwOnWalReplayFailure.has_value()) {
        systemConfig.throwOnWalReplayFailure = throwOnWalReplayFailure.value();
    }
    if (enableChecksums.has_value()) {
        systemConfig.enableChecksums = enableChecksums.value();
    }
    if (enableMultiWrites.has_value()) {
        systemConfig.enableMultiWrites = enableMultiWrites.value();
    }
    state = std::make_shared<PyDatabaseState>();
    state->database = std::make_unique<Database>(databasePath, systemConfig);
    lbug::extension::ExtensionUtils::addTableFunc<lbug::PandasScanFunction>(*state->database);
    state->storageDriver = std::make_unique<StorageDriver>(state->database.get());
    py::gil_scoped_acquire acquire;
    // Taken with the GIL held: nothing inside may call into Python.
    static std::mutex importCacheMutex;
    std::lock_guard<std::mutex> lock(importCacheMutex);
    if (lbug::importCache.get() == nullptr) {
        lbug::importCache = std::make_shared<lbug::PythonCachedImport>();
    }
}

PyDatabase::~PyDatabase() {
    close();
}

void PyDatabase::close() {
    state.reset();
}

template<class T>
void PyDatabase::scanNodeTable(const std::string& tableName, const std::string& propName,
    const py::array_t<uint64_t>& indices, py::array_t<T>& result, int numThreads) {
    auto indices_buffer_info = indices.request(false);
    auto indices_buffer = static_cast<uint64_t*>(indices_buffer_info.ptr);
    auto nodeOffsets = (offset_t*)indices_buffer;
    auto result_buffer_info = result.request();
    auto result_buffer = (uint8_t*)result_buffer_info.ptr;
    auto size = indices.size();
    if (state == nullptr) {
        throw RuntimeException("Database is closed.");
    }
    state->storage().scan(tableName, propName, nodeOffsets, size, result_buffer, numThreads);
}
