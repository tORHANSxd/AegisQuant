# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Deterministic classical baseline models and fair modality comparisons."""

from __future__ import annotations

import math
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

import numpy as np
from pydantic import Field, model_validator
from sklearn.base import RegressorMixin
from sklearn.linear_model import ElasticNet, LinearRegression, LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    UnitInterval,
    canonical_result,
)


class BaselineModelKind(StrEnum):
    LINEAR = "LINEAR"
    LOGISTIC = "LOGISTIC"
    ELASTIC_NET = "ELASTIC_NET"
    HAR_RV = "HAR_RV"
    SIMPLE_STATE = "SIMPLE_STATE"


class ResearchModality(StrEnum):
    MARKET_ONLY = "MARKET_ONLY"
    EVENT_ONLY = "EVENT_ONLY"
    FUSED = "FUSED"


class BaselineDataset(DomainModel):
    sample_ids: tuple[str, ...]
    timestamps: tuple[UtcDateTime, ...]
    feature_names: tuple[str, ...]
    features: tuple[tuple[float, ...], ...]
    targets: tuple[float, ...]

    @model_validator(mode="after")
    def validate_dataset(self) -> BaselineDataset:
        rows = len(self.sample_ids)
        if (
            rows < 4
            or len(self.timestamps) != rows
            or len(self.features) != rows
            or len(self.targets) != rows
        ):
            raise ValueError("baseline dataset dimensions are inconsistent or too small")
        if tuple(sorted(self.timestamps)) != self.timestamps:
            raise ValueError("baseline dataset must remain time ordered")
        if not self.feature_names or any(
            len(row) != len(self.feature_names) for row in self.features
        ):
            raise ValueError("baseline feature matrix is not rectangular")
        if len(set(self.sample_ids)) != rows:
            raise ValueError("baseline sample ids must be unique")
        if any(not math.isfinite(value) for row in self.features for value in row):
            raise ValueError("baseline features must be finite")
        if any(not math.isfinite(value) for value in self.targets):
            raise ValueError("baseline targets must be finite")
        return self

    def select_columns(self, indices: tuple[int, ...]) -> BaselineDataset:
        if not indices or len(set(indices)) != len(indices):
            raise ValueError("modality columns must be non-empty and unique")
        if any(index < 0 or index >= len(self.feature_names) for index in indices):
            raise IndexError("modality feature index is out of range")
        return BaselineDataset(
            sample_ids=self.sample_ids,
            timestamps=self.timestamps,
            feature_names=tuple(self.feature_names[index] for index in indices),
            features=tuple(tuple(row[index] for index in indices) for row in self.features),
            targets=self.targets,
        )


class BaselineModelSpec(DomainModel):
    model_id: str
    kind: BaselineModelKind
    seed: Annotated[int, Field(ge=0)] = 0
    max_iterations: Annotated[int, Field(ge=100)] = 10_000
    alpha: NonNegativeDecimal = Decimal("0.001")
    l1_ratio: UnitInterval = Decimal("0.5")

    @property
    def spec_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class BaselinePrediction(DomainModel):
    model_id: str
    model_kind: BaselineModelKind
    model_spec_sha256: str
    sample_ids: tuple[str, ...]
    predictions: tuple[FiniteDecimal, ...]
    positive_probabilities: tuple[UnitInterval, ...] | None = None

    @model_validator(mode="after")
    def validate_dimensions(self) -> BaselinePrediction:
        if len(self.sample_ids) != len(self.predictions):
            raise ValueError("prediction dimensions differ")
        if self.positive_probabilities is not None and len(self.positive_probabilities) != len(
            self.predictions
        ):
            raise ValueError("probability dimensions differ")
        return self


def _as_decimal(values: np.ndarray) -> tuple[Decimal, ...]:
    return tuple(Decimal(format(float(value), ".15g")) for value in values)


def _regression_pipeline(model: RegressorMixin) -> Pipeline:
    return Pipeline((("scale", StandardScaler()), ("model", model)))


