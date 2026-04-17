from __future__ import annotations

import ctypes
import ctypes.util
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any


class _LbugSystemConfig(ctypes.Structure):
    _fields_: list[tuple[str, Any]] = [
        ("buffer_pool_size", ctypes.c_uint64),
        ("max_num_threads", ctypes.c_uint64),
        ("enable_compression", ctypes.c_bool),
        ("read_only", ctypes.c_bool),
        ("max_db_size", ctypes.c_uint64),
        ("auto_checkpoint", ctypes.c_bool),
        ("checkpoint_threshold", ctypes.c_uint64),
        ("throw_on_wal_replay_failure", ctypes.c_bool),
        ("enable_checksums", ctypes.c_bool),
    ]
    if sys.platform == "darwin":
        _fields_.append(("thread_qos", ctypes.c_uint32))


class _LbugDatabase(ctypes.Structure):
    _fields_ = [("_database", ctypes.c_void_p)]


class _LbugConnection(ctypes.Structure):
    _fields_ = [("_connection", ctypes.c_void_p)]


class _LbugPreparedStatement(ctypes.Structure):
    _fields_ = [
        ("_prepared_statement", ctypes.c_void_p),
        ("_bound_values", ctypes.c_void_p),
    ]


class _LbugQueryResult(ctypes.Structure):
    _fields_ = [
        ("_query_result", ctypes.c_void_p),
        ("_is_owned_by_cpp", ctypes.c_bool),
    ]


class _LbugFlatTuple(ctypes.Structure):
    _fields_ = [
        ("_flat_tuple", ctypes.c_void_p),
        ("_is_owned_by_cpp", ctypes.c_bool),
    ]


class _LbugLogicalType(ctypes.Structure):
    _fields_ = [("_data_type", ctypes.c_void_p)]


class _LbugValue(ctypes.Structure):
    _fields_ = [
        ("_value", ctypes.c_void_p),
        ("_is_owned_by_cpp", ctypes.c_bool),
    ]


class _LbugQuerySummary(ctypes.Structure):
    _fields_ = [("_query_summary", ctypes.c_void_p)]


class _LbugInternalID(ctypes.Structure):
    _fields_ = [("table_id", ctypes.c_uint64), ("offset", ctypes.c_uint64)]


class _LbugDate(ctypes.Structure):
    _fields_ = [("days", ctypes.c_int32)]


class _LbugTimestamp(ctypes.Structure):
    _fields_ = [("value", ctypes.c_int64)]


class _LbugInterval(ctypes.Structure):
    _fields_ = [("months", ctypes.c_int32), ("days", ctypes.c_int32), ("micros", ctypes.c_int64)]


def _resolve_library_path() -> str:
    override = os.getenv("LBUG_C_API_LIB_PATH")
    if override:
        return override

    module_path = Path(__file__).resolve()
    candidate_roots = [
        module_path.parent.parent,
        module_path.parent.parent.parent,
        Path.cwd(),
    ]
    search_dirs: list[Path] = []
    for root in candidate_roots:
        search_dirs.extend(
            [
                root / ".cache" / "lbug-prebuilt" / "lib",
                root / "lib",
            ]
        )

    if sys.platform == "darwin":
        names = ["liblbug.dylib", "liblbug.0.dylib"]
    elif sys.platform.startswith("linux"):
        names = ["liblbug.so", "liblbug.so.0"]
    else:
        names = ["lbug_shared.dll", "lbug.dll"]

    for directory in search_dirs:
        for name in names:
            candidate = directory / name
            if candidate.exists():
                return str(candidate)

    found = ctypes.util.find_library("lbug") or ctypes.util.find_library("lbug_shared")
    if found:
        return found

    msg = (
        "Could not find lbug C API shared library. "
        "Set LBUG_C_API_LIB_PATH or download a shared lib (e.g. run "
        "LBUG_LIB_KIND=shared bash scripts/download_lbug.sh)."
    )
    raise RuntimeError(msg)


_LIB = ctypes.CDLL(_resolve_library_path())

_LBUG_SUCCESS = 0

# Data type IDs from lbug.h
_LBUG_ANY = 0
_LBUG_NODE = 10
_LBUG_REL = 11
_LBUG_RECURSIVE_REL = 12
_LBUG_SERIAL = 13
_LBUG_BOOL = 22
_LBUG_INT64 = 23
_LBUG_INT32 = 24
_LBUG_INT16 = 25
_LBUG_INT8 = 26
_LBUG_UINT64 = 27
_LBUG_UINT32 = 28
_LBUG_UINT16 = 29
_LBUG_UINT8 = 30
_LBUG_INT128 = 31
_LBUG_DOUBLE = 32
_LBUG_FLOAT = 33
_LBUG_DATE = 34
_LBUG_TIMESTAMP = 35
_LBUG_TIMESTAMP_SEC = 36
_LBUG_TIMESTAMP_MS = 37
_LBUG_TIMESTAMP_NS = 38
_LBUG_TIMESTAMP_TZ = 39
_LBUG_INTERVAL = 40
_LBUG_DECIMAL = 41
_LBUG_INTERNAL_ID = 42
_LBUG_STRING = 50
_LBUG_BLOB = 51
_LBUG_LIST = 52
_LBUG_ARRAY = 53
_LBUG_STRUCT = 54
_LBUG_MAP = 55
_LBUG_UNION = 56
_LBUG_UUID = 59


