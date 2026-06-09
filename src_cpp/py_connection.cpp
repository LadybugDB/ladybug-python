#include "include/py_connection.h"

#include <algorithm>
#include <cctype>
#include <utility>

#include "cached_import/py_cached_import.h"
#include "common/constants.h"
#include "common/exception/not_implemented.h"
#include "common/exception/runtime.h"
#include "common/json_utils.h"
#include "common/types/json_type.h"
#include "common/types/uuid.h"
#include "common/utils.h"
#include "datetime.h" // from Python
#include "function/cast/functions/cast_string_non_nested_functions.h"
#include "include/py_udf.h"
#include "main/connection.h"
#include "main/query_result/materialized_query_result.h"
#include "numpy/numpy_type.h"
#include "pandas/pandas_scan.h"
#include "processor/result/factorized_table.h"
#include "pyarrow/pyarrow_scan.h"
#include "storage/table/arrow_table_support.h"
#include <format>

using namespace lbug::common;
using namespace lbug;

void PyConnection::initialize(py::handle& m) {
    py::class_<PyConnection>(m, "Connection")
        .def(py::init<PyDatabase*, uint64_t>(), py::arg("database"), py::arg("num_threads") = 0)
        .def("close", &PyConnection::close)
        .def("execute", &PyConnection::execute, py::arg("prepared_statement"),
            py::arg("parameters") = py::dict())
        .def("query", &PyConnection::query, py::arg("statement"))
        .def("query_as_arrow", &PyConnection::queryAsArrow, py::arg("statement"),
            py::arg("chunk_size"))
        .def("set_max_threads_for_exec", &PyConnection::setMaxNumThreadForExec,
            py::arg("num_threads"))
        .def("prepare", &PyConnection::prepare, py::arg("query"),
            py::arg("parameters") = py::dict())
        .def("set_query_timeout", &PyConnection::setQueryTimeout, py::arg("timeout_in_ms"))
        .def("interrupt", &PyConnection::interrupt)
        .def("get_num_nodes", &PyConnection::getNumNodes, py::arg("node_name"))
        .def("get_num_rels", &PyConnection::getNumRels, py::arg("rel_name"))
        .def("get_all_edges_for_torch_geometric", &PyConnection::getAllEdgesForTorchGeometric,
            py::arg("np_array"), py::arg("src_table_name"), py::arg("rel_name"),
            py::arg("dst_table_name"), py::arg("query_batch_size"))
        .def("create_function", &PyConnection::createScalarFunction, py::arg("name"),
            py::arg("udf"), py::arg("params_type"), py::arg("return_value"),
            py::arg("default_null"), py::arg("catch_exceptions"))
        .def("remove_function", &PyConnection::removeScalarFunction, py::arg("name"))
        .def("create_arrow_table", &PyConnection::createArrowTable, py::arg("table_name"),
            py::arg("arrow_table"))
        .def("create_arrow_rel_table", &PyConnection::createArrowRelTable, py::arg("table_name"),
            py::arg("arrow_table"), py::arg("src_table_name"), py::arg("dst_table_name"),
            py::arg("layout") = "FLAT", py::arg("indptr_table") = py::none(),
            py::arg("dst_col_name") = "to")
        .def("drop_arrow_table", &PyConnection::dropArrowTable, py::arg("table_name"));
    PyDateTime_IMPORT;
}

static std::vector<function::scan_replace_handle_t> lookupPythonObject(
    const std::string& objectName) {
    std::vector<function::scan_replace_handle_t> ret;

    py::gil_scoped_acquire acquire;
    auto pyTableName = py::str(objectName);
    // Here we do an exhaustive search on the frame lineage.
    auto currentFrame = importCache->inspect.currentframe()();
    while (hasattr(currentFrame, "f_locals")) {
        auto localDict = py::cast<py::dict>(currentFrame.attr("f_locals"));
        auto hasLocalDict = !py::none().is(localDict);
        if (hasLocalDict) {
            if (localDict.contains(pyTableName)) {
                ret.push_back(reinterpret_cast<function::scan_replace_handle_t>(
                    localDict[pyTableName].ptr()));
            }
        }
        auto globalDict = py::reinterpret_borrow<py::dict>(currentFrame.attr("f_globals"));
        if (globalDict) {
            if (globalDict.contains(pyTableName)) {
                ret.push_back(reinterpret_cast<function::scan_replace_handle_t>(
                    globalDict[pyTableName].ptr()));
            }
        }
        currentFrame = currentFrame.attr("f_back");
    }
    return ret;
}

static std::unique_ptr<function::ScanReplacementData> tryReplacePolars(py::handle& entry) {
    if (PyConnection::isPolarsDataframe(entry)) {
        auto scanReplacementData = std::make_unique<function::ScanReplacementData>();
        scanReplacementData->func = PyArrowTableScanFunction::getFunction();
        auto bindInput = function::TableFuncBindInput();
        bindInput.addLiteralParam(Value::createValue(reinterpret_cast<uint8_t*>(entry.ptr())));
        scanReplacementData->bindInput = std::move(bindInput);
        return scanReplacementData;
    } else {
        return nullptr;
    }
}

static std::unique_ptr<function::ScanReplacementData> tryReplacePyArrow(py::handle& entry) {
    if (PyConnection::isPyArrowTable(entry)) {
        auto scanReplacementData = std::make_unique<function::ScanReplacementData>();
        scanReplacementData->func = PyArrowTableScanFunction::getFunction();
        auto bindInput = function::TableFuncBindInput();
        bindInput.addLiteralParam(Value::createValue(reinterpret_cast<uint8_t*>(entry.ptr())));
        scanReplacementData->bindInput = std::move(bindInput);
        return scanReplacementData;
    } else {
        return nullptr;
    }
}

