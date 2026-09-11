"""Synthetic B3 contracts only: never load market data, replay, fit or access holdout."""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import fields
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import numpy as np
import pytest
import yaml

from aegisquant.data.hashing import sha256_file
from aegisquant.research.validation import benchmark_contract as contract
from aegisquant.research.validation.evidence_contract import (
    CostMode,
    audit_cost_path,
    load_evidence_manifest,
)
from aegisquant.research.validation.paired_bootstrap import (
    LOG_GROWTH_ESTIMAND,
    PairedBootstrap,
    holm_adjust,
    paired_block_bootstrap,
    paired_log_growth_bootstrap,
)
from scripts.audit_alpha_profitability_root_causes import benchmark_factorial_attribution
from tests.alpha_v5.test_evidence_contract import statistics_fixture

ROOT = Path(__file__).resolve().parents[2]
START = "2024-01-01T00:00:00+00:00"
END = "2024-01-04T00:00:00+00:00"


def r5_fixture() -> dict[str, Any]:
    # Strategy parameters are configuration, not historical performance or market data.
    config = yaml.safe_load(
        (ROOT / "configs/research/aegis_alpha_v5.yaml").read_text(encoding="utf-8")
    )
    return {"source_head": contract.BASE, "config": config, "gate": {"synthetic_common_gate": True}}


def paths_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    definition = contract.build_benchmark_contract(r5_fixture())
    common = {
        "input_snapshot_sha256": "a" * 64,
        "risk_policy_sha256": definition["shared_gate_sha256"],
        "execution_policy_sha256": "b" * 64,
        "capital_mode": "FIVE_EQUAL_INITIAL_SLEEVES_NO_TRANSFERS",
        "cost_mode": "REDECIDE_FUNDED",
        "cost_multiplier": "1",
        "initial_cash": "50000",
        "symbols": list(contract.SYMBOLS),
        "terminal_exit": "EVALUATION_END_NEXT_OPEN_EXIT_PAID_BOUNDARY_INCLUDED",
        "risk_sizing_basis": "EX_ANTE_PRECEDING_DATA",
    }
    cash = contract.cash_reference(start=START, end=END, capital=Decimal("50000"))
    paths: dict[str, Any] = {}
    for number, arm in enumerate([*contract.ARMS, "CASH"], start=1):
        rows = copy.deepcopy(cash)
        for index, row in enumerate(rows):
            row.update(risk_ready=arm == "CASH" or index >= 2, signal_ready=True)
            if arm != "CASH" and index >= 2:
                profit = (index - 2) * number
                row["equity"] = str(50000 + profit)
                row["position_value"] = str(5000 + profit) if index < len(rows) - 1 else "0"
                row["cash"] = "45000" if index < len(rows) - 1 else row["equity"]
        paths[arm] = {
            "definition": {"signal": "CASH", "control": "CASH"}
            if arm == "CASH"
            else copy.deepcopy(definition["arms"][arm]),
            "common": copy.deepcopy(common),
            "rows": rows,
            "orders": []
            if arm == "CASH"
            else [
                {"time": rows[2]["time"], "side": "BUY", "quantity": "1"},
                {"time": rows[-1]["time"], "side": "SELL", "quantity": "1"},
            ],
            "fills": []
            if arm == "CASH"
            else [
                {"time": rows[2]["time"], "quantity": "1", "reference_price": "5000"},
                {
                    "time": rows[-1]["time"],
                    "quantity": "-1",
                    "reference_price": str(5000 + (len(rows) - 3) * number),
                },
            ],
        }
    return paths, definition


