"""From-scratch crypto translations evaluated through the P06 event engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal

from aegisquant.accounting.models import AccountingInstrument
from aegisquant.backtest.costs import HistoricalCostBook
from aegisquant.backtest.engine import EventBacktestEngine
from aegisquant.backtest.models import (
    BacktestOrder,
    BacktestResult,
    BacktestRunSpec,
    BarEvent,
    EngineKind,
    FundingEvent,
)
from aegisquant.backtest.policy import load_backtest_policy
from aegisquant.backtest.rules import HistoricalRuleBook
from aegisquant.data.hashing import canonical_sha256, sha256_file
from aegisquant.data.market import ContractForm, InstrumentType
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import (
    AssetId,
    BacktestEventId,
    BacktestOrderId,
    ClientOrderId,
    InstrumentId,
    OrderIntentId,
    RunId,
    StrategyId,
    StrategyVersionId,
    VenueId,
)
from aegisquant.domain.values import Money, Quantity
from aegisquant.intelligence.static_analysis.models import TranslationRecord

FIXTURE_START = datetime(2026, 9, 2, tzinfo=UTC)
BTC = AssetId("BTC")
USDT = AssetId("USDT")
VENUE = VenueId("SIM")
SPOT_ID = InstrumentId("SIM:SPOT:BTCUSDT")
PERP_ID = InstrumentId("SIM:PERP:BTCUSDT")
PERP_CONTRACT = AssetId("CONTRACT:SIM:PERP:BTCUSDT")
PRICES = ("100", "101", "103", "104", "102", "98", "97", "99", "101", "105", "106", "104")


class MigrationCandidateKind(StrEnum):
    CRYPTO_TREND_BREAKOUT = "crypto_trend_breakout"
    UTC_SESSION_REVERSAL = "utc_session_reversal"
    FUNDING_BASIS_CARRY = "funding_basis_carry"


class TranslationBacktestEvidence(DomainModel):
    candidate: MigrationCandidateKind
    run_id: str
    engine: Literal["EVENT"] = "EVENT"
    orders: int
    fills: int
    ledger_records: int
    net_pnl: str
    total_return: str
    maximum_drawdown: str
    economic_event_hash: str
    dataset_sha256: str
    config_sha256: str
    code_sha256: str
    reproduction_command: str
    source_code_reused: Literal[False] = False
    source_return_used_as_evidence: Literal[False] = False
    synthetic_fixture: Literal[True] = True
    alpha_or_profit_claim: Literal[False] = False
    live_trading_locked: Literal[True] = True


def translation_records() -> tuple[TranslationRecord, ...]:
    return (
        TranslationRecord(
            translation_id="translation-trend-breakout-v1",
            source_strategy_id="alpha-primitive-trend-breakout",
            target_strategy_id=MigrationCandidateKind.CRYPTO_TREND_BREAKOUT.value,
            source_market_concept="股票或期货趋势突破",
            crypto_mapping="高流动性现货/永续的时点可得滚动突破",
            semantic_changes=(
                "按 24/7 连续市场重定义日界",
                "仅使用当时可交易合约集合",
                "纳入交易费、价差、滑点和规则快照",
            ),
            required_rechecks=("上下币幸存者偏差", "跨所流动性", "资金费率", "拥挤反转"),
        ),
        TranslationRecord(
            translation_id="translation-utc-session-reversal-v1",
            source_strategy_id="alpha-primitive-open-close-reversal",
            target_strategy_id=MigrationCandidateKind.UTC_SESSION_REVERSAL.value,
            source_market_concept="传统市场开盘/收盘反转",
            crypto_mapping="UTC 时段、周末和资金费率结算附近的状态反转",
            semantic_changes=(
                "不假设交易所统一开盘",
                "信号在观测完成后提交并于后续事件成交",
                "时段只作为状态变量而非因果结论",
            ),
            required_rechecks=("时区稳健性", "周末状态", "延迟", "流动性分层"),
        ),
        TranslationRecord(
            translation_id="translation-funding-basis-v1",
            source_strategy_id="alpha-primitive-term-structure-carry",
            target_strategy_id=MigrationCandidateKind.FUNDING_BASIS_CARRY.value,
            source_market_concept="商品期货期限结构与展期收益",
            crypto_mapping="永续资金费率与交割合约基差的受限 Carry",
            semantic_changes=(
                "资金费率按历史结算事件入账",
                "多腿非原子成交不能假设瞬时完成",
                "保证金和强平风险独立于方向 Beta",
            ),
            required_rechecks=("资金费率修订", "借贷成本", "保证金", "多腿裸露", "交易所风险"),
        ),
    )


def _instrument(candidate: MigrationCandidateKind) -> AccountingInstrument:
    perpetual = candidate is MigrationCandidateKind.FUNDING_BASIS_CARRY
    return AccountingInstrument(
        instrument_id=PERP_ID if perpetual else SPOT_ID,
        venue="SIM",
        base_asset_id=BTC,
        quote_asset_id=USDT,
        settlement_asset_id=USDT,
        quantity_asset_id=PERP_CONTRACT if perpetual else BTC,
        instrument_type=InstrumentType.PERPETUAL if perpetual else InstrumentType.SPOT,
        contract_form=ContractForm.LINEAR if perpetual else ContractForm.SPOT,
        contract_multiplier=Decimal("1"),
    )


def _bars(instrument: AccountingInstrument) -> tuple[BarEvent, ...]:
    return tuple(
        BarEvent(
            event_id=BacktestEventId(f"p09-bar-{index}"),
            instrument_id=instrument.instrument_id,
            venue_id=VENUE,
            base_asset_id=BTC,
            quote_asset_id=USDT,
            event_time=FIXTURE_START + timedelta(hours=index),
            available_time=FIXTURE_START + timedelta(hours=index),
            open=Decimal(price),
            high=Decimal(price) + Decimal("1"),
            low=Decimal(price) - Decimal("1"),
            close=Decimal(price),
            volume=Decimal("100"),
        )
        for index, price in enumerate(PRICES)
    )


def _order(
    *,
    candidate: MigrationCandidateKind,
    instrument: AccountingInstrument,
    sequence: int,
    side: OrderSide,
    decision_bar: BarEvent,
    reduce_only: bool = False,
) -> BacktestOrder:
    submitted = decision_bar.available_time + timedelta(microseconds=1)
    prefix = candidate.value.replace("_", "-")
    return BacktestOrder(
        backtest_order_id=BacktestOrderId(f"p09-{prefix}-order-{sequence}"),
        client_order_id=ClientOrderId(f"p09-{prefix}-client-{sequence}"),
        order_intent_id=OrderIntentId(f"p09-{prefix}-intent-{sequence}"),
        instrument_id=instrument.instrument_id,
        venue_id=VENUE,
        side=side,
        order_type=OrderType.MARKET,
        quantity=Quantity(amount=Decimal("1"), asset_id=instrument.quantity_asset_id),
        time_in_force=TimeInForce.IMMEDIATE_OR_CANCEL,
        decision_time=decision_bar.available_time,
        submitted_at=submitted,
        reduce_only=reduce_only,
    )


def _orders(
    candidate: MigrationCandidateKind,
    instrument: AccountingInstrument,
    bars: tuple[BarEvent, ...],
) -> tuple[BacktestOrder, ...]:
    if candidate is MigrationCandidateKind.CRYPTO_TREND_BREAKOUT:
        decisions = ((OrderSide.BUY, 2, False), (OrderSide.SELL, 9, True))
    elif candidate is MigrationCandidateKind.UTC_SESSION_REVERSAL:
        decisions = ((OrderSide.BUY, 5, False), (OrderSide.SELL, 8, True))
    else:
        decisions = ((OrderSide.SELL, 1, False), (OrderSide.BUY, 8, True))
    return tuple(
        _order(
            candidate=candidate,
            instrument=instrument,
            sequence=sequence,
            side=side,
            decision_bar=bars[index],
            reduce_only=reduce_only,
        )
        for sequence, (side, index, reduce_only) in enumerate(decisions, start=1)
    )


def _funding_events(
    candidate: MigrationCandidateKind, instrument: AccountingInstrument
) -> tuple[FundingEvent, ...]:
    if candidate is not MigrationCandidateKind.FUNDING_BASIS_CARRY:
        return ()
    event_time = FIXTURE_START + timedelta(hours=6)
    return (
        FundingEvent(
            event_id=BacktestEventId("p09-funding-1"),
            instrument_id=instrument.instrument_id,
            venue_id=VENUE,
            base_asset_id=BTC,
            quote_asset_id=USDT,
            event_time=event_time,
            available_time=event_time,
            funding_rate=Decimal("0.0005"),
            mark_price=Decimal("97"),
        ),
    )


def _run_spec(
    *,
    candidate: MigrationCandidateKind,
    bars: tuple[BarEvent, ...],
    policy_payload: object,
) -> BacktestRunSpec:
    dataset_sha256 = canonical_sha256([item.model_dump(mode="json") for item in bars])
    config_sha256 = canonical_sha256(policy_payload)
    code_sha256 = sha256_file(Path(__file__))
    run_id = f"p09-{candidate.value}-event-v1"
    return BacktestRunSpec(
        run_id=RunId(run_id),
        engine_kind=EngineKind.EVENT,
        strategy_id=StrategyId(candidate.value),
        strategy_version_id=StrategyVersionId(f"{candidate.value}-v1"),
        dataset_sha256=dataset_sha256,
        config_sha256=config_sha256,
        code_sha256=code_sha256,
        seed=20260902,
        reporting_asset_id=USDT,
        initial_cash=Money(amount=Decimal("10000"), asset_id=USDT),
        start_time=bars[0].available_time,
        end_time=bars[-1].available_time + timedelta(hours=1),
        created_at=FIXTURE_START,
        accounting_policy_version="accounting-v1",
        cost_policy_version="p06-backtest-v1",
        rule_policy_version="p06-backtest-v1",
        reproduction_command=(
            ".venv\\Scripts\\python.exe -m scripts.generate_p09_evidence "
            f"--candidate {candidate.value}"
        ),
    )


def run_translation_candidate(
    *, candidate: MigrationCandidateKind, project_root: Path
) -> tuple[BacktestResult, TranslationBacktestEvidence]:
    """Run one deterministic candidate; the synthetic result is never an Alpha claim."""
    policy = load_backtest_policy(project_root / "configs/backtest/backtest_policy_v1.yaml")
    instrument = _instrument(candidate)
    bars = _bars(instrument)
    engine = EventBacktestEngine(
        project_root=project_root,
        cost_book=HistoricalCostBook(policy.cost_schedules),
        rule_book=HistoricalRuleBook(policy.instrument_rules),
        latency_policy=policy.latency_policy,
        margin_policies=policy.margin_policies,
    )
    spec = _run_spec(candidate=candidate, bars=bars, policy_payload=policy.model_dump(mode="json"))
    result = engine.run(
        spec=spec,
        instrument=instrument,
        market_events=bars,
        orders=_orders(candidate, instrument, bars),
        funding_events=_funding_events(candidate, instrument),
    )
    evidence = TranslationBacktestEvidence(
        candidate=candidate,
        run_id=str(spec.run_id),
        orders=len(result.orders),
        fills=len(result.fills),
        ledger_records=len(result.ledger_records),
        net_pnl=str(result.pnl_attribution[-1].net_pnl),
        total_return=str(result.metrics.total_return),
        maximum_drawdown=str(result.metrics.maximum_drawdown),
        economic_event_hash=result.economic_event_hash,
        dataset_sha256=spec.dataset_sha256,
        config_sha256=spec.config_sha256,
        code_sha256=spec.code_sha256,
        reproduction_command=spec.reproduction_command,
    )
    return result, evidence


def run_all_translation_candidates(
    project_root: Path,
) -> tuple[TranslationBacktestEvidence, ...]:
    return tuple(
        run_translation_candidate(candidate=candidate, project_root=project_root)[1]
        for candidate in MigrationCandidateKind
    )
