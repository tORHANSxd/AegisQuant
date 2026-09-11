"""Conservative robust portfolio projection with hard post-condition checks."""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import ProposalId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import canonical_result
from aegisquant.portfolio.models import (
    CovarianceEstimate,
    ExposureConstraint,
    ExposureDimension,
    NormalizedSignal,
    PortfolioConstructionPolicy,
    PortfolioLeg,
    PortfolioProposal,
    SignalInput,
    TargetQuantityAdjustment,
)
from aegisquant.portfolio.transition_costs import legacy_impact_model

ZERO = Decimal("0")
ONE = Decimal("1")


def target_quantity_adjustment(
    *,
    target_quantity: Decimal,
    current_quantity: Decimal,
    signed_pending_quantity: Decimal,
    price: Decimal,
    quantity_step: Decimal,
    minimum_notional: Decimal,
    minimum_economic_notional: Decimal = ZERO,
) -> TargetQuantityAdjustment:
    if (
        min(target_quantity, current_quantity, minimum_notional, minimum_economic_notional) < 0
        or min(price, quantity_step) <= 0
    ):
        raise ValueError("target adjustment requires valid long/flat quantities and market rules")
    delta = target_quantity - current_quantity - signed_pending_quantity
    conflict = delta * signed_pending_quantity < 0
    if conflict:
        quantity, reason = ZERO, "CANCEL_OPPOSING_PENDING_THEN_RECOMPUTE_FROM_ACK"
    else:
        rounded = (abs(delta) / quantity_step).to_integral_value(
            rounding=ROUND_DOWN
        ) * quantity_step
        quantity = rounded if delta > 0 else -rounded
        reason = "TARGET_MINUS_CURRENT_MINUS_PENDING"
        if abs(quantity) * price < max(minimum_notional, minimum_economic_notional):
            quantity, reason = ZERO, "BELOW_MINIMUM_ECONOMIC_REBALANCE"
    return TargetQuantityAdjustment(
        target_quantity=target_quantity,
        current_quantity=current_quantity,
        signed_pending_quantity=signed_pending_quantity,
        signed_order_quantity=canonical_result(quantity),
        cancel_pending_first=conflict,
        reason=reason,
    )


def _clip_unit(value: Decimal) -> Decimal:
    return max(Decimal("-1"), min(ONE, value))


def normalize_signal(signal: SignalInput, policy: PortfolioConstructionPolicy) -> NormalizedSignal:
    clipped = _clip_unit(signal.raw_score)
    discounted = canonical_result(clipped * signal.confidence)
    uncertainty_haircut = ONE - policy.uncertainty_penalty * (ONE - signal.confidence)
    robust = canonical_result(discounted * uncertainty_haircut)
    in_zone = abs(robust) < policy.no_trade_zone
    reasons: list[str] = []
    if clipped != signal.raw_score:
        reasons.append("AQ-PORTFOLIO-SIGNAL-CLIPPED")
    if signal.confidence < ONE:
        reasons.append("AQ-PORTFOLIO-CONFIDENCE-DISCOUNT")
    if in_zone:
        robust = ZERO
        reasons.append("AQ-PORTFOLIO-NO-TRADE-ZONE")
    return NormalizedSignal(
        signal=signal,
        clipped_score=clipped,
        discounted_score=discounted,
        robust_score=robust,
        in_no_trade_zone=in_zone,
        reason_codes=tuple(reasons),
    )


def _portfolio_variance(weights: list[Decimal], matrix: tuple[tuple[Decimal, ...], ...]) -> Decimal:
    value = sum(
        (
            weights[row] * matrix[row][column] * weights[column]
            for row in range(len(weights))
            for column in range(len(weights))
        ),
        start=ZERO,
    )
    if value < 0:
        raise ValueError("AQ-PORTFOLIO-NEGATIVE-VARIANCE")
    return canonical_result(value)


