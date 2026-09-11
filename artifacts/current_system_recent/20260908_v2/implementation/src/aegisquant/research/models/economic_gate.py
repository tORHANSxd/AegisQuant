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


class PointForecastStatus(StrEnum):
    LEGACY_UNSPECIFIED = "LEGACY_UNSPECIFIED"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


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
    holding_intervals: int | None = Field(default=None, ge=1)
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
    point_forecast_status: PointForecastStatus = PointForecastStatus.LEGACY_UNSPECIFIED
    residual_calibration_status: CalibrationStatus | None = None
    probability_calibration_status: CalibrationStatus | None = None
    residual_calibrated_through: UtcDateTime | None = None
    probability_calibrated_through: UtcDateTime | None = None
    component_evidence_sha256: str | None = None

    @model_validator(mode="after")
    def validate_forecast(self) -> EconomicForecast:
        if (self.raw_prediction is None) != (self.mean_bias is None):
            raise ValueError("raw prediction and calibration bias must be present together")
        if self.label_contract_version == "holding-intervals-v2" and self.holding_intervals is None:
            raise ValueError("v2 forecast requires explicit holding intervals")
        if self.label_contract_version == "decision-offset-v1" and self.holding_intervals not in (
            None,
            self.horizon_bars - 1,
        ):
            raise ValueError("legacy holding intervals must equal horizon minus entry offset")
        if not self.q10_return <= self.q50_return <= self.q90_return:
            raise ValueError("economic forecast quantiles must be ordered")
        if self.trained_through is not None and self.trained_through >= self.available_time:
            raise ValueError("forecast training labels must mature before availability")
        if (
            self.point_forecast_status is PointForecastStatus.AVAILABLE
            and self.trained_through is None
        ):
            raise ValueError("available point forecast requires its training boundary")
        for status, through in (
            (self.residual_calibration_status, self.residual_calibrated_through),
            (self.probability_calibration_status, self.probability_calibrated_through),
        ):
            if status is CalibrationStatus.VALIDATION_CALIBRATED:
                if through is None or through >= self.available_time:
                    raise ValueError("component calibration must precede forecast availability")
                if (
                    self.component_evidence_sha256 is None
                    or len(self.component_evidence_sha256) != 64
                    or any(c not in "0123456789abcdef" for c in self.component_evidence_sha256)
                ):
                    raise ValueError("component calibration requires explicit evidence SHA256")
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

    def component_failure(
        self,
        *,
        probability_required: bool,
        decision_time: UtcDateTime,
        maximum_age_days: Decimal | None = None,
    ) -> str | None:
        """R2 uses the corrected point plus residual evidence; probability is an independent dependency."""
        if self.point_forecast_status is not PointForecastStatus.AVAILABLE:
            return "POINT_FORECAST_UNAVAILABLE"
        if self.residual_calibration_status is not CalibrationStatus.VALIDATION_CALIBRATED:
            return "RESIDUAL_CALIBRATION_UNAVAILABLE"
        if (
            probability_required
            and self.probability_calibration_status is not CalibrationStatus.VALIDATION_CALIBRATED
        ):
            return "PROBABILITY_CALIBRATION_UNAVAILABLE"
        boundaries = [self.residual_calibrated_through]
        if probability_required:
            boundaries.append(self.probability_calibrated_through)
        for through in boundaries:
            if through is None or through >= decision_time or self.available_time > decision_time:
                return "COMPONENT_NOT_YET_AVAILABLE"
            if (
                maximum_age_days is not None
                and Decimal(str((decision_time - through).total_seconds())) / 86400
                > maximum_age_days
            ):
                return "CALIBRATION_EXPIRED"
        return None

    def conservative_return(self, uncertainty_weight: Decimal) -> Decimal:
        if uncertainty_weight < 0:
            raise ValueError("uncertainty weight cannot be negative")
        return self.q50_return - uncertainty_weight * (self.q90_return - self.q10_return)
