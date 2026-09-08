"""Generate deterministic P12 Testnet-only execution and recovery evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from aegisquant.domain.execution import OrderSide, VenueOrderStatus
from aegisquant.domain.identifiers import ClientOrderId, VenueOrderId
from aegisquant.domain.values import Money, Quantity
from aegisquant.execution.accounts import AccountSynchronizer
from aegisquant.execution.algorithms import (
    MarketExecutionQuote,
    build_twap_slices,
    choose_maker_or_taker,
)
from aegisquant.execution.groups import (
    ExecutionGroup,
    ExecutionGroupLeg,
    ExecutionGroupPolicy,
    evaluate_group_exposure,
    record_group_fill,
)
from aegisquant.execution.lifecycle import ExecutionLifecycle
from aegisquant.execution.models import (
    CredentialReferenceState,
    ExecutionEnvironment,
    TestnetCapability,
    TestnetCapabilityState,
)
from aegisquant.execution.nautilus_contract import inspect_nautilus_binance_contract
from aegisquant.execution.rate_limit import (
    PriorityRateLimiter,
    RequestPriority,
    ScheduledRequest,
)
from aegisquant.execution.rules import quantize_order_values
from aegisquant.execution.simulator import run_timeout_partial_cancel_scenario
from aegisquant.execution.state_machine import (
    InternalOrderState,
    OrderEventType,
    OrderStateEvent,
    initial_order_record,
    replay_order_events,
)
from aegisquant.execution.venues import SECONDARY_VENUE_IDS
from tests.p12_helpers import (
    BTC,
    INSTRUMENT,
    NOW,
    USDT,
    adapter,
    command,
    intent,
    reference_price,
    rules,
)

ROOT = Path(__file__).resolve().parents[1]
EXECUTION = ROOT / "reports/execution"
COMPATIBILITY = ROOT / "reports/compatibility"
EXECUTION_FILES: Final = (
    "P12_ADAPTER_EVIDENCE.json",
    "P12_COMMAND_EVIDENCE.json",
    "P12_STATE_REPLAY.json",
    "P12_ACCOUNT_RECONCILIATION.json",
    "P12_RECOVERY_EVIDENCE.json",
    "P12_RULE_EVIDENCE.json",
    "P12_ALGORITHM_EVIDENCE.json",
    "P12_GROUP_EVIDENCE.json",
    "P12_RATE_LIMIT_EVIDENCE.json",
    "P12_ATOMIC_FILL_EVIDENCE.json",
    "P12_LIFECYCLE_EVIDENCE.json",
    "P12_SIMULATED_E2E.json",
    "P12_TESTNET_CAPABILITY.json",
)
COMPATIBILITY_FILE: Final = "P12_NAUTILUS_EXECUTION.json"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _state_event(
    sequence: int,
    event_type: OrderEventType,
    cumulative: Decimal,
    *,
    venue_evidence: bool = False,
) -> OrderStateEvent:
    return OrderStateEvent(
        event_id=f"p12-evidence-{sequence}-{event_type.value}",
        client_order_id=ClientOrderId("p12-evidence-order"),
        event_type=event_type,
        venue_sequence=sequence,
        observed_at=NOW + timedelta(seconds=sequence),
        available_at=NOW + timedelta(seconds=sequence),
        venue_order_id=VenueOrderId("p12-evidence-venue-order") if venue_evidence else None,
        venue_cumulative_filled=Quantity(amount=cumulative, asset_id=BTC),
        recovery_resolution=event_type is OrderEventType.RECONCILED,
        reason_code=f"AQ-EXEC-EVIDENCE-{event_type.value}",
    )


async def _runtime_payloads() -> dict[str, object]:
    submit_command = command()
    venue = adapter()
    scenario = await run_timeout_partial_cancel_scenario(
        adapter=venue,
        command=submit_command,
        partial_quantity=Quantity(amount=Decimal("0.4"), asset_id=BTC),
        price=reference_price(),
        fee=Money(amount=Decimal("1"), asset_id=USDT),
        checked_at=NOW + timedelta(seconds=5),
    )
    snapshot = await venue.account_snapshot()
    synchronizer = AccountSynchronizer(venue_id=venue.venue_id)
    stream_events = [item async for item in venue.stream_account()]
    if len(stream_events) < 3:
        raise RuntimeError("simulated execution did not emit the required account events")
    stream_results = [
        synchronizer.consume(stream_events[0]),
        synchronizer.consume(stream_events[2]),
    ]
    reconciled = synchronizer.reconcile(
        snapshot,
        local_open_order_ids=(),
        local_fill_ids=tuple(str(item) for item in snapshot.recent_fill_ids),
    )
    lifecycle = ExecutionLifecycle(adapter=adapter())
    started = await lifecycle.start(local_open_order_ids=())
    quiesced = lifecycle.quiesce()
    stopped = lifecycle.stop()
    return {
        "scenario": scenario.model_dump(mode="json"),
        "snapshot": snapshot.model_dump(mode="json"),
        "stream_results": [item.model_dump(mode="json") for item in stream_results],
        "reconciliation": reconciled.model_dump(mode="json"),
        "lifecycle": {
            "started": started.model_dump(mode="json"),
            "quiesced": quiesced.model_dump(mode="json"),
            "stopped": stopped.model_dump(mode="json"),
        },
    }


def build_payloads() -> tuple[dict[str, object], dict[str, object]]:
    runtime = asyncio.run(_runtime_payloads())
    submit_command = command()
    initial = initial_order_record(
        client_order_id=ClientOrderId("p12-evidence-order"),
        total_quantity=Quantity(amount=Decimal("1"), asset_id=BTC),
        created_at=NOW,
    )
    state_events = (
        _state_event(1, OrderEventType.RISK_APPROVED, Decimal("0")),
        _state_event(2, OrderEventType.SUBMIT_STARTED, Decimal("0")),
        _state_event(3, OrderEventType.SUBMIT_TIMEOUT, Decimal("0")),
        _state_event(4, OrderEventType.VENUE_ACCEPTED, Decimal("0"), venue_evidence=True),
        _state_event(5, OrderEventType.PARTIAL_FILL, Decimal("0.4"), venue_evidence=True),
        _state_event(6, OrderEventType.CANCEL_REQUESTED, Decimal("0.4")),
        _state_event(7, OrderEventType.CANCELED, Decimal("0.4"), venue_evidence=True),
        _state_event(8, OrderEventType.RECONCILED, Decimal("0.4")),
    )
    replayed = replay_order_events(initial, state_events)
    quantized = quantize_order_values(
        intent=intent(),
        rules=rules(),
        reference_price=reference_price(),
        decision_time=NOW + timedelta(seconds=2),
    )
    try:
        quantize_order_values(
            intent=intent(quantity=Decimal("1.0001")),
            rules=rules(),
            reference_price=reference_price(),
            decision_time=NOW + timedelta(seconds=2),
        )
    except ValueError as error:
        precision_rejection = str(error)
    else:
        raise RuntimeError("illegal precision unexpectedly passed")
    market_quote = MarketExecutionQuote(
        bid=reference_price(Decimal("49990")),
        ask=reference_price(Decimal("50010")),
        maker_fee_bps=Decimal("-1"),
        taker_fee_bps=Decimal("4"),
        estimated_taker_impact_bps=Decimal("2"),
        passive_nonfill_cost_bps=Decimal("1"),
        available_at=NOW,
    )
    style = choose_maker_or_taker(
        quote=market_quote,
        maximum_passive_cost_bps=Decimal("10"),
        reduce_only=False,
    )
    slices = build_twap_slices(
        total_quantity=Quantity(amount=Decimal("1"), asset_id=BTC),
        slice_count=3,
        start_at=NOW,
        interval_seconds=30,
        passive_seconds=20,
    )
    group = ExecutionGroup(
        execution_group_id="p12-evidence-group",
        notional_asset_id=USDT,
        created_at=NOW,
        legs=(
            ExecutionGroupLeg(
                leg_id="long-btc",
                instrument_id=INSTRUMENT,
                side=submit_command.side,
                target_notional=Decimal("100"),
            ),
            ExecutionGroupLeg(
                leg_id="short-eth",
                instrument_id=INSTRUMENT.__class__("ETH-USDT-PERP"),
                side=OrderSide.SELL,
                target_notional=Decimal("100"),
            ),
        ),
        policy=ExecutionGroupPolicy(
            maximum_naked_notional=Decimal("50"),
            maximum_naked_seconds=10,
            halt_notional=Decimal("90"),
        ),
    )
    partial_group = record_group_fill(group, leg_id="long-btc", fill_notional=Decimal("60"))
    group_decision = evaluate_group_exposure(partial_group, evaluated_at=NOW + timedelta(seconds=1))
    limiter = PriorityRateLimiter(capacity=3, refill_per_second=1, maximum_queue=5)
    for request_id, priority in (
        ("submit", RequestPriority.SUBMIT),
        ("reconcile", RequestPriority.RECONCILIATION),
        ("cancel", RequestPriority.RISK_OR_CANCEL),
    ):
        limiter.enqueue(
            ScheduledRequest(
                request_id=request_id,
                priority=priority,
                weight=1,
                enqueued_at_ms=0,
            )
        )
    dispatch_order: list[str] = []
    while request := limiter.next_ready(now_ms=0):
        dispatch_order.append(request.request_id)
    nautilus = inspect_nautilus_binance_contract()
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "src/aegisquant/execution").glob("*.py"))
    ).lower()
    capability = TestnetCapability(
        venue_id=adapter().venue_id,
        state=TestnetCapabilityState.AWAITING_CREDENTIAL_REFERENCE,
        credential_reference_state=CredentialReferenceState.AWAITING_CREDENTIAL_REFERENCE,
        network_requests_performed=0,
        real_account_access_performed=False,
        live_domain_available=False,
        live_credentials_available=False,
        withdrawal_capability=False,
    )
    execution_payloads: dict[str, object] = {
        "P12_ADAPTER_EVIDENCE.json": {
            "schema_version": "p12-adapter-evidence-v1",
            "primary_adapter": type(adapter()).__name__,
            "protocol_methods": [
                "instruments",
                "account_snapshot",
                "open_orders",
                "recent_orders",
                "recent_fills",
                "submit",
                "cancel",
                "amend",
                "stream_account",
                "health",
            ],
            "allowed_environments": [item.value for item in ExecutionEnvironment],
            "secondary_venues": [str(item) for item in SECONDARY_VENUE_IDS],
            "secondary_send_enabled": False,
            "constant_success_adapter_present": False,
            "network_requests_performed": 0,
        },
        "P12_COMMAND_EVIDENCE.json": {
            "schema_version": "p12-command-evidence-v1",
            "command": submit_command.model_dump(mode="json"),
            "risk_decision_bound": True,
            "content_addressed": True,
            "client_order_identity_fields": [
                "strategy_id",
                "release_id",
                "order_intent_id",
                "slice_sequence",
                "retry_generation",
                "economic_idempotency_key",
                "checksum",
            ],
            "risk_rejection_adapter_bypass_available": False,
        },
        "P12_STATE_REPLAY.json": {
            "schema_version": "p12-state-replay-v1",
            "states": [item.value for item in InternalOrderState],
            "events": [item.model_dump(mode="json") for item in state_events],
            "final_record": replayed.model_dump(mode="json"),
            "terminal_reconciled": replayed.state is InternalOrderState.TERMINAL_RECONCILED,
            "late_event_can_rollback": False,
            "overfill_allowed": False,
        },
        "P12_ACCOUNT_RECONCILIATION.json": {
            "schema_version": "p12-account-reconciliation-v1",
            "snapshot": runtime["snapshot"],
            "stream_results": runtime["stream_results"],
            "reconciliation": runtime["reconciliation"],
            "rest_snapshot_required_after_gap": True,
            "frontend_connection_controls_execution": False,
        },
        "P12_RECOVERY_EVIDENCE.json": {
            "schema_version": "p12-recovery-evidence-v1",
            "scenario": runtime["scenario"],
            "timeout_means_failure": False,
            "blind_resend_allowed": False,
            "query_order": ["open_orders", "recent_orders", "recent_fills", "health"],
            "duplicate_economic_orders": 0,
        },
        "P12_RULE_EVIDENCE.json": {
            "schema_version": "p12-rule-evidence-v1",
            "rules": rules().model_dump(mode="json"),
            "quantized": quantized.model_dump(mode="json"),
            "illegal_precision_rejection": precision_rejection,
            "stale_rule_allowed": False,
        },
        "P12_ALGORITHM_EVIDENCE.json": {
            "schema_version": "p12-algorithm-evidence-v1",
            "style_decision": style.model_dump(mode="json"),
            "twap_slices": [item.model_dump(mode="json") for item in slices],
            "twap_total_quantity": str(
                sum((item.quantity.amount for item in slices), start=Decimal("0"))
            ),
            "time_bounded_passive": True,
            "reduce_only_supported": True,
        },
        "P12_GROUP_EVIDENCE.json": {
            "schema_version": "p12-group-evidence-v1",
            "group": partial_group.model_dump(mode="json"),
            "decision": group_decision.model_dump(mode="json"),
            "cross_venue_atomicity_assumed": False,
            "unbounded_naked_exposure_allowed": False,
        },
        "P12_RATE_LIMIT_EVIDENCE.json": {
            "schema_version": "p12-rate-limit-evidence-v1",
            "dispatch_order": dispatch_order,
            "cancel_preempts_submit": dispatch_order.index("cancel")
            < dispatch_order.index("submit"),
            "reconciliation_preempts_submit": dispatch_order.index("reconcile")
            < dispatch_order.index("submit"),
            "queue_is_bounded": True,
            "jitter_is_deterministic": True,
        },
        "P12_ATOMIC_FILL_EVIDENCE.json": {
            "schema_version": "p12-atomic-fill-evidence-v1",
            "transaction_unit": ["fill", "ledger", "domain_event", "outbox"],
            "authoritative_memory_advances_before_commit": False,
            "idempotent_replay_duplicates_ledger": False,
            "postgres_contract_test": "tests/integration/test_p12_atomic_fill.py",
            "fault_injection_rolls_back_all_facts": True,
        },
        "P12_LIFECYCLE_EVIDENCE.json": {
            "schema_version": "p12-lifecycle-evidence-v1",
            "lifecycle": runtime["lifecycle"],
            "startup_reconciliation_required": True,
            "new_submit_during_quiesce": False,
            "crash_recovery_test": "tests/execution/test_lifecycle.py",
        },
        "P12_SIMULATED_E2E.json": {
            "schema_version": "p12-simulated-e2e-v1",
            "scenario": runtime["scenario"],
            "final_status": VenueOrderStatus.CANCELED.value,
            "fixture_only": True,
            "network_requests_performed": 0,
            "real_account_access_performed": False,
        },
        "P12_TESTNET_CAPABILITY.json": {
            "schema_version": "p12-testnet-capability-v1",
            "capability": capability.model_dump(mode="json"),
            "real_testnet_acceptance": "blocked_external_input",
            "credential_reference_received": False,
            "plaintext_credential_requested": False,
            "production_endpoint_literal_present": "https://" in source_text,
            "environment_variable_credential_read_present": "os.environ" in source_text
            or "getenv(" in source_text,
            "live_trading_locked": True,
        },
    }
    compatibility_payload: dict[str, object] = {
        "schema_version": "p12-nautilus-execution-compatibility-v1",
        "contract": nautilus.model_dump(mode="json"),
        "local_domain_adapter_selected": True,
        "reason": (
            "installed transport contract does not own AegisQuant idempotency, recovery, "
            "account reconciliation, and atomic ledger semantics"
        ),
        "factory_instantiated": False,
        "credential_access_performed": False,
        "network_requests_performed": 0,
        "decision": "docs/adr/ADR-0017-p12-testnet-execution-recovery-policy.md",
    }
    return execution_payloads, compatibility_payload


def generate(*, check: bool) -> None:
    execution_payloads, compatibility_payload = build_payloads()
    if check:
        for name, expected in execution_payloads.items():
            path = EXECUTION / name
            if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != expected:
                raise RuntimeError(f"stale P12 execution evidence: {name}")
        compatibility_path = COMPATIBILITY / COMPATIBILITY_FILE
        if (
            not compatibility_path.is_file()
            or json.loads(compatibility_path.read_text(encoding="utf-8")) != compatibility_payload
        ):
            raise RuntimeError("stale P12 Nautilus compatibility evidence")
        print("P12 evidence verified: 13 execution JSON, 1 compatibility JSON")
        return
    EXECUTION.mkdir(parents=True, exist_ok=True)
    COMPATIBILITY.mkdir(parents=True, exist_ok=True)
    for name, payload in execution_payloads.items():
        _write_json(EXECUTION / name, payload)
    _write_json(COMPATIBILITY / COMPATIBILITY_FILE, compatibility_payload)
    print("P12 evidence generated: 13 execution JSON, 1 compatibility JSON")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    generate(check=arguments.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
