"""Strict point-in-time contracts for causal event research."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.evidence import EvidenceTier, tier_can_support_alpha_promotion
from aegisquant.domain.identifiers import ArtifactId, AssetId, EventId, InstrumentId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    PositiveDecimal,
    UnitInterval,
    canonical_result,
)

if TYPE_CHECKING:
    from aegisquant.intelligence.canonical_events import CanonicalEvent

DecimalVector = Annotated[tuple[FiniteDecimal, ...], Field(min_length=1)]


def _validate_hashes(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not values or values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be non-empty, unique, and sorted")
    for value in values:
        ensure_sha256(value, field_name=field_name)
    return values


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _population_standard_deviation(values: tuple[Decimal, ...]) -> Decimal:
    mean = _mean(values)
    return (_mean(tuple((value - mean) ** 2 for value in values))).sqrt()


def _path_fit_components(
    treated: tuple[Decimal, ...], counterfactual: tuple[Decimal, ...]
) -> tuple[Decimal, Decimal, Decimal]:
    if len(treated) < 3 or len(treated) != len(counterfactual):
        raise ValueError("pre-treatment fit requires equal paths with at least three points")
    rmse = (
        _mean(
            tuple((left - right) ** 2 for left, right in zip(treated, counterfactual, strict=True))
        )
    ).sqrt()
    scale = max(
        _population_standard_deviation(treated),
        _mean(tuple(abs(value) for value in treated)),
        Decimal("0.000000000001"),
    )
    return canonical_result(rmse), scale, canonical_result(rmse / scale)


def _path_slope(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 3:
        raise ValueError("pre-trend requires at least three points")
    x_values = tuple(Decimal(index) for index in range(len(values)))
    x_mean = _mean(x_values)
    y_mean = _mean(values)
    numerator = sum(
        (
            (x_value - x_mean) * (y_value - y_mean)
            for x_value, y_value in zip(x_values, values, strict=True)
        ),
        Decimal("0"),
    )
    denominator = sum(((value - x_mean) ** 2 for value in x_values), Decimal("0"))
    return canonical_result(numerator / denominator)


def _standardized_mean_differences(
    treated: tuple[tuple[Decimal, ...], ...],
    controls: tuple[tuple[Decimal, ...], ...],
) -> tuple[Decimal, ...]:
    if not treated or not controls or len(treated[0]) != len(controls[0]):
        raise ValueError("balance matrices must be non-empty and schema aligned")
    width = len(treated[0])
    if any(len(row) != width for row in (*treated, *controls)):
        raise ValueError("balance matrices must be rectangular")
    output: list[Decimal] = []
    for index in range(width):
        treated_values = tuple(row[index] for row in treated)
        control_values = tuple(row[index] for row in controls)
        pooled = (
            (
                _population_standard_deviation(treated_values) ** 2
                + _population_standard_deviation(control_values) ** 2
            )
            / Decimal("2")
        ).sqrt()
        denominator = max(pooled, Decimal("0.000000000001"))
        output.append(
            canonical_result((_mean(treated_values) - _mean(control_values)) / denominator)
        )
    return tuple(output)


class CausalMethod(StrEnum):
    MATCHED_EVENT_STUDY = "MATCHED_EVENT_STUDY"
    SYNTHETIC_CONTROL = "SYNTHETIC_CONTROL"
    DOUBLY_ROBUST_AIPW = "DOUBLY_ROBUST_AIPW"


class CausalEstimand(StrEnum):
    ATT = "ATT"
    ATE = "ATE"


class PlaceboKind(StrEnum):
    EVENT_TIMESTAMP = "EVENT_TIMESTAMP"
    ASSET = "ASSET"
    TREATMENT_PERMUTATION = "TREATMENT_PERMUTATION"


class IdentificationStatus(StrEnum):
    IDENTIFIED = "IDENTIFIED"
    DEVELOPMENT_ONLY = "DEVELOPMENT_ONLY"
    INSUFFICIENT_IDENTIFICATION = "INSUFFICIENT_IDENTIFICATION"


class EventResponseRow(DomainModel):
    """One revision-aware event anchor with covariates at t and outcomes after t."""

    event_id: EventId
    event_revision_id: ArtifactId
    canonical_event_sha256: str
    event_type: str
    asset: AssetId
    instrument_id: InstrumentId
    decision_time: UtcDateTime
    event_available_at: UtcDateTime
    feature_available_at: UtcDateTime
    label_start_time: UtcDateTime
    label_end_time: UtcDateTime
    outcome_available_at: UtcDateTime
    truth_probability_at_t: UnitInterval
    source_quality_at_t: UnitInterval
    novelty_at_t: UnitInterval
    market_reflection_at_t: UnitInterval | None
    actual: FiniteDecimal | None
    expected: FiniteDecimal | None
    surprise: FiniteDecimal | None
    regime: str
    pre_event_returns: Annotated[tuple[FiniteDecimal, ...], Field(min_length=3)]
    pre_event_vol: NonNegativeDecimal
    spread: NonNegativeDecimal
    depth: NonNegativeDecimal
    funding: FiniteDecimal
    basis: FiniteDecimal
    open_interest: NonNegativeDecimal
    liquidations: NonNegativeDecimal
    cross_asset_state: DecimalVector
    narrative_state: DecimalVector
    return_5m: FiniteDecimal
    return_30m: FiniteDecimal
    return_4h: FiniteDecimal
    return_1d: FiniteDecimal
    return_7d: FiniteDecimal
    vol_delta: FiniteDecimal
    liquidity_delta: FiniteDecimal
    tail_event: bool
    maximum_favorable_excursion: NonNegativeDecimal
    maximum_adverse_excursion: FiniteDecimal
    missing_feature_codes: tuple[str, ...] = ()
    source_dataset_ids: tuple[str, ...]
    feature_snapshot_sha256: str
    label_sha256: str
    universe_snapshot_sha256: str

    @field_validator(
        "canonical_event_sha256",
        "feature_snapshot_sha256",
        "label_sha256",
        "universe_snapshot_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="event response lineage hash")

    @field_validator("source_dataset_ids")
    @classmethod
    def validate_sources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise ValueError("source dataset ids must be non-empty, unique, and sorted")
        return values

    @field_validator("missing_feature_codes")
    @classmethod
    def validate_missing_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise ValueError("missing feature codes must be unique and sorted")
        return values

    @model_validator(mode="after")
    def validate_temporal_and_value_contract(self) -> Self:
        if not self.event_type.strip() or not self.regime.strip():
            raise ValueError("event type and regime cannot be blank")
        if self.event_available_at > self.decision_time:
            raise ValueError("AQ-CAUSAL-EVENT-LOOKAHEAD")
        if self.feature_available_at > self.decision_time:
            raise ValueError("AQ-CAUSAL-FEATURE-LOOKAHEAD")
        if not self.decision_time < self.label_start_time <= self.label_end_time:
            raise ValueError("AQ-CAUSAL-LABEL-WINDOW-INVALID")
        if self.label_end_time < self.decision_time + timedelta(days=7):
            raise ValueError("AQ-CAUSAL-SEVEN-DAY-OUTCOME-INCOMPLETE")
        if self.outcome_available_at < self.label_end_time:
            raise ValueError("AQ-CAUSAL-OUTCOME-AVAILABLE-BEFORE-LABEL")
        values = (self.actual, self.expected, self.surprise)
        if any(value is None for value in values) and any(value is not None for value in values):
            raise ValueError("actual, expected, and surprise must be present or missing together")
        if self.actual is not None and self.expected is not None and self.surprise is not None:
            if self.surprise != canonical_result(self.actual - self.expected):
                raise ValueError("AQ-CAUSAL-SURPRISE-MISMATCH")
        elif "EVENT_VALUE_MISSING" not in self.missing_feature_codes:
            raise ValueError("missing event values require EVENT_VALUE_MISSING")
        if (
            self.market_reflection_at_t is None
            and "MARKET_REFLECTION_MISSING" not in self.missing_feature_codes
        ):
            raise ValueError("missing reflection requires MARKET_REFLECTION_MISSING")
        if self.maximum_adverse_excursion > 0:
            raise ValueError("maximum adverse excursion must be non-positive")
        return self

    @classmethod
    def from_canonical_event(
        cls,
        *,
        canonical_event: CanonicalEvent,
        row_values: Mapping[str, object],
    ) -> EventResponseRow:
        """Build a row while binding every event-derived scalar to one revision."""

        bound_fields = {
            "event_id",
            "event_revision_id",
            "canonical_event_sha256",
            "event_type",
            "event_available_at",
            "truth_probability_at_t",
            "source_quality_at_t",
            "novelty_at_t",
            "market_reflection_at_t",
            "actual",
            "expected",
            "surprise",
        }
        overlap = bound_fields.intersection(row_values)
        if overlap:
            raise ValueError("AQ-CAUSAL-CANONICAL-BOUND-FIELD-OVERRIDE")
        truth = canonical_event.truth_assessment
        source_quality = min(
            truth.source_identity_probability,
            truth.content_integrity_probability,
            truth.evidence_independence_probability,
        )
        return cls.model_validate(
            {
                **row_values,
                "event_id": canonical_event.event_id,
                "event_revision_id": canonical_event.revision_id,
                "canonical_event_sha256": canonical_event.canonical_sha256,
                "event_type": canonical_event.event_type,
                "event_available_at": canonical_event.available_at,
                "truth_probability_at_t": truth.claim_truth_probability,
                "source_quality_at_t": source_quality,
                "novelty_at_t": canonical_event.novelty,
                "market_reflection_at_t": (
                    canonical_event.market_reflection.market_reflection_score
                ),
                "actual": canonical_event.actual_value,
                "expected": canonical_event.expected_value,
                "surprise": canonical_event.surprise_value,
            }
        )

    def assert_canonical_event_binding(self, canonical_event: CanonicalEvent) -> None:
        """Reject a row whose valid-looking references came from different revisions."""

        truth = canonical_event.truth_assessment
        source_quality = min(
            truth.source_identity_probability,
            truth.content_integrity_probability,
            truth.evidence_independence_probability,
        )
        expected = (
            canonical_event.event_id,
            canonical_event.revision_id,
            canonical_event.canonical_sha256,
            canonical_event.event_type,
            canonical_event.available_at,
            truth.claim_truth_probability,
            source_quality,
            canonical_event.novelty,
            canonical_event.market_reflection.market_reflection_score,
            canonical_event.actual_value,
            canonical_event.expected_value,
            canonical_event.surprise_value,
        )
        actual = (
            self.event_id,
            self.event_revision_id,
            self.canonical_event_sha256,
            self.event_type,
            self.event_available_at,
            self.truth_probability_at_t,
            self.source_quality_at_t,
            self.novelty_at_t,
            self.market_reflection_at_t,
            self.actual,
            self.expected,
            self.surprise,
        )
        if actual != expected:
            raise ValueError("AQ-CAUSAL-CANONICAL-EVENT-BINDING-MISMATCH")

    @property
    def row_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class EventResponseDataset(DomainModel):
    """Content-addressed, revision-aware causal response dataset."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    dataset_id: str
    dataset_sha256: str
    evidence_tier: EvidenceTier
    as_of_time: UtcDateTime
    created_at: UtcDateTime
    revision_aware: Literal[True] = True
    point_in_time: Literal[True] = True
    shuffle: Literal[False] = False
    rows: Annotated[tuple[EventResponseRow, ...], Field(min_length=4)]
    source_dataset_ids: tuple[str, ...]
    feature_snapshot_hashes: tuple[str, ...]
    label_hashes: tuple[str, ...]
    universe_snapshot_hashes: tuple[str, ...]
    feature_definition_hashes: tuple[str, ...]
    label_definition_hashes: tuple[str, ...]
    cost_policy_sha256: str

    @field_validator("dataset_sha256", "cost_policy_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="event response dataset hash")

    @field_validator(
        "feature_snapshot_hashes",
        "label_hashes",
        "universe_snapshot_hashes",
        "feature_definition_hashes",
        "label_definition_hashes",
    )
    @classmethod
    def validate_hash_collection(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_hashes(values, "event response hash collection")

    @field_validator("source_dataset_ids")
    @classmethod
    def validate_source_collection(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise ValueError("dataset source ids must be non-empty, unique, and sorted")
        return values

    @model_validator(mode="after")
    def validate_dataset(self) -> Self:
        if not self.dataset_id.strip():
            raise ValueError("dataset id cannot be blank")
        if self.created_at < self.as_of_time:
            raise ValueError("dataset cannot be created before its as-of time")
        order = tuple(
            (row.decision_time, str(row.event_id), str(row.asset), str(row.instrument_id))
            for row in self.rows
        )
        if order != tuple(sorted(order)) or len(order) != len(set(order)):
            raise ValueError("event response rows must be unique and time ordered")
        revision_bindings: dict[ArtifactId, tuple[object, ...]] = {}
        for row in self.rows:
            binding = (
                row.event_id,
                row.canonical_event_sha256,
                row.event_type,
                row.event_available_at,
            )
            previous = revision_bindings.setdefault(row.event_revision_id, binding)
            if previous != binding:
                raise ValueError("AQ-CAUSAL-EVENT-REVISION-BINDING-MISMATCH")
        if any(row.outcome_available_at > self.as_of_time for row in self.rows):
            raise ValueError("AQ-CAUSAL-DATASET-OUTCOME-LOOKAHEAD")
        expected_sources = tuple(
            sorted({source for row in self.rows for source in row.source_dataset_ids})
        )
        if self.source_dataset_ids != expected_sources:
            raise ValueError("dataset source lineage must equal row lineage")
        expected_features = tuple(sorted({row.feature_snapshot_sha256 for row in self.rows}))
        expected_labels = tuple(sorted({row.label_sha256 for row in self.rows}))
        expected_universes = tuple(sorted({row.universe_snapshot_sha256 for row in self.rows}))
        if self.feature_snapshot_hashes != expected_features:
            raise ValueError("feature snapshot lineage differs from rows")
        if self.label_hashes != expected_labels:
            raise ValueError("label lineage differs from rows")
        if self.universe_snapshot_hashes != expected_universes:
            raise ValueError("universe snapshot lineage differs from rows")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"dataset_sha256"}))
        if self.dataset_sha256 != expected_hash:
            raise ValueError("event response dataset hash mismatch")
        return self


