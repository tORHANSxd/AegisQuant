"""Machine-readable quality rules and quarantine/Gold gates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

import pyarrow as pa

from aegisquant.data.hashing import canonical_sha256
from aegisquant.data.models import (
    LakeLayer,
    QualityIssue,
    QualityReport,
    QualitySeverity,
)
from aegisquant.domain.errors import DomainError, ErrorDisposition
from aegisquant.domain.identifiers import ArtifactId
from aegisquant.domain.time import ensure_utc


class QualityRule(Protocol):
    @property
    def rule_id(self) -> str:
        """Stable machine-readable rule ID."""
        return ""

    def evaluate(self, table: pa.Table) -> tuple[QualityIssue, ...]:
        """Return deterministic issues for one Arrow table."""
        return ()


@dataclass(frozen=True, slots=True)
class RequiredColumnsRule:
    columns: tuple[str, ...]
    rule_id: str = "required-columns"

    def evaluate(self, table: pa.Table) -> tuple[QualityIssue, ...]:
        missing = sorted(set(self.columns) - set(table.column_names))
        if not missing:
            return ()
        return (
            QualityIssue(
                rule_id=self.rule_id,
                severity=QualitySeverity.ERROR,
                message=f"missing columns: {', '.join(missing)}",
                affected_rows=table.num_rows,
            ),
        )


@dataclass(frozen=True, slots=True)
class NonNullRule:
    columns: tuple[str, ...]
    rule_id: str = "non-null"

    def evaluate(self, table: pa.Table) -> tuple[QualityIssue, ...]:
        issues: list[QualityIssue] = []
        for column in self.columns:
            if column not in table.column_names:
                continue
            null_count = table[column].null_count
            if null_count:
                issues.append(
                    QualityIssue(
                        rule_id=f"{self.rule_id}:{column}",
                        severity=QualitySeverity.ERROR,
                        message=f"{column} contains nulls",
                        affected_rows=null_count,
                    )
                )
        return tuple(issues)


@dataclass(frozen=True, slots=True)
class UniqueKeyRule:
    columns: tuple[str, ...]
    rule_id: str = "unique-key"

    def evaluate(self, table: pa.Table) -> tuple[QualityIssue, ...]:
        if any(column not in table.column_names for column in self.columns):
            return ()
        rows = table.select(self.columns).to_pylist()
        keys = [tuple(row[column] for column in self.columns) for row in rows]
        duplicates = len(keys) - len(set(keys))
        if duplicates == 0:
            return ()
        return (
            QualityIssue(
                rule_id=self.rule_id,
                severity=QualitySeverity.ERROR,
                message=f"duplicate key rows for {', '.join(self.columns)}",
                affected_rows=duplicates,
            ),
        )


@dataclass(frozen=True, slots=True)
class AvailableBeforeIngestRule:
    available_column: str = "available_time"
    ingest_column: str = "ingest_time"
    rule_id: str = "available-before-ingest"

    def evaluate(self, table: pa.Table) -> tuple[QualityIssue, ...]:
        if (
            self.available_column not in table.column_names
            or self.ingest_column not in table.column_names
        ):
            return ()
        available_values = cast(list[object], table[self.available_column].to_pylist())
        ingest_values = cast(list[object], table[self.ingest_column].to_pylist())
        invalid_count = 0
        for available, ingest in zip(available_values, ingest_values, strict=True):
            if available is None or ingest is None:
                continue
            if not isinstance(available, datetime) or not isinstance(ingest, datetime):
                invalid_count += 1
                continue
            if ensure_utc(available) > ensure_utc(ingest):
                invalid_count += 1
        if invalid_count == 0:
            return ()
        return (
            QualityIssue(
                rule_id=self.rule_id,
                severity=QualitySeverity.ERROR,
                message="available_time exceeds ingest_time",
                affected_rows=invalid_count,
            ),
        )


@dataclass(frozen=True, slots=True)
class QualityEngine:
    rules: Sequence[QualityRule]

    def evaluate(
        self, *, table: pa.Table, dataset_name: str, evaluated_at: datetime
    ) -> QualityReport:
        issues = tuple(issue for rule in self.rules for issue in rule.evaluate(table))
        evaluated = ensure_utc(evaluated_at)
        identity = {
            "dataset_name": dataset_name,
            "issues": [issue.model_dump(mode="json") for issue in issues],
            "table_schema": str(table.schema),
            "row_count": table.num_rows,
        }
        return QualityReport(
            quality_report_id=ArtifactId(canonical_sha256(identity)),
            dataset_name=dataset_name,
            evaluated_at=evaluated,
            passed=not any(issue.severity is QualitySeverity.ERROR for issue in issues),
            issues=issues,
        )


def enforce_layer_quality(*, requested_layer: LakeLayer, report: QualityReport) -> LakeLayer:
    """Route failures to quarantine and make Gold bypasses impossible."""
    if report.passed:
        return requested_layer
    if requested_layer is LakeLayer.GOLD:
        raise DomainError(
            "AQ-DATA-GOLD-QUALITY-FAILED",
            ErrorDisposition.NO_RETRY,
            str(report.quality_report_id),
        )
    return LakeLayer.QUARANTINE
