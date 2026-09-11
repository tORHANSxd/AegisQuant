"""Strict P11 portfolio construction inputs and proposal-only outputs."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

import numpy as np
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
from aegisquant.portfolio.transition_costs import ImpactModel


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
    impact_model: ImpactModel | None = Field(default=None, exclude_if=lambda value: value is None)
    liquidity_horizon_seconds: int | None = Field(
        default=None, gt=0, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_impact_binding(self) -> SignalInput:
        if self.impact_model is not None and (
            self.impact_model.coefficient_bps != self.impact_coefficient_bps
            or self.impact_model.horizon_seconds != self.liquidity_horizon_seconds
        ):
            raise ValueError("AQ-IMPACT-COEFFICIENT-OR-HORIZON-MISMATCH")
        if (self.impact_model is None) != (self.liquidity_horizon_seconds is None):
            raise ValueError("explicit impact requires a matching liquidity horizon")
        return self


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


def covariance_psd_check(
    asset_ids: tuple[AssetId, ...], matrix: tuple[tuple[Decimal, ...], ...]
) -> tuple[float, Decimal]:
    """Fixed relative tolerance, with a canonical asset order for numerical eigensolving."""
    order = sorted(range(len(asset_ids)), key=lambda index: str(asset_ids[index]))
    values = np.asarray([[float(matrix[i][j]) for j in order] for i in order])
    if not np.all(np.isfinite(values)):
        raise ValueError("AQ-COVARIANCE-FLOAT-RANGE")
    scale = max((abs(v) for row in matrix for v in row), default=Decimal("0"))
    tolerance = scale * Decimal("1e-12")
    minimum = float(np.linalg.eigvalsh(values)[0])
    if minimum < -float(tolerance):
        raise ValueError("AQ-COVARIANCE-NOT-PSD")
    return minimum, tolerance


class CovarianceInputContract(DomainModel):
    basis: Literal["TOTAL", "RESIDUAL"]
    return_frequency: Literal["UTC_DAILY"] = "UTC_DAILY"
    input_unit: Literal["DAILY_DECIMAL_RETURN_COVARIANCE"] = "DAILY_DECIMAL_RETURN_COVARIANCE"
    output_unit: Literal["ANNUALIZED_DECIMAL_RETURN_COVARIANCE"] = (
        "ANNUALIZED_DECIMAL_RETURN_COVARIANCE"
    )
    annualization_days: PositiveDecimal = Decimal("365.25")
    complete_calendar_observations: int = Field(ge=2)
    missing_asset_policy: Literal["FAIL_CLOSED"] = "FAIL_CLOSED"
    factor_structure: Literal["ORTHOGONAL_DEFINED_FACTORS"] = "ORTHOGONAL_DEFINED_FACTORS"
    input_sha256: str

    @field_validator("input_sha256")
    @classmethod
    def validate_input_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="covariance input hash")


class CovarianceEvidence(DomainModel):
    contract: CovarianceInputContract
    minimum_sample_eigenvalue: FiniteDecimal
    diagonal_jitter: NonNegativeDecimal
    correction_frobenius_norm: NonNegativeDecimal
    psd_rule: Literal["REJECT_BELOW_REL_1E12_ELSE_FIXED_DIAGONAL_JITTER"] = (
        "REJECT_BELOW_REL_1E12_ELSE_FIXED_DIAGONAL_JITTER"
    )


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
    evidence: CovarianceEvidence | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

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
        covariance_psd_check(self.asset_ids, self.matrix)
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