def test_b3_matrix_reuses_frozen_g0_and_g1_without_changing_parameters() -> None:
    frozen = r5_fixture()
    before = copy.deepcopy(frozen)
    result = contract.build_benchmark_contract(frozen)
    assert frozen == before
    assert len(result["arms"]) == 6 and result["future_matrix_slots"] == 90
    assert result["future_matrix_slots_authorized_now"] == 0
    assert result["controls"]["G1"]["resize"]["smoothing_half_life"] == 5 * 86400
    assert result["controls"]["G1"]["resize"]["review_interval"] == 48 * 3600
    assert result["controls"]["G1"]["resize"]["cost_benefit_lambda"] == "1"
    assert result["controls"]["G0"]["resize"] is None
    assert result["arms"]["G1"]["control_sha256"] == result["arms"]["G1_PASSIVE"]["control_sha256"]
    assert (
        result["arms"]["G1"]["configuration_sha256"]
        != result["arms"]["G1_PASSIVE"]["configuration_sha256"]
    )
    assert result["controls"]["FIXED_QTY"]["execution_adapter"].startswith("NOT_IMPLEMENTED")


def test_b3_cash_calendar_keeps_flat_periods_and_readiness_is_only_a_subset() -> None:
    paths, definition = paths_fixture()
    before = copy.deepcopy(paths)
    result = contract.validate_benchmark_paths(paths, definition, start=START, end=END)
    assert result["full_calendar_observations"] == 19
    assert result["common_ready"][:3] == [False, False, True]
    assert result["full_calendar"][0] == START and result["full_calendar"][-1] == END
    assert paths == before and result["engine_equivalence"] == "NOT_VERIFIED"
    assert all(row["equity"] == "50000" and row["cost"] == "0" for row in paths["CASH"]["rows"])


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_arm",
        "wrong_signal",
        "missing_flat_day",
        "mixed_fee",
        "mixed_risk",
        "shared_account",
        "shadow_account",
        "full_sample_vol",
        "cash_trade",
        "cash_cost",
        "cash_profit",
        "cash_readiness",
        "cash_flow",
        "bad_balance",
        "nonflat_end",
        "unknown_ready",
        "different_risk_ready",
        "naive_clock",
    ],
)
def test_b3_panel_rejects_noncomparable_or_incomplete_paths(mutation: str) -> None:
    paths, definition = paths_fixture()
    g1, cash = paths["G1"], paths["CASH"]
    if mutation == "missing_arm":
        del paths["SIMPLE_TREND"]
    elif mutation == "wrong_signal":
        g1["definition"]["signal"] = "ALWAYS_HOLD"
    elif mutation == "missing_flat_day":
        del g1["rows"][1]
    elif mutation == "mixed_fee":
        g1["common"]["cost_multiplier"] = "2"
    elif mutation == "mixed_risk":
        g1["common"]["risk_policy_sha256"] = "c" * 64
    elif mutation in {"shared_account", "shadow_account", "full_sample_vol"}:
        key, value = {
            "shared_account": ("capital_mode", "SHARED_PORTFOLIO"),
            "shadow_account": ("cost_mode", "SAME_FILL_SHADOW"),
            "full_sample_vol": ("risk_sizing_basis", "FULL_SAMPLE_REALIZED_VOLATILITY"),
        }[mutation]
        for path in paths.values():
            path["common"][key] = value
    elif mutation == "cash_trade":
        cash["orders"].append({"quantity": "1"})
    elif mutation == "cash_cost":
        cash["rows"][1]["cost"] = "1"
    elif mutation == "cash_profit":
        cash["rows"][1].update(equity="50001", cash="50001")
    elif mutation == "cash_readiness":
        cash["rows"][1]["risk_ready"] = False
    elif mutation == "cash_flow":
        g1["rows"][1]["cash_flow"] = "1"
    elif mutation == "bad_balance":
        g1["rows"][3]["cash"] = "0"
    elif mutation == "nonflat_end":
        g1["rows"][-1]["position_value"] = "1"
    elif mutation == "unknown_ready":
        g1["rows"][1]["risk_ready"] = None
    elif mutation == "different_risk_ready":
        g1["rows"][1]["risk_ready"] = True
    elif mutation == "naive_clock":
        g1["rows"][1]["time"] = g1["rows"][1]["time"].removesuffix("+00:00")
    with pytest.raises(ValueError):
        contract.validate_benchmark_paths(paths, definition, start=START, end=END)


