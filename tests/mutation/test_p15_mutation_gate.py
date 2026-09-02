"""P15 mutation evidence gate."""

from __future__ import annotations

import json
from pathlib import Path


def test_p15_mutation_evidence_passes(project_root: Path) -> None:
    payload = json.loads(
        (project_root / "reports/testing/P15_MUTATION_RESULTS.json").read_text(encoding="utf-8")
    )
    assert payload["phase"] == "P15"
    assert payload["status"] == "passed"
    assert payload["score"] >= payload["threshold"]
    assert payload["survived"] == 0
    assert payload["invalid"] == 0
