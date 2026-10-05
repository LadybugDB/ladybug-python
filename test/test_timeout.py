from __future__ import annotations

import contextlib
import threading
import time
from typing import TYPE_CHECKING

import ladybug as lb
import pytest
from type_aliases import ConnDB

if TYPE_CHECKING:
    from collections.abc import Iterator


def test_timeout(conn_db_readonly: ConnDB) -> None:
    conn, _ = conn_db_readonly
    conn.set_query_timeout(1000)
    with pytest.raises(RuntimeError, match=r"Interrupted."):
        conn.execute(
            "UNWIND RANGE(1,100000) AS x UNWIND RANGE(1, 100000) AS y RETURN COUNT(x + y);"
        )


# Runs for seconds without materializing large lists.
LONG_QUERY = "WITH range(1, 30000) AS r UNWIND r AS x UNWIND r AS y RETURN sum(x * y)"


def _execute_until_interrupted(conn: lb.Connection, query: str) -> None:
    with contextlib.suppress(RuntimeError):
        conn.execute(query)


def _interrupt_until_done(conn: lb.Connection, *threads: threading.Thread) -> None:
    # An interrupt sent before execution starts is cleared, so repeat it.
    for thread in threads:
        while thread.is_alive():
            conn.interrupt()
            thread.join(0.05)


@pytest.fixture
def conn() -> Iterator[lb.Connection]:
    # A fresh connection: the shared read-only one carries other tests' settings.
    db = lb.Database(":memory:")
    conn = lb.Connection(db)
    yield conn
    conn.close()
    db.close()


def test_settings_do_not_wait_for_running_query(conn: lb.Connection) -> None:
    worker = threading.Thread(
        target=_execute_until_interrupted, args=(conn, LONG_QUERY)
    )
    worker.start()
    time.sleep(0.3)
    started = time.monotonic()
    conn.set_query_timeout(60_000)
    conn.set_max_threads_for_exec(2)
    elapsed = time.monotonic() - started
    _interrupt_until_done(conn, worker)
    assert elapsed < 1, elapsed


def test_applying_settings_lets_other_threads_run(conn: lb.Connection) -> None:
    running = threading.Thread(
        target=_execute_until_interrupted, args=(conn, LONG_QUERY)
    )
    running.start()
    time.sleep(0.3)
    conn.set_query_timeout(60_000)
    # This call applies the new timeout, which waits for the running query.
    waiting = threading.Thread(
        target=_execute_until_interrupted, args=(conn, "RETURN 1")
    )
    started = time.monotonic()
    waiting.start()
    time.sleep(0.4)
    elapsed = time.monotonic() - started
    _interrupt_until_done(conn, running, waiting)
    assert elapsed < 1, elapsed
