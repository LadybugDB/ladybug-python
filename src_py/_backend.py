from __future__ import annotations

import os

_BACKEND = os.getenv("LBUG_PYTHON_BACKEND", "pybind").strip().lower()

if _BACKEND == "capi":
    from . import _lbug_capi as _lbug
else:
    from . import _lbug

__all__ = ["_lbug"]