def test_b3_same_configuration_compares_orders_fills_and_returns() -> None:
    paths, _ = paths_fixture()
    left, right = paths["G1"], copy.deepcopy(paths["G1"])
    right["run_id"] = "another-synthetic-run"
    contract.assert_same_configuration_paths(left, right)
    for field in ("rows", "orders", "fills"):
        altered = copy.deepcopy(right)
        altered[field][-1] = {"changed_economic_payload": True}
        with pytest.raises(ValueError, match="DIFFERENT-ECONOMIC-PATH"):
            contract.assert_same_configuration_paths(left, altered)
    with pytest.raises(ValueError, match="DIFFERENT-CONFIGURATION"):
        contract.assert_same_configuration_paths(paths["G1"], paths["G1_PASSIVE"])


def test_b3_shadow_reuses_full_fill_identity_and_never_claims_funding() -> None:
    fill = {
        "time": START,
        "quantity": "1",
        "side": "BUY",
        "reference_price": "100",
        "inventory": "1",
    }
    rows: list[dict[str, Any]] = [
        {
            "arm": "G1",
            "symbol": "TEST",
            "cost": cost,
            "total_cost": total,
            "final_equity": wealth,
            "fill_path": [dict(fill)],
        }
        for cost, total, wealth in (("1", "1", "109"), ("1.5", "1.5", "108.5"), ("2", "2", "108"))
    ]
    result = audit_cost_path(CostMode.SAME_FILL_SHADOW, rows)
    assert result["status"] == "VERIFIED" and not result["funding_feasibility_claimed"]
    broken = copy.deepcopy(rows)
    broken[-1]["fill_path"][0]["quantity"] = "2"
    with pytest.raises(ValueError, match="SHADOW-PATH-CHANGED"):
        audit_cost_path(CostMode.SAME_FILL_SHADOW, broken)
    assert not audit_cost_path(CostMode.REDECIDE_FUNDED, rows)["monotonic_wealth_required"]


def test_b3_legacy_bootstrap_is_bitwise_equal_to_frozen_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = ROOT / "artifacts/alpha_v5/20260908_research_churn_v3"
    manifest = json.loads((frozen / "audit_manifest.json").read_text(encoding="utf-8"))
    name = "src/aegisquant/research/validation/paired_bootstrap.py"
    source = frozen / "implementation" / name
    assert sha256_file(source) == manifest["source_hashes"][name]
    module = ModuleType("b3_frozen_bootstrap_synthetic_test_only")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(source.read_bytes(), str(source), "exec"), module.__dict__)  # noqa: S102 -- hash-verified repository code, synthetic arrays only.
    values = np.column_stack(
        (np.sin(np.arange(241)) / 1000, np.cos(np.arange(241)) / 1000, np.zeros(241))
    )
    old: Any = module.paired_block_bootstrap(values, repetitions=257, block_bars=11, seed=17)
    current = paired_block_bootstrap(values, repetitions=257, block_bars=11, seed=17)
    assert [field.name for field in fields(PairedBootstrap)] == [
        field.name for field in fields(old)
    ]
    for name in (
        "compound_returns",
        "mean_returns",
        "observed_compound_returns",
        "observed_mean_returns",
    ):
        assert np.array_equal(getattr(current, name), getattr(old, name)), name
    assert current.reality_check_p_value == old.reality_check_p_value
    assert current.difference(0, 1) == old.difference(0, 1)
    assert len(current.difference(0, 1)) == 4
    assert current.estimand_ids["ci95"] != current.estimand_ids["one_sided_mean_p_value"]