def build_event_response_dataset(
    *,
    dataset_id: str,
    evidence_tier: EvidenceTier,
    as_of_time: UtcDateTime,
    created_at: UtcDateTime,
    rows: tuple[EventResponseRow, ...],
    feature_definition_hashes: tuple[str, ...],
    label_definition_hashes: tuple[str, ...],
    cost_policy_sha256: str,
) -> EventResponseDataset:
    source_dataset_ids = tuple(
        sorted({source for row in rows for source in row.source_dataset_ids})
    )
    feature_snapshot_hashes = tuple(sorted({row.feature_snapshot_sha256 for row in rows}))
    label_hashes = tuple(sorted({row.label_sha256 for row in rows}))
    universe_snapshot_hashes = tuple(sorted({row.universe_snapshot_sha256 for row in rows}))
    provisional = EventResponseDataset.model_construct(
        schema_version="1.0.0",
        dataset_id=dataset_id,
        dataset_sha256="",
        evidence_tier=evidence_tier,
        as_of_time=as_of_time,
        created_at=created_at,
        revision_aware=True,
        point_in_time=True,
        shuffle=False,
        rows=rows,
        source_dataset_ids=source_dataset_ids,
        feature_snapshot_hashes=feature_snapshot_hashes,
        label_hashes=label_hashes,
        universe_snapshot_hashes=universe_snapshot_hashes,
        feature_definition_hashes=feature_definition_hashes,
        label_definition_hashes=label_definition_hashes,
        cost_policy_sha256=cost_policy_sha256,
    )
    digest = canonical_sha256(provisional.model_dump(mode="json", exclude={"dataset_sha256"}))
    return EventResponseDataset(
        schema_version="1.0.0",
        dataset_id=dataset_id,
        dataset_sha256=digest,
        evidence_tier=evidence_tier,
        as_of_time=as_of_time,
        created_at=created_at,
        revision_aware=True,
        point_in_time=True,
        shuffle=False,
        rows=rows,
        source_dataset_ids=source_dataset_ids,
        feature_snapshot_hashes=feature_snapshot_hashes,
        label_hashes=label_hashes,
        universe_snapshot_hashes=universe_snapshot_hashes,
        feature_definition_hashes=feature_definition_hashes,
        label_definition_hashes=label_definition_hashes,
        cost_policy_sha256=cost_policy_sha256,
    )


