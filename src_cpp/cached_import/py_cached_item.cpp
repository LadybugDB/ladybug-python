#include "cached_import/py_cached_item.h"

#include "cached_import/py_cached_import.h"
#include "common/exception/runtime.h"

namespace lbug {

py::handle PythonCachedItem::operator()() {
    assert((bool)PyGILState_Check());
    if (isLoaded()) {
        return object;
    }
    // The parent takes the same lock, so load it before locking.
    py::handle parentObject = parent == nullptr ? py::handle() : (*parent)();
    auto lock = importCache->lockForLoading();
    if (!isLoaded()) {
        auto obj = parent == nullptr ? py::object(py::module::import(name.c_str())) :
                                       py::object(parentObject.attr(name.c_str()));
        object = importCache->addToCache(std::move(obj));
        loaded.store(true, std::memory_order_release);
    }
    return object;
}

} // namespace lbug