def _setup_signatures() -> None:
    _LIB.lbug_destroy_string.argtypes = [ctypes.c_void_p]

    _LIB.lbug_get_last_error.argtypes = []
    _LIB.lbug_get_last_error.restype = ctypes.c_void_p

    _LIB.lbug_get_version.argtypes = []
    _LIB.lbug_get_version.restype = ctypes.c_void_p
    _LIB.lbug_get_storage_version.argtypes = []
    _LIB.lbug_get_storage_version.restype = ctypes.c_uint64

    _LIB.lbug_default_system_config.argtypes = []
    _LIB.lbug_default_system_config.restype = _LbugSystemConfig

    _LIB.lbug_database_init.argtypes = [ctypes.c_char_p, _LbugSystemConfig, ctypes.POINTER(_LbugDatabase)]
    _LIB.lbug_database_init.restype = ctypes.c_int
    _LIB.lbug_database_destroy.argtypes = [ctypes.POINTER(_LbugDatabase)]

    _LIB.lbug_connection_init.argtypes = [ctypes.POINTER(_LbugDatabase), ctypes.POINTER(_LbugConnection)]
    _LIB.lbug_connection_init.restype = ctypes.c_int
    _LIB.lbug_connection_destroy.argtypes = [ctypes.POINTER(_LbugConnection)]

    _LIB.lbug_connection_set_max_num_thread_for_exec.argtypes = [ctypes.POINTER(_LbugConnection), ctypes.c_uint64]
    _LIB.lbug_connection_set_max_num_thread_for_exec.restype = ctypes.c_int
    _LIB.lbug_connection_set_query_timeout.argtypes = [ctypes.POINTER(_LbugConnection), ctypes.c_uint64]
    _LIB.lbug_connection_set_query_timeout.restype = ctypes.c_int
    _LIB.lbug_connection_interrupt.argtypes = [ctypes.POINTER(_LbugConnection)]

    _LIB.lbug_connection_query.argtypes = [ctypes.POINTER(_LbugConnection), ctypes.c_char_p, ctypes.POINTER(_LbugQueryResult)]
    _LIB.lbug_connection_query.restype = ctypes.c_int

    _LIB.lbug_connection_prepare.argtypes = [
        ctypes.POINTER(_LbugConnection),
        ctypes.c_char_p,
        ctypes.POINTER(_LbugPreparedStatement),
    ]
    _LIB.lbug_connection_prepare.restype = ctypes.c_int

    _LIB.lbug_connection_execute.argtypes = [
        ctypes.POINTER(_LbugConnection),
        ctypes.POINTER(_LbugPreparedStatement),
        ctypes.POINTER(_LbugQueryResult),
    ]
    _LIB.lbug_connection_execute.restype = ctypes.c_int

    _LIB.lbug_prepared_statement_destroy.argtypes = [ctypes.POINTER(_LbugPreparedStatement)]
    _LIB.lbug_prepared_statement_is_success.argtypes = [ctypes.POINTER(_LbugPreparedStatement)]
    _LIB.lbug_prepared_statement_is_success.restype = ctypes.c_bool
    _LIB.lbug_prepared_statement_get_error_message.argtypes = [ctypes.POINTER(_LbugPreparedStatement)]
    _LIB.lbug_prepared_statement_get_error_message.restype = ctypes.c_void_p

    _LIB.lbug_prepared_statement_bind_bool.argtypes = [ctypes.POINTER(_LbugPreparedStatement), ctypes.c_char_p, ctypes.c_bool]
    _LIB.lbug_prepared_statement_bind_bool.restype = ctypes.c_int
    _LIB.lbug_prepared_statement_bind_int64.argtypes = [ctypes.POINTER(_LbugPreparedStatement), ctypes.c_char_p, ctypes.c_int64]
    _LIB.lbug_prepared_statement_bind_int64.restype = ctypes.c_int
    _LIB.lbug_prepared_statement_bind_double.argtypes = [ctypes.POINTER(_LbugPreparedStatement), ctypes.c_char_p, ctypes.c_double]
    _LIB.lbug_prepared_statement_bind_double.restype = ctypes.c_int
    _LIB.lbug_prepared_statement_bind_string.argtypes = [ctypes.POINTER(_LbugPreparedStatement), ctypes.c_char_p, ctypes.c_char_p]
    _LIB.lbug_prepared_statement_bind_string.restype = ctypes.c_int
    _LIB.lbug_prepared_statement_bind_value.argtypes = [ctypes.POINTER(_LbugPreparedStatement), ctypes.c_char_p, ctypes.POINTER(_LbugValue)]
    _LIB.lbug_prepared_statement_bind_value.restype = ctypes.c_int

    _LIB.lbug_value_create_null.argtypes = []
    _LIB.lbug_value_create_null.restype = ctypes.POINTER(_LbugValue)
    _LIB.lbug_value_create_bool.argtypes = [ctypes.c_bool]
    _LIB.lbug_value_create_bool.restype = ctypes.POINTER(_LbugValue)
    _LIB.lbug_value_create_int64.argtypes = [ctypes.c_int64]
    _LIB.lbug_value_create_int64.restype = ctypes.POINTER(_LbugValue)
    _LIB.lbug_value_create_double.argtypes = [ctypes.c_double]
    _LIB.lbug_value_create_double.restype = ctypes.POINTER(_LbugValue)
    _LIB.lbug_value_create_string.argtypes = [ctypes.c_char_p]
    _LIB.lbug_value_create_string.restype = ctypes.POINTER(_LbugValue)
    _LIB.lbug_value_create_date.argtypes = [_LbugDate]
    _LIB.lbug_value_create_date.restype = ctypes.POINTER(_LbugValue)
    _LIB.lbug_value_create_timestamp.argtypes = [_LbugTimestamp]
    _LIB.lbug_value_create_timestamp.restype = ctypes.POINTER(_LbugValue)
    _LIB.lbug_value_create_timestamp_tz.argtypes = [_LbugTimestamp]
    _LIB.lbug_value_create_timestamp_tz.restype = ctypes.POINTER(_LbugValue)
    _LIB.lbug_value_create_interval.argtypes = [_LbugInterval]
    _LIB.lbug_value_create_interval.restype = ctypes.POINTER(_LbugValue)
    _LIB.lbug_value_create_list.argtypes = [
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.POINTER(_LbugValue)),
        ctypes.POINTER(ctypes.POINTER(_LbugValue)),
    ]
    _LIB.lbug_value_create_list.restype = ctypes.c_int
    _LIB.lbug_value_create_struct.argtypes = [
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_char_p),
        ctypes.POINTER(ctypes.POINTER(_LbugValue)),
        ctypes.POINTER(ctypes.POINTER(_LbugValue)),
    ]
    _LIB.lbug_value_create_struct.restype = ctypes.c_int
    _LIB.lbug_value_create_map.argtypes = [
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.POINTER(_LbugValue)),
        ctypes.POINTER(ctypes.POINTER(_LbugValue)),
        ctypes.POINTER(ctypes.POINTER(_LbugValue)),
    ]
    _LIB.lbug_value_create_map.restype = ctypes.c_int
    _LIB.lbug_value_destroy.argtypes = [ctypes.POINTER(_LbugValue)]

    _LIB.lbug_query_result_destroy.argtypes = [ctypes.POINTER(_LbugQueryResult)]
    _LIB.lbug_query_result_is_success.argtypes = [ctypes.POINTER(_LbugQueryResult)]
    _LIB.lbug_query_result_is_success.restype = ctypes.c_bool
    _LIB.lbug_query_result_get_error_message.argtypes = [ctypes.POINTER(_LbugQueryResult)]
    _LIB.lbug_query_result_get_error_message.restype = ctypes.c_void_p
    _LIB.lbug_query_result_get_num_columns.argtypes = [ctypes.POINTER(_LbugQueryResult)]
    _LIB.lbug_query_result_get_num_columns.restype = ctypes.c_uint64
    _LIB.lbug_query_result_get_column_name.argtypes = [ctypes.POINTER(_LbugQueryResult), ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)]
    _LIB.lbug_query_result_get_column_name.restype = ctypes.c_int
    _LIB.lbug_query_result_get_column_data_type.argtypes = [ctypes.POINTER(_LbugQueryResult), ctypes.c_uint64, ctypes.POINTER(_LbugLogicalType)]
    _LIB.lbug_query_result_get_column_data_type.restype = ctypes.c_int
    _LIB.lbug_query_result_get_num_tuples.argtypes = [ctypes.POINTER(_LbugQueryResult)]
    _LIB.lbug_query_result_get_num_tuples.restype = ctypes.c_uint64
    _LIB.lbug_query_result_has_next.argtypes = [ctypes.POINTER(_LbugQueryResult)]
    _LIB.lbug_query_result_has_next.restype = ctypes.c_bool
    _LIB.lbug_query_result_get_next.argtypes = [ctypes.POINTER(_LbugQueryResult), ctypes.POINTER(_LbugFlatTuple)]
    _LIB.lbug_query_result_get_next.restype = ctypes.c_int
    _LIB.lbug_query_result_has_next_query_result.argtypes = [ctypes.POINTER(_LbugQueryResult)]
    _LIB.lbug_query_result_has_next_query_result.restype = ctypes.c_bool
    _LIB.lbug_query_result_get_next_query_result.argtypes = [ctypes.POINTER(_LbugQueryResult), ctypes.POINTER(_LbugQueryResult)]
    _LIB.lbug_query_result_get_next_query_result.restype = ctypes.c_int
    _LIB.lbug_query_result_reset_iterator.argtypes = [ctypes.POINTER(_LbugQueryResult)]
    _LIB.lbug_query_result_get_query_summary.argtypes = [ctypes.POINTER(_LbugQueryResult), ctypes.POINTER(_LbugQuerySummary)]
    _LIB.lbug_query_result_get_query_summary.restype = ctypes.c_int

    _LIB.lbug_query_summary_destroy.argtypes = [ctypes.POINTER(_LbugQuerySummary)]
    _LIB.lbug_query_summary_get_compiling_time.argtypes = [ctypes.POINTER(_LbugQuerySummary)]
    _LIB.lbug_query_summary_get_compiling_time.restype = ctypes.c_double
    _LIB.lbug_query_summary_get_execution_time.argtypes = [ctypes.POINTER(_LbugQuerySummary)]
    _LIB.lbug_query_summary_get_execution_time.restype = ctypes.c_double

    _LIB.lbug_flat_tuple_destroy.argtypes = [ctypes.POINTER(_LbugFlatTuple)]
    _LIB.lbug_flat_tuple_get_value.argtypes = [ctypes.POINTER(_LbugFlatTuple), ctypes.c_uint64, ctypes.POINTER(_LbugValue)]
    _LIB.lbug_flat_tuple_get_value.restype = ctypes.c_int

    _LIB.lbug_value_is_null.argtypes = [ctypes.POINTER(_LbugValue)]
    _LIB.lbug_value_is_null.restype = ctypes.c_bool
    _LIB.lbug_value_get_data_type.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(_LbugLogicalType)]
    _LIB.lbug_data_type_get_id.argtypes = [ctypes.POINTER(_LbugLogicalType)]
    _LIB.lbug_data_type_get_id.restype = ctypes.c_int
    _LIB.lbug_data_type_get_child_type.argtypes = [ctypes.POINTER(_LbugLogicalType), ctypes.POINTER(_LbugLogicalType)]
    _LIB.lbug_data_type_get_child_type.restype = ctypes.c_int
    _LIB.lbug_data_type_get_num_elements_in_array.argtypes = [ctypes.POINTER(_LbugLogicalType), ctypes.POINTER(ctypes.c_uint64)]
    _LIB.lbug_data_type_get_num_elements_in_array.restype = ctypes.c_int
    _LIB.lbug_data_type_destroy.argtypes = [ctypes.POINTER(_LbugLogicalType)]

    _LIB.lbug_value_get_bool.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_bool)]
    _LIB.lbug_value_get_bool.restype = ctypes.c_int
    _LIB.lbug_value_get_int64.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_int64)]
    _LIB.lbug_value_get_int64.restype = ctypes.c_int
    _LIB.lbug_value_get_int32.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_int32)]
    _LIB.lbug_value_get_int32.restype = ctypes.c_int
    _LIB.lbug_value_get_int16.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_int16)]
    _LIB.lbug_value_get_int16.restype = ctypes.c_int
    _LIB.lbug_value_get_int8.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_int8)]
    _LIB.lbug_value_get_int8.restype = ctypes.c_int
    _LIB.lbug_value_get_uint64.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_uint64)]
    _LIB.lbug_value_get_uint64.restype = ctypes.c_int
    _LIB.lbug_value_get_uint32.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_uint32)]
    _LIB.lbug_value_get_uint32.restype = ctypes.c_int
    _LIB.lbug_value_get_uint16.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_uint16)]
    _LIB.lbug_value_get_uint16.restype = ctypes.c_int
    _LIB.lbug_value_get_uint8.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_uint8)]
    _LIB.lbug_value_get_uint8.restype = ctypes.c_int
    _LIB.lbug_value_get_double.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_double)]
    _LIB.lbug_value_get_double.restype = ctypes.c_int
    _LIB.lbug_value_get_float.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_float)]
    _LIB.lbug_value_get_float.restype = ctypes.c_int
    _LIB.lbug_value_get_string.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_void_p)]
    _LIB.lbug_value_get_string.restype = ctypes.c_int
    _LIB.lbug_value_get_uuid.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_void_p)]
    _LIB.lbug_value_get_uuid.restype = ctypes.c_int
    _LIB.lbug_value_get_decimal_as_string.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_void_p)]
    _LIB.lbug_value_get_decimal_as_string.restype = ctypes.c_int
    _LIB.lbug_value_get_blob.argtypes = [
        ctypes.POINTER(_LbugValue),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
        ctypes.POINTER(ctypes.c_uint64),
    ]
    _LIB.lbug_value_get_blob.restype = ctypes.c_int

    _LIB.lbug_value_get_internal_id.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(_LbugInternalID)]
    _LIB.lbug_value_get_internal_id.restype = ctypes.c_int
    _LIB.lbug_value_get_date.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(_LbugDate)]
    _LIB.lbug_value_get_date.restype = ctypes.c_int
    _LIB.lbug_value_get_timestamp.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(_LbugTimestamp)]
    _LIB.lbug_value_get_timestamp.restype = ctypes.c_int
    _LIB.lbug_value_get_timestamp_ns.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(_LbugTimestamp)]
    _LIB.lbug_value_get_timestamp_ns.restype = ctypes.c_int
    _LIB.lbug_value_get_timestamp_ms.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(_LbugTimestamp)]
    _LIB.lbug_value_get_timestamp_ms.restype = ctypes.c_int
    _LIB.lbug_value_get_timestamp_sec.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(_LbugTimestamp)]
    _LIB.lbug_value_get_timestamp_sec.restype = ctypes.c_int
    _LIB.lbug_value_get_timestamp_tz.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(_LbugTimestamp)]
    _LIB.lbug_value_get_timestamp_tz.restype = ctypes.c_int
    _LIB.lbug_value_get_interval.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(_LbugInterval)]
    _LIB.lbug_value_get_interval.restype = ctypes.c_int

    _LIB.lbug_value_get_list_size.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_uint64)]
    _LIB.lbug_value_get_list_size.restype = ctypes.c_int
    _LIB.lbug_value_get_list_element.argtypes = [ctypes.POINTER(_LbugValue), ctypes.c_uint64, ctypes.POINTER(_LbugValue)]
    _LIB.lbug_value_get_list_element.restype = ctypes.c_int

    _LIB.lbug_value_get_struct_num_fields.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_uint64)]
    _LIB.lbug_value_get_struct_num_fields.restype = ctypes.c_int
    _LIB.lbug_value_get_struct_field_name.argtypes = [ctypes.POINTER(_LbugValue), ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)]
    _LIB.lbug_value_get_struct_field_name.restype = ctypes.c_int
    _LIB.lbug_value_get_struct_field_value.argtypes = [ctypes.POINTER(_LbugValue), ctypes.c_uint64, ctypes.POINTER(_LbugValue)]
    _LIB.lbug_value_get_struct_field_value.restype = ctypes.c_int

    _LIB.lbug_value_get_map_size.argtypes = [ctypes.POINTER(_LbugValue), ctypes.POINTER(ctypes.c_uint64)]
    _LIB.lbug_value_get_map_size.restype = ctypes.c_int
    _LIB.lbug_value_get_map_key.argtypes = [ctypes.POINTER(_LbugValue), ctypes.c_uint64, ctypes.POINTER(_LbugValue)]
    _LIB.lbug_value_get_map_key.restype = ctypes.c_int
    _LIB.lbug_value_get_map_value.argtypes = [ctypes.POINTER(_LbugValue), ctypes.c_uint64, ctypes.POINTER(_LbugValue)]
    _LIB.lbug_value_get_map_value.restype = ctypes.c_int

    _LIB.lbug_value_to_string.argtypes = [ctypes.POINTER(_LbugValue)]
    _LIB.lbug_value_to_string.restype = ctypes.c_void_p

    _LIB.lbug_destroy_blob.argtypes = [ctypes.POINTER(ctypes.c_uint8)]


