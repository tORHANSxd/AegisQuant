"""P09 mutation score evidence gate."""

import json
from pathlib import Path


def test_p09_mutation_report_meets_configured_threshold(project_root: Path) -> None:
    payload = json.loads(
        (project_root / "reports/testing/P09_MUTATION_RESULTS.json").read_text(encoding="utf-8")
    )
    assert payload["phase"] == "P09"
    assert payload["status"] == "passed"
    assert payload["baseline_exit_code"] == 0
    assert payload["invalid"] == 0
    assert payload["score"] >= payload["threshold"] >= 0.90
