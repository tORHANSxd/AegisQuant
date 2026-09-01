"""Reject common incomplete implementation markers outside frozen inputs."""

import re
from pathlib import Path

TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".yaml", ".yml", ".toml"}
FORBIDDEN = re.compile(r"\b(?:TODO|FIXME|NotImplementedError)\b|\.\.\.\s*(?:#.*)?$")


def test_no_incomplete_markers_in_implementation(project_root: Path) -> None:
    excluded = {
        "node_modules",
        ".venv",
        ".tools",
        ".git",
        ".next",
        ".runtime",
        "coverage",
        "generated",
        "playwright-report",
        "storybook-static",
        "test-results",
    }
    violations: list[str] = []
    for path in project_root.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if path.name == "test_no_incomplete_implementation.py":
            continue
        if any(part in excluded for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        if FORBIDDEN.search(text):
            violations.append(path.relative_to(project_root).as_posix())

    assert violations == []
