"""Repository governance baseline tests."""

import subprocess
from pathlib import Path

REQUIRED_FILES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".pre-commit-config.yaml",
    "CODEX_BOOTSTRAP.md",
    "CONTRIBUTING.md",
    "LICENSE_POLICY.md",
    "Makefile",
    "README.md",
    "SECURITY.md",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "pyproject.toml",
    "uv.lock",
}


def test_required_repository_files_exist(project_root: Path) -> None:
    missing = sorted(path for path in REQUIRED_FILES if not (project_root / path).is_file())
    assert missing == []


def test_source_repository_uses_main_without_remote(project_root: Path) -> None:
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    remotes = subprocess.run(
        ["git", "remote"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert branch == "main"
    assert remotes == []
