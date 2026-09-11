"""Thin, proposal-only shared-capital bridge over the existing ledger and risk modules."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal
from itertools import pairwise
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from aegisquant.accounting.ledger import LedgerEngine
from aegisquant.accounting.models import (
    AccountingInstrument,
    AccountRole,
    FxRate,
    ValuationQuote,
    ValuationSnapshot,
)
from aegisquant.data.hashing import canonical_sha256
from aegisquant.data.market import InstrumentType
from aegisquant.domain.accounting import LotSide
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import (
    AssetId,
    InstrumentId,
    ProposalId,
    RiskDecisionId,
    ValuationSnapshotId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    NonNegativeDecimal,
    PositiveDecimal,
    UnitInterval,
    canonical_result,
)
from aegisquant.execution.accounts import AccountBalance
from aegisquant.portfolio.models import (
    CovarianceEstimate,
    CovarianceInputContract,
    ExposureConstraint,
    ExposureDimension,
    PortfolioConstructionPolicy,
    PortfolioProposal,
    RiskRegime,
    SignalInput,
)
from aegisquant.portfolio.optimizer import (
    _capacity_weight,  # pyright: ignore[reportPrivateUsage] -- reuse the existing capacity curve.
    _dimension_key,  # pyright: ignore[reportPrivateUsage] -- one definition of group membership.
    _portfolio_variance,  # pyright: ignore[reportPrivateUsage] -- reuse Decimal risk arithmetic.
    build_portfolio_proposal,
    target_quantity_adjustment,
)
from aegisquant.portfolio.risk_estimation import estimate_covariance
from aegisquant.research.validation.evidence_contract import Row, decimal, require, utc
from aegisquant.risk.engine import evaluate_circuit_breakers, evaluate_portfolio_proposal
from aegisquant.risk.models import (
    RiskDecision,
    RiskDecisionStatus,
    RiskEvent,
    RiskSnapshot,
    RiskState,
)
from aegisquant.risk.policy import SignedRiskPolicy, verify_signed_risk_policy
from aegisquant.risk.state_machine import SAFETY_RANK, transition_risk_state
from aegisquant.risk.stress import PortfolioStressScenario, run_portfolio_stress

ZERO, ONE = Decimal("0"), Decimal("1")
FILES = (
    "src/aegisquant/portfolio/risk_estimation.py",
    "src/aegisquant/portfolio/models.py",
    "src/aegisquant/portfolio/optimizer.py",
    "src/aegisquant/accounting/ledger.py",
    "src/aegisquant/research/validation/portfolio_replay.py",
    "scripts/run_alpha_v5_portfolio_diagnostics.py",
    "configs/research/alpha_v5_portfolio_contract.yaml",
    "tests/alpha_v5/test_portfolio_contract.py",
    "docs/research/alpha_v5_portfolio_contract.md",
)


def daily_covariance_from_rows(
    rows: Sequence[Row], *, asset_ids: tuple[AssetId, ...], decision_time: UtcDateTime
) -> CovarianceEstimate:
    """Fixed 90 complete UTC days, 30-day EWMA, 20% shrinkage; supplied observations only."""
    decision = utc(decision_time)
    end = decision.replace(hour=0, minute=0, second=0, microsecond=0)
    boundaries = tuple(end - timedelta(days=i) for i in range(89, -1, -1))
    assets = tuple(sorted(asset_ids, key=str))
    require(len(set(assets)) == len(assets) and bool(assets), "AQ-PORTFOLIO-ASSET-COVERAGE")
    known: dict[UtcDateTime, Row] = {}
    for row in rows:
        closed, available = utc(row["close_time"]), utc(row["available_time"])
        if available > decision or closed > end or closed < boundaries[0]:
            continue
        require(available >= closed and closed in boundaries, "AQ-PORTFOLIO-DAILY-CALENDAR")
        require(closed not in known, "AQ-PORTFOLIO-DUPLICATE-DAY")
        require(
            set(row["returns"]) == {str(asset) for asset in assets}, "AQ-PORTFOLIO-MISSING-ASSET"
        )
        known[closed] = row
    require(set(known) == set(boundaries), "AQ-PORTFOLIO-INCOMPLETE-90-DAY-WINDOW")
    accepted = [known[day] for day in boundaries]
    values: NDArray[np.float64] = np.asarray(
        [[float(decimal(row["returns"][str(asset)])) for asset in assets] for row in accepted],
        dtype=np.float64,
    )
    require(
        bool(np.all(np.isfinite(values))) and bool(np.all(values > -1)), "AQ-PORTFOLIO-DAILY-RETURN"
    )
    weights: NDArray[np.float64] = np.exp2(-np.arange(89, -1, -1, dtype=np.float64) / 30)
    weights /= weights.sum()
    centered: NDArray[np.float64] = values - np.sum(values * weights[:, None], axis=0)
    sample: NDArray[np.float64] = (
        (centered.T * weights) @ centered / (1 - float(np.sum(weights * weights)))
    )
    sample = (sample + sample.T) / 2
    contract = CovarianceInputContract(
        basis="TOTAL",
        complete_calendar_observations=90,
        input_sha256=canonical_sha256(accepted),
    )
    return estimate_covariance(
        asset_ids=assets,
        sample_covariance=tuple(tuple(Decimal(str(value)) for value in row) for row in sample),
        shrinkage=Decimal("0.20"),
        factors=(),
        regime=RiskRegime.NORMAL,
        regime_multiplier=ONE,
        observed_at=end,
        available_at=max(utc(row["available_time"]) for row in accepted),
        contract=contract,
    )


class BridgeAsset(DomainModel):
    instrument: AccountingInstrument
    signal: SignalInput
    mark: PositiveDecimal
    quantity_step: PositiveDecimal
    minimum_notional: NonNegativeDecimal
    maximum_execution_cost_fraction: UnitInterval
    available_at: UtcDateTime

    @model_validator(mode="after")
    def match_instrument(self) -> BridgeAsset:
        if (
            self.instrument.instrument_type is not InstrumentType.SPOT
            or self.instrument.contract_multiplier != 1
        ):
            raise ValueError("AQ-BRIDGE-FUNDED-UNIT-SPOT-ONLY")
        if (
            self.signal.instrument_id != self.instrument.instrument_id
            or self.signal.asset_id != self.instrument.base_asset_id
            or str(self.signal.venue_id) != self.instrument.venue
            or self.instrument.settlement_asset_id != self.instrument.quote_asset_id
        ):
            raise ValueError("AQ-BRIDGE-INSTRUMENT-IDENTITY")
        if self.signal.impact_model is None:
            raise ValueError("AQ-BRIDGE-EXPLICIT-IMPACT-REQUIRED")
        return self


class PendingReservation(DomainModel):
    order_id: str = Field(min_length=1)
    instrument_id: InstrumentId
    side: OrderSide
    remaining_quantity: PositiveDecimal
    maximum_price: PositiveDecimal
    maximum_cost_fraction: UnitInterval
    available_at: UtcDateTime

    @property
    def quote_reserve(self) -> Decimal:
        return (
            self.remaining_quantity * self.maximum_price * (1 + self.maximum_cost_fraction)
            if self.side is OrderSide.BUY
            else ZERO
        )


@dataclass(frozen=True)
class BridgeAccount:
    ledger_hash: str
    decision_time: UtcDateTime
    nav: Decimal
    quote_asset: AssetId
    quote_total: Decimal
    quote_available: Decimal
    pending_quote_reserved: Decimal
    unsettled_quote: Decimal
    current_quantities: Mapping[InstrumentId, Decimal]
    assets: tuple[BridgeAsset, ...]
    pending: tuple[PendingReservation, ...]


def account_from_ledger(
    ledger: LedgerEngine,
    *,
    assets: Sequence[BridgeAsset],
    quote_balance: AccountBalance,
    fx_rates: Mapping[AssetId, FxRate],
    pending: Sequence[PendingReservation],
    unsettled_quote: Decimal,
    decision_time: UtcDateTime,
    balance_available_at: UtcDateTime,
    fx_available_at: UtcDateTime,
) -> BridgeAccount:
    """Read the authoritative ledger; venue available cash is a ceiling, never sale proceeds."""
    at = utc(decision_time)
    require(
        utc(balance_available_at) <= at and utc(fx_available_at) <= at,
        "AQ-BRIDGE-FUTURE-BALANCE-OR-FX",
    )
    ordered = tuple(sorted(assets, key=lambda item: str(item.instrument.instrument_id)))
    require(
        bool(ordered) and len({a.instrument.instrument_id for a in ordered}) == len(ordered),
        "AQ-BRIDGE-ASSET-IDENTITY",
    )
    require(
        len({a.instrument.base_asset_id for a in ordered}) == len(ordered),
        "AQ-BRIDGE-DUPLICATE-BASE-ASSET",
    )
    require(len({a.instrument.venue for a in ordered}) == 1, "AQ-BRIDGE-SINGLE-VENUE-ACCOUNT")
    require(len({a.signal.account_id for a in ordered}) == 1, "AQ-BRIDGE-SINGLE-VENUE-ACCOUNT")
    quote, venue = quote_balance.asset_id, ordered[0].instrument.venue
    require(
        all(a.instrument.quote_asset_id == quote and a.available_at <= at for a in ordered),
        "AQ-BRIDGE-QUOTE-OR-FUTURE-MARK",
    )
    require(
        all(record.journal_entry.recorded_at <= at for record in ledger.records),
        "AQ-BRIDGE-FUTURE-LEDGER-EVENT",
    )
    require(
        ledger.policy.spot_fee_policy == "SPOT_NATIVE_FEES_V2",
        "AQ-BRIDGE-NATIVE-FEE-POLICY-REQUIRED",
    )
    require(unsettled_quote.is_finite() and unsettled_quote >= 0, "AQ-BRIDGE-UNSETTLED-QUOTE")
    by_id = {a.instrument.instrument_id: a for a in ordered}
    native: dict[AssetId, Decimal] = {}
    for balance in ledger.native_balances():
        definition = ledger.chart.definition(balance.account_id)
        if definition.economic_balance:
            require(
                definition.role is AccountRole.CASH and definition.venue == venue,
                "AQ-BRIDGE-UNSUPPORTED-ACCOUNT-OR-LIABILITY",
            )
            native[balance.asset_id] = native.get(balance.asset_id, ZERO) + balance.amount
    require(all(v >= 0 for v in native.values()), "AQ-BRIDGE-NEGATIVE-CASH")
    require(
        native.get(quote, ZERO) == quote_balance.total and unsettled_quote <= quote_balance.total,
        "AQ-BRIDGE-QUOTE-RECONCILIATION",
    )
    quantities = dict.fromkeys(by_id, ZERO)
    for lot in ledger.open_lots():
        require(
            lot.instrument_id in by_id and lot.side is LotSide.LONG,
            "AQ-BRIDGE-UNCOVERED-OR-SHORT-POSITION",
        )
        quantities[lot.instrument_id] += lot.remaining_quantity
    for asset in ordered:
        require(
            native.get(asset.instrument.base_asset_id, ZERO)
            == quantities[asset.instrument.instrument_id],
            "AQ-BRIDGE-BASE-CASH-LOT-MISMATCH",
        )
        rate = fx_rates.get(asset.instrument.base_asset_id)
        require(
            rate is not None
            and rate.rate == asset.mark
            and rate.reporting_asset_id == quote
            and rate.as_of_time <= at,
            "AQ-BRIDGE-MARK-FX-RECONCILIATION",
        )
    quotes = {
        a.instrument.instrument_id: ValuationQuote(
            instrument_id=a.instrument.instrument_id, as_of_time=at, available_time=at, mark=a.mark
        )
        for a in ordered
    }
    if ledger.open_lots():
        valuation = ledger.valuation_snapshot(quotes)
    else:
        identity = canonical_sha256(
            {
                "ledger": ledger.state_digest().state_hash,
                "as_of": at.isoformat(),
                "empty_lots": True,
            }
        )
        valuation = ValuationSnapshot(
            valuation_snapshot_id=ValuationSnapshotId(identity),
            as_of_time=at,
            available_time=at,
            policy_version=ledger.policy.policy_version,
            lots=(),
            content_hash=identity,
        )
    nav = ledger.equity_snapshot(
        valuation=valuation,
        reporting_asset_id=quote,
        fx_rates=fx_rates,
        valuation_basis="SPOT_NATIVE_MTM_V2",
    ).equity
    require(nav > 0, "AQ-BRIDGE-NONPOSITIVE-NAV")
    reservations = tuple(sorted(pending, key=lambda item: item.order_id))
    require(
        len({p.order_id for p in reservations}) == len(reservations), "AQ-BRIDGE-DUPLICATE-PENDING"
    )
    sells: dict[InstrumentId, Decimal] = dict.fromkeys(by_id, ZERO)
    sides: dict[InstrumentId, set[OrderSide]] = {key: set() for key in by_id}
    for item in reservations:
        require(
            item.instrument_id in by_id and item.available_at <= at,
            "AQ-BRIDGE-UNKNOWN-OR-FUTURE-PENDING",
        )
        sides[item.instrument_id].add(item.side)
        if item.side is OrderSide.SELL:
            sells[item.instrument_id] += item.remaining_quantity
    require(
        all(len(value) <= 1 for value in sides.values()),
        "AQ-BRIDGE-OPPOSING-PENDING-REQUIRES-RECONCILIATION",
    )
    require(
        all(sells[key] <= quantities[key] for key in by_id),
        "AQ-BRIDGE-PENDING-SELL-EXCEEDS-INVENTORY",
    )
    reserved = sum((p.quote_reserve for p in reservations), start=ZERO)
    require(reserved + unsettled_quote <= quote_balance.total, "AQ-BRIDGE-PENDING-EXCEEDS-CASH")
    available = min(quote_balance.available, quote_balance.total - unsettled_quote - reserved)
    return BridgeAccount(
        ledger.state_digest().state_hash,
        at,
        nav,
        quote,
        quote_balance.total,
        available,
        reserved,
        unsettled_quote,
        quantities,
        ordered,
        reservations,
    )


def risk_metrics(
    weights: Mapping[InstrumentId, Decimal],
    *,
    assets: Sequence[BridgeAsset],
    covariance: CovarianceEstimate,
    policy: PortfolioConstructionPolicy,
) -> dict[str, Any]:
    index = {key: i for i, key in enumerate(covariance.asset_ids)}
    ordered = tuple(sorted(assets, key=lambda a: str(a.instrument.instrument_id)))
    require(
        set(weights) == {a.instrument.instrument_id for a in ordered}
        and all(a.signal.asset_id in index for a in ordered),
        "AQ-BRIDGE-RISK-COVERAGE",
    )
    matrix = tuple(
        tuple(
            covariance.matrix[index[a.signal.asset_id]][index[b.signal.asset_id]] for b in ordered
        )
        for a in ordered
    )
    vector = [weights[a.instrument.instrument_id] for a in ordered]
    require(all(w.is_finite() and w >= 0 for w in vector), "AQ-BRIDGE-RISK-LONG-FLAT")
    variance = _portfolio_variance(vector, matrix)
    volatility = variance.sqrt()
    gross = sum(vector, start=ZERO)
    breaches: list[str] = []
    if gross > min(ONE, policy.maximum_gross_weight):
        breaches.append("GROSS")
    if volatility > policy.volatility_target:
        breaches.append("VOLATILITY")
    group_gross = {}
    for constraint in policy.exposure_constraints:
        value = sum(
            (
                vector[i]
                for i, a in enumerate(ordered)
                if _dimension_key(a.signal, constraint.dimension) == constraint.key
            ),
            start=ZERO,
        )
        group_gross[constraint.dimension.value + ":" + constraint.key] = str(value)
        if value > constraint.maximum_absolute_weight:
            breaches.append(constraint.dimension.value + ":" + constraint.key)
    contributions = {
        str(a.signal.asset_id): vector[i]
        * sum((matrix[i][j] * vector[j] for j in range(len(vector))), start=ZERO)
        for i, a in enumerate(ordered)
    }
    return {
        "annualized_volatility": str(volatility),
        "variance": str(variance),
        "gross": str(gross),
        "group_gross": group_gross,
        "variance_contributions": {k: str(v) for k, v in contributions.items()},
        "risk_contribution_shares": {
            k: str(v / variance) if variance else None for k, v in contributions.items()
        },
        "breaches": breaches,
    }


@dataclass(frozen=True)
class PortfolioBridgePlan:
    proposal: PortfolioProposal
    risk_decision: RiskDecision
    signed_quantities: Mapping[InstrumentId, Decimal]
    quote_required: Decimal
    cancel_first: tuple[str, ...]
    status: str
    diagnostics: Mapping[str, Any]


def plan_shared_capital(
    *,
    ledger: LedgerEngine,
    account: BridgeAccount,
    raw_target_weights: Mapping[InstrumentId, Decimal],
    covariance: CovarianceEstimate,
    construction: PortfolioConstructionPolicy,
    risk_snapshot: RiskSnapshot,
    signed_policy: SignedRiskPolicy,
    trusted_public_keys: dict[str, bytes],
    prior_risk_state: RiskState,
    risk_transition_sequence: int,
    events: tuple[RiskEvent, ...] = (),
    tail_evidence_ready: bool = False,
) -> PortfolioBridgePlan:
    """Deterministic funded allocation; returns quantities only and never submits orders."""
    require(
        ledger.state_digest().state_hash == account.ledger_hash,
        "AQ-BRIDGE-LEDGER-CHANGED-RECOMPUTE",
    )
    require(
        type(risk_transition_sequence) is int and risk_transition_sequence >= 1,
        "AQ-BRIDGE-RISK-TRANSITION-SEQUENCE",
    )
    require(
        covariance.evidence is not None and covariance.available_at <= account.decision_time,
        "AQ-BRIDGE-CAUSAL-COVARIANCE-REQUIRED",
    )
    if covariance.evidence is not None:
        require(
            covariance.evidence.contract.annualization_days == Decimal("365.25")
            and covariance.evidence.contract.complete_calendar_observations >= 90,
            "AQ-BRIDGE-COVARIANCE-UNIT-OR-COVERAGE",
        )
    require(
        risk_snapshot.ledger_reconciled and risk_snapshot.as_of_time == account.decision_time,
        "AQ-BRIDGE-RISK-SNAPSHOT-RECONCILIATION",
    )
    assets = account.assets
    ids = tuple(a.instrument.instrument_id for a in assets)
    current = {
        a.instrument.instrument_id: canonical_result(
            account.current_quantities[a.instrument.instrument_id] * a.mark / account.nav
        )
        for a in assets
    }
    positions = {p.instrument_id: p.signed_weight for p in risk_snapshot.positions}
    require(
        set(positions) <= set(ids) and all(positions.get(key, ZERO) == current[key] for key in ids),
        "AQ-BRIDGE-RISK-POSITION-MISMATCH",
    )
    signals = tuple(
        a.signal.model_copy(
            update={"current_weight": current[a.instrument.instrument_id], "expected_return": ZERO}
        )
        for a in assets
    )
    policy = verify_signed_risk_policy(
        signed_policy,
        trusted_public_keys=trusted_public_keys,
        decision_time=account.decision_time,
        deployment_stage=construction.environment_stage,
    )
    # Enforce the stricter signed limits also on pending and intermediate fill order.
    constraints = {(c.dimension, c.key): c for c in construction.exposure_constraints}
    limits = policy.pre_trade_limits
    for dimension, keys, maximum in (
        (
            ExposureDimension.ASSET,
            {str(a.signal.asset_id) for a in assets},
            limits.maximum_asset_gross_weight,
        ),
        (
            ExposureDimension.STRATEGY,
            {str(a.signal.strategy_id) for a in assets},
            limits.maximum_strategy_gross_weight,
        ),
    ):
        for key in keys:
            previous = constraints.get((dimension, key))
            constraints[(dimension, key)] = ExposureConstraint(
                dimension=dimension,
                key=key,
                maximum_absolute_weight=min(maximum, previous.maximum_absolute_weight)
                if previous
                else maximum,
            )
    construction = construction.model_copy(
        update={
            "maximum_gross_weight": min(
                construction.maximum_gross_weight, limits.maximum_account_gross_weight, ONE
            ),
            "exposure_constraints": tuple(
                constraints[key]
                for key in sorted(constraints, key=lambda key: (key[0].value, key[1]))
            ),
        }
    )
    circuit = evaluate_circuit_breakers(
        snapshot=risk_snapshot, policy=policy, decision_time=account.decision_time, events=events
    )
    current_risk = risk_metrics(current, assets=assets, covariance=covariance, policy=construction)
    triggered = max(
        circuit.state,
        RiskState.REDUCE_ONLY if current_risk["breaches"] else RiskState.NORMAL,
        key=SAFETY_RANK.__getitem__,
    )
    transition = None
    if prior_risk_state is RiskState.RECOVERY:
        effective_state = RiskState.HALTED if triggered is RiskState.HALTED else RiskState.RECOVERY
    else:
        effective_state = max(prior_risk_state, triggered, key=SAFETY_RANK.__getitem__)
        if effective_state is not prior_risk_state:
            transition = transition_risk_state(
                sequence=risk_transition_sequence,
                current=prior_risk_state,
                target=effective_state,
                automatic=True,
                actor="independent-risk-engine",
                reason_code="AQ-BRIDGE-HARD-RISK",
                occurred_at=account.decision_time,
            )
    hard = effective_state in {RiskState.REDUCE_ONLY, RiskState.HALTED}
    targets = dict.fromkeys(ids, ZERO) if hard else dict(raw_target_weights)
    require(set(raw_target_weights) == set(ids), "AQ-BRIDGE-RAW-TARGET-COVERAGE")
    proposal = build_portfolio_proposal(
        proposal_id=ProposalId(
            canonical_sha256(
                {
                    "ledger": account.ledger_hash,
                    "targets": {str(k): str(v) for k, v in targets.items()},
                    "as_of": account.decision_time.isoformat(),
                }
            )
        ),
        signals=signals,
        covariance=covariance,
        policy=construction,
        portfolio_nav=account.nav,
        as_of_time=account.decision_time,
        created_at=account.decision_time,
        raw_target_weights=targets,
        hard_risk_reduction=hard,
    )
    decision = evaluate_portfolio_proposal(
        proposal=proposal,
        snapshot=risk_snapshot,
        signed_policy=signed_policy,
        trusted_public_keys=trusted_public_keys,
        decision_time=account.decision_time,
        events=events,
    )
    if effective_state is not RiskState.NORMAL:
        reduced = tuple(
            t for t in decision.approved_targets if 0 <= t.approved_target_weight < t.current_weight
        )
        decision = RiskDecision.model_validate(
            {
                **dict(decision),
                "risk_decision_id": RiskDecisionId(
                    canonical_sha256(
                        {
                            "source": str(decision.risk_decision_id),
                            "latched_state": effective_state.value,
                        }
                    )
                ),
                "state": effective_state,
                "new_risk_allowed": False,
                "status": RiskDecisionStatus.REDUCE_ONLY
                if effective_state is RiskState.REDUCE_ONLY
                else RiskDecisionStatus.HALTED
                if effective_state is RiskState.HALTED
                else RiskDecisionStatus.REJECTED,
                "approved_targets": reduced if effective_state is RiskState.REDUCE_ONLY else (),
                "reason_codes": (*decision.reason_codes, "AQ-BRIDGE-PERSISTED-RISK-STATE"),
            }
        )
    approved = {t.instrument_id: t.approved_target_weight for t in decision.approved_targets}
    pending_net = dict.fromkeys(ids, ZERO)
    pending_buy = dict.fromkeys(ids, ZERO)
    pending_sell = dict.fromkeys(ids, ZERO)
    for item in account.pending:
        direction = ONE if item.side is OrderSide.BUY else -ONE
        pending_net[item.instrument_id] += direction * item.remaining_quantity
        (pending_buy if item.side is OrderSide.BUY else pending_sell)[item.instrument_id] += (
            item.remaining_quantity
        )
    candidates: dict[InstrumentId, Decimal] = dict.fromkeys(ids, ZERO)
    cancels: list[str] = [
        p.order_id
        for p in account.pending
        if p.side is OrderSide.BUY
        and (hard or not decision.new_risk_allowed or not tail_evidence_ready)
    ]
    blocked: list[str] = (
        ["RISK_STATE_BLOCKED"] if effective_state in {RiskState.CAUTION, RiskState.RECOVERY} else []
    )
    for asset, signal in zip(assets, signals, strict=True):
        key = asset.instrument.instrument_id
        if key not in approved:
            continue
        adjustment = target_quantity_adjustment(
            target_quantity=approved[key] * account.nav / asset.mark,
            current_quantity=account.current_quantities[key],
            signed_pending_quantity=pending_net[key],
            price=asset.mark,
            quantity_step=asset.quantity_step,
            minimum_notional=asset.minimum_notional,
        )
        if adjustment.cancel_pending_first:
            cancels.extend(p.order_id for p in account.pending if p.instrument_id == key)
            continue
        quantity = adjustment.signed_order_quantity
        capacity_qty = (
            _capacity_weight(signal, nav=account.nav, policy=construction)
            * account.nav
            / asset.mark
        )
        capacity_qty = (capacity_qty / asset.quantity_step).to_integral_value(
            rounding=ROUND_DOWN
        ) * asset.quantity_step
        quantity = min(abs(quantity), capacity_qty) * (ONE if quantity >= 0 else -ONE)
        if quantity < 0:
            quantity = -min(abs(quantity), account.current_quantities[key] - pending_sell[key])
        if quantity > 0 and (hard or not decision.new_risk_allowed or not tail_evidence_ready):
            quantity = ZERO
            blocked.append("NEW_RISK_NOT_ADMITTED")
        candidates[key] = quantity
    required = sum(
        (
            max(ZERO, candidates[a.instrument.instrument_id])
            * a.mark
            * (1 + a.maximum_execution_cost_fraction)
            for a in assets
        ),
        start=ZERO,
    )
    scale = min(ONE, account.quote_available / required) if required else ONE
    for asset in assets:
        key = asset.instrument.instrument_id
        if candidates[key] > 0:
            candidates[key] = (candidates[key] * scale / asset.quantity_step).to_integral_value(
                rounding=ROUND_DOWN
            ) * asset.quantity_step
        if abs(candidates[key]) * asset.mark < asset.minimum_notional:
            candidates[key] = ZERO

    def post_risk(quantities: Mapping[InstrumentId, Decimal], worst_prefix: bool) -> dict[str, Any]:
        maximum_costs = sum(
            (
                p.remaining_quantity * p.maximum_price * p.maximum_cost_fraction
                for p in account.pending
            ),
            start=ZERO,
        )
        maximum_costs += sum(
            (
                abs(quantities[a.instrument.instrument_id])
                * a.mark
                * a.maximum_execution_cost_fraction
                for a in assets
            ),
            start=ZERO,
        )
        post_nav = account.nav - maximum_costs
        require(post_nav > 0, "AQ-BRIDGE-COSTS-EXHAUST-NAV")
        weights = {
            a.instrument.instrument_id: canonical_result(
                (
                    account.current_quantities[a.instrument.instrument_id]
                    + pending_buy[a.instrument.instrument_id]
                    + (
                        max(ZERO, quantities[a.instrument.instrument_id])
                        if worst_prefix
                        else quantities[a.instrument.instrument_id]
                        - pending_sell[a.instrument.instrument_id]
                    )
                )
                * a.mark
                / post_nav
            )
            for a in assets
        }
        return risk_metrics(weights, assets=assets, covariance=covariance, policy=construction)

    worst, post = post_risk(candidates, True), post_risk(candidates, False)
    if worst["breaches"] or post["breaches"]:
        # Unfilled sales never finance or offset the risk of buys. Retain executable hard exits.
        candidates = {key: min(ZERO, value) if hard else ZERO for key, value in candidates.items()}
        blocked.append("POST_ROUNDING_RISK")
        worst, post = post_risk(candidates, True), post_risk(candidates, False)
    required = sum(
        (
            max(ZERO, candidates[a.instrument.instrument_id])
            * a.mark
            * (1 + a.maximum_execution_cost_fraction)
            for a in assets
        ),
        start=ZERO,
    )
    require(required <= account.quote_available, "AQ-BRIDGE-CASH-POSTCONDITION")
    unresolved = bool(
        current_risk["breaches"]
        or worst["breaches"]
        or post["breaches"]
        or any("UNRESOLVED-BREACH" in reason for reason in proposal.constraint_summary)
    )
    status = (
        "BREACH_UNEXECUTABLE_OR_PENDING"
        if hard or unresolved
        else "CANCEL_PENDING_FIRST"
        if cancels
        else "BLOCKED"
        if blocked
        else "PROPOSAL_ONLY"
    )
    return PortfolioBridgePlan(
        proposal,
        decision,
        candidates,
        required,
        tuple(sorted(set(cancels))),
        status,
        {
            "current_risk": current_risk,
            "worst_fill_order_risk": worst,
            "post_rounding_risk": post,
            "pending_quote_reserved": str(account.pending_quote_reserved),
            "unsettled_quote": str(account.unsettled_quote),
            "quote_available": str(account.quote_available),
            "blocked": sorted(set(blocked)),
            "assumed_sale_proceeds": "0",
            "submitted_orders": 0,
            "tail_evidence_ready": tail_evidence_ready,
            "partial_fill_requires_fresh_ledger_and_risk_snapshot": True,
            "effective_risk_state": effective_state.value,
            "risk_transition": transition.model_dump(mode="json") if transition else None,
            "automatic_recovery_allowed": False,
        },
    )


def cvar_evidence(
    daily_returns: Sequence[Decimal], *, confidence: Decimal = Decimal("0.95")
) -> dict[str, Any]:
    require(confidence == Decimal("0.95"), "AQ-BRIDGE-CVAR-FROZEN-CONFIDENCE")
    require(
        bool(daily_returns) and all(v.is_finite() and v > -1 for v in daily_returns),
        "AQ-BRIDGE-CVAR-RETURNS",
    )
    losses = sorted((-value for value in daily_returns), reverse=True)
    tail_mass = Decimal(len(losses)) * (1 - confidence)
    whole = int(tail_mass)
    tail_sum = sum(losses[:whole], start=ZERO)
    if tail_mass > whole:
        tail_sum += losses[whole] * (tail_mass - whole)
    point = max(ZERO, tail_sum / tail_mass)
    return {
        "daily_cvar95_point": str(point),
        "tail_mass": str(tail_mass),
        "observations": len(losses),
        "status": "UNKNOWN_INSUFFICIENT_TAIL_BLOCKS",
        "safety_proven": False,
        "block_uncertainty": None,
        "joint_stress_required": True,
    }


def joint_stress_diagnostic(
    *,
    plan: PortfolioBridgePlan,
    account: BridgeAccount,
    snapshot: RiskSnapshot,
    signed_policy: SignedRiskPolicy,
    scenario: PortfolioStressScenario,
) -> dict[str, Any]:
    result = run_portfolio_stress(
        proposal=plan.proposal, snapshot=snapshot, policy=signed_policy.policy, scenario=scenario
    )
    blocked = [
        str(a.instrument.instrument_id)
        for a in account.assets
        if account.current_quantities[a.instrument.instrument_id] > 0
        and (a.signal.venue_id in scenario.unavailable_venues or scenario.liquidity_multiplier == 0)
    ]
    return {
        "scenario": scenario.model_dump(mode="json"),
        "legacy_risk_action": result.model_dump(mode="json"),
        "actual_positions_not_exited": blocked,
        "execution_status": "UNEXECUTABLE" if blocked else "NOT_REPLAYED",
        "scenario_kind": "PREDECLARED_STRESS_ASSUMPTION",
        "realized_tail_loss": None,
        "instant_cash_assumed": False,
        "historical_replay_runs": 0,
    }


def drawdown_history(rows: Sequence[Row], *, decision_time: UtcDateTime) -> dict[str, Any]:
    """Full and trailing 30-day drawdown stay separate; no automatic recovery permission."""
    at = utc(decision_time)
    known = sorted(
        (row for row in rows if utc(row["available_time"]) <= at and utc(row["close_time"]) <= at),
        key=lambda row: utc(row["close_time"]),
    )
    require(bool(known), "AQ-BRIDGE-NO-EQUITY-HISTORY")
    times = [utc(row["close_time"]) for row in known]
    require(
        all(right - left == timedelta(days=1) for left, right in pairwise(times)),
        "AQ-BRIDGE-EQUITY-DAILY-CALENDAR",
    )
    values = [decimal(row["equity"]) for row in known]
    require(all(v > 0 for v in values), "AQ-BRIDGE-EQUITY-POSITIVE")

    def metrics(prices: Sequence[Decimal]) -> tuple[Decimal, int]:
        peak, maximum, duration, longest = prices[0], ZERO, 0, 0
        for value in prices:
            peak = max(peak, value)
            maximum = max(maximum, ONE - value / peak)
            duration = duration + 1 if value < peak else 0
            longest = max(longest, duration)
        return maximum, longest

    full, duration = metrics(values)
    trailing, trailing_duration = metrics(values[-31:])
    return {
        "full_period_maximum_drawdown": str(full),
        "full_period_maximum_duration_days": duration,
        "trailing_30d_maximum_drawdown": str(trailing) if len(values) >= 31 else None,
        "trailing_30d_maximum_duration_days": trailing_duration if len(values) >= 31 else None,
        "window_status": "COMPLETE" if len(values) >= 31 else "UNKNOWN_INCOMPLETE",
        "soft_gate_reached": trailing >= Decimal("0.08") if len(values) >= 31 else None,
        "hard_gate_reached": trailing >= Decimal("0.12") if len(values) >= 31 else None,
        "automatic_recovery_allowed": False,
    }


def validate_config(config: Row) -> None:
    match = re.fullmatch(r"alpha-r5-portfolio-contract-(\d{8})-v([1-9]\d*)", config["generation"])
    require(match is not None, "AQ-PORTFOLIO-GENERATION")
    if match is None:
        return
    require(
        config["output"] == f"artifacts/alpha_v5/{match[1]}_portfolio_contract_v{match[2]}",
        "AQ-PORTFOLIO-OUTPUT",
    )
    require(
        config["scope"] == "B5_PORTFOLIO_BRIDGE_AND_SYNTHETIC_CONTRACT_TESTS", "AQ-PORTFOLIO-SCOPE"
    )
    require(
        config["historical_portfolio_inputs"] is None
        and config["economic_policy_adopted"] is False,
        "AQ-PORTFOLIO-REAL-RESEARCH-NOT-AUTHORIZED",
    )
    require(
        config["future_scenarios"]
        == {
            "modes": ["INDEPENDENT_SLEEVES", "SHARED_CASH_BRIDGE", "SHARED_CASH_WITH_RISK"],
            "stress_paths": [
                "JOINT_CORRELATED_GAP",
                "DEPTH_LATENCY_AND_VENUE_HALT",
                "USDT_DEPEG_AND_BLOCKED_EXIT",
            ],
            "capital": "50000",
            "authorized_runs_now": 0,
        },
        "AQ-PORTFOLIO-MATRIX-REGISTRATION",
    )
    require(
        config["proposed_risk_policy"]
        == {
            "return_frequency": "UTC_DAILY",
            "lookback_calendar_days": 90,
            "ewma_half_life_days": 30,
            "diagonal_shrinkage": "0.20",
            "covariance_basis": "TOTAL",
            "annualization_days": "365.25",
            "volatility_target_annual": "0.12",
            "gross_max": "1.0",
            "single_asset_max": "0.30",
            "crypto_cluster_gross_max": "0.40",
            "cvar_confidence": "0.95",
            "cvar_loss_daily_max": "0.02",
            "drawdown_window_days": 30,
            "drawdown_soft": "0.08",
            "drawdown_hard": "0.12",
            "automatic_recovery_allowed": False,
            "enable_for_live": False,
        },
        "AQ-PORTFOLIO-RISK-PROPOSAL-IDENTITY",
    )


def build_documents(sources: dict[str, Any]) -> Mapping[str, Any]:
    gaps = [
        {"item": "real_pit_universe_and_joint_daily_returns", "status": "NOT_RECEIVED"},
        {
            "item": "historical_available_cash_pending_and_settlement_events",
            "status": "NOT_RECEIVED",
        },
        {"item": "empirically_verified_execution_capacity", "status": "NOT_COLLECTED"},
        {"item": "economic_adoption_of_proposed_risk_policy", "status": "NOT_ADOPTED"},
        {"item": "joint_tail_uncertainty_and_independent_stress_replay", "status": "NOT_COLLECTED"},
    ]
    return {
        "portfolio_bridge_reconciliation.json": {
            "status": "SYNTHETIC_CONTRACTS_ONLY",
            "actual_joint_paths": None,
            "same_configuration_engine_equivalence": "NOT_VERIFIED",
            "cash_source": "EXISTING_LEDGER_NATIVE_BALANCES",
            "available_cash_rule": "MIN_VENUE_AVAILABLE_AND_LEDGER_TOTAL_MINUS_UNSETTLED_MINUS_PENDING_BUY_RESERVE",
            "unfilled_sale_proceeds_available": False,
            "rounding": "DOWN_WITH_POST_ROUNDING_RISK_CHECK",
            "partial_fill_action": "RECOMPUTE_FROM_FRESH_LEDGER_AND_RISK_SNAPSHOT",
        },
        "covariance_and_risk_forecasts.json": {
            "status": "NOT_COLLECTED",
            "historical_forecasts": None,
            "TOTAL_factor_addition": "FORBIDDEN",
            "RESIDUAL_factor_addition": "DEFINED_ORTHOGONAL_FACTORS_ONLY",
            "psd_rule": "RELATIVE_1E12_REJECT_OR_RECORDED_FIXED_DIAGONAL_JITTER",
            "missing_asset_policy": "FAIL_CLOSED",
            "annualized_unit": "DAILY_DECIMAL_RETURN_COVARIANCE_TIMES_365_25",
            "lookback_calendar_days": 90,
        },
        "daily_risk_contribution.json": {
            "status": "NOT_COLLECTED",
            "rows": None,
            "cluster_limit_semantics": "GROSS_EXPOSURE_NOT_VARIANCE_SHARE",
            "zero_variance_share": None,
        },
        "joint_stress_and_breach_ledger.json": {
            "status": "NOT_COLLECTED",
            "real_paths": None,
            "hard_reduction_bypasses_ordinary_turnover": True,
            "hard_reduction_bypasses_liquidity": False,
            "unexecutable_exit": "KEEP_REAL_HOLDINGS_AND_BREACH_NO_INSTANT_CASH",
            "automatic_recovery_allowed": False,
        },
        "three_mode_attribution.json": {
            "status": "NOT_COLLECTED",
            "capital": "50000",
            "funding_bridge_contribution": None,
            "incremental_risk_projection_contribution": None,
            "historical_matrix_runs": 0,
        },
        "evidence_gaps.json": {
            "gaps": gaps,
            "pit_quality": sources["b2_safety"]["strict_data_quality"],
            "execution_calibration": "NOT_COLLECTED",
            "promotion_admitted": False,
        },
        "report.md": """# B5 组合风险与共享资金契约

