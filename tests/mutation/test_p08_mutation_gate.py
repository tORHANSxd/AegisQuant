"""P08 mutation score evidence gate."""

import json
from pathlib import Path


def test_p08_mutation_report_meets_configured_threshold(project_root: Path) -> None:
    payload = json.loads(
        (project_root / "reports/testing/P08_MUTATION_RESULTS.json").read_text(encoding="utf-8")
    )
    assert payload["phase"] == "P08"
    assert payload["status"] == "passed"
    assert payload["baseline_exit_code"] == 0
    assert payload["invalid"] == 0
    assert payload["score"] >= payload["threshold"] >= 0.90
