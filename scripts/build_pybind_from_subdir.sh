#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LBUG_DIR="${1:-$(cd "${ROOT_DIR}/.." && pwd)/ladybug}"
BUILD_DIR="${ROOT_DIR}/build/pybind"
CCACHE_DIR="${ROOT_DIR}/.cache/ccache"
CCACHE_TEMPDIR="${CCACHE_DIR}/tmp"

if [[ ! -d "${LBUG_DIR}" ]]; then
  echo "ladybug source checkout not found: ${LBUG_DIR}" >&2
  echo "Set LBUG_SOURCE_DIR to your Ladybug source tree checkout." >&2
  exit 1
fi

echo "[pybind] Building ${ROOT_DIR} with Ladybug sources from ${LBUG_DIR}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi
PYTHON_VERSION="$(${PYTHON_BIN} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

echo "[pybind] Using Python interpreter: ${PYTHON_BIN} (${PYTHON_VERSION})"

export PATH="$(dirname "${PYTHON_BIN}"):${PATH}"
export PYTHON_EXECUTABLE="${PYTHON_BIN}"
export Python_EXECUTABLE="${PYTHON_BIN}"
export Python3_EXECUTABLE="${PYTHON_BIN}"
export CCACHE_DIR
export CCACHE_TEMPDIR

mkdir -p "${CCACHE_TEMPDIR}"

# ---------------------------------------------------------------------------
# Generator selection
# ---------------------------------------------------------------------------
# Honour GEN env var (e.g. GEN=Unix\ Makefiles), otherwise default to Ninja.
if [[ -n "${GEN:-}" ]]; then
    GENERATOR="${GEN}"
else
    GENERATOR="Ninja"
fi
echo "[pybind] Generator: ${GENERATOR}"

# If the build directory exists with a different generator, wipe it so
# CMake doesn't error out with a generator mismatch.
if [[ -f "${BUILD_DIR}/CMakeCache.txt" ]]; then
    cached_gen="$(grep -m1 'CMAKE_GENERATOR:INTERNAL=' "${BUILD_DIR}/CMakeCache.txt" 2>/dev/null | cut -d= -f2)"
    if [[ -n "${cached_gen}" && "${cached_gen}" != "${GENERATOR}" ]]; then
        echo "[pybind] Generator changed from '${cached_gen}' to '${GENERATOR}' — wiping stale build directory."
        rm -rf "${BUILD_DIR}"
    fi
fi

# ---------------------------------------------------------------------------
# CMake configuration (always re-runs if CMakeLists.txt changed)
# ---------------------------------------------------------------------------
# Only wipe the build tree when BUILD_CLEAN=1 is set explicitly.
if [[ "${BUILD_CLEAN:-0}" == "1" ]]; then
  echo "[pybind] BUILD_CLEAN=1 — removing ${BUILD_DIR}"
  rm -rf "${BUILD_DIR}"
fi

cmake_args=(
    -S "${ROOT_DIR}"
    -B "${BUILD_DIR}"
    -G "${GENERATOR}"
    -DCMAKE_BUILD_TYPE=Release
    -DLBUG_SOURCE_DIR="${LBUG_DIR}"
    -DPYTHON_EXECUTABLE="${PYTHON_BIN}"
    -DPython_EXECUTABLE="${PYTHON_BIN}"
    -DPython3_EXECUTABLE="${PYTHON_BIN}"
    -DPYBIND11_PYTHON_VERSION="${PYTHON_VERSION}"
)

# Wire in ccache if it is available (vastly speeds up rebuilds).
if command -v ccache &>/dev/null; then
    cmake_args+=(
        -DCMAKE_C_COMPILER_LAUNCHER=ccache
        -DCMAKE_CXX_COMPILER_LAUNCHER=ccache
    )
fi

cmake "${cmake_args[@]}"

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
# Parallelism: honour CMAKE_BUILD_PARALLEL_LEVEL or PARALLEL first,
# then fall back to the number of logical CPUs.
if [[ -n "${CMAKE_BUILD_PARALLEL_LEVEL:-}" ]]; then
    NPROC="${CMAKE_BUILD_PARALLEL_LEVEL}"
elif [[ -n "${PARALLEL:-}" ]]; then
    NPROC="${PARALLEL}"
else
    NPROC="$(nproc 2>/dev/null || echo 4)"
fi

build_args=(
    --build "${BUILD_DIR}"
    --config Release
    --target _lbug
    --parallel "${NPROC}"
)

echo "[pybind] Starting build with ${NPROC} parallel job(s) ..."
cmake "${build_args[@]}"

# ---------------------------------------------------------------------------
# Post-build check
# ---------------------------------------------------------------------------
if compgen -G "${ROOT_DIR}/build/ladybug/_lbug*" &>/dev/null; then
  echo "[pybind] Built extension into ${ROOT_DIR}/build/ladybug"
elif compgen -G "${BUILD_DIR}/ladybug/_lbug*" &>/dev/null; then
  echo "[pybind] Built extension into ${BUILD_DIR}/ladybug"
  # Copy to expected location so Makefile's test target finds it.
  mkdir -p "${ROOT_DIR}/build/ladybug"
  cp "${BUILD_DIR}"/ladybug/_lbug* "${ROOT_DIR}/build/ladybug/"
else
  echo "[pybind] Build finished, but no _lbug extension artifact was found." >&2
  echo "Checked: ${ROOT_DIR}/build/ladybug and ${BUILD_DIR}/ladybug" >&2
  exit 1
fi