static std::unique_ptr<function::ScanReplacementData> replacePythonObject(
    std::span<function::scan_replace_handle_t> candidateHandles) {
    py::gil_scoped_acquire acquire;
    for (auto* handle : candidateHandles) {
        auto entry = py::handle(reinterpret_cast<PyObject*>(handle));
        auto result = tryReplacePD(entry);
        if (!result) {
            result = tryReplacePolars(entry);
        }
        if (!result) {
            result = tryReplacePyArrow(entry);
        }
        if (result) {
            return result;
        }
    }
    if (!candidateHandles.empty()) {
        throw BinderException("Attempted to scan from unsupported python object. Can only scan "
                              "from pandas/polars dataframes and pyarrow tables.");
    }
    return nullptr;
}

PyConnection::PyConnection(PyDatabase* pyDatabase, uint64_t numThreads) {
    if (pyDatabase == nullptr || pyDatabase->state == nullptr) {
        throw RuntimeException("Database is closed.");
    }
    state = std::make_shared<PyConnectionState>();
    state->database = pyDatabase->state;
    auto& database = state->database->ref();
    state->storageDriver = std::make_unique<lbug::main::StorageDriver>(&database);
    state->conn = std::make_unique<Connection>(&database);
    state->conn->getClientContext()->addScanReplace(
        function::ScanReplacement(lookupPythonObject, replacePythonObject));
    if (numThreads > 0) {
        state->conn->setMaxNumThreadForExec(numThreads);
    }
}

PyConnection::~PyConnection() {
    close();
}

void PyConnection::close() {
    state.reset();
}

PyConnectionState& PyConnection::refState() const {
    if (state == nullptr) {
        throw RuntimeException("Connection is closed.");
    }
    state->ref();
    state->storage();
    return *state;
}

void PyConnection::setQueryTimeout(uint64_t timeoutInMS) {
    refState().ref().setQueryTimeOut(timeoutInMS);
}

void PyConnection::interrupt() {
    refState().ref().interrupt();
}

static std::unordered_map<std::string, std::unique_ptr<Value>> transformPythonParameters(
    const py::dict& params, Connection* conn);

std::unique_ptr<PyQueryResult> PyConnection::execute(PyPreparedStatement* preparedStatement,
    const py::dict& params) {
    auto& stateRef = refState();
    if (preparedStatement == nullptr || preparedStatement->state == nullptr) {
        throw RuntimeException("Prepared statement is closed.");
    }
    auto parameters = transformPythonParameters(params, &stateRef.ref());
    py::gil_scoped_release release;
    auto queryResult =
        stateRef.ref().executeWithParams(&preparedStatement->state->ref(), std::move(parameters));
    py::gil_scoped_acquire acquire;
    return checkAndWrapQueryResult(queryResult, state);
}

std::unique_ptr<PyQueryResult> PyConnection::query(const std::string& statement) {
    auto& stateRef = refState();
    py::gil_scoped_release release;
    auto queryResult = stateRef.ref().query(statement);
    py::gil_scoped_acquire acquire;
    return checkAndWrapQueryResult(queryResult, state);
}

std::unique_ptr<PyQueryResult> PyConnection::queryAsArrow(const std::string& statement,
    int64_t chunkSize) {
    auto& stateRef = refState();
    py::gil_scoped_release release;
    auto queryResult = stateRef.ref().queryAsArrow(statement, chunkSize);
    py::gil_scoped_acquire acquire;
    return checkAndWrapQueryResult(queryResult, state);
}

void PyConnection::setMaxNumThreadForExec(uint64_t numThreads) {
    refState().ref().setMaxNumThreadForExec(numThreads);
}

PyPreparedStatement PyConnection::prepare(const std::string& query, const py::dict& parameters) {
    auto& stateRef = refState();
    auto params = transformPythonParameters(parameters, &stateRef.ref());
    auto preparedStatement = stateRef.ref().prepareWithParams(query, std::move(params));
    PyPreparedStatement pyPreparedStatement;
    pyPreparedStatement.state = std::make_shared<PyPreparedStatementState>();
    pyPreparedStatement.state->connection = state;
    pyPreparedStatement.state->preparedStatement = std::move(preparedStatement);
    return pyPreparedStatement;
}

uint64_t PyConnection::getNumNodes(const std::string& nodeName) {
    return refState().storage().getNumNodes(nodeName);
}

uint64_t PyConnection::getNumRels(const std::string& relName) {
    return refState().storage().getNumRels(relName);
}

void PyConnection::getAllEdgesForTorchGeometric(py::array_t<int64_t>& npArray,
    const std::string& srcTableName, const std::string& relName, const std::string& dstTableName,
    size_t queryBatchSize) {
    auto& stateRef = refState();
    // Get the number of nodes in the dst table for batching.
    auto numDstNodes = getNumNodes(dstTableName);
    uint64_t batches = numDstNodes / queryBatchSize;
    if (numDstNodes % queryBatchSize != 0) {
        batches += 1;
    }
    auto numRels = getNumRels(relName);

    auto bufferInfo = npArray.request();
    auto buffer = (int64_t*)bufferInfo.ptr;

    // Set the number of threads to 1 for fetching edges to ensure ordering.
    auto numThreadsForExec = stateRef.ref().getMaxNumThreadForExec();
    stateRef.ref().setMaxNumThreadForExec(1);
    auto query = std::format("MATCH (a:{})-[:{}]->(b:{}) WHERE offset(id(b)) >= "
                             "$s AND offset(id(b)) < "
                             "$e RETURN offset(id(a)), offset(id(b))",
        srcTableName, relName, dstTableName);
    auto preparedStatement = stateRef.ref().prepare(query);
    auto srcBuffer = buffer;
    auto dstBuffer = buffer + numRels;
    for (uint64_t batch = 0; batch < batches; ++batch) {
        // Must be int64_t for parameter typing.
        int64_t start = batch * queryBatchSize;
        int64_t end = (batch + 1) * queryBatchSize;
        end = (uint64_t)end > numDstNodes ? numDstNodes : end;
        std::unordered_map<std::string, std::unique_ptr<Value>> parameters;
        parameters["s"] = std::make_unique<Value>(start);
        parameters["e"] = std::make_unique<Value>(end);
        auto result =
            stateRef.ref().executeWithParams(preparedStatement.get(), std::move(parameters));
        if (!result->isSuccess()) {
            throw std::runtime_error(result->getErrorMessage());
        }
        DASSERT(result->getType() == QueryResultType::FTABLE);
        auto& table = result->constCast<MaterializedQueryResult>().getFactorizedTable();
        auto tableSchema = table.getTableSchema();
        if (tableSchema->getColumn(0)->isFlat() && !tableSchema->getColumn(1)->isFlat()) {
            for (auto i = 0u; i < table.getNumTuples(); ++i) {
                auto tuple = table.getTuple(i);
                auto overflowValue = (overflow_value_t*)(tuple + tableSchema->getColOffset(1));
                for (auto j = 0u; j < overflowValue->numElements; ++j) {
                    srcBuffer[j] = *(int64_t*)(tuple + tableSchema->getColOffset(0));
                }
                for (auto j = 0u; j < overflowValue->numElements; ++j) {
                    dstBuffer[j] = ((int64_t*)overflowValue->value)[j];
                }
                srcBuffer += overflowValue->numElements;
                dstBuffer += overflowValue->numElements;
            }
        } else if (tableSchema->getColumn(1)->isFlat() && !tableSchema->getColumn(0)->isFlat()) {
            for (auto i = 0u; i < table.getNumTuples(); ++i) {
                auto tuple = table.getTuple(i);
                auto overflowValue = (overflow_value_t*)(tuple + tableSchema->getColOffset(0));
                for (auto j = 0u; j < overflowValue->numElements; ++j) {
                    srcBuffer[j] = ((int64_t*)overflowValue->value)[j];
                }
                for (auto j = 0u; j < overflowValue->numElements; ++j) {
                    dstBuffer[j] = *(int64_t*)(tuple + tableSchema->getColOffset(1));
                }
                srcBuffer += overflowValue->numElements;
                dstBuffer += overflowValue->numElements;
            }
        } else {
            throw std::runtime_error("Wrong result table schema.");
        }
    }
    stateRef.ref().setMaxNumThreadForExec(numThreadsForExec);
}

