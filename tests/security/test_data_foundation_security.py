"""P02 security boundary tests."""

import ast
from pathlib import Path


def test_data_modules_do_not_import_network_or_process_clients() -> None:
    root = Path(__file__).resolve().parents[2] / "src/aegisquant/data"
    forbidden = {"httpx", "requests", "socket", "subprocess", "urllib"}
    for path in root.glob("*.py"):
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
        assert imported_roots.isdisjoint(forbidden), path.name


def test_data_main_module_is_inert_when_imported() -> None:
    path = Path(__file__).resolve().parents[2] / "src/aegisquant/data/__main__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    guards = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and "__name__" in ast.unparse(node.test)
    ]
    assert guards
