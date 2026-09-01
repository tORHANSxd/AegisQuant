"""Classical baseline models for P07 research."""

from aegisquant.research.models.baselines import (
    BaselineDataset,
    BaselineModelKind,
    BaselineModelSpec,
    BaselinePrediction,
    FairBaselineResult,
    ModelEvaluation,
    ResearchModality,
    compare_modalities,
    evaluate_predictions,
    fit_predict_baseline,
)

__all__ = [
    "BaselineDataset",
    "BaselineModelKind",
    "BaselineModelSpec",
    "BaselinePrediction",
    "FairBaselineResult",
    "ModelEvaluation",
    "ResearchModality",
    "compare_modalities",
    "evaluate_predictions",
    "fit_predict_baseline",
]
