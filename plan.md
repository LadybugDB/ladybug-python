# Plan: Full C-API Python backend + Node-style memory ownership

## Goal

Move `ladybug-python` fully to `lbug.h` C-API, with no backend knob, while preserving public Python API behavior and stability.

## Memory Management Strategy (authoritative)

### Ownership model

- **All heap memory returned by C-API result-reading calls is owned by the backend `QueryResult` object**.
- Memory is released when `result.close()` is called (or when GC triggers close), matching Node-style lifetime semantics.
- This includes:
  - `char*` returned through result paths (column names, string/uuid/decimal rendering, etc.)
  - blob buffers returned from result values

### Lifecycle ordering

- Normal close order remains:
  1. `result.close()`
  2. `conn.close()`
  3. `db.close()`

### Out-of-order safety

- Out-of-order close must never crash.
- We enforce safe parent/child close behavior in Python wrappers:
  - Database tracks live connections; closes them before destroying DB handle.
  - Connection tracks live query results; closes them before destroying connection handle.
  - QueryResult methods detect closed parent DB/connection and raise Python exceptions, not segfault.

## Execution Steps

1. Make C-API backend the only backend path.
2. Add QueryResult-owned allocation tracking and deferred free-on-close.
3. Add parent-child tracking across Database/Connection/QueryResult.
4. Ensure out-of-order close behavior is idempotent and crash-safe.
5. Add/adjust tests for:
   - normal close ordering
   - out-of-order close safety
   - C-API smoke and parameter binding.
