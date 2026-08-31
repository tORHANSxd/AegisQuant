"""Repository directory bootstrap tests."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


def load_bootstrap(project_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "bootstrap_directories", project_root / "scripts/bootstrap_directories.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_is_complete_and_materialized(project_root: Path) -> None:
    payload = json.loads(
        (project_root / "state/DIRECTORY_MANIFEST.json").read_text(encoding="utf-8")
    )
    directories = payload["directories"]

    assert len(directories) == len(set(directories)) == 152
    assert directories == sorted(directories)
    assert all((project_root / directory).is_dir() for directory in directories)


def test_bootstrap_is_safe_and_idempotent(project_root: Path, tmp_path: Path) -> None:
    module = load_bootstrap(project_root)
    manifest = project_root / "state/DIRECTORY_MANIFEST.json"

    first = module.create_directories(tmp_path, manifest)
    second = module.create_directories(tmp_path, manifest)

    assert first == second
    assert all(path.is_dir() for path in first)
    with pytest.raises(ValueError, match="unsafe"):
        module.validated_relative_path("../escape")
    with pytest.raises(ValueError, match="unsafe"):
        module.validated_relative_path("C:/escape")
