"""Generate and verify deterministic event, configuration, and data JSON Schemas."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from aegisquant.config.models import AppConfig
from aegisquant.data.archive import RevisionRecord, TombstoneRecord
from aegisquant.data.catalog import CatalogEntry
from aegisquant.data.checkpoint import IngestCheckpoint
from aegisquant.data.lineage import TransformationLineage
from aegisquant.data.models import (
    ContentTimeSemantics,
    DatasetManifest,
    ImportProposal,
    InventoryRecord,
    ProviderRegistryDocument,
    QualityReport,
)
from aegisquant.domain.accounting import JournalEntry, PositionLot
from aegisquant.domain.execution import Fill, OrderCommand, OrderIntent, VenueOrder
from aegisquant.domain.intelligence import (
    AlphaSignal,
    ClaimRecord,
    EventCluster,
    EventImpactForecast,
    ForecastBundle,
    MarketEvent,
    PortfolioProposal,
    RawContentEnvelope,
    RiskDecision,
)
from aegisquant.domain.policy import SourceProcessingPolicy
from aegisquant.domain.serialization import EventEnvelope

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
)

CONFIG_CONTRACTS: Final = (
    Contract("aegisquant.app-config", "1.0.0", AppConfig, Path("app-config-v1.json")),
    Contract(
        "aegisquant.source-processing-policy",
        "1.0.0",
        SourceProcessingPolicy,
        Path("source-processing-policy-domain-v1.json"),
    ),
)

DATA_CONTRACTS: Final = (
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
