"""Evidence mutations and an end-to-end CLI fixture containing ONLY synthetic saved tables."""

import copy
import gzip
import json
import socket
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import polars as pl
import pytest
import yaml

from aegisquant.data.hashing import canonical_sha256, sha256_file
from aegisquant.research.experiments.journal import (
    ExperimentEvent,
    ExperimentEventJournal,
    ExperimentEventType,
)
from aegisquant.research.validation import evidence_contract as audit
from aegisquant.research.validation.evidence_contract import (
    COMPARISONS,
    CostMode,
    VersionBinding,
    audit_cost_path,
    audit_equity,
    audit_fills,
    checked_path,
    claim_output,
    decimal,
    load_evidence_manifest,
    quarter_returns,
    resolve_required_evidence,
    statistics_identity,
    validate_version_binding,
    verify_full_bundle,
)
from aegisquant.research.validation.experiment_registry import registered_run
from scripts import audit_alpha_v5_evidence as cli

D = Decimal
T = datetime(2020, 3, 31, tzinfo=UTC)


def equity_fixture() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for arm in ("F0", "G1"):
        for day, equity, inventory in ((0, "50000", "0"), (1, "50500", "1000"), (2, "50400", "0")):
            rows.append(
                {
                    "arm": arm,
                    "cost": "1",
                    "time": T + timedelta(days=day),
                    "equity": equity,
                    "cash": str(D(equity) - D(inventory)),
                    "position_value": inventory,
                    "mode": "REDECIDE_FUNDED",
                    "capital_mode": "FIVE_EQUAL_INITIAL_SLEEVES_NO_TRANSFERS",
                    "external_flow": "0",
                    "cumulative_net_pnl": str(D(equity) - D(50000)),
                }
            )
    summaries = [
        {
            "arm": arm,
            "cost": "1",
            "initial_equity": "50000",
            "final_equity": "50400",
            "net_compound_return": ".008",
            "quarter_count": 2,
        }
        for arm in ("F0", "G1")
    ]
    return rows, summaries


def equity_audit(
    rows: list[dict[str, Any]], summaries: list[dict[str, Any]], **extra: Any
) -> list[dict[str, Any]]:
    return audit_equity(
        rows,
        summaries,
        start=T.isoformat(),
        end=(T + timedelta(days=2)).isoformat(),
        initial_cash=D(50000),
        **extra,
    )


def test_common_calendar_capital_quarters_and_flat_days() -> None:
    rows, summaries = equity_fixture()
    result = equity_audit(rows, summaries)
    assert [r["points"] for r in result] == [3, 3]
    assert all(r["external_capital_and_pnl"] == "VERIFIED" for r in result)
    quarters = [
        {"arm": arm, "cost": "1", **q}
        for arm in ("F0", "G1")
        for q in quarter_returns([r for r in rows if r["arm"] == arm])
    ]
    assert quarters[0]["quarter"] == "2020Q1" and quarters[0]["return"] == D(".01")
    assert equity_audit(rows, summaries, quarters=quarters)
    quarters[0]["return"] = decimal(quarters[0]["return"]) + D(".001")
    with pytest.raises(ValueError, match="QUARTER-ROW-MISMATCH"):
        equity_audit(rows, summaries, quarters=quarters)


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("duplicate", "DUPLICATE-TIME"),
        ("nonutc", "NON-UTC"),
        ("gap", "CALENDAR-GAP"),
        ("mixed_mode", "MIXED-CAPITAL-MODE"),
        ("principal", "EXTRA-PRINCIPAL"),
        ("balance", "CASH-INVENTORY-IDENTITY"),
        ("pnl", "CAPITAL-PNL-IDENTITY"),
        ("terminal", "TERMINAL-MISMATCH"),
        ("initial", "INITIAL-CAPITAL"),
    ],
)
def test_equity_mutations_fail(mutation: str, match: str) -> None:
    rows, summaries = equity_fixture()
    if mutation == "duplicate":
        rows[1]["time"] = rows[0]["time"]
    elif mutation == "nonutc":
        rows[1]["time"] = "2020-04-01T01:00:00+01:00"
    elif mutation == "gap":
        del rows[1]
    elif mutation == "mixed_mode":
        rows[1]["mode"] = "SAME_FILL_SHADOW"
    elif mutation == "principal":
        rows[1]["external_flow"] = "100"
    elif mutation == "balance":
        rows[1]["cash"] = "49499"
    elif mutation == "pnl":
        rows[1]["cumulative_net_pnl"] = "501"
    elif mutation == "terminal":
        summaries[0]["final_equity"] = "50401"
    else:
        summaries[0]["initial_equity"] = "50001"
    with pytest.raises(ValueError, match=match):
        equity_audit(rows, summaries)


