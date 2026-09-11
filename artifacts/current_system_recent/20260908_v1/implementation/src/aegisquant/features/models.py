"""Immutable feature definitions, values, vectors, and decision snapshots."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.intelligence import QualityState
from aegisquant.domain.time import UtcDateTime, assert_point_in_time

FEATURE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
PARAMETER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

type FeatureValue = Decimal | int | str | bool


class FeatureEntity(StrEnum):
    INSTRUMENT = "instrument"
    EVENT = "event"
    CROSS_SECTION = "cross_section"


class FeatureDType(StrEnum):
    FLOAT64 = "float64"
    INT64 = "int64"
    STRING = "string"
    BOOLEAN = "bool"


class FeatureParameter(DomainModel):
    name: str
    value: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if PARAMETER_NAME_RE.fullmatch(value) is None:
            raise ValueError("feature parameter names must be explicit snake_case")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if not value.strip() or any(character in value for character in "[],="):
            raise ValueError("feature parameter values must be non-empty scalar text")
        return value


class FeatureDefinition(DomainModel):
    feature_id: str
    version: str
    description: str
    entity: FeatureEntity
    dtype: FeatureDType
    unit: str
    inputs: tuple[str, ...]
    formula_reference: str
    parameters: tuple[FeatureParameter, ...] = ()
    lookback_seconds: Annotated[int, Field(ge=0)]
    minimum_history: Annotated[int, Field(ge=1)]
    availability_lag_seconds: Annotated[int, Field(ge=0)] = 0
    frequency_seconds: Annotated[int, Field(gt=0)]
    normalization: str
    missing_policy: str
    point_in_time_safe: Literal[True] = True
    online_compatible: bool
    owner: str
    tests: tuple[str, ...]

    @field_validator("feature_id")
    @classmethod
    def validate_feature_id(cls, value: str) -> str:
        if FEATURE_ID_RE.fullmatch(value) is None:
            raise ValueError("feature_id must be a parameter-free dotted identifier")
        if re.search(r"(?:^|[._])[0-9]+(?:s|m|h|d)(?:[._]|$)", value):
            raise ValueError("feature parameters cannot be hidden in feature_id")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if SEMVER_RE.fullmatch(value) is None:
            raise ValueError("feature version must be semantic x.y.z")
        return value

    @field_validator(
        "description",
        "unit",
        "formula_reference",
        "normalization",
        "missing_policy",
        "owner",
    )
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("feature metadata cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_parameters_and_tests(self) -> FeatureDefinition:
        names = tuple(item.name for item in self.parameters)
        if names != tuple(sorted(names)) or len(set(names)) != len(names):
            raise ValueError("feature parameters must be unique and sorted")
        if not self.tests:
            raise ValueError("every feature definition requires tests")
        if self.online_compatible and self.minimum_history < 1:
            raise ValueError("online features require explicit history")
        return self

    @property
    def qualified_id(self) -> str:
        suffix = ",".join(f"{item.name}={item.value}" for item in self.parameters)
        parameterized = f"{self.feature_id}[{suffix}]" if suffix else self.feature_id
        return f"{parameterized}@{self.version}"

    @property
    def definition_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class FeatureValueRecord(DomainModel):
    feature_key: str
    value: FeatureValue

    @field_validator("value")
    @classmethod
    def reject_float_and_non_finite(cls, value: FeatureValue) -> FeatureValue:
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("feature values must be finite")
        return value


class FeatureVector(DomainModel):
    entity_id: str
    event_time: UtcDateTime
    available_time: UtcDateTime
    values: tuple[FeatureValueRecord, ...]
    missing_flags: tuple[str, ...] = ()
    source_dataset_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_vector(self) -> FeatureVector:
        keys = tuple(item.feature_key for item in self.values)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("feature vector keys must be unique and sorted")
        if len(set(self.missing_flags)) != len(self.missing_flags):
            raise ValueError("missing flags must be unique")
        if self.available_time < self.event_time:
            raise ValueError("feature cannot be available before its event time")
        return self


class FeatureSetManifest(DomainModel):
    feature_set_id: str
    definition_hashes: tuple[str, ...]
    created_at: UtcDateTime

    @field_validator("definition_hashes")
    @classmethod
    def validate_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or tuple(sorted(values)) != values or len(set(values)) != len(values):
            raise ValueError("feature definition hashes must be non-empty, unique, and sorted")
        for value in values:
            ensure_sha256(value, field_name="feature definition hash")
        return values

    @property
    def manifest_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class FeatureSnapshot(DomainModel):
    feature_snapshot_id: str
    entity_id: str
    as_of_time: UtcDateTime
    feature_set_id: str
    values_uri: str
    values: tuple[FeatureValueRecord, ...]
    missing_flags: tuple[str, ...]
    source_dataset_ids: tuple[str, ...]
    watermark_time: UtcDateTime
    quality_state: QualityState

    @model_validator(mode="after")
    def validate_snapshot(self) -> FeatureSnapshot:
        assert_point_in_time(available_time=self.watermark_time, decision_time=self.as_of_time)
        keys = tuple(item.feature_key for item in self.values)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("snapshot feature values must be unique and sorted")
        if not self.values_uri.strip():
            raise ValueError("snapshot values_uri is required")
        expected = canonical_sha256(
            {
                "entity_id": self.entity_id,
                "as_of_time": self.as_of_time.isoformat(),
                "feature_set_id": self.feature_set_id,
                "values": [item.model_dump(mode="json") for item in self.values],
                "missing_flags": list(self.missing_flags),
                "source_dataset_ids": list(self.source_dataset_ids),
                "watermark_time": self.watermark_time.isoformat(),
                "quality_state": self.quality_state.value,
            }
        )
        if self.feature_snapshot_id != expected:
            raise ValueError("feature_snapshot_id must equal canonical snapshot hash")
        return self


def lagged_available_time(definition: FeatureDefinition, observed_at: UtcDateTime) -> UtcDateTime:
    return observed_at + timedelta(seconds=definition.availability_lag_seconds)