def _dimension_key(signal: SignalInput, dimension: ExposureDimension) -> str | None:
    return {
        ExposureDimension.ASSET: str(signal.asset_id),
        ExposureDimension.CONTRACT: str(signal.instrument_id),
        ExposureDimension.STRATEGY: str(signal.strategy_id),
        ExposureDimension.SLEEVE: signal.sleeve_id,
        ExposureDimension.VENUE: str(signal.venue_id),
        ExposureDimension.STABLECOIN: (
            str(signal.stablecoin_id) if signal.stablecoin_id is not None else None
        ),
        ExposureDimension.CORRELATION_CLUSTER: signal.correlation_cluster_id,
    }[dimension]


def _scale_all(weights: list[Decimal], maximum: Decimal) -> None:
    gross = sum((abs(item) for item in weights), start=ZERO)
    if gross > maximum:
        scale = maximum / gross
        for index, value in enumerate(weights):
            weights[index] = canonical_result(value * scale)


def _apply_group_constraints(
    *,
    weights: list[Decimal],
    signals: tuple[SignalInput, ...],
    constraints: tuple[ExposureConstraint, ...],
    reasons: list[list[str]],
) -> None:
    for constraint in constraints:
        members = [
            index
            for index, signal in enumerate(signals)
            if _dimension_key(signal, constraint.dimension) == constraint.key
        ]
        if not members:
            continue
        gross = sum((abs(weights[index]) for index in members), start=ZERO)
        if gross <= constraint.maximum_absolute_weight:
            continue
        scale = constraint.maximum_absolute_weight / gross if gross > ZERO else ZERO
        for index in members:
            weights[index] = canonical_result(weights[index] * scale)
            reasons[index].append(
                f"AQ-PORTFOLIO-{constraint.dimension.value}-CONSTRAINT:{constraint.key}"
            )


def _capacity_weight(
    signal: SignalInput, *, nav: Decimal, policy: PortfolioConstructionPolicy
) -> Decimal:
    if signal.average_daily_notional == ZERO:
        return ZERO
    participation = policy.maximum_participation
    curve = signal.impact_model or legacy_impact_model(signal.impact_coefficient_bps, capacity=True)
    participation = min(participation, curve.participation_for_impact(policy.maximum_impact_bps))
    return canonical_result(signal.average_daily_notional * participation / nav)


def _apply_capacity(
    *,
    weights: list[Decimal],
    signals: tuple[SignalInput, ...],
    nav: Decimal,
    policy: PortfolioConstructionPolicy,
    reasons: list[list[str]],
) -> list[Decimal]:
    capacities: list[Decimal] = []
    for index, signal in enumerate(signals):
        capacity = _capacity_weight(signal, nav=nav, policy=policy)
        capacities.append(capacity)
        delta = weights[index] - signal.current_weight
        if abs(delta) > capacity:
            direction = ONE if delta > ZERO else Decimal("-1")
            weights[index] = canonical_result(signal.current_weight + direction * capacity)
            reasons[index].append("AQ-PORTFOLIO-CAPACITY-CONSTRAINT")
    return capacities


def _apply_turnover(
    *,
    weights: list[Decimal],
    signals: tuple[SignalInput, ...],
    maximum_turnover: Decimal,
    reasons: list[list[str]],
) -> None:
    deltas = [
        weight - signal.current_weight for weight, signal in zip(weights, signals, strict=True)
    ]
    turnover = sum((abs(item) for item in deltas), start=ZERO)
    if turnover <= maximum_turnover:
        return
    scale = maximum_turnover / turnover if turnover > ZERO else ZERO
    remaining = maximum_turnover
    for index, signal in enumerate(signals):
        scaled_delta = canonical_result(deltas[index] * scale)
        magnitude = min(abs(scaled_delta), remaining)
        direction = ONE if scaled_delta > ZERO else Decimal("-1")
        candidate = canonical_result(signal.current_weight + direction * magnitude)
        realized = abs(candidate - signal.current_weight)
        if realized > remaining:
            candidate = signal.current_weight
            realized = ZERO
        weights[index] = candidate
        remaining = canonical_result(max(ZERO, remaining - realized))
        reasons[index].append("AQ-PORTFOLIO-TURNOVER-CONSTRAINT")