class HistoricalState(DomainModel):
    """A market state whose features are known at decision time and outcome later."""

    state_id: str
    event_id: EventId | None = None
    asset: AssetId
    instrument_id: InstrumentId
    regime: str
    decision_time: UtcDateTime
    feature_available_at: UtcDateTime
    outcome_available_at: UtcDateTime
    covariate_names: tuple[str, ...]
    covariates: DecimalVector
    pre_treatment_outcomes: Annotated[tuple[FiniteDecimal, ...], Field(min_length=3)]
    outcome: FiniteDecimal
    source_sha256: str

    @field_validator("source_sha256")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="historical state source hash")

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if not self.state_id.strip() or not self.regime.strip():
            raise ValueError("historical state metadata cannot be blank")
        if self.feature_available_at > self.decision_time:
            raise ValueError("AQ-CAUSAL-STATE-FEATURE-LOOKAHEAD")
        if self.outcome_available_at <= self.decision_time:
            raise ValueError("historical state outcome must be observed after decision")
        if (
            not self.covariate_names
            or len(self.covariate_names) != len(self.covariates)
            or len(set(self.covariate_names)) != len(self.covariate_names)
        ):
            raise ValueError("historical state covariate schema is invalid")
        return self

    @property
    def state_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class MatchingSpec(DomainModel):
    spec_id: str
    matched_count: Annotated[int, Field(ge=2)] = 3
    caliper: PositiveDecimal = Decimal("3")
    require_same_asset: bool = True
    require_same_regime: bool = True
    historical_outcomes_known_at_treatment: bool = True

    @property
    def spec_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class MatchedControl(DomainModel):
    state_id: str
    state_sha256: str
    distance: NonNegativeDecimal
    weight: UnitInterval

    @field_validator("state_sha256")
    @classmethod
    def validate_state_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="matched state hash")


