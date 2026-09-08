"""Distribution forecast contract consumed by the CAT economic filter."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, UnitInterval


class CalibrationStatus(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    VALIDATION_CALIBRATED = "VALIDATION_CALIBRATED"


class EconomicForecast(DomainModel):
    expected_gross_return: FiniteDecimal
    q10_return: FiniteDecimal
    q50_return: FiniteDecimal
    q90_return: FiniteDecimal
    p_net_positive: UnitInterval
    prediction_uncertainty: NonNegativeDecimal
    available_time: UtcDateTime
    horizon_bars: Literal[6, 12] = 6
    calibration_status: CalibrationStatus = CalibrationStatus.UNAVAILABLE
    calibrated_through: UtcDateTime | None = None
    calibration_sha256: str | None = None
    label_contract_version: Literal["decision-offset-v1", "holding-intervals-v2"] = (
        "decision-offset-v1"
    )
    holding_intervals: int = Field(default=5, ge=1)
    return_unit: Literal["ARITHMETIC_OPEN_TO_OPEN"] = "ARITHMETIC_OPEN_TO_OPEN"
    prediction_object: Literal["FIXED_INTERVAL_LONG_NOT_TREND_TRADE_RETURN"] = (
        "FIXED_INTERVAL_LONG_NOT_TREND_TRADE_RETURN"
    )
    uncertainty_definition: Literal["VALIDATION_RESIDUAL_PREDICTIVE_INTERVAL"] = (
        "VALIDATION_RESIDUAL_PREDICTIVE_INTERVAL"
    )
    raw_prediction: FiniteDecimal | None = None
    mean_bias: FiniteDecimal | None = None
    trained_through: UtcDateTime | None = None

    @model_validator(mode="after")
    def validate_forecast(self) -> EconomicForecast:
        if not self.q10_return <= self.q50_return <= self.q90_return:
            raise ValueError("economic forecast quantiles must be ordered")
        if self.trained_through is not None and self.trained_through >= self.available_time:
            raise ValueError("forecast training labels must mature before availability")
        if (
            self.raw_prediction is not None
            and self.mean_bias is not None
            and abs(self.raw_prediction + self.mean_bias - self.expected_gross_return)
            > Decimal("1e-12")
        ):
            raise ValueError("raw prediction plus bias must equal corrected forecast")
        if self.calibration_status is CalibrationStatus.VALIDATION_CALIBRATED:
            if self.calibrated_through is None or self.calibrated_through >= self.available_time:
                raise ValueError("economic calibration must precede forecast availability")
            if (
                self.calibration_sha256 is None
                or len(self.calibration_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.calibration_sha256)
            ):
                raise ValueError("economic calibration requires evidence SHA256")
        return self

    def conservative_return(self, uncertainty_weight: Decimal) -> Decimal:
        if uncertainty_weight < 0:
            raise ValueError("uncertainty weight cannot be negative")
        return self.q50_return - uncertainty_weight * (self.q90_return - self.q10_return)
