"""First R5 batch: finite, no-ML development diagnostics with preregistered inputs.

This command cannot allocate a holdout, select parameters, train a model or promote.
PIT/execution evidence remains a prerequisite for the later taskbook stages.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import JsonValue

from aegisquant.backtest.metrics import resample_equity
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import RunId
from aegisquant.portfolio.economic_gate import EconomicGatePolicy
from aegisquant.research.strategies.buffered_target import BufferPolicy, RiskResizePolicy
from aegisquant.research.validation.cat_replay import load_completed_bars, replay_cat
from aegisquant.research.validation.experiment_registry import (
    checked_development_path,
    registered_run,
)
from scripts.export_alpha_v4_audit_bundle import digest, git
from scripts.run_alpha_r4 import BASELINE, read_result, reproduce, save_run
from scripts.run_alpha_v4_audit import ROOT, SYMBOLS, AuditInputs, inputs, make_spec, read_json
from scripts.run_alpha_v4_audit_r2 import policies, strip_identity
from scripts.run_alpha_v4_walkforward import table, write_json

CONFIG = ROOT / "configs/research/aegis_alpha_v5.yaml"
R4 = ROOT / "artifacts/alpha_r4/20260908_v1"
DEFAULT_OUTPUT = ROOT / "artifacts/alpha_v5/20260908_research_churn_v3"


def controls(config: dict[str, Any], arm: str) -> tuple[BufferPolicy, RiskResizePolicy | None]:
    settings = config["arms"][arm]
    if settings["kind"] == "FROZEN_R4_F3":
        return BufferPolicy(), None
    resize = {**config["resize"], **settings}
    buffer = config["buffer"]
    return (
        BufferPolicy(
            relative_half_width=Decimal(buffer["relative_half_width"]),
            restore_half_width=Decimal(buffer["restore_half_width"]),
            reduce_half_width=Decimal(buffer["reduce_half_width"]),
            absolute_weight_floor=Decimal(buffer["absolute_weight_floor"]),
        ),
        RiskResizePolicy(
            smoothing_half_life=timedelta(days=resize["smoothing_half_life_days"]),
            review_interval=timedelta(hours=resize["review_interval_hours"]),
            minimum_weight_change=Decimal(resize["minimum_weight_change"]),
            minimum_notional=Decimal(resize["minimum_notional"]),
            cost_benefit_lambda=Decimal(resize["cost_benefit_lambda"]),
        ),
    )


def assert_research_scope(config: dict[str, Any]) -> None:
    for field in (
        "production_ml_enabled",
        "paper_trading_admitted",
        "live_trading",
        "order_submission_enabled",
        "parameter_selection_from_results",
    ):
        if config.get(field) is not False:
            raise PermissionError(f"first-batch research lock violated: {field}")
    if config["production_policy"] != "CASH" or config["selected_model_id"] is not None:
        raise PermissionError("research generation must retain CASH and no selected model")
    if config["new_return_model_fits"] != 0 or config["new_calibration_fits"] != 0:
        raise PermissionError("first batch has zero model/calibration fit budget")
    holdout = config["final_holdout"]
    if (
        holdout["development_access_allowed"] is not False
        or holdout["status"] != "NOT_ALLOCATED_INSUFFICIENT_EVIDENCE"
        or any(holdout[key] is not None for key in ("path", "sha256", "start", "end_exclusive"))
        or config["universe"]["promotion_evidence_eligible"] is not False
    ):
        raise PermissionError("first batch cannot allocate or consume final holdout evidence")
    if config["development"]["classification"] != "PREVIOUSLY_USED_DEVELOPMENT_DATA":
        raise PermissionError("legacy observations cannot be reclassified as unused evidence")
    for arm, settings in config["arms"].items():
        if settings["kind"] not in {"FROZEN_R4_F3", "RESIZE_V2", "SAME_RISK_PASSIVE"}:
            raise ValueError("unregistered strategy kind")
        if not settings["costs"] or any(c not in {"1", "1.5", "2"} for c in settings["costs"]):
            raise ValueError("invalid registered costs")
        controls(config, arm)


def preregister(output: Path) -> None:
    if (output / "preregistration.json").exists():
        raise FileExistsError("generation already registered; preserve all prior trials")
    if git(ROOT, "branch", "--show-current") != "main":
        raise PermissionError("research requires the existing main checkout")
    config: dict[str, Any] = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert_research_scope(config)
    source_manifest = ROOT / config["development"]["source_manifest"]
    if source_manifest.resolve() != ROOT / "artifacts/alpha_v4_multi_asset/source_manifest.json":
        raise PermissionError("first batch only admits the frozen legacy public data manifest")
    sources = read_json(source_manifest)["datasets"]
    if sorted(row["symbol"] for row in sources) != sorted(SYMBOLS):
        raise ValueError("legacy diagnostic requires the exact five registered assets")
    protected = [ROOT / p for p in config["protected_data_roots"]]
    # Enforce canonical protected roots even if a YAML edit omits one.
    protected += [ROOT / "artifacts/alpha_v4/holdout", ROOT / "artifacts/alpha_v5/holdout"]
    allowed = {Path(row["path"]).as_posix(): row["sha256"] for row in sources}
    for name in allowed:
        resolved = (ROOT / name).resolve()
        if not resolved.is_relative_to(ROOT) or any(
            resolved.is_relative_to(p.resolve()) for p in protected
        ):
            raise PermissionError("a protected path cannot be registered as development data")
    files = [*ROOT.glob("src/**/*.py"), CONFIG, ROOT / "uv.lock", ROOT / "pyproject.toml"]
    files += [
        ROOT / "scripts" / name
        for name in (
            "run_alpha_v5_research.py",
            "run_alpha_r4.py",
            "run_alpha_v4_audit.py",
            "run_alpha_v4_audit_r2.py",
            "run_alpha_v4_walkforward.py",
            "summarize_alpha_r4.py",
            "export_alpha_v4_audit_bundle.py",
            "audit_alpha_profitability_root_causes.py",
        )
    ]
    files += [ROOT / config["taskbook"], source_manifest]
    files += [
        ROOT / name
        for name in (
            "artifacts/alpha_v4_multi_asset/run_manifest.json",
            "configs/research/alpha_v4_multi_asset.yaml",
            "configs/research/aegis_alpha_v4.yaml",
            "configs/strategies/aegisalpha_cat_v1.yaml",
        )
    ]
    output.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for source in sorted(set(files)):
        name = source.relative_to(ROOT).as_posix()
        target = output / "implementation" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[name] = digest(target)
    evidence = [*BASELINE.glob("*.parquet"), BASELINE / "run_manifest.json"]
    predecessor = ROOT / config["predecessor"]
    parent_manifest = read_json(predecessor / "preregistration.json")
    evidence += [
        ROOT / name
        for name in parent_manifest["frozen_evidence"]
        if name.startswith("artifacts/alpha_v5/")
    ]
    if (predecessor / "baseline_reproduction.json").exists():
        evidence.append(predecessor / "baseline_reproduction.json")
    evidence += [
        predecessor / name
        for name in (
            "preregistration.json",
            "experiment_events.jsonl",
            "execution_claim.json",
            "validation/replay_execution.json",
            "validation/replay.log",
        )
    ]
    evidence += [
        R4 / name
        for name in (
            "go_no_go.md",
            "audit_manifest.json",
            "portfolio_equity.parquet",
            "execution_reason_attribution.parquet",
            "sleeve_results.parquet",
            "quarter_results.parquet",
            "opportunity_attribution.json",
        )
        if (R4 / name).exists()
    ]
    for symbol in SYMBOLS:
        evidence += list((R4 / "runs/F3" / symbol / "REDECIDE_FUNDED_1/continuous").glob("*"))
    plan = [
        (arm, symbol, cost)
        for arm, settings in config["arms"].items()
        for symbol in SYMBOLS
        for cost in settings["costs"]
    ]
    generation = config["generation"]
    planned_ids = [f"{generation}:baseline"] + [f"{generation}:{a}:{s}:{c}" for a, s, c in plan]
    if len(planned_ids) != len(set(planned_ids)):
        raise ValueError("duplicate research slot")
    manifest = {
        "registered_at": datetime.now(UTC).isoformat(),
        "config": config,
        "source_head": git(ROOT, "rev-parse", "HEAD"),
        "source_hashes": hashes,
        "code_sha256": canonical_sha256(hashes),
        "allowed_sources": allowed,
        "sources_by_symbol": {r["symbol"]: Path(r["path"]).as_posix() for r in sources},
        "protected_roots": [str(p.resolve()) for p in protected],
        "frozen_evidence": {p.relative_to(ROOT).as_posix(): digest(p) for p in evidence},
        "planned_runs": [{"arm": a, "symbol": s, "cost": c} for a, s, c in plan],
        "planned_run_ids": planned_ids,
        "historical_independent_trial_history": "INCOMPLETE_DO_NOT_PASS_DSR_PBO",
        "gate": read_json(BASELINE / "run_manifest.json")["gate"],
    }
    manifest["sha256"] = canonical_sha256(manifest)
    write_json(output / "preregistration.json", manifest)
    # Reuse the R4 exact A1 reproduction, which consumes only the gate from this manifest.
    write_json(output / "audit_manifest.json", manifest)
    print(f"Registered {len(plan)} continuous diagnostics plus 70 baseline partitions", flush=True)


def verify_bindings(output: Path) -> dict[str, Any]:
    manifest = read_json(output / "preregistration.json")
    if manifest["sha256"] != canonical_sha256({k: v for k, v in manifest.items() if k != "sha256"}):
        raise ValueError("generation manifest hash changed")
    assert_research_scope(manifest["config"])
    if git(ROOT, "branch", "--show-current") != "main":
        raise PermissionError("main checkout required")
    for name, expected in {**manifest["source_hashes"], **manifest["frozen_evidence"]}.items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"frozen implementation/evidence changed: {name}")
    return manifest


def prepare_development_inputs(output: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    config = manifest["config"]
    start = datetime.fromisoformat(config["development"]["start"])
    end = datetime.fromisoformat(config["development"]["end_exclusive"])
    for symbol, name in manifest["sources_by_symbol"].items():
        path = checked_development_path(
            ROOT,
            ROOT / name,
            allowed_sources=manifest["allowed_sources"],
            protected_roots=[Path(p) for p in manifest["protected_roots"]],
        )
        # Source bytes are already approved/hashed. Select by timestamp before
        # parsing OHLCV or building features; excluded tails never reach replay.
        partition = output / "development_data" / f"{symbol}_1h.csv"
        partition.parent.mkdir(parents=True, exist_ok=True)
        excluded = included = 0
        with (
            path.open(encoding="utf-8", newline="") as source,
            partition.open("x", encoding="utf-8", newline="") as destination,
        ):
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise ValueError("empty development source")
            writer = csv.DictWriter(destination, fieldnames=reader.fieldnames, lineterminator="\n")
            writer.writeheader()
            for row in reader:
                event_time = datetime.fromtimestamp(int(row["open_time_ms"]) / 1000, UTC)
                if start <= event_time < end:
                    writer.writerow(row)
                    included += 1
                else:
                    excluded += 1
        bars = load_completed_bars(partition, strict_source=True)
        if not bars or any(b.event_time < start or b.available_time >= end for b in bars):
            raise PermissionError("market observations exceed the registered development interval")
        rows[symbol] = {
            "source_path": name,
            "source_sha256": digest(path),
            "path": partition.relative_to(ROOT).as_posix(),
            "sha256": digest(partition),
            "included_hourly_rows": included,
            "excluded_outside_window_rows": excluded,
            "complete_4h_bars": len(bars),
            "first_event": bars[0].event_time,
            "last_available": bars[-1].available_time,
            "missing_bars_filled": False,
        }
    return rows


def guarded_inputs(symbol: str, manifest: dict[str, Any]) -> AuditInputs:
    expected = (ROOT / manifest["sources_by_symbol"][symbol]).resolve()

    def guard(source: Path) -> Path:
        protected = [Path(p).resolve() for p in manifest["protected_roots"]]
        if any(source.resolve().is_relative_to(p) for p in protected):
            raise PermissionError("AQ-DEVELOPMENT-HOLDOUT-PATH-FORBIDDEN")
        if source.resolve() != expected:
            raise PermissionError("symbol source differs from preregistered identity")
        row = manifest["prepared_sources"][symbol]
        checked = checked_development_path(
            ROOT,
            ROOT / row["path"],
            allowed_sources={row["path"]: row["sha256"]},
            protected_roots=protected,
        )
        return checked

    return inputs(symbol, source_guard=guard)


def run_one(
    output: Path, manifest: dict[str, Any], trial: dict[str, str], data: AuditInputs
) -> None:
    config = manifest["config"]
    arm, symbol, cost = trial["arm"], trial["symbol"], trial["cost"]
    source, market, bars, features, _, _, folds, indices, trend = data
    segment = replace(folds[0], fold_id="continuous", test_end=folds[-1].test_end)
    if segment.test_start != datetime.fromisoformat(
        config["development"]["test_start"]
    ) or segment.test_end != datetime.fromisoformat(config["development"]["end_exclusive"]):
        raise ValueError("legacy folds do not match registered absolute dates")
    buffer, resize = controls(config, arm)
    if config["arms"][arm]["kind"] == "SAME_RISK_PASSIVE":
        trend = dict.fromkeys(trend, True)
    spec = make_spec(
        symbol, segment, arm, source, manifest, Decimal(config["initial_cash_per_symbol"])
    ).model_copy(
        update={
            "run_id": RunId(f"r5-{arm}-{symbol}-{cost}"),
            "code_sha256": manifest["code_sha256"],
            "reproduction_command": "python -m scripts.run_alpha_v5_research run --output <registered-output>",
        }
    )
    result, trace = replay_cat(
        root=ROOT,
        spec=spec,
        bars=tuple(b for b in bars if segment.test_start <= b.event_time < segment.test_end),
        features=features,
        feature_indices=indices,
        trend_by_time=trend,
        forecasts={},
        level="A1",
        audit_policy=policies()["A1"],
        gate_policy=EconomicGatePolicy.model_validate_json(json.dumps(manifest["gate"])),
        market_spec=market,
        cost_multiplier=Decimal(cost),
        buffer_policy=buffer,
        resize_policy=resize,
        terminal_exit_reason="EVALUATION_END_NEXT_OPEN_EXIT",
    )
    if arm == "G0":
        old = read_result(R4 / "runs/F3" / symbol / "REDECIDE_FUNDED_1/continuous")
        for name in ("orders", "fills"):
            if [strip_identity(r.model_dump(mode="json")) for r in getattr(old, name)] != [
                strip_identity(r.model_dump(mode="json")) for r in getattr(result, name)
            ]:
                raise ValueError(f"R4 F3 {name} economic identity changed")
        if resample_equity(old.equity_curve, 14400) != resample_equity(result.equity_curve, 14400):
            raise ValueError("R4 F3 complete MTM changed")
    folder = output / "runs" / arm / symbol / cost
    save_run(folder, result, trace)
    table(
        folder / "equity.parquet",
        [
            {
                "arm": arm,
                "symbol": symbol,
                "cost": cost,
                "time": p.time,
                "equity": str(p.equity),
                "cash": str(p.cash),
                "position_value": str(p.position_value),
            }
            for p in resample_equity(result.equity_curve, 14400)
        ],
    )


def run(output: Path) -> None:
    manifest = verify_bindings(output)
    # The exclusive claim remains after any failure; reruns require a new generation.
    with (output / "execution_claim.json").open("x", encoding="utf-8") as stream:
        json.dump(
            {"manifest_sha256": manifest["sha256"], "started_at": datetime.now(UTC).isoformat()},
            stream,
        )
    generation = manifest["config"]["generation"]
    bindings: dict[str, JsonValue] = {
        "manifest_sha256": manifest["sha256"],
        "model_fits": 0,
        "calibration_fits": 0,
        "holdout_accesses": 0,
    }
    run_id = f"{generation}:baseline"
    with registered_run(
        output, run_id, planned_run_ids=manifest["planned_run_ids"], bindings=bindings
    ):
        rows = prepare_development_inputs(output, manifest)
        write_json(output / "development_input_audit.json", rows)
        manifest["prepared_sources"] = rows
        bindings["development_partitions_sha256"] = digest(output / "development_input_audit.json")
        reproduce(output, input_loader=lambda symbol: guarded_inputs(symbol, manifest))
        bindings["baseline_result_sha256"] = digest(output / "baseline_reproduction.json")
    # Read each approved public history once per symbol; no prediction artifacts/model code execute.
    for symbol in SYMBOLS:
        data = guarded_inputs(symbol, manifest)
        for trial in manifest["planned_runs"]:
            if trial["symbol"] != symbol:
                continue
            run_id = f"{generation}:{trial['arm']}:{symbol}:{trial['cost']}"
            current: dict[str, JsonValue] = {
                **bindings,
                "arm": trial["arm"],
                "symbol": symbol,
                "cost": trial["cost"],
            }
            print(run_id, flush=True)
            with registered_run(
                output, run_id, planned_run_ids=manifest["planned_run_ids"], bindings=current
            ):
                run_one(output, manifest, trial, data)
                folder = output / "runs" / trial["arm"] / symbol / trial["cost"]
                current["artifacts_sha256"] = {
                    p.name: digest(p) for p in folder.iterdir() if p.is_file()
                }
    verify_bindings(output)
    print("All registered engine diagnostics completed; no candidate selected", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "run", "report"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "artifacts/alpha_v5"):
        raise ValueError("R5 evidence must stay in its own artifacts/alpha_v5 directory")
    if args.command == "register":
        preregister(output)
    elif args.command == "run":
        run(output)
    else:
        from scripts.audit_alpha_profitability_root_causes import report

        report(output)


if __name__ == "__main__":
    main()
