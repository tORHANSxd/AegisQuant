"""Strict P11 portfolio construction inputs and proposal-only outputs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.entities import DeploymentStage
from aegisquant.domain.identifiers import (
    AccountId,
    AssetId,
    InstrumentId,
    ProposalId,
    SignalId,
    StrategyId,
    VenueId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    PositiveDecimal,
    UnitInterval,
    canonical_result,
)


class ExposureDimension(StrEnum):
    ASSET = "ASSET"
    CONTRACT = "CONTRACT"
    STRATEGY = "STRATEGY"
    SLEEVE = "SLEEVE"
    VENUE = "VENUE"
    STABLECOIN = "STABLECOIN"
    CORRELATION_CLUSTER = "CORRELATION_CLUSTER"


class RiskRegime(StrEnum):
    CALM = "CALM"
    NORMAL = "NORMAL"
    STRESSED = "STRESSED"
    CRISIS = "CRISIS"


class TargetQuantityAdjustment(DomainModel):
    target_quantity: NonNegativeDecimal
    current_quantity: NonNegativeDecimal
    signed_pending_quantity: FiniteDecimal
    signed_order_quantity: FiniteDecimal
    cancel_pending_first: bool
    reason: str


class SignalInput(DomainModel):
    signal_id: SignalId
    asset_id: AssetId
    instrument_id: InstrumentId
    strategy_id: StrategyId
    account_id: AccountId
    sleeve_id: str = Field(min_length=1, max_length=80)
    venue_id: VenueId
    stablecoin_id: AssetId | None = None
    correlation_cluster_id: str = Field(min_length=1, max_length=80)
    raw_score: FiniteDecimal
    confidence: UnitInterval
    expected_return: FiniteDecimal
    current_weight: FiniteDecimal
    average_daily_notional: NonNegativeDecimal
    impact_coefficient_bps: NonNegativeDecimal


class NormalizedSignal(DomainModel):
    signal: SignalInput
    clipped_score: FiniteDecimal
    discounted_score: FiniteDecimal
    robust_score: FiniteDecimal
    in_no_trade_zone: bool
    reason_codes: tuple[str, ...]


class FactorRisk(DomainModel):
    factor_id: str = Field(min_length=1, max_length=80)
    variance: NonNegativeDecimal
    exposures: dict[str, FiniteDecimal]

    @field_validator("exposures")
    @classmethod
    def require_exposures(cls, value: dict[str, FiniteDecimal]) -> dict[str, FiniteDecimal]:
        if not value:
            raise ValueError("factor risk requires asset exposures")
        return value


class CovarianceEstimate(DomainModel):
    asset_ids: tuple[AssetId, ...] = Field(min_length=1)
    matrix: tuple[tuple[FiniteDecimal, ...], ...] = Field(min_length=1)
    shrinkage: UnitInterval
    factor_ids: tuple[str, ...]
    regime: RiskRegime
    regime_multiplier: PositiveDecimal
    observed_at: UtcDateTime
    available_at: UtcDateTime
    estimate_sha256: str

    @field_validator("estimate_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="covariance estimate hash")

    @model_validator(mode="after")
    def validate_matrix(self) -> CovarianceEstimate:
        size = len(self.asset_ids)
        if len(set(self.asset_ids)) != size:
            raise ValueError("covariance assets must be unique")
        if len(self.matrix) != size or any(len(row) != size for row in self.matrix):
            raise ValueError("covariance matrix shape must match assets")
        for row_index, row in enumerate(self.matrix):
            if row[row_index] < 0:
                raise ValueError("covariance diagonal cannot be negative")
            for column_index, value in enumerate(row):
                if value != self.matrix[column_index][row_index]:
                    raise ValueError("covariance matrix must be symmetric")
        if self.available_at < self.observed_at:
            raise ValueError("covariance availability cannot precede observation")
        return self


class RiskBudget(DomainModel):
    asset_id: AssetId
    maximum_risk_share: UnitInterval


class ExposureConstraint(DomainModel):
    dimension: ExposureDimension
    key: str = Field(min_length=1, max_length=255)
    maximum_absolute_weight: NonNegativeDecimal


class PortfolioConstructionPolicy(DomainModel):
    version: str = Field(min_length=1, max_length=80)
    no_trade_zone: UnitInterval
    uncertainty_penalty: UnitInterval
    volatility_target: PositiveDecimal
    maximum_gross_weight: PositiveDecimal
    maximum_turnover: NonNegativeDecimal
    maximum_participation: UnitInterval
    maximum_impact_bps: NonNegativeDecimal
    risk_budgets: tuple[RiskBudget, ...] = Field(min_length=1)
    exposure_constraints: tuple[ExposureConstraint, ...] = Field(min_length=1)
    environment_stage: DeploymentStage = DeploymentStage.PAPER
    example_values_only: bool = True

    @model_validator(mode="after")
    def enforce_policy_shape(self) -> PortfolioConstructionPolicy:
        if len({item.asset_id for item in self.risk_budgets}) != len(self.risk_budgets):
            raise ValueError("risk budget assets must be unique")
        constraint_keys = {(item.dimension, item.key) for item in self.exposure_constraints}
        if len(constraint_keys) != len(self.exposure_constraints):
            raise ValueError("exposure constraints must be unique")
        if not self.example_values_only or self.environment_stage is not DeploymentStage.PAPER:
            raise ValueError("AQ-RISK-EXAMPLE-POLICY-PAPER-ONLY")
        return self


class PortfolioLeg(DomainModel):
    signal_id: SignalId
    asset_id: AssetId
    instrument_id: InstrumentId
    strategy_id: StrategyId
    account_id: AccountId
    sleeve_id: str
    venue_id: VenueId
    stablecoin_id: AssetId | None
    correlation_cluster_id: str
    current_weight: FiniteDecimal
    target_weight: FiniteDecimal
    delta_weight: FiniteDecimal
    normalized_signal: FiniteDecimal
    expected_return_contribution: FiniteDecimal
    marginal_variance_contribution: FiniteDecimal
    estimated_impact_bps: NonNegativeDecimal
    capacity_weight: NonNegativeDecimal
    constraint_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def validate_delta(self) -> PortfolioLeg:
        if self.delta_weight != canonical_result(self.target_weight - self.current_weight):
            raise ValueError("portfolio leg delta must equal target minus current")
        return self


class PortfolioProposal(DomainModel):
    proposal_id: ProposalId
    policy_version: str
    covariance_sha256: str
    proposal_sha256: str
    as_of_time: UtcDateTime
    created_at: UtcDateTime
    valid_until: UtcDateTime
    environment_stage: DeploymentStage
    legs: tuple[PortfolioLeg, ...] = Field(min_length=1)
    expected_return: FiniteDecimal
    expected_volatility: NonNegativeDecimal
    gross_weight: NonNegativeDecimal
    turnover: NonNegativeDecimal
    objective_value: FiniteDecimal
    constraint_summary: tuple[str, ...]
    order_capability: bool = False

    @field_validator("covariance_sha256", "proposal_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="portfolio proposal hash")

    @model_validator(mode="after")
    def validate_proposal(self) -> PortfolioProposal:
        if self.created_at < self.as_of_time or self.valid_until <= self.created_at:
            raise ValueError("proposal time interval is invalid")
        if self.environment_stage is not DeploymentStage.PAPER:
            raise ValueError("AQ-RISK-UNCONFIRMED-PAPER-ONLY")
        if self.order_capability:
            raise ValueError("portfolio proposals cannot create orders")
        if len({item.instrument_id for item in self.legs}) != len(self.legs):
            raise ValueError("portfolio proposal instruments must be unique")
        gross = sum((abs(item.target_weight) for item in self.legs), start=0)
        turnover = sum((abs(item.delta_weight) for item in self.legs), start=0)
        if self.gross_weight != gross or self.turnover != turnover:
            raise ValueError("portfolio proposal aggregates do not match legs")
        return self