class MatchedStateSet(DomainModel):
    treated_state_sha256: str
    matching_spec_sha256: str
    candidate_count: Annotated[int, Field(gt=0)]
    matched_controls: Annotated[tuple[MatchedControl, ...], Field(min_length=2)]
    as_of_time: UtcDateTime

    @field_validator("treated_state_sha256", "matching_spec_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="matched-state-set hash")

    @model_validator(mode="after")
    def validate_matches(self) -> Self:
        if self.candidate_count < len(self.matched_controls):
            raise ValueError("matched controls exceed candidate count")
        order = tuple((item.distance, item.state_id) for item in self.matched_controls)
        if order != tuple(sorted(order)):
            raise ValueError("matched controls must be deterministically ordered")
        if len({item.state_id for item in self.matched_controls}) != len(self.matched_controls):
            raise ValueError("matched controls must be unique")
        if sum((item.weight for item in self.matched_controls), Decimal("0")) != Decimal("1"):
            raise ValueError("matched control weights must sum to one")
        return self

    @property
    def match_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class StateWeight(DomainModel):
    state_id: str
    state_sha256: str
    weight: UnitInterval

    @field_validator("state_sha256")
    @classmethod
    def validate_state_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="synthetic control state hash")


class CausalPointEstimate(DomainModel):
    method: CausalMethod
    estimand: CausalEstimand
    effect: FiniteDecimal
    standard_error: NonNegativeDecimal | None
    confidence_lower: FiniteDecimal | None
    confidence_upper: FiniteDecimal | None
    treated_count: Annotated[int, Field(gt=0)]
    control_count: Annotated[int, Field(gt=0)]
    estimator_spec_sha256: str

    @field_validator("estimator_spec_sha256")
    @classmethod
    def validate_spec_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="causal estimator spec hash")

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        interval = (self.confidence_lower, self.confidence_upper)
        if any(value is None for value in interval) and any(
            value is not None for value in interval
        ):
            raise ValueError("confidence interval bounds must be present together")
        if (
            self.confidence_lower is not None
            and self.confidence_upper is not None
            and not self.confidence_lower <= self.effect <= self.confidence_upper
        ):
            raise ValueError("causal effect must fall inside its confidence interval")
        return self


