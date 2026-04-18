#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LBUG_DIR="${1:-${ROOT_DIR}/ladybug}"

if [[ ! -d "${LBUG_DIR}" ]]; then
  echo "ladybug source checkout not found: ${LBUG_DIR}" >&2
  echo "Expected inverted layout: <repo>/ladybug" >&2
  exit 1
fi

TOOLS_DIR="${LBUG_DIR}/tools"
API_LINK="${TOOLS_DIR}/python_api"

mkdir -p "${TOOLS_DIR}"

if [[ -e "${API_LINK}" && ! -L "${API_LINK}" ]]; then
  echo "Refusing to overwrite non-symlink path: ${API_LINK}" >&2
  echo "Please remove it manually or convert it to a symlink to ${ROOT_DIR}" >&2
  exit 1
fi

rm -f "${API_LINK}"
ln -s "${ROOT_DIR}" "${API_LINK}"

echo "[pybind] Building via ${LBUG_DIR} (target: make python)"
make -C "${LBUG_DIR}" python

mkdir -p "${ROOT_DIR}/build/ladybug"
cp "${ROOT_DIR}"/src_py/*.py "${ROOT_DIR}/build/ladybug/"

# Copy extension artifact(s) to local build package.
shopt -s nullglob
for ext in "${API_LINK}/build/ladybug"/_lbug*.so "${API_LINK}/build/ladybug"/_lbug*.pyd "${API_LINK}/build/ladybug"/_lbug*.dylib; do
  cp "${ext}" "${ROOT_DIR}/build/ladybug/"
done

if compgen -G "${ROOT_DIR}/build/ladybug/_lbug*" > /dev/null; then
  echo "[pybind] Copied extension into ${ROOT_DIR}/build/ladybug"
else
  echo "[pybind] Build finished, but no _lbug extension artifact was found." >&2
  echo "Checked: ${API_LINK}/build/ladybug" >&2
  exit 1
fi
