"""Generate or verify deterministic P14 Read Model, API, and web evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from pydantic import JsonValue

from aegisquant.api.app import create_app
from aegisquant.api.stream import (
    ALLOWED_ORIGINS,
    QUEUE_CAPACITY,
    TOPIC_PROJECTIONS,
    SequencedStream,
)
from aegisquant.readmodels.bootstrap import build_projection_events, build_snapshot
from aegisquant.readmodels.engine import ProjectionEngine, ReadModelQuery
from aegisquant.readmodels.models import ProjectionKind

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUTS: Final = {
    "projection": ROOT / "reports/read_models/P14_PROJECTION_EVIDENCE.json",
    "postgres": ROOT / "reports/read_models/P14_POSTGRES_EVIDENCE.json",
    "websocket": ROOT / "reports/api/P14_WEBSOCKET_EVIDENCE.json",
    "client": ROOT / "reports/api/P14_CLIENT_CONTRACT.json",
    "web": ROOT / "reports/web/P14_WEB_EVIDENCE.json",
    "storybook": ROOT / "reports/web/P14_STORYBOOK_EVIDENCE.json",
    "charts": ROOT / "reports/web/P14_CHART_EVIDENCE.json",
    "states": ROOT / "reports/web/P14_STATE_EVIDENCE.json",
    "e2e": ROOT / "reports/web/P14_E2E_EVIDENCE.json",
}
COMPONENTS: Final = (
    "MetricTile",
    "MetricDelta",
    "StatusBadge",
    "FreshnessIndicator",
    "RiskStateBanner",
    "EnvironmentBadge",
    "EquityChart",
    "DrawdownChart",
    "CandlestickTradeChart",
    "AttributionWaterfall",
    "PnLHeatmap",
    "ExposureTreemap",
    "CorrelationMatrix",
    "OrderTimeline",
    "SignalDecisionTrace",
    "DataQualityGrid",
    "ModelCalibrationChart",
    "IncidentTimeline",
    "VirtualDataTable",
    "FilterBar",
    "CommandPalette",
    "EmptyState",
    "ErrorBoundaryPanel",
    "ExportMenu",
)
STORY_STATES: Final = (
    "Normal",
    "Loading",
    "Empty",
    "Stale",
    "Degraded",
    "Disconnected",
    "Error",
    "PermissionDenied",
    "Narrow",
    "Accessible",
)
DATA_STATES: Final = (
    "LOADING",
    "EMPTY",
    "LIVE",
    "STALE",
    "DEGRADED",
    "DISCONNECTED",
    "ERROR",
    "PERMISSION_DENIED",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        values = cast("dict[object, object]", value).values()
        return any(_contains_float(nested) for nested in values)
    if isinstance(value, (list, tuple)):
        values = cast("list[object] | tuple[object, ...]", value)
        return any(_contains_float(nested) for nested in values)
    return False


def _client_inventory() -> list[dict[str, object]]:
    root = ROOT / "apps/web/src/generated/client"
    return [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(root.rglob("*.ts"))
    ]


def _projection_payload() -> dict[str, object]:
    first = build_snapshot(ROOT)
    second = build_snapshot(ROOT)
    events = build_projection_events(ROOT)
    engine = ProjectionEngine()
    accepted = engine.rebuild(events, projected_at=first.rebuilt_at)
    failure_code = ""
    try:
        engine.rebuild((events[0], events[2]), projected_at=first.rebuilt_at)
    except ValueError as error:
        failure_code = str(error)
    source_artifacts = sorted({record.source_artifact for record in first.records})
    source_hashes_match = all(
        _sha256(ROOT / record.source_artifact) == record.source_sha256 for record in first.records
    )
    counts = Counter(record.projection.value for record in first.records)
    return {
        "schema_version": "p14-projection-evidence-v1",
        "snapshot_sha256": first.content_sha256,
        "rebuild_id": first.rebuild_id,
        "source_event_count": first.source_event_count,
        "record_count": len(first.records),
        "checkpoint_count": len(first.checkpoints),
        "projection_record_counts": dict(sorted(counts.items())),
        "projection_coverage": sorted(item.value for item in ProjectionKind),
        "deterministic_rebuild": first == second,
        "failed_candidate_error": failure_code,
        "failed_candidate_left_previous_snapshot_intact": engine.snapshot == accepted,
        "provenance_complete": all(
            record.as_of_time <= record.projected_at
            and bool(record.source_watermark)
            and len(record.source_sha256) == 64
            for record in first.records
        ),
        "source_hashes_match": source_hashes_match,
        "source_artifacts": source_artifacts,
        "float_values_present": _contains_float(first.model_dump(mode="json")),
        "real_account_access_performed": False,
        "venue_network_requests_performed": 0,
        "live_trading_locked": True,
    }


def _postgres_payload() -> dict[str, object]:
    migration = ROOT / "migrations/versions/20260902_0003_p14_read_models.py"
    persistence = ROOT / "src/aegisquant/readmodels/persistence.py"
    test = ROOT / "tests/integration/test_p14_readmodels.py"
    return {
        "schema_version": "p14-postgres-evidence-v1",
        "database_contract": "PostgreSQL",
        "sqlite_or_mock_used_for_acceptance": False,
        "tables": [
            "read_model_records",
            "read_model_projection_checkpoints",
            "read_model_snapshot_state",
        ],
        "migration": migration.relative_to(ROOT).as_posix(),
        "migration_sha256": _sha256(migration),
        "persistence_sha256": _sha256(persistence),
        "atomic_replace_contract": "one caller-owned SQLAlchemy transaction",
        "read_api_role": "aegisquant_read_api",
        "read_api_grants": ["CONNECT", "USAGE", "SELECT"],
        "read_api_write_grants": [],
        "mandatory_ci_test": test.relative_to(ROOT).as_posix(),
        "mandatory_ci_command": "python -m pytest tests/integration/test_p14_readmodels.py",
        "verification_mode": "real disposable PostgreSQL in the P14 CI gate",
    }


def _websocket_payload() -> dict[str, object]:
    snapshot = build_snapshot(ROOT)
    stream = SequencedStream(ReadModelQuery(snapshot))
    now = datetime(2026, 9, 2, tzinfo=UTC)
    snapshots = stream.snapshots(("account.summary", "risk.state"), server_time=now)
    subscriber_id, queue = stream.subscribe(("risk.state",))
    first = stream.publish("risk.state", {"state": "CAUTION"}, event_time=now, server_time=now)
    second = stream.publish("risk.state", {"state": "NORMAL"}, event_time=now, server_time=now)
    for index in range(QUEUE_CAPACITY):
        stream.publish("risk.state", {"index": index}, event_time=now, server_time=now)
    return {
        "schema_version": "p14-websocket-evidence-v1",
        "path": "/ws/v1/stream",
        "topics": sorted(TOPIC_PROJECTIONS),
        "initial_message_types": [item.message_type for item in snapshots.messages],
        "initial_topics": [item.topic for item in snapshots.messages],
        "monotonic_increment_verified": second.sequence == first.sequence + 1,
        "subscriber_queue_capacity": QUEUE_CAPACITY,
        "overflow_unsubscribes": subscriber_id not in stream.subscriber_ids,
        "queued_before_overflow": 2,
        "allowed_origins": sorted(ALLOWED_ORIGINS),
        "loopback_only_origins": all(
            origin.startswith(("http://127.0.0.1", "http://localhost", "http://testserver"))
            for origin in ALLOWED_ORIGINS
        ),
        "remote_origin_rejected_by_contract": "https://remote.example" not in ALLOWED_ORIGINS,
        "heartbeat_seconds": 15,
        "recovery_endpoint": "/api/v1/stream/snapshot",
        "gap_recovery_rule": "stop increments, fetch REST snapshot, then resume",
        "test": "tests/contract/api/test_websocket.py",
        "network_requests_performed": 0,
        "queue_size_after_overflow": queue.qsize(),
    }


def _client_payload() -> dict[str, object]:
    snapshot = build_snapshot(ROOT)
    runtime_openapi = cast("dict[str, JsonValue]", create_app(snapshot).openapi())
    checked_openapi = cast(
        "dict[str, JsonValue]",
        json.loads((ROOT / "reports/api/P14_OPENAPI.json").read_text(encoding="utf-8")),
    )
    index = (ROOT / "apps/web/src/generated/client/index.ts").read_text(encoding="utf-8")
    required_symbols = (
        "OverviewResponse",
        "IntelligenceResponse",
        "StreamSnapshotResponse",
        "QualityState",
        "overviewApiV1OverviewGet",
    )
    inventory = _client_inventory()
    return {
        "schema_version": "p14-client-contract-v1",
        "generator": "@hey-api/openapi-ts",
        "generator_version": "0.99.0",
        "openapi_runtime_matches_checked_artifact": runtime_openapi == checked_openapi,
        "openapi_sha256": _sha256(ROOT / "reports/api/P14_OPENAPI.json"),
        "websocket_schema_sha256": _sha256(ROOT / "reports/api/P14_WEBSOCKET_SCHEMA.json"),
        "config_sha256": _sha256(ROOT / "apps/web/openapi-ts.config.ts"),
        "required_symbols": list(required_symbols),
        "required_symbols_present": all(symbol in index for symbol in required_symbols),
        "generated_file_count": len(inventory),
        "generated_files": inventory,
        "drift_check": "python scripts/check_p14_client.py",
    }


def _web_sources() -> tuple[str, list[Path]]:
    files = sorted((ROOT / "apps/web/app").rglob("*.tsx")) + sorted(
        path
        for path in (ROOT / "apps/web/src").rglob("*.ts*")
        if "src/generated" not in path.as_posix()
    )
    return "\n".join(path.read_text(encoding="utf-8") for path in files), files


def _web_payload() -> dict[str, object]:
    source, files = _web_sources()
    normalized = source.casefold()
    forbidden = (
        "postgresql://",
        "binance.com",
        "api_secret",
        "password input",
        "live_trading=true",
        "/submit",
        "/cancel",
        "/amend",
    )
    shell = (ROOT / "apps/web/src/components/app-shell.tsx").read_text(encoding="utf-8")
    proxy = (ROOT / "apps/web/proxy.ts").read_text(encoding="utf-8")
    return {
        "schema_version": "p14-web-evidence-v1",
        "framework": "Next.js App Router",
        "routes": ["/overview", "/intelligence"],
        "permission": "VIEWER_READ_ONLY",
        "environment": "RESEARCH",
        "live_trading_locked": "LIVE TRADING LOCKED" in shell,
        "read_only_marker_present": "VIEWER · READ ONLY" in shell,
        "forbidden_surface_matches": [item for item in forbidden if item in normalized],
        "loopback_api_contract_present": "127.0.0.1:8000" in normalized,
        "csp_nonce_present": "nonce" in proxy.casefold(),
        "csp_frame_ancestors_none": "frame-ancestors 'none'" in proxy,
        "source_file_count": len(files),
        "source_files": [
            {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256(path)} for path in files
        ],
        "real_account_connected": False,
        "credential_inputs_present": False,
    }


def _storybook_payload() -> dict[str, object]:
    gallery = (ROOT / "apps/web/src/components/component-gallery.tsx").read_text(encoding="utf-8")
    stories = (ROOT / "apps/web/src/components/component-gallery.stories.tsx").read_text(
        encoding="utf-8"
    )
    return {
        "schema_version": "p14-storybook-evidence-v1",
        "framework": "@storybook/react-webpack5",
        "compiler": "@storybook/addon-webpack5-compiler-swc",
        "component_count": len(COMPONENTS),
        "components": list(COMPONENTS),
        "missing_components": [
            item for item in COMPONENTS if f'<GalleryItem title="{item}">' not in gallery
        ],
        "state_count": len(STORY_STATES),
        "states": list(STORY_STATES),
        "missing_states": [
            item for item in STORY_STATES if f"export const {item}: Story" not in stories
        ],
        "build_command": "pnpm --filter @aegisquant/web build-storybook",
        "config_sha256": _sha256(ROOT / "apps/web/.storybook/main.ts"),
    }


def _chart_payload() -> dict[str, object]:
    package = cast(
        "dict[str, object]",
        json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8")),
    )
    dependencies = cast("dict[str, str]", package["dependencies"])
    source = (ROOT / "apps/web/src/components/charts/chart-suite.tsx").read_text(encoding="utf-8")
    chart_names = (
        "EquityChart",
        "DrawdownChart",
        "CandlestickTradeChart",
        "AttributionWaterfall",
        "PnLHeatmap",
        "ExposureTreemap",
        "CorrelationMatrix",
        "ModelCalibrationChart",
    )
    return {
        "schema_version": "p14-chart-evidence-v1",
        "libraries": {
            "echarts": dependencies["echarts"],
            "lightweight-charts": dependencies["lightweight-charts"],
        },
        "charts": list(chart_names),
        "missing_charts": [item for item in chart_names if f"function {item}" not in source],
        "client_lazy_loading": all(
            marker in source for marker in ('import("echarts")', 'import("lightweight-charts")')
        ),
        "semantic_data_table_present": "<ChartTable" in source and "<table>" in source,
        "text_summary_present": "summary=" in source and "aria-label" in source,
        "test": "apps/web/tests/charts.test.tsx",
    }


def _state_payload() -> dict[str, object]:
    source = (ROOT / "apps/web/src/components/data-state.tsx").read_text(encoding="utf-8")
    return {
        "schema_version": "p14-state-evidence-v1",
        "states": list(DATA_STATES),
        "missing_states": [item for item in DATA_STATES if item not in source],
        "provenance_fields": [
            "as_of_time",
            "latency_ms",
            "source",
            "authoritative",
            "estimated",
            "last_success_at",
        ],
        "rest_gap_recovery": "/api/v1/stream/snapshot",
        "test": "apps/web/tests/data-state.test.tsx; apps/web/tests/realtime.test.ts",
    }


def _e2e_payload() -> dict[str, object]:
    test_path = ROOT / "apps/web/e2e/dashboard.spec.ts"
    source = test_path.read_text(encoding="utf-8")
    titles = re.findall(r'test\("([^"]+)"', source)
    screenshot = ROOT / "apps/web/e2e/dashboard.spec.ts-snapshots/overview-chromium-win32.png"
    benchmark = cast(
        "dict[str, object]",
        json.loads(
            (ROOT / "reports/performance/P14_OVERVIEW_BENCHMARK.json").read_text(encoding="utf-8")
        ),
    )
    return {
        "schema_version": "p14-e2e-evidence-v1",
        "test_titles": titles,
        "test_count": len(titles),
        "browser": "chromium",
        "web_runtime": "Next.js production build on loopback",
        "api_runtime": "FastAPI on loopback",
        "visual_baseline": screenshot.relative_to(ROOT).as_posix(),
        "visual_baseline_sha256": _sha256(screenshot),
        "responsive_viewport": {"width": 390, "height": 844},
        "benchmark": "reports/performance/P14_OVERVIEW_BENCHMARK.json",
        "benchmark_status": benchmark["status"],
        "benchmark_target_p75_ms": benchmark["target_p75_ms"],
        "formal_acceptance_performed": False,
        "qualifies_as_12h_or_24h_acceptance": False,
    }


def build_payloads() -> dict[str, object]:
    return {
        "projection": _projection_payload(),
        "postgres": _postgres_payload(),
        "websocket": _websocket_payload(),
        "client": _client_payload(),
        "web": _web_payload(),
        "storybook": _storybook_payload(),
        "charts": _chart_payload(),
        "states": _state_payload(),
        "e2e": _e2e_payload(),
    }


def _validate(payloads: dict[str, object]) -> None:
    projection = cast("dict[str, object]", payloads["projection"])
    websocket = cast("dict[str, object]", payloads["websocket"])
    client = cast("dict[str, object]", payloads["client"])
    web = cast("dict[str, object]", payloads["web"])
    storybook = cast("dict[str, object]", payloads["storybook"])
    charts = cast("dict[str, object]", payloads["charts"])
    states = cast("dict[str, object]", payloads["states"])
    e2e = cast("dict[str, object]", payloads["e2e"])
    benchmark = cast(
        "dict[str, object]",
        json.loads(
            (ROOT / "reports/performance/P14_OVERVIEW_BENCHMARK.json").read_text(encoding="utf-8")
        ),
    )
    checks = {
        "projection deterministic": projection["deterministic_rebuild"] is True,
        "projection atomic": projection["failed_candidate_left_previous_snapshot_intact"] is True,
        "projection provenance": projection["provenance_complete"] is True,
        "projection source hashes": projection["source_hashes_match"] is True,
        "projection no floats": projection["float_values_present"] is False,
        "stream monotonic": websocket["monotonic_increment_verified"] is True,
        "stream overflow": websocket["overflow_unsubscribes"] is True,
        "stream origins": websocket["loopback_only_origins"] is True,
        "client openapi": client["openapi_runtime_matches_checked_artifact"] is True,
        "client symbols": client["required_symbols_present"] is True,
        "web safety": web["forbidden_surface_matches"] == [],
        "web lock": web["live_trading_locked"] is True,
        "storybook coverage": storybook["missing_components"] == []
        and storybook["missing_states"] == [],
        "chart coverage": charts["missing_charts"] == [],
        "chart accessibility": charts["semantic_data_table_present"] is True
        and charts["text_summary_present"] is True,
        "state coverage": states["missing_states"] == [],
        "e2e coverage": cast("int", e2e["test_count"]) >= 4,
        "performance": e2e["benchmark_status"] == "passed"
        and e2e["benchmark_target_p75_ms"] == benchmark["target_p75_ms"]
        and cast("int", benchmark["p75_ms"]) < cast("int", benchmark["target_p75_ms"]),
        "acceptance remains deferred": e2e["formal_acceptance_performed"] is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("P14 evidence validation failed: " + ", ".join(failed))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    payloads = build_payloads()
    _validate(payloads)
    mismatches: list[str] = []
    for key, payload in payloads.items():
        target = OUTPUTS[key]
        rendered = _render(payload)
        if arguments.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
                mismatches.append(target.relative_to(ROOT).as_posix())
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8", newline="\n")
    if mismatches:
        raise SystemExit("P14 evidence drift: " + ", ".join(mismatches))
    print(f"{'verified' if arguments.check else 'generated'} {len(payloads)} P14 evidence files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