_setup_signatures()


def _consume_last_error() -> str | None:
    ptr = _LIB.lbug_get_last_error()
    if not ptr:
        return None
    try:
        raw = ctypes.cast(ptr, ctypes.c_char_p).value or b""
        return raw.decode("utf-8", errors="replace")
    finally:
        _LIB.lbug_destroy_string(ptr)


def _decode_c_string(ptr: ctypes.c_void_p) -> str:
    if not ptr:
        return ""
    try:
        raw = ctypes.cast(ptr, ctypes.c_char_p).value or b""
        return raw.decode("utf-8", errors="replace")
    finally:
        _LIB.lbug_destroy_string(ptr)


def _check_state(state: int, context: str) -> None:
    if state == _LBUG_SUCCESS:
        return
    msg = _consume_last_error() or context
    raise RuntimeError(msg)


_TYPE_ID_TO_NAME: dict[int, str] = {
    _LBUG_ANY: "ANY",
    _LBUG_NODE: "NODE",
    _LBUG_REL: "REL",
    _LBUG_RECURSIVE_REL: "RECURSIVE_REL",
    _LBUG_SERIAL: "SERIAL",
    _LBUG_BOOL: "BOOL",
    _LBUG_INT64: "INT64",
    _LBUG_INT32: "INT32",
    _LBUG_INT16: "INT16",
    _LBUG_INT8: "INT8",
    _LBUG_UINT64: "UINT64",
    _LBUG_UINT32: "UINT32",
    _LBUG_UINT16: "UINT16",
    _LBUG_UINT8: "UINT8",
    _LBUG_INT128: "INT128",
    _LBUG_DOUBLE: "DOUBLE",
    _LBUG_FLOAT: "FLOAT",
    _LBUG_DATE: "DATE",
    _LBUG_TIMESTAMP: "TIMESTAMP",
    _LBUG_TIMESTAMP_SEC: "TIMESTAMP_SEC",
    _LBUG_TIMESTAMP_MS: "TIMESTAMP_MS",
    _LBUG_TIMESTAMP_NS: "TIMESTAMP_NS",
    _LBUG_TIMESTAMP_TZ: "TIMESTAMP_TZ",
    _LBUG_INTERVAL: "INTERVAL",
    _LBUG_DECIMAL: "DECIMAL",
    _LBUG_INTERNAL_ID: "INTERNAL_ID",
    _LBUG_STRING: "STRING",
    _LBUG_BLOB: "BLOB",
    _LBUG_LIST: "LIST",
    _LBUG_ARRAY: "ARRAY",
    _LBUG_STRUCT: "STRUCT",
    _LBUG_MAP: "MAP",
    _LBUG_UNION: "UNION",
    _LBUG_UUID: "UUID",
}


