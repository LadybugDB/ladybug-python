cmake_minimum_required(VERSION 3.15)

include(FetchContent)
project(_lbug LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 20)
set(LBUG_SOURCE_DIR "" CACHE PATH "Path to the Ladybug source tree used for pybind builds")

if(NOT TARGET pybind11::module)
    if(LBUG_SOURCE_DIR)
        add_subdirectory("${LBUG_SOURCE_DIR}/third_party/pybind11" "${CMAKE_BINARY_DIR}/third_party/pybind11" EXCLUDE_FROM_ALL)
    else()
        find_package(pybind11 CONFIG REQUIRED)
    endif()
endif()

if(NOT LBUG_API_USE_PRECOMPILED_LIB AND NOT TARGET lbug)
    if(NOT LBUG_SOURCE_DIR)
        message(FATAL_ERROR "LBUG_SOURCE_DIR must be set when building the pybind extension from Ladybug sources.")
    endif()

    set(BUILD_BENCHMARK FALSE CACHE BOOL "" FORCE)
    set(BUILD_EXAMPLES FALSE CACHE BOOL "" FORCE)
    set(BUILD_EXTENSION_TESTS FALSE CACHE BOOL "" FORCE)
    set(BUILD_JAVA FALSE CACHE BOOL "" FORCE)
    set(BUILD_NODEJS FALSE CACHE BOOL "" FORCE)
    set(BUILD_PYTHON FALSE CACHE BOOL "" FORCE)
    set(BUILD_SHELL FALSE CACHE BOOL "" FORCE)
    set(BUILD_TESTS FALSE CACHE BOOL "" FORCE)
    set(BUILD_WAL_DUMP FALSE CACHE BOOL "" FORCE)
    set(BUILD_WASM FALSE CACHE BOOL "" FORCE)

    add_subdirectory("${LBUG_SOURCE_DIR}" "${CMAKE_BINARY_DIR}/lbug-source" EXCLUDE_FROM_ALL)
endif()

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

if(TARGET lbug)
    get_target_property(LBUG_INCLUDE_DIRECTORIES lbug INCLUDE_DIRECTORIES)
    if(LBUG_INCLUDE_DIRECTORIES)
        target_include_directories(_lbug PRIVATE ${LBUG_INCLUDE_DIRECTORIES})
    endif()

    get_target_property(LBUG_COMPILE_DEFINITIONS lbug COMPILE_DEFINITIONS)
    if(LBUG_COMPILE_DEFINITIONS)
        target_compile_definitions(_lbug PRIVATE ${LBUG_COMPILE_DEFINITIONS})
    endif()

    get_target_property(LBUG_COMPILE_OPTIONS lbug COMPILE_OPTIONS)
    if(LBUG_COMPILE_OPTIONS)
        target_compile_options(_lbug PRIVATE ${LBUG_COMPILE_OPTIONS})
    endif()
endif()

get_target_property(PYTHON_DEST _lbug LIBRARY_OUTPUT_DIRECTORY)

file(COPY ${SOURCE_PY} DESTINATION ${PYTHON_DEST})