def fit_predict_baseline(
    *,
    spec: BaselineModelSpec,
    train: BaselineDataset,
    test: BaselineDataset,
) -> BaselinePrediction:
    if train.feature_names != test.feature_names:
        raise ValueError("train/test feature schemas differ")
    if train.timestamps[-1] >= test.timestamps[0]:
        raise ValueError("baseline training must precede test data")
    train_x = np.asarray(train.features, dtype=np.float64)
    test_x = np.asarray(test.features, dtype=np.float64)
    train_y = np.asarray(train.targets, dtype=np.float64)
    probabilities: tuple[Decimal, ...] | None = None

    if spec.kind is BaselineModelKind.LINEAR:
        estimator = _regression_pipeline(LinearRegression())
        estimator.fit(train_x, train_y)
        raw_predictions = estimator.predict(test_x)
    elif spec.kind is BaselineModelKind.ELASTIC_NET:
        estimator = _regression_pipeline(
            ElasticNet(
                alpha=float(spec.alpha),
                l1_ratio=float(spec.l1_ratio),
                max_iter=spec.max_iterations,
                random_state=spec.seed,
                selection="cyclic",
            )
        )
        estimator.fit(train_x, train_y)
        raw_predictions = estimator.predict(test_x)
    elif spec.kind is BaselineModelKind.LOGISTIC:
        unique_targets = set(train.targets)
        if len(unique_targets) < 2 or not unique_targets.issubset({-1.0, 0.0, 1.0}):
            raise ValueError("logistic baseline requires at least two -1/0/1 classes")
        classifier = Pipeline(
            (
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        random_state=spec.seed,
                        max_iter=spec.max_iterations,
                        solver="lbfgs",
                    ),
                ),
            )
        )
        classifier.fit(train_x, train_y)
        raw_predictions = classifier.predict(test_x)
        model = classifier.named_steps["model"]
        if not isinstance(model, LogisticRegression):
            raise TypeError("logistic pipeline contract changed")
        probability_matrix = classifier.predict_proba(test_x)
        classes = tuple(float(value) for value in model.classes_)
        if 1.0 in classes:
            probabilities = _as_decimal(probability_matrix[:, classes.index(1.0)])
        else:
            probabilities = tuple(Decimal("0") for _ in range(len(test.sample_ids)))
    elif spec.kind is BaselineModelKind.HAR_RV:
        required = ("rv_daily", "rv_weekly", "rv_monthly")
        if train.feature_names != required:
            raise ValueError("HAR-RV requires daily, weekly, and monthly realized volatility")
        estimator = LinearRegression()
        estimator.fit(train_x, train_y)
        raw_predictions = np.maximum(estimator.predict(test_x), 0.0)
    else:
        state_feature = train_x[:, 0]
        lower, upper = np.quantile(state_feature, (1.0 / 3.0, 2.0 / 3.0))

        def state(value: float) -> int:
            return 0 if value <= lower else 2 if value >= upper else 1

        state_means: dict[int, float] = {}
        overall = float(np.mean(train_y))
        state_feature_values = tuple(float(value) for value in state_feature)
        for state_id in (0, 1, 2):
            members = tuple(
                target
                for target, feature in zip(train.targets, state_feature_values, strict=True)
                if state(feature) == state_id
            )
            state_means[state_id] = sum(members) / len(members) if members else overall
        raw_predictions = np.asarray(
            [state_means[state(value)] for value in test_x[:, 0]], dtype=np.float64
        )
    if np.any(~np.isfinite(raw_predictions)):
        raise ValueError("baseline model produced non-finite predictions")
    return BaselinePrediction(
        model_id=spec.model_id,
        model_kind=spec.kind,
        model_spec_sha256=spec.spec_sha256,
        sample_ids=test.sample_ids,
        predictions=_as_decimal(np.asarray(raw_predictions)),
        positive_probabilities=probabilities,
    )


class ModelEvaluation(DomainModel):
    model_id: str
    modality: ResearchModality
    observations: int = Field(gt=0)
    mean_squared_error: NonNegativeDecimal
    direction_accuracy: UnitInterval
    brier_score: NonNegativeDecimal | None
    gross_return: FiniteDecimal
    transaction_cost: NonNegativeDecimal
    net_return: FiniteDecimal
    turnover: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_economics(self) -> ModelEvaluation:
        if self.net_return != canonical_result(self.gross_return - self.transaction_cost):
            raise ValueError("model evaluation net return must conserve")
        return self