def _logical_type_to_str(logical_type: _LbugLogicalType) -> str:
    type_id = _LIB.lbug_data_type_get_id(ctypes.byref(logical_type))
    if type_id == _LBUG_LIST:
        child = _LbugLogicalType()
        _check_state(_LIB.lbug_data_type_get_child_type(ctypes.byref(logical_type), ctypes.byref(child)), "Failed to read LIST child type")
        try:
            return f"{_logical_type_to_str(child)}[]"
        finally:
            _LIB.lbug_data_type_destroy(ctypes.byref(child))
    if type_id == _LBUG_ARRAY:
        child = _LbugLogicalType()
        size = ctypes.c_uint64(0)
        _check_state(_LIB.lbug_data_type_get_child_type(ctypes.byref(logical_type), ctypes.byref(child)), "Failed to read ARRAY child type")
        _check_state(
            _LIB.lbug_data_type_get_num_elements_in_array(ctypes.byref(logical_type), ctypes.byref(size)),
            "Failed to read ARRAY size",
        )
        try:
            return f"{_logical_type_to_str(child)}[{size.value}]"
        finally:
            _LIB.lbug_data_type_destroy(ctypes.byref(child))
    return _TYPE_ID_TO_NAME.get(type_id, f"UNKNOWN({type_id})")


