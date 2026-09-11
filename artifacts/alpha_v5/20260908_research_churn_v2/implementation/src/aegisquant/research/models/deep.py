# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Two bounded CPU-friendly deep time-series candidates."""

from __future__ import annotations

from enum import StrEnum

import numpy as np
import torch
from pydantic import Field, model_validator
from torch import nn

from aegisquant.domain.base import DomainModel
from aegisquant.research.models.baselines import BaselineDataset
from aegisquant.research.models.probabilistic import (
    ProbabilisticPrediction,
    from_point_predictions,
)


class DeepModelKind(StrEnum):
    TCN = "TCN"
    PATCH_TRANSFORMER = "PATCH_TRANSFORMER"


class DeepModelSpec(DomainModel):
    model_id: str
    kind: DeepModelKind
    seed: int = Field(default=0, ge=0)
    context_length: int = Field(default=8, ge=2, le=128)
    hidden_size: int = Field(default=16, ge=4, le=128)
    epochs: int = Field(default=8, ge=1, le=100)
    learning_rate: float = Field(default=0.01, gt=0, le=1)
    attention_heads: int = Field(default=2, ge=1, le=8)

    @model_validator(mode="after")
    def validate_attention_width(self) -> DeepModelSpec:
        if self.kind is DeepModelKind.PATCH_TRANSFORMER and self.hidden_size % self.attention_heads:
            raise ValueError("transformer hidden size must divide by attention heads")
        return self


class _TcnRegressor(nn.Module):
    def __init__(self, features: int, hidden: int) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Conv1d(features, hidden, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv1d(hidden, hidden, kernel_size=3, padding=1),
            nn.ReLU(),
        )
        self.output = nn.Linear(hidden, 1)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        encoded = self.network(values.transpose(1, 2)).mean(dim=2)
        return self.output(encoded).squeeze(1)


class _PatchTransformerRegressor(nn.Module):
    def __init__(self, features: int, hidden: int, heads: int, context_length: int) -> None:
        super().__init__()
        self.embedding = nn.Linear(features, hidden)
        self.position = nn.Parameter(torch.zeros(1, context_length, hidden))
        layer = nn.TransformerEncoderLayer(
            d_model=hidden,
            nhead=heads,
            dim_feedforward=hidden * 2,
            dropout=0.0,
            activation="gelu",
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=1)
        self.output = nn.Linear(hidden, 1)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        encoded = self.encoder(self.embedding(values) + self.position)
        return self.output(encoded[:, -1, :]).squeeze(1)


def _windows(
    features: np.ndarray, targets: np.ndarray, context: int
) -> tuple[np.ndarray, np.ndarray]:
    if len(features) <= context:
        raise ValueError("deep model needs more rows than context length")
    x = np.stack([features[index - context : index] for index in range(context, len(features))])
    y = targets[context:]
    return x, y


def fit_predict_deep(
    *, spec: DeepModelSpec, train: BaselineDataset, test: BaselineDataset
) -> ProbabilisticPrediction:
    if train.feature_names != test.feature_names:
        raise ValueError("deep train/test feature schemas differ")
    if train.timestamps[-1] >= test.timestamps[0]:
        raise ValueError("deep model training must precede test data")
    torch.manual_seed(spec.seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    train_features = np.asarray(train.features, dtype=np.float32)
    train_targets = np.asarray(train.targets, dtype=np.float32)
    train_x, train_y = _windows(train_features, train_targets, spec.context_length)
    if spec.kind is DeepModelKind.TCN:
        model: nn.Module = _TcnRegressor(len(train.feature_names), spec.hidden_size)
    else:
        model = _PatchTransformerRegressor(
            len(train.feature_names),
            spec.hidden_size,
            spec.attention_heads,
            spec.context_length,
        )
    optimizer = torch.optim.Adam(model.parameters(), lr=spec.learning_rate)
    loss_function = nn.MSELoss()
    train_tensor = torch.from_numpy(train_x)
    target_tensor = torch.from_numpy(train_y)
    model.train()
    for _ in range(spec.epochs):
        optimizer.zero_grad(set_to_none=True)
        loss = loss_function(model(train_tensor), target_tensor)
        if not torch.isfinite(loss):
            raise ValueError("deep model produced non-finite loss")
        loss.backward()
        optimizer.step()
    combined = np.concatenate(
        (train_features[-spec.context_length :], np.asarray(test.features, dtype=np.float32))
    )
    test_x = np.stack(
        [combined[index : index + spec.context_length] for index in range(len(test.sample_ids))]
    )
    model.eval()
    with torch.inference_mode():
        fitted = model(train_tensor).cpu().numpy()
        predicted = model(torch.from_numpy(test_x)).cpu().numpy()
    residual_std = float(np.std(train_y - fitted, ddof=1)) if len(train_y) > 1 else 0.0
    return from_point_predictions(
        model_id=spec.model_id,
        model_family=spec.kind.value,
        sample_ids=test.sample_ids,
        point=tuple(float(value) for value in predicted),
        residual_std=residual_std,
    )
