"""P05 mutation score acceptance gate."""

import json
from pathlib import Path


def test_p05_mutation_report_meets_configured_threshold(project_root: Path) -> None:
    payload = json.loads(
        (project_root / "reports/testing/P05_MUTATION_RESULTS.json").read_text(encoding="utf-8")
    )
    assert payload["phase"] == "P05"
    assert payload["status"] == "passed"
    assert payload["baseline_exit_code"] == 0
    assert payload["invalid"] == 0
    assert payload["score"] >= payload["threshold"] >= 0.90
