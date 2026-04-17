# Python APIs

## Build

### Existing source build

```bash
make build
```

### Precompiled static core (pybind backend)

```bash
make bootstrap-prebuilt
make build-prebuilt
```

### Experimental C-API backend (ctypes)

```bash
make bootstrap-capi
set -a; source .cache/lbug-capi.env; set +a
export LBUG_PYTHON_BACKEND=capi
```

Then run Python/tests with `PYTHONPATH=./build` (or an installed package).

> The C-API backend is additive and opt-in. Default behavior remains the existing pybind backend.
