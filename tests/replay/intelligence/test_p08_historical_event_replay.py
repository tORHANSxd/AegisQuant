from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

from aegisquant.data.hashing import sha256_file


def test_fomc_btc_replay_fixture_is_checksum_fixed_and_point_in_time(
    project_root: Path,
) -> None:
    fixture_root = project_root / "tests/fixtures/p08"
    manifest = cast(
        "dict[str, object]",
        json.loads((fixture_root / "fixture_manifest.json").read_text(encoding="utf-8")),
    )
    event = cast("dict[str, object]", manifest["event"])
    market = cast("dict[str, object]", manifest["market"])
    assert (
        sha256_file(fixture_root / str(event["normalized_fixture"]))
        == event["normalized_fixture_sha256"]
    )
    market_path = fixture_root / str(market["subset_fixture"])
    assert sha256_file(market_path) == market["subset_fixture_sha256"]
    with market_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == market["rows"] == 21

    evidence = cast(
        "dict[str, object]",
        json.loads(
            (project_root / "reports/data/P08_EVENT_REPLAY_EVIDENCE.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    assert evidence["post_event_rows_used_before_prediction"] == 0
    assert evidence["pre_event_rows_used_for_prediction"] == 10
    assert evidence["modalities"] == ["EVENT_ONLY", "FUSED", "MARKET_ONLY"]
    assert evidence["common_cost_rate"] == "0.0005"
    assert evidence["final_holdout_opened"] is False
