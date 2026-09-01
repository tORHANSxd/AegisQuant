"""P11 architecture proof that research/model code cannot own risk overrides."""

from __future__ import annotations

import ast
from pathlib import Path

import aegisquant.risk as risk_api


def test_research_and_model_packages_do_not_import_independent_risk_engine(
    project_root: Path,
) -> None:
    roots = (
        project_root / "src/aegisquant/research",
        project_root / "src/aegisquant/intelligence",
    )
    violations: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(
                    name == "aegisquant.risk" or name.startswith("aegisquant.risk.")
                    for name in names
                ):
                    violations.append(path.relative_to(project_root).as_posix())
    assert violations == []


def test_public_risk_api_exposes_no_override_or_bypass_symbol() -> None:
    exported = set(risk_api.__all__)
    assert all("override" not in name.casefold() for name in exported)
    assert all("bypass" not in name.casefold() for name in exported)
