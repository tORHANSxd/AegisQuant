"""Repository secret-boundary tests."""

import re
from pathlib import Path

SUSPICIOUS_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?secret|private[_-]?key|password|cookie|verification[_-]?code)"
    r"\s*[:=]\s*[\"'](?!disabled|prohibited|not_provided)[^\"']{6,}[\"']"
)


def test_no_local_secret_files_are_present() -> None:
    root = Path(__file__).resolve().parents[2]
    prohibited_suffixes = {".pem", ".key", ".p12", ".pfx", ".session"}
    secret_files = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and ".venv" not in path.parts
        and ".tools" not in path.parts
        and "node_modules" not in path.parts
        and (path.name.startswith(".env") or path.suffix.lower() in prohibited_suffixes)
    ]
    assert secret_files == []


def test_no_suspicious_secret_assignment_in_project_text() -> None:
    root = Path(__file__).resolve().parents[2]
    excluded = {".git", ".venv", ".tools", "node_modules", "docs"}
    violations: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.parts):
            continue
        if path.suffix.lower() not in {".py", ".json", ".yaml", ".yml", ".toml", ".ts", ".tsx"}:
            continue
        if SUSPICIOUS_ASSIGNMENT.search(path.read_text(encoding="utf-8")):
            violations.append(path.relative_to(root).as_posix())
    assert violations == []