def test_balance_identity_does_not_prove_absence_of_unobserved_cash_flows() -> None:
    rows, summaries = equity_fixture()
    for r in rows:
        del r["external_flow"]
        del r["cumulative_net_pnl"]
    assert all(
        r["external_capital_and_pnl"] == "NOT_VERIFIED" for r in equity_audit(rows, summaries)
    )
    with pytest.raises(TypeError):
        decimal(50000.1)
    for value in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValueError):
            decimal(value)


def test_r4_r5_version_strategy_hash_and_period_cannot_be_swapped() -> None:
    r5 = VersionBinding(
        audit.BASE,
        "a" * 64,
        "r5",
        "G1",
        "2022-04-01T00:00:00Z",
        "2025-10-01T00:00:00Z",
        "DEVELOPMENT",
    )
    validate_version_binding(r5, r5)
    for mutated in (
        replace(r5, strategy="F3"),
        replace(r5, source_manifest_sha256="b" * 64),
        replace(r5, generation="recent-r4"),
        replace(r5, end_exclusive="2026-09-08T12:00:00Z"),
    ):
        with pytest.raises(ValueError, match="VERSION-STRATEGY-PERIOD-CONFLICT"):
            validate_version_binding(mutated, r5)
    assert resolve_required_evidence(collected=False, received=False) == "NOT_COLLECTED"
    assert resolve_required_evidence(collected=True, received=False) == "NOT_RECEIVED"
    with pytest.raises(ValueError):
        resolve_required_evidence(collected=False, received=True)


def cost_rows() -> list[dict[str, Any]]:
    path = [
        {
            "time": "2020-01-01T00:00:00Z",
            "quantity": "1",
            "side": "BUY",
            "reference_price": "100",
            "inventory": "1",
        }
    ]
    return [
        {"cost": "1", "total_cost": "1", "final_equity": "109", "fill_path": path},
        {"cost": "2", "total_cost": "2", "final_equity": "108", "fill_path": copy.deepcopy(path)},
    ]


def test_shadow_cost_identity_and_funded_nonmonotonic_paths() -> None:
    rows = cost_rows()
    assert audit_cost_path(CostMode.SAME_FILL_SHADOW, rows)["fill_path_identity"] == "VERIFIED"
    rows[1]["final_equity"] = "115"
    with pytest.raises(ValueError, match="ADVERSE-COST-IMPROVES-PNL"):
        audit_cost_path(CostMode.SAME_FILL_SHADOW, rows)
    for mode in (CostMode.REDECIDE_FUNDED, CostMode.FROZEN_ORDERS_FUNDED):
        assert audit_cost_path(mode, rows)["monotonic_wealth_required"] is False


def test_shadow_missing_path_is_not_verified_and_identity_mix_is_rejected() -> None:
    rows = cost_rows()
    for r in rows:
        del r["fill_path"]
    result = audit_cost_path(CostMode.SAME_FILL_SHADOW, rows, require_fill_identity=False)
    assert result["status"] == "NOT_VERIFIED"
    assert result["saved_table_arithmetic_status"] == "DERIVED_ONLY"
    with pytest.raises(ValueError, match="FILL-PATH-MISSING"):
        audit_cost_path(CostMode.SAME_FILL_SHADOW, rows)
    rows[0].update(arm="G1", symbol="BTCUSDT")
    rows[1].update(arm="G1", symbol="ETHUSDT")
    with pytest.raises(ValueError, match="IDENTITY-CONFLICT"):
        audit_cost_path(CostMode.SAME_FILL_SHADOW, rows, require_fill_identity=False)


@pytest.mark.parametrize(
    "field,value",
    [
        ("time", "2020-01-02T00:00:00Z"),
        ("quantity", "2"),
        ("side", "SELL"),
        ("reference_price", "101"),
        ("inventory", "2"),
    ],
)
def test_same_fill_requires_identical_execution_and_inventory(field: str, value: str) -> None:
    rows = cost_rows()
    rows[1]["fill_path"][0][field] = value
    with pytest.raises(ValueError, match="SHADOW-PATH-CHANGED"):
        audit_cost_path(CostMode.SAME_FILL_SHADOW, rows)


