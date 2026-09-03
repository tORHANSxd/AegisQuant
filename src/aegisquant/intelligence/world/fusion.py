"""Point-in-time event/market fusion and same-budget four-view ablation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.intelligence import EVENT_IMPACT_HORIZONS, ForecastHorizon
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, UnitInterval
from aegisquant.intelligence.canonical_events import (
    CanonicalEvent,
    EventDirectionalGate,
    build_event_directional_gate,
)


class FusionFeature(StrEnum):
    PRICE_RETURN = "price_return"
    BOOK_IMBALANCE = "book_imbalance"
    OPEN_INTEREST_DELTA = "open_interest_delta"
    FUNDING_RATE = "funding_rate"
    BASIS = "basis"
    ONCHAIN_FLOW = "onchain_flow"


REQUIRED_FUSION_FEATURES = frozenset(FusionFeature)


class TimedFusionFeature(DomainModel):
    asset_id: str = Field(min_length=1)
    feature: FusionFeature
    value: FiniteDecimal
    event_time: UtcDateTime
    available_at: UtcDateTime
    source_id: str = Field(min_length=1)
    source_hash: str

    @model_validator(mode="after")
    def validate_feature(self) -> TimedFusionFeature:
        if self.event_time > self.available_at:
            raise ValueError("fusion feature cannot be available before event time")
        if not Decimal("-1") <= self.value <= Decimal("1"):
            raise ValueError("fusion feature must be normalized to [-1, 1]")
        if len(self.source_hash) != 64:
            raise ValueError("fusion source hash must be SHA-256")
        return self


class FusionFeatureSnapshot(DomainModel):
    asset_id: str = Field(min_length=1)
    as_of_time: UtcDateTime
    features: tuple[TimedFusionFeature, ...]
    snapshot_hash: str

    @model_validator(mode="after")
    def require_complete_point_in_time_snapshot(self) -> FusionFeatureSnapshot:
        if {item.feature for item in self.features} != set(REQUIRED_FUSION_FEATURES):
            raise ValueError("fusion snapshot requires price/book/OI/funding/basis/on-chain")
        if len(self.features) != len(REQUIRED_FUSION_FEATURES):
            raise ValueError("fusion snapshot features cannot be duplicated")
        if any(item.asset_id != self.asset_id for item in self.features):
            raise ValueError("fusion snapshot cannot mix assets")
        if any(item.available_at > self.as_of_time for item in self.features):
            raise ValueError("AQ-FUSION-LOOKAHEAD")
        expected = canonical_sha256(
            {
                "asset_id": self.asset_id,
                "as_of_time": self.as_of_time.isoformat(),
                "features": [item.model_dump(mode="json") for item in self.features],
            }
        )
        if self.snapshot_hash != expected:
            raise ValueError("fusion snapshot hash mismatch")
        return self


def build_feature_snapshot(
    *, asset_id: str, as_of_time: datetime, features: Sequence[TimedFusionFeature]
) -> FusionFeatureSnapshot:
    as_of = ensure_utc(as_of_time)
    ordered = tuple(sorted(features, key=lambda item: item.feature.value))
    payload = {
        "asset_id": asset_id,
        "as_of_time": as_of.isoformat(),
        "features": [item.model_dump(mode="json") for item in ordered],
    }
    return FusionFeatureSnapshot(
        asset_id=asset_id,
        as_of_time=as_of,
        features=ordered,
        snapshot_hash=canonical_sha256(payload),
    )


class FusedHorizonEstimate(DomainModel):
    horizon: ForecastHorizon
    expected_return: FiniteDecimal
    volatility_delta: NonNegativeDecimal
    tail_risk_delta: NonNegativeDecimal
    confidence: UnitInterval


class AssetEventImpact(DomainModel):
    forecast_id: str
    event_cluster_id: str = Field(min_length=1)
    event_revision_id: str | None = None
    directional_gate_id: str | None = None
    asset_id: str = Field(min_length=1)
    as_of_time: UtcDateTime
    feature_snapshot_hash: str
    horizon_coefficients_sha256: str
    horizons: tuple[FusedHorizonEstimate, ...]
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    model_versions: tuple[str, ...] = Field(min_length=1)
    manipulation_risk: UnitInterval
    directional_candidate_allowed: bool
    should_abstain: bool
    abstain_reasons: tuple[str, ...]
    action: str = "RESEARCH_PROPOSAL_ONLY"

    @model_validator(mode="after")
    def enforce_forecast_shape(self) -> AssetEventImpact:
        required = set(EVENT_IMPACT_HORIZONS)
        if {item.horizon for item in self.horizons} != required or len(self.horizons) != len(
            required
        ):
            raise ValueError("fused impact requires 5m, 30m, 4h, 1d, and 7d")
        if self.should_abstain != bool(self.abstain_reasons):
            raise ValueError("fused impact abstention flag and reasons disagree")
        if self.action != "RESEARCH_PROPOSAL_ONLY":
            raise ValueError("fused impact cannot construct or submit orders")
        for name, value in (
            ("snapshot", self.feature_snapshot_hash),
            ("horizon coefficients", self.horizon_coefficients_sha256),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"fusion {name} hash must be lower-case SHA-256")
        if not self.directional_candidate_allowed:
            if (
                not self.should_abstain
                or "EVENT_DIRECTIONAL_PATH_DENIED" not in self.abstain_reasons
            ):
                raise ValueError("denied fused event direction must explicitly abstain")
            if any(item.expected_return != 0 for item in self.horizons):
                raise ValueError("denied fused event direction must have zero expected return")
        elif self.event_revision_id is None or self.directional_gate_id is None:
            raise ValueError("allowed fused direction requires canonical event and gate binding")
        if (self.event_revision_id is None) != (self.directional_gate_id is None):
            raise ValueError("fused event revision and gate must be bound together")
        return self


_FEATURE_WEIGHTS: Final = {
    FusionFeature.PRICE_RETURN: Decimal("0.24"),
    FusionFeature.BOOK_IMBALANCE: Decimal("0.16"),
    FusionFeature.OPEN_INTEREST_DELTA: Decimal("0.10"),
    FusionFeature.FUNDING_RATE: Decimal("-0.08"),
    FusionFeature.BASIS: Decimal("0.12"),
    FusionFeature.ONCHAIN_FLOW: Decimal("0.15"),
}


def fuse_event_market_impact(
    *,
    event_cluster_id: str,
    event_directional_score: Decimal,
    event_confidence: Decimal,
    manipulation_risk: Decimal,
    snapshots: Sequence[FusionFeatureSnapshot],
    evidence_ids: tuple[str, ...],
    model_versions: tuple[str, ...],
    horizon_coefficients: Mapping[ForecastHorizon, Decimal],
    event: CanonicalEvent | None = None,
    directional_gate: EventDirectionalGate | None = None,
) -> tuple[AssetEventImpact, ...]:
    if not Decimal("-1") <= event_directional_score <= Decimal("1"):
        raise ValueError("event directional score must be in [-1, 1]")
    if not Decimal("0") <= event_confidence <= Decimal("1"):
        raise ValueError("event confidence must be in [0, 1]")
    if not Decimal("0") <= manipulation_risk <= Decimal("1"):
        raise ValueError("manipulation risk must be in [0, 1]")
    if not snapshots:
        raise ValueError("fusion requires at least one asset snapshot")
    if set(horizon_coefficients) != set(EVENT_IMPACT_HORIZONS):
        raise ValueError("fusion requires one fitted coefficient per horizon")
    if any(not value.is_finite() or value < 0 for value in horizon_coefficients.values()):
        raise ValueError("fusion horizon coefficients must be finite and non-negative")
    coefficients_sha256 = canonical_sha256(
        {
            horizon.value: format(horizon_coefficients[horizon].normalize(), "f")
            for horizon in EVENT_IMPACT_HORIZONS
        }
    )
    if (event is None) != (directional_gate is None):
        raise ValueError("AQ-FUSION-CANONICAL-EVENT-GATE-PAIR-REQUIRED")
    gate_allows = False
    event_revision_id = None
    directional_gate_id = None
    if event is not None and directional_gate is not None:
        if (
            event.available_at > directional_gate.as_of_time
            or event.market_reflection.as_of_time > directional_gate.as_of_time
        ):
            raise ValueError("AQ-FUSION-CANONICAL-EVENT-LOOKAHEAD")
        expected_gate = build_event_directional_gate(
            event=event,
            as_of_time=directional_gate.as_of_time,
        )
        if (
            event_cluster_id != str(event.source_cluster.event_cluster_id)
            or directional_gate != expected_gate
        ):
            raise ValueError("AQ-FUSION-DIRECTIONAL-GATE-BINDING")
        gate_allows = directional_gate.directional_candidate_allowed
        event_revision_id = str(event.revision_id)
        directional_gate_id = str(directional_gate.gate_id)
    impacts: list[AssetEventImpact] = []
    for snapshot in snapshots:
        if directional_gate is not None and snapshot.as_of_time != directional_gate.as_of_time:
            raise ValueError("AQ-FUSION-GATE-SNAPSHOT-TIME-MISMATCH")
        by_feature = {item.feature: item.value for item in snapshot.features}
        market_score = sum(
            (by_feature[name] * weight for name, weight in _FEATURE_WEIGHTS.items()),
            Decimal("0"),
        )
        fused_score = event_directional_score * Decimal("0.55") + market_score
        confidence = event_confidence * (Decimal("1") - manipulation_risk)
        reasons: set[str] = set()
        if confidence < Decimal("0.35"):
            reasons.add("LOW_POST_RISK_CONFIDENCE")
        if directional_gate is None:
            reasons.add("CANONICAL_EVENT_GATE_REQUIRED")
        elif not gate_allows:
            reasons.update(directional_gate.reason_codes)
        directional_allowed = gate_allows and not reasons
        if not directional_allowed:
            reasons.add("EVENT_DIRECTIONAL_PATH_DENIED")
            fused_score = Decimal("0")
        horizons = tuple(
            FusedHorizonEstimate(
                horizon=horizon,
                expected_return=fused_score * horizon_coefficients[horizon],
                volatility_delta=(
                    abs(fused_score) * horizon_coefficients[horizon]
                    + manipulation_risk * horizon_coefficients[horizon]
                ),
                tail_risk_delta=manipulation_risk * horizon_coefficients[horizon],
                confidence=confidence,
            )
            for horizon in EVENT_IMPACT_HORIZONS
        )
        identity = {
            "event_cluster_id": event_cluster_id,
            "event_revision_id": event_revision_id,
            "directional_gate_id": directional_gate_id,
            "asset_id": snapshot.asset_id,
            "as_of_time": snapshot.as_of_time.isoformat(),
            "snapshot_hash": snapshot.snapshot_hash,
            "horizon_coefficients_sha256": coefficients_sha256,
            "model_versions": sorted(model_versions),
        }
        impacts.append(
            AssetEventImpact(
                forecast_id=canonical_sha256(identity),
                event_cluster_id=event_cluster_id,
                event_revision_id=event_revision_id,
                directional_gate_id=directional_gate_id,
                asset_id=snapshot.asset_id,
                as_of_time=snapshot.as_of_time,
                feature_snapshot_hash=snapshot.snapshot_hash,
                horizon_coefficients_sha256=coefficients_sha256,
                horizons=horizons,
                evidence_ids=tuple(sorted(set(evidence_ids))),
                model_versions=tuple(sorted(set(model_versions))),
                manipulation_risk=manipulation_risk,
                directional_candidate_allowed=directional_allowed,
                should_abstain=bool(reasons),
                abstain_reasons=tuple(sorted(reasons)),
            )
        )
    return tuple(impacts)


class AblationView(StrEnum):
    MARKET_ONLY = "MARKET_ONLY"
    EVENT_ONLY = "EVENT_ONLY"
    FUSED = "FUSED"
    RISK_ONLY = "RISK_ONLY"


class ResultSign(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class AblationPrediction(DomainModel):
    sample_id: str = Field(min_length=1)
    view: AblationView
    prediction_time: UtcDateTime
    feature_available_at: UtcDateTime
    outcome_available_at: UtcDateTime
    predicted_return: FiniteDecimal
    actual_return: FiniteDecimal
    compute_budget_units: int = Field(gt=0)
    dataset_manifest_hash: str

    @model_validator(mode="after")
    def enforce_oos_timing(self) -> AblationPrediction:
        if self.feature_available_at > self.prediction_time:
            raise ValueError("AQ-ABLATION-FUTURE-FEATURE")
        if self.outcome_available_at <= self.prediction_time:
            raise ValueError("ablation outcome must become available after prediction")
        if len(self.dataset_manifest_hash) != 64:
            raise ValueError("ablation dataset manifest hash must be SHA-256")
        return self


class AblationScore(DomainModel):
    view: AblationView
    sample_count: int = Field(gt=0)
    mean_absolute_error: NonNegativeDecimal
    directional_accuracy: UnitInterval
    mean_signed_error: FiniteDecimal
    incremental_mae_vs_market: FiniteDecimal
    result_sign: ResultSign
    compute_budget_units: int = Field(gt=0)


class SameBudgetAblationReport(DomainModel):
    scores: tuple[AblationScore, ...]
    sample_ids: tuple[str, ...] = Field(min_length=1)
    compute_budget_units: int = Field(gt=0)
    dataset_manifest_hash: str
    selection_performed: bool = False

    @model_validator(mode="after")
    def require_all_views_without_selection(self) -> SameBudgetAblationReport:
        if {item.view for item in self.scores} != set(AblationView) or len(self.scores) != len(
            AblationView
        ):
            raise ValueError("ablation report requires exactly four views")
        if any(item.compute_budget_units != self.compute_budget_units for item in self.scores):
            raise ValueError("ablation views must use the same compute budget")
        if self.selection_performed:
            raise ValueError("ablation report cannot select a winner post hoc")
        return self


def _sign(value: Decimal) -> int:
    return 1 if value > 0 else (-1 if value < 0 else 0)


def run_same_budget_ablation(
    predictions: Sequence[AblationPrediction],
) -> SameBudgetAblationReport:
    grouped: dict[AblationView, list[AblationPrediction]] = defaultdict(list)
    for item in predictions:
        grouped[item.view].append(item)
    if set(grouped) != set(AblationView):
        raise ValueError("ablation requires Market/Event/Fused/Risk views")
    sample_sets = {view: {item.sample_id for item in items} for view, items in grouped.items()}
    first_samples = next(iter(sample_sets.values()))
    if not first_samples or any(samples != first_samples for samples in sample_sets.values()):
        raise ValueError("ablation views must evaluate identical OOS samples")
    budgets = {sum(item.compute_budget_units for item in items) for items in grouped.values()}
    if len(budgets) != 1:
        raise ValueError("ablation views must use identical total compute budget")
    manifests = {item.dataset_manifest_hash for item in predictions}
    if len(manifests) != 1:
        raise ValueError("ablation views must use one dataset manifest")
    per_view_metrics: dict[AblationView, tuple[Decimal, Decimal, Decimal]] = {}
    for view, items in grouped.items():
        count = Decimal(len(items))
        mae = (
            sum((abs(item.predicted_return - item.actual_return) for item in items), Decimal("0"))
            / count
        )
        directional = (
            Decimal(
                sum(_sign(item.predicted_return) == _sign(item.actual_return) for item in items)
            )
            / count
        )
        signed_error = (
            sum((item.predicted_return - item.actual_return for item in items), Decimal("0"))
            / count
        )
        per_view_metrics[view] = (mae, directional, signed_error)
    market_mae = per_view_metrics[AblationView.MARKET_ONLY][0]
    total_budget = budgets.pop()
    scores: list[AblationScore] = []
    for view in AblationView:
        mae, directional, signed_error = per_view_metrics[view]
        incremental = market_mae - mae
        sign = (
            ResultSign.POSITIVE
            if incremental > 0
            else ResultSign.NEGATIVE
            if incremental < 0
            else ResultSign.NEUTRAL
        )
        scores.append(
            AblationScore(
                view=view,
                sample_count=len(grouped[view]),
                mean_absolute_error=mae,
                directional_accuracy=directional,
                mean_signed_error=signed_error,
                incremental_mae_vs_market=incremental,
                result_sign=sign,
                compute_budget_units=total_budget,
            )
        )
    return SameBudgetAblationReport(
        scores=tuple(scores),
        sample_ids=tuple(sorted(first_samples)),
        compute_budget_units=total_budget,
        dataset_manifest_hash=manifests.pop(),
    )
