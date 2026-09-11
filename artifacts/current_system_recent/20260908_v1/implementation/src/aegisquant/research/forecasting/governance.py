"""Fail-closed forecast governance for meta reasoning, stacking, and calibration."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, cast

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.evidence import EvidenceTier
from aegisquant.domain.identifiers import AssetId
from aegisquant.domain.time import UtcDateTime, assert_point_in_time
from aegisquant.domain.truth import TruthState
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    PositiveDecimal,
    UnitInterval,
    validate_decimal,
)
from aegisquant.research.forecasting.contracts import (
    CalibrationMethod,
    CouncilHorizon,
    MarketRegime,
)
from aegisquant.research.models.ensemble import StackingWeights, smooth_weights


class ReasoningInputKind(StrEnum):
    TRUTH_ASSESSMENTS = "TRUTH_ASSESSMENTS"
    EVIDENCE_GRAPH = "EVIDENCE_GRAPH"
    EVENT_STRUCTURE = "EVENT_STRUCTURE"
    MODEL_FORECASTS = "MODEL_FORECASTS"
    MARKET_REGIME = "MARKET_REGIME"
    MODEL_RELIABILITY = "MODEL_RELIABILITY"
    CALIBRATION = "CALIBRATION"
    OOD = "OOD"
    MARKET_REFLECTION = "MARKET_REFLECTION"
    COST_FORECAST = "COST_FORECAST"
    PORTFOLIO_STATE = "PORTFOLIO_STATE"
    RISK_STATE = "RISK_STATE"


class WeightEvidenceSource(StrEnum):
    VALIDATION = "VALIDATION"
    CALIBRATION = "CALIBRATION"
    FORWARD = "FORWARD"


class SkepticSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CalibrationDriftAction(StrEnum):
    NONE = "NONE"
    RECALIBRATE = "RECALIBRATE"
    DEGRADE = "DEGRADE"
    ABSTAIN = "ABSTAIN"


class CouncilMemberSignal(DomainModel):
    candidate_id: str = Field(min_length=1)
    forecast_sha256: str
    expected_return: FiniteDecimal
    available_at: UtcDateTime

    @field_validator("forecast_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forecast signal hash")


class CouncilSignalSnapshot(DomainModel):
    asset_id: AssetId
    horizon: CouncilHorizon
    regime: MarketRegime
    decision_time: UtcDateTime
    signals: Annotated[tuple[CouncilMemberSignal, ...], Field(min_length=2)]
    snapshot_sha256: str

    @field_validator("snapshot_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="council signal snapshot hash")

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        candidate_ids = tuple(signal.candidate_id for signal in self.signals)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("AQ-P09-DUPLICATE-COUNCIL-CANDIDATE")
        if candidate_ids != tuple(sorted(candidate_ids)):
            raise ValueError("council signals must be sorted by candidate id")
        for signal in self.signals:
            assert_point_in_time(
                available_time=signal.available_at,
                decision_time=self.decision_time,
            )
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"snapshot_sha256"}))
        if self.snapshot_sha256 != expected:
            raise ValueError("AQ-P09-COUNCIL-SNAPSHOT-HASH-MISMATCH")
        return self


def create_council_signal_snapshot(
    *,
    asset_id: AssetId,
    horizon: CouncilHorizon,
    regime: MarketRegime,
    decision_time: UtcDateTime,
    signals: tuple[CouncilMemberSignal, ...],
) -> CouncilSignalSnapshot:
    ordered = tuple(sorted(signals, key=lambda item: item.candidate_id))
    payload = {
        "asset_id": asset_id,
        "horizon": horizon,
        "regime": regime,
        "decision_time": decision_time,
        "signals": ordered,
    }
    candidate = CouncilSignalSnapshot.model_construct(
        **cast("dict[str, Any]", payload), snapshot_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"snapshot_sha256"}))
    return CouncilSignalSnapshot.model_validate({**payload, "snapshot_sha256": digest})


class CouncilDisagreementPolicy(DomainModel):
    maximum_expected_return_range: NonNegativeDecimal
    abstain_on_direction_conflict: Literal[True] = True


def _derive_disagreement(
    snapshot: CouncilSignalSnapshot,
    policy: CouncilDisagreementPolicy,
) -> tuple[Decimal, bool, tuple[str, ...]]:
    returns = tuple(signal.expected_return for signal in snapshot.signals)
    expected_return_range = max(returns) - min(returns)
    direction_conflict = min(returns) < 0 < max(returns)
    reasons: set[str] = set()
    if expected_return_range > policy.maximum_expected_return_range:
        reasons.add("MODEL_DISAGREEMENT_RANGE_EXCEEDED")
    if direction_conflict:
        reasons.add("MODEL_DIRECTION_CONFLICT")
    return expected_return_range, direction_conflict, tuple(sorted(reasons))


class CouncilDisagreementReport(DomainModel):
    snapshot: CouncilSignalSnapshot
    policy: CouncilDisagreementPolicy
    expected_return_range: NonNegativeDecimal
    direction_conflict: bool
    should_abstain: bool
    reason_codes: tuple[str, ...]
    report_sha256: str

    @field_validator("report_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="council disagreement report hash")

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        expected_range, expected_conflict, expected_reasons = _derive_disagreement(
            self.snapshot,
            self.policy,
        )
        if (
            self.expected_return_range != expected_range
            or self.direction_conflict is not expected_conflict
            or self.reason_codes != expected_reasons
            or self.should_abstain != bool(expected_reasons)
        ):
            raise ValueError("AQ-P09-DISAGREEMENT-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("AQ-P09-DISAGREEMENT-HASH-MISMATCH")
        return self


def evaluate_council_disagreement(
    *,
    snapshot: CouncilSignalSnapshot,
    policy: CouncilDisagreementPolicy,
) -> CouncilDisagreementReport:
    validated_snapshot = CouncilSignalSnapshot.model_validate_json(snapshot.model_dump_json())
    validated_policy = CouncilDisagreementPolicy.model_validate_json(policy.model_dump_json())
    expected_range, direction_conflict, reasons = _derive_disagreement(
        validated_snapshot,
        validated_policy,
    )
    payload = {
        "snapshot": validated_snapshot,
        "policy": validated_policy,
        "expected_return_range": expected_range,
        "direction_conflict": direction_conflict,
        "should_abstain": bool(reasons),
        "reason_codes": reasons,
    }
    candidate = CouncilDisagreementReport.model_construct(
        **cast("dict[str, Any]", payload), report_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"report_sha256"}))
    return CouncilDisagreementReport.model_validate({**payload, "report_sha256": digest})


class ReasoningInputBinding(DomainModel):
    kind: ReasoningInputKind
    artifact_sha256: str

    @field_validator("artifact_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="reasoning input artifact hash")


class ReasoningContext(DomainModel):
    decision_time: UtcDateTime
    input_artifacts: Annotated[tuple[ReasoningInputBinding, ...], Field(min_length=1)]
    meta_reasoner_prompt_sha256: str
    meta_reasoner_model_revision_sha256: str
    skeptic_prompt_sha256: str
    skeptic_model_revision_sha256: str
    context_sha256: str

    @field_validator(
        "meta_reasoner_prompt_sha256",
        "meta_reasoner_model_revision_sha256",
        "skeptic_prompt_sha256",
        "skeptic_model_revision_sha256",
        "context_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="reasoning context hash")

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        kinds = tuple(binding.kind for binding in self.input_artifacts)
        if set(kinds) != set(ReasoningInputKind) or len(kinds) != len(set(kinds)):
            raise ValueError("AQ-P09-REASONING-CONTEXT-INCOMPLETE")
        if kinds != tuple(sorted(kinds, key=lambda item: item.value)):
            raise ValueError("reasoning input bindings must be sorted by kind")
        if (
            self.meta_reasoner_prompt_sha256 == self.skeptic_prompt_sha256
            or self.meta_reasoner_model_revision_sha256 == self.skeptic_model_revision_sha256
        ):
            raise ValueError("AQ-P09-SKEPTIC-NOT-INDEPENDENT")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"context_sha256"}))
        if self.context_sha256 != expected:
            raise ValueError("AQ-P09-REASONING-CONTEXT-HASH-MISMATCH")
        return self

    def artifact_sha256_for(self, kind: ReasoningInputKind) -> str:
        for binding in self.input_artifacts:
            if binding.kind is kind:
                return binding.artifact_sha256
        raise KeyError(kind)


def create_reasoning_context(
    *,
    decision_time: UtcDateTime,
    input_artifact_sha256s: dict[ReasoningInputKind, str],
    meta_reasoner_prompt_sha256: str,
    meta_reasoner_model_revision_sha256: str,
    skeptic_prompt_sha256: str,
    skeptic_model_revision_sha256: str,
) -> ReasoningContext:
    payload = {
        "decision_time": decision_time,
        "input_artifacts": tuple(
            ReasoningInputBinding(kind=kind, artifact_sha256=artifact_sha256)
            for kind, artifact_sha256 in sorted(
                input_artifact_sha256s.items(), key=lambda item: item[0].value
            )
        ),
        "meta_reasoner_prompt_sha256": meta_reasoner_prompt_sha256,
        "meta_reasoner_model_revision_sha256": meta_reasoner_model_revision_sha256,
        "skeptic_prompt_sha256": skeptic_prompt_sha256,
        "skeptic_model_revision_sha256": skeptic_model_revision_sha256,
    }
    candidate = ReasoningContext.model_construct(
        **cast("dict[str, Any]", payload), context_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"context_sha256"}))
    return ReasoningContext.model_validate({**payload, "context_sha256": digest})


class MetaReasonerRecommendation(DomainModel):
    context_sha256: str
    prompt_sha256: str
    model_revision_sha256: str
    generated_at: UtcDateTime
    available_at: UtcDateTime
    conflict_codes: tuple[str, ...]
    skeptic_questions: Annotated[tuple[str, ...], Field(min_length=1)]
    recommended_model_weight_cap: UnitInterval
    recommend_abstain: bool
    explanation: str = Field(min_length=1)
    action: Literal["RESEARCH_RECOMMENDATION_ONLY"] = "RESEARCH_RECOMMENDATION_ONLY"
    order_submission_enabled: Literal[False] = False
    recommendation_sha256: str

    @field_validator(
        "context_sha256",
        "prompt_sha256",
        "model_revision_sha256",
        "recommendation_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="meta reasoner hash")

    @model_validator(mode="after")
    def validate_recommendation(self) -> Self:
        if self.generated_at > self.available_at:
            raise ValueError("AQ-P09-META-REASONER-TIME-ORDER")
        if self.conflict_codes != tuple(sorted(set(self.conflict_codes))):
            raise ValueError("meta reasoner conflict codes must be sorted and unique")
        if len(set(self.skeptic_questions)) != len(self.skeptic_questions):
            raise ValueError("meta reasoner skeptic questions must be unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"recommendation_sha256"}))
        if self.recommendation_sha256 != expected:
            raise ValueError("AQ-P09-META-REASONER-HASH-MISMATCH")
        return self


def create_meta_reasoner_recommendation(
    *,
    context_sha256: str,
    prompt_sha256: str,
    model_revision_sha256: str,
    generated_at: UtcDateTime,
    available_at: UtcDateTime,
    conflict_codes: tuple[str, ...],
    skeptic_questions: tuple[str, ...],
    recommended_model_weight_cap: Decimal,
    recommend_abstain: bool,
    explanation: str,
) -> MetaReasonerRecommendation:
    payload = {
        "context_sha256": context_sha256,
        "prompt_sha256": prompt_sha256,
        "model_revision_sha256": model_revision_sha256,
        "generated_at": generated_at,
        "available_at": available_at,
        "conflict_codes": tuple(sorted(set(conflict_codes))),
        "skeptic_questions": skeptic_questions,
        "recommended_model_weight_cap": recommended_model_weight_cap,
        "recommend_abstain": recommend_abstain,
        "explanation": explanation,
        "action": "RESEARCH_RECOMMENDATION_ONLY",
        "order_submission_enabled": False,
    }
    candidate = MetaReasonerRecommendation.model_construct(
        **cast("dict[str, Any]", payload),
        recommendation_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"recommendation_sha256"}))
    return MetaReasonerRecommendation.model_validate({**payload, "recommendation_sha256": digest})


class SkepticFinding(DomainModel):
    code: str = Field(min_length=1)
    severity: SkepticSeverity
    blocks_new_risk: bool
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_finding(self) -> Self:
        if (
            self.severity in {SkepticSeverity.HIGH, SkepticSeverity.CRITICAL}
            and not self.blocks_new_risk
        ):
            raise ValueError("AQ-P09-SEVERE-SKEPTIC-FINDING-MUST-BLOCK")
        return self


class IndependentSkepticAssessment(DomainModel):
    context_sha256: str
    prompt_sha256: str
    model_revision_sha256: str
    generated_at: UtcDateTime
    available_at: UtcDateTime
    findings: Annotated[tuple[SkepticFinding, ...], Field(min_length=1)]
    shared_final_prompt: Literal[False] = False
    action: Literal["RESEARCH_RECOMMENDATION_ONLY"] = "RESEARCH_RECOMMENDATION_ONLY"
    order_submission_enabled: Literal[False] = False
    assessment_sha256: str

    @field_validator(
        "context_sha256",
        "prompt_sha256",
        "model_revision_sha256",
        "assessment_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="independent skeptic hash")

    @model_validator(mode="after")
    def validate_assessment(self) -> Self:
        if self.generated_at > self.available_at:
            raise ValueError("AQ-P09-SKEPTIC-TIME-ORDER")
        codes = tuple(finding.code for finding in self.findings)
        if codes != tuple(sorted(set(codes))):
            raise ValueError("skeptic findings must be sorted and unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"assessment_sha256"}))
        if self.assessment_sha256 != expected:
            raise ValueError("AQ-P09-SKEPTIC-HASH-MISMATCH")
        return self


def create_independent_skeptic_assessment(
    *,
    context_sha256: str,
    prompt_sha256: str,
    model_revision_sha256: str,
    generated_at: UtcDateTime,
    available_at: UtcDateTime,
    findings: tuple[SkepticFinding, ...],
) -> IndependentSkepticAssessment:
    ordered = tuple(sorted(findings, key=lambda item: item.code))
    payload = {
        "context_sha256": context_sha256,
        "prompt_sha256": prompt_sha256,
        "model_revision_sha256": model_revision_sha256,
        "generated_at": generated_at,
        "available_at": available_at,
        "findings": ordered,
        "shared_final_prompt": False,
        "action": "RESEARCH_RECOMMENDATION_ONLY",
        "order_submission_enabled": False,
    }
    candidate = IndependentSkepticAssessment.model_construct(
        **cast("dict[str, Any]", payload),
        assessment_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"assessment_sha256"}))
    return IndependentSkepticAssessment.model_validate({**payload, "assessment_sha256": digest})


class DynamicStackingPolicy(DomainModel):
    maximum_single_model_weight: UnitInterval
    maximum_weight_step: UnitInterval
    maximum_ood_score: NonNegativeDecimal
    minimum_data_quality: UnitInterval
    minimum_model_reliability: UnitInterval

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.maximum_single_model_weight <= 0:
            raise ValueError("dynamic stacking weight cap must be positive")
        return self


class WeightEvidenceBinding(DomainModel):
    source: WeightEvidenceSource
    artifact_sha256: str

    @field_validator("artifact_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="stacking evidence hash")


class StatisticalWeightProposal(DomainModel):
    asset_id: AssetId
    horizon: CouncilHorizon
    regime: MarketRegime
    training_cutoff: UtcDateTime
    available_at: UtcDateTime
    previous_weights: StackingWeights
    proposed_weights: StackingWeights
    evidence_bindings: Annotated[tuple[WeightEvidenceBinding, ...], Field(min_length=1)]
    split_sha256: str
    final_holdout_used: Literal[False] = False
    proposal_sha256: str

    @field_validator("split_sha256", "proposal_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="statistical weight proposal hash")

    @model_validator(mode="after")
    def validate_proposal(self) -> Self:
        if self.training_cutoff > self.available_at:
            raise ValueError("AQ-P09-STACKING-PROPOSAL-TIME-ORDER")
        if set(self.previous_weights.weights) != set(self.proposed_weights.weights):
            raise ValueError("AQ-P09-STACKING-MODEL-SET-MISMATCH")
        sources = tuple(binding.source for binding in self.evidence_bindings)
        required = {WeightEvidenceSource.VALIDATION, WeightEvidenceSource.CALIBRATION}
        if not required <= set(sources) or len(sources) != len(set(sources)):
            raise ValueError("AQ-P09-STACKING-EVIDENCE-INCOMPLETE")
        if sources != tuple(sorted(sources, key=lambda item: item.value)):
            raise ValueError("stacking evidence bindings must be sorted by source")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"proposal_sha256"}))
        if self.proposal_sha256 != expected:
            raise ValueError("AQ-P09-STACKING-PROPOSAL-HASH-MISMATCH")
        return self


def create_statistical_weight_proposal(
    *,
    asset_id: AssetId,
    horizon: CouncilHorizon,
    regime: MarketRegime,
    training_cutoff: UtcDateTime,
    available_at: UtcDateTime,
    previous_weights: StackingWeights,
    proposed_weights: StackingWeights,
    evidence_sha256_by_source: dict[WeightEvidenceSource, str],
    split_sha256: str,
) -> StatisticalWeightProposal:
    payload = {
        "asset_id": asset_id,
        "horizon": horizon,
        "regime": regime,
        "training_cutoff": training_cutoff,
        "available_at": available_at,
        "previous_weights": previous_weights,
        "proposed_weights": proposed_weights,
        "evidence_bindings": tuple(
            WeightEvidenceBinding(source=source, artifact_sha256=artifact_sha256)
            for source, artifact_sha256 in sorted(
                evidence_sha256_by_source.items(), key=lambda item: item[0].value
            )
        ),
        "split_sha256": split_sha256,
        "final_holdout_used": False,
    }
    candidate = StatisticalWeightProposal.model_construct(
        **cast("dict[str, Any]", payload), proposal_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"proposal_sha256"}))
    return StatisticalWeightProposal.model_validate({**payload, "proposal_sha256": digest})


class RegimeRoutingSnapshot(DomainModel):
    asset_id: AssetId
    horizon: CouncilHorizon
    regime: MarketRegime
    observed_at: UtcDateTime
    available_at: UtcDateTime
    decision_time: UtcDateTime
    data_quality: UnitInterval
    truth_state: TruthState
    ood_score: NonNegativeDecimal
    model_reliability_by_id: dict[str, UnitInterval]
    snapshot_sha256: str

    @field_validator("snapshot_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="regime routing snapshot hash")

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.observed_at > self.available_at:
            raise ValueError("AQ-P09-REGIME-OBSERVATION-TIME-ORDER")
        assert_point_in_time(available_time=self.available_at, decision_time=self.decision_time)
        if not self.model_reliability_by_id or any(
            not model_id.strip() for model_id in self.model_reliability_by_id
        ):
            raise ValueError("regime routing reliability map cannot be empty")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"snapshot_sha256"}))
        if self.snapshot_sha256 != expected:
            raise ValueError("AQ-P09-REGIME-SNAPSHOT-HASH-MISMATCH")
        return self


def create_regime_routing_snapshot(
    *,
    asset_id: AssetId,
    horizon: CouncilHorizon,
    regime: MarketRegime,
    observed_at: UtcDateTime,
    available_at: UtcDateTime,
    decision_time: UtcDateTime,
    data_quality: Decimal,
    truth_state: TruthState,
    ood_score: Decimal,
    model_reliability_by_id: dict[str, Decimal],
) -> RegimeRoutingSnapshot:
    payload = {
        "asset_id": asset_id,
        "horizon": horizon,
        "regime": regime,
        "observed_at": observed_at,
        "available_at": available_at,
        "decision_time": decision_time,
        "data_quality": data_quality,
        "truth_state": truth_state,
        "ood_score": ood_score,
        "model_reliability_by_id": model_reliability_by_id,
    }
    candidate = RegimeRoutingSnapshot.model_construct(
        **cast("dict[str, Any]", payload), snapshot_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"snapshot_sha256"}))
    return RegimeRoutingSnapshot.model_validate({**payload, "snapshot_sha256": digest})


def _derive_route(
    snapshot: RegimeRoutingSnapshot,
    proposal: StatisticalWeightProposal,
    policy: DynamicStackingPolicy,
) -> tuple[StackingWeights | None, tuple[str, ...]]:
    if (
        snapshot.asset_id != proposal.asset_id
        or snapshot.horizon is not proposal.horizon
        or snapshot.regime is not proposal.regime
    ):
        raise ValueError("AQ-P09-REGIME-PROPOSAL-CELL-MISMATCH")
    assert_point_in_time(available_time=proposal.available_at, decision_time=snapshot.decision_time)
    model_ids = set(proposal.proposed_weights.weights)
    if set(snapshot.model_reliability_by_id) != model_ids:
        raise ValueError("AQ-P09-REGIME-RELIABILITY-MODEL-SET-MISMATCH")
    reasons: set[str] = set()
    if policy.maximum_single_model_weight * len(model_ids) < Decimal("1"):
        reasons.add("DYNAMIC_WEIGHT_CAP_INFEASIBLE")
    if snapshot.regime is MarketRegime.OOD or snapshot.ood_score > policy.maximum_ood_score:
        reasons.add("OUT_OF_DISTRIBUTION")
    if snapshot.regime is MarketRegime.UNKNOWN:
        reasons.add("UNKNOWN_REGIME")
    if snapshot.data_quality < policy.minimum_data_quality:
        reasons.add("DATA_QUALITY_BELOW_POLICY")
    if snapshot.truth_state in {
        TruthState.UNVERIFIED,
        TruthState.RUMOR,
        TruthState.CONTRADICTED,
        TruthState.RETRACTED,
        TruthState.STALE,
        TruthState.UNKNOWN,
    }:
        reasons.add("TRUTH_UNCERTAIN")
    if any(
        reliability < policy.minimum_model_reliability
        for reliability in snapshot.model_reliability_by_id.values()
    ):
        reasons.add("MODEL_RELIABILITY_DEGRADED")
    if any(
        weight > policy.maximum_single_model_weight
        for weights in (proposal.previous_weights, proposal.proposed_weights)
        for weight in weights.weights.values()
    ):
        reasons.add("DYNAMIC_WEIGHT_CAP_EXCEEDED")
    if reasons:
        return None, tuple(sorted(reasons))
    selected = smooth_weights(
        previous=proposal.previous_weights,
        proposed=proposal.proposed_weights,
        maximum_step=policy.maximum_weight_step,
    )
    if any(weight > policy.maximum_single_model_weight for weight in selected.weights.values()):
        return None, ("DYNAMIC_WEIGHT_CAP_EXCEEDED",)
    if any(
        abs(selected.weights[model_id] - proposal.previous_weights.weights[model_id])
        > policy.maximum_weight_step
        for model_id in model_ids
    ):
        return None, ("DYNAMIC_WEIGHT_STEP_EXCEEDED",)
    return selected, ()


class RegimeRoutingDecision(DomainModel):
    snapshot: RegimeRoutingSnapshot
    proposal: StatisticalWeightProposal
    policy: DynamicStackingPolicy
    selected_weights: StackingWeights | None
    should_abstain: bool
    reason_codes: tuple[str, ...]
    decision_sha256: str

    @field_validator("decision_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="regime routing decision hash")

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        expected_weights, expected_reasons = _derive_route(
            self.snapshot,
            self.proposal,
            self.policy,
        )
        if (
            self.selected_weights != expected_weights
            or self.reason_codes != expected_reasons
            or self.should_abstain != bool(expected_reasons)
        ):
            raise ValueError("AQ-P09-REGIME-ROUTE-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
        if self.decision_sha256 != expected_hash:
            raise ValueError("AQ-P09-REGIME-ROUTE-HASH-MISMATCH")
        return self


def route_dynamic_stacking(
    *,
    snapshot: RegimeRoutingSnapshot,
    proposal: StatisticalWeightProposal,
    policy: DynamicStackingPolicy,
) -> RegimeRoutingDecision:
    validated_snapshot = RegimeRoutingSnapshot.model_validate_json(snapshot.model_dump_json())
    validated_proposal = StatisticalWeightProposal.model_validate_json(proposal.model_dump_json())
    validated_policy = DynamicStackingPolicy.model_validate_json(policy.model_dump_json())
    selected, reasons = _derive_route(validated_snapshot, validated_proposal, validated_policy)
    payload = {
        "snapshot": validated_snapshot,
        "proposal": validated_proposal,
        "policy": validated_policy,
        "selected_weights": selected,
        "should_abstain": bool(reasons),
        "reason_codes": reasons,
    }
    candidate = RegimeRoutingDecision.model_construct(
        **cast("dict[str, Any]", payload), decision_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"decision_sha256"}))
    return RegimeRoutingDecision.model_validate({**payload, "decision_sha256": digest})


class IntervalCoverageObservation(DomainModel):
    sample_id: str = Field(min_length=1)
    predicted_lower: FiniteDecimal
    predicted_median: FiniteDecimal
    predicted_upper: FiniteDecimal
    realized_value: FiniteDecimal
    predicted_at: UtcDateTime
    outcome_available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if not self.predicted_lower <= self.predicted_median <= self.predicted_upper:
            raise ValueError("AQ-P09-COVERAGE-INTERVAL-ORDER")
        if self.predicted_at > self.outcome_available_at:
            raise ValueError("AQ-P09-COVERAGE-OUTCOME-TIME-ORDER")
        return self


class IntervalCoverageWindow(DomainModel):
    asset_id: AssetId
    horizon: CouncilHorizon
    regime: MarketRegime
    model_revision_sha256: str
    dataset_manifest_sha256: str
    calibration_artifact_sha256: str
    window_start: UtcDateTime
    window_end: UtcDateTime
    decision_time: UtcDateTime
    observations: Annotated[tuple[IntervalCoverageObservation, ...], Field(min_length=2)]
    window_sha256: str

    @field_validator(
        "model_revision_sha256",
        "dataset_manifest_sha256",
        "calibration_artifact_sha256",
        "window_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="interval coverage window hash")

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if not self.window_start < self.window_end <= self.decision_time:
            raise ValueError("AQ-P09-COVERAGE-WINDOW-TIME-ORDER")
        sample_ids = tuple(observation.sample_id for observation in self.observations)
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError("AQ-P09-DUPLICATE-COVERAGE-SAMPLE")
        ordered = tuple(
            sorted(
                self.observations,
                key=lambda item: (item.outcome_available_at, item.sample_id),
            )
        )
        if self.observations != ordered:
            raise ValueError("coverage observations must be ordered by outcome availability")
        if any(
            not (
                self.window_start
                <= item.predicted_at
                <= item.outcome_available_at
                <= self.window_end
            )
            for item in self.observations
        ):
            raise ValueError("AQ-P09-COVERAGE-OBSERVATION-OUTSIDE-WINDOW")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"window_sha256"}))
        if self.window_sha256 != expected:
            raise ValueError("AQ-P09-COVERAGE-WINDOW-HASH-MISMATCH")
        return self


def create_interval_coverage_window(
    *,
    asset_id: AssetId,
    horizon: CouncilHorizon,
    regime: MarketRegime,
    model_revision_sha256: str,
    dataset_manifest_sha256: str,
    calibration_artifact_sha256: str,
    window_start: UtcDateTime,
    window_end: UtcDateTime,
    decision_time: UtcDateTime,
    observations: tuple[IntervalCoverageObservation, ...],
) -> IntervalCoverageWindow:
    ordered = tuple(
        sorted(observations, key=lambda item: (item.outcome_available_at, item.sample_id))
    )
    payload = {
        "asset_id": asset_id,
        "horizon": horizon,
        "regime": regime,
        "model_revision_sha256": model_revision_sha256,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "calibration_artifact_sha256": calibration_artifact_sha256,
        "window_start": window_start,
        "window_end": window_end,
        "decision_time": decision_time,
        "observations": ordered,
    }
    candidate = IntervalCoverageWindow.model_construct(
        **cast("dict[str, Any]", payload), window_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"window_sha256"}))
    return IntervalCoverageWindow.model_validate({**payload, "window_sha256": digest})


class AdaptiveConformalPolicy(DomainModel):
    method: CalibrationMethod
    target_coverage: UnitInterval
    warning_shortfall: UnitInterval
    critical_shortfall: UnitInterval
    minimum_sample_count: int = Field(ge=2)
    maximum_window_age_seconds: PositiveDecimal
    maximum_adjustment_step: PositiveDecimal

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.method not in {
            CalibrationMethod.ADAPTIVE_CONFORMAL,
            CalibrationMethod.DISTRIBUTION_AWARE_CONFORMAL,
        }:
            raise ValueError("AQ-P09-STATIC-CONFORMAL-FORBIDDEN")
        if not Decimal("0") < self.target_coverage < Decimal("1"):
            raise ValueError("adaptive conformal target coverage must be between zero and one")
        if not Decimal("0") < self.warning_shortfall <= self.critical_shortfall:
            raise ValueError("adaptive conformal drift thresholds are invalid")
        return self


def _coverage_quantile(values: tuple[Decimal, ...], coverage: Decimal) -> Decimal:
    ordered = tuple(sorted(values))
    rank = int((Decimal(len(ordered) + 1) * coverage).to_integral_value(rounding=ROUND_CEILING))
    return ordered[min(len(ordered), max(1, rank)) - 1]


def _derive_coverage(
    window: IntervalCoverageWindow,
    policy: AdaptiveConformalPolicy,
) -> tuple[
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    bool,
    CalibrationDriftAction,
    tuple[str, ...],
]:
    observations = window.observations
    covered_count = sum(
        item.predicted_lower <= item.realized_value <= item.predicted_upper for item in observations
    )
    observed_coverage = Decimal(covered_count) / Decimal(len(observations))
    shortfall = max(policy.target_coverage - observed_coverage, Decimal("0"))
    overcoverage = max(observed_coverage - policy.target_coverage, Decimal("0"))
    calibration_drift = abs(observed_coverage - policy.target_coverage)
    half_widths = tuple(
        max(
            item.predicted_median - item.predicted_lower,
            item.predicted_upper - item.predicted_median,
        )
        for item in observations
    )
    current_half_width = sum(half_widths, Decimal("0")) / Decimal(len(observations))
    distribution_scale_normalized = policy.method is CalibrationMethod.DISTRIBUTION_AWARE_CONFORMAL
    if distribution_scale_normalized:
        if any(width <= 0 for width in half_widths):
            raise ValueError("AQ-P09-DISTRIBUTION-SCALE-NONPOSITIVE")
        normalized_nonconformity = tuple(
            abs(item.realized_value - item.predicted_median) / width
            for item, width in zip(observations, half_widths, strict=True)
        )
        raw_quantile = (
            _coverage_quantile(normalized_nonconformity, policy.target_coverage)
            * current_half_width
        )
    else:
        nonconformity = tuple(
            abs(item.realized_value - item.predicted_median) for item in observations
        )
        raw_quantile = _coverage_quantile(nonconformity, policy.target_coverage)
    adjustment = raw_quantile - current_half_width
    bounded_adjustment = max(
        -policy.maximum_adjustment_step,
        min(policy.maximum_adjustment_step, adjustment),
    )
    recommended_quantile = max(Decimal("0"), current_half_width + bounded_adjustment)
    recommended_scale_multiplier = (
        recommended_quantile / current_half_width if current_half_width > 0 else Decimal("0")
    )
    age_seconds = Decimal(str((window.decision_time - window.window_end).total_seconds()))
    reasons: set[str] = set()
    if len(observations) < policy.minimum_sample_count:
        reasons.add("INSUFFICIENT_COVERAGE_SAMPLES")
    if age_seconds > policy.maximum_window_age_seconds:
        reasons.add("STALE_COVERAGE_WINDOW")
    if shortfall >= policy.critical_shortfall:
        reasons.add("INTERVAL_UNDERCOVERAGE_CRITICAL")
    elif shortfall >= policy.warning_shortfall:
        reasons.add("INTERVAL_UNDERCOVERAGE_WARNING")
    if overcoverage >= policy.critical_shortfall:
        reasons.add("INTERVAL_OVERCOVERAGE_CRITICAL")
    if {
        "INSUFFICIENT_COVERAGE_SAMPLES",
        "STALE_COVERAGE_WINDOW",
        "INTERVAL_UNDERCOVERAGE_CRITICAL",
    } & reasons:
        action = CalibrationDriftAction.ABSTAIN
    elif "INTERVAL_OVERCOVERAGE_CRITICAL" in reasons:
        action = CalibrationDriftAction.DEGRADE
    elif reasons:
        action = CalibrationDriftAction.RECALIBRATE
    else:
        action = CalibrationDriftAction.NONE
    return (
        observed_coverage,
        shortfall,
        calibration_drift,
        recommended_quantile,
        recommended_scale_multiplier,
        distribution_scale_normalized,
        action,
        tuple(sorted(reasons)),
    )


class AdaptiveConformalReport(DomainModel):
    window: IntervalCoverageWindow
    policy: AdaptiveConformalPolicy
    observed_coverage: UnitInterval
    coverage_shortfall: UnitInterval
    calibration_drift: UnitInterval
    recommended_residual_quantile: NonNegativeDecimal
    recommended_scale_multiplier: NonNegativeDecimal
    distribution_scale_normalized: bool
    action: CalibrationDriftAction
    reason_codes: tuple[str, ...]
    exchangeability_assumed: Literal[False] = False
    real_world_coverage_claimed: Literal[False] = False
    report_sha256: str

    @field_validator("report_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="adaptive conformal report hash")

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        expected = _derive_coverage(self.window, self.policy)
        actual = (
            self.observed_coverage,
            self.coverage_shortfall,
            self.calibration_drift,
            self.recommended_residual_quantile,
            self.recommended_scale_multiplier,
            self.distribution_scale_normalized,
            self.action,
            self.reason_codes,
        )
        if actual != expected:
            raise ValueError("AQ-P09-COVERAGE-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("AQ-P09-COVERAGE-REPORT-HASH-MISMATCH")
        return self


def evaluate_adaptive_conformal(
    *,
    window: IntervalCoverageWindow,
    policy: AdaptiveConformalPolicy,
) -> AdaptiveConformalReport:
    validated_window = IntervalCoverageWindow.model_validate_json(window.model_dump_json())
    validated_policy = AdaptiveConformalPolicy.model_validate_json(policy.model_dump_json())
    (
        coverage,
        shortfall,
        drift,
        residual_quantile,
        scale_multiplier,
        distribution_scale_normalized,
        action,
        reasons,
    ) = _derive_coverage(validated_window, validated_policy)
    payload = {
        "window": validated_window,
        "policy": validated_policy,
        "observed_coverage": coverage,
        "coverage_shortfall": shortfall,
        "calibration_drift": drift,
        "recommended_residual_quantile": residual_quantile,
        "recommended_scale_multiplier": scale_multiplier,
        "distribution_scale_normalized": distribution_scale_normalized,
        "action": action,
        "reason_codes": reasons,
        "exchangeability_assumed": False,
        "real_world_coverage_claimed": False,
    }
    candidate = AdaptiveConformalReport.model_construct(
        **cast("dict[str, Any]", payload), report_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"report_sha256"}))
    return AdaptiveConformalReport.model_validate({**payload, "report_sha256": digest})


class AdaptiveCalibratedInterval(DomainModel):
    asset_id: AssetId
    horizon: CouncilHorizon
    regime: MarketRegime
    lower: FiniteDecimal
    median: FiniteDecimal
    upper: FiniteDecimal
    calibration_report_sha256: str

    @field_validator("calibration_report_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="adaptive interval calibration hash")

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if not self.lower <= self.median <= self.upper:
            raise ValueError("AQ-P09-ADAPTIVE-INTERVAL-ORDER")
        return self


def adaptive_conformal_interval(
    *,
    prediction: Decimal,
    report: AdaptiveConformalReport,
    base_half_width: Decimal | None = None,
) -> AdaptiveCalibratedInterval:
    validated = AdaptiveConformalReport.model_validate_json(report.model_dump_json())
    if validated.action is CalibrationDriftAction.ABSTAIN:
        raise ValueError("AQ-P09-CALIBRATION-ABSTAIN")
    if validated.distribution_scale_normalized:
        if base_half_width is None:
            raise ValueError("AQ-P09-DISTRIBUTION-BASE-SCALE-REQUIRED")
        width = validate_decimal(base_half_width)
        if width <= 0:
            raise ValueError("AQ-P09-DISTRIBUTION-BASE-SCALE-NONPOSITIVE")
        width *= validated.recommended_scale_multiplier
    else:
        if base_half_width is not None:
            raise ValueError("AQ-P09-ADAPTIVE-BASE-SCALE-UNEXPECTED")
        width = validated.recommended_residual_quantile
    return AdaptiveCalibratedInterval(
        asset_id=validated.window.asset_id,
        horizon=validated.window.horizon,
        regime=validated.window.regime,
        lower=prediction - width,
        median=prediction,
        upper=prediction + width,
        calibration_report_sha256=validated.report_sha256,
    )


def _governance_reasons(
    *,
    meta_reasoner: MetaReasonerRecommendation,
    skeptic: IndependentSkepticAssessment,
    disagreement: CouncilDisagreementReport,
    route: RegimeRoutingDecision,
    calibration: AdaptiveConformalReport,
) -> tuple[str, ...]:
    reasons: set[str] = set(disagreement.reason_codes) | set(route.reason_codes)
    if meta_reasoner.recommend_abstain:
        reasons.add("META_REASONER_RECOMMENDS_ABSTAIN")
    for finding in skeptic.findings:
        if finding.blocks_new_risk:
            reasons.add(f"SKEPTIC_{finding.code}")
    if calibration.action is not CalibrationDriftAction.NONE:
        reasons.add(f"CALIBRATION_{calibration.action.value}")
        reasons.update(calibration.reason_codes)
    model_count = len(route.proposal.proposed_weights.weights)
    if meta_reasoner.recommended_model_weight_cap * model_count < Decimal("1"):
        reasons.add("META_MIXTURE_CAP_INFEASIBLE")
    if route.selected_weights is not None and any(
        weight > meta_reasoner.recommended_model_weight_cap
        for weight in route.selected_weights.weights.values()
    ):
        reasons.add("META_MIXTURE_CAP_REQUIRES_REVIEW")
    return tuple(sorted(reasons))


class ForecastGovernanceReport(DomainModel):
    context: ReasoningContext
    meta_reasoner: MetaReasonerRecommendation
    skeptic: IndependentSkepticAssessment
    disagreement: CouncilDisagreementReport
    regime_route: RegimeRoutingDecision
    calibration: AdaptiveConformalReport
    should_abstain: bool
    reason_codes: tuple[str, ...]
    structured_recommendation_only: Literal[True] = True
    statistically_learned_ensemble_controls_weights: Literal[True] = True
    llm_can_order: Literal[False] = False
    evidence_tier: Literal[EvidenceTier.DEVELOPMENT] = EvidenceTier.DEVELOPMENT
    alpha_promotion_eligible: Literal[False] = False
    final_holdout_opened: Literal[False] = False
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    report_sha256: str

    @field_validator("report_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forecast governance report hash")

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if (
            self.meta_reasoner.context_sha256 != self.context.context_sha256
            or self.skeptic.context_sha256 != self.context.context_sha256
        ):
            raise ValueError("AQ-P09-REASONING-CONTEXT-SPLICE")
        if (
            self.meta_reasoner.prompt_sha256 != self.context.meta_reasoner_prompt_sha256
            or self.meta_reasoner.model_revision_sha256
            != self.context.meta_reasoner_model_revision_sha256
            or self.skeptic.prompt_sha256 != self.context.skeptic_prompt_sha256
            or self.skeptic.model_revision_sha256 != self.context.skeptic_model_revision_sha256
        ):
            raise ValueError("AQ-P09-REVIEWER-BINDING-MISMATCH")
        if (
            self.meta_reasoner.prompt_sha256 == self.skeptic.prompt_sha256
            or self.meta_reasoner.model_revision_sha256 == self.skeptic.model_revision_sha256
        ):
            raise ValueError("AQ-P09-SKEPTIC-NOT-INDEPENDENT")
        for available_at in (self.meta_reasoner.available_at, self.skeptic.available_at):
            assert_point_in_time(
                available_time=available_at,
                decision_time=self.context.decision_time,
            )
        if (
            self.context.artifact_sha256_for(ReasoningInputKind.MODEL_FORECASTS)
            != self.disagreement.snapshot.snapshot_sha256
        ):
            raise ValueError("AQ-P09-FORECAST-CONTEXT-SPLICE")
        if (
            self.context.artifact_sha256_for(ReasoningInputKind.MARKET_REGIME)
            != self.regime_route.snapshot.snapshot_sha256
            or self.context.artifact_sha256_for(ReasoningInputKind.OOD)
            != self.regime_route.snapshot.snapshot_sha256
        ):
            raise ValueError("AQ-P09-REGIME-CONTEXT-SPLICE")
        if (
            self.context.artifact_sha256_for(ReasoningInputKind.CALIBRATION)
            != self.calibration.report_sha256
        ):
            raise ValueError("AQ-P09-CALIBRATION-CONTEXT-SPLICE")
        cells = {
            (
                self.disagreement.snapshot.asset_id,
                self.disagreement.snapshot.horizon,
                self.disagreement.snapshot.regime,
            ),
            (
                self.regime_route.snapshot.asset_id,
                self.regime_route.snapshot.horizon,
                self.regime_route.snapshot.regime,
            ),
            (
                self.calibration.window.asset_id,
                self.calibration.window.horizon,
                self.calibration.window.regime,
            ),
        }
        if len(cells) != 1:
            raise ValueError("AQ-P09-GOVERNANCE-CELL-SPLICE")
        if set(signal.candidate_id for signal in self.disagreement.snapshot.signals) != set(
            self.regime_route.proposal.proposed_weights.weights
        ):
            raise ValueError("AQ-P09-GOVERNANCE-MODEL-SET-SPLICE")
        expected_reasons = _governance_reasons(
            meta_reasoner=self.meta_reasoner,
            skeptic=self.skeptic,
            disagreement=self.disagreement,
            route=self.regime_route,
            calibration=self.calibration,
        )
        if self.reason_codes != expected_reasons or self.should_abstain != bool(expected_reasons):
            raise ValueError("AQ-P09-GOVERNANCE-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("AQ-P09-GOVERNANCE-HASH-MISMATCH")
        return self


def build_forecast_governance_report(
    *,
    context: ReasoningContext,
    meta_reasoner: MetaReasonerRecommendation,
    skeptic: IndependentSkepticAssessment,
    disagreement: CouncilDisagreementReport,
    regime_route: RegimeRoutingDecision,
    calibration: AdaptiveConformalReport,
) -> ForecastGovernanceReport:
    validated_context = ReasoningContext.model_validate_json(context.model_dump_json())
    validated_meta = MetaReasonerRecommendation.model_validate_json(meta_reasoner.model_dump_json())
    validated_skeptic = IndependentSkepticAssessment.model_validate_json(skeptic.model_dump_json())
    validated_disagreement = CouncilDisagreementReport.model_validate_json(
        disagreement.model_dump_json()
    )
    validated_route = RegimeRoutingDecision.model_validate_json(regime_route.model_dump_json())
    validated_calibration = AdaptiveConformalReport.model_validate_json(
        calibration.model_dump_json()
    )
    reasons = _governance_reasons(
        meta_reasoner=validated_meta,
        skeptic=validated_skeptic,
        disagreement=validated_disagreement,
        route=validated_route,
        calibration=validated_calibration,
    )
    payload = {
        "context": validated_context,
        "meta_reasoner": validated_meta,
        "skeptic": validated_skeptic,
        "disagreement": validated_disagreement,
        "regime_route": validated_route,
        "calibration": validated_calibration,
        "should_abstain": bool(reasons),
        "reason_codes": reasons,
        "structured_recommendation_only": True,
        "statistically_learned_ensemble_controls_weights": True,
        "llm_can_order": False,
        "evidence_tier": EvidenceTier.DEVELOPMENT,
        "alpha_promotion_eligible": False,
        "final_holdout_opened": False,
        "order_submission_enabled": False,
        "live_trading_locked": True,
    }
    candidate = ForecastGovernanceReport.model_construct(
        **cast("dict[str, Any]", payload), report_sha256="0" * 64
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"report_sha256"}))
    return ForecastGovernanceReport.model_validate({**payload, "report_sha256": digest})
