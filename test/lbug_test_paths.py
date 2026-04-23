import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.resolve()


def _resolve_lbug_root(anchor: Path | None = None) -> Path:
    repo_root = (anchor or _REPO_ROOT).resolve()
    for candidate in (repo_root, *repo_root.parents):
        if candidate.name == "python_api" and candidate.parent.name == "tools":
            return candidate.parent.parent
        if (candidate / "dataset").is_dir():
            return candidate
        if (candidate / "ladybug" / "dataset").is_dir():
            return candidate / "ladybug"
    return repo_root


LBUG_ROOT_PATH = _resolve_lbug_root()
DATASET_ROOT = LBUG_ROOT_PATH / "dataset"

if sys.platform == "win32":
    # \ in paths is not supported by lbug's parser
    LBUG_ROOT = LBUG_ROOT_PATH.as_posix()
else:
    LBUG_ROOT = str(LBUG_ROOT_PATH)
