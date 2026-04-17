# Plan: Align `ladybug-python` prebuilt flow with existing upstream downloader logic (minimal-risk)

## Goals

1. Reuse latest prebuilt core binaries with the same approach used by sibling bindings.
2. Avoid breaking existing Python clients/tests.
3. Keep source-build path intact.
4. Use `uv` in local workflows.

## Key Direction Change

Instead of implementing custom download logic in Python, use the same pattern as `../go-ladybug/download_lbug.sh`:

- keep a local wrapper script,
- fetch and run upstream `download-liblbug.sh`,
- pass env vars to control target dir/library kind,
- keep logic centralized upstream.

## Implementation Steps

1. Add `scripts/download_lbug.sh` wrapper:
   - fetches upstream `download-liblbug.sh` if missing,
   - calls it with `LBUG_LIB_KIND=static` and local cache target,
   - writes `.cache/lbug-prebuilt.env` with `EXTRA_CMAKE_FLAGS` for:
     - `LBUG_API_USE_PRECOMPILED_LIB=TRUE`
     - `LBUG_API_PRECOMPILED_LIB_PATH=...`

2. Update `Makefile` with additive targets:
   - `bootstrap-prebuilt`: runs wrapper script
   - `build-prebuilt`: sources emitted env file and builds using existing make flow
   - keep existing `build`/`test` untouched.

3. Verification:
   - run `make bootstrap-prebuilt`
   - confirm env file created and static library resolved.

## Non-Breaking Guarantees

- Python API remains unchanged.
- Existing tests and source build flow remain valid.
- Prebuilt linkage is opt-in via new target.
