"""Strong internal and external identifiers with deterministic constructors."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Self
from uuid import UUID, uuid5

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")


@dataclass(frozen=True, slots=True)
class TypedId:
    """Base class whose subclasses cannot be mixed accidentally."""

    value: str
    kind: ClassVar[str] = "typed"

    def __post_init__(self) -> None:
        if ID_PATTERN.fullmatch(self.value) is None:
            raise ValueError(f"invalid {self.kind} identifier")

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_name(cls, namespace: UUID, name: str) -> Self:
        """Create a stable namespace UUID identifier."""
        if not name:
            raise ValueError("deterministic identifier name cannot be empty")
        return cls(str(uuid5(namespace, name)))

    @classmethod
    def from_content(cls, content: bytes) -> Self:
        """Create a stable identifier from exact content bytes."""
        return cls(hashlib.sha256(content).hexdigest())

    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: Any, _handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        from_string = core_schema.no_info_after_validator_function(
            cls,
            core_schema.str_schema(min_length=1, max_length=255, pattern=ID_PATTERN.pattern),
        )
        return core_schema.json_or_python_schema(
            json_schema=from_string,
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(cls), from_string]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                str,
                return_schema=core_schema.str_schema(),
                when_used="json",
            ),
        )


class ExternalId(TypedId):
    """Marker base for provider-owned identifiers."""

    kind = "external"


class EventId(TypedId):
    kind = "event"


class RunId(TypedId):
    kind = "run"


class DatasetId(TypedId):
    kind = "dataset"


class FeatureSetId(TypedId):
    kind = "feature-set"


class LabelSetId(TypedId):
    kind = "label-set"


class ModelId(TypedId):
    kind = "model"


class ModelVersionId(TypedId):
    kind = "model-version"


class StrategyId(TypedId):
    kind = "strategy"


class StrategyVersionId(TypedId):
    kind = "strategy-version"


class SignalId(TypedId):
    kind = "signal"


class ProposalId(TypedId):
    kind = "proposal"


class RiskDecisionId(TypedId):
    kind = "risk-decision"


class OrderIntentId(TypedId):
    kind = "order-intent"


class ClientOrderId(TypedId):
    kind = "client-order"


class VenueOrderId(ExternalId):
    kind = "venue-order"


class FillId(ExternalId):
    kind = "fill"


class LedgerEntryId(TypedId):
    kind = "ledger-entry"


class IncidentId(TypedId):
    kind = "incident"


class ProviderId(TypedId):
    kind = "provider"


class SourceDocumentId(TypedId):
    kind = "source-document"


class ArtifactId(TypedId):
    kind = "artifact"


class InstrumentId(TypedId):
    kind = "instrument"


class VenueId(TypedId):
    kind = "venue"


class AssetId(TypedId):
    kind = "asset"


class AccountId(TypedId):
    kind = "account"


class EnvironmentId(TypedId):
    kind = "environment"


class ForecastId(TypedId):
    kind = "forecast"


class ContentId(TypedId):
    kind = "content"


class SourceIdentityId(TypedId):
    kind = "source-identity"


class SourceId(TypedId):
    kind = "source"


class SourcePolicyId(TypedId):
    kind = "source-policy"


class ClaimId(TypedId):
    kind = "claim"


class EventClusterId(TypedId):
    kind = "event-cluster"


class NarrativeId(TypedId):
    kind = "narrative"


class ImpactForecastId(TypedId):
    kind = "impact-forecast"


class RecoveryCaseId(TypedId):
    kind = "recovery-case"


class PositionLotId(TypedId):
    kind = "position-lot"


class PostingId(TypedId):
    kind = "posting"


class IdempotencyKey(TypedId):
    kind = "idempotency"


class ProviderNativeId(ExternalId):
    kind = "provider-native"


class EntryTemplateId(TypedId):
    kind = "entry-template"


class ValuationSnapshotId(TypedId):
    kind = "valuation-snapshot"


class ReconciliationCaseId(TypedId):
    kind = "reconciliation-case"


class AccountSnapshotId(TypedId):
    kind = "account-snapshot"


class LedgerSnapshotId(TypedId):
    kind = "ledger-snapshot"


class BacktestOrderId(TypedId):
    kind = "backtest-order"


class BacktestEventId(TypedId):
    kind = "backtest-event"


class CostScheduleId(TypedId):
    kind = "cost-schedule"


class InstrumentRuleId(TypedId):
    kind = "instrument-rule"


class MarginPolicyId(TypedId):
    kind = "margin-policy"


class MultiLegPlanId(TypedId):
    kind = "multi-leg-plan"


class StressScenarioId(TypedId):
    kind = "stress-scenario"
