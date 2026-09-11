"""Shared probabilistic forecast contract for every P08 model family."""

from __future__ import annotations

from decimal import Decimal

from pydantic import model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal


class ProbabilisticPrediction(DomainModel):
    model_id: str
    model_family: str
    sample_ids: tuple[str, ...]
    mean: tuple[FiniteDecimal, ...]
    std: tuple[NonNegativeDecimal, ...]
    q05: tuple[FiniteDecimal, ...]
    q50: tuple[FiniteDecimal, ...]
    q95: tuple[FiniteDecimal, ...]

    @model_validator(mode="after")
    def validate_distribution(self) -> ProbabilisticPrediction:
        lengths = {
            len(self.sample_ids),
            len(self.mean),
            len(self.std),
            len(self.q05),
            len(self.q50),
            len(self.q95),
        }
        if lengths != {len(self.sample_ids)} or not self.sample_ids:
            raise ValueError("probabilistic prediction dimensions differ")
        if len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError("probabilistic prediction sample ids must be unique")
        for lower, median, upper in zip(self.q05, self.q50, self.q95, strict=True):
            if not lower <= median <= upper:
                raise ValueError("probabilistic prediction quantiles must be ordered")
        return self


def from_point_predictions(
    *,
    model_id: str,
    model_family: str,
    sample_ids: tuple[str, ...],
    point: tuple[float, ...],
    residual_std: float,
) -> ProbabilisticPrediction:
    if residual_std < 0:
        raise ValueError("residual standard deviation cannot be negative")
    scale = Decimal(format(residual_std, ".15g"))
    width = Decimal("1.64485362695147") * scale
    means = tuple(Decimal(format(value, ".15g")) for value in point)
    return ProbabilisticPrediction(
        model_id=model_id,
        model_family=model_family,
        sample_ids=sample_ids,
        mean=means,
        std=tuple(scale for _ in means),
        q05=tuple(value - width for value in means),
        q50=means,
        q95=tuple(value + width for value in means),
    )
