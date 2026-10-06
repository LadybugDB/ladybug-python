#pragma once

#include <mutex>
#include <string>
#include <vector>

#include "py_cached_modules.h"

namespace lbug {

class PythonCachedImport {
public:
    // Note: Callers generally acquire the GIL prior to entering functions
    // that require the import cache.

    PythonCachedImport() = default;
    ~PythonCachedImport();

    // Call with the lock from lockForLoading() held.
    py::handle addToCache(py::object obj);
    std::unique_lock<std::mutex> lockForLoading();

    DateTimeCachedItem datetime;
    DecimalCachedItem decimal;
    ImportLibCachedItem importlib;
    InspectCachedItem inspect;
    NumpyMaCachedItem numpyma;
    PandasCachedItem pandas;
    PolarsCachedItem polars;
    PyarrowCachedItem pyarrow;
    SignalCachedItem signal;
    ThreadingCachedItem threading;
    UUIDCachedItem uuid;

private:
    std::mutex loadMutex;
    std::vector<py::object> allObjects;
};

bool doesPyModuleExist(std::string moduleName);

extern std::shared_ptr<PythonCachedImport> importCache;

} // namespace lbug
