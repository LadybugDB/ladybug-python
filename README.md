# Python APIs

## Build

### C-API backend (default)

```bash
make sync
```

This downloads the latest shared `liblbug` binary (via upstream
`download-liblbug.sh`) and syncs the project with dev dependencies.
The Python package is installed directly from `src_py/`, so the standalone
workflow no longer depends on `./build/ladybug`.

Run tests with:

```bash
uv run pytest
```

### Pybind backend from inverted layout

If your checkout layout is:

- `ladybug-python/` (this repo)
- `../ladybug/` (main Ladybug repo as a sibling checkout)

then build the pybind extension through the Ladybug top-level build with:

```bash
make build-pybind-subdir
```

This uses `LBUG_SOURCE_DIR` (default: `../ladybug`) to configure this repo's
CMake build against the Ladybug source checkout and writes `_lbug*` into
`./build/ladybug`.

Run tests against that pybind build with:

```bash
make test-pybind-subdir
```

Override the source tree location when needed:

```bash
make build-pybind-subdir LBUG_SOURCE_DIR=/path/to/ladybug
```