def _assert_constraints(
    *,
    weights: list[Decimal],
    signals: tuple[SignalInput, ...],
    capacities: list[Decimal],
    policy: PortfolioConstructionPolicy,
    covariance_matrix: tuple[tuple[Decimal, ...], ...],
) -> None:
    gross = sum((abs(item) for item in weights), start=ZERO)
    if gross > policy.maximum_gross_weight:
        raise ValueError("AQ-PORTFOLIO-GROSS-POSTCONDITION")
    turnover = sum(
        (
            abs(weight - signal.current_weight)
            for weight, signal in zip(weights, signals, strict=True)
        ),
        start=ZERO,
    )
    if turnover > policy.maximum_turnover:
        raise ValueError("AQ-PORTFOLIO-TURNOVER-POSTCONDITION")
    for index, signal in enumerate(signals):
        if abs(weights[index] - signal.current_weight) > capacities[index]:
            raise ValueError("AQ-PORTFOLIO-CAPACITY-POSTCONDITION")
    for constraint in policy.exposure_constraints:
        gross = sum(
            (
                abs(weights[index])
                for index, signal in enumerate(signals)
                if _dimension_key(signal, constraint.dimension) == constraint.key
            ),
            start=ZERO,
        )
        if gross > constraint.maximum_absolute_weight:
            raise ValueError("AQ-PORTFOLIO-GROUP-POSTCONDITION")
    variance = _portfolio_variance(weights, covariance_matrix)
    if variance.sqrt() > policy.volatility_target:
        raise ValueError("AQ-PORTFOLIO-VOLATILITY-POSTCONDITION")


