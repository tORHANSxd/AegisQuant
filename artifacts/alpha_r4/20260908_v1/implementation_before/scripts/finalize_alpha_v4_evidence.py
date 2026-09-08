"""Derive final audit evidence from saved results; never fit models or read market/holdout data."""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET  # nosec B405 - locally generated pytest XML only.
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, cast

import polars as pl


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build(root: Path) -> None:
    directory = root / "artifacts/alpha_v4"
    correctness = directory / "correctness"
    reports = directory / "reports"
    manifest = read_json(directory / "walkforward/run_manifest.json")
    bootstrap = read_json(directory / "walkforward/bootstrap_results.json")
    statistics = read_json(directory / "walkforward/dsr_pbo.json")
    policy = manifest["research_config"]["promotion"]
    holdout = read_json(directory / "holdout/final_results.json")
    aggregates = pl.read_parquet(directory / "walkforward/ablation_results.parquet").to_dicts()
    stresses = pl.read_parquet(directory / "walkforward/aggregate_stress.parquet").to_dicts()
    folds = pl.read_parquet(directory / "walkforward/fold_stability.parquet")
    waterfall = pl.read_parquet(directory / "walkforward/cost_waterfall.parquet")
    trials = pl.read_parquet(directory / "walkforward/all_trials.parquet")
    xml_path = correctness / "final_pytest.xml"
    # This file is produced by the local pytest command, not imported external XML.
    suite = ET.parse(xml_path).getroot().find("testsuite")  # noqa: S314 # nosec B314
    if suite is None or any(int(suite.attrib[k]) for k in ("failures", "errors", "skipped")):
        raise ValueError("final local test run must have no failures, errors or skips")
    test_section = (root / "AegisQuant_盈利导向重构任务书_v4.md").read_text(encoding="utf-8")
    test_section = test_section.split("## 11.", 1)[1].split("## 12.", 1)[0]
    required = [line for line in test_section.splitlines() if line.startswith("tests/")]
    exercised = {case.attrib["classname"] for case in suite.findall("testcase")}
    coverage = {
        name: (root / name).is_file() and name[:-3].replace("/", ".") in exercised
        for name in required
    }
    if not all(coverage.values()):
        raise ValueError(f"required test module not exercised: {coverage}")
    properties = {
        "higher_costs_cannot_improve_pnl_on_same_fills": (
            "tests/property/test_backtest_economics.py::"
            "test_higher_fees_and_slippage_cannot_improve_net_pnl_on_the_same_fills"
        ),
        "higher_slippage_cannot_improve_pnl_on_same_fills": (
            "tests/property/test_backtest_economics.py::"
            "test_higher_fees_and_slippage_cannot_improve_net_pnl_on_the_same_fills"
        ),
        "fixed_frequency_metrics_ignore_fill_fragmentation": (
            "tests/unit/backtest/test_fill_fragmentation_metric_invariance.py::"
            "test_same_timestamp_split_orders_do_not_change_fixed_frequency_risk_metrics"
        ),
        "target_position_idempotency_including_pending": (
            "tests/unit/portfolio/test_target_position_idempotency.py::"
            "test_repeating_filled_or_pending_target_does_not_place_another_order"
        ),
        "reduce_only_never_expands_absolute_position": (
            "tests/property/test_backtest_economics.py::"
            "test_reduce_only_never_increases_or_reverses_absolute_position"
        ),
        "available_time_never_exposes_future_facts": (
            "tests/property/test_data_properties.py::"
            "test_pit_property_never_exposes_future_available_fact"
        ),
    }
    test_summary = {
        key: suite.attrib[key] for key in ("tests", "failures", "errors", "skipped", "time")
    }
    write_json(
        correctness / "backtest_invariants.json",
        {
            "schema_version": "alpha-v4-final-invariants-v1",
            "decision": "ENGINEERING_CHECKS_PASSED_NOT_ALPHA_ADMISSION",
            "validated_implementation_commit": "bb3c37f6d6be374b51ea9ea0814c758797a9b44b",
            "pytest_command": ".venv/Scripts/python.exe -m pytest -q --junitxml=artifacts/alpha_v4/correctness/final_pytest.xml",
            "pytest": test_summary,
            "pytest_xml_sha256": digest(xml_path),
            "required_test_modules": coverage,
            "required_test_module_count": len(required),
            "six_required_properties": properties,
            "validation_output": "final_validation_output.txt",
            "limitations": [
                "Synthetic economics and recovery tests do not establish historical venue rules or liquidity.",
                "Some stressed frozen orders have different fills due to cash constraints; see cost_identity.json.",
                "Historical P07 label-evidence hashes predate corrected label semantics and are preserved, not re-certified.",
            ],
            "live_trading": False,
            "order_submission_enabled": False,
            "production_ml_enabled": False,
        },
    )
    same_signal = pl.read_parquet(directory / "diagnostics/failure_attribution.parquet").filter(
        pl.col("experiment").is_in(["A0", "A1", "A2"])
    )
    same_signal.write_parquet(correctness / "before_after_same_signal.parquet")
    fields = (
        "trading_fees",
        "spread_cost",
        "slippage_cost",
        "impact_cost",
        "funding",
        "borrow_interest",
        "settlement_fees",
        "liquidation_penalties",
    )
    totals: dict[str, dict[str, str]] = {}
    maximum_recomputed = Decimal(0)
    with localcontext() as context:
        context.prec = 100
        for level in waterfall["level"].unique(maintain_order=True):
            rows = waterfall.filter(pl.col("level") == level).to_dicts()
            totals[level] = {
                field: str(sum((Decimal(row[field]) for row in rows), Decimal(0)))
                for field in ("gross_trading_pnl", *fields, "net_pnl")
            }
            for row in rows:
                residual = Decimal(row["net_pnl"]) - (
                    Decimal(row["gross_trading_pnl"])
                    - sum((Decimal(row[field]) for field in fields), Decimal(0))
                )
                maximum_recomputed = max(maximum_recomputed, abs(residual))
    maximum_reported = max(abs(Decimal(v)) for v in folds["cost_identity_residual"])
    if max(maximum_recomputed, maximum_reported) >= Decimal("1E-8"):
        raise ValueError("cost attribution does not close at the absolute USDT tolerance")
    changed = folds.filter(pl.col("same_fill_topology") == False)  # noqa: E712
    write_json(
        correctness / "cost_identity.json",
        {
            "formula": "net = gross - fees - spread - slippage - impact - signed_funding - borrow - settlement - liquidation",
            "tolerance_absolute_USDT": "1E-8",
            "base_fold_runs": waterfall.height,
            "all_fold_scenario_runs": folds.height,
            "maximum_independently_recomputed_base_residual": str(maximum_recomputed),
            "maximum_reported_all_scenario_residual": str(maximum_reported),
            "passed": True,
            "totals_units": "USDT sums of fourteen independent 10000-USDT fold accounts; not compounded portfolio dollars",
            "totals": totals,
            "forced_close_statuses": folds["forced_close_status"].value_counts().to_dicts(),
            "stressed_order_fill_path_change_count": changed.height,
            "stressed_order_fill_path_changes": changed.select(
                "fold_id", "level", "scenario", "rejections", "fills"
            ).to_dicts(),
            "stress_interpretation": "Order timestamps/quantities are frozen; 16 fold-scenarios change actual fills. These are funded-order stress results, not pure same-fill cost attribution.",
        },
    )
    stress_map = {(row["level"], row["scenario"]): row for row in stresses}
    random_map = {row["level"]: row for row in bootstrap["matched_random"]}
    ml_baselines = {
        "B5": "B4",
        "B6": "B5",
        "B7": "B6",
        "LIGHTGBM": "B4",
        "ELASTIC_NET": "B4",
    }
    criteria = (
        ("net_compound_return", "minimum_oos_net_return", True),
        ("sharpe", "minimum_net_sharpe", True),
        ("calmar", "minimum_calmar", True),
        ("positive_fold_ratio", "minimum_positive_fold_ratio", True),
        ("median_fold_return", "minimum_median_fold_return", True),
        ("closed_trade_count", "minimum_closed_trades", True),
        ("maximum_drawdown", "maximum_drawdown", False),
        ("cost_to_gross_profit", "maximum_cost_to_gross_profit", False),
        ("maximum_positive_fold_share", "maximum_single_fold_profit_share", False),
        ("maximum_positive_year_share", "maximum_single_year_profit_share", False),
    )
    admissions: list[dict[str, Any]] = []
    for row in aggregates:
        level = row["level"]
        checks: dict[str, bool] = {}
        for field, threshold, lower_bound in criteria:
            value = row[field]
            checks[threshold] = value is not None and (
                value >= policy[threshold] if lower_bound else value <= policy[threshold]
            )
        # Positive returns/median must be strictly positive, including for cash.
        for field in ("net_compound_return", "median_fold_return"):
            checks[f"strictly_positive_{field}"] = row[field] > 0
        checks["net_positive_at_1_5_cost"] = (
            stress_map[(level, "cost_1.5")]["net_compound_return"] > 0
        )
        checks["survives_2_cost_without_destructive_loss"] = (
            stress_map[(level, "cost_2")]["net_compound_return"]
            > policy["destructive_loss_at_2_cost"]
        )
        dsr = statistics["dsr"][level].get("probability")
        checks["dsr"] = (
            dsr is not None and float(dsr) >= policy["minimum_deflated_sharpe_probability"]
        )
        checks["pbo"] = float(statistics["pbo"]["probability"]) <= policy["maximum_pbo"]
        p_value = random_map.get(level, {}).get("p_value")
        checks["matched_random_screen"] = (
            p_value is not None and p_value <= policy["maximum_matched_random_p_value"]
        )
        checks["matched_random_full_execution_evidence"] = False
        checks["historical_fee_rules_and_orderbook_evidence"] = False
        checks["unused_final_holdout_passed"] = bool(holdout["passed"])
        checks["cost_identity"] = bool(row["all_cost_identities_passed"])
        if level in ml_baselines:
            comparison = f"{level}_minus_{ml_baselines[level]}"
            incremental = bootstrap["incremental_comparisons"][comparison]
            checks["ml_positive_increment_lower_confidence_bound"] = incremental["ci95_lower"] > 0
            checks["ml_increment_survives_multiple_testing"] = (
                bootstrap["holm_adjusted_p_values"][comparison] <= 0.05
            )
            checks["ml_increment_wins_at_least_sixty_percent_of_folds"] = (
                incremental["fold_wins"] / manifest["folds"] >= 0.6
            )
        admissions.append(
            {
                "level": level,
                "admitted": all(checks.values()),
                "checks": checks,
                "failed_gates": [name for name, passed in checks.items() if not passed],
            }
        )
    if any(row["admitted"] for row in admissions):
        raise ValueError("unexpected admission requires review of the report derivation")
    write_json(
        reports / "promotion_decisions.json",
        {
            "decision": "NO_PROVEN_ALPHA",
            "selected_model_id": None,
            "production_policy": "CASH",
            "paper_trading_admitted": False,
            "production_ml_enabled": False,
            "live_trading": False,
            "order_submission_enabled": False,
            "final_holdout_access_count": 0,
            "candidates": admissions,
            "trials_by_kind_and_status": trials.group_by("kind", "status")
            .len()
            .sort("kind", "status")
            .to_dicts(),
        },
    )
    input_paths = [
        directory / "diagnostics/failure_attribution.parquet",
        xml_path,
        directory / "holdout/final_results.json",
        directory / "funding_basis/admission_report.json",
        directory / "walkforward/run_manifest.json",
        *[directory / "walkforward" / name for name in manifest["files_sha256"]],
    ]
    output_paths = [
        correctness / "backtest_invariants.json",
        correctness / "cost_identity.json",
        correctness / "before_after_same_signal.parquet",
        correctness / "final_validation_output.txt",
        *sorted(reports.glob("*.md")),
        reports / "promotion_decisions.json",
    ]
    if len(list(reports.glob("*.md"))) != 5:
        raise ValueError("exactly five required final reports must exist before sealing")
    write_json(
        reports / "reporting_manifest.json",
        {
            "version": "alpha-v4-final-reporting-v1",
            "method": "Read saved results and test evidence only; no raw-market load, model fit, holdout access or strategy selection.",
            "walkforward_execution_source_snapshot_commit": "7ebec24",
            "validated_implementation_commit": "bb3c37f6d6be374b51ea9ea0814c758797a9b44b",
            "reporting_script_sha256": digest(Path(__file__).resolve()),
            "input_sha256": {
                str(p.relative_to(root)).replace("\\", "/"): digest(p) for p in input_paths
            },
            "output_sha256": {
                str(p.relative_to(root)).replace("\\", "/"): digest(p) for p in output_paths
            },
            "metadata_correction": manifest["metadata_correction"],
        },
    )
    print(
        f"sealed five NO_PROVEN_ALPHA reports, {len(required)} required test modules, {folds.height} cost identities"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.check:
        manifest = read_json(root / "artifacts/alpha_v4/reports/reporting_manifest.json")
        for group in ("input_sha256", "output_sha256"):
            for name, expected in manifest[group].items():
                path = (root / name).resolve()
                if not path.is_relative_to(root) or digest(path) != expected:
                    raise ValueError(f"report evidence hash mismatch: {name}")
        if digest(Path(__file__).resolve()) != manifest["reporting_script_sha256"]:
            raise ValueError("reporting source has changed")
        print("final report evidence verified; no evaluation or holdout access")
    else:
        build(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