def _to_datetime_from_micros(value: int, *, tz_aware: bool = False) -> dt.datetime:
    seconds = value / 1_000_000
    utc_dt = dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)
    if tz_aware:
        return utc_dt
    return utc_dt.replace(tzinfo=None)


def _value_from_python(value: Any) -> ctypes.POINTER(_LbugValue):
    if value is None:
        return _LIB.lbug_value_create_null()
    if isinstance(value, bool):
        return _LIB.lbug_value_create_bool(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return _LIB.lbug_value_create_int64(value)
    if isinstance(value, float):
        return _LIB.lbug_value_create_double(value)
    if isinstance(value, str):
        return _LIB.lbug_value_create_string(value.encode("utf-8"))
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        epoch = dt.date(1970, 1, 1)
        days = (value - epoch).days
        return _LIB.lbug_value_create_date(_LbugDate(days=days))
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            micros = int(value.timestamp() * 1_000_000)
            return _LIB.lbug_value_create_timestamp_tz(_LbugTimestamp(value=micros))
        micros = int(value.replace(tzinfo=dt.timezone.utc).timestamp() * 1_000_000)
        return _LIB.lbug_value_create_timestamp(_LbugTimestamp(value=micros))
    if isinstance(value, dt.timedelta):
        total_seconds = value.days * 86400 + value.seconds
        micros = total_seconds * 1_000_000 + value.microseconds
        return _LIB.lbug_value_create_interval(_LbugInterval(months=0, days=0, micros=micros))
    if isinstance(value, (list, tuple)):
        child_ptrs: list[ctypes.POINTER(_LbugValue)] = []
        try:
            for item in value:
                child_ptrs.append(_value_from_python(item))
            out = ctypes.POINTER(_LbugValue)()
            arr_type = ctypes.POINTER(_LbugValue) * len(child_ptrs)
            arr = arr_type(*child_ptrs) if child_ptrs else arr_type()
            _check_state(
                _LIB.lbug_value_create_list(len(child_ptrs), arr, ctypes.byref(out)),
                "Failed to create list value",
            )
            return out
        finally:
            for ptr in child_ptrs:
                _LIB.lbug_value_destroy(ptr)
    if isinstance(value, dict):
        if all(isinstance(k, str) for k in value):
            names: list[bytes] = []
            child_ptrs: list[ctypes.POINTER(_LbugValue)] = []
            try:
                for k, v in value.items():
                    names.append(k.encode("utf-8"))
                    child_ptrs.append(_value_from_python(v))
                out = ctypes.POINTER(_LbugValue)()
                name_arr_type = ctypes.c_char_p * len(names)
                value_arr_type = ctypes.POINTER(_LbugValue) * len(child_ptrs)
                name_arr = name_arr_type(*names) if names else name_arr_type()
                value_arr = value_arr_type(*child_ptrs) if child_ptrs else value_arr_type()
                _check_state(
                    _LIB.lbug_value_create_struct(
                        len(names),
                        name_arr,
                        value_arr,
                        ctypes.byref(out),
                    ),
                    "Failed to create struct value",
                )
                return out
            finally:
                for ptr in child_ptrs:
                    _LIB.lbug_value_destroy(ptr)
        key_ptrs: list[ctypes.POINTER(_LbugValue)] = []
        value_ptrs: list[ctypes.POINTER(_LbugValue)] = []
        try:
            for k, v in value.items():
                key_ptrs.append(_value_from_python(k))
                value_ptrs.append(_value_from_python(v))
            out = ctypes.POINTER(_LbugValue)()
            key_arr_type = ctypes.POINTER(_LbugValue) * len(key_ptrs)
            value_arr_type = ctypes.POINTER(_LbugValue) * len(value_ptrs)
            key_arr = key_arr_type(*key_ptrs) if key_ptrs else key_arr_type()
            value_arr = value_arr_type(*value_ptrs) if value_ptrs else value_arr_type()
            _check_state(
                _LIB.lbug_value_create_map(
                    len(key_ptrs),
                    key_arr,
                    value_arr,
                    ctypes.byref(out),
                ),
                "Failed to create map value",
            )
            return out
        finally:
            for ptr in key_ptrs:
                _LIB.lbug_value_destroy(ptr)
            for ptr in value_ptrs:
                _LIB.lbug_value_destroy(ptr)

    msg = f"Unsupported parameter type for C-API backend: {type(value)!r}"
    raise TypeError(msg)


class Database:
    def __init__(
        self,
        database_path: str,
        buffer_pool_size: int = 0,
        max_num_threads: int = 0,
        compression: bool = True,
        read_only: bool = False,
        max_db_size: int = (1 << 43),
        auto_checkpoint: bool = True,
        checkpoint_threshold: int = -1,
        throw_on_wal_replay_failure: bool = True,
        enable_checksums: bool = True,
        enable_multi_writes: bool = False,
    ):
        if enable_multi_writes:
            raise NotImplementedError("enable_multi_writes is not yet wired in C-API backend")
        self._database = _LbugDatabase()
        config = _LIB.lbug_default_system_config()
        config.buffer_pool_size = buffer_pool_size
        config.max_num_threads = max_num_threads
        config.enable_compression = compression
        config.read_only = read_only
        config.max_db_size = max_db_size
        config.auto_checkpoint = auto_checkpoint
        if checkpoint_threshold >= 0:
            config.checkpoint_threshold = checkpoint_threshold
        config.throw_on_wal_replay_failure = throw_on_wal_replay_failure
        config.enable_checksums = enable_checksums

        state = _LIB.lbug_database_init(database_path.encode("utf-8"), config, ctypes.byref(self._database))
        _check_state(state, "Failed to initialize database")

    def close(self) -> None:
        if self._database._database:
            _LIB.lbug_database_destroy(ctypes.byref(self._database))
            self._database._database = None

    @staticmethod
    def get_version() -> str:
        return _decode_c_string(_LIB.lbug_get_version())

    @staticmethod
    def get_storage_version() -> int:
        return int(_LIB.lbug_get_storage_version())

    def scan_node_table_as_int64(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("scan_node_table_* is not yet implemented in C-API backend")

    scan_node_table_as_int32 = scan_node_table_as_int64
    scan_node_table_as_int16 = scan_node_table_as_int64
    scan_node_table_as_double = scan_node_table_as_int64
    scan_node_table_as_float = scan_node_table_as_int64
    scan_node_table_as_bool = scan_node_table_as_int64


class PreparedStatement:
    def __init__(self, prepared: _LbugPreparedStatement):
        self._prepared = prepared

    def close(self) -> None:
        if self._prepared._prepared_statement:
            _LIB.lbug_prepared_statement_destroy(ctypes.byref(self._prepared))
            self._prepared._prepared_statement = None

    def is_success(self) -> bool:
        return bool(_LIB.lbug_prepared_statement_is_success(ctypes.byref(self._prepared)))

    def get_error_message(self) -> str:
        return _decode_c_string(_LIB.lbug_prepared_statement_get_error_message(ctypes.byref(self._prepared)))

    def bind_parameters(self, parameters: dict[str, Any]) -> None:
        for key, value in parameters.items():
            key_b = key.encode("utf-8")
            value_ptr = _value_from_python(value)
            try:
                _check_state(
                    _LIB.lbug_prepared_statement_bind_value(
                        ctypes.byref(self._prepared), key_b, value_ptr
                    ),
                    f"Failed to bind parameter {key}",
                )
            finally:
                _LIB.lbug_value_destroy(value_ptr)


class QueryResult:
    def __init__(self, result: _LbugQueryResult):
        self._result = result

    def close(self) -> None:
        if self._result._query_result:
            _LIB.lbug_query_result_destroy(ctypes.byref(self._result))
            self._result._query_result = None

    def isSuccess(self) -> bool:
        return bool(_LIB.lbug_query_result_is_success(ctypes.byref(self._result)))

    def getErrorMessage(self) -> str:
        return _decode_c_string(_LIB.lbug_query_result_get_error_message(ctypes.byref(self._result)))

    def getColumnNames(self) -> list[str]:
        columns: list[str] = []
        num_cols = int(_LIB.lbug_query_result_get_num_columns(ctypes.byref(self._result)))
        for idx in range(num_cols):
            out = ctypes.c_void_p()
            _check_state(
                _LIB.lbug_query_result_get_column_name(ctypes.byref(self._result), idx, ctypes.byref(out)),
                "Failed to get column name",
            )
            columns.append(_decode_c_string(out))
        return columns

    def getColumnDataTypes(self) -> list[str]:
        dtypes: list[str] = []
        num_cols = int(_LIB.lbug_query_result_get_num_columns(ctypes.byref(self._result)))
        for idx in range(num_cols):
            logical_type = _LbugLogicalType()
            _check_state(
                _LIB.lbug_query_result_get_column_data_type(
                    ctypes.byref(self._result), idx, ctypes.byref(logical_type)
                ),
                "Failed to get column data type",
            )
            try:
                dtypes.append(_logical_type_to_str(logical_type))
            finally:
                _LIB.lbug_data_type_destroy(ctypes.byref(logical_type))
        return dtypes

    def hasNext(self) -> bool:
        return bool(_LIB.lbug_query_result_has_next(ctypes.byref(self._result)))

    def getNext(self) -> list[Any]:
        flat = _LbugFlatTuple()
        _check_state(
            _LIB.lbug_query_result_get_next(ctypes.byref(self._result), ctypes.byref(flat)),
            "Failed to fetch next row",
        )
        try:
            num_cols = int(_LIB.lbug_query_result_get_num_columns(ctypes.byref(self._result)))
            row: list[Any] = []
            for idx in range(num_cols):
                value = _LbugValue()
                _check_state(
                    _LIB.lbug_flat_tuple_get_value(ctypes.byref(flat), idx, ctypes.byref(value)),
                    "Failed to read tuple value",
                )
                try:
                    row.append(self._convert_value(value))
                finally:
                    _LIB.lbug_value_destroy(ctypes.byref(value))
            return row
        finally:
            _LIB.lbug_flat_tuple_destroy(ctypes.byref(flat))

    def resetIterator(self) -> None:
        _LIB.lbug_query_result_reset_iterator(ctypes.byref(self._result))

    def getNumTuples(self) -> int:
        return int(_LIB.lbug_query_result_get_num_tuples(ctypes.byref(self._result)))

    def hasNextQueryResult(self) -> bool:
        return bool(_LIB.lbug_query_result_has_next_query_result(ctypes.byref(self._result)))

    def getNextQueryResult(self) -> QueryResult:
        next_result = _LbugQueryResult()
        _check_state(
            _LIB.lbug_query_result_get_next_query_result(ctypes.byref(self._result), ctypes.byref(next_result)),
            "Failed to fetch next query result",
        )
        return QueryResult(next_result)

    def getCompilingTime(self) -> int:
        summary = _LbugQuerySummary()
        _check_state(
            _LIB.lbug_query_result_get_query_summary(ctypes.byref(self._result), ctypes.byref(summary)),
            "Failed to read query summary",
        )
        try:
            return int(_LIB.lbug_query_summary_get_compiling_time(ctypes.byref(summary)))
        finally:
            _LIB.lbug_query_summary_destroy(ctypes.byref(summary))

    def getExecutionTime(self) -> int:
        summary = _LbugQuerySummary()
        _check_state(
            _LIB.lbug_query_result_get_query_summary(ctypes.byref(self._result), ctypes.byref(summary)),
            "Failed to read query summary",
        )
        try:
            return int(_LIB.lbug_query_summary_get_execution_time(ctypes.byref(summary)))
        finally:
            _LIB.lbug_query_summary_destroy(ctypes.byref(summary))

    def getAsArrow(self, *_args: Any, **_kwargs: Any) -> Any:
        raise NotImplementedError("Arrow export is not yet implemented in C-API backend")

    def getAsDF(self) -> Any:
        raise NotImplementedError("DataFrame export is not yet implemented in C-API backend")

    def _convert_value(self, value: _LbugValue) -> Any:
        if _LIB.lbug_value_is_null(ctypes.byref(value)):
            return None

        logical_type = _LbugLogicalType()
        _LIB.lbug_value_get_data_type(ctypes.byref(value), ctypes.byref(logical_type))
        try:
            type_id = _LIB.lbug_data_type_get_id(ctypes.byref(logical_type))

            if type_id == _LBUG_BOOL:
                out = ctypes.c_bool()
                _check_state(_LIB.lbug_value_get_bool(ctypes.byref(value), ctypes.byref(out)), "Failed to read bool")
                return bool(out.value)
            if type_id in (_LBUG_INT64, _LBUG_SERIAL):
                out = ctypes.c_int64()
                _check_state(_LIB.lbug_value_get_int64(ctypes.byref(value), ctypes.byref(out)), "Failed to read int64")
                return int(out.value)
            if type_id == _LBUG_INT32:
                out = ctypes.c_int32()
                _check_state(_LIB.lbug_value_get_int32(ctypes.byref(value), ctypes.byref(out)), "Failed to read int32")
                return int(out.value)
            if type_id == _LBUG_INT16:
                out = ctypes.c_int16()
                _check_state(_LIB.lbug_value_get_int16(ctypes.byref(value), ctypes.byref(out)), "Failed to read int16")
                return int(out.value)
            if type_id == _LBUG_INT8:
                out = ctypes.c_int8()
                _check_state(_LIB.lbug_value_get_int8(ctypes.byref(value), ctypes.byref(out)), "Failed to read int8")
                return int(out.value)
            if type_id == _LBUG_UINT64:
                out = ctypes.c_uint64()
                _check_state(_LIB.lbug_value_get_uint64(ctypes.byref(value), ctypes.byref(out)), "Failed to read uint64")
                return int(out.value)
            if type_id == _LBUG_UINT32:
                out = ctypes.c_uint32()
                _check_state(_LIB.lbug_value_get_uint32(ctypes.byref(value), ctypes.byref(out)), "Failed to read uint32")
                return int(out.value)
            if type_id == _LBUG_UINT16:
                out = ctypes.c_uint16()
                _check_state(_LIB.lbug_value_get_uint16(ctypes.byref(value), ctypes.byref(out)), "Failed to read uint16")
                return int(out.value)
            if type_id == _LBUG_UINT8:
                out = ctypes.c_uint8()
                _check_state(_LIB.lbug_value_get_uint8(ctypes.byref(value), ctypes.byref(out)), "Failed to read uint8")
                return int(out.value)
            if type_id == _LBUG_DOUBLE:
                out = ctypes.c_double()
                _check_state(_LIB.lbug_value_get_double(ctypes.byref(value), ctypes.byref(out)), "Failed to read double")
                return float(out.value)
            if type_id == _LBUG_FLOAT:
                out = ctypes.c_float()
                _check_state(_LIB.lbug_value_get_float(ctypes.byref(value), ctypes.byref(out)), "Failed to read float")
                return float(out.value)
            if type_id == _LBUG_STRING:
                out = ctypes.c_void_p()
                _check_state(_LIB.lbug_value_get_string(ctypes.byref(value), ctypes.byref(out)), "Failed to read string")
                return _decode_c_string(out)
            if type_id == _LBUG_UUID:
                out = ctypes.c_void_p()
                _check_state(_LIB.lbug_value_get_uuid(ctypes.byref(value), ctypes.byref(out)), "Failed to read uuid")
                return _decode_c_string(out)
            if type_id == _LBUG_DECIMAL:
                out = ctypes.c_void_p()
                _check_state(_LIB.lbug_value_get_decimal_as_string(ctypes.byref(value), ctypes.byref(out)), "Failed to read decimal")
                return _decode_c_string(out)
            if type_id == _LBUG_BLOB:
                out_ptr = ctypes.POINTER(ctypes.c_uint8)()
                out_len = ctypes.c_uint64(0)
                _check_state(
                    _LIB.lbug_value_get_blob(ctypes.byref(value), ctypes.byref(out_ptr), ctypes.byref(out_len)),
                    "Failed to read blob",
                )
                try:
                    return bytes(ctypes.string_at(out_ptr, out_len.value))
                finally:
                    _LIB.lbug_destroy_blob(out_ptr)
            if type_id == _LBUG_INTERNAL_ID:
                out = _LbugInternalID()
                _check_state(
                    _LIB.lbug_value_get_internal_id(ctypes.byref(value), ctypes.byref(out)),
                    "Failed to read internal id",
                )
                return {"table": int(out.table_id), "offset": int(out.offset)}
            if type_id == _LBUG_DATE:
                out = _LbugDate()
                _check_state(_LIB.lbug_value_get_date(ctypes.byref(value), ctypes.byref(out)), "Failed to read date")
                return dt.date(1970, 1, 1) + dt.timedelta(days=int(out.days))
            if type_id == _LBUG_TIMESTAMP:
                out = _LbugTimestamp()
                _check_state(_LIB.lbug_value_get_timestamp(ctypes.byref(value), ctypes.byref(out)), "Failed to read timestamp")
                return _to_datetime_from_micros(int(out.value))
            if type_id == _LBUG_TIMESTAMP_TZ:
                out = _LbugTimestamp()
                _check_state(
                    _LIB.lbug_value_get_timestamp_tz(ctypes.byref(value), ctypes.byref(out)),
                    "Failed to read timestamp_tz",
                )
                return _to_datetime_from_micros(int(out.value), tz_aware=True)
            if type_id == _LBUG_TIMESTAMP_MS:
                out = _LbugTimestamp()
                _check_state(_LIB.lbug_value_get_timestamp_ms(ctypes.byref(value), ctypes.byref(out)), "Failed to read timestamp_ms")
                return dt.datetime.fromtimestamp(
                    int(out.value) / 1000, tz=dt.timezone.utc
                ).replace(tzinfo=None)
            if type_id == _LBUG_TIMESTAMP_SEC:
                out = _LbugTimestamp()
                _check_state(_LIB.lbug_value_get_timestamp_sec(ctypes.byref(value), ctypes.byref(out)), "Failed to read timestamp_sec")
                return dt.datetime.fromtimestamp(
                    int(out.value), tz=dt.timezone.utc
                ).replace(tzinfo=None)
            if type_id == _LBUG_TIMESTAMP_NS:
                out = _LbugTimestamp()
                _check_state(_LIB.lbug_value_get_timestamp_ns(ctypes.byref(value), ctypes.byref(out)), "Failed to read timestamp_ns")
                return dt.datetime.fromtimestamp(
                    int(out.value) / 1_000_000_000, tz=dt.timezone.utc
                ).replace(tzinfo=None)
            if type_id == _LBUG_INTERVAL:
                out = _LbugInterval()
                _check_state(_LIB.lbug_value_get_interval(ctypes.byref(value), ctypes.byref(out)), "Failed to read interval")
                return {"months": int(out.months), "days": int(out.days), "micros": int(out.micros)}
            if type_id in (_LBUG_LIST, _LBUG_ARRAY):
                size = ctypes.c_uint64(0)
                _check_state(_LIB.lbug_value_get_list_size(ctypes.byref(value), ctypes.byref(size)), "Failed to read list size")
                out_list: list[Any] = []
                for i in range(size.value):
                    child = _LbugValue()
                    _check_state(
                        _LIB.lbug_value_get_list_element(ctypes.byref(value), i, ctypes.byref(child)),
                        "Failed to read list element",
                    )
                    try:
                        out_list.append(self._convert_value(child))
                    finally:
                        _LIB.lbug_value_destroy(ctypes.byref(child))
                return out_list
            if type_id in (_LBUG_STRUCT, _LBUG_NODE, _LBUG_REL, _LBUG_RECURSIVE_REL, _LBUG_UNION):
                count = ctypes.c_uint64(0)
                _check_state(
                    _LIB.lbug_value_get_struct_num_fields(ctypes.byref(value), ctypes.byref(count)),
                    "Failed to read struct field count",
                )
                out_obj: dict[str, Any] = {}
                for i in range(count.value):
                    key_ptr = ctypes.c_void_p()
                    _check_state(
                        _LIB.lbug_value_get_struct_field_name(ctypes.byref(value), i, ctypes.byref(key_ptr)),
                        "Failed to read struct field name",
                    )
                    key = _decode_c_string(key_ptr)

                    child = _LbugValue()
                    _check_state(
                        _LIB.lbug_value_get_struct_field_value(ctypes.byref(value), i, ctypes.byref(child)),
                        "Failed to read struct field value",
                    )
                    try:
                        out_obj[key] = self._convert_value(child)
                    finally:
                        _LIB.lbug_value_destroy(ctypes.byref(child))
                return out_obj
            if type_id == _LBUG_MAP:
                count = ctypes.c_uint64(0)
                _check_state(
                    _LIB.lbug_value_get_map_size(ctypes.byref(value), ctypes.byref(count)),
                    "Failed to read map size",
                )
                out_map: dict[Any, Any] = {}
                for i in range(count.value):
                    key_val = _LbugValue()
                    val_val = _LbugValue()
                    _check_state(
                        _LIB.lbug_value_get_map_key(ctypes.byref(value), i, ctypes.byref(key_val)),
                        "Failed to read map key",
                    )
                    _check_state(
                        _LIB.lbug_value_get_map_value(ctypes.byref(value), i, ctypes.byref(val_val)),
                        "Failed to read map value",
                    )
                    try:
                        out_map[self._convert_value(key_val)] = self._convert_value(val_val)
                    finally:
                        _LIB.lbug_value_destroy(ctypes.byref(key_val))
                        _LIB.lbug_value_destroy(ctypes.byref(val_val))
                return out_map

            return _decode_c_string(_LIB.lbug_value_to_string(ctypes.byref(value)))
        finally:
            _LIB.lbug_data_type_destroy(ctypes.byref(logical_type))


class Connection:
    def __init__(self, database: Database, num_threads: int = 0):
        self._connection = _LbugConnection()
        _check_state(
            _LIB.lbug_connection_init(ctypes.byref(database._database), ctypes.byref(self._connection)),
            "Failed to initialize connection",
        )
        if num_threads > 0:
            self.set_max_threads_for_exec(num_threads)

    def close(self) -> None:
        if self._connection._connection:
            _LIB.lbug_connection_destroy(ctypes.byref(self._connection))
            self._connection._connection = None

    def set_max_threads_for_exec(self, num_threads: int) -> None:
        _check_state(
            _LIB.lbug_connection_set_max_num_thread_for_exec(
                ctypes.byref(self._connection), int(num_threads)
            ),
            "Failed to set max threads",
        )

    def set_query_timeout(self, timeout_in_ms: int) -> None:
        _check_state(
            _LIB.lbug_connection_set_query_timeout(ctypes.byref(self._connection), int(timeout_in_ms)),
            "Failed to set query timeout",
        )

    def interrupt(self) -> None:
        _LIB.lbug_connection_interrupt(ctypes.byref(self._connection))

    def query(self, query: str) -> QueryResult:
        result = _LbugQueryResult()
        _check_state(
            _LIB.lbug_connection_query(
                ctypes.byref(self._connection), query.encode("utf-8"), ctypes.byref(result)
            ),
            "Failed to execute query",
        )
        return QueryResult(result)

    def prepare(self, query: str, parameters: dict[str, Any] | None = None) -> PreparedStatement:
        prepared = _LbugPreparedStatement()
        _check_state(
            _LIB.lbug_connection_prepare(
                ctypes.byref(self._connection), query.encode("utf-8"), ctypes.byref(prepared)
            ),
            "Failed to prepare query",
        )
        stmt = PreparedStatement(prepared)
        if parameters:
            stmt.bind_parameters(parameters)
        return stmt

    def execute(
        self,
        prepared_statement: PreparedStatement,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        if parameters:
            prepared_statement.bind_parameters(parameters)
        result = _LbugQueryResult()
        _check_state(
            _LIB.lbug_connection_execute(
                ctypes.byref(self._connection),
                ctypes.byref(prepared_statement._prepared),
                ctypes.byref(result),
            ),
            "Failed to execute prepared statement",
        )
        return QueryResult(result)

    def create_function(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("UDF registration is not yet implemented in C-API backend")

    def remove_function(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("UDF removal is not yet implemented in C-API backend")

    def create_arrow_table(self, *_args: Any, **_kwargs: Any) -> Any:
        raise NotImplementedError("Arrow memory table APIs are not yet implemented in C-API backend")

    def drop_arrow_table(self, *_args: Any, **_kwargs: Any) -> Any:
        raise NotImplementedError("Arrow memory table APIs are not yet implemented in C-API backend")

    def create_arrow_rel_table(self, *_args: Any, **_kwargs: Any) -> Any:
        raise NotImplementedError("Arrow memory table APIs are not yet implemented in C-API backend")
