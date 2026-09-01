from __future__ import annotations

import importlib.metadata
from pathlib import Path


def test_research_source_contains_no_random_time_split_escape_hatch(project_root: Path) -> None:
    source_root = project_root / "src/aegisquant/research"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))
    assert "train_test_split" not in source
    assert "shuffle=True" not in source.replace(" ", "")
    assert "AQ-RESEARCH-RANDOM-TIME-SPLIT-FORBIDDEN" in source


def test_scikit_learn_contract_is_pinned_to_validated_version() -> None:
    assert importlib.metadata.version("scikit-learn") == "1.9.0"
