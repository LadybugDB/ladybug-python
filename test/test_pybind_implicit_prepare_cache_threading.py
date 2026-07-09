"""
Thread-safety regression tests for the implicit prepared-statement cache.

The cache lives on ``Connection._pybind_implicit_prepared_cache`` and is
shared by the pybind and C-API execute paths.  When two threads execute
the same parameterized query on the same connection, the cached
prepared statement is shared; if its mutable bound state is torn by
concurrent bind calls, the executor reads garbage and returns the wrong
value.  These tests reproduce that scenario and would catch a
regression where the cache is reintroduced without proper
serialization.
"""

from __future__ import annotations

import threading

import ladybug as lb
import pytest


@pytest.mark.parametrize(
    ("num_threads", "iters"),
    [
        # Light load - already covered by the async tests in spirit, but
        # we re-test on a synchronous shared connection to make sure the
        # per-connection lock covers the multi-threaded case.
        (2, 5),
        # Moderate load - the smallest case where the race used to
        # surface (1 thread never reproduces it).
        (8, 5),
        # Heavy load - the original failure mode.
        (32, 5),
    ],
)
def test_shared_connection_concurrent_same_query(num_threads: int, iters: int) -> None:
    """Many threads on a single connection must each see its own bound value."""
    # Use an explicit max_db_size (1 GB) so the C-API backend does not default
    # to the library's 8 TB mmap region, which fails on CI runners with tight
    # virtual-address limits.
    db = lb.Database(":memory:", buffer_pool_size=2**28, max_db_size=2**30)
    conn = lb.Connection(db)

    errors: list[tuple[int, list]] = []
    errors_lock = threading.Lock()

    def worker(base: int) -> None:
        for i in range(iters):
            v = base + i
            result = conn.execute("RETURN $n", {"n": v})
            try:
                got = result.get_next()
            finally:
                result.close()
            if got != [v]:
                with errors_lock:
                    errors.append((v, got))

    threads = [
        threading.Thread(target=worker, args=(i * 1000,)) for i in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], (
        f"{len(errors)}/{num_threads * iters} executions returned the "
        f"wrong value. First few: {errors[:5]}"
    )
