include(FetchContent)
project(_lbug)

set(CMAKE_CXX_STANDARD 20)

file(GLOB SOURCE_PY
        "src_py/*")

pybind11_add_module(_lbug
        SHARED
        src_cpp/lbug_binding.cpp
        src_cpp/cached_import/py_cached_item.cpp
        src_cpp/cached_import/py_cached_import.cpp
        src_cpp/py_connection.cpp
        src_cpp/py_database.cpp
        src_cpp/py_prepared_statement.cpp
        src_cpp/py_query_result.cpp
        src_cpp/py_query_result_converter.cpp
        src_cpp/py_scan_config.cpp
        src_cpp/py_udf.cpp
        src_cpp/py_conversion.cpp
        src_cpp/pyarrow/pyarrow_bind.cpp
        src_cpp/pyarrow/pyarrow_scan.cpp
        src_cpp/pandas/pandas_bind.cpp
        src_cpp/pandas/pandas_scan.cpp
        src_cpp/pandas/pandas_analyzer.cpp
        src_cpp/numpy/numpy_type.cpp
        src_cpp/numpy/numpy_scan.cpp)

set_target_properties(_lbug
        PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${PROJECT_SOURCE_DIR}/build/ladybug"
        RUNTIME_OUTPUT_DIRECTORY "${PROJECT_SOURCE_DIR}/build/ladybug"
        ARCHIVE_OUTPUT_DIRECTORY "${PROJECT_SOURCE_DIR}/build/ladybug")

if(LBUG_API_USE_PRECOMPILED_LIB)
    if(NOT LBUG_API_PRECOMPILED_LIB_PATH)
        message(FATAL_ERROR "LBUG_API_PRECOMPILED_LIB_PATH must be set when LBUG_API_USE_PRECOMPILED_LIB is enabled.")
    endif()
    target_link_libraries(_lbug
            PRIVATE
            ${LBUG_API_PRECOMPILED_LIB_PATH}
            # lbug_link_deps carries all third-party static libs (utf8proc, re2,
            # antlr4, zstd, …) that lbug.lib references but does not bundle on
            # Windows. On Linux/macOS the precompiled liblbug.a is a fat archive
            # with those objects already merged in, so this is a no-op there.
            lbug_link_deps)
    # The precompiled lib is always a static archive. Without LBUG_STATIC_DEFINE,
    # api.h decorates every LBUG_API symbol with __declspec(dllimport) on Windows,
    # which causes LNK2001 unresolved-symbol errors because no DLL is present.
    target_compile_definitions(_lbug PRIVATE LBUG_STATIC_DEFINE)
else()
    target_link_libraries(_lbug
            PRIVATE
            lbug)
endif()

target_include_directories(
        _lbug
        PUBLIC
        src_cpp/include)

get_target_property(PYTHON_DEST _lbug LIBRARY_OUTPUT_DIRECTORY)

file(COPY ${SOURCE_PY} DESTINATION ${PYTHON_DEST})
