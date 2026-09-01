"""Deterministic non-production P11 portfolio and risk fixtures."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegisquant.domain.identifiers import (
    AccountId,
    AssetId,
    InstrumentId,
    ProposalId,
    SignalId,
    StrategyId,
    VenueId,
)
from aegisquant.portfolio.models import (
    ExposureConstraint,
    ExposureDimension,
    FactorRisk,
    PortfolioConstructionPolicy,
    PortfolioProposal,
    RiskBudget,
    RiskRegime,
    SignalInput,
)
from aegisquant.portfolio.optimizer import build_portfolio_proposal
from aegisquant.portfolio.risk_estimation import estimate_covariance
from aegisquant.risk.engine import build_risk_snapshot
from aegisquant.risk.models import (
    MajorEventType,
    RiskAction,
    RiskPosition,
    RiskSnapshot,
    RiskState,
)
from aegisquant.risk.playbooks import (
    RiskPlaybook,
    RiskPlaybookRegistry,
    SignedRiskPlaybookRegistry,
    playbook_registry_payload,
    playbook_registry_sha256,
)
from aegisquant.risk.policy import (
    PreTradeLimits,
    RecoveryCondition,
    RiskPolicy,
    SignedRiskPolicy,
    risk_policy_payload,
    risk_policy_sha256,
)

AS_OF = datetime(2026, 9, 1, 18, tzinfo=UTC)
CREATED = AS_OF + timedelta(seconds=1)
DECISION_TIME = AS_OF + timedelta(seconds=2)
BTC = AssetId("BTC")
ETH = AssetId("ETH")
USDT = AssetId("USDT")
VENUE = VenueId("paper-venue")
ACCOUNT = AccountId("paper-account")
STRATEGY = StrategyId("strategy-core")
SIGNER_KEY_ID = "p11-fixture-signer"


def fixture_private_key() -> Ed25519PrivateKey:
    seed = hashlib.sha256(b"AegisQuant P11 deterministic non-production fixture key").digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def trusted_public_keys() -> dict[str, bytes]:
    public = (
        fixture_private_key()
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return {SIGNER_KEY_ID: public}


def signal(
    *,
    asset: AssetId,
    instrument: str,
    raw_score: Decimal,
    confidence: Decimal,
    current_weight: Decimal = Decimal("0"),
    adv: Decimal = Decimal("1000000"),
    impact_bps: Decimal = Decimal("10"),
    strategy: StrategyId = STRATEGY,
    account: AccountId = ACCOUNT,
    sleeve: str = "core",
    cluster: str = "large-cap",
) -> SignalInput:
    return SignalInput(
        signal_id=SignalId(f"signal-{instrument}"),
        asset_id=asset,
        instrument_id=InstrumentId(instrument),
        strategy_id=strategy,
        account_id=account,
        sleeve_id=sleeve,
        venue_id=VENUE,
        stablecoin_id=USDT,
        correlation_cluster_id=cluster,
        raw_score=raw_score,
        confidence=confidence,
        expected_return=raw_score / Decimal("100"),
        current_weight=current_weight,
        average_daily_notional=adv,
        impact_coefficient_bps=impact_bps,
    )


def signals() -> tuple[SignalInput, ...]:
    return (
        signal(
            asset=BTC,
            instrument="BTC-USDT-PERP",
            raw_score=Decimal("0.8"),
            confidence=Decimal("0.75"),
        ),
        signal(
            asset=ETH,
            instrument="ETH-USDT-PERP",
            raw_score=Decimal("-0.4"),
            confidence=Decimal("0.5"),
        ),
    )


def construction_policy() -> PortfolioConstructionPolicy:
    return PortfolioConstructionPolicy(
        version="p11-portfolio-fixture-v1",
        no_trade_zone=Decimal("0.05"),
        uncertainty_penalty=Decimal("0.25"),
        volatility_target=Decimal("0.25"),
        maximum_gross_weight=Decimal("0.60"),
        maximum_turnover=Decimal("0.40"),
        maximum_participation=Decimal("0.10"),
        maximum_impact_bps=Decimal("20"),
        risk_budgets=(
            RiskBudget(asset_id=BTC, maximum_risk_share=Decimal("0.50")),
            RiskBudget(asset_id=ETH, maximum_risk_share=Decimal("0.50")),
        ),
        exposure_constraints=(
            ExposureConstraint(
                dimension=ExposureDimension.ASSET,
                key="BTC",
                maximum_absolute_weight=Decimal("0.30"),
            ),
            ExposureConstraint(
                dimension=ExposureDimension.ASSET,
                key="ETH",
                maximum_absolute_weight=Decimal("0.30"),
            ),
            ExposureConstraint(
                dimension=ExposureDimension.CONTRACT,
                key="BTC-USDT-PERP",
                maximum_absolute_weight=Decimal("0.25"),
            ),
            ExposureConstraint(
                dimension=ExposureDimension.STRATEGY,
                key="strategy-core",
                maximum_absolute_weight=Decimal("0.50"),
            ),
            ExposureConstraint(
                dimension=ExposureDimension.SLEEVE,
                key="core",
                maximum_absolute_weight=Decimal("0.50"),
            ),
            ExposureConstraint(
                dimension=ExposureDimension.VENUE,
                key="paper-venue",
                maximum_absolute_weight=Decimal("0.50"),
            ),
            ExposureConstraint(
                dimension=ExposureDimension.STABLECOIN,
                key="USDT",
                maximum_absolute_weight=Decimal("0.50"),
            ),
            ExposureConstraint(
                dimension=ExposureDimension.CORRELATION_CLUSTER,
                key="large-cap",
                maximum_absolute_weight=Decimal("0.45"),
            ),
        ),
    )


def covariance():
    return estimate_covariance(
        asset_ids=(BTC, ETH),
        sample_covariance=(
            (Decimal("0.04"), Decimal("0.02")),
            (Decimal("0.02"), Decimal("0.09")),
        ),
        shrinkage=Decimal("0.50"),
        factors=(
            FactorRisk(
                factor_id="market",
                variance=Decimal("0.01"),
                exposures={"BTC": Decimal("1"), "ETH": Decimal("0.5")},
            ),
        ),
        regime=RiskRegime.STRESSED,
        regime_multiplier=Decimal("2"),
        observed_at=AS_OF - timedelta(seconds=1),
        available_at=AS_OF,
    )


def proposal(*, custom_signals: tuple[SignalInput, ...] | None = None) -> PortfolioProposal:
    return build_portfolio_proposal(
        proposal_id=ProposalId("proposal-p11-fixture"),
        signals=custom_signals or signals(),
        covariance=covariance(),
        policy=construction_policy(),
        portfolio_nav=Decimal("100000"),
        as_of_time=AS_OF,
        created_at=CREATED,
        validity_seconds=120,
    )


def risk_policy() -> RiskPolicy:
    return RiskPolicy(
        policy_id="risk-policy-p11-fixture",
        version="p11-risk-fixture-v1",
        effective_at=AS_OF - timedelta(days=1),
        expires_at=AS_OF + timedelta(days=1),
        snapshot_max_age_seconds=30,
        caution_target_scale=Decimal("0.50"),
        maximum_daily_loss_fraction=Decimal("0.05"),
        maximum_drawdown_fraction=Decimal("0.10"),
        maximum_margin_utilization=Decimal("0.80"),
        minimum_liquidity_score=Decimal("0.20"),
        maximum_rumor_reduction_fraction=Decimal("0.25"),
        pre_trade_limits=PreTradeLimits(
            maximum_order_weight=Decimal("0.30"),
            maximum_asset_gross_weight=Decimal("0.40"),
            maximum_strategy_gross_weight=Decimal("0.60"),
            maximum_account_gross_weight=Decimal("0.60"),
        ),
        recovery_conditions=tuple(RecoveryCondition),
    )


def signed_policy() -> SignedRiskPolicy:
    policy = risk_policy()
    signature = fixture_private_key().sign(risk_policy_payload(policy)).hex()
    return SignedRiskPolicy(
        policy=policy,
        policy_sha256=risk_policy_sha256(policy),
        signer_key_id=SIGNER_KEY_ID,
        signature_hex=signature,
    )


def snapshot(
    *,
    portfolio: PortfolioProposal | None = None,
    stale_seconds: int = 0,
    daily_pnl: Decimal = Decimal("0"),
    drawdown: Decimal = Decimal("0"),
    margin: Decimal = Decimal("0.20"),
    liquidity: Decimal = Decimal("0.90"),
    venue_operational: bool = True,
    security_clear: bool = True,
    major_event_clear: bool = True,
) -> RiskSnapshot:
    selected = portfolio or proposal()
    positions = tuple(
        RiskPosition(
            instrument_id=leg.instrument_id,
            asset_id=leg.asset_id,
            strategy_id=leg.strategy_id,
            account_id=leg.account_id,
            signed_weight=leg.current_weight,
        )
        for leg in selected.legs
    )
    last_available = AS_OF - timedelta(seconds=stale_seconds)
    return build_risk_snapshot(
        snapshot_id="snapshot-p11-fixture",
        as_of_time=AS_OF,
        available_at=CREATED,
        data_last_available_at=last_available,
        model_last_available_at=last_available,
        positions=positions,
        daily_pnl_fraction=daily_pnl,
        drawdown_fraction=drawdown,
        margin_utilization=margin,
        liquidity_score=liquidity,
        venue_operational=venue_operational,
        security_clear=security_clear,
        major_event_clear=major_event_clear,
        ledger_reconciled=True,
    )


def playbook_registry() -> RiskPlaybookRegistry:
    return RiskPlaybookRegistry(
        version="p11-playbooks-fixture-v1",
        playbooks=(
            RiskPlaybook(
                playbook_id="official-security-halt",
                event_type=MajorEventType.OFFICIAL_SECURITY_INCIDENT,
                action=RiskAction.HALT,
                target_state=RiskState.HALTED,
                reduction_fraction=Decimal("0"),
                reason_code="AQ-RISK-OFFICIAL-SECURITY-HALT",
            ),
            RiskPlaybook(
                playbook_id="withdrawal-reduce",
                event_type=MajorEventType.WITHDRAWAL_SUSPENSION,
                action=RiskAction.REDUCE,
                target_state=RiskState.REDUCE_ONLY,
                reduction_fraction=Decimal("0.50"),
                reason_code="AQ-RISK-WITHDRAWAL-REDUCE",
            ),
            RiskPlaybook(
                playbook_id="stablecoin-reduce",
                event_type=MajorEventType.STABLECOIN_DEPEG,
                action=RiskAction.REDUCE,
                target_state=RiskState.REDUCE_ONLY,
                reduction_fraction=Decimal("0.75"),
                reason_code="AQ-RISK-STABLECOIN-REDUCE",
            ),
            RiskPlaybook(
                playbook_id="regulatory-caution",
                event_type=MajorEventType.MAJOR_REGULATORY,
                action=RiskAction.TIGHTEN_LIMITS,
                target_state=RiskState.CAUTION,
                reduction_fraction=Decimal("0"),
                reason_code="AQ-RISK-REGULATORY-CAUTION",
            ),
            RiskPlaybook(
                playbook_id="infrastructure-halt",
                event_type=MajorEventType.INFRASTRUCTURE_OUTAGE,
                action=RiskAction.HALT,
                target_state=RiskState.HALTED,
                reduction_fraction=Decimal("0"),
                reason_code="AQ-RISK-INFRASTRUCTURE-HALT",
            ),
        ),
    )


def signed_playbooks() -> SignedRiskPlaybookRegistry:
    registry = playbook_registry()
    signature = fixture_private_key().sign(playbook_registry_payload(registry)).hex()
    return SignedRiskPlaybookRegistry(
        registry=registry,
        registry_sha256=playbook_registry_sha256(registry),
        signer_key_id=SIGNER_KEY_ID,
        signature_hex=signature,
    )
