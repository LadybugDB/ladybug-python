from pathlib import Path

from lbug_test_paths import _resolve_lbug_root


def test_resolve_lbug_root_handles_nested_ci_checkout() -> None:
    repo_root = Path(
        "/home/runner/work/ladybug-python/ladybug-python/ladybug/tools/python_api"
    )

    assert (
        _resolve_lbug_root(repo_root)
        .as_posix()
        .endswith("/ladybug-python/ladybug-python/ladybug")
    )


def test_nested_ci_checkout_dataset_path_is_outside_python_api_tree() -> None:
    repo_root = Path(
        "/home/runner/work/ladybug-python/ladybug-python/ladybug/tools/python_api"
    )

    dataset_root = _resolve_lbug_root(repo_root) / "dataset"
    assert dataset_root.as_posix().endswith(
        "/ladybug-python/ladybug-python/ladybug/dataset"
    )


def test_nested_ci_checkout_prefers_parent_ladybug_root_over_local_dataset_dir() -> (
    None
):
    repo_root = Path(
        "/home/runner/work/ladybug-python/ladybug-python/ladybug/tools/python_api"
    )

    resolved = _resolve_lbug_root(repo_root)
    assert resolved.name == "ladybug"
    assert "/tools/python_api" not in resolved.as_posix()
