"""P06 full-scale benchmark evidence gate."""

import json
from pathlib import Path
from typing import cast


def test_p06_event_vector_throughput_memory_and_stability_evidence(
    project_root: Path,
) -> None:
    payload = cast(
        dict[str, object],
        json.loads(
            (project_root / "reports/performance/P06_BACKTEST_BENCHMARK.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    event = cast(dict[str, object], payload["event"])
    vector = cast(dict[str, object], payload["vector"])
    stability = cast(dict[str, object], payload["stability"])

    assert payload["passed"] is True
    assert payload["live_trading_locked"] is True
    assert payload["real_account_connected"] is False
    assert int(cast(int, event["input_event_count"])) >= 10_000
    assert event["processed_event_count"] == event["input_event_count"]
    assert event["passed"] is True
    assert int(cast(int, vector["input_bar_count"])) >= 100_000
    assert vector["passed"] is True
    assert int(cast(int, stability["replays"])) >= 5
    assert stability["event_unique_hashes"] == 1
    assert stability["vector_unique_hashes"] == 1
