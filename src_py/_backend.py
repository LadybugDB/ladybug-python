from __future__ import annotations

from importlib import import_module
from typing import Any

_CAPI_MODULE: Any | None = None
_PYBIND_MODULE: Any | None = None
_PYBIND_IMPORT_ATTEMPTED = False


def get_capi_module() -> Any:
    global _CAPI_MODULE
    if _CAPI_MODULE is None:
        _CAPI_MODULE = import_module("._lbug_capi", __package__)
    return _CAPI_MODULE


def get_pybind_module() -> Any | None:
    global _PYBIND_MODULE, _PYBIND_IMPORT_ATTEMPTED
    if _PYBIND_IMPORT_ATTEMPTED:
        return _PYBIND_MODULE
    _PYBIND_IMPORT_ATTEMPTED = True
    try:
        _PYBIND_MODULE = import_module("._lbug", __package__)
    except ImportError:
        _PYBIND_MODULE = None
    return _PYBIND_MODULE
