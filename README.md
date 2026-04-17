# Python APIs

## Build

This package now uses the shared Lbug **C-API** backend.

```bash
make build
```

The build command downloads the latest shared `liblbug` binary (via upstream
`download-liblbug.sh`) and stages Python sources in `./build/ladybug`.

To run tests:

```bash
make test
```
