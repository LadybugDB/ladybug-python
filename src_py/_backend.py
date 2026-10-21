from __future__ import annotations

import os
import sys
from importlib import import_module
from typing import Any

_CAPI_MODULE: Any | None = None
_PYBIND_MODULE: Any | None = None
_PYBIND_IMPORT_ATTEMPTED = False
_PYBIND_IMPORT_ERROR: ImportError | None = None


def _import_pybind_module() -> Any:
    if sys.platform != "linux":
        return import_module("._lbug", __package__)

    original_dlopen_flags = sys.getdlopenflags()
    try:
        # Keep pybind's symbols visible to any transitive native extensions
        # without affecting the process-wide import path for the C-API backend.
        sys.setdlopenflags(os.RTLD_GLOBAL | os.RTLD_LAZY)
        return import_module("._lbug", __package__)
    finally:
        sys.setdlopenflags(original_dlopen_flags)


def get_capi_module() -> Any:
    global _CAPI_MODULE
    if _CAPI_MODULE is None:
        _CAPI_MODULE = import_module("._lbug_capi", __package__)
    return _CAPI_MODULE


def get_pybind_module() -> Any | None:
    global _PYBIND_MODULE, _PYBIND_IMPORT_ATTEMPTED, _PYBIND_IMPORT_ERROR
    if _PYBIND_IMPORT_ATTEMPTED:
        return _PYBIND_MODULE
    _PYBIND_IMPORT_ATTEMPTED = True
    try:
        _PYBIND_MODULE = _import_pybind_module()
    except ImportError as exc:
        _PYBIND_MODULE = None
        _PYBIND_IMPORT_ERROR = exc
    return _PYBIND_MODULE


def missing_capi_library_message() -> str:
    """
    Explain why neither backend could load.

    The C API library is the fallback when the bundled ``_lbug`` extension fails to import, so a missing C API
    library usually hides the real failure. Include that failure, such as a missing OpenSSL 3 runtime.
    """
    msg = (
        "Could not find lbug C API shared library. "
        "Set LBUG_C_API_LIB_PATH or download a shared lib (e.g. run "
        "LBUG_LIB_KIND=shared bash scripts/download_lbug.sh)."
    )
    if _PYBIND_IMPORT_ERROR is None:
        return msg
    msg += f" The bundled _lbug extension, which is tried first, failed to load: {_PYBIND_IMPORT_ERROR}"
    if "libssl" in str(_PYBIND_IMPORT_ERROR) or "libcrypto" in str(
        _PYBIND_IMPORT_ERROR
    ):
        msg += " Ladybug needs an OpenSSL 3 runtime; on macOS, install it with `brew install openssl@3`."
    return msg