class EventStudySpec(DomainModel):
    spec_id: str

    @property
    def spec_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class SyntheticControlSpec(DomainModel):
    spec_id: str
    maximum_iterations: Annotated[int, Field(ge=100)] = 10_000
    convergence_tolerance: PositiveDecimal = Decimal("0.0000000001")
    ridge_penalty: NonNegativeDecimal = Decimal("0.00000001")

    @property
    def spec_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class DoublyRobustSpec(DomainModel):
    spec_id: str
    propensity_lower_bound: UnitInterval = Decimal("0.05")
    propensity_upper_bound: UnitInterval = Decimal("0.95")
    confidence_z: PositiveDecimal = Decimal("1.95996398454005")

    @model_validator(mode="after")
    def validate_overlap_bounds(self) -> Self:
        if not 0 < self.propensity_lower_bound < self.propensity_upper_bound < 1:
            raise ValueError("doubly robust propensity bounds must lie inside (0, 1)")
        return self

    @property
    def spec_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class PreTreatmentFitReport(DomainModel):
    treated_path: Annotated[tuple[FiniteDecimal, ...], Field(min_length=3)]
    counterfactual_path: Annotated[tuple[FiniteDecimal, ...], Field(min_length=3)]
    root_mean_squared_error: NonNegativeDecimal
    outcome_scale: PositiveDecimal
    normalized_root_mean_squared_error: NonNegativeDecimal
    maximum_normalized_error: NonNegativeDecimal
    passed: bool

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        rmse, scale, normalized = _path_fit_components(self.treated_path, self.counterfactual_path)
        if (
            self.root_mean_squared_error != rmse
            or self.outcome_scale != scale
            or self.normalized_root_mean_squared_error != normalized
        ):
            raise ValueError("pre-treatment fit metrics mismatch")
        if self.passed != (normalized <= self.maximum_normalized_error):
            raise ValueError("pre-treatment fit decision mismatch")
        return self

    @classmethod
    def from_paths(
        cls,
        *,
        treated_path: tuple[Decimal, ...],
        counterfactual_path: tuple[Decimal, ...],
        maximum_normalized_error: Decimal,
    ) -> PreTreatmentFitReport:
        rmse, scale, normalized = _path_fit_components(treated_path, counterfactual_path)
        return cls(
            treated_path=treated_path,
            counterfactual_path=counterfactual_path,
            root_mean_squared_error=rmse,
            outcome_scale=scale,
            normalized_root_mean_squared_error=normalized,
            maximum_normalized_error=maximum_normalized_error,
            passed=normalized <= maximum_normalized_error,
        )


class PreTrendReport(DomainModel):
    treated_path: Annotated[tuple[FiniteDecimal, ...], Field(min_length=3)]
    counterfactual_path: Annotated[tuple[FiniteDecimal, ...], Field(min_length=3)]
    treated_slope: FiniteDecimal
    counterfactual_slope: FiniteDecimal
    absolute_slope_gap: NonNegativeDecimal
    maximum_absolute_slope_gap: NonNegativeDecimal
    passed: bool

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if len(self.treated_path) != len(self.counterfactual_path):
            raise ValueError("pre-trend paths must have equal length")
        treated_slope = _path_slope(self.treated_path)
        counterfactual_slope = _path_slope(self.counterfactual_path)
        gap = abs(treated_slope - counterfactual_slope)
        if (
            self.treated_slope != treated_slope
            or self.counterfactual_slope != counterfactual_slope
            or self.absolute_slope_gap != gap
        ):
            raise ValueError("pre-trend metrics mismatch")
        if self.passed != (gap <= self.maximum_absolute_slope_gap):
            raise ValueError("pre-trend decision mismatch")
        return self

    @classmethod
    def from_paths(
        cls,
        *,
        treated_path: tuple[Decimal, ...],
        counterfactual_path: tuple[Decimal, ...],
        maximum_absolute_slope_gap: Decimal,
    ) -> PreTrendReport:
        if len(treated_path) != len(counterfactual_path):
            raise ValueError("pre-trend paths must have equal length")
        treated_slope = _path_slope(treated_path)
        counterfactual_slope = _path_slope(counterfactual_path)
        gap = abs(treated_slope - counterfactual_slope)
        return cls(
            treated_path=treated_path,
            counterfactual_path=counterfactual_path,
            treated_slope=treated_slope,
            counterfactual_slope=counterfactual_slope,
            absolute_slope_gap=gap,
            maximum_absolute_slope_gap=maximum_absolute_slope_gap,
            passed=gap <= maximum_absolute_slope_gap,
        )


