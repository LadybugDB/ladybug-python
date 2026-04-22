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

rm -rf "${BUILD_DIR}"

cmake \
  -S "${ROOT_DIR}" \
  -B "${BUILD_DIR}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DLBUG_SOURCE_DIR="${LBUG_DIR}" \
  -DPYTHON_EXECUTABLE="${PYTHON_BIN}" \
  -DPython_EXECUTABLE="${PYTHON_BIN}" \
  -DPython3_EXECUTABLE="${PYTHON_BIN}" \
  -DPYBIND11_PYTHON_VERSION="${PYTHON_VERSION}"

cmake --build "${BUILD_DIR}" --config Release --target _lbug

if compgen -G "${ROOT_DIR}/build/ladybug/_lbug*" > /dev/null; then
  echo "[pybind] Built extension into ${ROOT_DIR}/build/ladybug"
else
  echo "[pybind] Build finished, but no _lbug extension artifact was found." >&2
  echo "Checked: ${ROOT_DIR}/build/ladybug" >&2
  exit 1
fi