def evaluate_predictions(
    *,
    predictions: BaselinePrediction,
    modality: ResearchModality,
    realized_returns: tuple[Decimal, ...],
    cost_rates: tuple[Decimal, ...],
    edge_threshold: Decimal = Decimal("0"),
) -> ModelEvaluation:
    if len(predictions.predictions) != len(realized_returns) or len(cost_rates) != len(
        realized_returns
    ):
        raise ValueError("evaluation dimensions differ")
    if any(value < 0 for value in cost_rates):
        raise ValueError("evaluation costs cannot be negative")
    positions = tuple(
        Decimal("1")
        if value > edge_threshold
        else Decimal("-1")
        if value < -edge_threshold
        else Decimal("0")
        for value in predictions.predictions
    )
    gross = sum(
        (
            position * realized
            for position, realized in zip(positions, realized_returns, strict=True)
        ),
        Decimal("0"),
    )
    previous = Decimal("0")
    turnover = Decimal("0")
    transaction_cost = Decimal("0")
    for position, cost in zip(positions, cost_rates, strict=True):
        change = abs(position - previous)
        turnover += change
        transaction_cost += change * cost
        previous = position
    errors = tuple(
        prediction - realized
        for prediction, realized in zip(predictions.predictions, realized_returns, strict=True)
    )
    mse = sum((error * error for error in errors), Decimal("0")) / Decimal(len(errors))
    correct = sum(
        (prediction > 0) == (realized > 0)
        for prediction, realized in zip(predictions.predictions, realized_returns, strict=True)
        if realized != 0
    )
    nonzero = sum(value != 0 for value in realized_returns)
    accuracy = Decimal(correct) / Decimal(nonzero) if nonzero else Decimal("0")
    brier: Decimal | None = None
    if predictions.positive_probabilities is not None:
        brier = sum(
            (probability - (Decimal("1") if realized > 0 else Decimal("0"))) ** 2
            for probability, realized in zip(
                predictions.positive_probabilities, realized_returns, strict=True
            )
        ) / Decimal(len(realized_returns))
    return ModelEvaluation(
        model_id=predictions.model_id,
        modality=modality,
        observations=len(realized_returns),
        mean_squared_error=canonical_result(mse),
        direction_accuracy=canonical_result(accuracy),
        brier_score=canonical_result(brier) if brier is not None else None,
        gross_return=canonical_result(gross),
        transaction_cost=canonical_result(transaction_cost),
        net_return=canonical_result(gross - transaction_cost),
        turnover=canonical_result(turnover),
    )


class FairBaselineResult(DomainModel):
    budget_sha256: str
    evaluations: tuple[ModelEvaluation, ...]

    @model_validator(mode="after")
    def validate_modalities(self) -> FairBaselineResult:
        modalities = {item.modality for item in self.evaluations}
        if modalities != set(ResearchModality):
            raise ValueError("fair comparison requires Market-only, Event-only, and Fused")
        return self


def compare_modalities(
    *,
    spec: BaselineModelSpec,
    train: BaselineDataset,
    test: BaselineDataset,
    market_columns: tuple[int, ...],
    event_columns: tuple[int, ...],
    realized_returns: tuple[Decimal, ...],
    cost_rates: tuple[Decimal, ...],
) -> FairBaselineResult:
    if set(market_columns) & set(event_columns):
        raise ValueError("market and event feature columns must be disjoint")
    columns = {
        ResearchModality.MARKET_ONLY: market_columns,
        ResearchModality.EVENT_ONLY: event_columns,
        ResearchModality.FUSED: tuple(sorted((*market_columns, *event_columns))),
    }
    evaluations: list[ModelEvaluation] = []
    for modality in ResearchModality:
        prediction = fit_predict_baseline(
            spec=spec,
            train=train.select_columns(columns[modality]),
            test=test.select_columns(columns[modality]),
        )
        evaluations.append(
            evaluate_predictions(
                predictions=prediction,
                modality=modality,
                realized_returns=realized_returns,
                cost_rates=cost_rates,
            )
        )
    budget = {
        "train_rows": len(train.sample_ids),
        "test_rows": len(test.sample_ids),
        "seed": spec.seed,
        "max_iterations": spec.max_iterations,
        "model_kind": spec.kind.value,
        "trials_per_modality": 1,
        "cost_rates": [str(item) for item in cost_rates],
    }
    return FairBaselineResult(
        budget_sha256=canonical_sha256(budget), evaluations=tuple(evaluations)
    )
