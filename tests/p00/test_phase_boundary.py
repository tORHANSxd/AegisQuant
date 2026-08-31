"""Ensure P00 does not contain future-phase implementation."""

from pathlib import Path


def test_only_bootstrap_package_contains_python_implementation(project_root: Path) -> None:
    package_root = project_root / "src/aegisquant"
    implementation_files = {
        path.relative_to(package_root).as_posix() for path in package_root.rglob("*.py")
    }

    assert implementation_files == {
        "__init__.py",
        "bootstrap/__init__.py",
        "bootstrap/live_lock.py",
    }


def test_future_service_directories_are_empty(project_root: Path) -> None:
    files = [path for path in (project_root / "services").rglob("*") if path.is_file()]
    assert files == []