class CovariateBalanceReport(DomainModel):
    covariate_names: tuple[str, ...]
    treated_covariates: tuple[DecimalVector, ...]
    candidate_covariates: tuple[DecimalVector, ...]
    matched_covariates: tuple[DecimalVector, ...]
    before_standardized_mean_difference: DecimalVector
    after_standardized_mean_difference: DecimalVector
    maximum_absolute_after: NonNegativeDecimal
    maximum_allowed: NonNegativeDecimal
    passed: bool

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        width = len(self.covariate_names)
        if (
            width == 0
            or len(set(self.covariate_names)) != width
            or len(self.before_standardized_mean_difference) != width
            or len(self.after_standardized_mean_difference) != width
        ):
            raise ValueError("covariate balance dimensions are invalid")
        before = _standardized_mean_differences(self.treated_covariates, self.candidate_covariates)
        after = _standardized_mean_differences(self.treated_covariates, self.matched_covariates)
        maximum = max(abs(value) for value in after)
        if (
            self.before_standardized_mean_difference != before
            or self.after_standardized_mean_difference != after
            or self.maximum_absolute_after != maximum
        ):
            raise ValueError("covariate balance metrics mismatch")
        if self.passed != (maximum <= self.maximum_allowed):
            raise ValueError("covariate balance decision mismatch")
        return self

    @classmethod
    def from_covariates(
        cls,
        *,
        covariate_names: tuple[str, ...],
        treated_covariates: tuple[tuple[Decimal, ...], ...],
        candidate_covariates: tuple[tuple[Decimal, ...], ...],
        matched_covariates: tuple[tuple[Decimal, ...], ...],
        maximum_allowed: Decimal,
    ) -> CovariateBalanceReport:
        before = _standardized_mean_differences(treated_covariates, candidate_covariates)
        after = _standardized_mean_differences(treated_covariates, matched_covariates)
        maximum = max(abs(value) for value in after)
        return cls(
            covariate_names=covariate_names,
            treated_covariates=treated_covariates,
            candidate_covariates=candidate_covariates,
            matched_covariates=matched_covariates,
            before_standardized_mean_difference=before,
            after_standardized_mean_difference=after,
            maximum_absolute_after=maximum,
            maximum_allowed=maximum_allowed,
            passed=maximum <= maximum_allowed,
        )


class PropensityOverlapReport(DomainModel):
    propensity_scores: DecimalVector
    treatments: Annotated[tuple[bool, ...], Field(min_length=4)]
    minimum_propensity: UnitInterval
    maximum_propensity: UnitInterval
    lower_bound: UnitInterval
    upper_bound: UnitInterval
    passed: bool

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if not 0 < self.lower_bound < self.upper_bound < 1:
            raise ValueError("overlap bounds must lie inside (0, 1)")
        if len(self.propensity_scores) != len(self.treatments):
            raise ValueError("propensity scores and treatments must align")
        treated_count = sum(self.treatments)
        if treated_count < 2 or len(self.treatments) - treated_count < 2:
            raise ValueError("overlap diagnostic requires two treated and two controls")
        minimum = min(self.propensity_scores)
        maximum = max(self.propensity_scores)
        if self.minimum_propensity != minimum or self.maximum_propensity != maximum:
            raise ValueError("propensity overlap extrema mismatch")
        expected = minimum >= self.lower_bound and maximum <= self.upper_bound
        if self.passed != expected:
            raise ValueError("propensity overlap decision mismatch")
        return self

    @classmethod
    def from_scores(
        cls,
        *,
        propensity_scores: tuple[Decimal, ...],
        treatments: tuple[bool, ...],
        lower_bound: Decimal,
        upper_bound: Decimal,
    ) -> PropensityOverlapReport:
        if not propensity_scores:
            raise ValueError("overlap diagnostic requires propensity scores")
        minimum = min(propensity_scores)
        maximum = max(propensity_scores)
        return cls(
            propensity_scores=propensity_scores,
            treatments=treatments,
            minimum_propensity=minimum,
            maximum_propensity=maximum,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            passed=minimum >= lower_bound and maximum <= upper_bound,
        )


class PlaceboTestResult(DomainModel):
    kind: PlaceboKind
    observed_effect: FiniteDecimal
    placebo_effects: DecimalVector
    empirical_p_value: UnitInterval
    maximum_p_value: UnitInterval
    minimum_draws: Annotated[int, Field(ge=9)]
    passed: bool

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        extreme = sum(abs(value) >= abs(self.observed_effect) for value in self.placebo_effects)
        expected = Decimal(extreme + 1) / Decimal(len(self.placebo_effects) + 1)
        if self.empirical_p_value != expected:
            raise ValueError("placebo empirical p-value mismatch")
        decision = (
            len(self.placebo_effects) >= self.minimum_draws and expected <= self.maximum_p_value
        )
        if self.passed != decision:
            raise ValueError("placebo decision mismatch")
        return self


class CausalDiagnosticPolicy(DomainModel):
    policy_id: str
    maximum_pre_treatment_nrmse: NonNegativeDecimal = Decimal("0.25")
    maximum_pretrend_slope_gap: NonNegativeDecimal = Decimal("0.05")
    maximum_absolute_smd: NonNegativeDecimal = Decimal("0.25")
    propensity_lower_bound: UnitInterval = Decimal("0.05")
    propensity_upper_bound: UnitInterval = Decimal("0.95")
    maximum_placebo_p_value: UnitInterval = Decimal("0.10")
    minimum_placebo_draws: Annotated[int, Field(ge=9)] = 19
    minimum_controls: Annotated[int, Field(ge=2)] = 3
    required_placebo_kinds: tuple[PlaceboKind, ...] = tuple(PlaceboKind)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if not 0 < self.propensity_lower_bound < self.propensity_upper_bound < 1:
            raise ValueError("causal diagnostic overlap bounds must lie inside (0, 1)")
        if self.required_placebo_kinds != tuple(PlaceboKind) or len(
            set(self.required_placebo_kinds)
        ) != len(self.required_placebo_kinds):
            raise ValueError("P06 requires timestamp, asset, and treatment permutation placebos")
        return self

    @property
    def policy_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