def test_missing_full_bundle_and_manifest_corruption_are_different(tmp_path: Path) -> None:
    assert (
        verify_full_bundle(tmp_path / "absent.zip", "a" * 64)["full_raw_bundle_received"] is False
    )
    bundle = tmp_path / "present.zip"
    bundle.write_bytes(b"synthetic")
    with pytest.raises(ValueError, match="FULL-BUNDLE-HASH-CONFLICT"):
        verify_full_bundle(bundle, "a" * 64)
    assert verify_full_bundle(bundle, sha256_file(bundle))["status"] == "HASH_ONLY"
    assert load_evidence_manifest(tmp_path)["status"] == "NOT_RECEIVED"
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps({"files": {"present.zip": sha256_file(bundle)}})
    )
    assert load_evidence_manifest(tmp_path)["listed_files_verified"] == 1
    bundle.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="MANIFEST-HASH-CONFLICT"):
        load_evidence_manifest(tmp_path)


def statistics_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    stats = {
        "block_days": 52,
        "comparisons": {
            name: {
                "observed_compound_return_difference": ".1",
                "ci95_lower": "-.2",
                "ci95_upper": ".3",
                "one_sided_mean_p_value": ".1234567890123456789",
                "holm_adjusted_p_value": ".9",
                "terminal_wealth_difference_usdt": "120",
            }
            for name in COMPARISONS
        },
        "dsr": None,
        "pbo": None,
        "dsr_pbo_status": "INSUFFICIENT_COMPLETE_HISTORICAL_INDEPENDENT_TRIAL_HISTORY",
    }
    settings = {"comparisons": list(COMPARISONS), "seed": 20260908, "repetitions": 10000}
    return stats, settings


def test_all_old_statistics_are_preserved_with_distinct_estimands() -> None:
    original, settings = statistics_fixture()
    before = copy.deepcopy(original)
    result = statistics_identity(original, settings)
    assert result["original_statistics"] == before == original
    assert result["family_size"] == 9 and result["independent_trial_count"] is None
    assert result["new_resamples"] == 0 and result["dsr"] is result["pbo"] is None
    assert result["comparisons"]["G1-G0"]["p_value_estimand"] == "DAILY_MEAN_RETURN_DIFFERENCE"
    assert (
        result["comparisons"]["G1-G0"]["secondary_interval_estimand"]
        == "COMPOUNDED_RETURN_DIFFERENCE"
    )
    del original["comparisons"]["G1_H3-G0"]
    with pytest.raises(ValueError, match="FAMILY-CHANGED"):
        statistics_identity(original, settings)


def test_output_reuse_protected_paths_parent_links_and_failure_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = tmp_path / "artifacts/alpha_v5/frozen"
    frozen.mkdir(parents=True)
    with pytest.raises(PermissionError, match="FROZEN-OUTPUT"):
        claim_output(tmp_path, "artifacts/alpha_v5/frozen/new", frozen_roots=[frozen])
    for name in ("artifacts/alpha_v5/holdout/new", "../outside", "artifacts/alpha_v5/a:stream"):
        with pytest.raises((PermissionError, ValueError)):
            claim_output(tmp_path, name)
    linked = tmp_path / "alias"
    original = Path.is_symlink

    def synthetic_link(p: Path) -> bool:
        return p == linked or original(p)

    monkeypatch.setattr(Path, "is_symlink", synthetic_link)
    with pytest.raises(PermissionError, match="LINK-FORBIDDEN"):
        checked_path(tmp_path, "alias/file")
    output = claim_output(tmp_path, "artifacts/alpha_v5/new")
    with pytest.raises(FileExistsError):
        claim_output(tmp_path, "artifacts/alpha_v5/new")
    with pytest.raises(ValueError, match="synthetic failure"):  # noqa: SIM117
        with registered_run(
            output, "report", planned_run_ids=["report"], bindings={"kind": "SYNTHETIC"}
        ):
            raise ValueError("synthetic failure")
    assert (
        ExperimentEventJournal(output / "experiment_events.jsonl").entries()[-1].event.event_type
        == ExperimentEventType.ERROR
    )
    with (
        pytest.raises(FileExistsError),
        registered_run(output, "report", planned_run_ids=["report"], bindings={}),
    ):
        pytest.fail("consumed report slot reopened")


