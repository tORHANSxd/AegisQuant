"""Deterministic covariance shrinkage with factor and regime risk."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import AssetId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import canonical_result
from aegisquant.portfolio.models import CovarianceEstimate, FactorRisk, RiskRegime


def _validate_sample(
    asset_ids: tuple[AssetId, ...], sample: tuple[tuple[Decimal, ...], ...]
) -> None:
    size = len(asset_ids)
    if size == 0 or len(set(asset_ids)) != size:
        raise ValueError("covariance assets must be non-empty and unique")
    if len(sample) != size or any(len(row) != size for row in sample):
        raise ValueError("sample covariance shape must match assets")
    for row_index, row in enumerate(sample):
        if row[row_index] < 0:
            raise ValueError("sample covariance diagonal cannot be negative")
        for column_index, value in enumerate(row):
            if not value.is_finite():
                raise ValueError("sample covariance must be finite")
            if value != sample[column_index][row_index]:
                raise ValueError("sample covariance must be symmetric")


def estimate_covariance(
    *,
    asset_ids: tuple[AssetId, ...],
    sample_covariance: tuple[tuple[Decimal, ...], ...],
    shrinkage: Decimal,
    factors: tuple[FactorRisk, ...],
    regime: RiskRegime,
    regime_multiplier: Decimal,
    observed_at: UtcDateTime,
    available_at: UtcDateTime,
) -> CovarianceEstimate:
    """Shrink off-diagonal noise, add factor covariance, then apply regime stress."""

    _validate_sample(asset_ids, sample_covariance)
    if not Decimal("0") <= shrinkage <= Decimal("1"):
        raise ValueError("covariance shrinkage must be in [0, 1]")
    if regime_multiplier <= 0 or not regime_multiplier.is_finite():
        raise ValueError("regime multiplier must be positive and finite")
    if available_at < observed_at:
        raise ValueError("covariance availability cannot precede observation")
    asset_keys = tuple(str(item) for item in asset_ids)
    known_assets = set(asset_keys)
    if any(not set(factor.exposures).issubset(known_assets) for factor in factors):
        raise ValueError("factor exposure references an unknown asset")
    matrix: list[tuple[Decimal, ...]] = []
    for row_index, row in enumerate(sample_covariance):
        output_row: list[Decimal] = []
        for column_index, sample_value in enumerate(row):
            shrunk = sample_value if row_index == column_index else sample_value * (1 - shrinkage)
            factor_covariance = sum(
                (
                    factor.exposures.get(asset_keys[row_index], Decimal("0"))
                    * factor.exposures.get(asset_keys[column_index], Decimal("0"))
                    * factor.variance
                    for factor in factors
                ),
                start=Decimal("0"),
            )
            output_row.append(canonical_result((shrunk + factor_covariance) * regime_multiplier))
        matrix.append(tuple(output_row))
    payload = {
        "assets": asset_keys,
        "matrix": [[str(value) for value in row] for row in matrix],
        "shrinkage": str(shrinkage),
        "factors": [factor.model_dump(mode="json") for factor in factors],
        "regime": regime.value,
        "regime_multiplier": str(regime_multiplier),
        "observed_at": observed_at.isoformat(),
        "available_at": available_at.isoformat(),
    }
    return CovarianceEstimate(
        asset_ids=asset_ids,
        matrix=tuple(matrix),
        shrinkage=shrinkage,
        factor_ids=tuple(factor.factor_id for factor in factors),
        regime=regime,
        regime_multiplier=regime_multiplier,
        observed_at=observed_at,
        available_at=available_at,
        estimate_sha256=canonical_sha256(payload),
    )
