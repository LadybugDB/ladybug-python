#pragma once

#include <atomic>
#include <memory>
#include <string>

#include "pybind_include.h"

namespace lbug {

class PythonCachedItem {
public:
    explicit PythonCachedItem(std::string name, PythonCachedItem* parent = nullptr)
        : name(std::move(name)), parent(parent) {}
    virtual ~PythonCachedItem() = default;

    bool isLoaded() const { return loaded.load(std::memory_order_acquire); }
    py::handle operator()();

protected:
    std::string name;
    PythonCachedItem* parent;
    std::atomic<bool> loaded{false};
    py::handle object;
};

} // namespace lbug