def test_budget_guard_blocks_spies_network_and_protected_opens(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    calls = Mock()

    def replay_cat() -> None:
        calls()

    def fit() -> None:
        calls()

    def calibrate() -> None:
        calls()

    def submit_orders() -> None:
        calls()

    for action in (
        replay_cat,
        fit,
        calibrate,
        submit_orders,
        lambda: socket.create_connection(("127.0.0.1", 1)),
        lambda: (tmp_path / "holdout" / "data.csv").open("rb"),
        lambda: (tmp_path / "input.json").open("w"),
    ):
        counters: dict[str, int] = dict.fromkeys(audit.ZERO_BUDGETS, 0)
        with pytest.raises(PermissionError), audit.zero_budget_guard(output, tmp_path, counters):
            action()
    calls.assert_not_called()


def synthetic_project(tmp_path: Path, project_root: Path) -> tuple[Path, dict[str, Any], Path]:
    """No original prices, ledgers or result files are read to build this fixture."""
    root, stage = tmp_path / "synthetic_repo", tmp_path / "preflight"
    root.mkdir()
    stage.mkdir()

    def write(name: str, value: object) -> Path:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, default=str), encoding="utf-8")
        return p

    def parquet(name: str, rows: list[dict[str, Any]]) -> None:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(rows).write_parquet(p)

    config = yaml.safe_load(
        (project_root / "configs/research/alpha_v5_review_contract.yaml").read_text(
            encoding="utf-8"
        )
    )
    config["period_binding"]["r5_long"].update(
        start="2020-01-01T00:00:00Z",
        end_exclusive="2020-01-03T00:00:00Z",
        terminal_account_boundary="2020-01-03T00:00:00Z",
    )
    config["period_binding"]["recent_r4"].update(
        start="2020-01-01T00:00:00Z", end_exclusive="2020-01-03T12:00:00Z"
    )
    for name in audit.NEW_FILES:
        write(name, "synthetic task file")
    src = config["source"]
    r5, r4, recent = (src[k] for k in ("r5", "r4", "recent"))
    name = "src/aegisquant/research/strategies/buffered_target.py"
    source_text = (project_root / name).read_text(encoding="utf-8")
    for target in (root / name, root / r5 / "implementation" / name):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source_text, encoding="utf-8")
    stats, settings = statistics_fixture()
    source_config = {
        "generation": src["r5_generation"],
        "primary_candidate": "G1",
        "statistics": settings,
        "development": {
            "test_start": "2020-01-01T00:00:00Z",
            "end_exclusive": "2020-01-03T00:00:00Z",
        },
        "production_policy": "CASH",
        **dict.fromkeys(audit.LOCKS, False),
    }
    p = root / "configs/research/aegis_alpha_v5.yaml"
    p.write_text(yaml.safe_dump(source_config), encoding="utf-8")
    p = root / "src/aegisquant/bootstrap/live_lock.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "LIVE_TRADING: bool = False\nORDER_SUBMISSION_ENABLED: bool = False\nLIVE_ADAPTERS: tuple = ()\n"
    )
    start = datetime(2020, 1, 1, tzinfo=UTC)
    portfolio: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for arm, step in (("F0", 10), ("G1", 20)):
        portfolio += [
            {
                "arm": arm,
                "cost": "1",
                "time": start + timedelta(hours=i * 4),
                "equity": float(50000 + step * i),
                "cash": float(50000 + step * i),
                "position_value": 0.0,
                "symbols": config["symbols"],
            }
            for i in range(13)
        ]
        summaries.append(
            {
                "arm": arm,
                "cost": "1",
                "initial_equity": 50000,
                "final_equity": 50000 + step * 12,
                "net_compound_return": str(D(step * 12) / 50000),
                "quarter_count": 1,
                "total_cost": 5,
                "traded_notional": 500,
                "fills": 5,
                "risk_resize_fills": 0,
            }
        )
        fills = [
            {
                "arm": arm,
                "symbol": symbol,
                "cost": "1",
                "fill_id": symbol + "synthetic-fill",
                "reason_primary": "FIRST_TREND_ENTRY",
                "filled_qty": "1",
                "filled_notional": "100",
                "fee_paid": "1",
                "spread_cost": "0",
                "slippage_cost": "0",
                "impact_cost": "0",
                "total_cost": "1",
            }
            for symbol in config["symbols"]
        ]
        sleeves = [
            {
                "arm": arm,
                "symbol": symbol,
                "cost": "1",
                "mode": "REDECIDE_FUNDED",
                "cost_multiplier": "1",
                "cost_paid": "1",
                "total_cost": "1",
                "traded_notional": "100",
                "fills": 1,
                "final_equity": str(D(50000 + step * 12) / 5),
                "final_cash": str(D(50000 + step * 12) / 5),
            }
            for symbol in config["symbols"]
        ]
        prefix = r4 if arm == "F0" else r5
        parquet(f"{prefix}/execution_reason_attribution.parquet", fills)
        parquet(f"{prefix}/sleeve_results.parquet", sleeves)
    parquet(f"{r5}/portfolio_equity.parquet", portfolio)
    parquet(
        f"{r5}/same_fill_cost_shadow.parquet",
        [
            {
                "arm": "G1",
                "symbol": symbol,
                "cost": str(cost),
                "final_equity": str(D("10048") + 1 - cost),
                "total_cost": str(cost),
                "funded": False,
            }
            for symbol in config["symbols"]
            for cost in (D(1), D("1.5"), D(2))
        ],
    )
    write(
        f"{r5}/root_cause_audit.json",
        {"summary": summaries, "churn_all_passed": True, "churn_checks": {"synthetic": True}},
    )
    src["r5_statistics_sha256"] = sha256_file(write(f"{r5}/paired_statistics.json", stats))
    src["arithmetic_reference_sha256"] = sha256_file(
        write(
            src["arithmetic_reference"],
            {
                "g1_vs_f0": {
                    "wealth_difference": 120,
                    "nominal_reported_cost_difference": 0,
                    "cost_difference_fraction_of_wealth_difference": 0,
                    "wealth_plus_reported_cost_difference": 120,
                }
            },
        )
    )
    parquet(
        f"{recent}/portfolio_equity.parquet",
        [
            {
                "arm": "F3",
                "cost_multiplier": "1",
                "mode": "REDECIDE_FUNDED",
                "time": start + timedelta(hours=i * 4),
                "equity": float(50000 + i * 10),
            }
            for i in range(16)
        ],
    )
    write(
        f"{recent}/summary.json",
        {
            "portfolio": [
                {
                    "arm": "F3",
                    "mode": "REDECIDE_FUNDED",
                    "cost_multiplier": "1",
                    "final_equity": 50150,
                }
            ]
        },
    )
    src["recent_config_sha256"] = sha256_file(
        write(
            f"{recent}/effective_config.json",
            {
                "source_head": audit.BASE,
                "source_sha256": {},
                "primary_candidate": "F3",
                "arms": ["F3"],
                "test_start": "2020-01-01T00:00:00Z",
                "test_end_exclusive": "2020-01-03T12:00:00Z",
                "version": "recent-r4-fixed-20260908-v1",
            },
        )
    )
    run_id = src["r5_generation"] + ":G1:BTCUSDT:1"
    prefix = f"{r5}/runs/G1/BTCUSDT/1"
    parquet(f"{prefix}/decision_trace.parquet", [{"time": start}])
    parquet(f"{prefix}/equity.parquet", [{"time": start, "equity": "10000"}])
    write(f"{prefix}/completion.json", {"kind": "SYNTHETIC"})
    (root / prefix / "result.json.gz").write_bytes(gzip.compress(b'{"synthetic": true}'))
    write(f"{r5}/baseline_reproduction.json", {"kind": "SYNTHETIC"})
    manifest = {
        "config": source_config,
        "source_head": audit.BASE,
        "source_hashes": {name: sha256_file(root / name)},
        "frozen_evidence": {},
        "planned_runs": [{"arm": "G1", "symbol": "BTCUSDT", "cost": "1"}],
        "planned_run_ids": [run_id],
    }
    manifest["code_sha256"] = canonical_sha256(manifest["source_hashes"])
    manifest["sha256"] = canonical_sha256(manifest)
    src["r5_manifest_sha256"] = sha256_file(write(f"{r5}/audit_manifest.json", manifest))
    write(f"{r5}/preregistration.json", manifest)
    for version in (1, 2, 3):
        directory = f"artifacts/alpha_v5/20260908_research_churn_v{version}"
        if version < 3:
            write(
                f"{directory}/preregistration.json",
                {"config": {"generation": f"synthetic-v{version}"}, "planned_run_ids": [run_id]},
            )
        journal = ExperimentEventJournal(root / directory / "experiment_events.jsonl")
        journal.append(
            ExperimentEvent(
                event_id=f"{run_id}:STARTED",
                run_id=run_id,
                event_type=ExperimentEventType.STARTED,
                recorded_at_utc=start,
                details={"kind": "SYNTHETIC"},
            )
        )
        details: dict[str, Any] = {"reason": "synthetic precondition failure"}
        if version == 3:
            details = {
                "arm": "G1",
                "symbol": "BTCUSDT",
                "cost": "1",
                "artifacts_sha256": {
                    n: sha256_file(root / prefix / n)
                    for n in (
                        "completion.json",
                        "decision_trace.parquet",
                        "equity.parquet",
                        "result.json.gz",
                    )
                },
            }
        journal.append(
            ExperimentEvent(
                event_id=f"{run_id}:END",
                run_id=run_id,
                event_type=ExperimentEventType.SUCCEEDED
                if version == 3
                else ExperimentEventType.ERROR,
                recorded_at_utc=start,
                details=details,
            )
        )
    for version in (1, 2):
        write(
            f"artifacts/current_system_recent/20260908_v{version}/failure.json",
            {"status": "SYNTHETIC_PRECONDITION_FAILURE"},
        )
    for prior in config.get("prior_report_failures", []):
        directory = prior["output"]
        prior_run = prior["generation"] + ":REPORT"
        write(
            f"{directory}/preregistration.json",
            {
                "config": {"generation": prior["generation"]},
                "kind": "EVIDENCE_REPORT_NOT_ALPHA_TRIAL",
                "planned_run_ids": [prior_run],
            },
        )
        write(
            f"{directory}/failure.json",
            {"error": "SYNTHETIC_ONLY", "actual_attempts": dict.fromkeys(audit.ZERO_BUDGETS, 0)},
        )
        journal = ExperimentEventJournal(root / directory / "experiment_events.jsonl")
        for event in (ExperimentEventType.STARTED, ExperimentEventType.ERROR):
            journal.append(
                ExperimentEvent(
                    event_id=f"{prior_run}:{event}",
                    run_id=prior_run,
                    event_type=event,
                    recorded_at_utc=start,
                    details={"kind": "SYNTHETIC", "reason": "synthetic prior report failure"},
                )
            )
        audit.seal_output(root / directory)
        prior["output_manifest_sha256"] = sha256_file(root / directory / "OUTPUT_MANIFEST.json")
    (root / "configs/research/alpha_v5_review_contract.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    baseline = {
        "branch": "main",
        "head": audit.BASE,
        "root": str(root),
        "status_porcelain": "SYNTHETIC",
        "files": {
            p.relative_to(root).as_posix(): {"sha256": sha256_file(p), "bytes": p.stat().st_size}
            for p in root.rglob("*")
            if p.is_file()
        },
    }
    (stage / "baseline_workspace.json").write_text(json.dumps(baseline), encoding="utf-8")
    for name in (
        "workspace_before.patch",
        "version_graph.txt",
        "remote_main.txt",
        "test_commands_and_results.txt",
    ):
        (stage / name).write_text("SYNTHETIC FIXTURE ONLY\n", encoding="utf-8")
    receipts = [
        {
            "check": check,
            "command": ["SYNTHETIC_RECEIPT_FIXTURE", *audit.NEW_FILES[3:5]],
            "exit_code": 0,
            "source_sha256": {name: sha256_file(root / name) for name in audit.NEW_FILES},
            "stdout": "SYNTHETIC_RECEIPT_NOT_AN_ACTUAL_TEST_RUN",
        }
        for check in ("pytest", "ruff", "format", "pyright")
    ]
    (stage / "validation_records.json").write_text(json.dumps(receipts), encoding="utf-8")
    return root, config, stage


