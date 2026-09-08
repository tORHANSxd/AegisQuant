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
    # Legacy execution rates are round-trip totals; explicit legs override the equal split.
    long_entry_cost: NonNegativeDecimal | None = None
    long_exit_cost: NonNegativeDecimal | None = None
    short_entry_cost: NonNegativeDecimal | None = None
    short_exit_cost: NonNegativeDecimal | None = None
    expected_funding_long: FiniteDecimal | None = None
    expected_funding_short: FiniteDecimal | None = None

    @property
    def execution_rate(self) -> Decimal:
        return canonical_result(
            self.fee_rate + self.spread_rate + self.slippage_rate + self.impact_rate
        )

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


class ActionValueLabel(DomainModel):
    decision_time: UtcDateTime
    earliest_execution_time: UtcDateTime
    horizon_end_time: UtcDateTime
    gross_long_return: FiniteDecimal
    gross_short_return: FiniteDecimal
    long_entry_cost: NonNegativeDecimal
    long_exit_cost: NonNegativeDecimal
    short_entry_cost: NonNegativeDecimal
    short_exit_cost: NonNegativeDecimal
    expected_funding_long: FiniteDecimal
    expected_funding_short: FiniteDecimal
    expected_borrow_short: NonNegativeDecimal
    long_risk_buffer: NonNegativeDecimal = Decimal("0")
    short_tail_risk_buffer: NonNegativeDecimal = Decimal("0")
    uncertainty_buffer: NonNegativeDecimal = Decimal("0")
    minimum_economic_margin: NonNegativeDecimal = Decimal("0")
    net_value_long: FiniteDecimal
    net_value_flat: FiniteDecimal = Decimal("0")
    net_value_short: FiniteDecimal
    best_action: DirectionClass
    action_margin: FiniteDecimal

    @model_validator(mode="after")
    def validate_action_values(self) -> ActionValueLabel:
        if not self.decision_time < self.earliest_execution_time <= self.horizon_end_time:
            raise ValueError("action label must begin at a strictly future executable event")
        expected_long = canonical_result(
            self.gross_long_return
            - self.long_entry_cost
            - self.long_exit_cost
            - self.expected_funding_long
            - self.long_risk_buffer
        )
        expected_short = canonical_result(
            self.gross_short_return
            - self.short_entry_cost
            - self.short_exit_cost
            - self.expected_funding_short
            - self.expected_borrow_short
            - self.short_tail_risk_buffer
        )
        if (
            self.net_value_flat != 0
            or self.net_value_long != expected_long
            or self.net_value_short != expected_short
        ):
            raise ValueError("action value costs must conserve separately for LONG/FLAT/SHORT")
        margin = canonical_result(max(expected_long, expected_short))
        if self.action_margin != margin:
            raise ValueError("action margin must compare the best directional value against cash")
        expected_action = DirectionClass.FLAT
        if (
            margin > self.uncertainty_buffer + self.minimum_economic_margin
            and expected_long != expected_short
        ):
            expected_action = (
                DirectionClass.UP if expected_long > expected_short else DirectionClass.DOWN
            )
        if self.best_action is not expected_action:
            raise ValueError("action must exceed the uncertainty and economic margin over FLAT")
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
