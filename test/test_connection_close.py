from __future__ import annotations

import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import ladybug as lb
import pytest

if TYPE_CHECKING:
    from pathlib import Path

# range() is bound once and the two UNWINDs multiply it, so this runs for tens of
# seconds without materializing large lists.
LONG_QUERY = "WITH range(1, 60000) AS r UNWIND r AS x UNWIND r AS y RETURN sum(x * y)"

# Closing a connection while a query runs used to hang or crash the process, so
# each scenario runs in its own interpreter.
PRELUDE = """
import asyncio, sys, threading, time
import ladybug as lb

db = lb.Database(sys.argv[1])
setup = lb.Connection(db)
setup.execute("CREATE NODE TABLE T(id INT64, PRIMARY KEY(id))")
setup.close()
LONG_QUERY = {long_query!r}
"""

SCENARIOS = {
    "close_from_inside_a_call": """
conn = lb.Connection(db)

def close_inside(query, parameters):
    conn.close()

# Stands in for anything that closes the connection from inside one of its own
# calls on the same thread, such as a finalizer that runs mid-call.
conn._rewrite_local_scan_object = close_inside
started = time.monotonic()
try:
    conn.execute("RETURN 1")
    outcome = "finished"
except RuntimeError as e:
    outcome = str(e)
print("CLOSE", time.monotonic() - started)
print("OUTCOME", outcome)
""",
    "close_from_a_udf": """
conn = lb.Connection(db)

def closer(x: int) -> int:
    if x == 3:
        conn.close()
    return x

# UDFs run on engine threads, so this is not caught as a call on the same thread.
conn.create_function("closer", closer)
started = time.monotonic()
try:
    conn.execute("UNWIND range(1, 5) AS i RETURN closer(i)").get_all()
    outcome = "finished"
except RuntimeError as e:
    outcome = str(e)
print("CLOSE", time.monotonic() - started)
print("OUTCOME", outcome)
""",
    "query_without_parameters": """
conn = lb.Connection(db)
outcome = []

def run():
    try:
        conn.execute(LONG_QUERY)
        outcome.append("finished")
    except RuntimeError as e:
        outcome.append(str(e))

worker = threading.Thread(target=run)
worker.start()
time.sleep(0.3)
started = time.monotonic()
conn.close()
print("CLOSE", time.monotonic() - started)
worker.join()
print("OUTCOME", outcome[0])
""",
    "query_with_parameters": """
conn = lb.Connection(db)
outcome = []

def run():
    try:
        conn.execute(LONG_QUERY.replace("60000", "$n"), {"n": 60000})
        outcome.append("finished")
    except RuntimeError as e:
        outcome.append(str(e))

worker = threading.Thread(target=run)
worker.start()
time.sleep(0.3)
started = time.monotonic()
conn.close()
print("CLOSE", time.monotonic() - started)
worker.join()
print("OUTCOME", outcome[0])
""",
    "write": """
conn = lb.Connection(db)
outcome = []

def run():
    try:
        conn.execute("UNWIND range(1, 500000) AS i CREATE (:T {id: i})")
        outcome.append("finished")
    except RuntimeError as e:
        outcome.append(str(e))

worker = threading.Thread(target=run)
worker.start()
time.sleep(0.3)
started = time.monotonic()
conn.close()
print("CLOSE", time.monotonic() - started)
worker.join()
print("OUTCOME", outcome[0])
""",
    "async_connection": """
async def main():
    async_conn = lb.AsyncConnection(db, max_concurrent_queries=2)
    task = asyncio.create_task(async_conn.execute(LONG_QUERY))
    await asyncio.sleep(0.3)
    started = time.monotonic()
    async_conn.close()
    print("CLOSE", time.monotonic() - started)
    try:
        await task
        print("OUTCOME finished")
    except RuntimeError as e:
        print("OUTCOME", e)

asyncio.run(main())
""",
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_close_with_query_in_flight(tmp_path: Path, scenario: str) -> None:
    script = (
        textwrap.dedent(PRELUDE.format(long_query=LONG_QUERY)) + SCENARIOS[scenario]
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / "db")],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{scenario}: close() hung")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "OUTCOME" in proc.stdout
    if scenario == "close_from_inside_a_call":
        assert "same connection" in proc.stdout, proc.stdout
    if scenario == "close_from_a_udf":
        assert "from a UDF" in proc.stdout, proc.stdout
    if scenario != "write":
        # A running read is interrupted rather than waited for. A write is
        # interrupted too, but undoing the rows it already inserted takes seconds,
        # so its close time is not bounded here.
        close_seconds = float(proc.stdout.split("CLOSE")[1].split()[0])
        assert close_seconds < 5, close_seconds


def test_execute_after_close_raises(tmp_path: Path) -> None:
    db = lb.Database(tmp_path / "db")
    conn = lb.Connection(db)
    conn.close()
    with pytest.raises(RuntimeError, match="Connection is closed"):
        conn.execute("RETURN 1")
    db.close()
