"""Deterministic, non-network P12 execution fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aegisquant.domain.execution import OrderIntent, OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import (
    AccountId,
    AssetId,
    IdempotencyKey,
    InstrumentId,
    OrderIntentId,
    ProposalId,
    RiskDecisionId,
    StrategyId,
    VenueId,
)
from aegisquant.domain.values import Price, Quantity
from aegisquant.execution.accounts import AccountBalance
from aegisquant.execution.adapter import SimulatedBinanceTestnetAdapter
from aegisquant.execution.commands import SubmitOrderCommand, translate_order_intent
from aegisquant.execution.models import ExecutionEnvironment
from aegisquant.execution.rules import (
    InstrumentRuleSnapshot,
    MarginMode,
    PositionMode,
    TradingStatus,
)
from aegisquant.risk.models import (
    ApprovedTarget,
    RiskDecision,
    RiskDecisionStatus,
    RiskState,
)

NOW = datetime(2026, 9, 1, 20, 0, tzinfo=UTC)
BTC = AssetId("BTC")
USDT = AssetId("USDT")
INSTRUMENT = InstrumentId("BTC-USDT-PERP")
STRATEGY = StrategyId("strategy-p12")
ACCOUNT = AccountId("account-p12-simulated")


def decision() -> RiskDecision:
    return RiskDecision(
        risk_decision_id=RiskDecisionId("risk-p12-approved"),
        proposal_id=ProposalId("proposal-p12"),
        proposal_sha256="1" * 64,
        snapshot_id="snapshot-p12",
        snapshot_sha256="2" * 64,
        policy_version="p12-risk-v1",
        policy_sha256="3" * 64,
        decided_at=NOW,
        valid_until=NOW + timedelta(minutes=5),
        status=RiskDecisionStatus.APPROVED,
        state=RiskState.NORMAL,
        new_risk_allowed=True,
        approved_targets=(
            ApprovedTarget(
                instrument_id=INSTRUMENT,
                asset_id=BTC,
                strategy_id=STRATEGY,
                account_id=ACCOUNT,
                current_weight=Decimal("0"),
                proposed_target_weight=Decimal("0.1"),
                approved_target_weight=Decimal("0.1"),
                approved_delta_weight=Decimal("0.1"),
            ),
        ),
        reason_codes=("AQ-RISK-P12-FIXTURE-APPROVED",),
    )


def intent(
    *,
    quantity: Decimal = Decimal("1"),
    order_type: OrderType = OrderType.LIMIT,
    limit: Decimal | None = Decimal("50000"),
) -> OrderIntent:
    return OrderIntent(
        order_intent_id=OrderIntentId("intent-p12"),
        risk_decision_id=RiskDecisionId("risk-p12-approved"),
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=Quantity(amount=quantity, asset_id=BTC),
        limit_price=(
            Price(amount=limit, base_asset_id=BTC, quote_asset_id=USDT)
            if limit is not None
            else None
        ),
        time_in_force=TimeInForce.GOOD_TIL_CANCELED,
        reduce_only=False,
        created_at=NOW + timedelta(seconds=1),
        valid_until=NOW + timedelta(minutes=2),
        idempotency_key=IdempotencyKey("economic-intent-p12"),
    )


def reference_price(amount: Decimal = Decimal("50000")) -> Price:
    return Price(amount=amount, base_asset_id=BTC, quote_asset_id=USDT)


def rules(*, venue_id: VenueId | None = None) -> InstrumentRuleSnapshot:
    venue = venue_id or SimulatedBinanceTestnetAdapter.venue_id
    return InstrumentRuleSnapshot(
        rule_version="binance-test-rules-v1",
        venue_id=venue,
        instrument_id=INSTRUMENT,
        price_tick=Decimal("0.10"),
        quantity_step=Decimal("0.001"),
        minimum_quantity=Decimal("0.001"),
        maximum_quantity=Decimal("100"),
        minimum_notional=Decimal("10"),
        supported_order_types=(OrderType.MARKET, OrderType.LIMIT),
        position_mode=PositionMode.ONE_WAY,
        margin_mode=MarginMode.CROSS,
        trading_status=TradingStatus.TRADING,
        price_protection_bps=Decimal("100"),
        self_trade_prevention_modes=("EXPIRE_MAKER",),
        request_weight=1,
        available_at=NOW,
        valid_until=NOW + timedelta(hours=1),
    )


def command(
    *,
    source_intent: OrderIntent | None = None,
    retry_generation: int = 0,
) -> SubmitOrderCommand:
    return translate_order_intent(
        intent=source_intent or intent(),
        decision=decision(),
        strategy_id=STRATEGY,
        release_id="release-p12-v1",
        venue_id=SimulatedBinanceTestnetAdapter.venue_id,
        environment=ExecutionEnvironment.SIMULATED,
        rules=rules(),
        reference_price=reference_price(),
        issued_at=NOW + timedelta(seconds=2),
        retry_generation=retry_generation,
    )


def adapter() -> SimulatedBinanceTestnetAdapter:
    return SimulatedBinanceTestnetAdapter(
        rules=(rules(),),
        balances=(
            AccountBalance(
                asset_id=USDT,
                total=Decimal("100000"),
                available=Decimal("100000"),
            ),
        ),
        clock=lambda: NOW + timedelta(seconds=3),
    )
