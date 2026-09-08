"""Behavioral contracts for the fixed-prediction audit, including funded replay."""

import json
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import yaml

from aegisquant.portfolio.economic_gate import (
    EconomicAction,
    EconomicGateDecision,
    EconomicGatePolicy,
    decide_economic_transition,
)
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from aegisquant.research.models.economic_gate import EconomicForecast
from aegisquant.research.validation.cat_contract import (
    CatAuditPolicy,
    audit_arms,
    compile_legacy_config,
)
from aegisquant.research.validation.cat_replay import executable_labels, replay_cat
from scripts.audit_alpha_v4_data_quality import archive_millis
from tests.integration.cat_helpers import ROOT, fixture
from tests.p06.helpers import NOW
from tests.unit.portfolio.test_dynamic_economic_gate import forecast


def test_label_contract_retains_20h_and_explicit_six_intervals_are_24h():
    _, bars, _ = fixture()
    old, old_ends = executable_labels(bars, 6)
    new, new_ends = executable_labels(bars, holding_intervals=6)
    assert old[0] == float(bars[6].open / bars[1].open - 1)
    assert new[0] == float(bars[7].open / bars[1].open - 1)
    assert old_ends[0] is not None and new_ends[0] is not None
    assert old_ends[0] - bars[1].event_time == timedelta(hours=20)
    assert new_ends[0] - bars[1].event_time == timedelta(hours=24)
    gap, ends = executable_labels((*bars[:3], *bars[4:]), holding_intervals=6)
    assert np.isnan(gap[0]) and ends[0] is None


def test_exit_cost_uses_position_and_same_latency_when_cash_is_small():
    small, large = [
        estimate_spot_transition_costs(
            available_time=NOW,
            natr=Decimal("0.01"),
            quote_volume=Decimal("100000"),
            order_notional=Decimal("1"),
            exit_order_notional=Decimal(value),
            exit_latency_adverse_bps=Decimal("1"),
        )
        for value in ("100", "10000")
    ]
    assert small.entry == large.entry
    assert large.exit.impact == Decimal("0.00025") > small.exit.impact
    assert large.entry.latency_adverse_selection == large.exit.latency_adverse_selection


def gate(
    arm: str,
    value: EconomicForecast | None,
    weight: Decimal = Decimal("0"),
    resize: bool = False,
    trend: bool = True,
) -> EconomicGateDecision:
    costs = estimate_spot_transition_costs(
        available_time=NOW,
        natr=Decimal("0.01"),
        quote_volume=Decimal("1000000"),
        order_notional=Decimal("10000"),
        exit_latency_adverse_bps=Decimal("1"),
    )
    return decide_economic_transition(
        policy=EconomicGatePolicy(),
        forecast=value,
        costs=costs,
        decision_time=NOW,
        current_weight=weight,
        trend_candidate=trend,
        trend_exit_confirmed=not trend,
        data_quality_passed=True,
        risk_allows_entry=True,
        annualized_volatility=Decimal("0.8"),
        resize_permitted=resize,
        audit_policy=audit_arms()[arm],
    )


def test_single_factor_entry_exit_risk_and_missing_forecast():
    assert gate("A1", None).target_weight == Decimal("0.25")
    assert gate("A2", forecast("0.001")).action is EconomicAction.ENTER_LONG
    assert gate("A3", forecast("0.001")).reason == "COST_ENTRY_REJECTED"
    assert gate("A3", forecast("-0.1"), Decimal("0.2")).action is EconomicAction.HOLD_CURRENT
    assert gate("A4", forecast("-0.1"), Decimal("0.2")).action is EconomicAction.EXIT_LONG
    assert gate("A2", None, Decimal("0.2")).action is EconomicAction.HOLD_CURRENT
    assert gate("A2", None, Decimal("0.2"), trend=False).action is EconomicAction.EXIT_LONG
    assert gate("A1", None, Decimal("0.1"), resize=True).target_weight == Decimal("0.25")
    assert gate("A1", None, Decimal("0.3"), resize=True).target_weight == Decimal("0.25")
    assert gate("A1", None, Decimal("0.24"), resize=True).action is EconomicAction.HOLD_CURRENT


