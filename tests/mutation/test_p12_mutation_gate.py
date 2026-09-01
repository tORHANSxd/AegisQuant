"""P12 mutation score is an executable phase gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast


def test_p12_mutation_score_meets_threshold(project_root: Path) -> None:
    payload = cast(
        "dict[str, object]",
        json.loads(
            (project_root / "reports/testing/P12_MUTATION_RESULTS.json").read_text(encoding="utf-8")
        ),
    )
    score = cast("float", payload["score"])
    threshold = cast("float", payload["threshold"])
    assert payload["status"] == "passed"
    assert score >= threshold
    assert payload["survived"] == 0
    assert payload["invalid"] == 0