def build_portfolio_proposal(
    *,
    proposal_id: ProposalId,
    signals: tuple[SignalInput, ...],
    covariance: CovarianceEstimate,
    policy: PortfolioConstructionPolicy,
    portfolio_nav: Decimal,
    as_of_time: UtcDateTime,
    created_at: UtcDateTime,
    validity_seconds: int = 60,
) -> PortfolioProposal:
    """Build a proposal by conservative projections; hard conflicts fail closed."""

    if not signals or len({item.instrument_id for item in signals}) != len(signals):
        raise ValueError("portfolio signals must be non-empty and instrument-unique")
    if portfolio_nav <= ZERO or not portfolio_nav.is_finite():
        raise ValueError("portfolio NAV must be positive and finite")
    if covariance.available_at > as_of_time:
        raise ValueError("AQ-PORTFOLIO-FUTURE-COVARIANCE")
    if created_at < as_of_time or validity_seconds <= 0:
        raise ValueError("portfolio proposal timing is invalid")
    asset_index = {asset_id: index for index, asset_id in enumerate(covariance.asset_ids)}
    if any(signal.asset_id not in asset_index for signal in signals):
        raise ValueError("every signal asset requires covariance coverage")
    budget_by_asset = {item.asset_id: item.maximum_risk_share for item in policy.risk_budgets}
    if any(signal.asset_id not in budget_by_asset for signal in signals):
        raise ValueError("every signal asset requires a risk budget")
    normalized = tuple(normalize_signal(signal, policy) for signal in signals)
    weights: list[Decimal] = []
    reasons = [list(item.reason_codes) for item in normalized]
    for item in normalized:
        if item.in_no_trade_zone:
            weights.append(item.signal.current_weight)
            continue
        variance = covariance.matrix[asset_index[item.signal.asset_id]][
            asset_index[item.signal.asset_id]
        ]
        if variance <= ZERO:
            raise ValueError("AQ-PORTFOLIO-NONPOSITIVE-ASSET-VARIANCE")
        inverse_volatility = ONE / variance.sqrt()
        weight = item.robust_score * budget_by_asset[item.signal.asset_id] * inverse_volatility
        weights.append(canonical_result(weight))
    _scale_all(weights, policy.maximum_gross_weight)
    ordered_matrix = tuple(
        tuple(
            covariance.matrix[asset_index[row.asset_id]][asset_index[column.asset_id]]
            for column in signals
        )
        for row in signals
    )
    variance = _portfolio_variance(weights, ordered_matrix)
    volatility = variance.sqrt()
    if volatility > policy.volatility_target:
        scale = policy.volatility_target / volatility
        for index, value in enumerate(weights):
            weights[index] = canonical_result(value * scale)
            reasons[index].append("AQ-PORTFOLIO-VOLATILITY-TARGET")
    _apply_group_constraints(
        weights=weights,
        signals=signals,
        constraints=policy.exposure_constraints,
        reasons=reasons,
    )
    capacities = _apply_capacity(
        weights=weights,
        signals=signals,
        nav=portfolio_nav,
        policy=policy,
        reasons=reasons,
    )
    _apply_turnover(
        weights=weights,
        signals=signals,
        maximum_turnover=policy.maximum_turnover,
        reasons=reasons,
    )
    _scale_all(weights, policy.maximum_gross_weight)
    _apply_group_constraints(
        weights=weights,
        signals=signals,
        constraints=policy.exposure_constraints,
        reasons=reasons,
    )
    _assert_constraints(
        weights=weights,
        signals=signals,
        capacities=capacities,
        policy=policy,
        covariance_matrix=ordered_matrix,
    )
    portfolio_variance = _portfolio_variance(weights, ordered_matrix)
    portfolio_volatility = portfolio_variance.sqrt()
    covariance_times_weight = [
        sum(
            (ordered_matrix[row][column] * weights[column] for column in range(len(weights))),
            start=ZERO,
        )
        for row in range(len(weights))
    ]
    legs: list[PortfolioLeg] = []
    for index, signal in enumerate(signals):
        delta = canonical_result(weights[index] - signal.current_weight)
        participation = (
            abs(delta) * portfolio_nav / signal.average_daily_notional
            if signal.average_daily_notional > ZERO
            else ZERO
        )
        curve = signal.impact_model or legacy_impact_model(
            signal.impact_coefficient_bps, capacity=True
        )
        impact = canonical_result(curve.impact_bps(participation))
        legs.append(
            PortfolioLeg(
                signal_id=signal.signal_id,
                asset_id=signal.asset_id,
                instrument_id=signal.instrument_id,
                strategy_id=signal.strategy_id,
                account_id=signal.account_id,
                sleeve_id=signal.sleeve_id,
                venue_id=signal.venue_id,
                stablecoin_id=signal.stablecoin_id,
                correlation_cluster_id=signal.correlation_cluster_id,
                current_weight=signal.current_weight,
                target_weight=weights[index],
                delta_weight=delta,
                normalized_signal=normalized[index].robust_score,
                expected_return_contribution=canonical_result(
                    weights[index] * signal.expected_return
                ),
                marginal_variance_contribution=canonical_result(
                    weights[index] * covariance_times_weight[index]
                ),
                estimated_impact_bps=impact,
                capacity_weight=capacities[index],
                constraint_reasons=tuple(dict.fromkeys(reasons[index])),
            )
        )
    proposal_payload = {
        "proposal_id": str(proposal_id),
        "policy_version": policy.version,
        "covariance_sha256": covariance.estimate_sha256,
        "as_of_time": as_of_time.isoformat(),
        "created_at": created_at.isoformat(),
        "legs": [leg.model_dump(mode="json") for leg in legs],
    }
    gross = sum((abs(item.target_weight) for item in legs), start=ZERO)
    turnover = sum((abs(item.delta_weight) for item in legs), start=ZERO)
    expected_return = sum((item.expected_return_contribution for item in legs), start=ZERO)
    objective = canonical_result(
        expected_return
        - policy.uncertainty_penalty * portfolio_variance
        - sum((item.estimated_impact_bps * abs(item.delta_weight) for item in legs), start=ZERO)
        / Decimal("10000")
    )
    return PortfolioProposal(
        proposal_id=proposal_id,
        policy_version=policy.version,
        covariance_sha256=covariance.estimate_sha256,
        proposal_sha256=canonical_sha256(proposal_payload),
        as_of_time=as_of_time,
        created_at=created_at,
        valid_until=created_at + timedelta(seconds=validity_seconds),
        environment_stage=policy.environment_stage,
        legs=tuple(legs),
        expected_return=expected_return,
        expected_volatility=portfolio_volatility,
        gross_weight=gross,
        turnover=turnover,
        objective_value=objective,
        constraint_summary=tuple(
            sorted({reason for leg_reasons in reasons for reason in leg_reasons})
        ),
    )
