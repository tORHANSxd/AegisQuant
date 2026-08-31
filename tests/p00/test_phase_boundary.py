"""Ensure the frozen P00 artifact snapshot contained no future implementation."""

import json
from pathlib import Path


def test_only_bootstrap_package_contains_python_implementation(project_root: Path) -> None:
    manifest = json.loads(
        (project_root / "reports/phases/P00/ARTIFACT_MANIFEST.json").read_text(encoding="utf-8")
    )
    implementation_files = {
        Path(entry["path"]).relative_to("src/aegisquant").as_posix()
        for entry in manifest["artifacts"]
        if entry["path"].startswith("src/aegisquant/") and entry["path"].endswith(".py")
    }

    assert implementation_files == {
        "__init__.py",
        "bootstrap/__init__.py",
        "bootstrap/live_lock.py",
    }


def test_future_service_directories_are_empty(project_root: Path) -> None:
    manifest = json.loads(
        (project_root / "reports/phases/P00/ARTIFACT_MANIFEST.json").read_text(encoding="utf-8")
    )
    service_files = [
        entry["path"] for entry in manifest["artifacts"] if entry["path"].startswith("services/")
    ]
    assert service_files == []
