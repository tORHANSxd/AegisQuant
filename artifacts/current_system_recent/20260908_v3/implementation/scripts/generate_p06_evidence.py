"""Generate deterministic P06 implementation evidence and the golden artifact set."""

from __future__ import annotations

import argparse
from datetime import timedelta
from decimal import Decimal

from aegisquant.backtest.artifacts import write_backtest_artifacts
from aegisquant.backtest.costs import (
    borrow_interest_cost,
    execution_price_and_cost,
    funding_cost,
    settlement_fee,
)
from aegisquant.backtest.margin import (
    create_liquidation_order,
    evaluate_margin,
    liquidation_instruction,
)
from aegisquant.backtest.models import (
    BacktestResult,
    EngineKind,
    FaultType,
    FaultWindow,
    FillPrecision,
    FillSlice,
    FundingEvent,
    LiquidityRole,
    MultiLegPlan,
    StressScenario,
    StressType,
)
from aegisquant.backtest.nautilus_contract import verify_nautilus_contract
from aegisquant.backtest.rules import HistoricalRuleBook
from aegisquant.backtest.stress import apply_stress
from aegisquant.backtest.vector import VectorBacktestEngine, buy_and_hold_benchmark
from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256
from aegisquant.domain.accounting import PostingSide
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import (
    BacktestEventId,
    InstrumentRuleId,
    MultiLegPlanId,
    StressScenarioId,
)
from tests.p06.helpers import (
    BTC,
    NOW,
    PERP_ID,
    ROOT,
    USDT,
    VENUE,
    bars,
    engine,
    l2_book,
    order,
    perp_bars,
    perp_instrument,
    perp_order,
    policy,
    run_spec,
    spot_instrument,
    zero_cost_policy,
)

DATA_REPORTS = ROOT / "reports/data"
BACKTEST_REPORT = ROOT / "reports/backtests/p06-golden"


def _write_json(name: str, payload: object) -> None:
    DATA_REPORTS.mkdir(parents=True, exist_ok=True)
    (DATA_REPORTS / name).write_bytes(canonical_json_bytes(payload))


def _ledger_balanced(result: BacktestResult) -> bool:
    for record in result.ledger_records:
        balances: dict[str, Decimal] = {}
        for posting in record.journal_entry.postings:
            sign = Decimal("1") if posting.side is PostingSide.DEBIT else Decimal("-1")
            asset = str(posting.amount.asset_id)
            balances[asset] = balances.get(asset, Decimal("0")) + sign * posting.amount.amount
        if any(value != 0 for value in balances.values()):
            return False
    return True


