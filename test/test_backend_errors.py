from __future__ import annotations

import ladybug._backend as backend


def test_missing_capi_message_without_pybind_error(monkeypatch) -> None:
    monkeypatch.setattr(backend, "_PYBIND_IMPORT_ERROR", None)
    msg = backend.missing_capi_library_message()
    assert msg.startswith("Could not find lbug C API shared library.")
    assert "_lbug extension" not in msg


def test_missing_capi_message_reports_pybind_error(monkeypatch) -> None:
    error = ImportError(
        "dlopen(_lbug.cpython-312-darwin.so, 0x0002): Library not loaded: /opt/homebrew/opt/openssl@3/lib/libssl.3.dylib"
    )
    monkeypatch.setattr(backend, "_PYBIND_IMPORT_ERROR", error)
    msg = backend.missing_capi_library_message()
    assert "Library not loaded: /opt/homebrew/opt/openssl@3/lib/libssl.3.dylib" in msg
    assert "brew install openssl@3" in msg


def test_failed_pybind_import_is_recorded(monkeypatch) -> None:
    error = ImportError("Library not loaded: libcrypto.3.dylib")

    def fail() -> None:
        raise error

    monkeypatch.setattr(backend, "_PYBIND_IMPORT_ATTEMPTED", False)
    monkeypatch.setattr(backend, "_PYBIND_MODULE", None)
    monkeypatch.setattr(backend, "_PYBIND_IMPORT_ERROR", None)
    monkeypatch.setattr(backend, "_import_pybind_module", fail)
    assert backend.get_pybind_module() is None
    assert "libcrypto.3.dylib" in str(backend._PYBIND_IMPORT_ERROR)
