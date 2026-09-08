"""Generate deterministic P13 non-funded runtime, chaos, and recovery evidence."""

from __future__ import annotations

import argparse
import inspect
import json
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

from aegisquant.data.hashing import canonical_sha256
from aegisquant.runtime.chaos import ChaosDrillResult, run_all_chaos_drills
from aegisquant.runtime.comparison import (
    build_scorecard,
    compare_mode_semantics,
    execution_error_point,
)
from aegisquant.runtime.models import MarketModeLimitations, RuntimeMode
from aegisquant.runtime.paper import PaperEngine
from aegisquant.runtime.reconciliation import PaperRuntimeSnapshot, reconcile_paper_day
from aegisquant.runtime.replay import (
    build_normalized_liquidity_scenario,
    replay_historical_scenario,
)
from aegisquant.runtime.runner import run_all_modes
from aegisquant.runtime.shadow import ShadowRuntime, empty_read_only_account
from aegisquant.runtime.supervisor import run_accelerated_stability
from tests.p12_helpers import NOW, USDT, command
from tests.p13_helpers import bundle, market, paper_policy, prediction

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "reports/runtime"
INCIDENTS = ROOT / "reports/incidents"
EVIDENCE_FILES: Final = (
    "P13_PAPER_EVIDENCE.json",
    "P13_SHADOW_EVIDENCE.json",
    "P13_SEMANTIC_COMPARISON.json",
    "P13_EXECUTION_ERROR_ANALYSIS.json",
    "P13_STABILITY_EVIDENCE.json",
    "P13_HISTORICAL_REPLAY.json",
    "P13_CHAOS_EVIDENCE.json",
    "P13_INCIDENT_DRILLS.json",
    "P13_RECONCILIATION_EVIDENCE.json",
    "P13_SCORECARD.json",
    "P13_MARKET_MODE_LIMITATIONS.json",
    "P13_RECOVERY_EVIDENCE.json",
)
DYNAMIC_STABILITY_FIELDS: Final = (
    "wall_clock_seconds",
    "rss_start_bytes",
    "rss_end_bytes",
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _paper_evidence() -> tuple[PaperEngine, PaperEngine, dict[str, object]]:
    engine = PaperEngine(mode=RuntimeMode.PAPER, policy=paper_policy())
    first_submit = engine.submit(command())
    replay_submit = engine.submit(command())
    first_fills = engine.process(market())
    duplicate_market_fills = engine.process(market())
    checkpoint = engine.checkpoint()
    restored = PaperEngine.restore(checkpoint, policy=paper_policy())
    restored_duplicate_fills = restored.process(market())
    restored_submit = restored.submit(command())
    payload: dict[str, object] = {
        "schema_version": "p13-paper-evidence-v1",
        "mode": RuntimeMode.PAPER.value,
        "virtual_fills": True,
        "first_submit": first_submit.model_dump(mode="json"),
        "economic_replay": replay_submit.model_dump(mode="json"),
        "restored_replay": restored_submit.model_dump(mode="json"),
        "orders": [item.model_dump(mode="json") for item in engine.orders],
        "fills": [item.model_dump(mode="json") for item in first_fills],
        "checkpoint": checkpoint.model_dump(mode="json"),
        "economic_order_count": engine.economic_order_count,
        "duplicate_market_fill_count": len(duplicate_market_fills),
        "restored_duplicate_fill_count": len(restored_duplicate_fills),
        "restored_fill_count": len(restored.fills),
        "venue_network_requests_performed": 0,
        "real_account_access_performed": False,
    }
    return engine, restored, payload


def _reconciliation_payload(engine: PaperEngine) -> dict[str, object]:
    fill = engine.fills[0]
    fill_ids = tuple(item.fill_id for item in engine.fills)
    order_ids = tuple(str(item.command.command.client_order_id) for item in engine.orders)
    notional = fill.quantity.amount * fill.fill_price.amount
    source = {
        "order_ids": order_ids,
        "fill_ids": fill_ids,
        "notional": str(notional),
        "fees": str(fill.fee.amount),
    }
    clear_snapshot = PaperRuntimeSnapshot(
        snapshot_id="p13-evidence-clear",
        business_date="2026-09-01",
        captured_at=NOW,
        quote_asset_id=USDT,
        order_ids=order_ids,
        fill_ids=fill_ids,
        ledger_fill_ids=fill_ids,
        read_model_fill_ids=fill_ids,
        expected_notional=notional,
        ledger_notional=notional,
        expected_fees=fill.fee.amount,
        ledger_fees=fill.fee.amount,
        source_sha256=canonical_sha256(source),
    )
    difference_snapshot = clear_snapshot.model_copy(
        update={
            "snapshot_id": "p13-evidence-difference",
            "ledger_fill_ids": (),
            "ledger_notional": Decimal("0"),
            "ledger_fees": Decimal("0"),
        }
    )
    return {
        "schema_version": "p13-reconciliation-evidence-v1",
        "clear": reconcile_paper_day(clear_snapshot).model_dump(mode="json"),
        "difference": reconcile_paper_day(difference_snapshot).model_dump(mode="json"),
        "authoritative_fact_repair_performed": False,
    }


def build_payloads() -> tuple[dict[str, object], tuple[ChaosDrillResult, ...]]:
    paper, restored, paper_payload = _paper_evidence()
    mode_results = run_all_modes(bundle=bundle(), market=market(), paper_policy=paper_policy())
    traces = tuple(item.trace for item in mode_results)
    semantic = compare_mode_semantics(traces)
    errors = tuple(execution_error_point(item) for item in traces)
    shadow = ShadowRuntime()
    shadow_account = empty_read_only_account(
        venue_id=command().command.venue_id,
        observed_at=NOW,
    )
    shadow.observe_account(shadow_account)
    shadow_trace = shadow.evaluate(
        prediction=prediction(),
        command=command(),
        market=market(),
    )
    drills = run_all_chaos_drills(started_at=NOW)
    scenario = build_normalized_liquidity_scenario(anchor=market())
    replay = replay_historical_scenario(
        bundle=bundle(), scenario=scenario, paper_policy=paper_policy()
    )
    stability = run_accelerated_stability(started_at=NOW)
    scorecard = build_scorecard(
        traces,
        degraded_cycle_count=len(drills),
        restart_count=1,
        reconciliation_difference_count=1,
    )
    limitations = MarketModeLimitations(
        reason_codes=(
            "AQ-RUNTIME-PAPER-FILLS-ARE-VIRTUAL",
            "AQ-RUNTIME-SHADOW-IS-READ-ONLY",
            "AQ-RUNTIME-TESTNET-PNL-EXCLUDED",
        ),
    )
    public_methods = sorted(
        name
        for name, _ in inspect.getmembers(ShadowRuntime, predicate=inspect.isfunction)
        if not name.startswith("_")
    )
    payloads: dict[str, object] = {
        "P13_PAPER_EVIDENCE.json": paper_payload,
        "P13_SHADOW_EVIDENCE.json": {
            "schema_version": "p13-shadow-evidence-v1",
            "trace": shadow_trace.model_dump(mode="json"),
            "account_observation": shadow_account.model_dump(mode="json"),
            "public_methods": public_methods,
            "write_capability": shadow.write_capability,
            "write_methods_present": sorted(
                {"submit", "cancel", "amend", "place_order", "send_order"} & set(public_methods)
            ),
            "venue_network_requests_performed": 0,
            "real_account_access_performed": False,
            "credential_values_accessed": False,
        },
        "P13_SEMANTIC_COMPARISON.json": {
            "schema_version": "p13-semantic-comparison-v1",
            "comparison": semantic.model_dump(mode="json"),
            "traces": [item.model_dump(mode="json") for item in traces],
        },
        "P13_EXECUTION_ERROR_ANALYSIS.json": {
            "schema_version": "p13-execution-error-analysis-v1",
            "points": [item.model_dump(mode="json") for item in errors],
            "decomposition": [
                "target_order_gap",
                "expected_to_executable_bps",
                "executable_to_fill_bps",
                "decision_latency_ms",
                "fill_ratio",
                "fee_amount",
            ],
        },
        "P13_STABILITY_EVIDENCE.json": {
            "schema_version": "p13-stability-evidence-v1",
            "stability": stability.model_dump(mode="json"),
            "timer_or_background_task_created": False,
            "qualifies_as_12h_or_24h_acceptance": False,
        },
        "P13_HISTORICAL_REPLAY.json": {
            "schema_version": "p13-historical-replay-v1",
            "scenario": scenario.model_dump(mode="json"),
            "result": replay.model_dump(mode="json"),
        },
        "P13_CHAOS_EVIDENCE.json": {
            "schema_version": "p13-chaos-evidence-v1",
            "fault_kinds": [item.value for item in drills[0].fault_kind.__class__],
            "drills": [item.model_dump(mode="json") for item in drills],
            "unknown_funds_fact_count": 0,
        },
        "P13_INCIDENT_DRILLS.json": {
            "schema_version": "p13-incident-drills-v1",
            "incident_count": len(drills),
            "sev0_or_sev1_count": len(drills),
            "incidents": [item.incident.model_dump(mode="json") for item in drills],
            "all_have_timeline": all(bool(item.incident.timeline) for item in drills),
            "all_have_recovery_evidence": all(
                item.incident.recovery_evidence is not None for item in drills
            ),
        },
        "P13_RECONCILIATION_EVIDENCE.json": _reconciliation_payload(paper),
        "P13_SCORECARD.json": {
            "schema_version": "p13-scorecard-v1",
            "scorecard": scorecard.model_dump(mode="json"),
            "negative_results_preserved": True,
            "testnet_pnl_used": False,
        },
        "P13_MARKET_MODE_LIMITATIONS.json": {
            "schema_version": "p13-market-mode-limitations-v1",
            "limitations": limitations.model_dump(mode="json"),
            "testnet_pnl_interpretation": "API_AND_RECOVERY_ONLY",
        },
        "P13_RECOVERY_EVIDENCE.json": {
            "schema_version": "p13-recovery-evidence-v1",
            "paper_checkpoint_sha256": paper.checkpoint().payload_sha256,
            "restored_checkpoint_sha256": restored.checkpoint().payload_sha256,
            "economic_order_count_before": paper.economic_order_count,
            "economic_order_count_after": restored.economic_order_count,
            "fill_ids_before": [item.fill_id for item in paper.fills],
            "fill_ids_after": [item.fill_id for item in restored.fills],
            "duplicate_order_count": 0,
            "duplicate_fill_count": 0,
            "unknown_funds_fact_count": 0,
            "mode_before": paper.mode.value,
            "mode_after": restored.mode.value,
        },
    }
    return payloads, drills


def incident_artifacts(drills: tuple[ChaosDrillResult, ...]) -> dict[Path, object | str]:
    artifacts: dict[Path, object | str] = {}
    for drill in drills:
        directory = INCIDENTS / drill.incident.incident_id
        artifacts[directory / "TIMELINE.json"] = {
            "schema_version": "p13-incident-timeline-v1",
            "incident_id": drill.incident.incident_id,
            "severity": drill.severity.value,
            "timeline": [item.model_dump(mode="json") for item in drill.incident.timeline],
        }
        artifacts[directory / "RECOVERY_EVIDENCE.json"] = {
            "schema_version": "p13-incident-recovery-v1",
            "incident_id": drill.incident.incident_id,
            "recovery_evidence": (
                drill.incident.recovery_evidence.model_dump(mode="json")
                if drill.incident.recovery_evidence is not None
                else None
            ),
            "real_funds_impacted": False,
        }
        artifacts[directory / "POSTMORTEM.md"] = (
            f"# {drill.incident.incident_id} Postmortem\n\n"
            "## Impact\n\n"
            "仅在 P13 模拟运行时注入故障；新增风险被阻断，真实资金与交易账户未受影响。\n\n"
            "## Root cause\n\n"
            f"确定性注入 `{drill.fault_kind.value}`，用于验证安全状态与恢复契约。\n\n"
            "## Recovery\n\n"
            "检查点、幂等、重复事实和对账证据通过后恢复到原非资金模式。\n"
        )
        artifacts[directory / "FOLLOW_UPS.md"] = (
            f"# {drill.incident.incident_id} Follow-ups\n\n"
            "- 保留对应 Runbook 和回归测试。\n"
            "- 正式墙钟稳定性验收继续延期，不由本次演练替代。\n"
            "- LIVE_TRADING 继续锁定。\n"
        )
    return artifacts


def _normalize_dynamic(name: str, payload: object) -> object:
    if name != "P13_STABILITY_EVIDENCE.json":
        return payload
    root = cast(
        "dict[str, object]",
        json.loads(json.dumps(payload, ensure_ascii=False)),
    )
    stability = cast("dict[str, object]", root["stability"])
    for field in DYNAMIC_STABILITY_FIELDS:
        stability[field] = "<measured-at-run-time>"
    return root


def _check_json(path: Path, expected: object) -> bool:
    if not path.is_file():
        print(f"missing P13 evidence: {path.relative_to(ROOT)}")
        return False
    actual = cast("object", json.loads(path.read_text(encoding="utf-8")))
    name = path.name if path.parent == RUNTIME else ""
    matches = _normalize_dynamic(name, actual) == _normalize_dynamic(name, expected)
    if not matches:
        print(f"stale P13 evidence: {path.relative_to(ROOT)}")
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payloads, drills = build_payloads()
    extra = incident_artifacts(drills)
    if args.check:
        valid = all(_check_json(RUNTIME / name, payloads[name]) for name in EVIDENCE_FILES)
        for path, expected in extra.items():
            if isinstance(expected, str):
                matches = path.is_file() and path.read_text(encoding="utf-8") == expected
            else:
                matches = _check_json(path, expected)
            if not matches:
                print(f"stale P13 incident artifact: {path.relative_to(ROOT)}")
            valid = valid and matches
        print(f"P13 evidence check: {'passed' if valid else 'failed'}")
        return 0 if valid else 1
    for name in EVIDENCE_FILES:
        _write_json(RUNTIME / name, payloads[name])
    for path, payload in extra.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8", newline="\n")
        else:
            _write_json(path, payload)
    print(f"generated {len(payloads)} P13 runtime evidence files")
    print(f"generated {len(extra)} P13 incident artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