def _golden_cost_evidence() -> dict[str, object]:
    selected = policy()
    candidate = order(sequence=1, side=OrderSide.BUY, quantity="10")
    fill_slice = FillSlice(
        quantity=Decimal("10"),
        reference_price=Decimal("100"),
        available_liquidity=Decimal("20"),
        precision=FillPrecision.L2_DEPTH,
        liquidity_role=LiquidityRole.TAKER,
        source_event_id=BacktestEventId("cost-golden-event"),
        event_time=NOW,
        available_time=NOW,
    )
    execution_price, cost = execution_price_and_cost(
        order=candidate,
        fill_slice=fill_slice,
        schedule=selected.cost_schedules[0],
        base_asset_id=BTC,
        quote_asset_id=USDT,
    )
    margin = evaluate_margin(
        policy=selected.margin_policies[0],
        signed_quantity=Decimal("10"),
        entry_price=Decimal("100"),
        mark_price=Decimal("80"),
        collateral=Decimal("30"),
    )
    instruction = liquidation_instruction(
        evaluation=margin,
        policy=selected.margin_policies[0],
    )
    liquidation_order = create_liquidation_order(
        instruction=instruction,
        instrument=perp_instrument(),
        venue_id=VENUE,
        decision_time=NOW,
        identity="margin-golden",
    )
    opening_order = perp_order(
        sequence=1,
        side=OrderSide.BUY,
        quantity="10",
        submitted_at=NOW + timedelta(microseconds=1),
    )
    ledger_liquidation_order = create_liquidation_order(
        instruction=instruction,
        instrument=perp_instrument(),
        venue_id=VENUE,
        decision_time=NOW + timedelta(seconds=2, microseconds=1),
        identity="ledger-golden",
    )
    liquidation_result = engine().run(
        spec=run_spec(run_id="p06-liquidation-ledger-evidence"),
        instrument=perp_instrument(),
        market_events=perp_bars(),
        orders=(opening_order, ledger_liquidation_order),
    )
    payload: dict[str, object] = {
        "schema_version": "p06-golden-results-v1",
        "execution_cost": {
            "quantity": "10",
            "reference_price": "100",
            "execution_price": str(execution_price.amount),
            "fee": str(cost.fee),
            "spread": str(cost.spread),
            "slippage": str(cost.slippage),
            "impact": str(cost.impact),
            "total": str(cost.total),
            "hand_calculation_matched": cost.total == Decimal("0.700100"),
        },
        "funding": str(
            funding_cost(
                signed_quantity=Decimal("2"),
                mark_price=Decimal("100"),
                funding_rate=Decimal("0.0001"),
            )
        ),
        "borrow_interest_one_year": str(
            borrow_interest_cost(
                borrowed_notional=Decimal("1000"),
                annual_rate=Decimal("0.10"),
                elapsed_seconds=31_557_600,
            )
        ),
        "settlement_fee": str(
            settlement_fee(notional=Decimal("1000"), schedule=selected.cost_schedules[1])
        ),
        "margin": margin.model_dump(mode="json"),
        "liquidation": instruction.model_dump(mode="json"),
        "liquidation_order": liquidation_order.model_dump(mode="json"),
        "liquidation_ledger": {
            "order_statuses": [item.status.value for item in liquidation_result.orders],
            "final_position_quantity": str(liquidation_result.positions[0].quantity),
            "ledger_entry_count": len(liquidation_result.ledger_records),
            "ledger_balanced": _ledger_balanced(liquidation_result),
            "economic_event_hash": liquidation_result.economic_event_hash,
        },
        "live_trading_locked": True,
        "real_account_connected": False,
    }
    return payload


def _failure_evidence() -> dict[str, object]:
    timeout_order = order(sequence=20, side=OrderSide.BUY)
    timeout = FaultWindow(
        fault_type=FaultType.REQUEST_TIMEOUT,
        venue_id=VENUE,
        starts_at=NOW,
        ends_at=NOW + timedelta(seconds=2),
        evidence="recorded deterministic request timeout",
    )
    timeout_result = engine().run(
        spec=run_spec(run_id="p06-evidence-timeout"),
        instrument=spot_instrument(),
        market_events=bars(),
        orders=(timeout_order,),
        faults=(timeout,),
    )

    plan_id = MultiLegPlanId("p06-evidence-failed-leg")
    first = order(sequence=21, side=OrderSide.BUY, quantity="1").model_copy(
        update={"multi_leg_plan_id": plan_id, "leg_index": 0}
    )
    second = order(
        sequence=22,
        side=OrderSide.BUY,
        quantity="2",
        submitted_at=NOW + timedelta(microseconds=2),
    ).model_copy(update={"multi_leg_plan_id": plan_id, "leg_index": 1})
    plan = MultiLegPlan(
        multi_leg_plan_id=plan_id,
        orders=(first, second),
        maximum_exposure_ns=2_000_000_000,
    )
    leg_result = engine().run(
        spec=run_spec(run_id="p06-evidence-failed-leg"),
        instrument=spot_instrument(),
        market_events=(bars(2, volume="1")[1],),
        orders=(first, second),
        multi_leg_plans=(plan,),
        failed_leg_indices={plan_id: 1},
    )
    return {
        "schema_version": "p06-failure-evidence-v1",
        "timeout": {
            "status": timeout_result.orders[0].status.value,
            "unknown_reason": timeout_result.orders[0].unknown_reason,
            "recovery_evidence": list(timeout_result.orders[0].recovery_evidence),
            "fill_count": len(timeout_result.fills),
            "ledger_balanced": _ledger_balanced(timeout_result),
        },
        "partial_and_multileg_failure": {
            "statuses": [item.status.value for item in leg_result.orders],
            "filled_quantities": [
                str(item.cumulative_filled_quantity) for item in leg_result.orders
            ],
            "exposure": leg_result.multi_leg_exposures[0].model_dump(mode="json"),
            "ledger_balanced": _ledger_balanced(leg_result),
            "economic_event_hash": leg_result.economic_event_hash,
        },
        "live_trading_locked": True,
    }


