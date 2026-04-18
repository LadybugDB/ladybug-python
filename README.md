# Python APIs

## Build

### C-API backend (default)

```bash
make build
```

This downloads the latest shared `liblbug` binary (via upstream
`download-liblbug.sh`) and stages Python sources in `./build/ladybug`.

Run tests with:

```bash
make test
```

### Pybind backend from inverted layout

If your checkout layout is:

- `ladybug-python/` (this repo, top-level)
- `ladybug-python/ladybug/` (main Ladybug repo as subdir)

then build the pybind extension through the Ladybug top-level build with:

```bash
make build-pybind-subdir
```

This creates a symlink at `ladybug/tools/python_api -> <this repo>`, runs
`make python` in `./ladybug`, and copies `_lbug*` into `./build/ladybug`.

Run tests against that pybind build with:

```bash
make test-pybind-subdir
```
