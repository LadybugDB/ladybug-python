from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# The driver fills its import cache on first use, and the cache cannot be reset within a
# process, so every attempt runs in a fresh interpreter. Only a free-threaded build with the GIL
# disabled can expose a race; on other builds this is a smoke test.
FREE_THREADED = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))


@pytest.mark.parametrize("attempt", range(10 if FREE_THREADED else 1))
def test_concurrent_first_use_of_the_import_cache(
    attempt: int, build_dir: Path
) -> None:
    code = dedent(f"""
        import sys
        import threading

        sys.path.append(r"{build_dir!s}")

        import ladybug as lb

        db = lb.Database(":memory:")
        conns = [lb.Connection(db) for _ in range(16)]
        start = threading.Barrier(len(conns))
        errors = []

        def run(conn, n):
            start.wait()
            try:
                assert conn.execute("RETURN $n", {{"n": n}}).get_next() == [n]
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=run, args=(c, i)) for i, c in enumerate(conns)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
    """)
    env = {**os.environ, "PYTHON_GIL": "0"} if FREE_THREADED else None
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (result.returncode, result.stderr)
