import asyncio
import time
from typing import Any

import ladybug as lb
import pyarrow as pa
import pytest


@pytest.mark.asyncio
async def test_async_prepare_and_execute(async_connection_readonly):
    query = "MATCH (a:person) WHERE a.ID = $1 RETURN a.age;"
    result = await async_connection_readonly.execute(query, {"1": 0})
    assert result.has_next()
    assert result.get_next() == [35]
    assert not result.has_next()
    result.close()
    for i in async_connection_readonly.connections_counter:
        assert i == 0


@pytest.mark.asyncio
async def test_async_prepare_and_execute_concurrent(async_connection_readonly):
    num_queries = 100
    query = "RETURN $1;"
    results = await asyncio.gather(
        *[
            async_connection_readonly.execute(query, {"1": i})
            for i in range(num_queries)
        ]
    )
    for i, result in enumerate(results):
        assert result.has_next()
        assert result.get_next() == [i]
        assert not result.has_next()
        result.close()
    for i in async_connection_readonly.connections_counter:
        assert i == 0


@pytest.mark.asyncio
async def test_async_query(async_connection_readonly):
    query = "MATCH (a:person) WHERE a.ID = 0 RETURN a.age;"
    result = await async_connection_readonly.execute(query)
    assert result.has_next()
    assert result.get_next() == [35]
    assert not result.has_next()
    result.close()

    query = "MATCH (a:person) WHERE a.ID = 2 RETURN a.age;"
    result = await async_connection_readonly.execute(query)
    assert result.has_next()
    assert result.get_next() == [30]
    assert not result.has_next()
    result.close()
    for i in async_connection_readonly.connections_counter:
        assert i == 0


@pytest.mark.asyncio
async def test_async_scan_df(async_connection_readwrite):
    nodes = pa.Table.from_arrays(
        [
            pa.array([1, 2, 3], type=pa.int32()),
            pa.array(["a", "b", "c"], type=pa.string()),
            pa.array([True, False, None], type=pa.bool_()),
        ],
        names=["id", "A", "B"],
    )
    await async_connection_readwrite.execute(
        "CREATE NODE TABLE pyarrowtab(id INT32, A STRING, B BOOL, PRIMARY KEY(id))"
    )
    await async_connection_readwrite.execute(
        "COPY pyarrowtab FROM $tab", {"tab": nodes}
    )

    result = await async_connection_readwrite.execute(
        "MATCH (t:pyarrowtab) RETURN t.id AS id, t.A AS A, t.B AS B ORDER BY t.id"
    )
    assert result.get_next() == [1, "a", True]
    assert result.get_next() == [2, "b", False]
    assert result.get_next() == [3, "c", None]
    result.close()

    for i in async_connection_readwrite.connections_counter:
        assert i == 0


@pytest.mark.asyncio
async def test_async_query_concurrent(async_connection_readonly):
    num_queries = 100
    queries = [f"RETURN {i};" for i in range(num_queries)]
    results = await asyncio.gather(
        *[async_connection_readonly.execute(query) for query in queries]
    )
    for i, result in enumerate(results):
        assert result.has_next()
        assert result.get_next() == [i]
        assert not result.has_next()
        result.close()
    for i in async_connection_readonly.connections_counter:
        assert i == 0


@pytest.mark.asyncio
async def test_async_query_multiple_results(async_connection_readonly):
    query = "MATCH (a:person) WHERE a.ID = 0 RETURN a.age; MATCH (a:person) WHERE a.ID = 2 RETURN a.age;"
    results = await async_connection_readonly.execute(query)
    assert len(results) == 2
    result = results[0]
    assert result.has_next()
    assert result.get_next() == [35]
    assert not result.has_next()

    result = results[1]
    assert result.has_next()
    assert result.get_next() == [30]
    assert not result.has_next()
    for result in results:
        result.close()
    for i in async_connection_readonly.connections_counter:
        assert i == 0


