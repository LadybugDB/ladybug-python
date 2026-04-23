from __future__ import annotations

import subprocess
import sys


def test_import_ladybug_before_torch_does_not_crash() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import ladybug; import torch"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
