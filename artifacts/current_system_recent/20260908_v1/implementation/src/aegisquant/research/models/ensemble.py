"""Leakage-safe OOF assembly, capped stacking, smoothing, and PIT regime gating."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime, assert_point_in_time
from aegisquant.domain.values import FiniteDecimal, UnitInterval


class OofFoldPrediction(DomainModel):
    fold_id: str
    train_sample_ids: tuple[str, ...] = Field(min_length=1)
    validation_sample_ids: tuple[str, ...] = Field(min_length=1)
    predictions: dict[str, tuple[FiniteDecimal, ...]]

    @model_validator(mode="after")
    def validate_oof_fold(self) -> OofFoldPrediction:
        if set(self.train_sample_ids) & set(self.validation_sample_ids):
            raise ValueError("OOF train and validation samples overlap")
        if not self.predictions or any(
            len(values) != len(self.validation_sample_ids) for values in self.predictions.values()
        ):
            raise ValueError("OOF prediction dimensions differ")
        return self


class OofMatrix(DomainModel):
    sample_ids: tuple[str, ...]
    predictions: dict[str, tuple[FiniteDecimal, ...]]


def assemble_oof(
    folds: tuple[OofFoldPrediction, ...], *, expected_sample_ids: tuple[str, ...]
) -> OofMatrix:
    if not folds or len(set(expected_sample_ids)) != len(expected_sample_ids):
        raise ValueError("OOF expected sample ids must be unique and non-empty")
    model_ids = set(folds[0].predictions)
    if any(set(fold.predictions) != model_ids for fold in folds):
        raise ValueError("OOF folds must contain identical model ids")
    by_sample: dict[str, dict[str, Decimal]] = {}
    for fold in folds:
        for offset, sample_id in enumerate(fold.validation_sample_ids):
            if sample_id in by_sample:
                raise ValueError("OOF sample was predicted by multiple folds")
            by_sample[sample_id] = {
                model_id: values[offset] for model_id, values in fold.predictions.items()
            }
    if set(by_sample) != set(expected_sample_ids):
        raise ValueError("OOF predictions do not cover the expected samples exactly")
    return OofMatrix(
        sample_ids=expected_sample_ids,
        predictions={
            model_id: tuple(by_sample[sample_id][model_id] for sample_id in expected_sample_ids)
            for model_id in sorted(model_ids)
        },
    )


class StackingWeights(DomainModel):
    weights: dict[str, UnitInterval]
    maximum_weight: UnitInterval

    @model_validator(mode="after")
    def validate_weights(self) -> StackingWeights:
        if not self.weights or sum(self.weights.values(), Decimal("0")) != Decimal("1"):
            raise ValueError("stacking weights must sum exactly to one")
        if any(value > self.maximum_weight for value in self.weights.values()):
            raise ValueError("stacking weight cap exceeded")
        return self


def _capped_normalize(raw: dict[str, Decimal], cap: Decimal) -> dict[str, Decimal]:
    if not raw or cap * len(raw) < Decimal("1"):
        raise ValueError("stacking cap cannot support a unit simplex")
    remaining = set(raw)
    output: dict[str, Decimal] = {}
    mass = Decimal("1")
    while remaining:
        total = sum((raw[key] for key in remaining), Decimal("0"))
        proposed = {
            key: mass * raw[key] / total if total else mass / len(remaining) for key in remaining
        }
        capped = {key for key, value in proposed.items() if value > cap}
        if not capped:
            output.update(proposed)
            break
        for key in capped:
            output[key] = cap
            remaining.remove(key)
            mass -= cap
    correction_key = min(output)
    output[correction_key] += Decimal("1") - sum(output.values(), Decimal("0"))
    return output


def fit_oof_stacker(
    *, matrix: OofMatrix, targets: tuple[Decimal, ...], maximum_weight: Decimal
) -> StackingWeights:
    if len(targets) != len(matrix.sample_ids):
        raise ValueError("OOF target dimensions differ")
    inverse_errors: dict[str, Decimal] = {}
    epsilon = Decimal("1e-18")
    for model_id, values in matrix.predictions.items():
        mse = sum(
            (
                (prediction - target) ** 2
                for prediction, target in zip(values, targets, strict=True)
            ),
            Decimal("0"),
        ) / Decimal(len(targets))
        inverse_errors[model_id] = Decimal("1") / max(mse, epsilon)
    return StackingWeights(
        weights=_capped_normalize(inverse_errors, maximum_weight),
        maximum_weight=maximum_weight,
    )


def smooth_weights(
    *, previous: StackingWeights, proposed: StackingWeights, maximum_step: Decimal
) -> StackingWeights:
    if set(previous.weights) != set(proposed.weights):
        raise ValueError("stacking smoothing model sets differ")
    if not Decimal("0") <= maximum_step <= Decimal("1"):
        raise ValueError("stacking smoothing step must be between zero and one")
    largest_change = max(
        abs(proposed.weights[key] - previous.weights[key]) for key in previous.weights
    )
    blend = min(Decimal("1"), maximum_step / largest_change) if largest_change else Decimal("1")
    weights = {
        key: previous.weights[key] + blend * (proposed.weights[key] - previous.weights[key])
        for key in previous.weights
    }
    correction_key = min(weights)
    weights[correction_key] += Decimal("1") - sum(weights.values(), Decimal("0"))
    return StackingWeights(
        weights=weights,
        maximum_weight=min(previous.maximum_weight, proposed.maximum_weight),
    )


class RegimeObservation(DomainModel):
    regime_id: str
    observed_at_utc: UtcDateTime
    available_at_utc: UtcDateTime

    @model_validator(mode="after")
    def validate_availability(self) -> RegimeObservation:
        if self.observed_at_utc > self.available_at_utc:
            raise ValueError("regime cannot be available before observation")
        return self


def select_regime_weights(
    *,
    observation: RegimeObservation,
    decision_time: UtcDateTime,
    weights_by_regime: dict[str, StackingWeights],
) -> StackingWeights:
    assert_point_in_time(available_time=observation.available_at_utc, decision_time=decision_time)
    try:
        return weights_by_regime[observation.regime_id]
    except KeyError as error:
        raise KeyError("AQ-ENSEMBLE-UNKNOWN-REGIME") from error


def stack_predictions(
    *, predictions: dict[str, tuple[Decimal, ...]], weights: StackingWeights
) -> tuple[Decimal, ...]:
    if set(predictions) != set(weights.weights):
        raise ValueError("stacking prediction and weight model sets differ")
    lengths = {len(values) for values in predictions.values()}
    if len(lengths) != 1:
        raise ValueError("stacking prediction dimensions differ")
    length = lengths.pop()
    return tuple(
        sum(
            (weights.weights[key] * predictions[key][offset] for key in sorted(predictions)),
            Decimal("0"),
        )
        for offset in range(length)
    )
