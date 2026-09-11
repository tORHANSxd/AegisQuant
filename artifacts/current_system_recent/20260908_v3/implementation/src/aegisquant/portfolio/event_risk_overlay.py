"""The only event-intelligence inputs admitted to the first CAT stage."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import UnitInterval


class EventRiskOverlay(DomainModel):
    available_time: UtcDateTime
    valid_until: UtcDateTime
    risk_veto: bool = False
    position_scale: UnitInterval = Decimal("1")
    entry_hurdle_multiplier: Decimal = Field(default=Decimal("1"), ge=1, le=10)
    expected_slippage_multiplier: Decimal = Field(default=Decimal("1"), ge=1, le=10)
    data_confidence: UnitInterval = Decimal("1")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid_interval(self) -> EventRiskOverlay:
        if self.valid_until <= self.available_time:
            raise ValueError("event risk evidence must have a positive validity interval")
        return self