DEFAULT_CAUSAL_DIAGNOSTIC_POLICY = CausalDiagnosticPolicy(policy_id="v5-p06-development-v1")


class CausalDiagnostics(DomainModel):
    policy: CausalDiagnosticPolicy
    pre_treatment_fit: PreTreatmentFitReport
    pretrend: PreTrendReport
    covariate_balance: CovariateBalanceReport
    propensity_overlap: PropensityOverlapReport
    placebo_tests: tuple[PlaceboTestResult, ...]
    control_count: Annotated[int, Field(gt=0)]
    minimum_controls: Annotated[int, Field(ge=2)]
    required_placebo_kinds: tuple[PlaceboKind, ...]
    unresolved_assumptions: tuple[str, ...]
    passed: bool
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.policy != DEFAULT_CAUSAL_DIAGNOSTIC_POLICY:
            raise ValueError("AQ-CAUSAL-DIAGNOSTIC-POLICY-NOT-APPROVED")
        if self.unresolved_assumptions != tuple(sorted(set(self.unresolved_assumptions))):
            raise ValueError("unresolved assumptions must be unique and sorted")
        kinds = tuple(item.kind for item in self.placebo_tests)
        if len(set(kinds)) != len(kinds):
            raise ValueError("placebo kinds must be unique")
        if self.required_placebo_kinds != tuple(PlaceboKind):
            raise ValueError("causal diagnostics must bind all P06 placebo kinds")
        if (
            self.minimum_controls != self.policy.minimum_controls
            or self.required_placebo_kinds != self.policy.required_placebo_kinds
            or self.pre_treatment_fit.maximum_normalized_error
            != self.policy.maximum_pre_treatment_nrmse
            or self.pretrend.maximum_absolute_slope_gap != self.policy.maximum_pretrend_slope_gap
            or self.covariate_balance.maximum_allowed != self.policy.maximum_absolute_smd
            or self.propensity_overlap.lower_bound != self.policy.propensity_lower_bound
            or self.propensity_overlap.upper_bound != self.policy.propensity_upper_bound
            or any(
                item.maximum_p_value != self.policy.maximum_placebo_p_value
                or item.minimum_draws != self.policy.minimum_placebo_draws
                for item in self.placebo_tests
            )
        ):
            raise ValueError("causal diagnostics thresholds differ from approved policy")
        expected_reasons: list[str] = []
        if not self.pre_treatment_fit.passed:
            expected_reasons.append("PRE_TREATMENT_FIT_FAILED")
        if not self.pretrend.passed:
            expected_reasons.append("PRE_TREND_FAILED")
        if not self.covariate_balance.passed:
            expected_reasons.append("COVARIATE_BALANCE_FAILED")
        if not self.propensity_overlap.passed:
            expected_reasons.append("PROPENSITY_OVERLAP_FAILED")
        if self.control_count < self.minimum_controls:
            expected_reasons.append("INSUFFICIENT_CONTROLS")
        if set(kinds) != set(self.required_placebo_kinds):
            expected_reasons.append("PLACEBO_COVERAGE_INCOMPLETE")
        if any(not item.passed for item in self.placebo_tests):
            expected_reasons.append("PLACEBO_FAILED")
        if self.unresolved_assumptions:
            expected_reasons.append("UNRESOLVED_IDENTIFICATION_ASSUMPTIONS")
        expected_passed = not expected_reasons
        if self.passed != expected_passed or self.reason_codes != tuple(expected_reasons):
            raise ValueError("causal diagnostics decision is not reproducible")
        return self

    @property
    def diagnostics_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class DoublyRobustObservation(DomainModel):
    sample_id: str
    decision_time: UtcDateTime
    nuisance_available_at: UtcDateTime
    nuisance_training_cutoff: UtcDateTime
    outcome_available_at: UtcDateTime
    treated: bool
    outcome: FiniteDecimal
    propensity_score: UnitInterval
    predicted_outcome_if_control: FiniteDecimal
    predicted_outcome_if_treated: FiniteDecimal
    nuisance_model_sha256: str
    feature_snapshot_sha256: str

    @field_validator("nuisance_model_sha256", "feature_snapshot_sha256")
    @classmethod
    def validate_model_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="nuisance model hash")

    @model_validator(mode="after")
    def validate_pit(self) -> Self:
        if not self.sample_id.strip():
            raise ValueError("doubly robust sample id cannot be blank")
        if self.nuisance_available_at > self.decision_time:
            raise ValueError("AQ-CAUSAL-NUISANCE-LOOKAHEAD")
        if self.nuisance_training_cutoff > self.decision_time:
            raise ValueError("AQ-CAUSAL-NUISANCE-TRAINING-LOOKAHEAD")
        if self.outcome_available_at <= self.decision_time:
            raise ValueError("doubly robust outcome must be observed after decision")
        if not 0 < self.propensity_score < 1:
            raise ValueError("propensity score must lie inside (0, 1)")
        return self


