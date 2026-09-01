"""Strict point-in-time label contracts for tradable research targets."""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    PositiveDecimal,
    UnitInterval,
    canonical_result,
)

LABEL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


class DirectionClass(StrEnum):
    UP = "UP"
    FLAT = "FLAT"
    DOWN = "DOWN"


class LabelKind(StrEnum):
    RETURN_PATH = "RETURN_PATH"
    EXECUTION = "EXECUTION"
    EVENT_IMPACT = "EVENT_IMPACT"


class LabelDefinition(DomainModel):
    label_id: str
    version: str
    kind: LabelKind
    description: str
    horizon_seconds: Annotated[int, Field(gt=0)]
    inputs: tuple[str, ...]
    cost_policy_version: str
    tests: tuple[str, ...]

    @field_validator("label_id")
    @classmethod
    def validate_label_id(cls, value: str) -> str:
        if LABEL_ID_RE.fullmatch(value) is None:
            raise ValueError("label_id must be a dotted identifier")
        return value

    @field_validator("description", "cost_policy_version")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label metadata cannot be blank")
        return value

    @model_validator(mode="after")
    def require_tests_and_version(self) -> LabelDefinition:
        if not self.tests:
            raise ValueError("every label requires tests")
        if len(self.version.split(".")) != 3:
            raise ValueError("label version must be semantic x.y.z")
        return self

    @property
    def qualified_id(self) -> str:
        return f"{self.label_id}@{self.version}"

    @property
    def definition_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class CostAssumption(DomainModel):
    policy_version: str
    fee_rate: NonNegativeDecimal = Decimal("0")
    spread_rate: NonNegativeDecimal = Decimal("0")
    slippage_rate: NonNegativeDecimal = Decimal("0")
    impact_rate: NonNegativeDecimal = Decimal("0")
    borrow_rate: NonNegativeDecimal = Decimal("0")
    funding_rate: FiniteDecimal = Decimal("0")

    @property
    def total_rate(self) -> Decimal:
        return canonical_result(
            self.fee_rate
            + self.spread_rate
            + self.slippage_rate
            + self.impact_rate
            + self.borrow_rate
            + self.funding_rate
        )


class PricePathObservation(DomainModel):
    instrument_id: str
    event_time: UtcDateTime
    available_time: UtcDateTime
    executable_price: PositiveDecimal
    source_dataset_id: str

    @model_validator(mode="after")
    def validate_availability(self) -> PricePathObservation:
        if self.available_time < self.event_time:
            raise ValueError("price cannot be available before event time")
        return self


class ReturnPathLabel(DomainModel):
    label_id: str
    instrument_id: str
    decision_time: UtcDateTime
    label_start_time: UtcDateTime
    label_end_time: UtcDateTime
    horizon_steps: Annotated[int, Field(gt=0)]
    gross_return: FiniteDecimal
    total_cost_rate: FiniteDecimal
    net_return: FiniteDecimal
    direction: DirectionClass
    q10_return: FiniteDecimal
    q50_return: FiniteDecimal
    q90_return: FiniteDecimal
    realized_volatility: NonNegativeDecimal
    maximum_adverse_excursion: FiniteDecimal
    maximum_favorable_excursion: FiniteDecimal
    overlap_weight: PositiveDecimal
    cost_policy_version: str
    source_dataset_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_label(self) -> ReturnPathLabel:
        if not self.decision_time < self.label_start_time <= self.label_end_time:
            raise ValueError("label window must begin strictly after decision time")
        expected = canonical_result(self.gross_return - self.total_cost_rate)
        if self.net_return != expected:
            raise ValueError("net label must equal gross return minus explicit cost")
        if not self.q10_return <= self.q50_return <= self.q90_return:
            raise ValueError("return quantiles must be ordered")
        if self.maximum_adverse_excursion > self.maximum_favorable_excursion:
            raise ValueError("MAE cannot exceed MFE")
        if not self.source_dataset_ids:
            raise ValueError("labels require source dataset lineage")
        return self


class ExecutionLabel(DomainModel):
    label_id: str
    decision_time: UtcDateTime
    label_end_time: UtcDateTime
    fill_probability: UnitInterval
    fill_ratio: UnitInterval
    slippage_bps: FiniteDecimal
    adverse_selection_bps: FiniteDecimal
    post_cancel_fill: bool
    impact_bps: FiniteDecimal
    recovery_seconds: NonNegativeDecimal
    multi_leg_exposure_seconds: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_window(self) -> ExecutionLabel:
        if self.label_end_time <= self.decision_time:
            raise ValueError("execution label requires a future observation window")
        return self


class EventImpactLabel(DomainModel):
    label_id: str
    event_id: str
    instrument_id: str
    first_observed_time: UtcDateTime
    label_end_time: UtcDateTime
    net_return: FiniteDecimal
    volatility_change: FiniteDecimal
    downside_return: FiniteDecimal
    spread_change_bps: FiniteDecimal
    funding_change: FiniteDecimal
    event_persisted: bool

    @model_validator(mode="after")
    def validate_window(self) -> EventImpactLabel:
        if self.label_end_time <= self.first_observed_time:
            raise ValueError("event impact label must end after first observation")
        return self


class LabelSetManifest(DomainModel):
    label_set_id: str
    definition_hashes: tuple[str, ...]
    created_at: UtcDateTime

    @field_validator("definition_hashes")
    @classmethod
    def validate_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("label hashes must be non-empty, unique, and sorted")
        for value in values:
            ensure_sha256(value, field_name="label definition hash")
        return values

    @property
    def manifest_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))