bool PyConnection::isPandasDataframe(const py::handle& object) {
    if (!doesPyModuleExist("pandas")) {
        return false;
    }
    return py::isinstance(object, importCache->pandas.DataFrame());
}

bool PyConnection::isPolarsDataframe(const py::handle& object) {
    if (!doesPyModuleExist("polars")) {
        return false;
    }
    return py::isinstance(object, importCache->polars.DataFrame());
}

bool PyConnection::isPyArrowTable(const py::handle& object) {
    if (!doesPyModuleExist("pyarrow")) {
        return false;
    }
    return py::isinstance(object, importCache->pyarrow.lib.Table());
}

static std::unordered_map<std::string, std::unique_ptr<Value>> transformPythonParameters(
    const py::dict& params, Connection* conn) {
    std::unordered_map<std::string, std::unique_ptr<Value>> result;
    for (auto& [key, value] : params) {
        if (!py::isinstance<py::str>(key)) {
            // TODO(Chang): remove ROLLBACK once we can guarantee database is deleted
            // after conn
            conn->query("ROLLBACK");
            throw std::runtime_error("Parameter name must be of type string but got " +
                                     py::str(key.get_type()).cast<std::string>());
        }
        auto name = key.cast<std::string>();
        auto val = std::make_unique<Value>(PyConnection::transformPythonValueFromParameter(value));
        result.insert({name, std::move(val)});
    }
    return result;
}

template<typename T>
bool integerFitsIn(int64_t val);

template<>
bool integerFitsIn<int64_t>(int64_t) {
    return true;
}

template<>
bool integerFitsIn<int32_t>(int64_t val) {
    return val >= INT32_MIN && val <= INT32_MAX;
}

template<>
bool integerFitsIn<int16_t>(int64_t val) {
    return val >= INT16_MIN && val <= INT16_MAX;
}

template<>
bool integerFitsIn<int8_t>(int64_t val) {
    return val >= INT8_MIN && val <= INT8_MAX;
}

template<>
bool integerFitsIn<uint64_t>(int64_t val) {
    return val >= 0;
}

template<>
bool integerFitsIn<uint32_t>(int64_t val) {
    return val >= 0 && val <= UINT32_MAX;
}

template<>
bool integerFitsIn<uint16_t>(int64_t val) {
    return val >= 0 && val <= UINT16_MAX;
}

template<>
bool integerFitsIn<uint8_t>(int64_t val) {
    return val >= 0 && val <= UINT8_MAX;
}

static LogicalType pyHomogeneousListType(const py::list& lst) {
    py::handle firstNonNull;
    for (auto child : lst) {
        if (!child.is_none()) {
            firstNonNull = child;
            break;
        }
    }
    if (!firstNonNull) {
        return LogicalType::LIST(LogicalType::ANY());
    }
    if (!py::isinstance<py::bool_>(firstNonNull) && !py::isinstance<py::int_>(firstNonNull) &&
        !py::isinstance<py::float_>(firstNonNull)) {
        return LogicalType::ANY();
    }
    for (auto child : lst) {
        if (child.is_none()) {
            continue;
        }
        if (child.get_type().ptr() != firstNonNull.get_type().ptr()) {
            return LogicalType::ANY();
        }
    }
    if (py::isinstance<py::bool_>(firstNonNull)) {
        return LogicalType::LIST(LogicalType::BOOL());
    }
    if (py::isinstance<py::int_>(firstNonNull)) {
        return LogicalType::LIST(LogicalType::INT64());
    }
    return LogicalType::LIST(LogicalType::DOUBLE());
}

static LogicalType pyNumpyArrayLogicalType(const py::array& arr) {
    auto npType = NumpyTypeUtils::convertNumpyType(arr.attr("dtype"));
    auto type = NumpyTypeUtils::numpyToLogicalType(npType);
    for (auto i = 0; i < arr.ndim(); ++i) {
        type = LogicalType::LIST(std::move(type));
    }
    return type;
}

static bool hasNumpyTypeModule(const py::handle& val) {
    auto module = py::str(val.get_type().attr("__module__")).cast<std::string>();
    return module == "numpy" || module.starts_with("numpy.");
}

