"""Generate and verify deterministic event, configuration, and data JSON Schemas."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from aegisquant.accounting.models import (
    AccountingInstrument,
    CashflowEvent,
    ChartOfAccounts,
    DailyLedgerSnapshot,
    EntryTemplate,
    EquitySnapshot,
    LedgerRecord,
    PnLBreakdown,
    PositionLotState,
    ReconciliationCase,
    SettlementEvent,
    ValuationSnapshot,
    VenueAccountSnapshot,
)
from aegisquant.backtest.models import (
    BacktestFill,
    BacktestOrder,
    BacktestResult,
    BacktestRunSpec,
    CostSchedule,
    HistoricalInstrumentRule,
    MarginPolicy,
    StressScenario,
)
from aegisquant.backtest.policy import BacktestPolicy
from aegisquant.config.models import AppConfig
from aegisquant.data.archive import RevisionRecord, TombstoneRecord
from aegisquant.data.catalog import CatalogEntry
from aegisquant.data.checkpoint import IngestCheckpoint
from aegisquant.data.lineage import TransformationLineage
from aegisquant.data.market import (
    CanonicalAsset,
    CanonicalExposure,
    CanonicalPair,
    ClockObservation,
    ComparisonResult,
    LeadLagObservation,
    MarketObservation,
    UnifiedInstrument,
)
from aegisquant.data.models import (
    ContentTimeSemantics,
    DatasetManifest,
    ImportProposal,
    InventoryRecord,
    ProviderRegistryDocument,
    QualityReport,
)
from aegisquant.data.providers.binance.adapter import (
    DatasetDescriptor,
    ProviderHealth,
    ProviderQuota,
)
from aegisquant.data.providers.binance.changelog import ChangelogSnapshot
from aegisquant.data.providers.binance.models import (
    BookTickerRecord,
    ConnectionHealth,
    DepthDeltaRecord,
    FundingRateRecord,
    InstrumentSnapshot,
    KlineRecord,
    MarkIndexRecord,
    OpenInterestRecord,
    RawResponseEnvelope,
    SoakEvidence,
    SoakStreamEvidence,
    TradeRecord,
)
from aegisquant.data.providers.binance.replay import FixtureEnvelope, FixtureManifest
from aegisquant.data.providers.public import (
    BookUpdate,
    PublicRequest,
    WsSubscription,
)
from aegisquant.data.providers.public import (
    ChangelogSnapshot as PublicChangelogSnapshot,
)
from aegisquant.domain.accounting import JournalEntry, PositionLot
from aegisquant.domain.execution import Fill, OrderCommand, OrderIntent, VenueOrder
from aegisquant.domain.intelligence import (
    AlphaSignal,
    ClaimRecord,
    EngagementSnapshot,
    EventCluster,
    EventImpactForecast,
    ForecastBundle,
    MarketEvent,
    PortfolioProposal,
    RawContentEnvelope,
    RiskDecision,
    SourceIdentity,
)
from aegisquant.domain.policy import SourceProcessingPolicy
from aegisquant.domain.serialization import EventEnvelope
from aegisquant.intelligence.collectors import (
    BlueskyStreamSelection,
    CollectedContent,
    OfficialWebChangeSnapshot,
    SourceBatch,
    SourceQuotaWindow,
    SourceRequest,
)
from aegisquant.research.provider_bakeoff.models import (
    ProviderCandidateCatalog,
    TrialPlanDocument,
)

JSON_SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"


@dataclass(frozen=True, slots=True)
class Contract:
    schema_name: str
    version: str
    model: type[BaseModel]
    path: Path


EVENT_CONTRACTS: Final = (
    Contract("aegisquant.event-envelope", "1.0.0", EventEnvelope, Path("event-envelope-v1.json")),
    Contract("aegisquant.market-event", "1.0.0", MarketEvent, Path("market-event-v1.json")),
    Contract(
        "aegisquant.raw-content-envelope",
        "1.0.0",
        RawContentEnvelope,
        Path("raw-content-envelope-v1.json"),
    ),
    Contract(
        "aegisquant.source-identity", "1.0.0", SourceIdentity, Path("source-identity-v1.json")
    ),
    Contract(
        "aegisquant.engagement-snapshot",
        "1.0.0",
        EngagementSnapshot,
        Path("engagement-snapshot-v1.json"),
    ),
    Contract(
        "aegisquant.collected-content",
        "1.0.0",
        CollectedContent,
        Path("collected-content-v1.json"),
    ),
    Contract("aegisquant.source-batch", "1.0.0", SourceBatch, Path("source-batch-v1.json")),
    Contract(
        "aegisquant.source-quota-window",
        "1.0.0",
        SourceQuotaWindow,
        Path("source-quota-window-v1.json"),
    ),
    Contract(
        "aegisquant.official-web-change-snapshot",
        "1.0.0",
        OfficialWebChangeSnapshot,
        Path("official-web-change-snapshot-v1.json"),
    ),
    Contract(
        "aegisquant.bluesky-stream-selection",
        "1.0.0",
        BlueskyStreamSelection,
        Path("bluesky-stream-selection-v1.json"),
    ),
    Contract("aegisquant.claim-record", "1.0.0", ClaimRecord, Path("claim-record-v1.json")),
    Contract("aegisquant.event-cluster", "1.0.0", EventCluster, Path("event-cluster-v1.json")),
    Contract(
        "aegisquant.event-impact-forecast",
        "1.0.0",
        EventImpactForecast,
        Path("event-impact-forecast-v1.json"),
    ),
    Contract(
        "aegisquant.forecast-bundle", "1.0.0", ForecastBundle, Path("forecast-bundle-v1.json")
    ),
    Contract("aegisquant.alpha-signal", "1.0.0", AlphaSignal, Path("alpha-signal-v1.json")),
    Contract(
        "aegisquant.portfolio-proposal",
        "1.0.0",
        PortfolioProposal,
        Path("portfolio-proposal-v1.json"),
    ),
    Contract("aegisquant.risk-decision", "1.0.0", RiskDecision, Path("risk-decision-v1.json")),
    Contract("aegisquant.order-intent", "1.0.0", OrderIntent, Path("order-intent-v1.json")),
    Contract("aegisquant.order-command", "1.0.0", OrderCommand, Path("order-command-v1.json")),
    Contract("aegisquant.venue-order", "1.0.0", VenueOrder, Path("venue-order-v1.json")),
    Contract("aegisquant.fill", "1.0.0", Fill, Path("fill-v1.json")),
    Contract("aegisquant.journal-entry", "1.0.0", JournalEntry, Path("journal-entry-v1.json")),
    Contract("aegisquant.position-lot", "1.0.0", PositionLot, Path("position-lot-v1.json")),
    Contract(
        "aegisquant.accounting-instrument",
        "1.0.0",
        AccountingInstrument,
        Path("accounting-instrument-v1.json"),
    ),
    Contract(
        "aegisquant.chart-of-accounts",
        "1.0.0",
        ChartOfAccounts,
        Path("chart-of-accounts-v1.json"),
    ),
    Contract(
        "aegisquant.entry-template",
        "1.0.0",
        EntryTemplate,
        Path("entry-template-v1.json"),
    ),
    Contract(
        "aegisquant.ledger-record",
        "1.0.0",
        LedgerRecord,
        Path("ledger-record-v1.json"),
    ),
    Contract(
        "aegisquant.position-lot-state",
        "1.0.0",
        PositionLotState,
        Path("position-lot-state-v1.json"),
    ),
    Contract(
        "aegisquant.cashflow-event",
        "1.0.0",
        CashflowEvent,
        Path("cashflow-event-v1.json"),
    ),
    Contract(
        "aegisquant.settlement-event",
        "1.0.0",
        SettlementEvent,
        Path("settlement-event-v1.json"),
    ),
    Contract(
        "aegisquant.valuation-snapshot",
        "1.0.0",
        ValuationSnapshot,
        Path("valuation-snapshot-v1.json"),
    ),
    Contract(
        "aegisquant.equity-snapshot",
        "1.0.0",
        EquitySnapshot,
        Path("equity-snapshot-v1.json"),
    ),
    Contract(
        "aegisquant.pnl-breakdown",
        "1.0.0",
        PnLBreakdown,
        Path("pnl-breakdown-v1.json"),
    ),
    Contract(
        "aegisquant.venue-account-snapshot",
        "1.0.0",
        VenueAccountSnapshot,
        Path("venue-account-snapshot-v1.json"),
    ),
    Contract(
        "aegisquant.reconciliation-case",
        "1.0.0",
        ReconciliationCase,
        Path("reconciliation-case-v1.json"),
    ),
    Contract(
        "aegisquant.daily-ledger-snapshot",
        "1.0.0",
        DailyLedgerSnapshot,
        Path("daily-ledger-snapshot-v1.json"),
    ),
    Contract(
        "aegisquant.backtest-run-spec",
        "1.0.0",
        BacktestRunSpec,
        Path("backtest-run-spec-v1.json"),
    ),
    Contract(
        "aegisquant.backtest-order",
        "1.0.0",
        BacktestOrder,
        Path("backtest-order-v1.json"),
    ),
    Contract(
        "aegisquant.backtest-fill",
        "1.0.0",
        BacktestFill,
        Path("backtest-fill-v1.json"),
    ),
    Contract(
        "aegisquant.backtest-result",
        "1.0.0",
        BacktestResult,
        Path("backtest-result-v1.json"),
    ),
    Contract(
        "aegisquant.backtest-cost-schedule",
        "1.0.0",
        CostSchedule,
        Path("backtest-cost-schedule-v1.json"),
    ),
    Contract(
        "aegisquant.backtest-instrument-rule",
        "1.0.0",
        HistoricalInstrumentRule,
        Path("backtest-instrument-rule-v1.json"),
    ),
    Contract(
        "aegisquant.backtest-margin-policy",
        "1.0.0",
        MarginPolicy,
        Path("backtest-margin-policy-v1.json"),
    ),
    Contract(
        "aegisquant.backtest-stress-scenario",
        "1.0.0",
        StressScenario,
        Path("backtest-stress-scenario-v1.json"),
    ),
)

CONFIG_CONTRACTS: Final = (
    Contract("aegisquant.app-config", "1.0.0", AppConfig, Path("app-config-v1.json")),
    Contract(
        "aegisquant.backtest-policy",
        "1.0.0",
        BacktestPolicy,
        Path("backtest-policy-v1.json"),
    ),
    Contract(
        "aegisquant.source-processing-policy",
        "1.0.0",
        SourceProcessingPolicy,
        Path("source-processing-policy-domain-v1.json"),
    ),
    Contract(
        "aegisquant.provider-candidate-catalog",
        "1.0.0",
        ProviderCandidateCatalog,
        Path("provider-candidate-catalog-v1.json"),
    ),
    Contract(
        "aegisquant.provider-trial-plans",
        "1.0.0",
        TrialPlanDocument,
        Path("provider-trial-plans-v1.json"),
    ),
)

DATA_CONTRACTS: Final = (
    Contract(
        "aegisquant.canonical-asset",
        "1.0.0",
        CanonicalAsset,
        Path("canonical-asset-v1.json"),
    ),
    Contract(
        "aegisquant.canonical-pair",
        "1.0.0",
        CanonicalPair,
        Path("canonical-pair-v1.json"),
    ),
    Contract(
        "aegisquant.canonical-exposure",
        "1.0.0",
        CanonicalExposure,
        Path("canonical-exposure-v1.json"),
    ),
    Contract(
        "aegisquant.unified-instrument",
        "1.0.0",
        UnifiedInstrument,
        Path("unified-instrument-v1.json"),
    ),
    Contract(
        "aegisquant.market-observation",
        "1.0.0",
        MarketObservation,
        Path("market-observation-v1.json"),
    ),
    Contract(
        "aegisquant.market-comparison",
        "1.0.0",
        ComparisonResult,
        Path("market-comparison-v1.json"),
    ),
    Contract(
        "aegisquant.clock-observation",
        "1.0.0",
        ClockObservation,
        Path("clock-observation-v1.json"),
    ),
    Contract(
        "aegisquant.lead-lag-observation",
        "1.0.0",
        LeadLagObservation,
        Path("lead-lag-observation-v1.json"),
    ),
    Contract(
        "aegisquant.public-exchange-request",
        "1.0.0",
        PublicRequest,
        Path("public-exchange-request-v1.json"),
    ),
    Contract(
        "aegisquant.public-ws-subscription",
        "1.0.0",
        WsSubscription,
        Path("public-ws-subscription-v1.json"),
    ),
    Contract(
        "aegisquant.public-book-update",
        "1.0.0",
        BookUpdate,
        Path("public-book-update-v1.json"),
    ),
    Contract(
        "aegisquant.public-changelog-snapshot",
        "1.0.0",
        PublicChangelogSnapshot,
        Path("public-changelog-snapshot-v1.json"),
    ),
    Contract(
        "aegisquant.source-request",
        "1.0.0",
        SourceRequest,
        Path("source-request-v1.json"),
    ),
    Contract(
        "aegisquant.provider-registry",
        "1.0.0",
        ProviderRegistryDocument,
        Path("provider-registry-v1.json"),
    ),
    Contract(
        "aegisquant.content-time-semantics",
        "1.0.0",
        ContentTimeSemantics,
        Path("content-time-semantics-v1.json"),
    ),
    Contract(
        "aegisquant.dataset-manifest",
        "1.0.0",
        DatasetManifest,
        Path("dataset-manifest-v1.json"),
    ),
    Contract(
        "aegisquant.quality-report",
        "1.0.0",
        QualityReport,
        Path("quality-report-v1.json"),
    ),
    Contract(
        "aegisquant.inventory-record",
        "1.0.0",
        InventoryRecord,
        Path("inventory-record-v1.json"),
    ),
    Contract(
        "aegisquant.import-proposal",
        "1.0.0",
        ImportProposal,
        Path("import-proposal-v1.json"),
    ),
    Contract(
        "aegisquant.ingest-checkpoint",
        "1.0.0",
        IngestCheckpoint,
        Path("ingest-checkpoint-v1.json"),
    ),
    Contract(
        "aegisquant.revision-record",
        "1.0.0",
        RevisionRecord,
        Path("revision-record-v1.json"),
    ),
    Contract(
        "aegisquant.tombstone-record",
        "1.0.0",
        TombstoneRecord,
        Path("tombstone-record-v1.json"),
    ),
    Contract(
        "aegisquant.catalog-entry",
        "1.0.0",
        CatalogEntry,
        Path("catalog-entry-v1.json"),
    ),
    Contract(
        "aegisquant.transformation-lineage",
        "1.0.0",
        TransformationLineage,
        Path("transformation-lineage-v1.json"),
    ),
    Contract(
        "aegisquant.binance-instrument-snapshot",
        "1.0.0",
        InstrumentSnapshot,
        Path("binance-instrument-snapshot-v1.json"),
    ),
    Contract(
        "aegisquant.binance-kline",
        "1.0.0",
        KlineRecord,
        Path("binance-kline-v1.json"),
    ),
    Contract(
        "aegisquant.binance-trade",
        "1.0.0",
        TradeRecord,
        Path("binance-trade-v1.json"),
    ),
    Contract(
        "aegisquant.binance-book-ticker",
        "1.0.0",
        BookTickerRecord,
        Path("binance-book-ticker-v1.json"),
    ),
    Contract(
        "aegisquant.binance-depth-delta",
        "1.0.0",
        DepthDeltaRecord,
        Path("binance-depth-delta-v1.json"),
    ),
    Contract(
        "aegisquant.binance-mark-index",
        "1.0.0",
        MarkIndexRecord,
        Path("binance-mark-index-v1.json"),
    ),
    Contract(
        "aegisquant.binance-funding-rate",
        "1.0.0",
        FundingRateRecord,
        Path("binance-funding-rate-v1.json"),
    ),
    Contract(
        "aegisquant.binance-open-interest",
        "1.0.0",
        OpenInterestRecord,
        Path("binance-open-interest-v1.json"),
    ),
    Contract(
        "aegisquant.binance-raw-response",
        "1.0.0",
        RawResponseEnvelope,
        Path("binance-raw-response-v1.json"),
    ),
    Contract(
        "aegisquant.binance-connection-health",
        "1.0.0",
        ConnectionHealth,
        Path("binance-connection-health-v1.json"),
    ),
    Contract(
        "aegisquant.binance-dataset-descriptor",
        "1.0.0",
        DatasetDescriptor,
        Path("binance-dataset-descriptor-v1.json"),
    ),
    Contract(
        "aegisquant.binance-provider-health",
        "1.0.0",
        ProviderHealth,
        Path("binance-provider-health-v1.json"),
    ),
    Contract(
        "aegisquant.binance-provider-quota",
        "1.0.0",
        ProviderQuota,
        Path("binance-provider-quota-v1.json"),
    ),
    Contract(
        "aegisquant.binance-fixture-envelope",
        "1.0.0",
        FixtureEnvelope,
        Path("binance-fixture-envelope-v1.json"),
    ),
    Contract(
        "aegisquant.binance-fixture-manifest",
        "1.0.0",
        FixtureManifest,
        Path("binance-fixture-manifest-v1.json"),
    ),
    Contract(
        "aegisquant.binance-changelog-snapshot",
        "1.0.0",
        ChangelogSnapshot,
        Path("binance-changelog-snapshot-v1.json"),
    ),
    Contract(
        "aegisquant.binance-soak-stream-evidence",
        "1.0.0",
        SoakStreamEvidence,
        Path("binance-soak-stream-evidence-v1.json"),
    ),
    Contract(
        "aegisquant.binance-soak-evidence",
        "1.0.0",
        SoakEvidence,
        Path("binance-soak-evidence-v1.json"),
    ),
)


def schema_bytes(contract: Contract) -> bytes:
    schema = contract.model.model_json_schema(mode="validation")
    schema["$schema"] = JSON_SCHEMA_DIALECT
    schema["$id"] = f"https://aegisquant.local/schemas/{contract.schema_name}/{contract.version}"
    schema["x-aegisquant-schema-name"] = contract.schema_name
    schema["x-aegisquant-schema-version"] = contract.version
    return (json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def expected_outputs(root: Path) -> dict[Path, bytes]:
    outputs: dict[Path, bytes] = {}
    registry_entries: list[dict[str, str]] = []
    for directory, contracts in (
        (root / "schemas/events", EVENT_CONTRACTS),
        (root / "schemas/config", CONFIG_CONTRACTS),
    ):
        for contract in contracts:
            path = directory / contract.path
            raw = schema_bytes(contract)
            outputs[path] = raw
            registry_entries.append(
                {
                    "schema_name": contract.schema_name,
                    "schema_version": contract.version,
                    "model": f"{contract.model.__module__}.{contract.model.__name__}",
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "compatibility": "BACKWARD",
                }
            )
    registry = {
        "schema_version": "1.0.0",
        "event_contracts": registry_entries,
    }
    outputs[root / "schemas/events/registry.json"] = (
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    data_registry_entries: list[dict[str, str]] = []
    for contract in DATA_CONTRACTS:
        path = root / "schemas/data" / contract.path
        raw = schema_bytes(contract)
        outputs[path] = raw
        data_registry_entries.append(
            {
                "schema_name": contract.schema_name,
                "schema_version": contract.version,
                "model": f"{contract.model.__module__}.{contract.model.__name__}",
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "compatibility": "BACKWARD",
            }
        )
    data_registry = {
        "schema_version": "1.0.0",
        "data_contracts": data_registry_entries,
    }
    outputs[root / "schemas/data/registry.json"] = (
        json.dumps(data_registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    outputs = expected_outputs(root)
    if args.check:
        stale = [
            path for path, raw in outputs.items() if not path.is_file() or path.read_bytes() != raw
        ]
        if stale:
            raise SystemExit(f"generated schemas are stale: {[path.as_posix() for path in stale]}")
        print(f"verified {len(outputs)} generated schema artifacts")
        return 0
    for path, raw in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    print(f"wrote {len(outputs)} generated schema artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