def test_b3_log_growth_ci_p_value_and_known_constant_increment() -> None:
    base = np.sin(np.arange(240)) / 1000
    values = np.expm1(np.column_stack((base, base, base + 0.002, np.zeros(240))))
    draw = paired_log_growth_bootstrap(values, repetitions=1000, block_bars=6, seed=23)
    same = draw.difference(1, 0)
    better = draw.difference(2, 0)
    assert (
        same["observed_mean_log_return_difference"] == same["ci95_lower"] == same["ci95_upper"] == 0
    )
    assert same["one_sided_p_value"] == 1
    assert better["estimand_id"] == LOG_GROWTH_ESTIMAND
    assert better["observed_mean_log_return_difference"] == pytest.approx(0.002)
    assert better["ci95_lower"] == pytest.approx(0.002) and better["ci95_upper"] == pytest.approx(
        0.002
    )
    assert better["one_sided_p_value"] == pytest.approx(1 / 1001)
    assert np.array_equal(draw.mean_log_returns[:, 0], draw.mean_log_returns[:, 1])
    assert np.all(draw.mean_log_returns[:, 3] == 0)


def test_b3_log_growth_handles_compound_underflow_and_column_permutation() -> None:
    values = np.column_stack((np.full(240, -0.9), np.zeros(240), np.sin(np.arange(240)) / 1000))
    draw = paired_log_growth_bootstrap(values, repetitions=257, block_bars=7, seed=11)
    reordered = paired_log_growth_bootstrap(
        values[:, [2, 0, 1]], repetitions=257, block_bars=7, seed=11
    )
    assert np.array_equal(draw.mean_log_returns, reordered.mean_log_returns[:, [1, 2, 0]])
    assert np.all(np.isfinite(draw.mean_log_returns))
    assert draw.difference(1, 0)["observed_mean_log_return_difference"] == pytest.approx(
        -np.log(0.1)
    )


@pytest.mark.parametrize(
    "bad", ["nan", "infinite", "bankrupt", "short", "no_columns", "few_repetitions"]
)
def test_b3_log_bootstrap_rejects_invalid_or_insufficient_observations(bad: str) -> None:
    values = np.zeros((240, 2))
    repetitions = 100
    if bad in {"nan", "infinite", "bankrupt"}:
        values[0, 0] = {"nan": np.nan, "infinite": np.inf, "bankrupt": -1}[bad]
    elif bad == "short":
        values = values[:3]
    elif bad == "no_columns":
        values = np.zeros((240, 0))
    else:
        repetitions = 99
    with pytest.raises(ValueError):
        paired_log_growth_bootstrap(values, repetitions=repetitions, block_bars=6, seed=1)


def test_b3_four_comparisons_remain_one_holm_family() -> None:
    p_values: dict[str, float] = dict(
        zip(contract.PRIMARY_COMPARISONS, [0.01, 0.02, 0.4, 0.8], strict=True)
    )
    adjusted = holm_adjust(p_values)
    assert len(adjusted) == 4
    assert adjusted["G1-CASH"] == pytest.approx(0.04)
    assert adjusted["G1-F5_MATCHED"] == pytest.approx(0.06)
    assert adjusted["G1-G1_PASSIVE"] == adjusted["G1-SIMPLE_TREND"] == pytest.approx(0.8)


def test_b3_factorial_effects_reconstruct_each_cell_and_survive_column_order() -> None:
    cells = list(contract.ARMS.values())
    control_effect = {"G0": -0.001, "G1": 0.002, "FIXED_QTY": -0.001}
    interaction = {"G0": -0.0002, "G1": 0.0001, "FIXED_QTY": 0.0001}
    base = 0.01 + np.sin(np.arange(48)) / 10000
    logs = np.column_stack(
        [
            base
            + control_effect[control]
            + (1 if signal == "TREND_10_40" else -1) * (0.003 + interaction[control])
            for signal, control in cells
        ]
    )
    simple_returns = np.expm1(logs)
    result = benchmark_factorial_attribution(simple_returns, cells)
    assert result["signal_main_effects"]["TREND_10_40"] == pytest.approx(0.003)
    assert result["control_main_effects"] == pytest.approx(control_effect)
    for row in result["cells"]:
        reconstructed = (
            result["grand_mean"]
            + result["signal_main_effects"][row["signal"]]
            + result["control_main_effects"][row["control"]]
            + row["interaction"]
        )
        assert reconstructed == pytest.approx(row["mean_log_return"], abs=1e-15)
    assert benchmark_factorial_attribution(simple_returns[:, ::-1], cells[::-1]) == result
    with pytest.raises(ValueError):
        benchmark_factorial_attribution(simple_returns[:, :-1], cells[:-1])
    with pytest.raises(ValueError):
        benchmark_factorial_attribution(simple_returns, [cells[0]] * 6)