static bool isNumpyArray(const py::handle& val) {
    return hasNumpyTypeModule(val) && py::isinstance<py::array>(val);
}

static LogicalType pyLogicalType(const py::handle& val) {
    auto datetime_datetime = importCache->datetime.datetime();
    auto time_delta = importCache->datetime.timedelta();
    auto datetime_date = importCache->datetime.date();
    auto uuid = importCache->uuid.UUID();
    auto Decimal = importCache->decimal.Decimal();
    if (val.is_none()) {
        return LogicalType::ANY();
    } else if (py::isinstance<py::bool_>(val)) {
        return LogicalType::BOOL();
    } else if (py::isinstance<py::int_>(val)) {
        auto nativeValue = val.cast<int64_t>();
        if (integerFitsIn<int8_t>(nativeValue)) {
            return LogicalType::INT8();
        } else if (integerFitsIn<uint8_t>(nativeValue)) {
            return LogicalType::UINT8();
        } else if (integerFitsIn<int16_t>(nativeValue)) {
            return LogicalType::INT16();
        } else if (integerFitsIn<uint16_t>(nativeValue)) {
            return LogicalType::UINT16();
        } else if (integerFitsIn<int32_t>(nativeValue)) {
            return LogicalType::INT32();
        } else if (integerFitsIn<uint32_t>(nativeValue)) {
            return LogicalType::UINT32();
        } else {
            return LogicalType::INT64();
        }
    } else if (py::isinstance<py::float_>(val)) {
        return LogicalType::DOUBLE();
    } else if (py::isinstance(val, Decimal)) {
        auto as_tuple = val.attr("as_tuple")();
        auto precision = py::len(as_tuple.attr("digits"));
        auto exponent = py::cast<int32_t>(as_tuple.attr("exponent"));
        if (exponent > 0) {
            precision += exponent;
            exponent = 0;
        }
        if (precision > common::DECIMAL_PRECISION_LIMIT) {
            throw common::NotImplementedException(
                std::format("Decimal precision cannot be greater than {}"
                            "Note: positive exponents contribute to precision",
                    common::DECIMAL_PRECISION_LIMIT));
        }
        return LogicalType::DECIMAL(precision, -exponent);
    } else if (py::isinstance<py::str>(val)) {
        return LogicalType::STRING();
    } else if (py::isinstance<py::bytes>(val)) {
        return LogicalType::BLOB();
    } else if (py::isinstance(val, datetime_datetime)) {
        return LogicalType::TIMESTAMP();
    } else if (py::isinstance(val, datetime_date)) {
        return LogicalType::DATE();
    } else if (py::isinstance(val, time_delta)) {
        return LogicalType::INTERVAL();
    } else if (py::isinstance(val, uuid)) {
        return LogicalType::UUID();
    } else if (py::isinstance<py::dict>(val)) {
        py::dict dict = py::reinterpret_borrow<py::dict>(val);
        auto childKeyType = LogicalType::ANY(), childValueType = LogicalType::ANY();
        for (auto child : dict) {
            auto curChildKeyType = pyLogicalType(child.first),
                 curChildValueType = pyLogicalType(child.second);
            LogicalType resultKey, resultValue;
            if (!LogicalTypeUtils::tryGetMaxLogicalType(childKeyType, curChildKeyType, resultKey)) {
                throw RuntimeException(
                    std::format("Cannot convert Python object to Lbug value : {}  is "
                                "incompatible with {}",
                        childKeyType.toString(), curChildKeyType.toString()));
            }
            if (!LogicalTypeUtils::tryGetMaxLogicalType(childValueType, curChildValueType,
                    resultValue)) {
                throw RuntimeException(
                    std::format("Cannot convert Python object to Lbug value : {}  is incompatible "
                                "with {}",
                        childValueType.toString(), curChildValueType.toString()));
            }
            childKeyType = std::move(resultKey);
            childValueType = std::move(resultValue);
        }
        return LogicalType::MAP(std::move(childKeyType), std::move(childValueType));
    } else if (isNumpyArray(val)) {
        return pyNumpyArrayLogicalType(py::reinterpret_borrow<py::array>(val));
    } else if (py::isinstance<py::list>(val)) {
        py::list lst = py::reinterpret_borrow<py::list>(val);
        auto homogeneousType = pyHomogeneousListType(lst);
        if (homogeneousType.getLogicalTypeID() != LogicalTypeID::ANY) {
            return homogeneousType;
        }
        auto childType = LogicalType::ANY();
        for (auto child : lst) {
            auto curChildType = pyLogicalType(child);
            LogicalType result;
            if (!LogicalTypeUtils::tryGetMaxLogicalType(childType, curChildType, result)) {
                throw RuntimeException(
                    std::format("Cannot convert Python object to Lbug value : {}  is "
                                "incompatible with {}",
                        childType.toString(), curChildType.toString()));
            }
            childType = std::move(result);
        }
        return LogicalType::LIST(std::move(childType));
    } else if (PyConnection::isPyArrowTable(val) || PyConnection::isPandasDataframe(val) ||
               PyConnection::isPolarsDataframe(val)) {
        return LogicalType::POINTER();
    } else {
        // LCOV_EXCL_START
        throw common::RuntimeException(
            "Unknown parameter type " + py::str(val.get_type()).cast<std::string>());
        // LCOV_EXCL_STOP
    }
}

static bool validateMapFields(py::dict& dict) {
    for (auto& field : dict) {
        auto keyType = pyLogicalType(field.first).getLogicalTypeID();
        if (keyType != LogicalTypeID::STRING) {
            return false;
        }
        auto valType = pyLogicalType(field.second).getLogicalTypeID();
        if (valType != LogicalTypeID::LIST) {
            return false;
        }
    }
    std::string keyName = py::str(dict.begin()->first);
    if (keyName != "key") {
        return false;
    }
    std::string valueName = py::str((++dict.begin())->first);
    if (valueName != "value") {
        return false;
    }
    return true;
}

static LogicalType pyLogicalTypeFromParameter(const py::handle& val);