def _rule_evidence() -> dict[str, object]:
    base = policy().instrument_rules[0]
    cutoff = NOW + timedelta(seconds=2)
    earlier = base.model_copy(
        update={
            "instrument_rule_id": InstrumentRuleId("evidence-rule-before"),
            "version": "rule-before-halt",
            "effective_to": cutoff,
            "trading_enabled": True,
        }
    )
    later = base.model_copy(
        update={
            "instrument_rule_id": InstrumentRuleId("evidence-rule-after"),
            "version": "rule-after-halt",
            "effective_from": cutoff,
            "effective_to": None,
            "trading_enabled": False,
        }
    )
    rule_book = HistoricalRuleBook((earlier, later))
    before = rule_book.validate_order(
        order(
            sequence=30,
            side=OrderSide.BUY,
            submitted_at=cutoff - timedelta(microseconds=1),
        ),
        reference_price=Decimal("100"),
    )
    after = rule_book.validate_order(
        order(sequence=31, side=OrderSide.BUY, submitted_at=cutoff),
        reference_price=Decimal("100"),
    )
    return {
        "schema_version": "p06-rules-evidence-v1",
        "cutoff": cutoff.isoformat(),
        "before": before.model_dump(mode="json"),
        "after": after.model_dump(mode="json"),
        "legality_changed": before.valid and not after.valid,
        "missing_rule_behavior": "fail_closed",
    }


def _stress_evidence() -> dict[str, object]:
    selected = policy()
    delayed = bars()[1].model_copy(
        update={"available_time": bars()[1].event_time + timedelta(milliseconds=1)}
    )
    market_events = (delayed, l2_book(sequence=2))
    funding = FundingEvent(
        event_id=BacktestEventId("evidence-funding-stress"),
        instrument_id=PERP_ID,
        venue_id=VENUE,
        base_asset_id=BTC,
        quote_asset_id=USDT,
        event_time=NOW + timedelta(seconds=1),
        available_time=NOW + timedelta(seconds=1),
        funding_rate=Decimal("0.0001"),
        mark_price=Decimal("100"),
    )
    scenarios: dict[str, object] = {}
    for stress_type in StressType:
        multiplier = (
            Decimal("0.8")
            if stress_type
            in {
                StressType.CORRELATION_SHOCK,
                StressType.LIQUIDITY_FACTOR,
                StressType.STABLECOIN_DEPEG,
            }
            else Decimal("2")
        )
        scenario = StressScenario(
            stress_scenario_id=StressScenarioId(f"evidence-{stress_type.value.lower()}"),
            stress_type=stress_type,
            multiplier=multiplier,
            starts_at=NOW,
            ends_at=NOW + timedelta(seconds=4),
            source="P06 deterministic stress evidence",
        )
        application = apply_stress(
            scenario=scenario,
            market_events=market_events,
            funding_events=(funding,),
            cost_schedules=selected.cost_schedules,
            latency_policy=selected.latency_policy,
        )
        scenarios[stress_type.value] = {
            "application_sha256": canonical_sha256(application.model_dump(mode="json")),
            "fault_count": len(application.faults),
            "model_available": application.model_available,
            "strategy_enabled": application.strategy_enabled,
            "correlation_target": (
                str(application.correlation_target)
                if application.correlation_target is not None
                else None
            ),
            "historical_replay_required": application.historical_replay_required,
        }
    return {
        "schema_version": "p06-stress-evidence-v1",
        "scenario_count": len(scenarios),
        "required_scenario_count": len(StressType),
        "scenarios": scenarios,
        "seed": 20260901,
    }


