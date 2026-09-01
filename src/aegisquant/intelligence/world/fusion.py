"""Point-in-time event/market fusion and same-budget four-view ablation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.intelligence import ForecastHorizon
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, UnitInterval


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
    asset_id: str = Field(min_length=1)
    as_of_time: UtcDateTime
    feature_snapshot_hash: str
    horizons: tuple[FusedHorizonEstimate, ...]
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    model_versions: tuple[str, ...] = Field(min_length=1)
    manipulation_risk: UnitInterval
    should_abstain: bool
    abstain_reasons: tuple[str, ...]
    action: str = "RESEARCH_PROPOSAL_ONLY"

    @model_validator(mode="after")
    def enforce_forecast_shape(self) -> AssetEventImpact:
        required = {
            ForecastHorizon.FIVE_MINUTES,
            ForecastHorizon.THIRTY_MINUTES,
            ForecastHorizon.FOUR_HOURS,
            ForecastHorizon.ONE_DAY,
            ForecastHorizon.SEVEN_DAYS,
        }
        if {item.horizon for item in self.horizons} != required or len(self.horizons) != len(
            required
        ):
            raise ValueError("fused impact requires 5m, 30m, 4h, 1d, and 7d")
        if self.should_abstain != bool(self.abstain_reasons):
            raise ValueError("fused impact abstention flag and reasons disagree")
        if self.action != "RESEARCH_PROPOSAL_ONLY":
            raise ValueError("fused impact cannot construct or submit orders")
        if len(self.feature_snapshot_hash) != 64:
            raise ValueError("fusion snapshot hash must be SHA-256")
        return self


_FEATURE_WEIGHTS: Final = {
    FusionFeature.PRICE_RETURN: Decimal("0.24"),
    FusionFeature.BOOK_IMBALANCE: Decimal("0.16"),
    FusionFeature.OPEN_INTEREST_DELTA: Decimal("0.10"),
    FusionFeature.FUNDING_RATE: Decimal("-0.08"),
    FusionFeature.BASIS: Decimal("0.12"),
    FusionFeature.ONCHAIN_FLOW: Decimal("0.15"),
}
_HORIZON_SCALE: Final = {
    ForecastHorizon.FIVE_MINUTES: Decimal("0.0002"),
    ForecastHorizon.THIRTY_MINUTES: Decimal("0.0005"),
    ForecastHorizon.FOUR_HOURS: Decimal("0.0010"),
    ForecastHorizon.ONE_DAY: Decimal("0.0015"),
    ForecastHorizon.SEVEN_DAYS: Decimal("0.0020"),
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
) -> tuple[AssetEventImpact, ...]:
    if not Decimal("-1") <= event_directional_score <= Decimal("1"):
        raise ValueError("event directional score must be in [-1, 1]")
    if not Decimal("0") <= event_confidence <= Decimal("1"):
        raise ValueError("event confidence must be in [0, 1]")
    if not Decimal("0") <= manipulation_risk <= Decimal("1"):
        raise ValueError("manipulation risk must be in [0, 1]")
    if not snapshots:
        raise ValueError("fusion requires at least one asset snapshot")
    impacts: list[AssetEventImpact] = []
    for snapshot in snapshots:
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
        horizons = tuple(
            FusedHorizonEstimate(
                horizon=horizon,
                expected_return=fused_score * scale,
                volatility_delta=abs(fused_score) * scale + manipulation_risk * scale,
                tail_risk_delta=manipulation_risk * scale,
                confidence=confidence,
            )
            for horizon, scale in _HORIZON_SCALE.items()
        )
        identity = {
            "event_cluster_id": event_cluster_id,
            "asset_id": snapshot.asset_id,
            "as_of_time": snapshot.as_of_time.isoformat(),
            "snapshot_hash": snapshot.snapshot_hash,
            "model_versions": sorted(model_versions),
        }
        impacts.append(
            AssetEventImpact(
                forecast_id=canonical_sha256(identity),
                event_cluster_id=event_cluster_id,
                asset_id=snapshot.asset_id,
                as_of_time=snapshot.as_of_time,
                feature_snapshot_hash=snapshot.snapshot_hash,
                horizons=horizons,
                evidence_ids=tuple(sorted(set(evidence_ids))),
                model_versions=tuple(sorted(set(model_versions))),
                manipulation_risk=manipulation_risk,
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