// If we want to interpret a python dict as MAP, it has to satisfy the following
// two conditions:
// 1. The dictionary has only two fields.
// 2. The first field name is "key", while the second field name is "value".
// 3. Values of both first and second fields are list of values with the same
// type. Sample: my_map_dict = {
//    "key": [
//        1, 2, 3
//    ],
//    "value": [
//        "one", "two", "three"
//    ]
//  }
static bool tryCastToMap(py::dict& dict, LogicalType& result) {
    if (dict.size() != 2) {
        return false;
    }
    if (!validateMapFields(dict)) {
        return false;
    }
    auto keyList = dict.begin()->second;
    auto valList = (++dict.begin())->second;
    if (py::reinterpret_borrow<py::list>(keyList).size() !=
        py::reinterpret_borrow<py::list>(valList).size()) {
        return false;
    }
    auto keyListType = pyLogicalTypeFromParameter(keyList);
    auto valListType = pyLogicalTypeFromParameter(valList);
    result = LogicalType::MAP(ListType::getChildType(keyListType).copy(),
        ListType::getChildType(valListType).copy());
    return true;
}

static LogicalType pyLogicalTypeFromParameter(const py::handle& val) {
    if (py::isinstance<py::str>(val)) {
        return LogicalType::STRING();
    }
    if (py::isinstance<py::dict>(val)) {
        auto dict = py::reinterpret_borrow<py::dict>(val);
        LogicalType resultType;
        if (tryCastToMap(dict, resultType)) {
            return resultType;
        }
        auto structFields = std::vector<StructField>{};
        for (auto child : dict) {
            auto keyName = py::cast<std::string>(py::str(child.first));
            auto keyType = pyLogicalTypeFromParameter(child.second);
            structFields.emplace_back(std::move(keyName), std::move(keyType));
        }
        return LogicalType::STRUCT(std::move(structFields));
    } else if (isNumpyArray(val)) {
        return pyNumpyArrayLogicalType(py::reinterpret_borrow<py::array>(val));
    } else if (py::isinstance<py::list>(val)) {
        py::list lst = py::reinterpret_borrow<py::list>(val);
        auto homogeneousType = pyHomogeneousListType(lst);
        if (homogeneousType.getLogicalTypeID() != LogicalTypeID::ANY) {
            return homogeneousType;
        }
        auto childType = LogicalType::ANY();
        for (auto child : lst) {
            auto curChildType = pyLogicalTypeFromParameter(child);
            if (childType.getLogicalTypeID() != LogicalTypeID::ANY &&
                childType.getLogicalTypeID() != curChildType.getLogicalTypeID()) {
                if ((LogicalTypeUtils::isNested(childType.getLogicalTypeID()) &&
                        !LogicalTypeUtils::isNested(curChildType.getLogicalTypeID())) ||
                    (!LogicalTypeUtils::isNested(childType.getLogicalTypeID()) &&
                        LogicalTypeUtils::isNested(curChildType.getLogicalTypeID()))) {
                    return LogicalType::JSON();
                }
            }
            LogicalType result;
            if (!LogicalTypeUtils::tryGetMaxLogicalType(childType, curChildType, result)) {
                throw RuntimeException(
                    std::format("Cannot convert Python object to Lbug value : {}  is "
                                "incompatible with {}",
                        childType.toString(), curChildType.toString()));
            }
            childType = std::move(result);
        }
        return LogicalType::LIST(std::move(childType));
    } else {
        return pyLogicalType(val);
    }
}

static std::string pythonObjectToJsonString(const py::handle& val) {
    auto jsonModule = py::module_::import("json");
    auto jsonStr = jsonModule.attr("dumps")(val);
    return py::cast<std::string>(jsonStr);
}

template<typename T>
static Value transformNumpyScalarAs(const void* ptr, const LogicalType& type) {
    auto value = *reinterpret_cast<const T*>(ptr);
    switch (type.getLogicalTypeID()) {
    case LogicalTypeID::BOOL:
        return Value::createValue<bool>(static_cast<bool>(value));
    case LogicalTypeID::INT64:
        return Value::createValue<int64_t>(static_cast<int64_t>(value));
    case LogicalTypeID::UINT32:
        return Value::createValue<uint32_t>(static_cast<uint32_t>(value));
    case LogicalTypeID::INT32:
        return Value::createValue<int32_t>(static_cast<int32_t>(value));
    case LogicalTypeID::UINT16:
        return Value::createValue<uint16_t>(static_cast<uint16_t>(value));
    case LogicalTypeID::INT16:
        return Value::createValue<int16_t>(static_cast<int16_t>(value));
    case LogicalTypeID::UINT8:
        return Value::createValue<uint8_t>(static_cast<uint8_t>(value));
    case LogicalTypeID::INT8:
        return Value::createValue<int8_t>(static_cast<int8_t>(value));
    case LogicalTypeID::FLOAT:
        return Value(static_cast<float>(value));
    case LogicalTypeID::DOUBLE:
        return Value::createValue<double>(static_cast<double>(value));
    default:
        throw RuntimeException("Unsupported numpy ndarray parameter child type " + type.toString());
    }
}

static Value transformNumpyScalarAs(const void* ptr, NumpyNullableType npType,
    const LogicalType& type) {
    switch (npType) {
    case NumpyNullableType::BOOL:
        return transformNumpyScalarAs<bool>(ptr, type);
    case NumpyNullableType::INT_8:
        return transformNumpyScalarAs<int8_t>(ptr, type);
    case NumpyNullableType::UINT_8:
        return transformNumpyScalarAs<uint8_t>(ptr, type);
    case NumpyNullableType::INT_16:
        return transformNumpyScalarAs<int16_t>(ptr, type);
    case NumpyNullableType::UINT_16:
        return transformNumpyScalarAs<uint16_t>(ptr, type);
    case NumpyNullableType::INT_32:
        return transformNumpyScalarAs<int32_t>(ptr, type);
    case NumpyNullableType::UINT_32:
        return transformNumpyScalarAs<uint32_t>(ptr, type);
    case NumpyNullableType::INT_64:
        return transformNumpyScalarAs<int64_t>(ptr, type);
    case NumpyNullableType::UINT_64:
        return transformNumpyScalarAs<uint64_t>(ptr, type);
    case NumpyNullableType::FLOAT_32:
        return transformNumpyScalarAs<float>(ptr, type);
    case NumpyNullableType::FLOAT_64:
        return transformNumpyScalarAs<double>(ptr, type);
    default:
        throw RuntimeException("Unsupported numpy ndarray parameter dtype");
    }
}