@pytest.mark.asyncio
async def test_async_connection_create_and_close():
    db = lb.Database(":memory:", buffer_pool_size=2**28)
    async_connection = lb.AsyncConnection(db)
    for _ in range(10):
        res = await async_connection.execute("RETURN 1;")
        assert res.has_next()
        assert res.get_next() == [1]
        assert not res.has_next()
        res.close()
    num_queries = 100
    queries = [f"RETURN {i};" for i in range(num_queries)]
    results = await asyncio.gather(
        *[async_connection.execute(query) for query in queries]
    )
    for i, result in enumerate(results):
        assert result.has_next()
        assert result.get_next() == [i]
        assert not result.has_next()
        result.close()
    async_connection.close()
    db.close()


def test_acquire_connection(async_connection_readonly):
    conn = async_connection_readonly.acquire_connection()
    assert conn is not None
    assert async_connection_readonly.connections_counter[0] == 1
    result = conn.execute("RETURN 1;")
    assert result.has_next()
    assert result.get_next() == [1]
    assert not result.has_next()
    result.close()
    async_connection_readonly.release_connection(conn)
    for i in async_connection_readonly.connections_counter:
        assert i == 0


# range() is bound once and the two UNWINDs multiply it, so these run for long
# enough to cancel mid-flight without materializing large lists.
LONG_QUERY = "WITH range(1, 30000) AS r UNWIND r AS x UNWIND r AS y RETURN sum(x * y)"


async def _wait_until_idle(
    async_connection: lb.AsyncConnection, timeout: float = 5.0
) -> None:
    deadline = time.monotonic() + timeout
    while any(async_connection.connections_counter):
        assert time.monotonic() < deadline, async_connection.connections_counter
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_async_cancel_running_query_raises(
    async_connection_readonly: lb.AsyncConnection,
) -> None:
    task = asyncio.create_task(async_connection_readonly.execute(LONG_QUERY))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    # The query was interrupted, so its connection frees up long before the
    # query could have finished on its own.
    await _wait_until_idle(async_connection_readonly)


@pytest.mark.asyncio
async def test_async_wait_for_timeout_raises(
    async_connection_readonly: lb.AsyncConnection,
) -> None:
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(async_connection_readonly.execute(LONG_QUERY), 0.3)
    await _wait_until_idle(async_connection_readonly)


@pytest.mark.asyncio
async def test_async_cancel_queued_query_spares_running_query(
    async_connection_readonly: lb.AsyncConnection,
) -> None:
    async_connection = lb.AsyncConnection(
        async_connection_readonly.database,
        max_concurrent_queries=1,
        max_threads_per_query=4,
    )
    try:
        running = asyncio.create_task(async_connection.execute(LONG_QUERY))
        queued = asyncio.create_task(async_connection.execute("RETURN 1;"))
        await asyncio.sleep(0.1)
        queued.cancel()
        await asyncio.sleep(0.1)
        running_alive = not running.done()
        running.cancel()
        outcomes = await asyncio.gather(queued, running, return_exceptions=True)
        assert all(isinstance(o, asyncio.CancelledError) for o in outcomes), outcomes
        assert running_alive
        await _wait_until_idle(async_connection)
    finally:
        async_connection.close()


@pytest.mark.asyncio
async def test_async_cancel_during_compile_still_interrupts(
    async_connection_readonly: lb.AsyncConnection,
) -> None:
    # An interrupt sent before execution starts is cleared by the engine, so a
    # cancel that lands in that window must be repeated.
    conn = async_connection_readonly.connections[0]
    execute = conn.execute

    def slow_start(*args: Any, **kwargs: Any) -> Any:
        time.sleep(0.2)
        return execute(*args, **kwargs)

    conn.execute = slow_start
    task = asyncio.create_task(async_connection_readonly.execute(LONG_QUERY))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    started = time.monotonic()
    await _wait_until_idle(async_connection_readonly)
    assert time.monotonic() - started < 2


@pytest.mark.asyncio
async def test_async_execute_prepared_statement_from_other_connection(
    async_connection_readonly: lb.AsyncConnection,
) -> None:
    conn = lb.Connection(async_connection_readonly.database)
    prepared_statement = conn._prepare("RETURN $x;")
    result = await async_connection_readonly.execute(prepared_statement, {"x": 7})
    assert result.get_next() == [7]
    result.close()
    for i in async_connection_readonly.connections_counter:
        assert i == 0
    conn.close()