def test_cli_synthetic_end_to_end_no_forbidden_import_or_call(
    tmp_path: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config, stage = synthetic_project(tmp_path, project_root)
    poison = Mock(side_effect=AssertionError("forbidden pipeline reached"))
    for module in (
        "scripts.run_alpha_v5_research",
        "scripts.audit_alpha_profitability_root_causes",
        "aegisquant.research.validation.cat_replay",
        "aegisquant.research.validation.persistent_holdout",
        "aegisquant.research.training.economic_filter",
        "aegisquant.execution",
    ):
        sentinel = ModuleType(module)
        sentinel.__getattr__ = poison
        monkeypatch.setitem(sys.modules, module, sentinel)
    monkeypatch.setattr(cli, "__file__", str(root / "scripts/audit_alpha_v5_evidence.py"))
    monkeypatch.setattr(sys, "argv", ["audit", "--preflight-dir", str(stage)])
    git_spy = Mock(side_effect=[(audit.BASE + "\n").encode(), b"main\n", b"SYNTHETIC\n"])
    monkeypatch.setattr(cli.subprocess, "check_output", git_spy)
    cli.main()
    output = root / config["output"]
    assert git_spy.call_count == 3
    poison.assert_not_called()
    assert load_evidence_manifest(output, "OUTPUT_MANIFEST.json")["status"] == "VERIFIED"
    safety = json.loads((output / "safety_and_budget_audit.json").read_text())
    assert safety["actual"] == {"report_jobs": 1, **dict.fromkeys(audit.ZERO_BUDGETS, 0)}
    assert safety["report_attempts_including_retained_failures"] == 2
    history = json.loads((output / "failure_history_index.json").read_text())
    assert len(history["review_report_failures"]) == 1
    assert history["review_report_failures"][0]["events"][-1]["event_type"] == "ERROR"
    identity = json.loads((output / "source_and_version_bindings.json").read_text())
    assert (
        identity["recent_g1"] == "NOT_COLLECTED"
        and identity["full_bundle"]["full_raw_bundle_received"] is False
    )
    arithmetic = json.loads((output / "arithmetic_audit.json").read_text())
    assert arithmetic["recent_f3_separate"]["terminal_half_day_pnl_included"] == "30.0"
    assert json.loads((output / "statistics_identity.json").read_text())["family_size"] == 9
    assert (
        audit.audit_existing_files(
            root, json.loads((stage / "baseline_workspace.json").read_text())
        )["changed"]
        == []
    )
    with pytest.raises(FileExistsError):
        audit.run_report(root, config, stage, {"branch": "main", "head": audit.BASE})


def test_failed_cli_claim_is_retained_and_cannot_reopen(tmp_path: Path, project_root: Path) -> None:
    root, config, stage = synthetic_project(tmp_path, project_root)
    config["source"]["r5_manifest_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="R5-MANIFEST-PIN"):
        audit.run_report(root, config, stage, {"branch": "main", "head": audit.BASE})
    output = root / config["output"]
    assert (output / "failure.json").is_file() and (output / "OUTPUT_MANIFEST.json").is_file()
    assert (
        ExperimentEventJournal(output / "experiment_events.jsonl").entries()[-1].event.event_type
        == ExperimentEventType.ERROR
    )
    with pytest.raises(FileExistsError):
        audit.run_report(root, config, stage, {"branch": "main", "head": audit.BASE})


@pytest.mark.parametrize(
    "reason,quantity", [("ORDINARY_RISK_REDUCE", "-1"), ("ORDINARY_RISK_RESTORE", "1")]
)
def test_derived_fill_count_reason_and_cost_mutations(reason: str, quantity: str) -> None:
    row = {
        "arm": "G1",
        "cost": "1",
        "symbol": "SYNTH",
        "fill_id": "f",
        "reason_primary": reason,
        "filled_qty": quantity,
        "filled_notional": "100",
        "fee_paid": ".1",
        "spread_cost": ".01",
        "slippage_cost": ".02",
        "impact_cost": ".03",
        "total_cost": ".16",
    }
    summary = {
        "arm": "G1",
        "cost": "1",
        "fills": 1,
        "risk_resize_fills": 1,
        "total_cost": ".16",
        "traded_notional": "100",
    }
    result = audit_fills([row], [summary])[0]
    assert result["reason_counts"] == {reason: 1}
    assert result["filled_qty_semantics"] == "SIGNED_BUY_POSITIVE_SELL_NEGATIVE"
    for field, value, match in (
        ("filled_qty", "0", "FILL-AMOUNT"),
        ("filled_qty", str(-D(quantity)), "LONG-ONLY-RESIZE-DIRECTION"),
        ("filled_notional", "-100", "FILL-AMOUNT"),
        ("total_cost", ".17", "COST-COMPONENTS"),
        ("filled_notional", "101", "FILL-TOTALS"),
        ("reason_primary", "ENTRY", "FILL-REASON-COUNT"),
    ):
        with pytest.raises(ValueError, match=match):
            audit_fills([{**row, field: value}], [summary])
