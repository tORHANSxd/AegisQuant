"""Required content-addressed manifests that gate every training task."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.intelligence import QualityState
from aegisquant.domain.time import UtcDateTime
from aegisquant.features.models import FeatureSetManifest
from aegisquant.labels.models import LabelSetManifest


def _hash(value: str, field_name: str) -> str:
    return ensure_sha256(value, field_name=field_name)


class DatasetManifest(DomainModel):
    dataset_id: str
    dataset_sha256: str
    row_count: Annotated[int, Field(gt=0)]
    starts_at: UtcDateTime
    ends_at: UtcDateTime
    source_dataset_ids: tuple[str, ...]
    created_at: UtcDateTime

    @field_validator("dataset_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _hash(value, "dataset_sha256")

    @model_validator(mode="after")
    def validate_interval(self) -> DatasetManifest:
        if self.starts_at >= self.ends_at or not self.source_dataset_ids:
            raise ValueError("dataset manifest requires interval and lineage")
        return self


class UniverseManifest(DomainModel):
    universe_id: str
    snapshot_hashes: tuple[str, ...]
    point_in_time: bool
    created_at: UtcDateTime

    @field_validator("snapshot_hashes")
    @classmethod
    def validate_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("universe manifest requires snapshots")
        for value in values:
            _hash(value, "universe snapshot hash")
        return values

    @model_validator(mode="after")
    def validate_pit(self) -> UniverseManifest:
        if not self.point_in_time:
            raise ValueError("AQ-RESEARCH-UNIVERSE-NOT-POINT-IN-TIME")
        return self


class SplitManifest(DomainModel):
    split_id: str
    split_sha256: str
    policy_id: str
    fold_hashes: tuple[str, ...]
    final_holdout_id: str
    shuffle: bool
    created_at: UtcDateTime

    @field_validator("split_sha256")
    @classmethod
    def validate_split_hash(cls, value: str) -> str:
        return _hash(value, "split_sha256")

    @field_validator("fold_hashes")
    @classmethod
    def validate_fold_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("split manifest requires folds")
        for value in values:
            _hash(value, "fold hash")
        return values

    @model_validator(mode="after")
    def forbid_shuffle(self) -> SplitManifest:
        if self.shuffle:
            raise ValueError("AQ-RESEARCH-RANDOM-TIME-SPLIT-FORBIDDEN")
        return self


class CostAssumptionManifest(DomainModel):
    policy_version: str
    policy_sha256: str
    components: tuple[str, ...]
    created_at: UtcDateTime

    @field_validator("policy_sha256")
    @classmethod
    def validate_policy_hash(cls, value: str) -> str:
        return _hash(value, "cost policy hash")

    @model_validator(mode="after")
    def validate_components(self) -> CostAssumptionManifest:
        required = {"fee", "spread", "slippage", "impact", "funding", "borrow"}
        if not required.issubset(set(self.components)):
            raise ValueError("cost manifest is missing required economic components")
        return self


class DataQualityReport(DomainModel):
    quality_state: QualityState
    checked_rows: Annotated[int, Field(gt=0)]
    missing_fraction: Annotated[float, Field(ge=0.0, le=1.0)]
    stale_fraction: Annotated[float, Field(ge=0.0, le=1.0)]
    issues: tuple[str, ...]
    generated_at: UtcDateTime


class LeakageAuditState(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class LeakageAuditManifest(DomainModel):
    audit_id: str
    state: LeakageAuditState
    checked_records: Annotated[int, Field(gt=0)]
    finding_codes: tuple[str, ...]
    generated_at: UtcDateTime

    @model_validator(mode="after")
    def validate_findings(self) -> LeakageAuditManifest:
        if self.state is LeakageAuditState.PASSED and self.finding_codes:
            raise ValueError("passed leakage audit cannot contain findings")
        if self.state is LeakageAuditState.FAILED and not self.finding_codes:
            raise ValueError("failed leakage audit requires findings")
        return self


class TrainingManifestBundle(DomainModel):
    dataset: DatasetManifest
    feature_set: FeatureSetManifest
    label_set: LabelSetManifest
    universe: UniverseManifest
    split: SplitManifest
    costs: CostAssumptionManifest
    quality: DataQualityReport
    leakage: LeakageAuditManifest

    @model_validator(mode="after")
    def training_must_be_ready(self) -> TrainingManifestBundle:
        if self.quality.quality_state is not QualityState.GOOD:
            raise ValueError("AQ-RESEARCH-DATA-QUALITY-NOT-GOOD")
        if self.leakage.state is not LeakageAuditState.PASSED:
            raise ValueError("AQ-RESEARCH-LEAKAGE-AUDIT-FAILED")
        return self

    @property
    def bundle_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))