**NO_PROVEN_ALPHA / CASH；ML、纸面准入、实盘、订单全部关闭。**

已为 covariance 增加 TOTAL/RESIDUAL、单位和 PSD 契约；只有浮点容差内的小负特征值允许固定修正并记录。90 个完整 UTC 日的 EWMA/shrinkage 使用固定规则，缺币或缺日失败。原数值调用保留；显式目标投影直接使用已有 raw targets，期望收益字段为 0，不把二元趋势信号当收益预测。

共享资金适配器读取原 ledger，计入真实可用现金、pending BUY 预留、未结算收入与未完成卖出。按固定比例预算并向下取整，逐次检查最坏成交顺序和取整后的风险。partial fill 后要求重新读取账本及风险快照。硬风险减仓可越过普通换手限额，但流动性不够、撤单未确认或场所停摆时保留持仓与 BREACH。

显式 SPOT_NATIVE_MTM_V2 估值避免在已经按现价估值的现货余额上再次叠加 lot 浮盈。旧估值默认不改。费用币资产仍必须有可知 FX，底层原生币账本继续复用；没有另造账本或下单器。

风险贡献、30 日回撤与全期回撤分开。90 日 CVaR95 的尾部点不足以证明安全，状态保持 UNKNOWN，必须补充独立时间块不确定性和联合压力。任务书的风险数值仍是待经济采用的研究起点，本批不启用该风险配置做真实研究。

仅完成接口及合成验证。三模式九个历史组合回放、真实预测/实现风险、资金共享贡献、尾部非劣与容量均 NOT_COLLECTED；不能由工程通过推断风险策略或 alpha 准入。历史回放、真实模型/校准拟合、最终留出读取、订单均为 0。
""",
    }
