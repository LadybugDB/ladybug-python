from __future__ import annotations

import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# Each scenario sends SIGINT to itself one second into a query that runs for many
# seconds, and reports how the query ended.
PRELUDE = """
import os, signal, sys, threading, time
import ladybug as lb

db = lb.Database(sys.argv[1])
conn = lb.Connection(db)
LONG_QUERY = "WITH range(1, $n) AS r UNWIND r AS x UNWIND r AS y RETURN sum(x * y)"
threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGINT)).start()
"""

SCENARIOS = {
    "query": "conn.execute(LONG_QUERY.replace('$n', '40000'))",
    "execute_with_parameters": "conn.execute(LONG_QUERY, {'n': 40000})",
    "query_as_arrow": "conn.query_as_arrow(LONG_QUERY.replace('$n', '40000'), 1000)",
}

RUN = """
started = time.monotonic()
try:
    {call}
    print("OUTCOME finished")
except KeyboardInterrupt:
    print("OUTCOME KeyboardInterrupt")
print("ELAPSED", time.monotonic() - started)
print("AFTER", conn.execute("RETURN 1").get_next()[0])
"""

CUSTOM_HANDLER = """
received = []
signal.signal(signal.SIGINT, lambda signum, frame: received.append(signum))
result = conn.execute(LONG_QUERY.replace("$n", "20000")).get_next()[0]
time.sleep(0.2)
print("OUTCOME", "finished" if result else "empty", "handled" if received else "missed")
"""


def run_script(tmp_path: Path, body: str) -> str:
    script = textwrap.dedent(PRELUDE) + textwrap.dedent(body)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / "db")],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the query was not interrupted")
    assert proc.returncode == 0, proc.stderr[-2000:]
    return proc.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT is POSIX only")
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_keyboard_interrupt_stops_the_query(tmp_path: Path, scenario: str) -> None:
    stdout = run_script(tmp_path, RUN.format(call=SCENARIOS[scenario]))
    assert "OUTCOME KeyboardInterrupt" in stdout, stdout
    assert float(stdout.split("ELAPSED")[1].split()[0]) < 10, stdout
    assert "AFTER 1" in stdout, stdout


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT is POSIX only")
def test_custom_sigint_handler_still_runs(tmp_path: Path) -> None:
    stdout = run_script(tmp_path, CUSTOM_HANDLER)
    # A custom handler is left alone: the query finishes, then the handler runs.
    assert "OUTCOME finished handled" in stdout, stdout


CLOSE_DURING_QUERY = """
threading.Timer(0.5, conn._connection.close).start()
started = time.monotonic()
try:
    conn.execute(LONG_QUERY.replace('$n', '40000'))
    print("OUTCOME finished")
except KeyboardInterrupt:
    print("OUTCOME KeyboardInterrupt")
print("ELAPSED", time.monotonic() - started)
"""


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT is POSIX only")
def test_keyboard_interrupt_after_close_from_another_thread(tmp_path: Path) -> None:
    # The running call keeps the connection alive, so closing it from another thread
    # returns at once instead of waiting for the query with the GIL held. (Whether the
    # context was freed under the running query would need ASan to observe.)
    stdout = run_script(tmp_path, CLOSE_DURING_QUERY)
    assert "OUTCOME KeyboardInterrupt" in stdout, stdout
    assert float(stdout.split("ELAPSED")[1].split()[0]) < 10, stdout


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT is POSIX only")
def test_failed_handler_check_is_reported_not_raised(tmp_path: Path) -> None:
    script = """
import signal, sys
import ladybug as lb

def broken(signum):
    raise RuntimeError("getsignal is broken")

signal.getsignal = broken
conn = lb.Connection(lb.Database(sys.argv[1]))
print("RESULT", conn.execute("RETURN 1").get_next()[0])
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "db")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "RESULT 1" in proc.stdout, proc.stdout
    assert "getsignal is broken" in proc.stderr, proc.stderr
