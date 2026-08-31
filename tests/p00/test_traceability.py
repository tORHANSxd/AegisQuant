"""Requirements traceability completeness tests."""

import csv
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_generator(project_root: Path) -> ModuleType:
    """Load the deterministic generator directly from the repository."""
    path = project_root / "scripts/generate_traceability.py"
    spec = importlib.util.spec_from_file_location("generate_traceability", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_normative_keyword_occurrence_is_traced(project_root: Path) -> None:
    module = load_generator(project_root)
    source = project_root / "AegisQuant_v3.1_Multimodal_Event_Intelligence_Codex_Master_Taskbook.md"
    expected = module.requirements_from_lines(source.read_text(encoding="utf-8").splitlines())
    matrix_path = project_root / "state/REQUIREMENTS_TRACEABILITY.csv"
    with matrix_path.open(encoding="utf-8", newline="") as matrix_file:
        rows = list(csv.DictReader(matrix_file))

    assert len(expected) == 466
    assert len(rows) == len(expected)
    assert len({row["requirement_id"] for row in rows}) == len(rows)
    observed = [
        (int(row["source_line"]), row["normative_keyword"], row["requirement_text"]) for row in rows
    ]
    wanted = [(item.line_number, item.keyword, item.clause) for item in expected]
    assert observed == wanted
    assert all(row["implementation_artifact"] for row in rows)
    assert all(row["verification_artifact"] for row in rows)


def test_p00_requirements_have_explicit_status(project_root: Path) -> None:
    with (project_root / "state/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as matrix_file:
        rows = list(csv.DictReader(matrix_file))

    p00_rows = [row for row in rows if "P00" in row["owner_phase"]]
    assert p00_rows
    assert {row["status"] for row in p00_rows} <= {"planned", "verified"}