def report_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    """Fake repository/receipts for CLI mechanics; never copied to a real generation."""
    root, stage = tmp_path / "synthetic-repo", tmp_path / "synthetic-stage"
    root.mkdir()
    stage.mkdir()
    config = yaml.safe_load(
        (ROOT / "configs/research/alpha_v5_benchmark_contract.yaml").read_text(encoding="utf-8")
    )

    def save(name: str, data: str | bytes) -> Path:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        return path

    for name in contract.B3_FILES:
        save(name, "SYNTHETIC TASK FILE ONLY\n")
    stats, settings = statistics_fixture()
    # Exercise preservation of actual JSON numeric tokens as well as Decimal strings.
    stats["comparisons"]["G1-G0"]["one_sided_mean_p_value"] = 0.123
    r5 = r5_fixture()
    r5["config"]["statistics"] = settings
    source_data = {
        "r5_manifest": r5,
        "r5_statistics": stats,
        "b0_manifest": {"SYNTHETIC_ONLY": True},
        "b0_cost_audit": {"status": "SYNTHETIC_REFERENCE_ONLY"},
        "b2_manifest": {"SYNTHETIC_ONLY": True},
        "b2_safety": {"strict_data_quality": "FAILED_CLOSED_INSUFFICIENT_PIT_EVIDENCE"},
    }
    for name, binding in config["sources"].items():
        binding["sha256"] = sha256_file(save(binding["path"], json.dumps(source_data[name])))
    save("configs/research/aegis_alpha_v5.yaml", yaml.safe_dump(r5["config"]))
    save(
        "src/aegisquant/bootstrap/live_lock.py",
        "LIVE_TRADING: bool = False\nORDER_SUBMISSION_ENABLED: bool = False\nLIVE_ADAPTERS: tuple = ()\n",
    )
    save("configs/research/alpha_v5_benchmark_contract.yaml", yaml.safe_dump(config))
    baseline = {
        "root": str(root),
        "head": contract.BASE,
        "branch": "main",
        "allowed_modifications": list(contract.MODIFIED_FILES),
        "files": {
            path.relative_to(root).as_posix(): {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in root.rglob("*")
            if path.is_file()
        },
    }
    (stage / "baseline_workspace.json").write_text(json.dumps(baseline), encoding="utf-8")
    for name in contract.MODIFIED_FILES:
        target = stage / "before" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / name).read_bytes())
    for name in ("workspace_before.patch", "version_graph.txt", "test_commands_and_results.txt"):
        (stage / name).write_text("SYNTHETIC RECEIPT ONLY\n", encoding="utf-8")
    hashes = {name: sha256_file(root / name) for name in contract.B3_FILES}
    records = [
        {
            "check": check,
            "exit_code": 0,
            "command": ["SYNTHETIC_FIXTURE_ONLY", contract.NEW_FILES[3]],
            "source_sha256": hashes,
        }
        for check in ("ruff", "format", "pyright", "pytest")
    ]
    (stage / "validation_records.json").write_text(json.dumps(records), encoding="utf-8")
    (stage / "pytest_results.xml").write_text(
        '<testsuite name="SYNTHETIC_RECEIPT_ONLY"><testcase name="synthetic_contract_fixture"/></testsuite>',
        encoding="utf-8",
    )
    return root, stage, config


