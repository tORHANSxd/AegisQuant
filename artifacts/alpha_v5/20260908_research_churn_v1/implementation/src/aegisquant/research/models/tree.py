# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Deterministic LightGBM, CatBoost, and XGBoost adapters."""

from __future__ import annotations

from enum import StrEnum

import numpy as np
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from pydantic import Field
from xgboost import XGBRegressor

from aegisquant.domain.base import DomainModel
from aegisquant.research.models.baselines import BaselineDataset
from aegisquant.research.models.probabilistic import (
    ProbabilisticPrediction,
    from_point_predictions,
)


class TreeModelKind(StrEnum):
    LIGHTGBM = "LIGHTGBM"
    CATBOOST = "CATBOOST"
    XGBOOST = "XGBOOST"


class TreeModelSpec(DomainModel):
    model_id: str
    kind: TreeModelKind
    seed: int = Field(default=0, ge=0)
    estimators: int = Field(default=32, ge=1, le=500)
    max_depth: int = Field(default=4, ge=1, le=12)
    learning_rate: float = Field(default=0.05, gt=0, le=1)


def _validate_split(train: BaselineDataset, test: BaselineDataset) -> None:
    if train.feature_names != test.feature_names:
        raise ValueError("tree train/test feature schemas differ")
    if train.timestamps[-1] >= test.timestamps[0]:
        raise ValueError("tree model training must precede test data")


def fit_predict_tree(
    *, spec: TreeModelSpec, train: BaselineDataset, test: BaselineDataset
) -> ProbabilisticPrediction:
    _validate_split(train, test)
    train_x = np.asarray(train.features, dtype=np.float64)
    train_y = np.asarray(train.targets, dtype=np.float64)
    test_x = np.asarray(test.features, dtype=np.float64)
    if spec.kind is TreeModelKind.LIGHTGBM:
        estimator = LGBMRegressor(
            n_estimators=spec.estimators,
            max_depth=spec.max_depth,
            num_leaves=min(2**spec.max_depth, 31),
            learning_rate=spec.learning_rate,
            random_state=spec.seed,
            n_jobs=1,
            deterministic=True,
            force_col_wise=True,
            verbosity=-1,
        )
    elif spec.kind is TreeModelKind.CATBOOST:
        estimator = CatBoostRegressor(
            iterations=spec.estimators,
            depth=spec.max_depth,
            learning_rate=spec.learning_rate,
            random_seed=spec.seed,
            thread_count=1,
            verbose=False,
            allow_writing_files=False,
            loss_function="RMSE",
        )
    else:
        estimator = XGBRegressor(
            n_estimators=spec.estimators,
            max_depth=spec.max_depth,
            learning_rate=spec.learning_rate,
            random_state=spec.seed,
            n_jobs=1,
            objective="reg:squarederror",
            tree_method="hist",
        )
    estimator.fit(train_x, train_y)
    fitted = np.asarray(estimator.predict(train_x), dtype=np.float64)
    predicted = np.asarray(estimator.predict(test_x), dtype=np.float64)
    if np.any(~np.isfinite(fitted)) or np.any(~np.isfinite(predicted)):
        raise ValueError("tree model produced non-finite values")
    residual_std = float(np.std(train_y - fitted, ddof=1)) if len(train_y) > 1 else 0.0
    return from_point_predictions(
        model_id=spec.model_id,
        model_family=spec.kind.value,
        sample_ids=test.sample_ids,
        point=tuple(float(value) for value in predicted),
        residual_std=residual_std,
    )