static Value transformNumpyArrayAs(const LogicalType& type, uint64_t dimension, const uint8_t* ptr,
    const py::buffer_info& info, NumpyNullableType npType) {
    if (dimension == static_cast<uint64_t>(info.ndim)) {
        return transformNumpyScalarAs(ptr, npType, type);
    }
    if (type.getLogicalTypeID() != LogicalTypeID::LIST) {
        throw RuntimeException("Cannot convert numpy ndarray parameter to " + type.toString());
    }
    std::vector<std::unique_ptr<Value>> children;
    children.reserve(info.shape[dimension]);
    const auto& childType = ListType::getChildType(type);
    for (auto i = 0; i < info.shape[dimension]; ++i) {
        auto childPtr = ptr + i * info.strides[dimension];
        children.push_back(std::make_unique<Value>(
            transformNumpyArrayAs(childType, dimension + 1, childPtr, info, npType)));
    }
    return Value(type.copy(), std::move(children));
}

static Value transformNumpyArrayAs(const py::array& arr, const LogicalType& type) {
    auto info = arr.request();
    auto npType = NumpyTypeUtils::convertNumpyType(arr.attr("dtype")).type;
    return transformNumpyArrayAs(type, 0, reinterpret_cast<const uint8_t*>(info.ptr), info, npType);
}

Value PyConnection::transformPythonValueAs(const py::handle& val, const LogicalType& type) {
    // ignore the type of the actual python object, just directly cast
    auto datetime_datetime = importCache->datetime.datetime();
    auto time_delta = importCache->datetime.timedelta();
    auto datetime_date = importCache->datetime.date();
    if (val.is_none()) {
        return Value::createNullValue(type);
    }
    switch (type.getLogicalTypeID()) {
    case LogicalTypeID::ANY:
        return Value::createNullValue();
    case LogicalTypeID::BOOL:
        return Value::createValue<bool>(py::cast<py::bool_>(val).cast<bool>());
    case LogicalTypeID::INT64:
        return Value::createValue<int64_t>(py::cast<py::int_>(val).cast<int64_t>());
    case LogicalTypeID::UINT32:
        return Value::createValue<uint32_t>(py::cast<py::int_>(val).cast<uint32_t>());
    case LogicalTypeID::INT32:
        return Value::createValue<int32_t>(py::cast<py::int_>(val).cast<int32_t>());
    case LogicalTypeID::UINT16:
        return Value::createValue<uint16_t>(py::cast<py::int_>(val).cast<uint16_t>());
    case LogicalTypeID::INT16:
        return Value::createValue<int16_t>(py::cast<py::int_>(val).cast<int16_t>());
    case LogicalTypeID::UINT8:
        return Value::createValue<uint8_t>(py::cast<py::int_>(val).cast<uint8_t>());
    case LogicalTypeID::INT8:
        return Value::createValue<int8_t>(py::cast<py::int_>(val).cast<int8_t>());
    case LogicalTypeID::DOUBLE:
        return Value::createValue<double>(py::cast<py::float_>(val).cast<double>());
    case LogicalTypeID::FLOAT:
        return Value(py::cast<py::float_>(val).cast<float>());
    case LogicalTypeID::DECIMAL: {
        auto str = py::cast<std::string>(py::str(val));
        int128_t result = 0;
        function::decimalCast(str.c_str(), str.size(), result, type);
        auto val = Value::createDefaultValue(type);
        val.val.int128Val = result;
        return val;
    }
    case LogicalTypeID::STRING:
        if (py::isinstance<py::str>(val)) {
            return Value::createValue<std::string>(val.cast<std::string>());
        }
        return Value::createValue<std::string>(py::str(val));
    case LogicalTypeID::BLOB: {
        auto bytes = py::cast<py::bytes>(val);
        const char* data = PyBytes_AsString(bytes.ptr());
        Py_ssize_t size = PyBytes_Size(bytes.ptr());
        std::string blobStr(data, size);
        return Value(LogicalType::BLOB(), blobStr);
    }
    case LogicalTypeID::TIMESTAMP: {
        // LCOV_EXCL_START
        if (!py::isinstance(val, datetime_datetime)) {
            throw RuntimeException("Error: parameter is not of type datetime.datetime, \
                but was resolved to type datetime.datetime");
        }
        // LCOV_EXCL_STOP
        auto ptr = val.ptr();
        auto year = PyDateTime_GET_YEAR(ptr);
        auto month = PyDateTime_GET_MONTH(ptr);
        auto day = PyDateTime_GET_DAY(ptr);
        auto hour = PyDateTime_DATE_GET_HOUR(ptr);
        auto minute = PyDateTime_DATE_GET_MINUTE(ptr);
        auto second = PyDateTime_DATE_GET_SECOND(ptr);
        auto micros = PyDateTime_DATE_GET_MICROSECOND(ptr);
        auto date = Date::fromDate(year, month, day);
        auto time = Time::fromTime(hour, minute, second, micros);
        return Value::createValue<timestamp_t>(Timestamp::fromDateTime(date, time));
    }
    case LogicalTypeID::DATE: {
        // LCOV_EXCL_START
        if (!py::isinstance(val, datetime_date)) {
            throw RuntimeException("Error: parameter is not of type datetime.date, \
                but was resolved to type datetime.date");
        }
        // LCOV_EXCL_STOP
        auto ptr = val.ptr();
        auto year = PyDateTime_GET_YEAR(ptr);
        auto month = PyDateTime_GET_MONTH(ptr);
        auto day = PyDateTime_GET_DAY(ptr);
        return Value::createValue<date_t>(Date::fromDate(year, month, day));
    }
    case LogicalTypeID::INTERVAL: {
        // LCOV_EXCL_START
        if (!py::isinstance(val, time_delta)) {
            throw RuntimeException("Error: parameter is not of type datetime.timedelta, \
                but was resolved to type datetime.timedelta");
        }
        // LCOV_EXCL_STOP
        auto ptr = val.ptr();
        auto days = PyDateTime_DELTA_GET_DAYS(ptr);
        auto seconds = PyDateTime_DELTA_GET_SECONDS(ptr);
        auto microseconds = PyDateTime_DELTA_GET_MICROSECONDS(ptr);
        interval_t interval;
        Interval::addition(interval, days, "days");
        Interval::addition(interval, seconds, "seconds");
        Interval::addition(interval, microseconds, "microseconds");
        return Value::createValue<interval_t>(interval);
    }
    case LogicalTypeID::UUID: {
        auto strVal = py::str(val).cast<std::string>();
        auto uuidVal = UUID::fromString(strVal);
        uuid uuidToAppend{uuidVal};
        return Value{uuidToAppend};
    }
    case LogicalTypeID::LIST: {
        if (isNumpyArray(val)) {
            return transformNumpyArrayAs(py::reinterpret_borrow<py::array>(val), type);
        }
        py::list lst = py::reinterpret_borrow<py::list>(val);
        std::vector<std::unique_ptr<Value>> children;
        for (auto child : lst) {
            children.push_back(std::make_unique<Value>(
                transformPythonValueAs(child, ListType::getChildType(type))));
        }
        return Value(type.copy(), std::move(children));
    }
    case LogicalTypeID::MAP: {
        py::dict dict = py::reinterpret_borrow<py::dict>(val);
        std::vector<std::unique_ptr<Value>> children;
        const auto& childKeyType = MapType::getKeyType(type);
        const auto& childValueType = MapType::getValueType(type);
        for (auto child : dict) {
            // type construction is inefficient, we have to create duplicates because
            // it asks for a unique ptr
            std::vector<StructField> fields;
            fields.emplace_back(InternalKeyword::MAP_KEY, childKeyType.copy());
            fields.emplace_back(InternalKeyword::MAP_VALUE, childValueType.copy());
            std::vector<std::unique_ptr<Value>> structValues;
            structValues.push_back(
                std::make_unique<Value>(transformPythonValueAs(child.first, childKeyType)));
            structValues.push_back(
                std::make_unique<Value>(transformPythonValueAs(child.second, childValueType)));
            children.push_back(std::make_unique<Value>(LogicalType::STRUCT(std::move(fields)),
                std::move(structValues)));
        }
        return Value(type.copy(), std::move(children));
    }
    case LogicalTypeID::STRUCT: {
        auto dict = py::reinterpret_borrow<py::dict>(val);
        std::vector<std::unique_ptr<Value>> children;
        auto fieldIdx = 0u;
        for (auto field : dict) {
            auto fieldType = StructType::getFieldType(type, fieldIdx++).copy();
            children.push_back(
                std::make_unique<Value>(transformPythonValueAs(field.second, fieldType)));
        }
        return Value(type.copy(), std::move(children));
    }
    // LCOV_EXCL_START
    default:
        UNREACHABLE_CODE;
        // LCOV_EXCL_STOP
    }
}

