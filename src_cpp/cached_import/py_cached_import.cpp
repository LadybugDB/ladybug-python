#include "cached_import/py_cached_import.h"

#include "common/exception/runtime.h"

namespace lbug {

std::shared_ptr<PythonCachedImport> importCache;

PythonCachedImport::~PythonCachedImport() {
    py::gil_scoped_acquire acquire;
    allObjects.clear();
}

std::unique_lock<std::mutex> PythonCachedImport::lockForLoading() {
    // Wait with the GIL released (detached on free-threaded builds): the holder needs the GIL to
    // finish its import, and a detached waiter does not stall stop-the-world pauses.
    py::gil_scoped_release release;
    return std::unique_lock<std::mutex>(loadMutex);
}

py::handle PythonCachedImport::addToCache(py::object obj) {
    auto ptr = obj.ptr();
    allObjects.push_back(obj);
    return ptr;
}

bool doesPyModuleExist(std::string moduleName) {
    py::gil_scoped_acquire acquire;
    auto find_spec = importCache->importlib.util.find_spec();
#if defined(__clang__)
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
#elif defined(__GNUC__)
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif
    return find_spec(moduleName) != Py_None;
}

} // namespace lbug
