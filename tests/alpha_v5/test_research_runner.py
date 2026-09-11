"""Execute the saved-configuration path, including strict Decimal deserialization."""

from datetime import timedelta
from pathlib import Path

import yaml

from aegisquant.portfolio.economic_gate import EconomicGatePolicy
from aegisquant.research.validation.calendar_walkforward import CalendarFold
from aegisquant.research.validation.cat_replay import DEFAULT_MARKET
from scripts.run_alpha_r4 import read_result
from scripts.run_alpha_v4_audit import AuditInputs
from scripts.run_alpha_v5_research import CONFIG, run_one
from tests.integration.cat_helpers import fixture


def test_registered_json_policy_reaches_actual_funded_replay(tmp_path: Path):
    spec, bars, features = fixture()
    end = bars[-1].event_time + timedelta(hours=4)
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config["development"]["test_start"] = spec.start_time.isoformat()
    config["development"]["end_exclusive"] = end.isoformat()
    fold = CalendarFold(
        "fixture",
        spec.created_at,
        spec.created_at,
        spec.start_time,
        end,
        (),
        (),
        tuple(range(280, 340)),
        12,
        1,
    )
    source = tmp_path / "synthetic-source.txt"
    source.write_text("synthetic in-memory bars", encoding="utf-8")
    indices = {t: i for i, t in enumerate(features.available_times)}
    data: AuditInputs = (
        source,
        DEFAULT_MARKET,
        bars,
        features,
        (),
        (),
        (fold,),
        indices,
        dict.fromkeys(features.available_times, True),
    )
    manifest = {
        "config": config,
        "registered_at": spec.created_at.isoformat(),
        "sha256": "a" * 64,
        "code_sha256": "b" * 64,
        "gate": EconomicGatePolicy().model_dump(mode="json"),
    }
    run_one(tmp_path, manifest, {"arm": "G1", "symbol": "BTCUSDT", "cost": "1"}, data)
    folder = tmp_path / "runs/G1/BTCUSDT/1"
    result = read_result(folder)
    assert len(result.fills) >= 2
    assert result.positions[-1].quantity == 0
    assert all(p.cash >= 0 for p in result.equity_curve)
    assert (folder / "completion.json").is_file()
    assert (folder / "equity.parquet").is_file()