Value PyConnection::transformPythonValueFromParameterAs(const py::handle& val,
    const LogicalType& type) {
    switch (type.getLogicalTypeID()) {
    case LogicalTypeID::LIST: {
        if (ListType::getChildType(type).getLogicalTypeID() == LogicalTypeID::JSON) {
            auto jsonStr = pythonObjectToJsonString(val);
            return Value::createValue<std::string>(jsonStr);
        }
        if (isNumpyArray(val)) {
            return transformNumpyArrayAs(py::reinterpret_borrow<py::array>(val), type);
        }
        py::list lst = py::reinterpret_borrow<py::list>(val);
        std::vector<std::unique_ptr<Value>> children;
        for (auto child : lst) {
            children.push_back(std::make_unique<Value>(
                transformPythonValueFromParameterAs(child, ListType::getChildType(type))));
        }
        return Value(type.copy(), std::move(children));
    }
    case LogicalTypeID::MAP: {
        auto dict = py::reinterpret_borrow<py::dict>(val);
        std::vector<std::unique_ptr<Value>> children;
        auto keys = transformPythonValueFromParameter(
            py::reinterpret_borrow<py::list>(dict.begin()->second));
        auto vals = transformPythonValueFromParameter(
            py::reinterpret_borrow<py::list>((++dict.begin())->second));
        auto numKeys = NestedVal::getChildrenSize(&keys);
        // LCOV_EXCL_START
        if (NestedVal::getChildrenSize(&keys) != NestedVal::getChildrenSize(&vals)) {
            throw RuntimeException("Map Key and Value lengths do not match!");
        }
        // LCOV_EXCL_STOP
        for (auto i = 0u; i < numKeys; i++) {
            std::vector<std::unique_ptr<Value>> structValues;
            structValues.push_back(NestedVal::getChildVal(&keys, i)->copy());
            structValues.push_back(NestedVal::getChildVal(&vals, i)->copy());
            children.push_back(std::make_unique<Value>(ListType::getChildType(type).copy(),
                std::move(structValues)));
        }
        return Value(type.copy(), std::move(children));
    }
    case LogicalTypeID::STRUCT: {
        auto dict = py::reinterpret_borrow<py::dict>(val);
        std::vector<std::unique_ptr<Value>> children;
        auto fieldIdx = 0u;
        for (auto field : dict) {
            auto fieldType = StructType::getFieldType(type, fieldIdx++).copy();
            children.push_back(std::make_unique<Value>(
                transformPythonValueFromParameterAs(field.second, fieldType)));
        }
        return Value(type.copy(), std::move(children));
    }
    case LogicalTypeID::JSON: {
        if (py::isinstance<py::str>(val)) {
            return Value::createValue<std::string>(py::cast<std::string>(val));
        }
        auto jsonStr = pythonObjectToJsonString(val);
        return Value::createValue<std::string>(jsonStr);
    }
    case LogicalTypeID::POINTER: {
        return Value::createValue(reinterpret_cast<uint8_t*>(val.ptr()));
    }
    default:
        return transformPythonValueAs(val, type);
    }
}