def test_b3_cli_seals_read_only_report_without_replay_or_resampling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aegisquant.research.validation import paired_bootstrap as statistics
    from scripts import audit_alpha_profitability_root_causes as old_report
    from scripts import run_alpha_v5_benchmark_diagnostics as entry
    from scripts import run_alpha_v5_research as old_runner

    root, stage, config = report_fixture(tmp_path)
    poison = Mock(
        side_effect=AssertionError("B3 contract job attempted market/replay/old inference")
    )
    for name in ("run", "run_one", "inputs", "replay_cat", "load_completed_bars", "preregister"):
        monkeypatch.setattr(old_runner, name, poison)
    for name in ("report", "collect", "paired_statistics"):
        monkeypatch.setattr(old_report, name, poison)
    monkeypatch.setattr(statistics, "paired_block_bootstrap", poison)
    monkeypatch.setattr(statistics, "paired_log_growth_bootstrap", poison)
    monkeypatch.setattr(entry, "ROOT", root)

    def synthetic_git(_root: Path, *args: str) -> str:
        return "main" if args[0] == "branch" else contract.BASE

    monkeypatch.setattr(entry, "git", synthetic_git)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "b3",
            "--config",
            "configs/research/alpha_v5_benchmark_contract.yaml",
            "--preflight-dir",
            str(stage),
        ],
    )
    entry.main()
    output = root / config["output"]
    assert load_evidence_manifest(output, "OUTPUT_MANIFEST.json")["status"] == "VERIFIED"
    assert (output / "legacy_paired_statistics_original.json").read_bytes() == (
        root / config["sources"]["r5_statistics"]["path"]
    ).read_bytes()
    primary = json.loads((output / "primary_comparisons.json").read_text())
    assert primary["status"] == "NOT_COLLECTED" and len(primary["comparisons"]) == 4
    assert all(row["one_sided_p_value"] is None for row in primary["comparisons"].values())
    budget = json.loads((output / "safety_and_budget_audit.json").read_text())["actual"]
    assert budget.pop("contract_jobs") == 1 and not any(budget.values())
    assert not poison.called
    with pytest.raises(FileExistsError):
        contract.run_contract_job(root, config, stage, {"head": contract.BASE, "branch": "main"})


@pytest.mark.parametrize(
    "mutation",
    [
        "replay",
        "fit",
        "historical_inference",
        "live",
        "wrong_comparisons",
        "seed",
        "historical_input",
    ],
)
def test_b3_scope_cannot_be_expanded_by_configuration(mutation: str) -> None:
    config = yaml.safe_load(
        (ROOT / "configs/research/alpha_v5_benchmark_contract.yaml").read_text(encoding="utf-8")
    )
    if mutation in {"replay", "fit", "historical_inference"}:
        key = {
            "replay": "historical_strategy_engine_runs",
            "fit": "real_return_model_fits",
            "historical_inference": "historical_bootstrap_runs",
        }[mutation]
        config["budgets"][key] = 1
    elif mutation == "live":
        config["live_trading"] = True
    elif mutation == "wrong_comparisons":
        config["statistics"]["comparisons"] = ["G1-F0"]
    elif mutation == "seed":
        config["statistics"]["seed"] = 999
    else:
        config["historical_matrix_inputs"] = "data/not_authorized.json"
    with pytest.raises(ValueError):
        contract.validate_config(config)


def test_b3_failure_is_retained_with_manifest_and_consumed_slot(tmp_path: Path) -> None:
    root, stage, config = report_fixture(tmp_path)
    config["sources"]["r5_statistics"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="FROZEN-SOURCE"):
        contract.run_contract_job(root, config, stage, {"head": contract.BASE, "branch": "main"})
    output = root / config["output"]
    assert load_evidence_manifest(output, "OUTPUT_MANIFEST.json")["status"] == "VERIFIED"
    assert json.loads((output / "failure.json").read_text())["actual"]["contract_jobs"] == 1
    events = [
        json.loads(line)["event"]["event_type"]
        for line in (output / "experiment_events.jsonl").read_text().splitlines()
    ]
    assert events == ["STARTED", "ERROR"]
    with pytest.raises(FileExistsError):
        contract.run_contract_job(root, config, stage, {"head": contract.BASE, "branch": "main"})


def test_b3_calendar_rejects_non_four_hour_end_boundary() -> None:
    invalid = (contract.utc(END) + timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match="CALENDAR-GRID"):
        contract.cash_reference(start=START, end=invalid, capital=Decimal("50000"))
