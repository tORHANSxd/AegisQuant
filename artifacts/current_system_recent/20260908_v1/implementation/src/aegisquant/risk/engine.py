"""Independent circuit-breaker, portfolio decision, and Paper pre-trade gates."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TypedDict

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.entities import DeploymentStage
from aegisquant.domain.execution import OrderIntent
from aegisquant.domain.identifiers import (
    IdempotencyKey,
    OrderIntentId,
    ProposalId,
    RiskDecisionId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import canonical_result
from aegisquant.portfolio.models import PortfolioProposal
from aegisquant.risk.models import (
    ApprovedTarget,
    CircuitBreakerOutcome,
    CircuitBreakerType,
    PreTradeRequest,
    RiskAlert,
    RiskConfirmation,
    RiskDecision,
    RiskDecisionStatus,
    RiskEvent,
    RiskPosition,
    RiskSnapshot,
    RiskState,
)
from aegisquant.risk.policy import RiskPolicy, SignedRiskPolicy, verify_signed_risk_policy

ZERO = Decimal("0")
ONE = Decimal("1")
STATE_RANK = {
    RiskState.NORMAL: 0,
    RiskState.CAUTION: 1,
    RiskState.REDUCE_ONLY: 2,
    RiskState.HALTED: 3,
}


class _DecisionBase(TypedDict):
    risk_decision_id: RiskDecisionId
    proposal_id: ProposalId
    proposal_sha256: str
    snapshot_id: str
    snapshot_sha256: str
    policy_version: str
    policy_sha256: str
    decided_at: UtcDateTime
    valid_until: UtcDateTime
    state: RiskState
    reason_codes: tuple[str, ...]


def build_risk_snapshot(
    *,
    snapshot_id: str,
    as_of_time: UtcDateTime,
    available_at: UtcDateTime,
    data_last_available_at: UtcDateTime,
    model_last_available_at: UtcDateTime,
    positions: tuple[RiskPosition, ...],
    daily_pnl_fraction: Decimal,
    drawdown_fraction: Decimal,
    margin_utilization: Decimal,
    liquidity_score: Decimal,
    venue_operational: bool,
    security_clear: bool,
    major_event_clear: bool,
    ledger_reconciled: bool,
) -> RiskSnapshot:
    gross = sum((abs(item.signed_weight) for item in positions), start=ZERO)
    payload = {
        "snapshot_id": snapshot_id,
        "as_of_time": as_of_time.isoformat(),
        "available_at": available_at.isoformat(),
        "data_last_available_at": data_last_available_at.isoformat(),
        "model_last_available_at": model_last_available_at.isoformat(),
        "positions": [item.model_dump(mode="json") for item in positions],
        "daily_pnl_fraction": str(daily_pnl_fraction),
        "drawdown_fraction": str(drawdown_fraction),
        "margin_utilization": str(margin_utilization),
        "liquidity_score": str(liquidity_score),
        "venue_operational": venue_operational,
        "security_clear": security_clear,
        "major_event_clear": major_event_clear,
        "ledger_reconciled": ledger_reconciled,
    }
    return RiskSnapshot(
        snapshot_id=snapshot_id,
        as_of_time=as_of_time,
        available_at=available_at,
        data_last_available_at=data_last_available_at,
        model_last_available_at=model_last_available_at,
        positions=positions,
        portfolio_gross_weight=gross,
        daily_pnl_fraction=daily_pnl_fraction,
        drawdown_fraction=drawdown_fraction,
        margin_utilization=margin_utilization,
        liquidity_score=liquidity_score,
        venue_operational=venue_operational,
        security_clear=security_clear,
        major_event_clear=major_event_clear,
        ledger_reconciled=ledger_reconciled,
        snapshot_sha256=canonical_sha256(payload),
    )


def _alert(
    *, breaker: CircuitBreakerType, state: RiskState, reason: str, at: UtcDateTime
) -> RiskAlert:
    return RiskAlert(
        alert_id=f"{breaker.value.lower()}:{int(at.timestamp())}",
        breaker_type=breaker,
        state=state,
        reason_code=reason,
        evidence_ids=(reason,),
        created_at=at,
    )


def evaluate_circuit_breakers(
    *,
    snapshot: RiskSnapshot,
    policy: RiskPolicy,
    decision_time: UtcDateTime,
    events: tuple[RiskEvent, ...] = (),
) -> CircuitBreakerOutcome:
    if snapshot.available_at > decision_time:
        raise ValueError("AQ-RISK-FUTURE-SNAPSHOT")
    if any(event.available_at > decision_time for event in events):
        raise ValueError("AQ-RISK-FUTURE-EVENT")
    triggers: list[tuple[CircuitBreakerType, RiskState, str]] = []
    maximum_age = timedelta(seconds=policy.snapshot_max_age_seconds)
    if decision_time - snapshot.data_last_available_at > maximum_age:
        triggers.append((CircuitBreakerType.DATA, RiskState.CAUTION, "AQ-RISK-DATA-STALE"))
    if decision_time - snapshot.model_last_available_at > maximum_age:
        triggers.append((CircuitBreakerType.MODEL, RiskState.CAUTION, "AQ-RISK-MODEL-STALE"))
    if snapshot.daily_pnl_fraction <= -policy.maximum_daily_loss_fraction:
        triggers.append((CircuitBreakerType.LOSS, RiskState.REDUCE_ONLY, "AQ-RISK-LOSS-LIMIT"))
    if snapshot.drawdown_fraction >= policy.maximum_drawdown_fraction:
        triggers.append((CircuitBreakerType.LOSS, RiskState.REDUCE_ONLY, "AQ-RISK-DRAWDOWN-LIMIT"))
    if snapshot.margin_utilization >= policy.maximum_margin_utilization:
        triggers.append((CircuitBreakerType.MARGIN, RiskState.REDUCE_ONLY, "AQ-RISK-MARGIN-LIMIT"))
    if snapshot.liquidity_score <= policy.minimum_liquidity_score:
        triggers.append(
            (CircuitBreakerType.LIQUIDITY, RiskState.REDUCE_ONLY, "AQ-RISK-LIQUIDITY-LIMIT")
        )
    if not snapshot.venue_operational:
        triggers.append((CircuitBreakerType.VENUE, RiskState.HALTED, "AQ-RISK-VENUE-HALTED"))
    if not snapshot.security_clear:
        triggers.append((CircuitBreakerType.SECURITY, RiskState.HALTED, "AQ-RISK-SECURITY-HALTED"))
    if not snapshot.major_event_clear:
        triggers.append(
            (
                CircuitBreakerType.MAJOR_EVENT,
                RiskState.REDUCE_ONLY,
                "AQ-RISK-MAJOR-EVENT-UNCLEARED",
            )
        )
    for event in events:
        if event.confirmation is RiskConfirmation.RUMOR:
            triggers.append(
                (CircuitBreakerType.MAJOR_EVENT, RiskState.CAUTION, "AQ-RISK-RUMOR-MONITOR")
            )
        elif event.action.value == "HALT":
            triggers.append(
                (CircuitBreakerType.MAJOR_EVENT, RiskState.HALTED, "AQ-RISK-PLAYBOOK-HALT")
            )
        else:
            triggers.append(
                (
                    CircuitBreakerType.MAJOR_EVENT,
                    RiskState.REDUCE_ONLY,
                    "AQ-RISK-PLAYBOOK-REDUCE",
                )
            )
    state = max(
        (item[1] for item in triggers), key=lambda item: STATE_RANK[item], default=RiskState.NORMAL
    )
    new_risk_allowed = state is RiskState.NORMAL
    target_scale = {
        RiskState.NORMAL: ONE,
        RiskState.CAUTION: policy.caution_target_scale,
        RiskState.REDUCE_ONLY: ZERO,
        RiskState.HALTED: ZERO,
    }[state]
    return CircuitBreakerOutcome(
        state=state,
        new_risk_allowed=new_risk_allowed,
        target_scale=target_scale,
        reason_codes=tuple(item[2] for item in triggers) or ("AQ-RISK-NORMAL",),
        alerts=tuple(
            _alert(breaker=item[0], state=item[1], reason=item[2], at=decision_time)
            for item in triggers
        ),
    )


def _group_gross(targets: list[ApprovedTarget], attribute: str, key: object) -> Decimal:
    return sum(
        (abs(item.approved_target_weight) for item in targets if getattr(item, attribute) == key),
        start=ZERO,
    )


def _scale_group(
    targets: list[ApprovedTarget], *, attribute: str, key: object, maximum: Decimal
) -> list[ApprovedTarget]:
    gross = _group_gross(targets, attribute, key)
    if gross <= maximum:
        return targets
    scale = maximum / gross
    output: list[ApprovedTarget] = []
    for item in targets:
        if getattr(item, attribute) != key:
            output.append(item)
            continue
        approved = canonical_result(item.approved_target_weight * scale)
        output.append(
            item.model_copy(
                update={
                    "approved_target_weight": approved,
                    "approved_delta_weight": canonical_result(approved - item.current_weight),
                }
            )
        )
    return output


def _apply_policy_limits(targets: list[ApprovedTarget], policy: RiskPolicy) -> list[ApprovedTarget]:
    limited: list[ApprovedTarget] = []
    for item in targets:
        delta = item.approved_delta_weight
        maximum = policy.pre_trade_limits.maximum_order_weight
        if abs(delta) > maximum:
            direction = ONE if delta > ZERO else Decimal("-1")
            approved = canonical_result(item.current_weight + direction * maximum)
            item = item.model_copy(
                update={
                    "approved_target_weight": approved,
                    "approved_delta_weight": canonical_result(approved - item.current_weight),
                }
            )
        limited.append(item)
    groups = (
        ("asset_id", policy.pre_trade_limits.maximum_asset_gross_weight),
        ("strategy_id", policy.pre_trade_limits.maximum_strategy_gross_weight),
        ("account_id", policy.pre_trade_limits.maximum_account_gross_weight),
    )
    for attribute, maximum in groups:
        for key in {getattr(item, attribute) for item in limited}:
            limited = _scale_group(limited, attribute=attribute, key=key, maximum=maximum)
    for item in limited:
        if abs(item.approved_delta_weight) > policy.pre_trade_limits.maximum_order_weight:
            raise ValueError("AQ-RISK-POLICY-LIMITS-INFEASIBLE")
    return limited


def evaluate_portfolio_proposal(
    *,
    proposal: PortfolioProposal,
    snapshot: RiskSnapshot,
    signed_policy: SignedRiskPolicy,
    trusted_public_keys: dict[str, bytes],
    decision_time: UtcDateTime,
    events: tuple[RiskEvent, ...] = (),
    decision_validity_seconds: int = 30,
) -> RiskDecision:
    policy = verify_signed_risk_policy(
        signed_policy,
        trusted_public_keys=trusted_public_keys,
        decision_time=decision_time,
        deployment_stage=proposal.environment_stage,
    )
    if proposal.valid_until <= decision_time or decision_validity_seconds <= 0:
        raise ValueError("AQ-RISK-PROPOSAL-EXPIRED")
    if snapshot.as_of_time < proposal.as_of_time:
        raise ValueError("AQ-RISK-SNAPSHOT-PREDATES-PROPOSAL")
    outcome = evaluate_circuit_breakers(
        snapshot=snapshot, policy=policy, decision_time=decision_time, events=events
    )
    decision_id = RiskDecisionId.from_content(
        f"{proposal.proposal_sha256}:{snapshot.snapshot_sha256}:{signed_policy.policy_sha256}:{decision_time.isoformat()}".encode()
    )
    common: _DecisionBase = {
        "risk_decision_id": decision_id,
        "proposal_id": proposal.proposal_id,
        "proposal_sha256": proposal.proposal_sha256,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_sha256": snapshot.snapshot_sha256,
        "policy_version": policy.version,
        "policy_sha256": signed_policy.policy_sha256,
        "decided_at": decision_time,
        "valid_until": decision_time + timedelta(seconds=decision_validity_seconds),
        "state": outcome.state,
        "reason_codes": outcome.reason_codes,
    }
    if outcome.state is RiskState.HALTED:
        return RiskDecision(
            **common,
            status=RiskDecisionStatus.HALTED,
            new_risk_allowed=False,
            approved_targets=(),
        )
    position_by_instrument = {item.instrument_id: item for item in snapshot.positions}
    if any(
        leg.current_weight
        != position_by_instrument.get(
            leg.instrument_id,
            RiskPosition(
                instrument_id=leg.instrument_id,
                asset_id=leg.asset_id,
                strategy_id=leg.strategy_id,
                account_id=leg.account_id,
                signed_weight=ZERO,
            ),
        ).signed_weight
        for leg in proposal.legs
    ):
        raise ValueError("AQ-RISK-PROPOSAL-SNAPSHOT-POSITION-MISMATCH")
    if outcome.state is RiskState.CAUTION:
        return RiskDecision(
            **common,
            status=RiskDecisionStatus.REJECTED,
            new_risk_allowed=False,
            approved_targets=(),
        )
    targets: list[ApprovedTarget] = []
    for leg in proposal.legs:
        approved = leg.target_weight
        if outcome.state is RiskState.REDUCE_ONLY:
            same_side = leg.current_weight == ZERO or approved * leg.current_weight >= ZERO
            if not same_side or abs(approved) >= abs(leg.current_weight):
                approved = leg.current_weight
        targets.append(
            ApprovedTarget(
                instrument_id=leg.instrument_id,
                asset_id=leg.asset_id,
                strategy_id=leg.strategy_id,
                account_id=leg.account_id,
                current_weight=leg.current_weight,
                proposed_target_weight=leg.target_weight,
                approved_target_weight=approved,
                approved_delta_weight=canonical_result(approved - leg.current_weight),
            )
        )
    targets = _apply_policy_limits(targets, policy)
    if outcome.state is RiskState.REDUCE_ONLY:
        targets = [item for item in targets if item.approved_delta_weight != ZERO]
        return RiskDecision(
            **common,
            status=RiskDecisionStatus.REDUCE_ONLY,
            new_risk_allowed=False,
            approved_targets=tuple(targets),
        )
    return RiskDecision(
        **common,
        status=RiskDecisionStatus.APPROVED,
        new_risk_allowed=True,
        approved_targets=tuple(targets),
    )


def _post_trade_positions(
    snapshot: RiskSnapshot, target: ApprovedTarget, requested_delta: Decimal
) -> tuple[RiskPosition, ...]:
    post_weight = canonical_result(target.current_weight + requested_delta)
    existing = {item.instrument_id: item for item in snapshot.positions}
    existing[target.instrument_id] = RiskPosition(
        instrument_id=target.instrument_id,
        asset_id=target.asset_id,
        strategy_id=target.strategy_id,
        account_id=target.account_id,
        signed_weight=post_weight,
    )
    return tuple(existing[key] for key in sorted(existing, key=str))


def create_paper_order_intent(
    *,
    request: PreTradeRequest,
    proposal: PortfolioProposal,
    decision: RiskDecision,
    snapshot: RiskSnapshot,
    signed_policy: SignedRiskPolicy,
    trusted_public_keys: dict[str, bytes],
) -> OrderIntent:
    policy = verify_signed_risk_policy(
        signed_policy,
        trusted_public_keys=trusted_public_keys,
        decision_time=request.created_at,
        deployment_stage=DeploymentStage.PAPER,
    )
    if proposal.environment_stage is not DeploymentStage.PAPER:
        raise ValueError("AQ-RISK-UNCONFIRMED-PAPER-ONLY")
    if request.valid_until <= request.created_at or decision.valid_until <= request.created_at:
        raise ValueError("AQ-RISK-PRETRADE-EXPIRED")
    if request.proposal_id != proposal.proposal_id or decision.proposal_id != proposal.proposal_id:
        raise ValueError("AQ-RISK-PRETRADE-PROPOSAL-MISMATCH")
    if decision.proposal_sha256 != proposal.proposal_sha256:
        raise ValueError("AQ-RISK-PRETRADE-PROPOSAL-HASH-MISMATCH")
    if request.risk_decision_id != decision.risk_decision_id:
        raise ValueError("AQ-RISK-PRETRADE-DECISION-MISMATCH")
    if (
        decision.snapshot_id != snapshot.snapshot_id
        or decision.snapshot_sha256 != snapshot.snapshot_sha256
    ):
        raise ValueError("AQ-RISK-PRETRADE-SNAPSHOT-MISMATCH")
    if decision.policy_sha256 != signed_policy.policy_sha256:
        raise ValueError("AQ-RISK-PRETRADE-POLICY-MISMATCH")
    if decision.status not in {RiskDecisionStatus.APPROVED, RiskDecisionStatus.REDUCE_ONLY}:
        raise ValueError("AQ-RISK-PRETRADE-DECISION-NOT-ACTIONABLE")
    target = next(
        (item for item in decision.approved_targets if item.instrument_id == request.instrument_id),
        None,
    )
    if target is None:
        raise ValueError("AQ-RISK-PRETRADE-TARGET-NOT-APPROVED")
    if (
        target.asset_id != request.asset_id
        or target.strategy_id != request.strategy_id
        or target.account_id != request.account_id
    ):
        raise ValueError("AQ-RISK-PRETRADE-SCOPE-MISMATCH")
    approved_delta = target.approved_delta_weight
    if (
        approved_delta == ZERO
        or request.requested_delta_weight * approved_delta <= ZERO
        or abs(request.requested_delta_weight) > abs(approved_delta)
    ):
        raise ValueError("AQ-RISK-PRETRADE-AMPLIFIES-APPROVED-TARGET")
    post_weight = canonical_result(target.current_weight + request.requested_delta_weight)
    if decision.status is RiskDecisionStatus.REDUCE_ONLY and (
        abs(post_weight) >= abs(target.current_weight) or target.current_weight * post_weight < ZERO
    ):
        raise ValueError("AQ-RISK-REDUCE-ONLY-VIOLATION")
    limits = policy.pre_trade_limits
    if abs(request.requested_delta_weight) > limits.maximum_order_weight:
        raise ValueError("AQ-RISK-PRETRADE-ORDER-LIMIT")
    positions = _post_trade_positions(snapshot, target, request.requested_delta_weight)
    asset_gross = sum(
        (abs(item.signed_weight) for item in positions if item.asset_id == request.asset_id),
        start=ZERO,
    )
    strategy_gross = sum(
        (abs(item.signed_weight) for item in positions if item.strategy_id == request.strategy_id),
        start=ZERO,
    )
    account_gross = sum(
        (abs(item.signed_weight) for item in positions if item.account_id == request.account_id),
        start=ZERO,
    )
    if asset_gross > limits.maximum_asset_gross_weight:
        raise ValueError("AQ-RISK-PRETRADE-ASSET-LIMIT")
    if strategy_gross > limits.maximum_strategy_gross_weight:
        raise ValueError("AQ-RISK-PRETRADE-STRATEGY-LIMIT")
    if account_gross > limits.maximum_account_gross_weight:
        raise ValueError("AQ-RISK-PRETRADE-ACCOUNT-LIMIT")
    identity = canonical_sha256(
        {
            "request": request.model_dump(mode="json"),
            "proposal_sha256": proposal.proposal_sha256,
            "risk_decision_id": str(decision.risk_decision_id),
        }
    )
    return OrderIntent(
        order_intent_id=OrderIntentId(identity),
        risk_decision_id=decision.risk_decision_id,
        instrument_id=request.instrument_id,
        side=request.side,
        order_type=request.order_type,
        quantity=request.quantity,
        limit_price=request.limit_price,
        time_in_force=request.time_in_force,
        reduce_only=decision.status is RiskDecisionStatus.REDUCE_ONLY,
        created_at=request.created_at,
        valid_until=min(request.valid_until, decision.valid_until),
        idempotency_key=IdempotencyKey(identity),
    )