def test_v2_replay_uses_causal_reserve_and_full_ledger():
    spec, bars, features = fixture()
    result, trace = replay_cat(
        root=ROOT,
        spec=spec,
        bars=bars,
        features=features,
        feature_indices={time: i for i, time in enumerate(features.available_times)},
        trend_by_time={b.available_time: True for b in bars},
        forecasts={},
        level="C0",
        audit_policy=audit_arms()["C0"],
    )
    assert result.positions[-1].quantity == 0
    assert abs(result.cost_identity_residual) < result.cost_identity_tolerance
    assert all(Decimal(row["cash"]) >= 0 for row in trace)
    assert Decimal(trace[0]["buy_reserve_factor"]) > 1
    assert Decimal(trace[0]["planned_order_notional"]) < Decimal(trace[0]["cash"])
    assert trace[0]["raw_prediction"] is None
    changed = list(bars)
    changed[1] = changed[1].model_copy(
        update={"open": bars[1].open * 10, "high": bars[1].high * 10}
    )
    _, jump = replay_cat(
        root=ROOT,
        spec=spec,
        bars=tuple(changed),
        features=features,
        feature_indices={time: i for i, time in enumerate(features.available_times)},
        trend_by_time={b.available_time: True for b in bars},
        forecasts={},
        level="C0",
        audit_policy=audit_arms()["C0"],
    )
    assert trace[0]["signed_planned_quantity"] == jump[0]["signed_planned_quantity"]
    assert jump[0]["rejection_reason"] is not None


def test_strict_effective_contracts_and_legacy_reproduction_guard():
    effective = compile_legacy_config(ROOT, multi_asset=True)
    assert effective["label_contract"]["holding_intervals"] == 5
    with pytest.raises(ValueError):
        CatAuditPolicy.model_validate({"ignored_setting": True})
    with pytest.raises(ValueError):
        CatAuditPolicy.model_validate({"live_trading": True})
    assert audit_arms()["A1"].sha256 != audit_arms()["A2"].sha256


def test_every_legacy_config_leaf_is_rejected_when_perturbed(tmp_path: Path):
    documents = {
        name: json.loads((ROOT / name).read_text(encoding="utf-8"))
        for name in (
            "artifacts/alpha_v4/walkforward/run_manifest.json",
            "artifacts/alpha_v4_multi_asset/run_manifest.json",
        )
    }
    config_names = (
        "configs/strategies/aegisalpha_cat_v1.yaml",
        "configs/research/aegis_alpha_v4.yaml",
        "configs/research/alpha_v4_multi_asset.yaml",
    )
    for name, document in documents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
    for name in config_names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())

    def leaves(value: Any, prefix: tuple[str | int, ...] = ()) -> Iterator[tuple[str | int, ...]]:
        if isinstance(value, dict):
            mapping = cast(dict[str, Any], value)
            for key, item in mapping.items():
                yield from leaves(item, (*prefix, key))
        elif isinstance(value, list):
            sequence = cast(list[Any], value)
            for index, item in enumerate(sequence):
                yield from leaves(item, (*prefix, index))
        else:
            yield prefix

    count = 0
    for name in config_names:
        original = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
        for keys in leaves(original):
            changed = json.loads(json.dumps(original))
            target = changed
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = "UNREGISTERED_PERTURBATION"
            (tmp_path / name).write_text(yaml.safe_dump(changed), encoding="utf-8")
            with pytest.raises(ValueError, match="every field is frozen"):
                compile_legacy_config(tmp_path, multi_asset=True)
            count += 1
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    assert count > 100
    assert compile_legacy_config(tmp_path, multi_asset=True)["effective_sha256"]


def test_forecast_metadata_pair_and_archive_time_units():
    data = forecast().model_dump(mode="python")
    with pytest.raises(ValueError, match="present together"):
        EconomicForecast.model_validate({**data, "raw_prediction": Decimal("0.1")})
    with pytest.raises(ValueError, match="explicit holding"):
        EconomicForecast.model_validate({**data, "label_contract_version": "holding-intervals-v2"})
    assert archive_millis(1735689600000000, "2025-01-01") == 1735689600000
    assert archive_millis(1735693199999999, "2025-01-01") == 1735693199999
    assert archive_millis(1704067200000, "2024-01-01") == 1704067200000
