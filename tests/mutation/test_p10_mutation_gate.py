from __future__ import annotations

import json
from pathlib import Path
from typing import cast


def test_p10_mutation_score_meets_threshold(project_root: Path) -> None:
    payload = cast(
        "dict[str, object]",
        json.loads(
            (project_root / "reports/testing/P10_MUTATION_RESULTS.json").read_text(encoding="utf-8")
        ),
    )
    assert payload["phase"] == "P10"
    assert payload["status"] == "passed"
    assert cast(float, payload["score"]) >= cast(float, payload["threshold"])
    assert payload["invalid"] == 0
