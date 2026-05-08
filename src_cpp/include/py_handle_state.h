#pragma once

#include <memory>
#include <string>
#include <unordered_map>

#include "common/exception/runtime.h"
#include "main/lbug.h"
#include "main/prepared_statement.h"
#include "main/storage_driver.h"
#include "pybind_include.h"

struct PyDatabaseState {
    std::unique_ptr<lbug::main::Database> database;
    std::unique_ptr<lbug::main::StorageDriver> storageDriver;

    ~PyDatabaseState() { closeNative(); }

    void closeNative() {
        storageDriver.reset();
        database.reset();
    }

    lbug::main::Database& ref() const {
        if (database == nullptr) {
            throw lbug::common::RuntimeException("Database is closed.");
        }
        return *database;
    }

    lbug::main::StorageDriver& storage() const {
        if (storageDriver == nullptr) {
            throw lbug::common::RuntimeException("Database is closed.");
        }
        return *storageDriver;
    }
};

struct PyConnectionState {
    std::shared_ptr<PyDatabaseState> database;
    std::unique_ptr<lbug::main::StorageDriver> storageDriver;
    std::unique_ptr<lbug::main::Connection> conn;
    std::unordered_map<std::string, py::object> arrowTableRefs;

    ~PyConnectionState() { closeNative(); }

    void closeNative() {
        arrowTableRefs.clear();
        conn.reset();
        storageDriver.reset();
        database.reset();
    }

    lbug::main::Connection& ref() const {
        if (conn == nullptr) {
            throw lbug::common::RuntimeException("Connection is closed.");
        }
        return *conn;
    }

    lbug::main::StorageDriver& storage() const {
        if (storageDriver == nullptr) {
            throw lbug::common::RuntimeException("Connection is closed.");
        }
        return *storageDriver;
    }
};

struct PyPreparedStatementState {
    std::shared_ptr<PyConnectionState> connection;
    std::unique_ptr<lbug::main::PreparedStatement> preparedStatement;

    lbug::main::PreparedStatement& ref() const {
        if (preparedStatement == nullptr) {
            throw lbug::common::RuntimeException("Prepared statement is closed.");
        }
        return *preparedStatement;
    }
};

struct PyQueryResultState {
    std::shared_ptr<PyConnectionState> connection;
    std::shared_ptr<PyQueryResultState> parent;
    std::unique_ptr<lbug::main::QueryResult> owned;
    lbug::main::QueryResult* borrowed = nullptr;

    lbug::main::QueryResult& ref() const {
        auto* result = owned != nullptr ? owned.get() : borrowed;
        if (result == nullptr) {
            throw lbug::common::RuntimeException("Query result is closed.");
        }
        return *result;
    }
};
