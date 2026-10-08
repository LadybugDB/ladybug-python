from __future__ import annotations

import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# A UDF that calls back into the connection running its query used to wait for
# that query forever, so each scenario runs in its own interpreter.
PRELUDE = """
import sys
import ladybug as lb

db = lb.Database(sys.argv[1])
conn = lb.Connection(db)
other = lb.Connection(db)
target = {target}

def reenter(x: int) -> int:
    return target.execute("RETURN 1").get_next()[0] + x

conn.create_function("reenter", reenter)
try:
    print("OUTCOME", conn.execute({query!r}).get_next()[0])
except RuntimeError as e:
    print("OUTCOME", e)
"""

SCENARIOS = {
    # Arguments from a column: the UDF runs on an engine worker thread.
    "same_connection_on_a_worker": (
        "conn",
        "UNWIND range(1, 3) AS i RETURN sum(reenter(i))",
        "A UDF cannot use a connection while it runs a query.",
    ),
    # A literal argument: the UDF is folded while binding, on the calling thread.
    "same_connection_while_binding": (
        "conn",
        "RETURN reenter(1)",
        "A UDF cannot use a connection while it runs a query.",
    ),
    "idle_other_connection": (
        "other",
        "UNWIND range(1, 3) AS i RETURN sum(reenter(i))",
        "OUTCOME 9",
    ),
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_udf_calling_a_connection(tmp_path: Path, scenario: str) -> None:
    target, query, expected = SCENARIOS[scenario]
    script = textwrap.dedent(PRELUDE.format(target=target, query=query))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / "db")],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{scenario}: hung")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert expected in proc.stdout, proc.stdout