class SyntheticControlResult(DomainModel):
    point_estimate: CausalPointEstimate
    donor_weights: Annotated[tuple[StateWeight, ...], Field(min_length=2)]
    counterfactual_outcome: FiniteDecimal
    pre_treatment_fit: PreTreatmentFitReport
    converged: Literal[True]
    iterations: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def validate_weights_and_effect(self) -> Self:
        if sum((item.weight for item in self.donor_weights), Decimal("0")) != Decimal("1"):
            raise ValueError("synthetic control weights must sum to one")
        if len({item.state_id for item in self.donor_weights}) != len(self.donor_weights):
            raise ValueError("synthetic control donors must be unique")
        return self


class CausalEffectEstimate(DomainModel):
    estimate_id: ArtifactId
    estimate_sha256: str
    event_id: EventId
    asset: AssetId
    instrument_id: InstrumentId
    horizon_seconds: Annotated[int, Field(gt=0)]
    point_estimate: CausalPointEstimate
    input_dataset_sha256: str
    diagnostics: CausalDiagnostics
    evidence_tier: EvidenceTier
    identification_status: IdentificationStatus
    causal_claim_allowed: bool
    alpha_promotion_eligible: Literal[False] = False
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    reason_codes: tuple[str, ...]
    available_at: UtcDateTime

    @field_validator("estimate_sha256", "input_dataset_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="causal estimate hash")

    @model_validator(mode="after")
    def validate_gate(self) -> Self:
        tier_ready = tier_can_support_alpha_promotion(self.evidence_tier)
        expected_allowed = self.diagnostics.passed and tier_ready
        if not self.diagnostics.passed:
            expected_status = IdentificationStatus.INSUFFICIENT_IDENTIFICATION
            expected_reasons = ("CAUSAL_DIAGNOSTICS_FAILED",)
        elif not tier_ready:
            expected_status = IdentificationStatus.DEVELOPMENT_ONLY
            expected_reasons = ("EVIDENCE_TIER_NOT_CAUSAL",)
        else:
            expected_status = IdentificationStatus.IDENTIFIED
            expected_reasons = ("CAUSAL_DIAGNOSTICS_PASSED",)
        if (
            self.causal_claim_allowed != expected_allowed
            or self.identification_status is not expected_status
            or self.reason_codes != expected_reasons
        ):
            raise ValueError("causal claim gate is not reproducible")
        expected_hash = canonical_sha256(
            self.model_dump(mode="json", exclude={"estimate_id", "estimate_sha256"})
        )
        if str(self.estimate_id) != expected_hash or self.estimate_sha256 != expected_hash:
            raise ValueError("causal estimate id/hash mismatch")
        return self


def build_causal_effect_estimate(
    *,
    event_id: EventId,
    asset: AssetId,
    instrument_id: InstrumentId,
    horizon_seconds: int,
    point_estimate: CausalPointEstimate,
    input_dataset_sha256: str,
    diagnostics: CausalDiagnostics,
    evidence_tier: EvidenceTier,
    available_at: UtcDateTime,
) -> CausalEffectEstimate:
    tier_ready = tier_can_support_alpha_promotion(evidence_tier)
    allowed = diagnostics.passed and tier_ready
    if not diagnostics.passed:
        status = IdentificationStatus.INSUFFICIENT_IDENTIFICATION
        reasons = ("CAUSAL_DIAGNOSTICS_FAILED",)
    elif not tier_ready:
        status = IdentificationStatus.DEVELOPMENT_ONLY
        reasons = ("EVIDENCE_TIER_NOT_CAUSAL",)
    else:
        status = IdentificationStatus.IDENTIFIED
        reasons = ("CAUSAL_DIAGNOSTICS_PASSED",)
    provisional = CausalEffectEstimate.model_construct(
        estimate_id=ArtifactId("provisional"),
        estimate_sha256="",
        event_id=event_id,
        asset=asset,
        instrument_id=instrument_id,
        horizon_seconds=horizon_seconds,
        point_estimate=point_estimate,
        input_dataset_sha256=input_dataset_sha256,
        diagnostics=diagnostics,
        evidence_tier=evidence_tier,
        identification_status=status,
        causal_claim_allowed=allowed,
        alpha_promotion_eligible=False,
        order_submission_enabled=False,
        live_trading_locked=True,
        reason_codes=reasons,
        available_at=available_at,
    )
    digest = canonical_sha256(
        provisional.model_dump(mode="json", exclude={"estimate_id", "estimate_sha256"})
    )
    return CausalEffectEstimate(
        estimate_id=ArtifactId(digest),
        estimate_sha256=digest,
        event_id=event_id,
        asset=asset,
        instrument_id=instrument_id,
        horizon_seconds=horizon_seconds,
        point_estimate=point_estimate,
        input_dataset_sha256=input_dataset_sha256,
        diagnostics=diagnostics,
        evidence_tier=evidence_tier,
        identification_status=status,
        causal_claim_allowed=allowed,
        alpha_promotion_eligible=False,
        order_submission_enabled=False,
        live_trading_locked=True,
        reason_codes=reasons,
        available_at=available_at,
    )
