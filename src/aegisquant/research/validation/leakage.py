"""Active audits that detect feature, label, revision, and normalization leakage."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from pydantic import model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.research.datasets.manifests import (
    LeakageAuditManifest,
    LeakageAuditState,
)


class FeatureSourceKind(StrEnum):
    FEATURE = "FEATURE"
    LABEL = "LABEL"


class NormalizationScope(StrEnum):
    TRAIN_ONLY = "TRAIN_ONLY"
    ROLLING_POINT_IN_TIME = "ROLLING_POINT_IN_TIME"
    FULL_SAMPLE = "FULL_SAMPLE"


class FeatureAccessRecord(DomainModel):
    record_id: str
    sample_id: str
    feature_id: str
    decision_time: UtcDateTime
    source_event_time: UtcDateTime
    available_time: UtcDateTime
    revision_time: UtcDateTime | None = None
    engagement_snapshot_time: UtcDateTime | None = None
    source_kind: FeatureSourceKind = FeatureSourceKind.FEATURE
    normalization_scope: NormalizationScope = NormalizationScope.TRAIN_ONLY


class LabelWindowRecord(DomainModel):
    sample_id: str
    decision_time: UtcDateTime
    label_start_time: UtcDateTime
    label_end_time: UtcDateTime

    @model_validator(mode="after")
    def validate_window(self) -> LabelWindowRecord:
        if self.label_end_time < self.label_start_time:
            raise ValueError("label window end cannot precede start")
        return self


class LeakageFinding(DomainModel):
    code: str
    sample_id: str
    feature_id: str | None
    detail: str


class LeakageAuditReport(DomainModel):
    audit_id: str
    state: LeakageAuditState
    checked_records: int
    findings: tuple[LeakageFinding, ...]
    generated_at: UtcDateTime

    @model_validator(mode="after")
    def validate_report(self) -> LeakageAuditReport:
        if self.checked_records < 1:
            raise ValueError("leakage audit must check records")
        expected_state = LeakageAuditState.FAILED if self.findings else LeakageAuditState.PASSED
        if self.state is not expected_state:
            raise ValueError("leakage audit state differs from findings")
        payload = {
            "state": self.state.value,
            "checked_records": self.checked_records,
            "findings": [item.model_dump(mode="json") for item in self.findings],
            "generated_at": self.generated_at.isoformat(),
        }
        if self.audit_id != canonical_sha256(payload):
            raise ValueError("leakage audit id must equal canonical report hash")
        return self

    def manifest(self) -> LeakageAuditManifest:
        return LeakageAuditManifest(
            audit_id=self.audit_id,
            state=self.state,
            checked_records=self.checked_records,
            finding_codes=tuple(sorted({item.code for item in self.findings})),
            generated_at=self.generated_at,
        )


def audit_leakage(
    *,
    feature_accesses: Iterable[FeatureAccessRecord],
    label_windows: Iterable[LabelWindowRecord],
    generated_at: UtcDateTime,
) -> LeakageAuditReport:
    accesses = tuple(feature_accesses)
    windows = tuple(label_windows)
    if not accesses and not windows:
        raise ValueError("leakage audit requires records")
    findings: list[LeakageFinding] = []
    for access in accesses:
        checks = (
            (
                access.source_event_time > access.decision_time,
                "AQ-LEAKAGE-FUTURE-EVENT",
                "source event occurs after decision",
            ),
            (
                access.available_time > access.decision_time,
                "AQ-LEAKAGE-FUTURE-AVAILABILITY",
                "source was not available at decision",
            ),
            (
                access.revision_time is not None and access.revision_time > access.decision_time,
                "AQ-LEAKAGE-FUTURE-REVISION",
                "future revision entered feature",
            ),
            (
                access.engagement_snapshot_time is not None
                and access.engagement_snapshot_time > access.decision_time,
                "AQ-LEAKAGE-FUTURE-ENGAGEMENT",
                "future engagement snapshot entered feature",
            ),
            (
                access.source_kind is FeatureSourceKind.LABEL,
                "AQ-LEAKAGE-LABEL-AS-FEATURE",
                "future label was read as feature input",
            ),
            (
                access.normalization_scope is NormalizationScope.FULL_SAMPLE,
                "AQ-LEAKAGE-FULL-SAMPLE-NORMALIZATION",
                "normalization used complete sample statistics",
            ),
        )
        for failed, code, detail in checks:
            if failed:
                findings.append(
                    LeakageFinding(
                        code=code,
                        sample_id=access.sample_id,
                        feature_id=access.feature_id,
                        detail=detail,
                    )
                )
    for window in windows:
        if window.label_start_time <= window.decision_time:
            findings.append(
                LeakageFinding(
                    code="AQ-LEAKAGE-LABEL-WINDOW-OVERLAP",
                    sample_id=window.sample_id,
                    feature_id=None,
                    detail="label window does not begin strictly after decision",
                )
            )
    ordered = tuple(
        sorted(findings, key=lambda item: (item.sample_id, item.code, item.feature_id or ""))
    )
    state = LeakageAuditState.FAILED if ordered else LeakageAuditState.PASSED
    payload = {
        "state": state.value,
        "checked_records": len(accesses) + len(windows),
        "findings": [item.model_dump(mode="json") for item in ordered],
        "generated_at": generated_at.isoformat(),
    }
    return LeakageAuditReport(
        audit_id=canonical_sha256(payload),
        state=state,
        checked_records=len(accesses) + len(windows),
        findings=ordered,
        generated_at=generated_at,
    )


def assert_no_leakage(report: LeakageAuditReport) -> None:
    if report.state is LeakageAuditState.FAILED:
        codes = ",".join(sorted({item.code for item in report.findings}))
        raise ValueError(f"AQ-RESEARCH-LEAKAGE-DETECTED: {codes}")
