"""Bootstrap modules must be inert when imported."""

import ast
from pathlib import Path


def test_live_lock_has_no_network_process_or_environment_access() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / "src/aegisquant/bootstrap/live_lock.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", maxsplit=1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", maxsplit=1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert imported_roots.isdisjoint({"socket", "subprocess", "requests", "httpx", "os"})