def generate(run_id: str) -> None:
    values = bars()
    instrument = spot_instrument()
    orders = buy_and_hold_benchmark(
        bars=values,
        instrument=instrument,
        quantity=Decimal("1"),
    )
    golden = engine().run(
        spec=run_spec(EngineKind.EVENT, run_id=run_id),
        instrument=instrument,
        market_events=values,
        orders=orders,
    )
    artifacts = write_backtest_artifacts(golden, BACKTEST_REPORT)

    zero_engine = engine(zero_cost_policy())
    event_consistency = zero_engine.run(
        spec=run_spec(EngineKind.EVENT, run_id="p06-consistency-event"),
        instrument=instrument,
        market_events=values,
        orders=orders,
    )
    vector_consistency = VectorBacktestEngine(zero_engine).run(
        spec=run_spec(EngineKind.VECTOR, run_id="p06-consistency-vector"),
        instrument=instrument,
        bars=values,
        orders=orders,
    )
    consistency = {
        "schema_version": "p06-consistency-evidence-v1",
        "zero_cost": True,
        "immediate_fill": True,
        "fills_equal": event_consistency.fills == vector_consistency.fills,
        "positions_equal": event_consistency.positions == vector_consistency.positions,
        "equity_equal": event_consistency.equity_curve == vector_consistency.equity_curve,
        "event_hash": event_consistency.economic_event_hash,
        "vector_hash": vector_consistency.economic_event_hash,
        "matched": (
            event_consistency.economic_event_hash == vector_consistency.economic_event_hash
        ),
    }
    replay_hashes = [
        zero_engine.run(
            spec=run_spec(EngineKind.EVENT, run_id="p06-replay-evidence"),
            instrument=instrument,
            market_events=values,
            orders=orders,
        ).economic_event_hash
        for _ in range(5)
    ]
    replay = {
        "schema_version": "p06-replay-evidence-v1",
        "replays": len(replay_hashes),
        "unique_hashes": len(set(replay_hashes)),
        "economic_event_hash": replay_hashes[0],
        "deterministic": len(set(replay_hashes)) == 1,
        "seed": 20260901,
    }
    golden_costs = _golden_cost_evidence()
    nautilus = verify_nautilus_contract("1.231.0")
    nautilus_payload = nautilus.model_dump(mode="json") | {
        "schema_version": "p06-nautilus-contract-v1",
        "authoritative_accounting_engine": "AegisQuant Decimal LedgerEngine",
        "official_sources": [
            "https://pypi.org/project/nautilus-trader/",
            "https://nautilustrader.io/docs/latest/concepts/backtesting/",
            "https://nautilustrader.io/docs/nightly/concepts/backtesting/fill-models/",
            "https://nautilustrader.io/docs/latest/concepts/backtesting/execution-flow/",
        ],
    }

    _write_json("P06_NAUTILUS_CONTRACT.json", nautilus_payload)
    _write_json("P06_GOLDEN_RESULTS.json", golden_costs)
    _write_json("P06_FAILURE_EVIDENCE.json", _failure_evidence())
    _write_json("P06_RULES_EVIDENCE.json", _rule_evidence())
    _write_json("P06_CONSISTENCY_EVIDENCE.json", consistency)
    _write_json("P06_STRESS_EVIDENCE.json", _stress_evidence())
    _write_json("P06_REPLAY_EVIDENCE.json", replay)
    _write_json(
        "P06_BACKTEST_EVIDENCE.json",
        {
            "schema_version": "p06-backtest-evidence-v1",
            "run_id": run_id,
            "engine_kind": golden.engine_kind.value,
            "economic_event_hash": golden.economic_event_hash,
            "orders": len(golden.orders),
            "fills": len(golden.fills),
            "ledger_entries": len(golden.ledger_records),
            "ledger_balanced": _ledger_balanced(golden),
            "events_processed": golden.events_processed,
            "final_equity": str(golden.equity_curve[-1].equity),
            "artifact_sha256": artifacts.sha256_by_name,
            "artifact_count": len(artifacts.paths),
            "vector_event_consistency": consistency["matched"],
            "deterministic_replay": replay["deterministic"],
            "nautilus_contract_deterministic": nautilus.deterministic,
            "live_trading_locked": True,
            "real_account_connected": False,
            "authentication_used": False,
            "order_transmission_used": False,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="p06-golden")
    arguments = parser.parse_args()
    generate(arguments.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