Value PyConnection::transformPythonValue(const py::handle& val) {
    auto type = pyLogicalType(val);
    return transformPythonValueAs(val, type);
}

Value PyConnection::transformPythonValueFromParameter(const py::handle& val) {
    auto type = pyLogicalTypeFromParameter(val);
    return transformPythonValueFromParameterAs(val, type);
}

std::unique_ptr<PyQueryResult> PyConnection::checkAndWrapQueryResult(
    std::unique_ptr<QueryResult>& queryResult, std::shared_ptr<PyConnectionState> state) {
    if (!queryResult->isSuccess()) {
        throw std::runtime_error(queryResult->getErrorMessage());
    }
    auto pyQueryResult = std::make_unique<PyQueryResult>();
    pyQueryResult->state = std::make_shared<PyQueryResultState>();
    pyQueryResult->state->connection = std::move(state);
    pyQueryResult->state->owned = std::move(queryResult);
    return pyQueryResult;
}

void PyConnection::createScalarFunction(const std::string& name, const py::function& udf,
    const py::list& params, const std::string& retval, bool defaultNull, bool catchExceptions) {
    auto& stateRef = refState();
    stateRef.ref().addUDFFunctionSet(name,
        PyUDF::toFunctionSet(name, udf, params, retval, defaultNull, catchExceptions,
            stateRef.ref().getClientContext()));
}

void PyConnection::removeScalarFunction(const std::string& name) {
    refState().ref().removeUDFFunction(name);
}

struct ExportedArrowTable {
    ArrowSchemaWrapper schema;
    std::vector<ArrowArrayWrapper> arrays;
    py::list keepAlive;
};

static py::object normalizeArrowTable(py::object arrowTable) {
    if (PyConnection::isPandasDataframe(arrowTable)) {
        return importCache->pyarrow.lib.Table.from_pandas()(arrowTable);
    }
    if (PyConnection::isPolarsDataframe(arrowTable)) {
        return arrowTable.attr("to_arrow")();
    }
    if (!PyConnection::isPyArrowTable(arrowTable)) {
        throw RuntimeException("Expected a pyarrow Table, polars DataFrame, or pandas DataFrame");
    }
    return arrowTable;
}

static ExportedArrowTable exportArrowTable(py::object arrowTable) {
    arrowTable = normalizeArrowTable(std::move(arrowTable));

    ExportedArrowTable exported;
    arrowTable.attr("schema").attr("_export_to_c")(reinterpret_cast<uint64_t>(&exported.schema));

    py::list batches = arrowTable.attr("to_batches")();
    for (auto& batch : batches) {
        exported.arrays.emplace_back();
        batch.attr("_export_to_c")(reinterpret_cast<uint64_t>(&exported.arrays.back()));
    }

    // Keep pyarrow producers alive while C++ accesses exported Arrow memory.
    exported.keepAlive.append(arrowTable);
    exported.keepAlive.append(batches);
    return exported;
}

std::unique_ptr<PyQueryResult> PyConnection::createArrowTable(const std::string& tableName,
    py::object arrowTable) {
    auto& stateRef = refState();
    py::gil_scoped_acquire acquire;

    auto exported = exportArrowTable(std::move(arrowTable));
    auto result = ArrowTableSupport::createViewFromArrowTable(stateRef.ref(), tableName,
        std::move(exported.schema), std::move(exported.arrays));
    if (result.queryResult && result.queryResult->isSuccess()) {
        stateRef.arrowTableRefs[tableName] = std::move(exported.keepAlive);
    }

    return checkAndWrapQueryResult(result.queryResult, state);
}

std::unique_ptr<PyQueryResult> PyConnection::createArrowRelTable(const std::string& tableName,
    py::object arrowTable, const std::string& srcTableName, const std::string& dstTableName,
    const std::string& layout, py::object indptrTable, const std::string& dstColName) {
    auto& stateRef = refState();
    py::gil_scoped_acquire acquire;

    auto layoutUpper = layout;
    std::transform(layoutUpper.begin(), layoutUpper.end(), layoutUpper.begin(),
        [](unsigned char c) { return static_cast<char>(std::toupper(c)); });

    auto exported = exportArrowTable(std::move(arrowTable));
    ArrowTableCreationResult result;
    py::list keepAlive;
    keepAlive.append(exported.keepAlive);

    if (layoutUpper == "FLAT") {
        if (!py::none().is(indptrTable)) {
            throw RuntimeException("indptr_table is only valid for CSR Arrow relationship tables");
        }
        result = ArrowTableSupport::createRelTableFromArrowTable(stateRef.ref(), tableName,
            srcTableName, dstTableName, std::move(exported.schema), std::move(exported.arrays));
    } else if (layoutUpper == "CSR") {
        if (py::none().is(indptrTable)) {
            throw RuntimeException("indptr_table is required for CSR Arrow relationship tables");
        }
        auto exportedIndptr = exportArrowTable(std::move(indptrTable));
        keepAlive.append(exportedIndptr.keepAlive);
        result = ArrowTableSupport::createRelTableFromArrowCSR(stateRef.ref(), tableName,
            srcTableName, dstTableName, std::move(exported.schema), std::move(exported.arrays),
            std::move(exportedIndptr.schema), std::move(exportedIndptr.arrays), dstColName);
    } else {
        throw RuntimeException("Arrow relationship table layout must be FLAT or CSR");
    }
    if (result.queryResult && result.queryResult->isSuccess()) {
        stateRef.arrowTableRefs[tableName] = std::move(keepAlive);
    }

    return checkAndWrapQueryResult(result.queryResult, state);
}

std::unique_ptr<PyQueryResult> PyConnection::dropArrowTable(const std::string& tableName) {
    auto& stateRef = refState();
    auto result = ArrowTableSupport::unregisterArrowTable(stateRef.ref(), tableName);
    if (result && result->isSuccess()) {
        stateRef.arrowTableRefs.erase(tableName);
    }
    return checkAndWrapQueryResult(result, state);
}
