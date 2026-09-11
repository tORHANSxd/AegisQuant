"""Strict P17 candidate, trial, scoring, and procurement contracts."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from aegisquant.data.models import ProviderStatus
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ProviderId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, UnitInterval


class ProviderClass(StrEnum):
    MARKET_HISTORY = "market_history"
    DERIVATIVES_AGGREGATE = "derivatives_aggregate"
    ONCHAIN = "onchain"
    CROSS_ASSET = "cross_asset"
    NEWS_PERSONAL = "news_personal"
    NEWS_INSTITUTIONAL = "news_institutional"
    SOCIAL = "social"


class EvidenceState(StrEnum):
    DESK_REVIEW_ONLY = "desk_review_only"
    NOT_TESTED = "not_tested"
    TRIAL_COMPLETE = "trial_complete"


class PriceDisclosure(StrEnum):
    PUBLIC = "public"
    ORDER_FORM = "order_form"
    DEVELOPER_CONSOLE = "developer_console"
    CONTACT_SALES = "contact_sales"


class ProcurementDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    DEFER = "DEFER"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SourceAuthority(StrEnum):
    OFFICIAL_EXCHANGE = "official_exchange"
    THIRD_PARTY_AGGREGATOR = "third_party_aggregator"


class DegradationMode(StrEnum):
    BASELINE_ONLY = "BASELINE_ONLY"
    BASELINE_PLUS_APPROVED_SOURCE = "BASELINE_PLUS_APPROVED_SOURCE"


class ProviderCandidate(DomainModel):
    provider_id: ProviderId
    provider_name: str
    provider_class: ProviderClass
    comparison_group: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    official_sources: tuple[str, ...]
    credentials_required: bool
    price_disclosure: PriceDisclosure
    public_monthly_price_usd: NonNegativeDecimal | None = None
    license_review_complete: bool
    evidence_state: EvidenceState
    status: ProviderStatus
    runtime_dependency: bool
    official_fact_authority: bool
    desk_review_facts: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    condition: str | None = None

    @field_validator("provider_name")
    @classmethod
    def non_blank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provider name cannot be blank")
        return value

    @field_validator("official_sources")
    @classmethod
    def official_https_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("official sources must be non-empty and unique")
        if any(not item.startswith("https://") for item in value):
            raise ValueError("official sources must use HTTPS")
        return value

    @model_validator(mode="after")
    def fail_closed_candidate(self) -> ProviderCandidate:
        if (
            self.price_disclosure is not PriceDisclosure.PUBLIC
            and self.public_monthly_price_usd is not None
        ):
            raise ValueError("non-public pricing cannot carry a public monthly price")
        if self.status is ProviderStatus.APPROVED:
            if self.evidence_state is not EvidenceState.TRIAL_COMPLETE:
                raise ValueError("approved provider requires completed trial evidence")
            if not self.license_review_complete:
                raise ValueError("approved provider requires completed license review")
        if self.runtime_dependency and self.status is not ProviderStatus.APPROVED:
            raise ValueError("unapproved provider cannot be a runtime dependency")
        if self.official_fact_authority:
            raise ValueError("paid aggregator cannot be official trading-fact authority")
        return self


class ProviderCandidateCatalog(DomainModel):
    schema_version: str
    reviewed_at_utc: UtcDateTime
    candidates: tuple[ProviderCandidate, ...]

    @model_validator(mode="after")
    def unique_candidates(self) -> ProviderCandidateCatalog:
        identifiers = [str(item.provider_id) for item in self.candidates]
        if not identifiers or len(identifiers) != len(set(identifiers)):
            raise ValueError("candidate catalog requires unique provider IDs")
        return self


class TrialBudget(DomainModel):
    proposed_max_cost_usd: NonNegativeDecimal
    approved_max_cost_usd: NonNegativeDecimal
    user_budget_approved: bool
    approval_reference: str | None = None
    max_calls: int = Field(ge=0)
    max_storage_gb: NonNegativeDecimal
    max_duration_days: int = Field(ge=1, le=30)
    overage_allowed: bool = False
    automatic_renewal_allowed: bool = False

    @model_validator(mode="after")
    def budget_is_fail_closed(self) -> TrialBudget:
        if self.approved_max_cost_usd > self.proposed_max_cost_usd:
            raise ValueError("approved cost cannot exceed proposed cost")
        if self.user_budget_approved:
            if self.approval_reference is None or not self.approval_reference.strip():
                raise ValueError("approved budget requires an approval reference")
        elif self.approved_max_cost_usd != Decimal("0") or self.approval_reference is not None:
            raise ValueError("unapproved trial budget must remain zero")
        if self.overage_allowed or self.automatic_renewal_allowed:
            raise ValueError("P17 trials prohibit overage and automatic renewal")
        return self


class TrialCriteria(DomainModel):
    min_oos_observations: int = Field(ge=1)
    min_official_match_rate: UnitInterval
    min_completeness_rate: UnitInterval
    max_gap_rate: UnitInterval
    max_p95_latency_ms: NonNegativeDecimal
    min_net_incremental_bps: FiniteDecimal
    max_adjusted_p_value: UnitInterval
    max_operations_minutes_per_day: NonNegativeDecimal
    min_news_recall: UnitInterval | None = None
    max_news_false_alert_rate: UnitInterval | None = None
    max_news_duplicate_rate: UnitInterval | None = None
    min_news_risk_coverage_rate: UnitInterval | None = None

    @model_validator(mode="after")
    def news_metrics_are_complete(self) -> TrialCriteria:
        news_values = (
            self.min_news_recall,
            self.max_news_false_alert_rate,
            self.max_news_duplicate_rate,
            self.min_news_risk_coverage_rate,
        )
        if any(item is not None for item in news_values) and any(
            item is None for item in news_values
        ):
            raise ValueError("news criteria must be supplied as a complete set")
        return self


class TrialPlan(DomainModel):
    trial_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,95}$")
    provider_ids: tuple[ProviderId, ...]
    hypothesis: str
    datasets: tuple[str, ...]
    asset_scope: tuple[str, ...]
    equal_research_budget: bool
    official_crosscheck_sources: tuple[str, ...]
    budget: TrialBudget
    criteria: TrialCriteria
    activated: bool
    stop_conditions: tuple[str, ...]
    condition: str | None = None

    @model_validator(mode="after")
    def validate_plan(self) -> TrialPlan:
        if not self.provider_ids or len(self.provider_ids) != len(set(self.provider_ids)):
            raise ValueError("trial plan requires unique provider IDs")
        if not self.hypothesis.strip() or not self.datasets or not self.asset_scope:
            raise ValueError("trial scope cannot be blank")
        if not self.equal_research_budget:
            raise ValueError("provider comparison requires equal research budget")
        if not self.official_crosscheck_sources:
            raise ValueError("trial requires official cross-check sources")
        if not self.stop_conditions:
            raise ValueError("trial requires explicit stop conditions")
        if self.activated and not self.budget.user_budget_approved:
            raise ValueError("trial cannot activate without user-approved budget")
        return self


class TrialPlanDocument(DomainModel):
    schema_version: str
    plans: tuple[TrialPlan, ...]

    @model_validator(mode="after")
    def unique_plans(self) -> TrialPlanDocument:
        identifiers = [item.trial_id for item in self.plans]
        if not identifiers or len(identifiers) != len(set(identifiers)):
            raise ValueError("trial plan IDs must be unique")
        return self


class TrialMeasurement(DomainModel):
    provider_id: ProviderId
    oos_observations: int = Field(ge=0)
    official_match_rate: UnitInterval
    completeness_rate: UnitInterval
    gap_rate: UnitInterval
    p95_latency_ms: NonNegativeDecimal
    baseline_net_bps: FiniteDecimal
    augmented_net_bps: FiniteDecimal
    incremental_data_cost_bps: NonNegativeDecimal
    incremental_operations_cost_bps: NonNegativeDecimal
    incremental_trading_cost_bps: NonNegativeDecimal
    adjusted_p_value: UnitInterval
    operations_minutes_per_day: NonNegativeDecimal
    total_cost_usd: NonNegativeDecimal
    license_approved: bool
    point_in_time_verified: bool
    negative_result_retained: bool

    @property
    def net_incremental_bps(self) -> Decimal:
        return (
            self.augmented_net_bps
            - self.baseline_net_bps
            - self.incremental_data_cost_bps
            - self.incremental_operations_cost_bps
            - self.incremental_trading_cost_bps
        )


class ProviderDecisionRecord(DomainModel):
    provider_id: ProviderId
    comparison_group: str
    decision: ProcurementDecision
    evidence_state: EvidenceState
    reason_codes: tuple[str, ...]
    net_incremental_bps: FiniteDecimal | None = None
    selected_as_primary: bool = False

    @model_validator(mode="after")
    def approval_requires_selection(self) -> ProviderDecisionRecord:
        if self.decision is ProcurementDecision.APPROVE:
            if (
                not self.selected_as_primary
                or self.evidence_state is not EvidenceState.TRIAL_COMPLETE
            ):
                raise ValueError("approval requires completed evidence and primary selection")
        elif self.selected_as_primary:
            raise ValueError("non-approved provider cannot be selected as primary")
        if not self.reason_codes:
            raise ValueError("provider decision requires reason codes")
        return self


class NewsReferenceEvent(DomainModel):
    event_id: str
    official_available_time: UtcDateTime
    risk_relevant: bool


class NewsDetection(DomainModel):
    detection_id: str
    matched_official_event_id: str | None
    available_time: UtcDateTime
    story_fingerprint: str


class NewsBakeoffMetrics(DomainModel):
    reference_event_count: int = Field(ge=1)
    detection_count: int = Field(ge=0)
    matched_event_count: int = Field(ge=0)
    recall: UnitInterval
    false_alert_rate: UnitInterval
    duplicate_rate: UnitInterval
    mean_lead_time_seconds: FiniteDecimal
    risk_coverage_rate: UnitInterval


class DegradationSelection(DomainModel):
    mode: DegradationMode
    selected_record_ids: tuple[str, ...]
    baseline_preserved: bool
    candidate_records_used: bool
    runtime_hard_dependency: bool


class TradingFactRecord(DomainModel):
    fact_id: str
    fact_type: str
    source_authority: SourceAuthority
    source_id: str
