"""Exact runtime and direct dependency lock tests."""

import json
import re
import tomllib
from pathlib import Path

EXACT_REQUIREMENT = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^=<>~!]+$")


def test_python_direct_dependencies_are_exact(project_root: Path) -> None:
    payload = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = list(payload["project"]["dependencies"])
    for group in payload["dependency-groups"].values():
        requirements.extend(group)

    assert requirements
    assert all(EXACT_REQUIREMENT.fullmatch(requirement) for requirement in requirements)
    assert (project_root / ".python-version").read_text(encoding="utf-8").strip() == "3.13.15"


def test_web_direct_dependencies_are_exact(project_root: Path) -> None:
    root_package = json.loads((project_root / "package.json").read_text(encoding="utf-8"))
    web_package = json.loads((project_root / "apps/web/package.json").read_text(encoding="utf-8"))
    versions = {**web_package["dependencies"], **web_package["devDependencies"]}

    assert root_package["engines"] == {"node": "24.20.0", "pnpm": "11.24.0"}
    assert all(not version.startswith(("^", "~", ">", "<", "*")) for version in versions.values())


def test_dependency_matrix_is_fail_closed(project_root: Path) -> None:
    matrix = json.loads((project_root / "state/DEPENDENCY_MATRIX.json").read_text(encoding="utf-8"))

    assert matrix["policy"]["exact_direct_versions"] is True
    assert matrix["policy"]["candidate_runtime_is_production"] is False
    assert matrix["policy"]["contract_failure_blocks_acceptance"] is True
    assert "live_execution_adapter" in matrix["deferred_components"]
