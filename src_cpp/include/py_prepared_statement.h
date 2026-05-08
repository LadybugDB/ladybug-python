#pragma once

#include "main/lbug.h"
#include "main/prepared_statement.h"
#include "py_handle_state.h"
#include "pybind_include.h"

using namespace lbug::main;

class PyPreparedStatement {
    friend class PyConnection;

public:
    static void initialize(py::handle& m);

    py::str getErrorMessage() const;

    bool isSuccess() const;

private:
    std::shared_ptr<PyPreparedStatementState> state;
};
