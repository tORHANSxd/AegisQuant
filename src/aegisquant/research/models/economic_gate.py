"""Distribution forecast contract consumed by the CAT economic filter."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import model_validator

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

    @model_validator(mode="after")
    def validate_forecast(self) -> EconomicForecast:
        if not self.q10_return <= self.q50_return <= self.q90_return:
            raise ValueError("economic forecast quantiles must be ordered")
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
