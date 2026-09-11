"""Fail-closed V5 decision integration from governed forecast to independent risk."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, cast

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.evidence import EvidenceTier
from aegisquant.domain.identifiers import AssetId, InstrumentId, SignalId
from aegisquant.domain.intelligence import EventClusterStatus, QualityState
from aegisquant.domain.time import UtcDateTime, assert_point_in_time
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    PositiveDecimal,
    UnitInterval,
    canonical_result,
)
from aegisquant.portfolio.models import PortfolioProposal
from aegisquant.research.forecasting.contracts import CouncilHorizon, MarketRegime
from aegisquant.research.forecasting.event import EventIncrement
from aegisquant.research.forecasting.governance import (
    CalibrationDriftAction,
    ForecastGovernanceReport,
)
from aegisquant.risk.models import RiskDecision, RiskDecisionStatus


class PositionDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class MakerQueueMode(StrEnum):
    CONSERVATIVE_QUEUE = "CONSERVATIVE_QUEUE"
    REPLAY_QUEUE = "REPLAY_QUEUE"


class CostCalibrationState(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    MISCALIBRATED = "MISCALIBRATED"


class NetEdgeThresholdSource(StrEnum):
    BOOTSTRAP = "BOOTSTRAP"
    OOS = "OOS"


class DecisionOutcome(StrEnum):
    DIRECTIONAL_ALPHA = "DIRECTIONAL_ALPHA"
    RISK_OVERLAY_ONLY = "RISK_OVERLAY_ONLY"
    NO_TRADE = "NO_TRADE"


class RiskOverlayAction(StrEnum):
    REDUCE_EXPOSURE = "REDUCE_EXPOSURE"
    REDUCE_LEVERAGE = "REDUCE_LEVERAGE"
    PAUSE_NEW_RISK = "PAUSE_NEW_RISK"
    CANCEL_MAKER_ORDERS = "CANCEL_MAKER_ORDERS"
    RAISE_LIQUIDITY_BUFFER = "RAISE_LIQUIDITY_BUFFER"


class ExecutionCostComponent(StrEnum):
    FEE = "fee"
    SPREAD = "spread"
    SLIPPAGE = "slippage"
    MARKET_IMPACT = "market_impact"
    QUEUE_PROBABILITY = "queue_probability"
    MAKER_ADVERSE_SELECTION = "maker_adverse_selection"
    LATENCY_COST = "latency_cost"
    FUNDING = "funding"
    BORROW = "borrow"
    SETTLEMENT = "settlement"
    LIQUIDATION_RISK = "liquidation_risk"


REQUIRED_EXECUTION_COST_COMPONENTS = tuple(ExecutionCostComponent)
REQUIRED_EXECUTION_ENVIRONMENTS = ("BACKTEST", "PAPER", "LIVE")
REQUIRED_OVERLAY_ACTIONS = tuple(RiskOverlayAction)
DECISION_PIPELINE = (
    "FORECAST",
    "TRUTH_GATE",
    "PRICE_IN_GATE",
    "COST",
    "NET_EDGE",
    "PORTFOLIO",
    "RISK",
)


class ReplayQueueInputs(DomainModel):
    l2_snapshots_sha256: str
    l2_deltas_sha256: str
    trades_sha256: str
    order_arrival_sha256: str
    cancel_replace_sha256: str
    queue_ahead_sha256: str

    @field_validator("*")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return ensure_sha256(value, field_name="replay queue input hash")


class ExecutionCostModelV2(DomainModel):
    version: str = Field(min_length=1, max_length=80)
    queue_mode: MakerQueueMode
    replay_inputs: ReplayQueueInputs | None = None
    calibration_state: CostCalibrationState
    tca_artifact_sha256: str | None = None
    tca_sample_count: int = Field(ge=0)
    cost_confidence: UnitInterval
    components: tuple[ExecutionCostComponent, ...] = REQUIRED_EXECUTION_COST_COMPONENTS
    environments: tuple[Literal["BACKTEST", "PAPER", "LIVE"], ...] = (
        "BACKTEST",
        "PAPER",
        "LIVE",
    )
    real_world_tca_claimed: Literal[False] = False
    model_sha256: str

    @field_validator("model_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="execution cost model hash")

    @field_validator("tca_artifact_sha256")
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ensure_sha256(value, field_name="TCA artifact hash")

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        if self.components != REQUIRED_EXECUTION_COST_COMPONENTS:
            raise ValueError("AQ-P10-COST-COMPONENT-SET-MISMATCH")
        if self.environments != REQUIRED_EXECUTION_ENVIRONMENTS:
            raise ValueError("AQ-P10-COST-ENVIRONMENT-SCOPE-MISMATCH")
        if (self.queue_mode is MakerQueueMode.REPLAY_QUEUE) != (self.replay_inputs is not None):
            raise ValueError("AQ-P10-REPLAY-QUEUE-INPUT-BINDING-MISMATCH")
        has_tca = self.tca_artifact_sha256 is not None and self.tca_sample_count > 0
        if self.calibration_state is CostCalibrationState.UNVERIFIED:
            if self.tca_artifact_sha256 is not None or self.tca_sample_count != 0:
                raise ValueError("AQ-P10-UNVERIFIED-COST-MODEL-HAS-TCA")
        elif not has_tca:
            raise ValueError("AQ-P10-COST-CALIBRATION-EVIDENCE-MISSING")
        if (
            self.calibration_state is CostCalibrationState.MISCALIBRATED
            and self.cost_confidence >= Decimal("1")
        ):
            raise ValueError("AQ-P10-COST-MISCALIBRATION-MUST-REDUCE-CONFIDENCE")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"model_sha256"}))
        if self.model_sha256 != expected:
            raise ValueError("AQ-P10-COST-MODEL-HASH-MISMATCH")
        return self


def create_execution_cost_model_v2(
    *,
    version: str,
    queue_mode: MakerQueueMode,
    replay_inputs: ReplayQueueInputs | None,
    calibration_state: CostCalibrationState,
    tca_artifact_sha256: str | None,
    tca_sample_count: int,
    cost_confidence: Decimal,
) -> ExecutionCostModelV2:
    payload = {
        "version": version,
        "queue_mode": queue_mode,
        "replay_inputs": replay_inputs,
        "calibration_state": calibration_state,
        "tca_artifact_sha256": tca_artifact_sha256,
        "tca_sample_count": tca_sample_count,
        "cost_confidence": cost_confidence,
        "components": REQUIRED_EXECUTION_COST_COMPONENTS,
        "environments": REQUIRED_EXECUTION_ENVIRONMENTS,
        "real_world_tca_claimed": False,
    }
    candidate = ExecutionCostModelV2.model_construct(
        **cast("dict[str, Any]", payload), model_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"model_sha256"}))
    return ExecutionCostModelV2.model_validate({**payload, "model_sha256": digest})


class ExecutionCostScenario(DomainModel):
    scenario_id: str = Field(min_length=1, max_length=120)
    probability: UnitInterval
    fee: NonNegativeDecimal
    spread: NonNegativeDecimal
    slippage: NonNegativeDecimal
    market_impact: NonNegativeDecimal
    queue_probability: UnitInterval
    maker_adverse_selection: NonNegativeDecimal
    latency_cost: NonNegativeDecimal
    funding: NonNegativeDecimal
    borrow: NonNegativeDecimal
    settlement: NonNegativeDecimal
    liquidation_risk: NonNegativeDecimal
    total_cost: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_scenario(self) -> Self:
        if self.probability <= 0:
            raise ValueError("execution cost scenario probability must be positive")
        expected = canonical_result(
            self.fee
            + self.spread
            + self.slippage
            + self.market_impact
            + self.maker_adverse_selection
            + self.latency_cost
            + self.funding
            + self.borrow
            + self.settlement
            + self.liquidation_risk
        )
        if self.total_cost != expected:
            raise ValueError("AQ-P10-COST-SCENARIO-RECOMPUTATION-MISMATCH")
        return self


class ExecutionCostDistribution(DomainModel):
    model: ExecutionCostModelV2
    asset_id: AssetId
    instrument_id: InstrumentId
    horizon: CouncilHorizon
    sleeve_id: str = Field(min_length=1, max_length=80)
    decision_time: UtcDateTime
    available_at: UtcDateTime
    scenarios: Annotated[tuple[ExecutionCostScenario, ...], Field(min_length=3, max_length=4096)]
    expected_cost: PositiveDecimal
    evidence_tier: Literal[EvidenceTier.DEVELOPMENT] = EvidenceTier.DEVELOPMENT
    distribution_sha256: str

    @field_validator("distribution_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="execution cost distribution hash")

    @model_validator(mode="after")
    def validate_distribution(self) -> Self:
        model = ExecutionCostModelV2.model_validate_json(self.model.model_dump_json())
        if model != self.model:
            raise ValueError("AQ-P10-COST-MODEL-REVALIDATION-MISMATCH")
        assert_point_in_time(available_time=self.available_at, decision_time=self.decision_time)
        scenario_ids = tuple(item.scenario_id for item in self.scenarios)
        if scenario_ids != tuple(sorted(set(scenario_ids))):
            raise ValueError("cost scenarios must be sorted and unique")
        if sum((item.probability for item in self.scenarios), start=Decimal("0")) != 1:
            raise ValueError("AQ-P10-COST-SCENARIO-PROBABILITY-MISMATCH")
        expected_cost = canonical_result(
            sum(
                (item.probability * item.total_cost for item in self.scenarios),
                start=Decimal("0"),
            )
        )
        if self.expected_cost != expected_cost:
            raise ValueError("AQ-P10-EXPECTED-COST-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(
            self.model_dump(mode="json", exclude={"distribution_sha256"})
        )
        if self.distribution_sha256 != expected_hash:
            raise ValueError("AQ-P10-COST-DISTRIBUTION-HASH-MISMATCH")
        return self


def create_execution_cost_distribution(
    *,
    model: ExecutionCostModelV2,
    asset_id: AssetId,
    instrument_id: InstrumentId,
    horizon: CouncilHorizon,
    sleeve_id: str,
    decision_time: UtcDateTime,
    available_at: UtcDateTime,
    scenarios: tuple[ExecutionCostScenario, ...],
) -> ExecutionCostDistribution:
    ordered = tuple(sorted(scenarios, key=lambda item: item.scenario_id))
    expected_cost = canonical_result(
        sum((item.probability * item.total_cost for item in ordered), start=Decimal("0"))
    )
    payload = {
        "model": model,
        "asset_id": asset_id,
        "instrument_id": instrument_id,
        "horizon": horizon,
        "sleeve_id": sleeve_id,
        "decision_time": decision_time,
        "available_at": available_at,
        "scenarios": ordered,
        "expected_cost": expected_cost,
        "evidence_tier": EvidenceTier.DEVELOPMENT,
    }
    candidate = ExecutionCostDistribution.model_construct(
        **cast("dict[str, Any]", payload), distribution_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"distribution_sha256"}))
    return ExecutionCostDistribution.model_validate({**payload, "distribution_sha256": digest})


class DirectionalForecastScenario(DomainModel):
    scenario_id: str = Field(min_length=1, max_length=120)
    probability: UnitInterval
    gross_edge: FiniteDecimal

    @model_validator(mode="after")
    def probability_is_positive(self) -> Self:
        if self.probability <= 0:
            raise ValueError("forecast scenario probability must be positive")
        return self


class DirectionalForecastDistribution(DomainModel):
    governance: ForecastGovernanceReport
    event_increment: EventIncrement
    direction: PositionDirection
    sleeve_id: str = Field(min_length=1, max_length=80)
    scenarios: Annotated[
        tuple[DirectionalForecastScenario, ...], Field(min_length=3, max_length=4096)
    ]
    expected_gross_edge: FiniteDecimal
    evidence_tier: Literal[EvidenceTier.DEVELOPMENT] = EvidenceTier.DEVELOPMENT
    real_world_accuracy_claimed: Literal[False] = False
    alpha_promotion_eligible: Literal[False] = False
    distribution_sha256: str

    @field_validator("distribution_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="directional forecast distribution hash")

    @model_validator(mode="after")
    def validate_distribution(self) -> Self:
        governance = ForecastGovernanceReport.model_validate_json(self.governance.model_dump_json())
        increment = EventIncrement.model_validate_json(self.event_increment.model_dump_json())
        council = governance.disagreement.snapshot
        lineage = increment.event_conditioned.lineage
        condition = increment.event_conditioned.event_condition
        forecast = increment.event_conditioned.inputs.forecast
        if (
            council.asset_id != lineage.asset_id
            or council.horizon is not lineage.horizon
            or council.regime is not lineage.regime
            or council.decision_time != lineage.decision_time
            or condition.asset_id != lineage.asset_id
            or condition.instrument_id != lineage.instrument_id
            or condition.decision_time != lineage.decision_time
            or forecast.as_of_time != lineage.decision_time
        ):
            raise ValueError("AQ-P10-FORECAST-EVENT-GOVERNANCE-CELL-SPLICE")
        scenario_ids = tuple(item.scenario_id for item in self.scenarios)
        if scenario_ids != tuple(sorted(set(scenario_ids))):
            raise ValueError("forecast scenarios must be sorted and unique")
        if sum((item.probability for item in self.scenarios), start=Decimal("0")) != 1:
            raise ValueError("AQ-P10-FORECAST-SCENARIO-PROBABILITY-MISMATCH")
        expected = canonical_result(
            sum(
                (item.probability * item.gross_edge for item in self.scenarios),
                start=Decimal("0"),
            )
        )
        raw_mean = forecast.horizons[0].return_distribution.mean
        direction_adjusted_mean = (
            raw_mean if self.direction is PositionDirection.LONG else -raw_mean
        )
        if self.expected_gross_edge != expected or expected != direction_adjusted_mean:
            raise ValueError("AQ-P10-FORECAST-DISTRIBUTION-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(
            self.model_dump(mode="json", exclude={"distribution_sha256"})
        )
        if self.distribution_sha256 != expected_hash:
            raise ValueError("AQ-P10-FORECAST-DISTRIBUTION-HASH-MISMATCH")
        return self


def create_directional_forecast_distribution(
    *,
    governance: ForecastGovernanceReport,
    event_increment: EventIncrement,
    direction: PositionDirection,
    sleeve_id: str,
    scenarios: tuple[DirectionalForecastScenario, ...],
) -> DirectionalForecastDistribution:
    ordered = tuple(sorted(scenarios, key=lambda item: item.scenario_id))
    expected = canonical_result(
        sum((item.probability * item.gross_edge for item in ordered), start=Decimal("0"))
    )
    payload = {
        "governance": governance,
        "event_increment": event_increment,
        "direction": direction,
        "sleeve_id": sleeve_id,
        "scenarios": ordered,
        "expected_gross_edge": expected,
        "evidence_tier": EvidenceTier.DEVELOPMENT,
        "real_world_accuracy_claimed": False,
        "alpha_promotion_eligible": False,
    }
    candidate = DirectionalForecastDistribution.model_construct(
        **cast("dict[str, Any]", payload), distribution_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"distribution_sha256"}))
    return DirectionalForecastDistribution.model_validate(
        {**payload, "distribution_sha256": digest}
    )


def directional_signal_id(distribution: DirectionalForecastDistribution) -> SignalId:
    """Return the only portfolio signal identity accepted for this forecast distribution."""

    return SignalId.from_content(distribution.distribution_sha256.encode("ascii"))


class NetEdgePolicy(DomainModel):
    version: str = Field(min_length=1, max_length=80)
    asset_id: AssetId
    horizon: CouncilHorizon
    sleeve_id: str = Field(min_length=1, max_length=80)
    threshold_source: NetEdgeThresholdSource
    oos_evidence_sha256: str | None = None
    minimum_probability_positive: UnitInterval
    confidence_level: UnitInterval
    economic_floor: NonNegativeDecimal
    minimum_net_edge_cost_ratio: NonNegativeDecimal
    minimum_truth_probability: UnitInterval
    maximum_contradiction_probability: UnitInterval
    maximum_manipulation_probability: UnitInterval
    minimum_novelty: UnitInterval
    maximum_market_reflection: UnitInterval
    maximum_forecast_range: NonNegativeDecimal
    maximum_ood_score: NonNegativeDecimal
    minimum_data_quality: UnitInterval
    minimum_event_increment_magnitude: NonNegativeDecimal
    minimum_cost_confidence: UnitInterval
    final_holdout_opened: Literal[False] = False
    alpha_truth_claimed: Literal[False] = False
    policy_sha256: str

    @field_validator("policy_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="net edge policy hash")

    @field_validator("oos_evidence_sha256")
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ensure_sha256(value, field_name="net edge OOS evidence hash")

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.minimum_probability_positive <= Decimal("0.5"):
            raise ValueError("net edge probability threshold must be conservative")
        if self.confidence_level <= Decimal("0.5"):
            raise ValueError("net edge confidence level must exceed 0.5")
        has_oos = self.oos_evidence_sha256 is not None
        if (self.threshold_source is NetEdgeThresholdSource.OOS) != has_oos:
            raise ValueError("AQ-P10-NET-EDGE-OOS-THRESHOLD-EVIDENCE-MISMATCH")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        if self.policy_sha256 != expected:
            raise ValueError("AQ-P10-NET-EDGE-POLICY-HASH-MISMATCH")
        return self


def create_net_edge_policy(
    *,
    version: str,
    asset_id: AssetId,
    horizon: CouncilHorizon,
    sleeve_id: str,
    threshold_source: NetEdgeThresholdSource,
    oos_evidence_sha256: str | None,
    minimum_probability_positive: Decimal,
    confidence_level: Decimal,
    economic_floor: Decimal,
    minimum_net_edge_cost_ratio: Decimal,
    minimum_truth_probability: Decimal,
    maximum_contradiction_probability: Decimal,
    maximum_manipulation_probability: Decimal,
    minimum_novelty: Decimal,
    maximum_market_reflection: Decimal,
    maximum_forecast_range: Decimal,
    maximum_ood_score: Decimal,
    minimum_data_quality: Decimal,
    minimum_event_increment_magnitude: Decimal,
    minimum_cost_confidence: Decimal,
) -> NetEdgePolicy:
    payload = {
        "version": version,
        "asset_id": asset_id,
        "horizon": horizon,
        "sleeve_id": sleeve_id,
        "threshold_source": threshold_source,
        "oos_evidence_sha256": oos_evidence_sha256,
        "minimum_probability_positive": minimum_probability_positive,
        "confidence_level": confidence_level,
        "economic_floor": economic_floor,
        "minimum_net_edge_cost_ratio": minimum_net_edge_cost_ratio,
        "minimum_truth_probability": minimum_truth_probability,
        "maximum_contradiction_probability": maximum_contradiction_probability,
        "maximum_manipulation_probability": maximum_manipulation_probability,
        "minimum_novelty": minimum_novelty,
        "maximum_market_reflection": maximum_market_reflection,
        "maximum_forecast_range": maximum_forecast_range,
        "maximum_ood_score": maximum_ood_score,
        "minimum_data_quality": minimum_data_quality,
        "minimum_event_increment_magnitude": minimum_event_increment_magnitude,
        "minimum_cost_confidence": minimum_cost_confidence,
        "final_holdout_opened": False,
        "alpha_truth_claimed": False,
    }
    candidate = NetEdgePolicy.model_construct(
        **cast("dict[str, Any]", payload), policy_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"policy_sha256"}))
    return NetEdgePolicy.model_validate({**payload, "policy_sha256": digest})


class NetEdgeScenario(DomainModel):
    scenario_id: str = Field(min_length=1, max_length=120)
    probability: UnitInterval
    gross_edge: FiniteDecimal
    queue_probability: UnitInterval
    queue_adjusted_gross_edge: FiniteDecimal
    execution_cost: NonNegativeDecimal
    net_edge: FiniteDecimal

    @model_validator(mode="after")
    def validate_net_edge(self) -> Self:
        if self.probability <= 0:
            raise ValueError("net edge scenario probability must be positive")
        expected_realized_edge = canonical_result(self.gross_edge * self.queue_probability)
        if self.queue_adjusted_gross_edge != expected_realized_edge:
            raise ValueError("AQ-P10-QUEUE-ADJUSTED-EDGE-RECOMPUTATION-MISMATCH")
        if self.net_edge != canonical_result(expected_realized_edge - self.execution_cost):
            raise ValueError("AQ-P10-NET-EDGE-SCENARIO-RECOMPUTATION-MISMATCH")
        return self


def _weighted_quantile(scenarios: tuple[NetEdgeScenario, ...], quantile: Decimal) -> Decimal:
    cumulative = Decimal("0")
    ordered = sorted(scenarios, key=lambda item: (item.net_edge, item.scenario_id))
    for scenario in ordered:
        cumulative += scenario.probability
        if cumulative >= quantile:
            return scenario.net_edge
    return ordered[-1].net_edge


class NetEdgeDistribution(DomainModel):
    forecast: DirectionalForecastDistribution
    costs: ExecutionCostDistribution
    policy: NetEdgePolicy
    scenarios: Annotated[tuple[NetEdgeScenario, ...], Field(min_length=3, max_length=4096)]
    expected_net_edge: FiniteDecimal
    raw_probability_positive: UnitInterval
    confidence_adjusted_probability_positive: UnitInterval
    lower_confidence_bound: FiniteDecimal
    expected_net_edge_cost_ratio: FiniteDecimal
    truth_gate_passed: bool
    price_in_gate_passed: bool
    uncertainty_gate_passed: bool
    ood_gate_passed: bool
    data_quality_gate_passed: bool
    event_increment_gate_passed: bool
    cost_confidence_gate_passed: bool
    expected_edge_gate_passed: bool
    probability_gate_passed: bool
    lower_bound_gate_passed: bool
    edge_cost_ratio_gate_passed: bool
    allowed_before_portfolio_and_risk: bool
    reason_codes: tuple[str, ...]
    evidence_tier: Literal[EvidenceTier.DEVELOPMENT] = EvidenceTier.DEVELOPMENT
    alpha_promotion_eligible: Literal[False] = False
    distribution_sha256: str

    @field_validator("distribution_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="net edge distribution hash")

    @model_validator(mode="after")
    def validate_distribution(self) -> Self:
        expected = _derive_net_edge(self.forecast, self.costs, self.policy)
        if any(getattr(self, field) != value for field, value in expected.items()):
            raise ValueError("AQ-P10-NET-EDGE-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(
            self.model_dump(mode="json", exclude={"distribution_sha256"})
        )
        if self.distribution_sha256 != expected_hash:
            raise ValueError("AQ-P10-NET-EDGE-HASH-MISMATCH")
        return self


def _derive_net_edge(
    forecast: DirectionalForecastDistribution,
    costs: ExecutionCostDistribution,
    policy: NetEdgePolicy,
) -> dict[str, object]:
    validated_forecast = DirectionalForecastDistribution.model_validate_json(
        forecast.model_dump_json()
    )
    validated_costs = ExecutionCostDistribution.model_validate_json(costs.model_dump_json())
    validated_policy = NetEdgePolicy.model_validate_json(policy.model_dump_json())
    condition = validated_forecast.event_increment.event_conditioned.event_condition
    council = validated_forecast.governance.disagreement.snapshot
    route = validated_forecast.governance.regime_route.snapshot
    if (
        validated_policy.asset_id != council.asset_id
        or validated_policy.horizon is not council.horizon
        or validated_policy.sleeve_id != validated_forecast.sleeve_id
    ):
        raise ValueError("AQ-P10-NET-EDGE-POLICY-CELL-SPLICE")
    if (
        validated_costs.asset_id != council.asset_id
        or validated_costs.instrument_id != condition.instrument_id
        or validated_costs.horizon is not council.horizon
        or validated_costs.sleeve_id != validated_forecast.sleeve_id
        or validated_costs.decision_time != council.decision_time
    ):
        raise ValueError("AQ-P10-FORECAST-COST-CELL-SPLICE")
    forecast_by_id = {item.scenario_id: item for item in validated_forecast.scenarios}
    cost_by_id = {item.scenario_id: item for item in validated_costs.scenarios}
    if set(forecast_by_id) != set(cost_by_id):
        raise ValueError("AQ-P10-FORECAST-COST-SCENARIO-SPLICE")
    scenarios: list[NetEdgeScenario] = []
    for scenario_id in sorted(forecast_by_id):
        forecast_scenario = forecast_by_id[scenario_id]
        cost_scenario = cost_by_id[scenario_id]
        if forecast_scenario.probability != cost_scenario.probability:
            raise ValueError("AQ-P10-FORECAST-COST-PROBABILITY-SPLICE")
        scenarios.append(
            NetEdgeScenario(
                scenario_id=scenario_id,
                probability=forecast_scenario.probability,
                gross_edge=forecast_scenario.gross_edge,
                queue_probability=cost_scenario.queue_probability,
                queue_adjusted_gross_edge=canonical_result(
                    forecast_scenario.gross_edge * cost_scenario.queue_probability
                ),
                execution_cost=cost_scenario.total_cost,
                net_edge=canonical_result(
                    forecast_scenario.gross_edge * cost_scenario.queue_probability
                    - cost_scenario.total_cost
                ),
            )
        )
    scenario_tuple = tuple(scenarios)
    expected_net_edge = canonical_result(
        sum((item.probability * item.net_edge for item in scenario_tuple), start=Decimal("0"))
    )
    raw_probability = canonical_result(
        sum(
            (item.probability for item in scenario_tuple if item.net_edge > 0),
            start=Decimal("0"),
        )
    )
    adjusted_probability = canonical_result(raw_probability * validated_costs.model.cost_confidence)
    lower_bound = _weighted_quantile(
        scenario_tuple, Decimal("1") - validated_policy.confidence_level
    )
    ratio = canonical_result(expected_net_edge / validated_costs.expected_cost)
    truth = condition.canonical_event.truth_assessment
    truth_gate = (
        condition.canonical_event.event_stage is EventClusterStatus.CONFIRMED
        and truth.claim_truth_probability >= validated_policy.minimum_truth_probability
        and truth.contradiction_probability <= validated_policy.maximum_contradiction_probability
        and truth.manipulation_probability <= validated_policy.maximum_manipulation_probability
    )
    gate = condition.directional_gate
    price_in_gate = (
        condition.directional_candidate_allowed
        and gate.market_reflection_quality is QualityState.GOOD
        and gate.market_reflection_score is not None
        and gate.market_reflection_score < gate.high_price_in_threshold
        and gate.market_reflection_score <= validated_policy.maximum_market_reflection
        and condition.features.novelty_at_t >= validated_policy.minimum_novelty
    )
    governance = validated_forecast.governance
    uncertainty_gate = (
        not governance.should_abstain
        and governance.disagreement.expected_return_range <= validated_policy.maximum_forecast_range
        and governance.calibration.action is CalibrationDriftAction.NONE
    )
    ood_gate = (
        route.regime not in {MarketRegime.OOD, MarketRegime.UNKNOWN}
        and route.ood_score <= validated_policy.maximum_ood_score
    )
    data_quality_gate = route.data_quality >= validated_policy.minimum_data_quality
    increment = validated_forecast.event_increment.by_horizon.delta_expected_return
    direction_multiplier = (
        Decimal("1") if validated_forecast.direction is PositionDirection.LONG else Decimal("-1")
    )
    event_increment_gate = (
        canonical_result(increment * direction_multiplier)
        >= validated_policy.minimum_event_increment_magnitude
    )
    cost_confidence_gate = (
        validated_costs.model.cost_confidence >= validated_policy.minimum_cost_confidence
    )
    expected_edge_gate = expected_net_edge > 0
    probability_gate = adjusted_probability >= validated_policy.minimum_probability_positive
    lower_bound_gate = lower_bound > validated_policy.economic_floor
    ratio_gate = ratio >= validated_policy.minimum_net_edge_cost_ratio
    gates = {
        "truth_gate_passed": truth_gate,
        "price_in_gate_passed": price_in_gate,
        "uncertainty_gate_passed": uncertainty_gate,
        "ood_gate_passed": ood_gate,
        "data_quality_gate_passed": data_quality_gate,
        "event_increment_gate_passed": event_increment_gate,
        "cost_confidence_gate_passed": cost_confidence_gate,
        "expected_edge_gate_passed": expected_edge_gate,
        "probability_gate_passed": probability_gate,
        "lower_bound_gate_passed": lower_bound_gate,
        "edge_cost_ratio_gate_passed": ratio_gate,
    }
    reason_by_gate = {
        "truth_gate_passed": "TRUTH_GATE_REJECTED",
        "price_in_gate_passed": "PRICE_IN_GATE_REJECTED",
        "uncertainty_gate_passed": "FORECAST_UNCERTAINTY_REJECTED",
        "ood_gate_passed": "OOD_GATE_REJECTED",
        "data_quality_gate_passed": "DATA_QUALITY_GATE_REJECTED",
        "event_increment_gate_passed": "EVENT_INCREMENT_GATE_REJECTED",
        "cost_confidence_gate_passed": "COST_CONFIDENCE_GATE_REJECTED",
        "expected_edge_gate_passed": "EXPECTED_NET_EDGE_NONPOSITIVE",
        "probability_gate_passed": "NET_EDGE_PROBABILITY_BELOW_POLICY",
        "lower_bound_gate_passed": "NET_EDGE_LOWER_BOUND_BELOW_FLOOR",
        "edge_cost_ratio_gate_passed": "NET_EDGE_COST_RATIO_BELOW_POLICY",
    }
    reasons = tuple(sorted(reason_by_gate[name] for name, passed in gates.items() if not passed))
    return {
        "scenarios": scenario_tuple,
        "expected_net_edge": expected_net_edge,
        "raw_probability_positive": raw_probability,
        "confidence_adjusted_probability_positive": adjusted_probability,
        "lower_confidence_bound": lower_bound,
        "expected_net_edge_cost_ratio": ratio,
        **gates,
        "allowed_before_portfolio_and_risk": not reasons,
        "reason_codes": reasons,
        "evidence_tier": EvidenceTier.DEVELOPMENT,
        "alpha_promotion_eligible": False,
    }


def evaluate_net_edge(
    *,
    forecast: DirectionalForecastDistribution,
    costs: ExecutionCostDistribution,
    policy: NetEdgePolicy,
) -> NetEdgeDistribution:
    derived = _derive_net_edge(forecast, costs, policy)
    payload = {"forecast": forecast, "costs": costs, "policy": policy, **derived}
    candidate = NetEdgeDistribution.model_construct(
        **cast("dict[str, Any]", payload), distribution_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"distribution_sha256"}))
    return NetEdgeDistribution.model_validate({**payload, "distribution_sha256": digest})


class RiskOverlayPolicy(DomainModel):
    version: str = Field(min_length=1, max_length=80)
    minimum_truth_probability: UnitInterval
    minimum_severity: UnitInterval
    target_exposure_scale: UnitInterval
    policy_sha256: str

    @field_validator("policy_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="risk overlay policy hash")

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        if self.policy_sha256 != expected:
            raise ValueError("AQ-P10-RISK-OVERLAY-POLICY-HASH-MISMATCH")
        return self


def create_risk_overlay_policy(
    *,
    version: str,
    minimum_truth_probability: Decimal,
    minimum_severity: Decimal,
    target_exposure_scale: Decimal,
) -> RiskOverlayPolicy:
    payload = {
        "version": version,
        "minimum_truth_probability": minimum_truth_probability,
        "minimum_severity": minimum_severity,
        "target_exposure_scale": target_exposure_scale,
    }
    candidate = RiskOverlayPolicy.model_construct(
        **cast("dict[str, Any]", payload), policy_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"policy_sha256"}))
    return RiskOverlayPolicy.model_validate({**payload, "policy_sha256": digest})


def _risk_decision_sha256(decision: RiskDecision) -> str:
    return canonical_sha256(decision.model_dump(mode="json"))


class EventDirectionalAlpha(DomainModel):
    forecast_distribution_sha256: str
    net_edge_distribution_sha256: str
    portfolio_proposal_sha256: str
    risk_decision_sha256: str
    direction: PositionDirection
    approved_delta_weight: FiniteDecimal
    action: Literal["RESEARCH_PROPOSAL_ONLY"] = "RESEARCH_PROPOSAL_ONLY"
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    alpha_promotion_eligible: Literal[False] = False
    alpha_sha256: str

    @field_validator(
        "forecast_distribution_sha256",
        "net_edge_distribution_sha256",
        "portfolio_proposal_sha256",
        "risk_decision_sha256",
        "alpha_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return ensure_sha256(value, field_name="event directional alpha hash")

    @model_validator(mode="after")
    def validate_alpha(self) -> Self:
        multiplier = Decimal("1") if self.direction is PositionDirection.LONG else Decimal("-1")
        if self.approved_delta_weight * multiplier <= 0:
            raise ValueError("AQ-P10-DIRECTIONAL-ALPHA-DELTA-DIRECTION-MISMATCH")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"alpha_sha256"}))
        if self.alpha_sha256 != expected:
            raise ValueError("AQ-P10-DIRECTIONAL-ALPHA-HASH-MISMATCH")
        return self


class EventRiskOverlay(DomainModel):
    event_condition_sha256: str
    policy_sha256: str
    portfolio_proposal_sha256: str
    risk_decision_sha256: str
    actions: tuple[RiskOverlayAction, ...] = REQUIRED_OVERLAY_ACTIONS
    target_exposure_scale: UnitInterval
    directional_alpha_allowed: Literal[False] = False
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    overlay_sha256: str

    @field_validator(
        "event_condition_sha256",
        "policy_sha256",
        "portfolio_proposal_sha256",
        "risk_decision_sha256",
        "overlay_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return ensure_sha256(value, field_name="event risk overlay hash")

    @model_validator(mode="after")
    def validate_overlay(self) -> Self:
        if self.actions != REQUIRED_OVERLAY_ACTIONS:
            raise ValueError("AQ-P10-RISK-OVERLAY-ACTION-SET-MISMATCH")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"overlay_sha256"}))
        if self.overlay_sha256 != expected:
            raise ValueError("AQ-P10-RISK-OVERLAY-HASH-MISMATCH")
        return self


class NoTradeDecision(DomainModel):
    forecast_distribution_sha256: str
    cost_distribution_sha256: str
    net_edge_distribution_sha256: str
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1)]
    action: Literal["NO_TRADE"] = "NO_TRADE"
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    decision_sha256: str

    @field_validator(
        "forecast_distribution_sha256",
        "cost_distribution_sha256",
        "net_edge_distribution_sha256",
        "decision_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return ensure_sha256(value, field_name="no-trade decision hash")

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("no-trade reasons must be sorted and unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
        if self.decision_sha256 != expected:
            raise ValueError("AQ-P10-NO-TRADE-HASH-MISMATCH")
        return self


def _portfolio_directional_delta(
    forecast: DirectionalForecastDistribution,
    proposal: PortfolioProposal | None,
    decision_time: UtcDateTime,
) -> Decimal | None:
    if proposal is None:
        return None
    condition = forecast.event_increment.event_conditioned.event_condition
    if (
        proposal.as_of_time != condition.decision_time
        or proposal.created_at > decision_time
        or proposal.valid_until <= decision_time
    ):
        return None
    expected_signal_id = directional_signal_id(forecast)
    matches = [
        leg
        for leg in proposal.legs
        if leg.signal_id == expected_signal_id
        and leg.asset_id == condition.asset_id
        and leg.instrument_id == condition.instrument_id
        and leg.sleeve_id == forecast.sleeve_id
    ]
    if len(matches) != 1:
        return None
    leg = matches[0]
    multiplier = Decimal("1") if forecast.direction is PositionDirection.LONG else Decimal("-1")
    if leg.delta_weight * multiplier <= 0 or leg.normalized_signal * multiplier <= 0:
        return None
    return leg.delta_weight


def _risk_directional_delta(
    forecast: DirectionalForecastDistribution,
    proposal: PortfolioProposal | None,
    risk: RiskDecision | None,
    decision_time: UtcDateTime,
) -> Decimal | None:
    if proposal is None or risk is None:
        return None
    if risk.proposal_id != proposal.proposal_id or risk.proposal_sha256 != proposal.proposal_sha256:
        raise ValueError("AQ-P10-RISK-PROPOSAL-SPLICE")
    if (
        risk.decided_at < proposal.created_at
        or risk.decided_at > decision_time
        or risk.valid_until <= decision_time
        or risk.status is not RiskDecisionStatus.APPROVED
        or not risk.new_risk_allowed
    ):
        return None
    condition = forecast.event_increment.event_conditioned.event_condition
    expected_signal_id = directional_signal_id(forecast)
    portfolio_matches = [
        leg
        for leg in proposal.legs
        if leg.signal_id == expected_signal_id
        and leg.asset_id == condition.asset_id
        and leg.instrument_id == condition.instrument_id
        and leg.sleeve_id == forecast.sleeve_id
    ]
    if len(portfolio_matches) != 1:
        return None
    portfolio_leg = portfolio_matches[0]
    matches = [
        item
        for item in risk.approved_targets
        if item.asset_id == condition.asset_id
        and item.instrument_id == condition.instrument_id
        and item.strategy_id == portfolio_leg.strategy_id
        and item.account_id == portfolio_leg.account_id
        and item.current_weight == portfolio_leg.current_weight
        and item.proposed_target_weight == portfolio_leg.target_weight
    ]
    if len(matches) != 1:
        return None
    multiplier = Decimal("1") if forecast.direction is PositionDirection.LONG else Decimal("-1")
    delta = matches[0].approved_delta_weight
    if delta * multiplier <= 0:
        return None
    return delta


def _overlay_eligible(
    net_edge: NetEdgeDistribution,
    policy: RiskOverlayPolicy,
) -> bool:
    condition = net_edge.forecast.event_increment.event_conditioned.event_condition
    return (
        condition.risk_overlay_only
        and condition.canonical_event.truth_assessment.claim_truth_probability
        >= policy.minimum_truth_probability
        and condition.features.severity_at_t >= policy.minimum_severity
    )


def _overlay_risk_allows(
    proposal: PortfolioProposal | None,
    risk: RiskDecision | None,
    decision_time: UtcDateTime,
) -> bool:
    if proposal is None or risk is None:
        return False
    if risk.proposal_id != proposal.proposal_id or risk.proposal_sha256 != proposal.proposal_sha256:
        raise ValueError("AQ-P10-RISK-PROPOSAL-SPLICE")
    return (
        risk.decided_at >= proposal.created_at
        and risk.decided_at <= decision_time
        and risk.valid_until > decision_time
        and risk.status in {RiskDecisionStatus.REDUCE_ONLY, RiskDecisionStatus.HALTED}
        and not risk.new_risk_allowed
    )


def _hashed_model(
    model_type: type[DomainModel], payload: Mapping[str, object], field: str
) -> DomainModel:
    candidate_payload = {**payload, field: "0" * 64}
    candidate = model_type.model_construct(**cast("dict[str, Any]", candidate_payload))
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={field}))
    return model_type.model_validate({**payload, field: digest})


def _build_directional_alpha(
    net_edge: NetEdgeDistribution,
    proposal: PortfolioProposal,
    risk: RiskDecision,
    approved_delta: Decimal,
) -> EventDirectionalAlpha:
    payload = {
        "forecast_distribution_sha256": net_edge.forecast.distribution_sha256,
        "net_edge_distribution_sha256": net_edge.distribution_sha256,
        "portfolio_proposal_sha256": proposal.proposal_sha256,
        "risk_decision_sha256": _risk_decision_sha256(risk),
        "direction": net_edge.forecast.direction,
        "approved_delta_weight": approved_delta,
        "action": "RESEARCH_PROPOSAL_ONLY",
        "order_submission_enabled": False,
        "live_trading_locked": True,
        "alpha_promotion_eligible": False,
    }
    return cast(
        "EventDirectionalAlpha",
        _hashed_model(EventDirectionalAlpha, payload, "alpha_sha256"),
    )


def _build_risk_overlay(
    net_edge: NetEdgeDistribution,
    policy: RiskOverlayPolicy,
    proposal: PortfolioProposal,
    risk: RiskDecision,
) -> EventRiskOverlay:
    payload = {
        "event_condition_sha256": net_edge.forecast.event_increment.event_conditioned.event_condition.snapshot_sha256,
        "policy_sha256": policy.policy_sha256,
        "portfolio_proposal_sha256": proposal.proposal_sha256,
        "risk_decision_sha256": _risk_decision_sha256(risk),
        "actions": REQUIRED_OVERLAY_ACTIONS,
        "target_exposure_scale": policy.target_exposure_scale,
        "directional_alpha_allowed": False,
        "order_submission_enabled": False,
        "live_trading_locked": True,
    }
    return cast("EventRiskOverlay", _hashed_model(EventRiskOverlay, payload, "overlay_sha256"))


def _build_no_trade(net_edge: NetEdgeDistribution, reasons: tuple[str, ...]) -> NoTradeDecision:
    payload = {
        "forecast_distribution_sha256": net_edge.forecast.distribution_sha256,
        "cost_distribution_sha256": net_edge.costs.distribution_sha256,
        "net_edge_distribution_sha256": net_edge.distribution_sha256,
        "reason_codes": tuple(sorted(set(reasons))),
        "action": "NO_TRADE",
        "order_submission_enabled": False,
        "live_trading_locked": True,
    }
    return cast("NoTradeDecision", _hashed_model(NoTradeDecision, payload, "decision_sha256"))


def _derive_integrated_decision(
    *,
    net_edge: NetEdgeDistribution,
    overlay_policy: RiskOverlayPolicy,
    portfolio: PortfolioProposal | None,
    risk: RiskDecision | None,
    decision_time: UtcDateTime,
) -> dict[str, object]:
    validated_net_edge = NetEdgeDistribution.model_validate_json(net_edge.model_dump_json())
    validated_overlay_policy = RiskOverlayPolicy.model_validate_json(
        overlay_policy.model_dump_json()
    )
    validated_portfolio = (
        PortfolioProposal.model_validate_json(portfolio.model_dump_json())
        if portfolio is not None
        else None
    )
    validated_risk = (
        RiskDecision.model_validate_json(risk.model_dump_json()) if risk is not None else None
    )
    assert_point_in_time(
        available_time=validated_net_edge.costs.available_at,
        decision_time=decision_time,
    )
    portfolio_delta = _portfolio_directional_delta(
        validated_net_edge.forecast, validated_portfolio, decision_time
    )
    risk_delta = _risk_directional_delta(
        validated_net_edge.forecast,
        validated_portfolio,
        validated_risk,
        decision_time,
    )
    portfolio_allows = portfolio_delta is not None
    risk_allows = risk_delta is not None
    if validated_net_edge.allowed_before_portfolio_and_risk and portfolio_allows and risk_allows:
        if validated_portfolio is None or validated_risk is None:
            raise RuntimeError("directional gate invariant failed")
        alpha = _build_directional_alpha(
            validated_net_edge,
            validated_portfolio,
            validated_risk,
            risk_delta,
        )
        return {
            "portfolio_allows": True,
            "risk_allows": True,
            "outcome": DecisionOutcome.DIRECTIONAL_ALPHA,
            "directional_alpha": alpha,
            "risk_overlay": None,
            "no_trade": None,
            "reason_codes": ("DIRECTIONAL_ALPHA_RESEARCH_CANDIDATE",),
        }
    overlay_eligible = _overlay_eligible(validated_net_edge, validated_overlay_policy)
    overlay_allowed = _overlay_risk_allows(validated_portfolio, validated_risk, decision_time)
    if overlay_eligible and overlay_allowed:
        if validated_portfolio is None or validated_risk is None:
            raise RuntimeError("risk overlay invariant failed")
        overlay = _build_risk_overlay(
            validated_net_edge,
            validated_overlay_policy,
            validated_portfolio,
            validated_risk,
        )
        return {
            "portfolio_allows": portfolio_allows,
            "risk_allows": False,
            "outcome": DecisionOutcome.RISK_OVERLAY_ONLY,
            "directional_alpha": None,
            "risk_overlay": overlay,
            "no_trade": None,
            "reason_codes": ("EVENT_RISK_OVERLAY_ONLY",),
        }
    reasons = set(validated_net_edge.reason_codes)
    if not portfolio_allows:
        reasons.add("PORTFOLIO_GATE_REJECTED")
    if not risk_allows:
        reasons.add("RISK_GATE_REJECTED")
    if validated_net_edge.forecast.event_increment.event_conditioned.event_condition.risk_overlay_only:
        if not overlay_eligible:
            reasons.add("RISK_OVERLAY_THRESHOLD_REJECTED")
        elif not overlay_allowed:
            reasons.add("RISK_OVERLAY_NOT_AUTHORIZED_BY_RISK")
    if not reasons:
        reasons.add("NO_TRADE_FAIL_CLOSED")
    ordered_reasons = tuple(sorted(reasons))
    return {
        "portfolio_allows": portfolio_allows,
        "risk_allows": risk_allows,
        "outcome": DecisionOutcome.NO_TRADE,
        "directional_alpha": None,
        "risk_overlay": None,
        "no_trade": _build_no_trade(validated_net_edge, ordered_reasons),
        "reason_codes": ordered_reasons,
    }


class IntegratedDecisionReport(DomainModel):
    net_edge: NetEdgeDistribution
    overlay_policy: RiskOverlayPolicy
    portfolio: PortfolioProposal | None
    risk: RiskDecision | None
    decision_time: UtcDateTime
    pipeline: tuple[str, ...] = DECISION_PIPELINE
    portfolio_allows: bool
    risk_allows: bool
    outcome: DecisionOutcome
    directional_alpha: EventDirectionalAlpha | None
    risk_overlay: EventRiskOverlay | None
    no_trade: NoTradeDecision | None
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1)]
    evidence_tier: Literal[EvidenceTier.DEVELOPMENT] = EvidenceTier.DEVELOPMENT
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    alpha_promotion_eligible: Literal[False] = False
    report_sha256: str

    @field_validator("report_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="integrated decision report hash")

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if self.pipeline != DECISION_PIPELINE:
            raise ValueError("AQ-P10-DECISION-PIPELINE-MISMATCH")
        expected = _derive_integrated_decision(
            net_edge=self.net_edge,
            overlay_policy=self.overlay_policy,
            portfolio=self.portfolio,
            risk=self.risk,
            decision_time=self.decision_time,
        )
        actual = {
            "portfolio_allows": self.portfolio_allows,
            "risk_allows": self.risk_allows,
            "outcome": self.outcome,
            "directional_alpha": self.directional_alpha,
            "risk_overlay": self.risk_overlay,
            "no_trade": self.no_trade,
            "reason_codes": self.reason_codes,
        }
        if actual != expected:
            raise ValueError("AQ-P10-INTEGRATED-DECISION-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("AQ-P10-INTEGRATED-DECISION-HASH-MISMATCH")
        return self


def integrate_forecast_decision(
    *,
    net_edge: NetEdgeDistribution,
    overlay_policy: RiskOverlayPolicy,
    portfolio: PortfolioProposal | None,
    risk: RiskDecision | None,
    decision_time: UtcDateTime,
) -> IntegratedDecisionReport:
    validated_portfolio = (
        PortfolioProposal.model_validate_json(portfolio.model_dump_json())
        if portfolio is not None
        else None
    )
    validated_risk = (
        RiskDecision.model_validate_json(risk.model_dump_json()) if risk is not None else None
    )
    derived = _derive_integrated_decision(
        net_edge=net_edge,
        overlay_policy=overlay_policy,
        portfolio=validated_portfolio,
        risk=validated_risk,
        decision_time=decision_time,
    )
    payload = {
        "net_edge": net_edge,
        "overlay_policy": overlay_policy,
        "portfolio": validated_portfolio,
        "risk": validated_risk,
        "decision_time": decision_time,
        "pipeline": DECISION_PIPELINE,
        **derived,
        "evidence_tier": EvidenceTier.DEVELOPMENT,
        "order_submission_enabled": False,
        "live_trading_locked": True,
        "alpha_promotion_eligible": False,
    }
    candidate = IntegratedDecisionReport.model_construct(
        **cast("dict[str, Any]", payload), report_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"report_sha256"}))
    return IntegratedDecisionReport.model_validate({**payload, "report_sha256": digest})
